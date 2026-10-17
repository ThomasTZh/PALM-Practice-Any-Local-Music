"""Media worker: executes durable media jobs in a subprocess (M1.4).

Concurrency model:
- The main thread reads stdin and handles ``describe``/``ping``/``cancel``/
  ``shutdown``.
- At most one job thread runs at a time (the JobManager enforces a single
  active job). The job thread emits ``progress``/``completed``/``failed``/
  ``cancelled``.
- All stdout writes are serialized by a lock so the two threads never
  interleave partial lines.

Ownership rules (milestone1.md §6.4): the worker receives validated paths
and parameters, writes only into its assigned staging directory, emits
progress and result metadata, and never touches the database or attaches an
asset to a project. The backend verifies and publishes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import shutil
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from basseparate.domain.common import JS_SAFE_INTEGER_MAX, Uuid
from basseparate.domain.export import (
    ExportFormat,
    ExportNormalization,
    ExportResult,
    ExportStemResult,
    export_dither_for,
)
from basseparate.domain.media_job import JobStage, JobType
from basseparate.domain.representation import MonitoringDownmixResult, PlaybackRateResult
from basseparate.domain.separation import StemRole
from basseparate.domain.waveform import BASE_BUCKET_FRAMES, WaveformResult
from basseparate.media.decode import (
    DecodeCancelledError,
    DecodeError,
    DecodeProgress,
    DecodeTimeoutError,
    EmptyAudioError,
    InsufficientDiskSpaceError,
    NonFiniteSamplesError,
    decode_canonical,
)
from basseparate.media.derived import (
    DerivedCancelledError,
    DerivedError,
    DerivedProgress,
    DerivedTimeoutError,
    downmix_monitoring,
    resample_playback,
)
from basseparate.media.derived import (
    EmptyAudioError as _DerivedEmptyAudioError,
)
from basseparate.media.derived import (
    InsufficientDiskSpaceError as _DerivedInsufficientDiskSpaceError,
)
from basseparate.media.derived import (
    NonFiniteSamplesError as _DerivedNonFiniteSamplesError,
)
from basseparate.media.export import (
    ExportCancelledError,
    ExportClippingError,
    ExportDiskSpaceError,
    ExportError,
    ExportStemInput,
    ExportStemVerificationError,
    ExportTimeoutError,
    ExportVerificationError,
    export_stems,
)
from basseparate.media.probe import (
    NoAudioStreamError,
    ProbeCancelledError,
    ProbeError,
    ProbeFailedError,
    ProbeTimeoutError,
    UnsupportedMediaError,
    probe_media,
)
from basseparate.media.waveform import (
    WaveformCancelledError,
    WaveformError,
    build_waveform_cache,
)
from basseparate.worker.protocol import (
    ERR_INTERNAL,
    ERR_MALFORMED,
    ERR_NOT_IMPLEMENTED,
    ERR_OVERSIZED,
    ERR_UNKNOWN_TYPE,
    ERR_VERSION_MISMATCH,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    CancelMessage,
    Capability,
    DescribeMessage,
    PingMessage,
    RunMessage,
    RunPayload,
    ShutdownMessage,
    WorkerMessage,
    decode_message,
    make_cancelled,
    make_capabilities,
    make_completed,
    make_error,
    make_failed,
    make_hello,
    make_pong,
    make_progress,
    make_stopped,
)

WORKER_NAME = "media"

_JOB_THREAD_JOIN_SECONDS = 15.0

_stdout_lock = threading.Lock()


def _log(message: str) -> None:
    # Logs go to stderr only; stdout carries protocol messages exclusively.
    print(f"[media-worker] {message}", file=sys.stderr, flush=True)


def _send(message: WorkerMessage) -> None:
    with _stdout_lock:
        sys.stdout.buffer.write(message.encode() + b"\n")
        sys.stdout.buffer.flush()


def _remove_staging(staging_dir: str) -> bool:
    """Remove a job's staging directory. Returns True if it was removed."""
    path = Path(staging_dir)
    if not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def _probe_error_code(exc: ProbeError) -> str:
    if isinstance(exc, ProbeTimeoutError):
        return "PROBE_TIMEOUT"
    if isinstance(exc, NoAudioStreamError):
        return "NO_AUDIO_STREAM"
    if isinstance(exc, UnsupportedMediaError):
        return "UNSUPPORTED_MEDIA"
    if isinstance(exc, ProbeFailedError):
        return "PROBE_FAILED"
    return "PROBE_FAILED"


def _decode_error_code(exc: DecodeError) -> str:
    if isinstance(exc, DecodeTimeoutError):
        return "DECODE_TIMEOUT"
    if isinstance(exc, EmptyAudioError):
        return "EMPTY_AUDIO"
    if isinstance(exc, NonFiniteSamplesError):
        return "NONFINITE_SAMPLES"
    if isinstance(exc, InsufficientDiskSpaceError):
        return "INSUFFICIENT_DISK_SPACE"
    return "DECODE_FAILED"


def _derived_error_code(exc: DerivedError) -> str:
    if isinstance(exc, DerivedTimeoutError):
        return "DERIVED_TIMEOUT"
    if isinstance(exc, _DerivedEmptyAudioError):
        return "EMPTY_AUDIO"
    if isinstance(exc, _DerivedNonFiniteSamplesError):
        return "NONFINITE_SAMPLES"
    if isinstance(exc, _DerivedInsufficientDiskSpaceError):
        return "INSUFFICIENT_DISK_SPACE"
    return "DERIVED_FAILED"


def _export_error_code(exc: ExportError) -> str:
    if isinstance(exc, ExportTimeoutError):
        return "EXPORT_TIMEOUT"
    if isinstance(exc, ExportClippingError):
        return "EXPORT_CLIPPING"
    if isinstance(exc, ExportDiskSpaceError):
        return "EXPORT_DISK"
    if isinstance(exc, ExportStemVerificationError):
        return "EXPORT_STEM_MISSING"
    if isinstance(exc, ExportVerificationError):
        return "EXPORT_VERIFICATION"
    return "EXPORT_FAILED"


def _as_int_param(parameters: dict[str, Any], name: str, minimum: int, maximum: int) -> int:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _as_str_param(parameters: dict[str, Any], name: str, maximum: int) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} must be a string of 1-{maximum} characters")
    return value


def _as_optional_float_param(parameters: dict[str, Any], name: str) -> float | None:
    value = parameters.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a nonnegative number")
    return float(value)


def _run_probe(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a probe job: inspect the source, report the result metadata."""
    _send(make_progress(payload.job_id, JobStage.INSPECTING, None, "running ffprobe"))
    result = asyncio.run(probe_media(Path(payload.source_path), cancel_event=cancel_event))
    # The backend verifies this payload before publishing it.
    _send(make_completed(payload.job_id, result.model_dump(mode="json")))


def _run_canonical_decode(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a decode job: canonical PCM in staging, result metadata only.

    The backend re-verifies the result against the probe and publishes the
    asset; the worker never touches the database.
    """
    job_id = payload.job_id
    _send(make_progress(job_id, JobStage.DECODING, None, "starting ffmpeg"))
    parameters = payload.parameters
    try:
        stream_index = _as_int_param(parameters, "stream_index", 0, 1024)
        sample_rate = _as_int_param(parameters, "sample_rate", 8_000, 192_000)
        channel_count = _as_int_param(parameters, "channel_count", 1, 8)
        channel_layout = parameters.get("channel_layout")
        if channel_layout is not None and (
            not isinstance(channel_layout, str) or not 1 <= len(channel_layout) <= 64
        ):
            raise ValueError("channel_layout must be a short string")
        estimated = _as_optional_float_param(parameters, "estimated_duration_seconds")
        start_timestamp = _as_optional_float_param(parameters, "start_timestamp_seconds")
    except ValueError as exc:
        _send(
            make_failed(
                job_id,
                "DECODE_PARAMETERS",
                f"invalid decode parameters: {exc}",
            )
        )
        return

    def on_progress(progress: DecodeProgress) -> None:
        detail = f"decoded {progress.out_time_seconds:.1f}s"
        if estimated is not None:
            detail += f" of ~{estimated:.1f}s"
        _send(make_progress(job_id, JobStage.DECODING, progress.fraction, detail))

    output_path = Path(payload.staging_dir) / "canonical.pcm"
    result = asyncio.run(
        decode_canonical(
            source_path=Path(payload.source_path),
            output_path=output_path,
            stream_index=stream_index,
            sample_rate=sample_rate,
            channel_count=channel_count,
            max_threads=payload.max_threads,
            channel_layout=channel_layout,
            estimated_duration_seconds=estimated,
            start_timestamp_seconds=start_timestamp,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
    )
    # The backend verifies this payload before publishing it.
    _send(make_completed(job_id, result.model_dump(mode="json")))


def _derived_parameters(payload: RunPayload) -> dict[str, Any]:
    """Validate the parameters shared by both derived transforms."""
    parameters = payload.parameters
    try:
        source_pcm_path = _as_str_param(parameters, "source_pcm_path", 4096)
        sample_rate = _as_int_param(parameters, "sample_rate", 8_000, 192_000)
        channel_count = _as_int_param(parameters, "channel_count", 1, 8)
        estimated = _as_optional_float_param(parameters, "estimated_duration_seconds")
    except ValueError as exc:
        raise ValueError(f"invalid derived parameters: {exc}") from exc
    return {
        "source_pcm_path": source_pcm_path,
        "sample_rate": sample_rate,
        "channel_count": channel_count,
        "estimated": estimated,
    }


def _derived_progress_sender(
    job_id: Uuid, estimated: float | None
) -> Callable[[DerivedProgress], None]:
    def on_progress(progress: DerivedProgress) -> None:
        detail = f"processed {progress.out_time_seconds:.1f}s"
        if estimated is not None:
            detail += f" of ~{estimated:.1f}s"
        _send(make_progress(job_id, JobStage.PREPARING_PLAYBACK, progress.fraction, detail))

    return on_progress


def _run_monitoring_downmix(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a monitoring downmix: stereo PCM in staging, metadata only."""
    job_id = payload.job_id
    _send(make_progress(job_id, JobStage.PREPARING_PLAYBACK, None, "starting ffmpeg"))
    try:
        common = _derived_parameters(payload)
        pan_spec = _as_str_param(payload.parameters, "pan_spec", 1024)
        downmix_mode = _as_str_param(payload.parameters, "downmix_mode", 32)
        left_channel = _as_int_param(payload.parameters, "left_channel", 0, 7)
        right_channel = _as_int_param(payload.parameters, "right_channel", 0, 7)
    except ValueError as exc:
        _send(make_failed(job_id, "DOWNMIX_PARAMETERS", str(exc)))
        return

    output_path = Path(payload.staging_dir) / "monitoring.pcm"
    outcome = asyncio.run(
        downmix_monitoring(
            source_path=Path(common["source_pcm_path"]),
            output_path=output_path,
            sample_rate=common["sample_rate"],
            channel_count=common["channel_count"],
            pan_spec=pan_spec,
            max_threads=payload.max_threads,
            estimated_duration_seconds=common["estimated"],
            cancel_event=cancel_event,
            on_progress=_derived_progress_sender(job_id, common["estimated"]),
        )
    )
    result = MonitoringDownmixResult(
        frame_count=outcome.frame_count,
        sample_rate=common["sample_rate"],
        channel_count=2,
        content_hash=outcome.content_hash,
        max_amplitude=outcome.max_amplitude,
        pcm_byte_count=outcome.pcm_byte_count,
        source_frame_count=outcome.frame_count,
        downmix_mode=downmix_mode,
        left_channel=left_channel,
        right_channel=right_channel,
        ffmpeg_version=outcome.ffmpeg_version,
        profile_version=1,
        staging_pcm_path=str(output_path.resolve()),
    )
    _send(make_completed(job_id, result.model_dump(mode="json")))


def _run_playback_rate(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a playback-rate conversion: PCM in staging, metadata only."""
    job_id = payload.job_id
    _send(make_progress(job_id, JobStage.PREPARING_PLAYBACK, None, "starting ffmpeg"))
    try:
        common = _derived_parameters(payload)
        target_rate = _as_int_param(payload.parameters, "target_sample_rate", 8_000, 192_000)
    except ValueError as exc:
        _send(make_failed(job_id, "PLAYBACK_PARAMETERS", str(exc)))
        return

    output_path = Path(payload.staging_dir) / "playback.pcm"
    outcome = asyncio.run(
        resample_playback(
            source_path=Path(common["source_pcm_path"]),
            output_path=output_path,
            source_rate=common["sample_rate"],
            target_rate=target_rate,
            channel_count=common["channel_count"],
            max_threads=payload.max_threads,
            estimated_duration_seconds=common["estimated"],
            cancel_event=cancel_event,
            on_progress=_derived_progress_sender(job_id, common["estimated"]),
        )
    )
    result = PlaybackRateResult(
        frame_count=outcome.frame_count,
        sample_rate=target_rate,
        channel_count=common["channel_count"],
        content_hash=outcome.content_hash,
        max_amplitude=outcome.max_amplitude,
        pcm_byte_count=outcome.pcm_byte_count,
        source_frame_count=outcome.source_frame_count,
        source_sample_rate=common["sample_rate"],
        target_sample_rate=target_rate,
        expected_frame_count=outcome.expected_frame_count,
        endpoint_difference_frames=outcome.endpoint_difference_frames,
        ffmpeg_version=outcome.ffmpeg_version,
        profile_version=1,
        staging_pcm_path=str(output_path.resolve()),
    )
    _send(make_completed(job_id, result.model_dump(mode="json")))


def _export_parameters(
    payload: RunPayload,
) -> tuple[str, ExportFormat, int | None, ExportNormalization, list[ExportStemInput]]:
    """Parse and validate the export job parameters (M2.13 §15)."""
    parameters = payload.parameters
    result_set_id = _as_str_param(parameters, "result_set_id", 64)
    format_value = _as_str_param(parameters, "format", 16)
    try:
        export_format = ExportFormat(format_value)
    except ValueError as exc:
        raise ValueError("format must be one of wav16, wav24, wav32f") from exc
    normalize_value = _as_str_param(parameters, "normalize", 32)
    try:
        normalize = ExportNormalization(normalize_value)
    except ValueError as exc:
        raise ValueError("normalize must be one of off, linked_peak") from exc
    if "target_sample_rate" in parameters:
        target_rate = _as_int_param(parameters, "target_sample_rate", 8_000, 192_000)
    else:
        target_rate = None
    stems_raw = parameters.get("stems")
    if not isinstance(stems_raw, list) or not 1 <= len(stems_raw) <= 16:
        raise ValueError("stems must be a list of 1-16 stem payloads")
    stems: list[ExportStemInput] = []
    for index, entry in enumerate(stems_raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"stem {index} must be an object")
        try:
            stem = ExportStemInput(
                stem_id=_as_str_param(entry, "stem_id", 64),
                asset_id=_as_str_param(entry, "asset_id", 64),
                role=_as_str_param(entry, "role", 32),
                source_path=Path(_as_str_param(entry, "source_path", 4096)),
                source_hash=_as_str_param(entry, "source_hash", 64),
                sample_rate=_as_int_param(entry, "sample_rate", 8_000, 192_000),
                channel_count=_as_int_param(entry, "channel_count", 1, 8),
                frame_count=_as_int_param(entry, "frame_count", 1, 1_000_000_000),
                download_filename=_as_str_param(entry, "download_filename", 200),
            )
        except ValueError as exc:
            raise ValueError(f"stem {index}: {exc}") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", stem.source_hash):
            raise ValueError(f"stem {index}: source_hash must be 64 hex characters")
        if not stem.source_path.is_absolute():
            raise ValueError(f"stem {index}: source_path must be absolute")
        try:
            StemRole(stem.role)
        except ValueError as exc:
            raise ValueError(f"stem {index}: unknown stem role {stem.role!r}") from exc
        stems.append(stem)
    if len({s.sample_rate for s in stems}) != 1:
        raise ValueError("all stems must share one sample rate")
    if len({s.frame_count for s in stems}) != 1:
        raise ValueError("all stems must share one frame count")
    return result_set_id, export_format, target_rate, normalize, stems


def _run_export(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a WAV stem export (M2.13 §15): encode, verify, report."""
    job_id = payload.job_id
    _send(make_progress(job_id, JobStage.VERIFYING_STEMS, None, "verifying stem sources"))
    try:
        (
            result_set_id,
            export_format,
            target_rate,
            normalize,
            stems,
        ) = _export_parameters(payload)
    except ValueError as exc:
        _send(make_failed(job_id, "EXPORT_PARAMETERS", str(exc)))
        return

    def on_progress(stage: str, fraction: float | None, detail: str) -> None:
        _send(make_progress(job_id, JobStage(stage), fraction, detail))

    outcome = asyncio.run(
        export_stems(
            stems=stems,
            staging_dir=Path(payload.staging_dir),
            format=export_format,
            target_sample_rate=target_rate,
            normalize=normalize,
            max_threads=payload.max_threads,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
    )
    dither = export_dither_for(export_format)
    artifacts = [
        ExportStemResult(
            stem_id=stem.stem_id,
            audio_asset_id=stem.asset_id,
            role=StemRole(stem.role),
            format=export_format,
            sample_rate=output.output_rate,
            channel_count=stem.channel_count,
            frame_count=output.frame_count,
            source_frame_count=stem.frame_count,
            normalized=outcome.gain_db is not None,
            gain_db=outcome.gain_db,
            dither=dither,
            sha256=output.sha256,
            byte_size=output.byte_size,
            download_filename=stem.download_filename,
            staging_path=str(output.staging_path.resolve()),
        )
        for stem, output in zip(stems, outcome.stems, strict=True)
    ]
    result = ExportResult(
        result_set_id=result_set_id,
        artifacts=artifacts,
        joint_peak=outcome.joint_peak,
    )
    _send(make_completed(job_id, result.model_dump(mode="json")))


def _run_waveform(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Execute a waveform job: pyramid cache on disk, result metadata only.

    The worker writes tiles and the manifest under the assigned cache
    directory and never touches the database (M1.4 boundary). The backend
    re-verifies the final manifest and a spot-checked tile before it
    registers the cache row.
    """
    job_id = payload.job_id
    _send(make_progress(job_id, JobStage.BUILDING_WAVEFORM, None, "starting waveform build"))
    parameters = payload.parameters
    try:
        source_path = _as_str_param(parameters, "source_path", 4096)
        source_hash = _as_str_param(parameters, "source_hash", 64)
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError("source_hash must be 64 lowercase hex characters")
        sample_rate = _as_int_param(parameters, "sample_rate", 8_000, 192_000)
        frame_count = _as_int_param(parameters, "frame_count", 1, JS_SAFE_INTEGER_MAX)
        channel_count = _as_int_param(parameters, "channel_count", 1, 8)
        cache_dir = _as_str_param(parameters, "cache_dir", 4096)
    except ValueError as exc:
        _send(make_failed(job_id, "WAVEFORM_PARAMETERS", f"invalid waveform parameters: {exc}"))
        return

    source = Path(source_path)
    if not source.is_file():
        _send(
            make_failed(job_id, "WAVEFORM_SOURCE_MISSING", f"source PCM not found: {source_path}")
        )
        return
    expected_bytes = frame_count * channel_count * 4
    try:
        actual_bytes = source.stat().st_size
    except OSError as exc:
        _send(
            make_failed(
                job_id, "WAVEFORM_SOURCE_MISSING", f"cannot stat source PCM: {exc}"
            )
        )
        return
    if actual_bytes != expected_bytes:
        _send(
            make_failed(
                job_id,
                "WAVEFORM_SOURCE_SIZE_MISMATCH",
                f"source PCM is {actual_bytes} bytes; expected {expected_bytes} "
                f"for {frame_count} frames x {channel_count} channels",
            )
        )
        return

    manifest = build_waveform_cache(
        source,
        Path(cache_dir),
        source_hash=source_hash,
        sample_rate=sample_rate,
        frame_count=frame_count,
        channel_count=channel_count,
        cancel_event=cancel_event,
        on_progress=lambda fraction: _send(
            make_progress(job_id, JobStage.BUILDING_WAVEFORM, fraction, "building pyramid")
        ),
    )
    result = WaveformResult(
        cache_version=manifest.cache_version,
        source_hash=manifest.source_hash,
        sample_rate=manifest.sample_rate,
        frame_count=manifest.frame_count,
        channel_count=manifest.channel_count,
        final_bucket_frames=manifest.frame_count % BASE_BUCKET_FRAMES or BASE_BUCKET_FRAMES,
        levels=manifest.levels,
        manifest_path=str((Path(cache_dir) / "manifest.json").resolve()),
    )
    # The backend verifies this payload before publishing it.
    _send(make_completed(job_id, result.model_dump(mode="json")))


def _execute_job(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Run one job to a terminal report. Never raises out of the thread."""
    job_id = payload.job_id
    try:
        if payload.job_type is JobType.PROBE:
            _run_probe(payload, cancel_event)
        elif payload.job_type is JobType.CANONICAL_DECODE:
            _run_canonical_decode(payload, cancel_event)
        elif payload.job_type is JobType.MONITORING_DOWNMIX:
            _run_monitoring_downmix(payload, cancel_event)
        elif payload.job_type is JobType.PLAYBACK_RATE:
            _run_playback_rate(payload, cancel_event)
        elif payload.job_type is JobType.WAVEFORM:
            _run_waveform(payload, cancel_event)
        elif payload.job_type is JobType.EXPORT:
            _run_export(payload, cancel_event)
        else:
            # Defensive: every protocol-v2 type is implemented, but a newer
            # protocol version may carry a type this worker does not know.
            _send(  # type: ignore[unreachable]
                make_failed(
                    job_id,
                    ERR_NOT_IMPLEMENTED,
                    f"job type {payload.job_type.value!r} is implemented in a later milestone",
                )
            )
    except (
        ProbeCancelledError,
        DecodeCancelledError,
        DerivedCancelledError,
        WaveformCancelledError,
        ExportCancelledError,
    ):
        removed = _remove_staging(payload.staging_dir)
        _log(f"job {job_id} cancelled; staging removed={removed}")
        _send(make_cancelled(job_id, staging_removed=removed))
    except ProbeError as exc:
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} failed: {_probe_error_code(exc)}: {exc}")
        _send(make_failed(job_id, _probe_error_code(exc), str(exc)))
    except DecodeError as exc:
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} failed: {_decode_error_code(exc)}: {exc}")
        _send(make_failed(job_id, _decode_error_code(exc), str(exc)))
    except DerivedError as exc:
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} failed: {_derived_error_code(exc)}: {exc}")
        _send(make_failed(job_id, _derived_error_code(exc), str(exc)))
    except WaveformError as exc:
        # The engine already removed the cache directory on failure.
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} failed: WAVEFORM_FAILED: {exc}")
        _send(make_failed(job_id, "WAVEFORM_FAILED", str(exc)))
    except ExportError as exc:
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} failed: {_export_error_code(exc)}: {exc}")
        _send(make_failed(job_id, _export_error_code(exc), str(exc)))
    except Exception as exc:  # noqa: BLE001 - last-resort guard inside the job thread
        _remove_staging(payload.staging_dir)
        _log(f"job {job_id} crashed: {exc!r}")
        _send(make_failed(job_id, ERR_INTERNAL, f"worker failed: {exc!r}"))


class _ActiveJob:
    """State for the single in-flight job."""

    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.job_id: Any = None


_active = _ActiveJob()


def _handle_run(payload: RunPayload) -> None:
    if _active.thread is not None and _active.thread.is_alive():
        _send(
            make_error(
                ERR_INTERNAL,
                "a job is already running; the manager must serialize jobs",
            )
        )
        return
    staging = Path(payload.staging_dir)
    try:
        staging.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _send(
            make_failed(
                payload.job_id,
                "STAGING_ERROR",
                f"cannot create staging directory: {exc}",
            )
        )
        return
    _active.cancel_event = threading.Event()
    _active.job_id = payload.job_id
    _active.thread = threading.Thread(
        target=_execute_job,
        args=(payload, _active.cancel_event),
        name=f"media-job-{payload.job_id.hex[:8]}",
        daemon=True,
    )
    _active.thread.start()
    _log(f"job {payload.job_id} ({payload.job_type.value}) started")


def _handle_cancel(job_id: Any) -> None:
    if _active.job_id == job_id and _active.thread is not None:
        _active.cancel_event.set()
        _log(f"cancel requested for job {job_id}")
    else:
        _log(f"cancel ignored: no running job {job_id}")


def _handle_shutdown() -> int:
    if _active.thread is not None and _active.thread.is_alive():
        _active.cancel_event.set()
        _active.thread.join(timeout=_JOB_THREAD_JOIN_SECONDS)
        if _active.thread.is_alive():
            _log("job thread did not stop within the join timeout; proceeding")
    _send(make_stopped(0))
    _log("shutdown requested; stopping")
    return 0


def _handle(message: WorkerMessage) -> int | None:
    """Handle one validated, version-matched message.

    Returns a process exit code when the worker should stop,
    or None to keep running.
    """
    if isinstance(message, DescribeMessage):
        _send(
            make_capabilities(
                WORKER_NAME,
                capabilities=[
                    Capability(
                        id="media.probe",
                        description="Inspect a media file and report its audio streams.",
                    ),
                    Capability(
                        id="media.canonical_decode",
                        description="Decode the selected stream to canonical PCM (M1.5).",
                    ),
                    Capability(
                        id="media.monitoring_downmix",
                        description="Build a stereo monitoring downmix (M1.7).",
                    ),
                    Capability(
                        id="media.playback_rate",
                        description="Convert to a playback sample rate (M1.7).",
                    ),
                    Capability(
                        id="media.waveform",
                        description="Generate waveform peaks (M1.8).",
                    ),
                    Capability(
                        id="media.export",
                        description="Export selected stems as WAV files (M2.13).",
                    ),
                ],
                models=[],
            )
        )
        return None
    if isinstance(message, PingMessage):
        _send(make_pong(message.payload.nonce, request_id=message.message_id))
        return None
    if isinstance(message, RunMessage):
        _handle_run(message.payload)
        return None
    if isinstance(message, CancelMessage):
        _handle_cancel(message.payload.job_id)
        return None
    if isinstance(message, ShutdownMessage):
        return _handle_shutdown()
    _send(
        make_error(
            ERR_UNKNOWN_TYPE,
            f"unknown message type {message.type!r}",
            request_id=message.message_id,
        )
    )
    return None


def run() -> int:
    try:
        _send(make_hello(WORKER_NAME))
        _log(f"hello emitted (protocol v{PROTOCOL_VERSION}); awaiting stdin")
        stdin = sys.stdin.buffer
        while True:
            line = stdin.readline()
            if not line:
                _log("stdin EOF; stopping")
                return 0
            line = line.rstrip(b"\r\n")
            if not line:
                continue
            if len(line) > MAX_MESSAGE_BYTES:
                _log(f"oversized message ({len(line)} bytes); rejecting")
                _send(make_error(ERR_OVERSIZED, f"message exceeds {MAX_MESSAGE_BYTES} bytes"))
                continue
            try:
                message = decode_message(line)
            except Exception as exc:
                _log(f"malformed message: {exc}")
                _send(make_error(ERR_MALFORMED, str(exc)))
                continue
            if message.protocol_version != PROTOCOL_VERSION:
                _log(f"version mismatch: got {message.protocol_version}, want {PROTOCOL_VERSION}")
                _send(
                    make_error(
                        ERR_VERSION_MISMATCH,
                        f"protocol version {message.protocol_version} is not supported",
                        request_id=message.message_id,
                    )
                )
                continue
            exit_code = _handle(message)
            if exit_code is not None:
                return exit_code
    except Exception as exc:  # noqa: BLE001 - last-resort guard: log, structured error, exit 1
        _log(f"unexpected worker exception: {exc!r}")
        with contextlib.suppress(Exception):
            _send(make_error(ERR_INTERNAL, f"worker failed: {exc!r}"))
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; ``--memory-limit-mb`` bounds the worker (M2.12 §14.3)."""

    parser = argparse.ArgumentParser(prog="basseparate-media-worker")
    parser.add_argument("--memory-limit-mb", type=int, default=None)
    args = parser.parse_args(argv)
    effective = apply_memory_limit(args.memory_limit_mb)
    if effective is not None:
        _log(f"address-space limit set to {effective // (1024 * 1024)} MiB")
    return run()


def apply_memory_limit(limit_mb: int | None) -> int | None:
    """Best-effort ``RLIMIT_AS`` for this process (M2.12, spec §14.3).

    Returns the effective soft limit in bytes, or ``None`` when the
    platform has no ``resource`` module, the current limit is already
    stricter, or the change was refused. Never fatal: the guard is a
    safety net, not a correctness requirement.
    """

    if limit_mb is None or limit_mb <= 0:
        return None
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX platforms only
        return None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return None
    if soft != resource.RLIM_INFINITY and soft <= limit_mb * 1024 * 1024:
        return int(soft)
    target = limit_mb * 1024 * 1024
    if hard != resource.RLIM_INFINITY:
        target = min(target, int(hard))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (target, hard))
    except (OSError, ValueError):  # pragma: no cover - refused by the OS
        return None
    return int(target)


if __name__ == "__main__":
    raise SystemExit(main())
