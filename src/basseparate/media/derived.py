"""Derived PCM transforms (M1.7): monitoring downmix and playback rate.

Both transforms read a validated PCM asset (raw interleaved little-endian
float32) and write a new staged PCM file, then validate the result in a
single chunked pass (frame alignment, finiteness, SHA-256, max amplitude).
The source is never modified.

Commands (verified against FFmpeg 8.1; see the M1.7 research notes in
``docs/implementation-status.md``)::

    # Monitoring downmix (pan matrix; coefficients are precomputed by
    # ``basseparate.media.downmix`` because pan channel expressions accept
    # only ``coef*channel`` terms):
    ffmpeg -hide_banner -nostdin -v warning -threads N
        -f f32le -ar <rate> -ac <ch> -i <source.pcm>
        -af pan=stereo|c0=...|c1=...
        -c:a pcm_f32le -f f32le
        -progress pipe:2 <staging.pcm>

    # Playback rate (versioned SWR profile v1):
    ffmpeg -hide_banner -nostdin -v warning -threads N
        -f f32le -ar <src_rate> -ac <ch> -i <source.pcm>
        -af aresample=<target>:filter_size=64:exact_rational=1:dither_method=0
        -c:a pcm_f32le -f f32le
        -progress pipe:2 <staging.pcm>

Design notes:
- The resampler profile pins every option that affects sample values:
  ``filter_size=64``, ``exact_rational=1``, no dithering (float output
  makes dither moot), no ``async``. ``exact_rational`` and ``async=0``
  are already the FFmpeg defaults; the profile states them explicitly so
  it is self-documenting and deterministic across builds (spec §9.5).
- A failed, timed-out, or cancelled transform never leaves a partial
  staging file behind.
- Derived assets are bounded by the source size and deduplicated by
  content hash, so the 2 GiB decode publication reserve (M1.6) does not
  apply to their disk budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from basseparate.domain.common import Sha256Hash
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
from basseparate.media.decode import (
    DISK_HEADROOM_FACTOR,
    MINIMUM_FREE_DISK_BYTES,
    DecodeProgress,
    _ProgressState,
    check_frame_alignment,
    validate_pcm,
)
from basseparate.media.decode import (
    DecodeFailedError as _DecodeFailedError,
)
from basseparate.media.decode import (
    NonFiniteSamplesError as _NonFiniteSamplesError,
)
from basseparate.media.probe import tool_versions

DEFAULT_DERIVED_TIMEOUT_SECONDS = 1800.0
MAX_DERIVED_STDERR_BYTES = 10 * 1024 * 1024  # 10 MiB

#: Version of the playback resampler profile (recorded in the transform key).
RESAMPLER_PROFILE_VERSION = 1


def playback_resample_filter(target_rate: int) -> str:
    """The versioned SWR filter argument for a playback-rate conversion."""
    return f"aresample={target_rate}:filter_size=64:exact_rational=1:dither_method=0"


class DerivedError(Exception):
    """Base class for derived-transform failures."""


class DerivedFailedError(DerivedError):
    """ffmpeg could not run, exited nonzero, or produced unusable output."""


class DerivedTimeoutError(DerivedError):
    """The transform did not finish within the allowed time."""


class DerivedCancelledError(DerivedError):
    """The transform was cancelled before it completed."""


class EmptyAudioError(DerivedError):
    """The transform produced no samples."""


class NonFiniteSamplesError(DerivedError):
    """The transform output contains NaN or infinite samples."""


class InsufficientDiskSpaceError(DerivedError):
    """Not enough free disk space for the expected transform output."""


@dataclass(frozen=True)
class DerivedProgress:
    """One derived-transform progress report (determinate when set)."""

    out_time_seconds: float
    dup_frames: int
    drop_frames: int
    fraction: float | None = None


@dataclass(frozen=True)
class _DriverOutcome:
    frame_count: int
    content_hash: Sha256Hash
    max_amplitude: float
    pcm_byte_count: int


@dataclass(frozen=True)
class DownmixOutcome:
    """Validated output of a monitoring downmix (the worker builds the
    domain result model from this)."""

    frame_count: int
    content_hash: Sha256Hash
    max_amplitude: float
    pcm_byte_count: int
    ffmpeg_version: str


@dataclass(frozen=True)
class PlaybackOutcome:
    """Validated output of a playback-rate conversion."""

    frame_count: int
    content_hash: Sha256Hash
    max_amplitude: float
    pcm_byte_count: int
    source_frame_count: int
    expected_frame_count: int
    endpoint_difference_frames: int
    ffmpeg_version: str


def _required_free_bytes(
    estimated_duration_seconds: float | None,
    output_rate: int,
    output_channels: int,
) -> int:
    """Pre-flight disk budget for a derived transform.

    The expected output PCM with temporary-publication overhead. Derived
    assets are bounded by the source size and deduplicated by content
    hash, so the 2 GiB decode publication reserve (M1.6) does not apply.
    """
    expected = 0
    if estimated_duration_seconds is not None:
        expected = int(estimated_duration_seconds * output_rate * output_channels * 4)
    return max(int(expected * DISK_HEADROOM_FACTOR), MINIMUM_FREE_DISK_BYTES)


def _check_disk_space(output_path: Path, required_bytes: int) -> None:
    probe_dir = output_path.parent
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    usage = shutil.disk_usage(probe_dir)
    if usage.free < required_bytes:
        raise InsufficientDiskSpaceError(
            f"need ~{required_bytes // (1024 * 1024)} MiB free for the transform "
            f"but only {usage.free // (1024 * 1024)} MiB are available"
        )


def _adapted_on_progress(
    on_progress: Callable[[DerivedProgress], None] | None,
) -> Callable[[DecodeProgress], None] | None:
    if on_progress is None:
        return None

    def adapt(progress: DecodeProgress) -> None:
        on_progress(
            DerivedProgress(
                out_time_seconds=progress.out_time_seconds,
                dup_frames=progress.dup_frames,
                drop_frames=progress.drop_frames,
                fraction=progress.fraction,
            )
        )

    return adapt


async def _run_derived_ffmpeg(
    *,
    input_path: Path,
    input_rate: int,
    input_channels: int,
    output_path: Path,
    output_rate: int,
    output_channels: int,
    filter_expr: str,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> _DriverOutcome:
    """Run one ffmpeg PCM→PCM transform and validate the staged output."""
    if cancel_event is not None and cancel_event.is_set():
        raise DerivedCancelledError("transform was cancelled before it started")
    if not input_path.is_file():
        raise DerivedFailedError(f"source PCM not found: {input_path.name}")

    required_bytes = _required_free_bytes(
        estimated_duration_seconds, output_rate, output_channels
    )
    _check_disk_space(output_path, required_bytes)

    args: Sequence[str] = (
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-v",
        "warning",
        "-threads",
        str(max_threads),
        "-f",
        "f32le",
        "-ar",
        str(input_rate),
        "-ac",
        str(input_channels),
        "-i",
        str(input_path),
        "-af",
        filter_expr,
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
        raise DerivedFailedError(f"could not launch ffmpeg: {exc}") from exc

    stderr_stream = proc.stderr
    if stderr_stream is None:
        _kill(proc)
        raise DerivedFailedError("ffmpeg subprocess stderr is unavailable")

    state = _ProgressState(estimated_duration_seconds, _adapted_on_progress(on_progress))

    async def _read_stderr() -> None:
        buffer = b""
        total = 0
        while True:
            chunk = await stderr_stream.read(65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DERIVED_STDERR_BYTES:
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
    returncode: int
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
                raise DerivedCancelledError("transform was cancelled")
            if cancel_task is not None:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
            try:
                read_task.result()
            except SubprocessOutputError as exc:
                raise DerivedFailedError(str(exc)) from exc
            returncode = await proc.wait()
    except TimeoutError as exc:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise DerivedTimeoutError(
            f"transform did not finish within {timeout_seconds:g} seconds"
        ) from exc
    except DerivedFailedError:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise

    try:
        if returncode != 0:
            detail = "\n".join(state.warnings[-5:])
            raise DerivedFailedError(
                f"ffmpeg exited with {returncode}" + (f": {detail}" if detail else "")
            )

        size = output_path.stat().st_size
        if size == 0:
            raise EmptyAudioError("transform produced no audio samples")

        try:
            frame_count = check_frame_alignment(size, output_channels)
        except _DecodeFailedError as exc:
            raise DerivedFailedError(str(exc)) from exc

        try:
            content_hash, max_amplitude = validate_pcm(output_path, output_channels)
        except _NonFiniteSamplesError as exc:
            raise NonFiniteSamplesError(str(exc)) from exc
        except _DecodeFailedError as exc:
            raise DerivedFailedError(str(exc)) from exc
        except OSError as exc:
            raise DerivedFailedError(f"could not validate derived PCM: {exc}") from exc
    except DerivedError:
        # A failed transform never leaves a partial staging file behind.
        _remove_partial(output_path)
        raise

    return _DriverOutcome(
        frame_count=frame_count,
        content_hash=content_hash,
        max_amplitude=max_amplitude,
        pcm_byte_count=size,
    )


async def downmix_monitoring(
    *,
    source_path: Path,
    output_path: Path,
    sample_rate: int,
    channel_count: int,
    pan_spec: str,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> DownmixOutcome:
    """Downmix a multichannel PCM source to stereo with a pan matrix.

    ``pan_spec`` is the full ``pan`` filter argument (see
    ``basseparate.media.downmix.pan_expression``). The output is stereo at
    the source rate.
    """
    outcome = await _run_derived_ffmpeg(
        input_path=source_path,
        input_rate=sample_rate,
        input_channels=channel_count,
        output_path=output_path,
        output_rate=sample_rate,
        output_channels=2,
        filter_expr=pan_spec,
        max_threads=max_threads,
        estimated_duration_seconds=estimated_duration_seconds,
        cancel_event=cancel_event,
        on_progress=on_progress,
        timeout_seconds=timeout_seconds,
    )
    ffmpeg_version, _ffprobe_version = await tool_versions()
    return DownmixOutcome(
        frame_count=outcome.frame_count,
        content_hash=outcome.content_hash,
        max_amplitude=outcome.max_amplitude,
        pcm_byte_count=outcome.pcm_byte_count,
        ffmpeg_version=ffmpeg_version,
    )


async def resample_playback(
    *,
    source_path: Path,
    output_path: Path,
    source_rate: int,
    target_rate: int,
    channel_count: int,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> PlaybackOutcome:
    """Resample a PCM source to the playback (target) rate.

    Records the endpoint difference (spec §9.6.5): the actual output frame
    count minus ``round(source_frames × target / source)``.
    """
    if source_rate <= 0 or target_rate <= 0:
        raise DerivedFailedError(
            f"sample rates must be positive, got source={source_rate} target={target_rate}"
        )
    source_frame_count = input_frame_count(source_path, channel_count)
    expected_frame_count = (source_frame_count * target_rate + source_rate // 2) // source_rate

    outcome = await _run_derived_ffmpeg(
        input_path=source_path,
        input_rate=source_rate,
        input_channels=channel_count,
        output_path=output_path,
        output_rate=target_rate,
        output_channels=channel_count,
        filter_expr=playback_resample_filter(target_rate),
        max_threads=max_threads,
        estimated_duration_seconds=estimated_duration_seconds,
        cancel_event=cancel_event,
        on_progress=on_progress,
        timeout_seconds=timeout_seconds,
    )
    ffmpeg_version, _ffprobe_version = await tool_versions()
    return PlaybackOutcome(
        frame_count=outcome.frame_count,
        content_hash=outcome.content_hash,
        max_amplitude=outcome.max_amplitude,
        pcm_byte_count=outcome.pcm_byte_count,
        source_frame_count=source_frame_count,
        expected_frame_count=expected_frame_count,
        endpoint_difference_frames=outcome.frame_count - expected_frame_count,
        ffmpeg_version=ffmpeg_version,
    )


def input_frame_count(path: Path, channel_count: int) -> int:
    """Frame count of a raw f32le PCM file, or raise when missing/misaligned."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DerivedFailedError(f"source PCM not found: {path.name}") from exc
    try:
        return check_frame_alignment(size, channel_count)
    except _DecodeFailedError as exc:
        raise DerivedFailedError(str(exc)) from exc


def _remove_partial(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
