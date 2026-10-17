"""Repository round-trip for separation records (M2.1, spec §3.6).

Verifies the acceptance criterion: a result set, its audio, and its playback
settings can be *represented* (persisted and read back) without modifying the
original source record of the project.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain import (
    AssetRecord,
    AssetRole,
    AudioMetadata,
    Confidence,
    ConfidenceKind,
    DeviceType,
    PlaybackMode,
    PracticeState,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    TrackSettings,
    ValidationStatus,
)
from basseparate.domain.separation import ReferenceMixIdentity
from basseparate.storage.db import DatabaseError, initialize_database
from basseparate.storage.repository import ProjectRepository, SeparationRepository

SOURCE_COLUMNS = (
    "source_asset_id",
    "canonical_asset_id",
    "monitoring_asset_id",
    "source_stream_index",
    "sample_rate",
    "duration_frames",
    "source_channel_count",
    "source_channel_layout",
    "decode_profile_version",
    "source_metadata",
    "status",
)

SOURCE_HASH = "ab" * 32
PCM_HASH = "cd" * 32


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
    """Simulate a published (ready) source by setting the source columns."""
    source_asset = str(uuid.uuid4())
    pcm_asset = str(uuid.uuid4())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            UPDATE projects SET
                source_asset_id = ?,
                canonical_asset_id = ?,
                source_stream_index = 0,
                sample_rate = 48000,
                duration_frames = 441000,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1,
                source_metadata = '{"encoder": "test"}',
                status = 'ready'
            WHERE id = ?
            """,
            (source_asset, pcm_asset, str(project_id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _build_run(project_id: uuid.UUID, result_set_id: uuid.UUID) -> SeparationRun:
    return SeparationRun(
        id=uuid.uuid4(),
        project_id=project_id,
        input_asset_id=uuid.uuid4(),
        input_transform_hash=SOURCE_HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid.uuid4(),
        model_manifest_hash=PCM_HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
        status=SeparationRunStatus.COMPLETED,
        result_set_id=result_set_id,
        requested_parameters={"split": 8},
        effective_parameters={"split": 4},
    )


def _build_stem(result_set_id: uuid.UUID, role: StemRole) -> StemRecord:
    return StemRecord(
        id=uuid.uuid4(),
        result_set_id=result_set_id,
        role=role,
        display_name=role.value.title(),
        audio_asset_id=uuid.uuid4(),
        sample_rate=48_000,
        channel_count=2,
        frame_count=441_000,
        confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
    )


def _build_result_set(
    run: SeparationRun, project_id: uuid.UUID, stem_ids: list[uuid.UUID]
) -> SeparationResultSet:
    return SeparationResultSet(
        id=run.result_set_id,
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash=SOURCE_HASH,
            sample_rate=48_000,
            duration_frames=441_000,
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=441_000,
        available_stem_roles=[StemRole.VOCALS, StemRole.BASS],
        stem_ids=stem_ids,
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash=PCM_HASH, transformation_hash=SOURCE_HASH
        ),
        reconstruction_metrics={"l1_error": 0.01},
        validation_status=ValidationStatus.VALID,
        created_at="2026-01-01T00:00:00Z",
    )


def test_full_round_trip_and_source_unchanged(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    separation = SeparationRepository(db_path)

    project = projects.create_project("Song")
    _publish_source(db_path, project.id)
    before = _source_columns(db_path, project.id)

    # Build and persist a completed run -> result set -> stems.
    result_set_id = uuid.uuid4()
    run = _build_run(project.id, result_set_id)
    stems = [
        _build_stem(result_set_id, StemRole.VOCALS),
        _build_stem(result_set_id, StemRole.BASS),
    ]
    result_set = _build_result_set(run, project.id, [s.id for s in stems])

    separation.create_run(run)
    separation.create_result_set(result_set)
    for stem in stems:
        separation.create_stem(stem)

    # Persist the playback / mixer settings on the project.
    projects.set_practice_state(
        project.id,
        PracticeState(
            playback_mode=PlaybackMode.FOUR_STEMS,
            active_result_set_id=result_set_id,
            tracks={
                "bass": TrackSettings(gain=0.5),
                "vocals": TrackSettings(mute=True),
            },
            playback_speed=0.5,
        ),
    )

    # Read everything back.
    got_run = separation.get_run(run.id)
    assert got_run is not None
    assert got_run.status == SeparationRunStatus.COMPLETED
    assert got_run.requested_parameters == {"split": 8}
    assert got_run.effective_parameters == {"split": 4}
    assert got_run.result_set_id == result_set_id

    got_set = separation.get_result_set(result_set_id)
    assert got_set is not None
    assert got_set.validation_status == ValidationStatus.VALID
    assert got_set.stem_ids == [s.id for s in stems]
    assert got_set.reconstruction_metrics == {"l1_error": 0.01}

    got_stems = separation.list_stems_for_result_set(result_set_id)
    # The repository orders stems by id (a UUID), not insertion order.
    assert {s.role for s in got_stems} == {StemRole.VOCALS, StemRole.BASS}
    assert all(s.frame_count == 441_000 for s in got_stems)

    assert len(separation.list_runs_for_project(project.id)) == 1
    assert len(separation.list_result_sets_for_project(project.id)) == 1

    # The playback settings round-tripped onto the project.
    reloaded = projects.get_project(project.id)
    assert reloaded is not None
    assert reloaded.practice_state.playback_mode == PlaybackMode.FOUR_STEMS
    assert reloaded.practice_state.active_result_set_id == result_set_id
    assert reloaded.practice_state.playback_speed == 0.5
    assert reloaded.practice_state.tracks["bass"].gain == 0.5
    assert reloaded.practice_state.tracks["vocals"].mute is True

    # The original source record is byte-for-byte unchanged.
    after = _source_columns(db_path, project.id)
    assert after == before


def test_source_fields_preserved_value_by_value(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    project = projects.create_project("Song")
    _publish_source(db_path, project.id)

    before = _source_columns(db_path, project.id)
    assert before["status"] == "ready"
    assert before["sample_rate"] == 48000
    assert before["duration_frames"] == 441000

    # Writing only the practice state must not touch the source record.
    projects.set_practice_state(project.id, PracticeState())
    after = _source_columns(db_path, project.id)
    assert after == before


def _queued_run(project_id: uuid.UUID) -> SeparationRun:
    """A run in flight, before publication (spec §8.7)."""
    return SeparationRun(
        id=uuid.uuid4(),
        project_id=project_id,
        input_asset_id=uuid.uuid4(),
        input_transform_hash=SOURCE_HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid.uuid4(),
        model_manifest_hash=PCM_HASH,
        engine_version="demucs-4.1.0",
        adapter_version="outer-window-v1",
        device_type=DeviceType.CPU,
        started_at="2026-01-01T00:00:00Z",
        status=SeparationRunStatus.RUNNING,
    )


def _build_publish_asset(seed: int, frames: int) -> AssetRecord:
    content_hash = f"{seed:02d}" * 32
    return AssetRecord(
        id=uuid.uuid4(),
        content_hash=content_hash,
        role=AssetRole.STEM,
        relative_path=f"assets/{content_hash}.pcm",
        media_type="audio/pcm",
        byte_count=frames * 2 * 4,
        created_at="2026-01-01T00:10:00Z",
        audio=AudioMetadata(
            sample_rate=48_000,
            channel_count=2,
            frame_count=frames,
            sample_format="f32le",
        ),
    )


def _completed_run(running: SeparationRun, result_set_id: uuid.UUID) -> SeparationRun:
    return running.model_copy(
        update={
            "status": SeparationRunStatus.COMPLETED,
            "result_set_id": result_set_id,
            "ended_at": datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        }
    )


def _project_asset_rows(db_path: Path, project_id: uuid.UUID) -> set[tuple[str, str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT asset_id, role FROM project_assets WHERE project_id = ?",
            (str(project_id),),
        ).fetchall()
        return {(row[0], row[1]) for row in rows}
    finally:
        conn.close()


def test_publish_result_set_completes_run_atomically(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    separation = SeparationRepository(db_path)
    project = projects.create_project("Song")

    running = _queued_run(project.id)
    separation.create_run(running)

    result_set_id = uuid.uuid4()
    assets = [_build_publish_asset(1, 441_000), _build_publish_asset(2, 441_000)]
    bass = _build_stem(result_set_id, StemRole.BASS).model_copy(
        update={"audio_asset_id": assets[0].id}
    )
    others = _build_stem(result_set_id, StemRole.OTHERS).model_copy(
        update={
            "audio_asset_id": assets[1].id,
            "display_name": "Others",
            "provenance": {"kind": "bass_residual"},
        }
    )
    stems = [bass, others]
    completed = _completed_run(running, result_set_id)
    result_set = _build_result_set(completed, project.id, [s.id for s in stems]).model_copy(
        update={
            "available_stem_roles": [StemRole.BASS, StemRole.OTHERS],
            "bass_residual_asset_id": assets[1].id,
        }
    )
    separation.publish_result_set(completed, result_set, stems, assets)

    got_run = separation.get_run(running.id)
    assert got_run is not None
    assert got_run.status == SeparationRunStatus.COMPLETED
    assert got_run.result_set_id == result_set_id

    got_set = separation.get_result_set(result_set_id)
    assert got_set is not None
    assert got_set.validation_status == ValidationStatus.VALID
    assert got_set.bass_residual_asset_id == assets[1].id

    got_stems = separation.list_stems_for_result_set(result_set_id)
    assert {s.role for s in got_stems} == {StemRole.BASS, StemRole.OTHERS}

    for asset in assets:
        assert projects.get_asset(asset.id) is not None
    assert _project_asset_rows(db_path, project.id) == {(str(a.id), "stem") for a in assets}

    # Re-publishing the same run is rejected (results are immutable).
    with pytest.raises(DatabaseError, match="already published"):
        separation.publish_result_set(completed, result_set, stems, assets)


def test_publish_result_set_rolls_back_on_failure(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    separation = SeparationRepository(db_path)
    project = projects.create_project("Song")

    running = _queued_run(project.id)
    separation.create_run(running)

    result_set_id = uuid.uuid4()
    assets = [_build_publish_asset(3, 441_000)]
    stem = _build_stem(result_set_id, StemRole.BASS).model_copy(
        update={"audio_asset_id": assets[0].id}
    )
    completed = _completed_run(running, result_set_id)
    result_set = _build_result_set(completed, project.id, [stem.id])

    # A duplicate stem primary key fails mid-transaction.
    with pytest.raises(DatabaseError, match="cannot publish"):
        separation.publish_result_set(completed, result_set, [stem, stem], assets)

    # Every row from the failed transaction is gone.
    assert separation.get_result_set(result_set_id) is None
    assert separation.list_stems_for_result_set(result_set_id) == []
    after = separation.get_run(running.id)
    assert after is not None and after.status == SeparationRunStatus.RUNNING
    assert projects.get_asset(assets[0].id) is None
    assert _project_asset_rows(db_path, project.id) == set()


def test_publish_rejects_non_valid_result_set(db_path: Path) -> None:
    projects = ProjectRepository(db_path)
    separation = SeparationRepository(db_path)
    project = projects.create_project("Song")

    running = _queued_run(project.id)
    separation.create_run(running)
    result_set_id = uuid.uuid4()
    assets = [_build_publish_asset(4, 441_000)]
    stem = _build_stem(result_set_id, StemRole.BASS).model_copy(
        update={"audio_asset_id": assets[0].id}
    )
    completed = _completed_run(running, result_set_id)
    pending = _build_result_set(completed, project.id, [stem.id]).model_copy(
        update={"validation_status": ValidationStatus.PENDING}
    )
    with pytest.raises(DatabaseError, match="valid"):
        separation.publish_result_set(completed, pending, [stem], assets)
    assert separation.get_result_set(result_set_id) is None


def test_latest_run_elapsed_seconds_reflects_most_recent_run(db_path: Path) -> None:
    """M2.12 (spec §14.4): the diagnostics surface reads the latest run time."""

    projects = ProjectRepository(db_path)
    separation = SeparationRepository(db_path)
    project = projects.create_project("Song")
    assert separation.latest_run_elapsed_seconds() is None

    running = _queued_run(project.id)
    separation.create_run(running)
    # Started but not ended, and no metrics: nothing to report yet.
    assert separation.latest_run_elapsed_seconds() is None

    completed = running.model_copy(
        update={
            "id": uuid.uuid4(),
            "status": SeparationRunStatus.COMPLETED,
            "result_set_id": uuid.uuid4(),
            "ended_at": datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC),
        }
    )
    separation.create_run(completed)
    assert separation.latest_run_elapsed_seconds() == 10.0

    failed = running.model_copy(
        update={
            "id": uuid.uuid4(),
            "status": SeparationRunStatus.FAILED,
            "metrics": {"wall_seconds": 4.5},
        }
    )
    separation.create_run(failed)
    assert separation.latest_run_elapsed_seconds() == 4.5
