"""Integration tests for the undoable active result set selection (M2.7, §9.4).

The selection lives in the project's practice state; switching it is an
undoable command that records history, validates the target against the
project, and persists across reopens.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from basseparate.domain.commands import SetActiveResultSetOp
from basseparate.domain.practice import PlaybackMode, PracticeState
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SourceIdentity,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    ProjectRepository,
    ResultSetNotFoundError,
    SeparationRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64
DURATION = 100_000


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def repo(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def separation(db_path: Path) -> SeparationRepository:
    return SeparationRepository(db_path)


def _sql(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _make_ready_project(repo: ProjectRepository, db_path: Path) -> uuid.UUID:
    project = repo.create_project("Ready")
    conn = _sql(db_path)
    try:
        conn.execute(
            """
            UPDATE projects SET
                status = 'ready',
                source_asset_id = ?,
                canonical_asset_id = ?,
                source_stream_index = 0,
                sample_rate = 48000,
                duration_frames = ?,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1
            WHERE id = ?
            """,
            (str(uuid4()), str(uuid4()), DURATION, str(project.id)),
        )
        conn.commit()
    finally:
        conn.close()
    return project.id


def _result_set_for(separation: SeparationRepository, project_id: uuid.UUID) -> uuid.UUID:
    """Create a minimal queued run + pending result set for the project."""
    run = SeparationRun(
        id=uuid4(),
        project_id=project_id,
        input_asset_id=uuid4(),
        input_transform_hash=HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid4(),
        model_manifest_hash=HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
    )
    separation.create_run(run)
    result_set = SeparationResultSet(
        id=uuid4(),
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid4(), source_hash=HASH, sample_rate=48_000, duration_frames=DURATION
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=DURATION,
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid4(), hash=HASH, transformation_hash=HASH
        ),
        created_at=NOW,
    )
    separation.create_result_set(result_set)
    return result_set.id


def _current(repo: ProjectRepository, project_id: uuid.UUID):
    project = repo.get_project(project_id)
    assert project is not None
    return project


def test_set_active_result_set_applies(
    repo: ProjectRepository, separation: SeparationRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    rs_id = _result_set_for(separation, project_id)
    base = _current(repo, project_id).revision

    result = repo.apply_command(project_id, SetActiveResultSetOp(result_set_id=rs_id), base)

    assert result.revision == base + 1
    assert result.practice_state.active_result_set_id == rs_id
    assert result.practice_state.playback_mode == PlaybackMode.ORIGINAL
    assert result.can_undo is True
    assert result.can_redo is False


def test_set_active_result_set_unknown_id_rejected(
    repo: ProjectRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    base = _current(repo, project_id).revision
    with pytest.raises(ResultSetNotFoundError):
        repo.apply_command(project_id, SetActiveResultSetOp(result_set_id=uuid4()), base)


def test_set_active_result_set_foreign_project_rejected(
    repo: ProjectRepository, separation: SeparationRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    other_id = _make_ready_project(repo, db_path)
    foreign_rs = _result_set_for(separation, other_id)
    base = _current(repo, project_id).revision
    with pytest.raises(ResultSetNotFoundError):
        repo.apply_command(project_id, SetActiveResultSetOp(result_set_id=foreign_rs), base)


def test_set_active_result_set_undo_and_redo(
    repo: ProjectRepository, separation: SeparationRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    rs_a = _result_set_for(separation, project_id)
    rs_b = _result_set_for(separation, project_id)

    project = _current(repo, project_id)
    project = repo.apply_command(
        project_id, SetActiveResultSetOp(result_set_id=rs_a), project.revision
    )
    assert project.practice_state.active_result_set_id == rs_a

    # Undo restores the previous (empty) selection.
    project = repo.undo(project_id, project.revision)
    assert project.practice_state.active_result_set_id is None
    assert project.can_redo is True

    # Redo re-applies the selection.
    project = repo.redo(project_id, project.revision)
    assert project.practice_state.active_result_set_id == rs_a

    # A second switch remembers the first selection for undo.
    project = repo.apply_command(
        project_id, SetActiveResultSetOp(result_set_id=rs_b), project.revision
    )
    assert project.practice_state.active_result_set_id == rs_b
    project = repo.undo(project_id, project.revision)
    assert project.practice_state.active_result_set_id == rs_a


def test_set_active_result_set_clear_reverts_stem_playback_mode(
    repo: ProjectRepository, separation: SeparationRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    rs_a = _result_set_for(separation, project_id)
    project = _current(repo, project_id)
    project = repo.apply_command(
        project_id, SetActiveResultSetOp(result_set_id=rs_a), project.revision
    )

    # Simulate the M2.8 transport switch to stem playback on the active set.
    conn = _sql(db_path)
    try:
        row = conn.execute(
            "SELECT practice_state FROM projects WHERE id = ?", (str(project_id),)
        ).fetchone()
        state = PracticeState.model_validate_json(row["practice_state"])
        state = state.model_copy(update={"playback_mode": PlaybackMode.FOUR_STEMS})
        conn.execute(
            "UPDATE projects SET practice_state = ? WHERE id = ?",
            (state.model_dump_json(), str(project_id)),
        )
        conn.commit()
    finally:
        conn.close()

    # Clearing the selection must revert stem playback to the original mix.
    project = _current(repo, project_id)
    project = repo.apply_command(project_id, SetActiveResultSetOp(), project.revision)
    assert project.practice_state.active_result_set_id is None
    assert project.practice_state.playback_mode == PlaybackMode.ORIGINAL


def test_set_active_result_set_persists_across_reopen(
    repo: ProjectRepository, separation: SeparationRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(repo, db_path)
    rs_a = _result_set_for(separation, project_id)
    project = _current(repo, project_id)
    project = repo.apply_command(
        project_id, SetActiveResultSetOp(result_set_id=rs_a), project.revision
    )

    reopened = ProjectRepository(db_path)
    restored = _current(reopened, project_id)
    assert restored.practice_state.active_result_set_id == rs_a

    # Undo history survives the reopen as well.
    undone = reopened.undo(project_id, restored.revision)
    assert undone.practice_state.active_result_set_id is None
