"""WAV stem export encoding (M2.13, milestone2.md §15).

Turns the published f32le stem assets of one immutable separation result
set into WAV files in the job's staging directory, one file per selected
stem. The backend verifies the reported hashes and moves the files into
managed export storage; this module never touches the database.

Sequence (spec §15.3):

1. Verify + measure every stem source (size, SHA-256, joint peak) in one
   pass per stem.
2. Estimate the disk budget before any write.
3. Apply the clip rule: integer outputs refuse when the (unnormalized)
   joint peak exceeds the integer full-scale bound; float32 output never
   refuses.
4. Encode each stem with one ffmpeg pass: ``volume`` (linked
   normalization only) then ``aresample`` with triangular dither for
   integer outputs, ``-rf64 auto`` for oversized WAVs.
5. Verify each output with ffprobe (rate, channels, codec, decoded
   frames from the stream duration) plus the output SHA-256.

Design rules (spec §15.4): raw exports ignore all monitoring state;
every stem begins at the same source origin (alignment is enforced by
the backend before the worker runs).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from basseparate.domain.export import (
    ExportFormat,
    ExportNormalization,
    export_format_spec,
    normalize_gain_db,
)
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
    VALIDATION_CHUNK_BYTES,
    validate_pcm,
)
from basseparate.media.decode import (
    DecodeFailedError as _DecodeFailedError,
)
from basseparate.media.decode import (
    NonFiniteSamplesError as _NonFiniteSamplesError,
)

DEFAULT_EXPORT_TIMEOUT_SECONDS = 1800.0
MAX_EXPORT_STDERR_BYTES = 10 * 1024 * 1024  # 10 MiB

#: Decoded-frame tolerance for resampled outputs (spec §15.3.14): the
#: resampler may land one or two frames off the rational estimate.
ENDPOINT_TOLERANCE_FRAMES = 2

#: Progress stage names (mirror the ``JobStage`` values; the worker maps
#: them back onto protocol progress messages).
STAGE_VERIFYING_STEMS = "verifying_stems"
STAGE_ENCODING = "encoding"
STAGE_VERIFYING_EXPORT = "verifying_export"

_MAX_PROBE_OUTPUT_BYTES = 4 * 1024 * 1024  # 4 MiB per probe
_PROGRESS_MIN_INTERVAL_SECONDS = 0.25


class ExportError(Exception):
    """Base class for export failures."""


class ExportFailedError(ExportError):
    """ffmpeg could not run, exited nonzero, or produced unusable output."""


class ExportTimeoutError(ExportError):
    """An export step did not finish within the allowed time."""


class ExportCancelledError(ExportError):
    """The export was cancelled before it completed."""


class ExportClippingError(ExportError):
    """Integer output would clip the source (spec §15.3.9–10)."""


class ExportDiskSpaceError(ExportError):
    """Not enough free disk space for the expected export output."""


class ExportStemVerificationError(ExportError):
    """A stem source file is missing, mis-sized, or hash-mismatched."""


class ExportVerificationError(ExportError):
    """An encoded output failed ffprobe verification (spec §15.3.14)."""


@dataclass(frozen=True)
class ExportStemInput:
    """One selected stem source (backend-resolved, validated)."""

    stem_id: str
    asset_id: str
    role: str
    source_path: Path
    source_hash: str
    sample_rate: int
    channel_count: int
    frame_count: int
    download_filename: str


@dataclass(frozen=True)
class ExportStemOutput:
    """One verified staged export file."""

    staging_path: Path
    frame_count: int
    byte_size: int
    sha256: str
    output_rate: int


@dataclass(frozen=True)
class ExportOutcome:
    """Validated output of the export run (the worker builds the domain
    result model from this)."""

    stems: tuple[ExportStemOutput, ...]
    joint_peak: float
    gain_db: float | None


def _expected_output_frames(
    frame_count: int, source_rate: int, target_rate: int | None
) -> int:
    """Rational estimate of the resampled frame count (rounding)."""
    if target_rate is None or target_rate == source_rate:
        return frame_count
    return (frame_count * target_rate + source_rate // 2) // source_rate


def _check_disk_space(staging_dir: Path, required_bytes: int) -> None:
    probe_dir = staging_dir
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    usage = shutil.disk_usage(probe_dir)
    if usage.free < required_bytes:
        raise ExportDiskSpaceError(
            f"need ~{required_bytes // (1024 * 1024)} MiB free for the export "
            f"but only {usage.free // (1024 * 1024)} MiB are available"
        )


def _measure_stem(stem: ExportStemInput) -> float:
    """Verify one stem source and return its peak amplitude.

    Checks the size (``frames × channels × 4``), the SHA-256, and sample
    finiteness in the same chunked pass that measures the peak.
    """
    try:
        size = stem.source_path.stat().st_size
    except OSError as exc:
        raise ExportStemVerificationError(
            f"stem source not found: {stem.source_path.name}"
        ) from exc
    expected_size = stem.frame_count * stem.channel_count * 4
    if size != expected_size:
        raise ExportStemVerificationError(
            f"stem source {stem.source_path.name} is {size} bytes, "
            f"expected {expected_size} (frames x channels x 4)"
        )
    try:
        content_hash, peak = validate_pcm(stem.source_path, stem.channel_count)
    except _NonFiniteSamplesError as exc:
        raise ExportStemVerificationError(
            f"stem source {stem.source_path.name} contains non-finite samples"
        ) from exc
    except (_DecodeFailedError, OSError) as exc:
        raise ExportStemVerificationError(
            f"could not read stem source {stem.source_path.name}: {exc}"
        ) from exc
    if content_hash != stem.source_hash:
        raise ExportStemVerificationError(
            f"stem source {stem.source_path.name} hash mismatch "
            f"(expected {stem.source_hash[:12]}…, got {content_hash[:12]}…)"
        )
    return peak


def _build_filter_chain(
    *,
    format: ExportFormat,
    source_rate: int,
    output_rate: int,
    gain_db: float | None,
) -> str:
    """The per-stem ffmpeg filter chain (spec §15.3.8, 11, 12).

    Linked normalization first (``volume``), then the resampler. Integer
    outputs pin the resampler's output format (``out_sample_fmt``) so the
    float→integer reduction happens inside the explicit filter with
    ``dither_method=triangular``; float32 output never dithers and only
    resamples when the rate changes.
    """
    parts: list[str] = []
    if gain_db is not None:
        parts.append(f"volume={gain_db!r}dB")
    if format is ExportFormat.WAV32F:
        if output_rate != source_rate:
            parts.append(f"aresample={output_rate}:dither_method=0")
    elif format is ExportFormat.WAV16:
        parts.append(f"aresample={output_rate}:out_sample_fmt=s16:dither_method=triangular")
    else:  # WAV24: 24-bit data in an s32 container
        parts.append(f"aresample={output_rate}:out_sample_fmt=s32:dither_method=triangular")
    return ",".join(parts)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(VALIDATION_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_partial(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


@dataclass
class _EncodeProgressState:
    """Parses ffmpeg ``-progress pipe:2`` lines into progress reports."""

    estimated_seconds: float
    on_progress: Callable[[str, float | None, str], None] | None
    stage: str
    last_emit: float = 0.0
    out_time_us: int | None = None
    warnings: list[str] = field(default_factory=list)

    def handle_line(self, line: str, now: float) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            value = value.strip()
            if key == "out_time_us":
                with contextlib.suppress(ValueError):
                    self.out_time_us = int(value)
            elif key == "progress":
                self._emit(now, is_final=value == "end")
            return
        if len(self.warnings) < 5:
            self.warnings.append(stripped[:500])

    def _emit(self, now: float, is_final: bool) -> None:
        if self.out_time_us is None or self.on_progress is None:
            return
        if not is_final and now - self.last_emit < _PROGRESS_MIN_INTERVAL_SECONDS:
            return
        self.last_emit = now
        out_time = self.out_time_us / 1_000_000
        fraction = (
            min(1.0, out_time / self.estimated_seconds)
            if self.estimated_seconds > 0
            else None
        )
        self.on_progress(
            self.stage,
            fraction,
            f"encoded {out_time:.1f}s of ~{self.estimated_seconds:.1f}s",
        )


async def _run_export_ffmpeg(
    *,
    stem: ExportStemInput,
    output_path: Path,
    filter_expr: str | None,
    encoder: str,
    max_threads: int,
    estimated_seconds: float,
    stage: str,
    cancel_event: threading.Event | None,
    on_progress: Callable[[str, float | None, str], None] | None,
    timeout_seconds: float,
) -> None:
    """Encode one stem: f32le PCM in, one WAV out (spec §15.3.12–13)."""
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelledError("export was cancelled before it started")
    args: list[str] = [
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
        str(stem.sample_rate),
        "-ac",
        str(stem.channel_count),
        "-i",
        str(stem.source_path),
    ]
    if filter_expr:
        args += ["-af", filter_expr]
    args += [
        "-c:a",
        encoder,
        "-f",
        "wav",
        "-rf64",
        "auto",
        "-progress",
        "pipe:2",
        "-y",
        str(output_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ExportFailedError(f"could not launch ffmpeg: {exc}") from exc

    stderr_stream = proc.stderr
    if stderr_stream is None:
        _kill(proc)
        raise ExportFailedError("ffmpeg subprocess stderr is unavailable")

    state = _EncodeProgressState(estimated_seconds, on_progress, stage)

    async def _read_stderr() -> None:
        buffer = b""
        total = 0
        while True:
            chunk = await stderr_stream.read(65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_EXPORT_STDERR_BYTES:
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
                raise ExportCancelledError("export was cancelled")
            if cancel_task is not None:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
            try:
                read_task.result()
            except SubprocessOutputError as exc:
                raise ExportFailedError(str(exc)) from exc
            returncode = await proc.wait()
    except TimeoutError as exc:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise ExportTimeoutError(
            f"export encoding did not finish within {timeout_seconds:g} seconds"
        ) from exc
    except ExportFailedError:
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise

    if returncode != 0:
        detail = " | ".join(state.warnings[-5:])
        await _terminate_gracefully(proc)
        _remove_partial(output_path)
        raise ExportFailedError(
            f"ffmpeg exited with {returncode}" + (f": {detail}" if detail else "")
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        _remove_partial(output_path)
        raise ExportFailedError("ffmpeg produced no output file")


async def _probe_exported_stem(
    path: Path, timeout_seconds: float
) -> dict[str, Any]:
    """ffprobe one staged WAV; the stream section.

    The stream ``duration`` is exact for WAV (data-chunk size over byte
    rate) and is the reliable decoded-frame source: ffprobe's
    ``nb_frames``/``nb_read_frames`` are not meaningful for PCM streams
    on the verified FFmpeg 8.x builds.
    """
    args = (
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,codec_name,duration",
        "-of",
        "json",
        str(path),
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ExportFailedError(f"could not launch ffprobe: {exc}") from exc
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        _kill(proc)
        raise ExportTimeoutError(
            f"ffprobe did not finish within {timeout_seconds:g} seconds"
        ) from exc
    if proc.returncode != 0:
        raise ExportVerificationError(f"ffprobe exited with {proc.returncode}")
    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ExportVerificationError("ffprobe returned invalid JSON") from exc
    streams = data.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ExportVerificationError("ffprobe output has no stream section")
    stream = streams[0]
    if not isinstance(stream, dict):
        raise ExportVerificationError("ffprobe stream section is malformed")
    return stream


def _check_probed_stream(
    *,
    stream: dict[str, Any],
    stem: ExportStemInput,
    output_rate: int,
    expected_frames: int,
    same_rate: bool,
    expected_codec: str,
    path: Path,
) -> int:
    """Assert the probed stream matches the export expectations.

    Returns the decoded frame count derived from the stream duration.
    """

    def _as_int(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ExportVerificationError(f"ffprobe output missing {name}")
        try:
            result = int(value)
        except ValueError as exc:
            raise ExportVerificationError(f"ffprobe output has invalid {name}") from exc
        return result

    codec = stream.get("codec_name")
    if codec != expected_codec:
        raise ExportVerificationError(
            f"{path.name} codec is {codec!r}, expected {expected_codec!r}"
        )
    rate = _as_int(stream.get("sample_rate"), "sample_rate")
    if rate != output_rate:
        raise ExportVerificationError(
            f"{path.name} sample rate is {rate}, expected {output_rate}"
        )
    channels = _as_int(stream.get("channels"), "channels")
    if channels != stem.channel_count:
        raise ExportVerificationError(
            f"{path.name} has {channels} channels, expected {stem.channel_count}"
        )
    duration = stream.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float, str)):
        raise ExportVerificationError(f"{path.name} ffprobe output has no duration")
    try:
        duration_seconds = float(duration)
    except ValueError as exc:
        raise ExportVerificationError(f"{path.name} ffprobe duration is invalid") from exc
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ExportVerificationError(f"{path.name} ffprobe duration is not usable")
    frames = round(duration_seconds * rate)
    if same_rate:
        if frames != expected_frames:
            raise ExportVerificationError(
                f"{path.name} decoded {frames} frames, expected exactly "
                f"{expected_frames} at the source rate"
            )
    elif abs(frames - expected_frames) > ENDPOINT_TOLERANCE_FRAMES:
        raise ExportVerificationError(
            f"{path.name} decoded {frames} frames, expected "
            f"{expected_frames} ± {ENDPOINT_TOLERANCE_FRAMES} after resampling"
        )
    return frames


async def export_stems(
    *,
    stems: Sequence[ExportStemInput],
    staging_dir: Path,
    format: ExportFormat,
    target_sample_rate: int | None,
    normalize: ExportNormalization,
    max_threads: int = 4,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[str, float | None, str], None] | None = None,
    timeout_seconds: float = DEFAULT_EXPORT_TIMEOUT_SECONDS,
) -> ExportOutcome:
    """Encode every selected stem into a staged WAV (spec §15.3).

    Raises the ``Export*Error`` hierarchy; a failed run never leaves a
    partial staged file behind.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelledError("export was cancelled before it started")
    if not stems:
        raise ExportFailedError("no stems to export")

    spec = export_format_spec(format)
    source_rate = stems[0].sample_rate
    output_rate = target_sample_rate if target_sample_rate is not None else source_rate
    same_rate = output_rate == source_rate

    def report(stage: str, fraction: float | None, detail: str) -> None:
        if on_progress is not None:
            on_progress(stage, fraction, detail)

    # --- 1. Verify + measure (joint peak across the selected set). -----
    report(STAGE_VERIFYING_STEMS, 0.0, f"verifying {len(stems)} stem source(s)")
    peaks: list[float] = []
    for index, stem in enumerate(stems):
        peaks.append(_measure_stem(stem))
        report(
            STAGE_VERIFYING_STEMS,
            (index + 1) / len(stems),
            f"verified stem {index + 1}/{len(stems)}",
        )
    joint_peak = max(peaks)

    # --- 2. Linked normalization gain and the clip rule. ----------------
    if normalize is ExportNormalization.LINKED_PEAK:
        gain_db = normalize_gain_db(joint_peak)
    else:
        gain_db = None
    if (
        gain_db is None
        and spec.integer_full_scale is not None
        and joint_peak > spec.integer_full_scale
    ):
        raise ExportClippingError(
            f"the selected stems peak at {joint_peak:.6f}, above the "
            f"{format.value} full-scale bound {spec.integer_full_scale:.6f}; "
            "export as float32 (wav32f) or use linked peak normalization"
        )

    # --- 3. Disk budget before any write. -------------------------------
    required_bytes = 0
    for stem in stems:
        out_frames = _expected_output_frames(stem.frame_count, source_rate, target_sample_rate)
        required_bytes += out_frames * stem.channel_count * spec.bytes_per_sample
    required_bytes = max(
        int(required_bytes * DISK_HEADROOM_FACTOR), MINIMUM_FREE_DISK_BYTES
    )
    staging_dir.mkdir(parents=True, exist_ok=True)
    _check_disk_space(staging_dir, required_bytes)

    # --- 4. Encode, one ffmpeg pass per stem. ----------------------------
    filter_expr = _build_filter_chain(
        format=format,
        source_rate=source_rate,
        output_rate=output_rate,
        gain_db=gain_db,
    ) or None
    outputs: list[ExportStemOutput] = []
    total = len(stems)
    for index, stem in enumerate(stems):
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelledError("export was cancelled")
        output_path = staging_dir / f"export-{index}.wav"
        out_frames = _expected_output_frames(stem.frame_count, source_rate, target_sample_rate)
        estimated_seconds = out_frames / output_rate
        report(
            STAGE_ENCODING,
            index / total,
            f"encoding stem {index + 1}/{total}",
        )
        await _run_export_ffmpeg(
            stem=stem,
            output_path=output_path,
            filter_expr=filter_expr,
            encoder=spec.encoder,
            max_threads=max_threads,
            estimated_seconds=estimated_seconds,
            stage=STAGE_ENCODING,
            cancel_event=cancel_event,
            on_progress=report,
            timeout_seconds=timeout_seconds,
        )
        outputs.append(
            ExportStemOutput(
                staging_path=output_path,
                frame_count=0,  # filled in by verification
                byte_size=0,
                sha256="",
                output_rate=output_rate,
            )
        )

    # --- 5. Verify every output (ffprobe -count_frames + hash). ---------
    verified: list[ExportStemOutput] = []
    for index, (stem, output) in enumerate(zip(stems, outputs, strict=True)):
        if cancel_event is not None and cancel_event.is_set():
            _remove_partial(output.staging_path)
            raise ExportCancelledError("export was cancelled")
        stream = await _probe_exported_stem(output.staging_path, timeout_seconds)
        expected_frames = _expected_output_frames(
            stem.frame_count, source_rate, target_sample_rate
        )
        frames = _check_probed_stream(
            stream=stream,
            stem=stem,
            output_rate=output_rate,
            expected_frames=expected_frames,
            same_rate=same_rate,
            expected_codec=spec.encoder,
            path=output.staging_path,
        )
        byte_size = output.staging_path.stat().st_size
        digest = await asyncio.get_running_loop().run_in_executor(
            None, _sha256_file, output.staging_path
        )
        verified.append(
            ExportStemOutput(
                staging_path=output.staging_path,
                frame_count=frames,
                byte_size=byte_size,
                sha256=digest,
                output_rate=output_rate,
            )
        )
        report(
            STAGE_VERIFYING_EXPORT,
            (index + 1) / total,
            f"verified export {index + 1}/{total}",
        )

    return ExportOutcome(
        stems=tuple(verified),
        joint_peak=joint_peak,
        gain_db=gain_db,
    )
