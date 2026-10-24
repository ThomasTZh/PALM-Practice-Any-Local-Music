"""Activation validation, publication, and run orchestration (M3.4, §6)."""

from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.rhythm import RhythmAnalysisRun, RhythmAnalysisStatus
from basseparate.rhythm import (
    BEAT_FILE,
    DOWNBEAT_FILE,
    ActivationRequest,
    RhythmActivationCancelled,
    RhythmActivationFailed,
    RhythmActivationInvalid,
    RhythmActivationStore,
    artifact_content_hash,
    build_manifest,
    run_and_publish,
    validate_activation_array,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ProjectRepository, RhythmRepository

HASH = "ab" * 32
NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


def _request(tmp_path: Path, *, staging: str = "staging") -> ActivationRequest:
    input_path = tmp_path / "prepared.pcm"
    input_path.write_bytes(np.zeros(200, dtype="<f4").tobytes())
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"checkpoint")
    return ActivationRequest(
        run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        input_path=input_path,
        input_hash=HASH,
        staging_dir=tmp_path / staging,
        checkpoint_path=checkpoint,
        model_id="beat_this_final0",
        model_manifest_hash="cd" * 32,
        adapter_version="beat-this-adapter-v1",
        project_sample_rate=48_000,
    )


def _running_run(request: ActivationRequest) -> RhythmAnalysisRun:
    return RhythmAnalysisRun(
        id=request.run_id,
        project_id=request.project_id,
        input_asset_id=uuid.uuid4(),
        input_hash=HASH,
        input_role="original_mix",
        model_manifest_id="beat_this_final0",
        model_manifest_hash="cd" * 32,
        model_preset="final0",
        adapter_version="beat-this-adapter-v1",
        preprocessing_profile="beat-this-logmel-22050-441-v1",
        preprocessing_version=1,
        requested_device="cpu",
        actual_device="cpu",
        started_at=NOW,
        status=RhythmAnalysisStatus.RUNNING,
    )


class TestArrayValidation:
    def test_valid_float32(self, tmp_path: Path) -> None:
        path = tmp_path / BEAT_FILE
        np.save(path, np.linspace(-1.0, 1.0, 64, dtype=np.float32))
        digest = validate_activation_array(path, 64)
        assert len(digest) == 64
        assert digest == validate_activation_array(path, 64)

    @pytest.mark.parametrize("bad", ["int16", "float64", "nan", "shape"])
    def test_invalid_arrays(self, tmp_path: Path, bad: str) -> None:
        path = tmp_path / BEAT_FILE
        if bad == "int16":
            np.save(path, np.arange(64, dtype=np.int16))
        elif bad == "float64":
            np.save(path, np.arange(64, dtype=np.float64))
        elif bad == "nan":
            values = np.zeros(64, dtype=np.float32)
            values[3] = np.nan
            np.save(path, values)
        else:
            np.save(path, np.zeros((8, 8), dtype=np.float32))
        with pytest.raises(RhythmActivationInvalid):
            validate_activation_array(path, 64)

    def test_wrong_length_and_missing(self, tmp_path: Path) -> None:
        path = tmp_path / BEAT_FILE
        np.save(path, np.zeros(10, dtype=np.float32))
        with pytest.raises(RhythmActivationInvalid):
            validate_activation_array(path, 11)
        with pytest.raises(RhythmActivationInvalid):
            validate_activation_array(tmp_path / "missing.npy", 1)


class TestStore:
    def test_publish_verify_and_manifest(self, tmp_path: Path) -> None:
        request = _request(tmp_path)
        staging = request.staging_dir
        staging.mkdir()
        beat = staging / BEAT_FILE
        downbeat = staging / DOWNBEAT_FILE
        np.save(beat, np.zeros(12, dtype=np.float32))
        np.save(downbeat, np.zeros(12, dtype=np.float32))
        beat_sha = validate_activation_array(beat, 12)
        downbeat_sha = validate_activation_array(downbeat, 12)
        manifest = build_manifest(
            request,
            beat_sha256=beat_sha,
            downbeat_sha256=downbeat_sha,
            frame_count=12,
            artifact_id=uuid.uuid4(),
            source_asset_id=uuid.uuid4(),
            output_semantics="test logits",
        )
        assert manifest.content_hash == artifact_content_hash(
            beat_sha256=beat_sha,
            downbeat_sha256=downbeat_sha,
            model_id=request.model_id,
            model_manifest_hash=request.model_manifest_hash,
            adapter_version=request.adapter_version,
            source_hash=request.input_hash,
        )
        store = RhythmActivationStore(tmp_path / "rhythm")
        path = store.publish(
            manifest.artifact_id,
            beat_path=beat,
            downbeat_path=downbeat,
            manifest=manifest,
        )
        assert (path / BEAT_FILE).is_file()
        assert (path / "manifest.json").is_file()
        assert store.verify(manifest)
        (path / BEAT_FILE).write_bytes(b"tampered")
        assert not store.verify(manifest)

    def test_duplicate_publish_rejected(self, tmp_path: Path) -> None:
        request = _request(tmp_path)
        staging = request.staging_dir
        staging.mkdir()
        beat = staging / BEAT_FILE
        downbeat = staging / DOWNBEAT_FILE
        np.save(beat, np.zeros(4, dtype=np.float32))
        np.save(downbeat, np.zeros(4, dtype=np.float32))
        manifest = build_manifest(
            request,
            beat_sha256=validate_activation_array(beat, 4),
            downbeat_sha256=validate_activation_array(downbeat, 4),
            frame_count=4,
            artifact_id=uuid.uuid4(),
            source_asset_id=uuid.uuid4(),
            output_semantics="test",
        )
        store = RhythmActivationStore(tmp_path / "rhythm")
        store.publish(
            manifest.artifact_id, beat_path=beat, downbeat_path=downbeat, manifest=manifest
        )
        with pytest.raises(Exception, match="already exists"):
            store.publish(
                manifest.artifact_id,
                beat_path=beat,
                downbeat_path=downbeat,
                manifest=manifest,
            )


FAKE_WORKER = r"""
import json, os, sys, uuid
from pathlib import Path

def send(kind, payload):
    print(json.dumps({"protocol_version": 2, "message_id": str(uuid.uuid4()),
                      "request_id": None, "type": kind, "payload": payload}), flush=True)

send("hello", {"worker": "fake_rhythm", "protocol_version": 2})
mode = os.environ.get("FAKE_RHYTHM_MODE", "success")
for line in sys.stdin:
    message = json.loads(line)
    kind = message.get("type")
    if kind == "run":
        payload = message["payload"]
        job_id = payload["job_id"]
        staging = Path(payload["staging_dir"])
        staging.mkdir(parents=True, exist_ok=True)
        params = payload.get("parameters", {})
        frames = int(params.get("fake_frames", 12))
        send("progress", {"job_id": job_id, "stage": "running_inference",
                          "fraction": None, "detail": "fake inference"})
        if mode == "cancel":
            for inner in sys.stdin:
                if json.loads(inner).get("type") == "cancel":
                    send("cancelled", {"job_id": job_id, "staging_removed": False})
                    break
            continue
        if mode == "fail":
            send("failed", {"job_id": job_id, "code": "FAKE_FAILURE", "message": "boom"})
            continue
        import numpy as np
        np.save(staging / "beat.npy", np.linspace(-1, 1, frames, dtype=np.float32))
        np.save(staging / "downbeat.npy", np.linspace(1, -1, frames, dtype=np.float32))
        send("completed", {"job_id": job_id, "result": {
            "status": "complete", "frame_count": frames, "load_seconds": 0.1,
            "inference_seconds": 0.2, "peak_host_rss_kib": 1024,
            "peak_device_memory_bytes": None}})
    elif kind == "shutdown":
        send("stopped", {"exit_code": 0})
        break
"""


@pytest.fixture()
def fake_worker(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    return [sys.executable, str(script)]


class TestRunAndPublish:
    def test_success_publishes_artifact_and_completes_run(
        self, db_path: Path, tmp_path: Path, fake_worker: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        projects = ProjectRepository(db_path)
        project = projects.create_project("Rhythm")
        request = replace(_request(tmp_path), project_id=project.id)
        run = _running_run(request)
        repo = RhythmRepository(db_path)
        repo.create_run(run)
        store = RhythmActivationStore(tmp_path / "rhythm")
        monkeypatch.setenv("FAKE_RHYTHM_MODE", "success")
        progress: list[tuple[str, float | None, str | None]] = []

        completed, manifest = run_and_publish(
            run=run,
            request=request,
            store=store,
            repository=repo,
            source_asset_id=uuid.uuid4(),
            output_semantics="test logits",
            worker_command=fake_worker,
            on_progress=lambda stage, fraction, detail: progress.append(
                (stage.value, fraction, detail)
            ),
        )

        assert completed.status is RhythmAnalysisStatus.COMPLETED
        assert completed.activation_artifact_id == manifest.artifact_id
        assert completed.runtime_metrics["load_seconds"] == pytest.approx(0.1)
        assert completed.peak_host_memory_bytes == 1024 * 1024
        assert repo.get_run(run.id) == completed
        assert repo.get_artifact(manifest.artifact_id) == manifest
        assert store.verify(manifest)
        assert manifest.frame_mapping.project_sample_rate == 48_000
        assert manifest.model_frame_count == 12
        assert progress and progress[0][0] == "running_inference"
        assert not request.staging_dir.exists()

    def test_failure_updates_run_and_keeps_no_artifact(
        self, db_path: Path, tmp_path: Path, fake_worker: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        projects = ProjectRepository(db_path)
        project = projects.create_project("Rhythm")
        request = replace(_request(tmp_path), project_id=project.id)
        run = _running_run(request)
        repo = RhythmRepository(db_path)
        repo.create_run(run)
        store = RhythmActivationStore(tmp_path / "rhythm")
        monkeypatch.setenv("FAKE_RHYTHM_MODE", "fail")

        with pytest.raises(RhythmActivationFailed) as excinfo:
            run_and_publish(
                run=run,
                request=request,
                store=store,
                repository=repo,
                source_asset_id=uuid.uuid4(),
                output_semantics="test",
                worker_command=fake_worker,
            )
        assert excinfo.value.code == "FAKE_FAILURE"
        stored = repo.get_run(run.id)
        assert stored is not None and stored.status is RhythmAnalysisStatus.FAILED
        assert repo.list_artifacts_for_project(project.id) == []
        assert not request.staging_dir.exists()

    def test_cancellation_updates_run(
        self, db_path: Path, tmp_path: Path, fake_worker: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        projects = ProjectRepository(db_path)
        project = projects.create_project("Rhythm")
        request = replace(_request(tmp_path), project_id=project.id)
        run = _running_run(request)
        repo = RhythmRepository(db_path)
        repo.create_run(run)
        store = RhythmActivationStore(tmp_path / "rhythm")
        monkeypatch.setenv("FAKE_RHYTHM_MODE", "cancel")
        cancel = threading.Event()
        cancel.set()

        with pytest.raises(RhythmActivationCancelled):
            run_and_publish(
                run=run,
                request=request,
                store=store,
                repository=repo,
                source_asset_id=uuid.uuid4(),
                output_semantics="test",
                worker_command=fake_worker,
                cancel_event=cancel,
            )
        stored = repo.get_run(run.id)
        assert stored is not None and stored.status is RhythmAnalysisStatus.CANCELLED
        assert repo.list_artifacts_for_project(project.id) == []
