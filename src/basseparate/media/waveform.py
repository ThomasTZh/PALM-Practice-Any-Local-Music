"""Waveform pyramid generator (M1.8).

Streaming min/max extrema over a canonical PCM asset (interleaved
little-endian float32). The engine reads the source in bounded blocks,
carries incomplete base buckets between blocks, aggregates groups of four
buckets per level, and publishes each completed tile atomically
(tmp + fsync + rename) followed by an atomic manifest rewrite — so
completed regions are always visible and never partial (spec §10.2–10.3).

Incomplete buckets are never zero-padded: partial buckets keep their true
sample count and their extrema are computed over the real samples only
(spec §10.2). On cancellation or failure the whole cache directory is
removed — a failed run leaves no partial cache behind.

Memory is bounded: one input block (default 4 MiB) plus per-level partial
bucket buffers (≤ TILE_BUCKETS + AGGREGATION − 1 buckets), far below the
256 MiB worker bound (spec §10.5).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import numpy as np

from basseparate.domain.waveform import (
    AGGREGATION,
    BASE_BUCKET_FRAMES,
    TILE_BUCKETS,
    WAVEFORM_CACHE_VERSION,
    WaveformManifest,
    expected_levels,
)

DEFAULT_BLOCK_BYTES = 4 * 1024 * 1024
_READ_HEADROOM = 1 << 20  # read a little extra so blocks end on frame boundaries


class WaveformError(Exception):
    """Base error for waveform cache generation."""


class WaveformFailedError(WaveformError):
    """The cache could not be generated (bad input, I/O, hash mismatch)."""


class WaveformCancelledError(WaveformError):
    """The job was cancelled while the cache was being generated."""


def validate_tile_bytes(data: bytes, expected_len: int, channel_count: int) -> None:
    """Verify one decoded tile (spec §10.4).

    Checks the exact byte length, finiteness of every value, and
    ``minimum ≤ maximum`` per channel per bucket. Raises ``ValueError``.
    """
    if len(data) != expected_len:
        raise ValueError(f"tile length {len(data)} != expected {expected_len}")
    if expected_len == 0 or expected_len % (channel_count * 8) != 0:
        raise ValueError("tile length is not a whole number of buckets")
    values = np.frombuffer(data, dtype="<f4")
    if not np.isfinite(values).all():
        raise ValueError("tile contains non-finite extrema")
    buckets = values.reshape(-1, channel_count, 2)  # (bucket, channel, [min, max])
    if not (buckets[..., 0] <= buckets[..., 1]).all():
        raise ValueError("tile contains minimum > maximum")


def _per_bucket_minmax(samples: np.ndarray, bucket_frames: int, channels: int) -> np.ndarray:
    """(buckets, channels, 2) f32 min/max over complete buckets."""
    shaped = samples.reshape(-1, bucket_frames, channels)
    return np.stack([shaped.min(axis=1), shaped.max(axis=1)], axis=-1)


class _LevelState:
    """Bounded carry buffer and bookkeeping for one level.

    ``buffer`` holds the last ``total % TILE_BUCKETS`` buckets (the carry
    window for the next tiles). ``aggregated`` counts the buckets already
    folded into the level above — always a multiple of AGGREGATION and
    within three of ``total`` — so each bucket is aggregated exactly once
    even though the carry window is re-presented every block.
    """

    __slots__ = ("buffer", "total", "aggregated", "tiles_written", "ranges")

    def __init__(self) -> None:
        self.buffer: np.ndarray | None = None  # (n, channels, 2) f32
        self.total: int = 0
        self.aggregated: int = 0
        self.tiles_written: int = 0
        self.ranges: list[list[int]] = []  # inclusive [first, last] tile ranges

    def append(self, buckets: np.ndarray) -> None:
        if self.buffer is None:
            self.buffer = buckets
        else:
            self.buffer = np.concatenate([self.buffer, buckets], axis=0)
        self.total += len(buckets)

    def add_range(self, tile_index: int) -> None:
        if self.ranges and self.ranges[-1][1] + 1 == tile_index:
            self.ranges[-1][1] = tile_index
        else:
            self.ranges.append([tile_index, tile_index])


def build_waveform_cache(
    source_path: Path,
    cache_dir: Path,
    *,
    source_hash: str,
    sample_rate: int,
    frame_count: int,
    channel_count: int,
    block_bytes: int = DEFAULT_BLOCK_BYTES,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> WaveformManifest:
    """Build the full pyramid cache for one canonical PCM asset.

    Returns the final manifest. On cancellation or failure the cache
    directory is removed and the corresponding ``WaveformError`` is
    raised.
    """
    if frame_count < 1:
        raise WaveformFailedError("frame_count must be >= 1")
    if not 1 <= channel_count <= 8:
        raise WaveformFailedError("channel_count must be 1..8")
    frame_bytes = channel_count * 4
    if block_bytes < frame_bytes:
        raise WaveformFailedError("block_bytes must cover at least one frame")

    levels = expected_levels(frame_count)
    # Cap the chunk so a single feed adds at most TILE_BUCKETS - AGGREGATION
    # level-0 buckets: then at most one tile completes per feed per level,
    # and every tile/aggregation slice stays inside the carry window.
    max_chunk_frames = (TILE_BUCKETS - AGGREGATION) * BASE_BUCKET_FRAMES
    chunk_frames = min(max(1, (block_bytes + _READ_HEADROOM) // frame_bytes), max_chunk_frames)
    chunk_bytes = chunk_frames * frame_bytes

    cache_dir.mkdir(parents=True, exist_ok=True)
    for index in range(len(levels)):
        (cache_dir / f"level_{index}").mkdir(exist_ok=True)
    manifest_path = cache_dir / "manifest.json"

    state = [_LevelState() for _ in levels]
    hasher = hashlib.sha256()
    carried: np.ndarray = np.zeros(0, dtype="<f4")
    processed_frames = 0

    def fail(exc: WaveformError) -> NoReturn:
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise exc

    def write_manifest(final: bool) -> None:
        manifest = WaveformManifest(
            cache_version=WAVEFORM_CACHE_VERSION,
            source_hash=source_hash,
            sample_rate=sample_rate,
            frame_count=frame_count,
            channel_count=channel_count,
            levels=levels,
            available_tiles={
                str(index): [list(r) for r in level.ranges] for index, level in enumerate(state)
            },
            final=final,
        )
        _atomic_write(manifest_path, manifest.model_dump_json().encode("utf-8"))

    def feed(buckets: np.ndarray) -> None:
        """Push level-0 buckets through aggregation and tile publication.

        Aggregation (groups of four upward) and tiling (4096 across) are
        independent projections over the bucket stream. Each level's carry
        window keeps only the last ``total % TILE_BUCKETS`` buckets, so the
        ``aggregated`` counter records which buckets have already been
        folded upward — each bucket is aggregated exactly once, and the
        chunk cap guarantees every tile slice and aggregation slice stays
        inside the pre-truncation window.
        """
        state[0].append(buckets)
        published = False
        for index in range(len(levels)):
            level = state[index]
            count = level.total
            window = level.buffer
            if count == 0 or window is None:
                continue
            window_start = count - len(window)
            if index + 1 < len(levels):
                n_groups = (count - level.aggregated) // AGGREGATION
                if n_groups:
                    start = count - n_groups * AGGREGATION
                    state[index + 1].append(_aggregate(window[start - window_start :]))
                    level.aggregated += n_groups * AGGREGATION
            while level.tiles_written < count // TILE_BUCKETS:
                start = level.tiles_written * TILE_BUCKETS
                _write_tile(
                    cache_dir,
                    index,
                    level.tiles_written,
                    window[start - window_start : start - window_start + TILE_BUCKETS],
                )
                level.tiles_written += 1
                level.add_range(level.tiles_written - 1)
                published = True
            tail = count % TILE_BUCKETS
            level.buffer = window[-tail:] if tail else None
        if published:
            write_manifest(final=False)

    def _aggregate(groups: np.ndarray) -> np.ndarray:
        # (n_groups · 4, channels, 2) → (n_groups, channels, 2):
        # min of the mins, max of the maxs, over each group of four buckets.
        total, channels, _ = groups.shape
        shaped = groups.reshape(total // AGGREGATION, AGGREGATION, channels, 2)
        return np.stack([shaped[..., 0].min(axis=1), shaped[..., 1].max(axis=1)], axis=-1)

    def _flush_partial_group(buckets: np.ndarray) -> np.ndarray:
        # (n, channels, 2), 1 ≤ n < AGGREGATION → (1, channels, 2):
        # the EOF flush of a final incomplete group (spec §10.2.8).
        return np.stack(
            [buckets[..., 0].min(axis=0), buckets[..., 1].max(axis=0)], axis=-1
        )[None, ...]

    try:
        with source_path.open("rb") as handle:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise WaveformCancelledError("waveform generation cancelled")
                chunk = handle.read(chunk_bytes)
                if not chunk:
                    break
                hasher.update(chunk)
                processed_frames += len(chunk) // frame_bytes
                samples = np.frombuffer(chunk, dtype="<f4")
                if carried.size:
                    samples = np.concatenate([carried, samples])
                complete = (len(samples) // (BASE_BUCKET_FRAMES * channel_count)) * (
                    BASE_BUCKET_FRAMES * channel_count
                )
                carried = samples[complete:]
                if complete:
                    feed(_per_bucket_minmax(samples[:complete], BASE_BUCKET_FRAMES, channel_count))
                if on_progress is not None:
                    on_progress(min(1.0, processed_frames / frame_count))
        if len(carried):
            partial = carried.reshape(-1, channel_count)
            feed(
                np.stack([partial.min(axis=0), partial.max(axis=0)], axis=-1).reshape(
                    1, channel_count, 2
                )
            )
        # Bottom-up: flush each level's unaggregated tail group (its last
        # ``total - aggregated`` buckets, fewer than AGGREGATION) as one
        # partial bucket at the level above (spec §10.2.8). This keeps
        # every level's bucket total at ceil(frame_count / bucket size).
        # The carry stays intact — the next pass publishes it as the
        # level's final tile.
        for index in range(len(levels) - 1):
            level = state[index]
            unaggregated = level.total - level.aggregated
            if unaggregated and level.buffer is not None:
                state[index + 1].append(_flush_partial_group(level.buffer[-unaggregated:]))
        # Final partial tiles at every level (immutable once the stream ends).
        for index, level in enumerate(state):
            if level.buffer is not None and len(level.buffer):
                _write_tile(cache_dir, index, level.tiles_written, level.buffer)
                level.tiles_written += 1
                level.add_range(level.tiles_written - 1)
                level.buffer = None
        if hasher.hexdigest() != source_hash:
            raise WaveformFailedError("source hash mismatch")
        if processed_frames != frame_count:
            raise WaveformFailedError(
                f"processed {processed_frames} frames, expected {frame_count}"
            )
        write_manifest(final=True)
        return WaveformManifest(
            cache_version=WAVEFORM_CACHE_VERSION,
            source_hash=source_hash,
            sample_rate=sample_rate,
            frame_count=frame_count,
            channel_count=channel_count,
            levels=levels,
            available_tiles={
                str(index): [list(r) for r in level.ranges] for index, level in enumerate(state)
            },
            final=True,
        )
    except WaveformError as exc:
        fail(exc)
    except OSError as exc:
        fail(WaveformFailedError(f"waveform generation I/O error: {exc}"))


def _write_tile(cache_dir: Path, level: int, tile_index: int, buckets: np.ndarray) -> None:
    """Atomically publish one tile (immutable once renamed)."""
    data = np.ascontiguousarray(buckets, dtype="<f4").tobytes()
    target_dir = cache_dir / f"level_{level}"
    name = f"tile_{tile_index:06d}.bin"
    _atomic_write(target_dir / name, data)


def _atomic_write(target: Path, data: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(target)
