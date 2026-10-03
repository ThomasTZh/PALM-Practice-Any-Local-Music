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

import asyncio
import contextlib
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from basseparate.domain.media_job import JobStage, JobType
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
from basseparate.media.probe import (
    NoAudioStreamError,
    ProbeCancelledError,
    ProbeError,
    ProbeFailedError,
    ProbeTimeoutError,
    UnsupportedMediaError,
    probe_media,
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


def _as_int_param(parameters: dict[str, Any], name: str, minimum: int, maximum: int) -> int:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
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


def _execute_job(payload: RunPayload, cancel_event: threading.Event) -> None:
    """Run one job to a terminal report. Never raises out of the thread."""
    job_id = payload.job_id
    try:
        if payload.job_type is JobType.PROBE:
            _run_probe(payload, cancel_event)
        elif payload.job_type is JobType.CANONICAL_DECODE:
            _run_canonical_decode(payload, cancel_event)
        else:
            _send(
                make_failed(
                    job_id,
                    ERR_NOT_IMPLEMENTED,
                    f"job type {payload.job_type.value!r} is implemented in a later milestone",
                )
            )
    except (ProbeCancelledError, DecodeCancelledError):
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
                        description="Build a monitoring downmix (M1.6).",
                    ),
                    Capability(
                        id="media.playback_rate",
                        description="Convert to a playback sample rate (M1.6).",
                    ),
                    Capability(
                        id="media.waveform",
                        description="Generate waveform peaks (M1.7).",
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


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
