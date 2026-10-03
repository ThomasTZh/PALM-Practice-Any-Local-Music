"""Canonical audio decode (M1.5).

Decodes the selected audio stream of a completed upload to interleaved
little-endian float32 raw PCM in a staging file, then validates the result
in a single chunked pass.

Decode command (verified against FFmpeg 8.1; see the M1.5 research notes in
``docs/implementation-status.md``)::

    ffmpeg -hide_banner -nostdin -v warning -threads N -i <source>
        -map 0:<global_stream_index>
        -af aresample=async=1
        -c:a pcm_f32le -f f32le
        -progress pipe:2 <staging.pcm>

Design notes:
- No ``-ar`` / ``-ac``: sample rate, channel count, and layout are preserved.
- No ``-ss`` / ``-t``: no trimming. The time origin is the decoded stream
  start after the decoder's priming/padding (milestone1.md §7.3).
- ``aresample=async=1`` (filling and trimming): timestamp gaps are padded
  with silence, overlaps are trimmed, no gradual speed correction. Timing
  repair is detected arithmetically by comparing the decoded duration with
  the probe's estimated duration (the resampler's own log lines are
  AV_LOG_VERBOSE and not visible at ``-v warning``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from basseparate.domain.common import Sha256Hash
from basseparate.domain.representation import CanonicalDecodeResult
from basseparate.media._process import (
    SubprocessOutputError,
)
from basseparate.media._process import (
    kill as _kill,
)
from basseparate.media._process import (
    terminate_gracefully as _terminate_gracefully,
)
from basseparate.media._process import (
    wait_for_cancel as _wait_for_cancel,
)
from basseparate.media.probe import tool_versions

DEFAULT_DECODE_TIMEOUT_SECONDS = 1800.0
MAX_DECODE_STDERR_BYTES = 10 * 1024 * 1024  # 10 MiB
DISK_HEADROOM_FACTOR = 1.25
MINIMUM_FREE_DISK_BYTES = 64 * 1024 * 1024  # 64 MiB floor
VALIDATION_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MiB (multiple of 4)
MAX_DECODER_WARNINGS = 20
TIMING_REPAIR_TOLERANCE_SECONDS = 0.5
PROGRESS_MIN_INTERVAL_SECONDS = 0.25

#: The production resampler config: gaps -> silence padding, overlaps -> trim.
DISCONTINUITY_FILTER = "aresample=async=1"

_PROGRESS_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

_MIME_BY_FORMAT: dict[str, str] = {
    "wav": "audio/wav",
    "wave": "audio/wav",
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "aac": "audio/aac",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "mov": "audio/quicktime",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "flac": "audio/flac",
    "alac": "audio/m4a",
    "webm": "audio/webm",
    "matroska": "audio/matroska",
    "mkv": "audio/matroska",
    "ts": "video/mp2t",
    "mpegts": "video/mp2t",
}


def mime_type_for_format(format_name: str) -> str:
    """Best-effort MIME type for an ffprobe ``format_name``.

    ffprobe names are comma-separated ("matroska,webm"); the first token is
    the primary muxer. Unknown formats get a generic type.
    """
    if not format_name:
        return "application/octet-stream"
    key = format_name.split(",")[0].strip().lower()
    return _MIME_BY_FORMAT.get(key, "application/octet-stream")


class DecodeError(Exception):
    """Base class for decode failures."""


class DecodeFailedError(DecodeError):
    """ffmpeg could not run, exited nonzero, or produced unusable output."""


class DecodeTimeoutError(DecodeError):
    """The decode did not finish within the allowed time."""


class DecodeCancelledError(DecodeError):
    """The decode was cancelled before it completed."""


class EmptyAudioError(DecodeError):
    """The decoded stream contains no samples."""


class NonFiniteSamplesError(DecodeError):
    """The decoded stream contains NaN or infinite samples."""


class InsufficientDiskSpaceError(DecodeError):
    """Not enough free disk space for the expected decode output."""


@dataclass(frozen=True)
class DecodeProgress:
    """One decode progress report (determinate when ``fraction`` is set)."""

    out_time_seconds: float
    dup_frames: int
    drop_frames: int
    fraction: float | None = None


def parse_progress_line(line: str) -> tuple[str, str] | None:
    """Parse an ``key=value`` progress line; None for non-progress lines."""
    match = _PROGRESS_KEY_RE.match(line)
    if match is None:
        return None
    key, value = match.group(1), match.group(2).strip()
    if not value:
        return None
    return key, value


def _required_free_bytes(
    estimated_duration_seconds: float | None,
    sample_rate: int,
    channel_count: int,
) -> int:
    expected = 0
    if estimated_duration_seconds is not None:
        expected = int(estimated_duration_seconds * sample_rate * channel_count * 4)
    return max(int(expected * DISK_HEADROOM_FACTOR), MINIMUM_FREE_DISK_BYTES)


def _check_disk_space(output_path: Path, required_bytes: int) -> None:
    probe_dir = output_path.parent
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    usage = shutil.disk_usage(probe_dir)
    if usage.free < required_bytes:
        raise InsufficientDiskSpaceError(
            f"need ~{required_bytes // (1024 * 1024)} MiB free for the decode "
            f"but only {usage.free // (1024 * 1024)} MiB are available"
        )


def check_frame_alignment(size: int, channel_count: int) -> int:
    """Return the decoded frame count, or raise when the size is misaligned.

    The decoded byte count must be a multiple of ``channel_count * 4``
    (one float32 per channel per frame); anything else means the stream
    structure was not preserved.
    """
    frame_bytes = channel_count * 4
    if size % frame_bytes != 0:
        raise DecodeFailedError(
            f"decoded PCM size {size} is not a multiple of {frame_bytes} bytes "
            f"({channel_count} channels x 4); stream structure not preserved"
        )
    return size // frame_bytes


def duration_discrepancy_warnings(
    decoded_duration_seconds: float,
    estimated_duration_seconds: float | None,
) -> tuple[float | None, list[str]]:
    """Compare decoded vs container-estimated duration.

    Returns ``(discrepancy, warnings)``. A discrepancy beyond
    ``TIMING_REPAIR_TOLERANCE_SECONDS`` means the resampler padded gaps with
    silence (positive) or trimmed overlaps (negative).
    """
    if estimated_duration_seconds is None:
        return None, []
    discrepancy = decoded_duration_seconds - estimated_duration_seconds
    if abs(discrepancy) <= TIMING_REPAIR_TOLERANCE_SECONDS:
        return discrepancy, []
    if discrepancy > 0:
        return discrepancy, [
            f"decoded duration is {discrepancy:.2f}s longer than the container "
            f"estimate (timestamp gaps were padded with silence)"
        ]
    return discrepancy, [
        f"decoded duration is {-discrepancy:.2f}s shorter than the container "
        f"estimate (timestamp overlaps were trimmed)"
    ]


def validate_pcm(path: Path, channel_count: int) -> tuple[str, float]:
    """Single chunked pass over a PCM file: SHA-256 + finiteness + max amplitude.

    ``path`` must be nonzero and its size a multiple of ``channel_count * 4``
    (the frame alignment is checked by the caller). Returns
    ``(content_hash, max_amplitude)``. Raises ``NonFiniteSamplesError`` when
    any sample is NaN or infinite.
    """
    if path.stat().st_size % 4 != 0:
        raise DecodeFailedError(
            f"PCM size {path.stat().st_size} is not a multiple of 4 bytes"
        )
    digest = hashlib.sha256()
    max_amplitude = 0.0
    with path.open("rb") as handle:
        while chunk := handle.read(VALIDATION_CHUNK_BYTES):
            digest.update(chunk)
            # Every chunk is 4-byte aligned: the chunk size is a multiple of 4
            # and the total size is a multiple of channel_count * 4.
            samples = np.frombuffer(chunk, dtype="<f4")
            if not bool(np.isfinite(samples).all()):
                raise NonFiniteSamplesError("decoded audio contains non-finite samples")
            max_amplitude = max(max_amplitude, float(np.max(np.abs(samples))))
    return digest.hexdigest(), max_amplitude


@dataclass
class _ProgressState:
    estimated_seconds: float | None
    on_progress: Callable[[DecodeProgress], None] | None
    last_emit: float = field(default=0.0)
    out_time_us: int | None = None
    dup_frames: int = 0
    drop_frames: int = 0
    warnings: list[str] = field(default_factory=list)

    def handle_line(self, line: str, now: float) -> None:
        parsed = parse_progress_line(line)
        if parsed is None:
            stripped = line.strip()
            if stripped and len(self.warnings) < MAX_DECODER_WARNINGS:
                self.warnings.append(stripped[:500])
            return
        key, value = parsed
        if key == "out_time_us":
            with contextlib.suppress(ValueError):
                self.out_time_us = int(value)
        elif key == "dup_frames":
            with contextlib.suppress(ValueError):
                self.dup_frames = int(value)
        elif key == "drop_frames":
            with contextlib.suppress(ValueError):
                self.drop_frames = int(value)
        elif key == "progress":
            self._emit(now, is_final=value == "end")

    def _emit(self, now: float, is_final: bool) -> None:
        if self.out_time_us is None or self.on_progress is None:
            return
        if not is_final and now - self.last_emit < PROGRESS_MIN_INTERVAL_SECONDS:
            return
        self.last_emit = now
        out_time = self.out_time_us / 1_000_000
        fraction: float | None = None
        if self.estimated_seconds and self.estimated_seconds > 0:
            fraction = min(1.0, out_time / self.estimated_seconds)
        self.on_progress(
            DecodeProgress(
                out_time_seconds=out_time,
                dup_frames=self.dup_frames,
                drop_frames=self.drop_frames,
                fraction=fraction,
            )
        )


async def decode_canonical(
    *,
    source_path: Path,
    output_path: Path,
    stream_index: int,
    sample_rate: int,
    channel_count: int,
    max_threads: int = 4,
    channel_layout: str | None = None,
    estimated_duration_seconds: float | None = None,
    start_timestamp_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DecodeProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DECODE_TIMEOUT_SECONDS,
) -> CanonicalDecodeResult:
    """Decode one audio stream to canonical PCM and validate it.

    Raises ``DecodeCancelledError``, ``DecodeTimeoutError``,
    ``DecodeFailedError``, ``EmptyAudioError``, ``NonFiniteSamplesError``,
    or ``InsufficientDiskSpaceError``.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise DecodeCancelledError("decode was cancelled before it started")
    if not source_path.is_file():
        raise DecodeFailedError(f"media file not found: {source_path.name}")

    required_bytes = _required_free_bytes(estimated_duration_seconds, sample_rate, channel_count)
    _check_disk_space(output_path, required_bytes)

    args: Sequence[str] = (
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-v",
        "warning",
        "-threads",
        str(max_threads),
        "-i",
        str(source_path),
        "-map",
        f"0:{stream_index}",
        "-af",
        DISCONTINUITY_FILTER,
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        "-progress",
        "pipe:2",
        "-y",
        str(output_path),
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise DecodeFailedError(f"could not launch ffmpeg: {exc}") from exc

    stderr_stream = proc.stderr
    if stderr_stream is None:
        _kill(proc)
        raise DecodeFailedError("ffmpeg subprocess stderr is unavailable")

    state = _ProgressState(estimated_duration_seconds, on_progress)

    async def _read_stderr() -> None:
        buffer = b""
        total = 0
        while True:
            chunk = await stderr_stream.read(65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DECODE_STDERR_BYTES:
                raise SubprocessOutputError("ffmpeg stderr exceeds its byte bound")
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                state.handle_line(
                    line.decode("utf-8", errors="replace"), asyncio.get_running_loop().time()
                )
        if buffer:
            state.handle_line(
                buffer.decode("utf-8", errors="replace"), asyncio.get_running_loop().time()
            )

    cancel_task: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            read_task = asyncio.ensure_future(_read_stderr())
            if cancel_event is not None:
                cancel_task = asyncio.ensure_future(_wait_for_cancel(cancel_event))
            waitables: set[asyncio.Task[None]] = {read_task}
            if cancel_task is not None:
                waitables.add(cancel_task)
            done, _pending = await asyncio.wait(
                waitables,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task is not None and cancel_task in done:
                read_task.cancel()
                with contextlib.suppress(BaseException):
                    await read_task
                await _terminate_gracefully(proc)
                _remove_partial(output_path)
                raise DecodeCancelledError("decode was cancelled")
            if cancel_task is not None:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
            try:
                read_task.result()
            except SubprocessOutputError as exc:
                raise DecodeFailedError(str(exc)) from exc
            returncode = await proc.wait()
    except TimeoutError as exc:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise DecodeTimeoutError(
            f"decode did not finish within {timeout_seconds:g} seconds"
        ) from exc
    except DecodeFailedError:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise

    try:
        if returncode != 0:
            detail = "\n".join(state.warnings[-5:])
            raise DecodeFailedError(
                f"ffmpeg exited with {returncode}" + (f": {detail}" if detail else "")
            )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise EmptyAudioError("decode produced no audio samples")

        size = output_path.stat().st_size
        frame_count = check_frame_alignment(size, channel_count)

        content_hash: Sha256Hash
        max_amplitude: float
        try:
            content_hash, max_amplitude = validate_pcm(output_path, channel_count)
        except OSError as exc:
            raise DecodeFailedError(f"could not validate decoded PCM: {exc}") from exc

        decoded_duration = frame_count / sample_rate
        discrepancy, timing_warnings = duration_discrepancy_warnings(
            decoded_duration, estimated_duration_seconds
        )

        ffmpeg_version, _ffprobe_version = await tool_versions()
        return CanonicalDecodeResult(
            frame_count=frame_count,
            sample_rate=sample_rate,
            channel_count=channel_count,
            channel_layout=channel_layout,
            content_hash=content_hash,
            max_amplitude=max_amplitude,
            pcm_byte_count=size,
            decoded_duration_seconds=decoded_duration,
            estimated_duration_seconds=estimated_duration_seconds,
            duration_discrepancy_seconds=discrepancy,
            source_start_timestamp_seconds=start_timestamp_seconds,
            decoder_warnings=tuple(state.warnings),
            timing_repair_warnings=tuple(timing_warnings),
            ffmpeg_version=ffmpeg_version,
            profile_version=1,
            staging_pcm_path=str(output_path.resolve()),
        )
    except DecodeError:
        # A failed decode never leaves a partial staging file behind.
        _remove_partial(output_path)
        raise


def _remove_partial(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
