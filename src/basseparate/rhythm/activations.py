"""Beat This! activation execution and publication (M3.4, milestone3.md §6).

The application-side service validates the request and model installation,
runs the isolated rhythm worker, validates the returned framewise arrays,
and publishes an immutable activation artifact:

    data/rhythm/activations/<artifact_id>/
        beat.npy
        downbeat.npy
        manifest.json

Publication is staged and renamed atomically, so a cancelled or failed
run never leaves a complete artifact. The worker never writes outside its
assigned staging directory and never touches the database.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from basseparate.domain.media_job import JobStage
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
)
from basseparate.domain.rhythm_input import BEAT_THIS_INPUT_PROFILE
from basseparate.storage.repository import RhythmRepository
from basseparate.worker import (
    CancelledMessage,
    CompletedMessage,
    FailedMessage,
    ProgressMessage,
    WorkerExitedError,
    WorkerSupervisor,
    WorkerSupervisorError,
    WorkerTimeoutError,
    assert_protocol_version,
    make_cancel,
    rhythm_worker_command,
)

BEAT_FILE = "beat.npy"
DOWNBEAT_FILE = "downbeat.npy"
MANIFEST_FILE = "manifest.json"
MODEL_SAMPLE_RATE = 22_050
FRAME_HOP = 441
DEFAULT_TIMEOUT_SECONDS = 3_600.0

ProgressCallback = Callable[[JobStage, float | None, str | None], None]


class RhythmActivationError(Exception):
    """Base class for activation execution/publication failures."""


class RhythmActivationInvalid(RhythmActivationError):
    """The worker's activation files are missing, malformed, or non-finite."""


class RhythmActivationCancelled(RhythmActivationError):
    """The activation run was cancelled."""


class RhythmActivationFailed(RhythmActivationError):
    """The activation run failed with a worker or validation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ActivationRequest:
    """One activation run's inputs (all paths are backend-owned)."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    input_path: Path
    input_hash: str
    staging_dir: Path
    checkpoint_path: Path
    model_id: str
    model_manifest_hash: str
    adapter_version: str
    project_sample_rate: int
    device: str = "cpu"
    threads: int = 4
    float16: bool = False


@dataclass(frozen=True)
class ActivationWorkerResult:
    """Validated result metadata returned by the rhythm worker."""

    frame_count: int
    result: dict[str, Any]

    @property
    def timings(self) -> dict[str, float]:
        return {
            key: float(self.result[key])
            for key in ("load_seconds", "inference_seconds")
            if key in self.result
        }

    @property
    def peak_host_memory_bytes(self) -> int | None:
        value = self.result.get("peak_host_rss_kib")
        return int(value) * 1024 if isinstance(value, (int, float)) else None

    @property
    def peak_device_memory_bytes(self) -> int | None:
        value = self.result.get("peak_device_memory_bytes")
        return int(value) if isinstance(value, (int, float)) else None


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def validate_activation_array(path: Path, expected_frames: int) -> str:
    """Validate one activation `.npy` array; return its SHA-256.

    Enforces float32, one dimension, exact frame count, and finite values
    without loading the whole array into memory.
    """
    if not path.is_file():
        raise RhythmActivationInvalid(f"activation array missing: {path.name}")
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RhythmActivationInvalid(f"cannot read {path.name}: {exc}") from exc
    if array.dtype != np.float32:
        raise RhythmActivationInvalid(
            f"{path.name} dtype must be float32, got {array.dtype}"
        )
    if array.ndim != 1:
        raise RhythmActivationInvalid(f"{path.name} must be one-dimensional")
    if int(array.size) != expected_frames:
        raise RhythmActivationInvalid(
            f"{path.name} has {array.size} frames, expected {expected_frames}"
        )
    for start in range(0, int(array.size), 1 << 20):
        if not bool(np.isfinite(array[start : start + (1 << 20)]).all()):
            raise RhythmActivationInvalid(f"{path.name} contains non-finite values")
    return _sha256_file(path)


def artifact_content_hash(
    *,
    beat_sha256: str,
    downbeat_sha256: str,
    model_id: str,
    model_manifest_hash: str,
    adapter_version: str,
    source_hash: str,
) -> str:
    """Deterministic content identity of one activation pair."""
    payload = {
        "artifact": "beat-downbeat-activations",
        "version": 1,
        "beat": beat_sha256,
        "downbeat": downbeat_sha256,
        "model_id": model_id,
        "model_manifest_hash": model_manifest_hash,
        "adapter_version": adapter_version,
        "source_hash": source_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class RhythmActivationStore:
    """Managed immutable activation-artifact store under ``data/rhythm``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.staging = self.root / ".staging"
        self.artifacts = self.root / "activations"

    def artifact_dir(self, artifact_id: uuid.UUID) -> Path:
        return self.artifacts / str(artifact_id)

    def publish(
        self,
        artifact_id: uuid.UUID,
        *,
        beat_path: Path,
        downbeat_path: Path,
        manifest: ActivationArtifactManifest,
    ) -> Path:
        """Copy staged arrays + manifest into the store and rename atomically."""
        self.staging.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        destination = self.artifact_dir(artifact_id)
        if destination.exists():
            raise RhythmActivationError(f"activation artifact {artifact_id} already exists")
        tmp = self.staging / f"{artifact_id}.{uuid.uuid4().hex}.tmp"
        tmp.mkdir(parents=True)
        try:
            shutil.copyfile(beat_path, tmp / BEAT_FILE)
            shutil.copyfile(downbeat_path, tmp / DOWNBEAT_FILE)
            for name in (BEAT_FILE, DOWNBEAT_FILE):
                with open(tmp / name, "rb") as handle:
                    import os

                    os.fsync(handle.fileno())
            (tmp / MANIFEST_FILE).write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            tmp.replace(destination)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return destination

    def verify(self, manifest: ActivationArtifactManifest) -> bool:
        """Check both files and their recorded hashes."""
        directory = self.artifact_dir(manifest.artifact_id)
        beat = directory / BEAT_FILE
        downbeat = directory / DOWNBEAT_FILE
        if not beat.is_file() or not downbeat.is_file():
            return False
        return (
            _sha256_file(beat) == manifest.beat.sha256
            and _sha256_file(downbeat) == manifest.downbeat.sha256
        )


def _worker_payload(
    request: ActivationRequest, *, max_threads: int
) -> dict[str, Any]:
    return {
        "protocol_version": 2,
        "message_id": str(uuid.uuid4()),
        "request_id": None,
        "type": "run",
        "payload": {
            "job_id": str(request.run_id),
            "job_type": "rhythm_activation",
            "source_path": str(request.input_path),
            "staging_dir": str(request.staging_dir),
            "max_threads": max_threads,
            "parameters": {
                "checkpoint_path": str(request.checkpoint_path),
                "model_id": request.model_id,
                "model_manifest_hash": request.model_manifest_hash,
                "adapter_version": request.adapter_version,
                "input_hash": request.input_hash,
                "device": request.device,
                "float16": request.float16,
            },
        },
    }


def run_activation_worker(
    request: ActivationRequest,
    *,
    worker_command: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ActivationWorkerResult:
    """Run the isolated worker and return validated result metadata."""
    if not request.input_path.is_file():
        raise RhythmActivationError(f"prepared input missing: {request.input_path}")
    if not request.checkpoint_path.is_file():
        raise RhythmActivationError(
            f"model checkpoint missing: {request.checkpoint_path}; install it explicitly"
        )
    request.staging_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_worker_payload(request, max_threads=request.threads)).encode()
    deadline = time.monotonic() + timeout_seconds
    cancel_sent = False
    try:
        with WorkerSupervisor(
            command=worker_command or rhythm_worker_command(), cwd=Path.cwd()
        ) as supervisor:
            hello = supervisor.wait_for_handshake()
            assert_protocol_version(hello)
            supervisor.send_raw(payload)
            while True:
                if cancel_event is not None and cancel_event.is_set() and not cancel_sent:
                    supervisor.send(make_cancel(request.run_id))
                    cancel_sent = True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RhythmActivationError("rhythm worker timed out")
                try:
                    message = supervisor.receive(timeout=min(0.5, remaining))
                except WorkerTimeoutError:
                    continue
                if isinstance(message, ProgressMessage):
                    if on_progress is not None:
                        on_progress(
                            message.payload.stage,
                            message.payload.fraction,
                            message.payload.detail,
                        )
                    continue
                if isinstance(message, CompletedMessage):
                    result = message.payload.result
                    frames = int(result.get("frame_count", -1))
                    if frames <= 0:
                        raise RhythmActivationInvalid(
                            "worker reported a non-positive frame count"
                        )
                    return ActivationWorkerResult(frame_count=frames, result=result)
                if isinstance(message, CancelledMessage):
                    raise RhythmActivationCancelled()
                if isinstance(message, FailedMessage):
                    raise RhythmActivationFailed(
                        message.payload.code, message.payload.message
                    )
    except (WorkerExitedError, WorkerSupervisorError) as exc:
        raise RhythmActivationError(f"rhythm worker failed: {exc}") from exc


def build_manifest(
    request: ActivationRequest,
    *,
    beat_sha256: str,
    downbeat_sha256: str,
    frame_count: int,
    artifact_id: uuid.UUID,
    source_asset_id: uuid.UUID,
    output_semantics: str,
) -> ActivationArtifactManifest:
    return ActivationArtifactManifest(
        artifact_id=artifact_id,
        content_hash=artifact_content_hash(
            beat_sha256=beat_sha256,
            downbeat_sha256=downbeat_sha256,
            model_id=request.model_id,
            model_manifest_hash=request.model_manifest_hash,
            adapter_version=request.adapter_version,
            source_hash=request.input_hash,
        ),
        parent_run_id=request.run_id,
        source_asset_id=source_asset_id,
        source_hash=request.input_hash,
        model_frame_count=frame_count,
        beat=ActivationArrayRef(
            relative_path=BEAT_FILE, sha256=beat_sha256, element_count=frame_count
        ),
        downbeat=ActivationArrayRef(
            relative_path=DOWNBEAT_FILE,
            sha256=downbeat_sha256,
            element_count=frame_count,
        ),
        frame_mapping=ActivationFrameMapping(
            model_sample_rate=MODEL_SAMPLE_RATE,
            project_sample_rate=request.project_sample_rate,
            frame_hop=FRAME_HOP,
        ),
        preprocessing_transform={
            "recipe": BEAT_THIS_INPUT_PROFILE.recipe,
            "profile_version": BEAT_THIS_INPUT_PROFILE.profile_version,
            "channel_transform": BEAT_THIS_INPUT_PROFILE.channel_transform,
            "amplitude_transform": BEAT_THIS_INPUT_PROFILE.amplitude_transform,
            "long_track_strategy": BEAT_THIS_INPUT_PROFILE.long_track_strategy,
        },
        output_semantics=output_semantics,
    )


def _transition(
    run: RhythmAnalysisRun,
    status: RhythmAnalysisStatus,
    *,
    warnings: list[str],
    activation_artifact_id: uuid.UUID | None = None,
    metrics: dict[str, float] | None = None,
    peak_host_memory_bytes: int | None = None,
    peak_device_memory_bytes: int | None = None,
) -> RhythmAnalysisRun:
    data = run.model_dump()
    data.update(
        {
            "status": status,
            "ended_at": _now(),
            "warnings": [*run.warnings, *warnings][-128:],
        }
    )
    if activation_artifact_id is not None:
        data["activation_artifact_id"] = activation_artifact_id
    if metrics is not None:
        data["runtime_metrics"] = metrics
    if peak_host_memory_bytes is not None:
        data["peak_host_memory_bytes"] = peak_host_memory_bytes
    if peak_device_memory_bytes is not None:
        data["peak_device_memory_bytes"] = peak_device_memory_bytes
    return RhythmAnalysisRun.model_validate(data)


def run_and_publish(
    *,
    run: RhythmAnalysisRun,
    request: ActivationRequest,
    store: RhythmActivationStore,
    repository: RhythmRepository,
    source_asset_id: uuid.UUID,
    output_semantics: str,
    worker_command: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[RhythmAnalysisRun, ActivationArtifactManifest]:
    """Run inference, validate arrays, publish the artifact, and update the run.

    On cancellation or failure the durable run is updated to its terminal
    state and staged arrays are removed. Previously published artifacts and
    result sets are never touched.
    """
    if run.id != request.run_id or run.project_id != request.project_id:
        raise ValueError("the run record does not match the activation request")
    if run.status is not RhythmAnalysisStatus.RUNNING:
        raise ValueError("activation publication requires a running run record")

    try:
        worker_result = run_activation_worker(
            request,
            worker_command=worker_command,
            cancel_event=cancel_event,
            on_progress=on_progress,
            timeout_seconds=timeout_seconds,
        )
        beat_path = request.staging_dir / BEAT_FILE
        downbeat_path = request.staging_dir / DOWNBEAT_FILE
        beat_sha256 = validate_activation_array(beat_path, worker_result.frame_count)
        downbeat_sha256 = validate_activation_array(
            downbeat_path, worker_result.frame_count
        )
        artifact_id = uuid.uuid4()
        manifest = build_manifest(
            request,
            beat_sha256=beat_sha256,
            downbeat_sha256=downbeat_sha256,
            frame_count=worker_result.frame_count,
            artifact_id=artifact_id,
            source_asset_id=source_asset_id,
            output_semantics=output_semantics,
        )
        store.publish(
            artifact_id,
            beat_path=beat_path,
            downbeat_path=downbeat_path,
            manifest=manifest,
        )
        repository.create_artifact(request.project_id, manifest)
        completed = _transition(
            run,
            RhythmAnalysisStatus.COMPLETED,
            warnings=[],
            activation_artifact_id=artifact_id,
            metrics=worker_result.timings,
            peak_host_memory_bytes=worker_result.peak_host_memory_bytes,
            peak_device_memory_bytes=worker_result.peak_device_memory_bytes,
        )
        repository.save_run(completed)
        shutil.rmtree(request.staging_dir, ignore_errors=True)
        return completed, manifest
    except RhythmActivationCancelled:
        cancelled = _transition(
            run, RhythmAnalysisStatus.CANCELLED, warnings=["activation cancelled"]
        )
        repository.save_run(cancelled)
        shutil.rmtree(request.staging_dir, ignore_errors=True)
        raise
    except RhythmActivationFailed as exc:
        failed = _transition(
            run,
            RhythmAnalysisStatus.FAILED,
            warnings=[f"{exc.code}: {exc.message}"],
        )
        repository.save_run(failed)
        shutil.rmtree(request.staging_dir, ignore_errors=True)
        raise
    except BaseException as exc:
        failed = _transition(
            run,
            RhythmAnalysisStatus.FAILED,
            warnings=[f"RHYTHM_ACTIVATION_FAILED: {exc}"],
        )
        repository.save_run(failed)
        shutil.rmtree(request.staging_dir, ignore_errors=True)
        raise RhythmActivationFailed("RHYTHM_ACTIVATION_FAILED", str(exc)) from exc
