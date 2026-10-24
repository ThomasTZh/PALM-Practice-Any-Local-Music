"""Rhythm persistence and restart recovery (M3.18, spec §20.5-§20.7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ProjectRepository, RhythmRepository

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


def _run(project_id: uuid.UUID, status: RhythmAnalysisStatus, **updates) -> RhythmAnalysisRun:
    started = NOW
    ended = NOW + timedelta(seconds=1) if status not in {
        RhythmAnalysisStatus.QUEUED,
        RhythmAnalysisStatus.RUNNING,
    } else None
    values = {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "input_asset_id": uuid.uuid4(),
        "input_hash": "ab" * 32,
        "input_role": "original_mix",
        "model_manifest_id": "beat_this_final0",
        "model_manifest_hash": "ef" * 32,
        "model_preset": "final0",
        "adapter_version": "beat-this-adapter-v1",
        "preprocessing_profile": "beat-this-logmel-22050-441-v1",
        "preprocessing_version": 1,
        "requested_device": "cpu",
        "actual_device": "cpu" if status is not RhythmAnalysisStatus.QUEUED else None,
        "status": status,
        "started_at": None if status is RhythmAnalysisStatus.QUEUED else started,
        "ended_at": ended,
        "activation_artifact_id": (
            uuid.uuid4() if status is RhythmAnalysisStatus.COMPLETED else None
        ),
    }
    values.update(updates)
    return RhythmAnalysisRun(**values)


def test_running_runs_become_interrupted_and_stay_restartable(tmp_path: Path) -> None:
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    project = ProjectRepository(db).create_project("Recovery")
    repository = RhythmRepository(db)

    running = _run(project.id, RhythmAnalysisStatus.RUNNING)
    completed = _run(project.id, RhythmAnalysisStatus.COMPLETED)
    queued = _run(project.id, RhythmAnalysisStatus.QUEUED)
    repository.create_run(running)
    repository.create_run(completed)
    repository.create_run(queued)

    assert repository.mark_interrupted() == 1

    recovered = repository.get_run(running.id)
    assert recovered is not None
    assert recovered.status is RhythmAnalysisStatus.INTERRUPTED
    assert recovered.ended_at is not None
    assert repository.get_run(completed.id) == completed
    assert repository.get_run(queued.id) == queued


def test_interrupted_run_keeps_published_stages(tmp_path: Path) -> None:
    """Restart recovery never deletes artifacts or results of earlier stages."""
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    project = ProjectRepository(db).create_project("Recovery stages")
    repository = RhythmRepository(db)

    artifact_id = uuid.uuid4()
    running = _run(project.id, RhythmAnalysisStatus.RUNNING)
    repository.create_run(running)
    repository.create_artifact(
        project.id,
        ActivationArtifactManifest(
            artifact_id=artifact_id,
            content_hash="cd" * 32,
            parent_run_id=running.id,
            source_asset_id=running.input_asset_id,
            source_hash=running.input_hash,
            model_frame_count=1,
            beat=ActivationArrayRef(relative_path="beat.npy", sha256="ab" * 32, element_count=1),
            downbeat=ActivationArrayRef(
                relative_path="downbeat.npy", sha256="ef" * 32, element_count=1
            ),
            frame_mapping=ActivationFrameMapping(
                model_sample_rate=22_050, project_sample_rate=48_000, frame_hop=441
            ),
            output_semantics="test",
        ),
    )

    repository.mark_interrupted()

    assert repository.get_artifact(artifact_id) is not None
    recovered = repository.get_run(running.id)
    assert recovered is not None
    # The run record itself never references an artifact before completion;
    # the artifact row is durable and reusable by the restarted run.
    assert recovered.status is RhythmAnalysisStatus.INTERRUPTED
