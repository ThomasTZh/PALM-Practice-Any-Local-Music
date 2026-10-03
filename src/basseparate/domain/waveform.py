"""Waveform pyramid cache models (M1.8).

A *waveform cache* stores signed min/max extrema for every canonical
channel of a PCM asset, as a pyramid of buckets:

- Level 0 buckets cover 64 sample frames; each higher level aggregates
  groups of four of the level below (256, 1024, 4096, ... frames).
- Buckets are grouped into tiles of 4096 buckets; the coarsest level is
  the first whose bucket count fits one tile.
- Values are float32 little-endian: each bucket holds, per channel, a
  signed minimum and maximum.

The on-disk manifest is the source of truth for progressive tile
availability while a WAVEFORM job runs; the database row pins the final
cache to its canonical asset. The worker never touches the database
(M1.4 boundary) — it writes tile and manifest files only.

Cache layout (relative to the storage root)::

    cache/waveforms/<source_hash>/manifest.json
    cache/waveforms/<source_hash>/level_<L>/tile_<N>.bin
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import (
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)

WAVEFORM_CACHE_VERSION = 1
BASE_BUCKET_FRAMES = 64
AGGREGATION = 4
TILE_BUCKETS = 4096

MAX_CHANNEL_COUNT = 8


class WaveformLevelSummary(BaseModel):
    """Bucket/tile geometry of one pyramid level."""

    model_config = ConfigDict(frozen=True)

    bucket_frame_count: int = Field(ge=1, description="Sample frames covered by one bucket")
    bucket_count: int = Field(ge=1, description="Buckets at this level (last may be partial)")
    tile_count: int = Field(ge=1)
    final_tile_buckets: int = Field(
        ge=1, le=TILE_BUCKETS, description="Buckets in the level's last (possibly partial) tile"
    )


class WaveformManifest(BaseModel):
    """On-disk cache manifest (atomic rewrites; progressive availability).

    ``available_tiles`` maps level index (string) to a sorted list of
    inclusive ``[first, last]`` completed-tile ranges. ``final`` is true
    only once every level's last tile is published.
    """

    model_config = ConfigDict(frozen=True)

    cache_version: int = Field(ge=1)
    source_hash: Sha256Hash
    sample_rate: SampleRate
    frame_count: SamplePosition = Field(ge=1)
    channel_count: int = Field(ge=1, le=MAX_CHANNEL_COUNT)
    base_bucket_frames: int = Field(default=BASE_BUCKET_FRAMES, ge=1)
    aggregation: int = Field(default=AGGREGATION, ge=2)
    levels: list[WaveformLevelSummary] = Field(min_length=1)
    available_tiles: dict[str, list[list[int]]] = Field(default_factory=dict)
    final: bool = False


class WaveformResult(BaseModel):
    """Validated outcome of a WAVEFORM job (worker → publisher).

    ``manifest_path`` is the absolute path of the final manifest; the
    publisher converts it to a storage-relative path when registering the
    cache row.
    """

    model_config = ConfigDict(frozen=True)

    cache_version: int = Field(ge=1)
    source_hash: Sha256Hash
    sample_rate: SampleRate
    frame_count: SamplePosition = Field(ge=1)
    channel_count: int = Field(ge=1, le=MAX_CHANNEL_COUNT)
    final_bucket_frames: int = Field(
        ge=1,
        le=BASE_BUCKET_FRAMES,
        description="True sample frames in the level-0 last bucket (spec §10.2.9)",
    )
    levels: list[WaveformLevelSummary] = Field(min_length=1)
    manifest_path: str = Field(min_length=1, description="Absolute path of the final manifest")


class WaveformCacheRecord(BaseModel):
    """Database row pinning a completed waveform cache to its asset."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    asset_id: Uuid
    cache_version: int = Field(ge=1)
    source_hash: Sha256Hash
    sample_rate: SampleRate
    frame_count: SamplePosition = Field(ge=1)
    channel_count: int = Field(ge=1, le=MAX_CHANNEL_COUNT)
    levels: tuple[WaveformLevelSummary, ...] = Field(min_length=1)
    manifest_path: str = Field(
        min_length=1, description="Storage-relative, e.g. 'cache/waveforms/<hash>/manifest.json'"
    )
    created_at: UtcTimestamp


def expected_levels(frame_count: int) -> list[WaveformLevelSummary]:
    """Pyramid geometry for ``frame_count`` (spec §10.1).

    Level L buckets cover ``BASE_BUCKET_FRAMES · AGGREGATION**L`` frames;
    the coarsest level is the first whose bucket count fits one tile.
    """
    if frame_count < 1:
        raise ValueError("frame_count must be >= 1")
    levels: list[WaveformLevelSummary] = []
    bucket_frames = BASE_BUCKET_FRAMES
    while True:
        bucket_count = math.ceil(frame_count / bucket_frames)
        tile_count = math.ceil(bucket_count / TILE_BUCKETS)
        final_tile_buckets = bucket_count - (tile_count - 1) * TILE_BUCKETS
        levels.append(
            WaveformLevelSummary(
                bucket_frame_count=bucket_frames,
                bucket_count=bucket_count,
                tile_count=tile_count,
                final_tile_buckets=final_tile_buckets,
            )
        )
        if bucket_count <= TILE_BUCKETS:
            break
        bucket_frames *= AGGREGATION
    return levels


def tile_byte_count(buckets: int, channel_count: int) -> int:
    """Bytes of a tile holding ``buckets`` (per-channel min/max, f32le)."""
    if buckets < 1 or not 1 <= channel_count <= MAX_CHANNEL_COUNT:
        raise ValueError("invalid bucket/channel count")
    return buckets * channel_count * 2 * 4


def validate_manifest(manifest: WaveformManifest, *, source_hash: str) -> None:
    """Verify a parsed manifest against its expectations (spec §10.4).

    Raises ``ValueError`` on any mismatch: cache version, source hash,
    level geometry, or an inconsistent availability map.
    """
    if manifest.cache_version != WAVEFORM_CACHE_VERSION:
        raise ValueError(f"unsupported cache version {manifest.cache_version}")
    if manifest.source_hash != source_hash:
        raise ValueError("manifest source hash mismatch")
    if manifest.base_bucket_frames != BASE_BUCKET_FRAMES:
        raise ValueError("unexpected base bucket size")
    if manifest.aggregation != AGGREGATION:
        raise ValueError("unexpected aggregation factor")
    if manifest.levels != expected_levels(manifest.frame_count):
        raise ValueError("level geometry does not match the frame count")
    for index, level in enumerate(manifest.levels):
        key = str(index)
        ranges = manifest.available_tiles.get(key, [])
        if key not in manifest.available_tiles:
            continue
        if not _is_valid_range_list(ranges, level.tile_count):
            raise ValueError(f"invalid availability ranges for level {index}")
        if manifest.final and sum(end - start + 1 for start, end in ranges) != level.tile_count:
            raise ValueError(f"final manifest is missing tiles at level {index}")


def _is_valid_range_list(ranges: list[list[int]], tile_count: int) -> bool:
    previous_end = -1
    for pair in ranges:
        if len(pair) != 2:
            return False
        start, end = pair
        if start > end or start < 0 or end >= tile_count:
            return False
        if start <= previous_end:
            return False
        previous_end = end
    return True
