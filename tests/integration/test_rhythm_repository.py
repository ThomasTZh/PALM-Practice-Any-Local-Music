"""Rhythm repository round-trip (M3.1, milestone3.md §3.11).

Verifies that rhythm runs, activation artifacts, and editable branches
persist and read back without altering the project's source/stem timing,
and that branch writes use optimistic revision checks.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.practice import PracticeState
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    BarOriginState,
    GridValidity,
    MeterRegion,
    MeterTempoUnit,
    MusicalPosition,
    ProjectRhythmState,
    PulseAcceptance,
    PulseRole,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmBranchRecord,
    RhythmInputRole,
    RhythmOrigin,
    RhythmPulse,
    SnapMode,
    TempoAnchor,
)
from basseparate.domain.separation import DeviceType
from basseparate.storage.db import DatabaseError, initialize_database
from basseparate.storage.repository import (
    ProjectRepository,
    RhythmBranchStaleRevisionError,
    RhythmRepository,
)

SOURCE_HASH = "ab" * 32
ARTIFACT_HASH = "cd" * 32
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
DURATION = 48_000

SOURCE_COLUMNS = (
    "source_asset_id",
    "canonical_asset_id",
    "sample_rate",
    "duration_frames",
    "source_channel_count",
    "source_channel_layout",
    "status",
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


def _source_columns(db_path: Path, project_id: uuid.UUID) -> dict[str, object]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM projects WHERE id = ?",
            (str(project_id),),
        ).fetchone()
        assert row is not None
        return {column: row[column] for column in SOURCE_COLUMNS}
    finally:
        conn.close()


def _publish_source(db_path: Path, project_id: uuid.UUID) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            UPDATE projects SET
                source_asset_id = ?,
                canonical_asset_id = ?,
                source_stream_index = 0,
                sample_rate = 48000,
                duration_frames = ?,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1,
                source_metadata = '{}',
                status = 'ready'
            WHERE id = ?
            """,
            (str(uuid.uuid4()), str(uuid.uuid4()), DURATION, str(project_id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _run(project_id: uuid.UUID, artifact_id: uuid.UUID) -> RhythmAnalysisRun:
    return RhythmAnalysisRun(
        id=uuid.uuid4(),
        project_id=project_id,
        input_asset_id=uuid.uuid4(),
        input_hash=SOURCE_HASH,
        input_role=RhythmInputRole.ORIGINAL_MIX,
        model_manifest_id="beat_this_final0",
        model_manifest_hash=ARTIFACT_HASH,
        model_preset="final0",
        adapter_version="adapter-1",
        environment_fingerprint={"python": "3.11.15", "torch": "2.9.1"},
        preprocessing_profile="beat-input-v1",
        preprocessing_version=1,
        requested_device=DeviceType.CPU,
        actual_device=DeviceType.CPU,
        started_at=NOW,
        ended_at=NOW,
        status=RhythmAnalysisStatus.COMPLETED,
        activation_artifact_id=artifact_id,
        runtime_metrics={"wall_seconds": 1.5},
    )


def _artifact(project_id: uuid.UUID, run: RhythmAnalysisRun) -> ActivationArtifactManifest:
    assert run.activation_artifact_id is not None
    return ActivationArtifactManifest(
        artifact_id=run.activation_artifact_id,
        content_hash=ARTIFACT_HASH,
        parent_run_id=run.id,
        source_asset_id=run.input_asset_id,
        source_hash=SOURCE_HASH,
        model_frame_count=4,
        beat=ActivationArrayRef(
            relative_path="rhythm/beats.npy", sha256=SOURCE_HASH, element_count=4
        ),
        downbeat=ActivationArrayRef(
            relative_path="rhythm/downbeats.npy", sha256=ARTIFACT_HASH, element_count=4
        ),
        frame_mapping=ActivationFrameMapping(
            model_sample_rate=22_050,
            project_sample_rate=48_000,
            frame_hop=512,
        ),
        output_semantics="sigmoid activation per model frame",
    )


def _pos(numerator: int, denominator: int = 1) -> MusicalPosition:
    return MusicalPosition(numerator=numerator, denominator=denominator)


def _branch(project_id: uuid.UUID, parent_id: uuid.UUID | None = None) -> RhythmBranchRecord:
    branch_id = uuid.uuid4()
    pulse = RhythmPulse(
        id=uuid.uuid4(),
        parent_id=branch_id,
        source_frame=0,
        model_frame_index=0,
        role=PulseRole.DOWNBEAT,
        acceptance=PulseAcceptance.ACCEPTED,
        confidence=Confidence(kind=ConfidenceKind.PROBABILITY, value=0.8),
        origin=RhythmOrigin.AUTOMATIC,
    )
    anchors = [
        TempoAnchor(
            id=uuid.uuid4(),
            branch_id=branch_id,
            source_frame=frame,
            musical_position=position,
            origin=RhythmOrigin.MANUAL,
            created_at=NOW,
            updated_at=NOW,
        )
        for frame, position in ((0, _pos(0)), (DURATION, _pos(2)))
    ]
    region = MeterRegion(
        id=uuid.uuid4(),
        branch_id=branch_id,
        start=_pos(0),
        numerator=4,
        denominator=4,
        grouping=[1, 1, 1, 1],
        display_tempo_unit=MeterTempoUnit.QUARTER,
        origin=RhythmOrigin.MANUAL,
    )
    return RhythmBranchRecord(
        id=branch_id,
        project_id=project_id,
        parent_automatic_result_id=parent_id,
        source_duration_frames=DURATION,
        pulses=[pulse],
        tempo_anchors=anchors,
        meter_regions=[region],
        bar_origin=BarOriginState(first_numbered_bar_position=_pos(0)),
        grid_validity=GridValidity.VALID,
        created_at=NOW,
        updated_at=NOW,
    )


def test_round_trip_and_source_unchanged(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    rhythm = RhythmRepository(db_path)
    project = projects.create_project("Song")
    _publish_source(db_path, project.id)
    before = _source_columns(db_path, project.id)

    run = _run(project.id, uuid.uuid4())
    rhythm.create_run(run)
    manifest = _artifact(project.id, run)
    rhythm.create_artifact(project.id, manifest)
    branch = _branch(project.id, parent_id=uuid.uuid4())
    rhythm.create_branch(branch)

    assert rhythm.get_run(run.id) == run
    assert rhythm.list_runs_for_project(project.id) == [run]
    assert rhythm.get_artifact(manifest.artifact_id) == manifest
    assert rhythm.list_artifacts_for_project(project.id) == [manifest]
    assert rhythm.get_branch(branch.id) == branch
    assert rhythm.list_branches_for_project(project.id) == [branch]

    # Editing a branch never touches source/stem timing or the project row.
    edited = branch.model_copy(update={"grid_validity": GridValidity.UNCERTAIN})
    edited = edited.model_copy(update={"revision": 1})
    rhythm.save_branch(edited, expected_revision=0)
    assert rhythm.get_branch(branch.id) == edited
    assert _source_columns(db_path, project.id) == before


def test_run_status_can_be_updated(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    rhythm = RhythmRepository(db_path)
    project = projects.create_project("Song")
    queued = RhythmAnalysisRun(
        id=uuid.uuid4(),
        project_id=project.id,
        input_asset_id=uuid.uuid4(),
        input_hash=SOURCE_HASH,
        input_role=RhythmInputRole.DRUM_STEM,
        model_manifest_id="beat_this_small0",
        model_manifest_hash=ARTIFACT_HASH,
        model_preset="small0",
        adapter_version="adapter-1",
        preprocessing_profile="beat-input-v1",
        preprocessing_version=1,
        requested_device=DeviceType.CPU,
    )
    rhythm.create_run(queued)
    running = queued.model_copy(
        update={
            "status": RhythmAnalysisStatus.RUNNING,
            "started_at": NOW,
            "actual_device": DeviceType.CPU,
        }
    )
    rhythm.save_run(running)
    assert rhythm.get_run(queued.id) == running


def test_branch_revision_guard(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    rhythm = RhythmRepository(db_path)
    project = projects.create_project("Song")
    branch = _branch(project.id)
    rhythm.create_branch(branch)

    first = branch.model_copy(update={"revision": 1})
    rhythm.save_branch(first, expected_revision=0)

    stale = branch.model_copy(update={"revision": 1})
    with pytest.raises(RhythmBranchStaleRevisionError) as excinfo:
        rhythm.save_branch(stale, expected_revision=0)
    assert excinfo.value.current_revision == 1

    with pytest.raises(ValueError):
        rhythm.save_branch(branch.model_copy(update={"revision": 3}), expected_revision=1)


def test_missing_run_rejects_artifact(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    rhythm = RhythmRepository(db_path)
    project = projects.create_project("Song")
    run = _run(project.id, uuid.uuid4())
    # The run was never created.
    with pytest.raises(DatabaseError, match="parent run"):
        rhythm.create_artifact(project.id, _artifact(project.id, run))


def test_set_rhythm_state_bumps_revision(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    project = projects.create_project("Song")
    original = projects.get_project(project.id)
    assert original is not None
    assert original.practice_state == PracticeState()

    state = ProjectRhythmState(lane_visible=False, snap_mode=SnapMode.BAR)
    updated = projects.set_rhythm_state(project.id, state)
    assert updated.rhythm_state == state
    assert updated.revision == original.revision + 1
    assert updated.practice_state == original.practice_state
    assert updated.schema_version == original.schema_version
