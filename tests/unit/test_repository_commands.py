"""Repository tests for project commands, history, and undo/redo (M1.15)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from basseparate.domain.commands import (
    AddMarkerOp,
    DeleteMarkerOp,
    SetDisplayOp,
    SetFollowPlayheadOp,
    SetMonitoringVolumeOp,
    SetPositionOp,
    SetSelectionOp,
    SetViewportOp,
    UpdateMarkerOp,
)
from basseparate.domain.project import ChannelDisplay, ViewportState
from basseparate.storage.db import DATABASE_SCHEMA_VERSION, initialize_database
from basseparate.storage.repository import (
    HISTORY_DEPTH_LIMIT,
    MarkerNotFoundError,
    NothingToRedoError,
    NothingToUndoError,
    ProjectNotReady,
    ProjectRepository,
    StaleRevisionError,
)

DURATION = 100_000


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def projects(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


def _sql(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _make_ready_project(projects: ProjectRepository, db_path: Path) -> str:
    """Create a project and flip it to ready with a full source row."""
    project = projects.create_project("Ready")
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
            (str(uuid.uuid4()), str(uuid.uuid4()), DURATION, str(project.id)),
        )
        conn.commit()
    finally:
        conn.close()
    return str(project.id)


def _add_marker(projects: ProjectRepository, project_id: str, position: int) -> str:
    current = projects.get_project(uuid.UUID(project_id))
    assert current is not None
    project = projects.apply_command(
        uuid.UUID(project_id), AddMarkerOp(position_frames=position), current.revision
    )
    match = next(m for m in project.markers if m.position_frames == position)
    return str(match.id)


def test_migration_created_v6_tables(db_path: Path) -> None:
    conn = _sql(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == DATABASE_SCHEMA_VERSION == 6
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"markers", "project_history"} <= tables
        columns = {
            r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        assert {"working_state", "history_seq"} <= columns
    finally:
        conn.close()


def test_new_project_has_default_working_state(projects: ProjectRepository) -> None:
    project = projects.create_project("Empty")
    got = projects.get_project(project.id)
    assert got is not None
    assert got.markers == []
    assert got.working_state.follow_playhead is True
    assert got.working_state.monitoring_volume == 1.0


def test_add_marker_op(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    result = projects.apply_command(
        uuid.UUID(project_id),
        AddMarkerOp(position_frames=1_200, label="  Intro  ", color="#112233"),
        0,
    )
    assert result.revision == 1
    assert len(result.markers) == 1
    marker = result.markers[0]
    assert marker.position_frames == 1_200
    assert marker.label == "Intro"
    assert marker.color == "#112233"
    assert marker.project_id == uuid.UUID(project_id)


def test_marker_positions_inclusive_bounds(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 0)
    _add_marker(projects, project_id, DURATION)
    got = projects.get_project(uuid.UUID(project_id))
    assert got is not None
    assert sorted(m.position_frames for m in got.markers) == [0, DURATION]


def test_marker_beyond_duration_rejected(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    with pytest.raises(ValueError, match="duration"):
        projects.apply_command(
            uuid.UUID(project_id), AddMarkerOp(position_frames=DURATION + 1), 0
        )


def test_position_ops_require_ready_project(projects: ProjectRepository) -> None:
    project = projects.create_project("Empty")
    for op in (
        AddMarkerOp(position_frames=0),
        SetPositionOp(position_frames=0),
        SetSelectionOp(start_frames=0, end_frames=10),
        SetViewportOp(viewport=ViewportState(start_frame=0, frames_per_css_pixel=8.0)),
    ):
        with pytest.raises(ProjectNotReady):
            projects.apply_command(project.id, op, 0)


def test_display_volume_follow_work_on_empty_project(projects: ProjectRepository) -> None:
    project = projects.create_project("Empty")
    result = projects.apply_command(
        project.id,
        SetDisplayOp(channel_display=ChannelDisplay(linked=False, scales=[2.0])),
        0,
    )
    assert result.working_state.channel_display.scales == [2.0]
    result = projects.apply_command(project.id, SetMonitoringVolumeOp(volume=0.5), 1)
    assert result.working_state.monitoring_volume == 0.5
    result = projects.apply_command(project.id, SetFollowPlayheadOp(follow_playhead=False), 2)
    assert result.working_state.follow_playhead is False


def test_stale_revision_rejected(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    with pytest.raises(StaleRevisionError) as excinfo:
        projects.apply_command(uuid.UUID(project_id), AddMarkerOp(position_frames=200), 0)
    assert excinfo.value.current_revision == 1


def test_update_marker_op(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    marker_id = _add_marker(projects, project_id, 100)
    result = projects.apply_command(
        uuid.UUID(project_id),
        UpdateMarkerOp(marker_id=uuid.UUID(marker_id), label="Drop", position_frames=500),
        1,
    )
    assert result.markers[0].label == "Drop"
    assert result.markers[0].position_frames == 500
    assert result.markers[0].created_at is not None


def test_update_missing_marker(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    with pytest.raises(MarkerNotFoundError):
        projects.apply_command(
            uuid.UUID(project_id), UpdateMarkerOp(marker_id=uuid.uuid4()), 0
        )


def test_delete_marker_op(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    marker_id = _add_marker(projects, project_id, 100)
    result = projects.apply_command(
        uuid.UUID(project_id), DeleteMarkerOp(marker_id=uuid.UUID(marker_id)), 1
    )
    assert result.markers == []
    assert result.revision == 2
    with pytest.raises(MarkerNotFoundError):
        projects.apply_command(
            uuid.UUID(project_id), DeleteMarkerOp(marker_id=uuid.UUID(marker_id)), 2
        )


def test_selection_ops(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    result = projects.apply_command(
        uuid.UUID(project_id), SetSelectionOp(start_frames=1_000, end_frames=2_000), 0
    )
    assert result.working_state.selection is not None
    assert result.working_state.selection.start == 1_000
    result = projects.apply_command(uuid.UUID(project_id), SetSelectionOp(), 1)
    assert result.working_state.selection is None


def test_viewport_op(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    result = projects.apply_command(
        uuid.UUID(project_id),
        SetViewportOp(viewport=ViewportState(start_frame=5_000, frames_per_css_pixel=16.0)),
        0,
    )
    assert result.working_state.viewport is not None
    assert result.working_state.viewport.frames_per_css_pixel == 16.0
    result = projects.apply_command(uuid.UUID(project_id), SetViewportOp(), 1)
    assert result.working_state.viewport is None


def test_set_position_not_in_history(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    result = projects.apply_command(
        uuid.UUID(project_id), SetPositionOp(position_frames=48_000), 1
    )
    assert result.working_state.last_position_frames == 48_000
    assert result.can_undo is True
    assert result.can_redo is False
    conn = _sql(db_path)
    try:
        kinds = [
            r[0]
            for r in conn.execute(
                "SELECT kind FROM project_history WHERE project_id = ? ORDER BY seq",
                (project_id,),
            ).fetchall()
        ]
    finally:
        conn.close()
    assert kinds == ["add_marker"]  # set_position is not recorded


def test_undo_roundtrip(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    marker_id = _add_marker(projects, project_id, 100)
    result = projects.apply_command(
        uuid.UUID(project_id),
        UpdateMarkerOp(marker_id=uuid.UUID(marker_id), label="B"),
        1,
    )
    assert result.can_undo is True
    undone = projects.undo(uuid.UUID(project_id), result.revision)
    assert len(undone.markers) == 1
    assert undone.markers[0].label == "Marker"
    # The add entry is still on the stack: both directions are live.
    assert undone.can_undo is True
    assert undone.can_redo is True
    redone = projects.redo(uuid.UUID(project_id), undone.revision)
    assert redone.markers[0].label == "B"
    assert redone.can_redo is False
    assert redone.can_undo is True
    # Revisions keep incrementing through undo/redo (1, 2, 3, 4).
    assert redone.revision == 4


def test_undo_preserves_last_position(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    projects.apply_command(uuid.UUID(project_id), SetPositionOp(position_frames=90_000), 1)
    undone = projects.undo(uuid.UUID(project_id), 2)
    # The playhead position is not part of the history snapshot.
    assert undone.working_state.last_position_frames == 90_000
    assert undone.markers == []


def test_new_edit_clears_redo_branch(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    undone = projects.undo(uuid.UUID(project_id), 1)
    assert undone.can_redo is True
    fresh = projects.apply_command(
        uuid.UUID(project_id), AddMarkerOp(position_frames=500), undone.revision
    )
    assert fresh.can_redo is False
    assert fresh.can_undo is True
    with pytest.raises(NothingToRedoError):
        projects.redo(uuid.UUID(project_id), fresh.revision)


def test_nothing_to_undo(projects: ProjectRepository) -> None:
    project = projects.create_project("Empty")
    with pytest.raises(NothingToUndoError):
        projects.undo(project.id, 0)
    with pytest.raises(NothingToRedoError):
        projects.redo(project.id, 0)


def test_stale_undo_rejected(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    with pytest.raises(StaleRevisionError):
        projects.undo(uuid.UUID(project_id), 0)


def test_history_snapshots_store_before_after(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    conn = _sql(db_path)
    try:
        row = conn.execute(
            "SELECT before_json, after_json FROM project_history WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    before = json.loads(row["before_json"])
    after = json.loads(row["after_json"])
    assert before["markers"] == []
    assert len(after["markers"]) == 1
    # last_position_frames is never stored in snapshots (§17.4.10).
    assert "last_position_frames" not in before["working_state"]
    assert "last_position_frames" not in after["working_state"]


def test_history_depth_cap(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    for i in range(HISTORY_DEPTH_LIMIT + 5):
        project = projects.apply_command(
            uuid.UUID(project_id), AddMarkerOp(position_frames=i + 1), i
        )
    conn = _sql(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM project_history WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == HISTORY_DEPTH_LIMIT
    # Undo still works at the cap.
    undone = projects.undo(uuid.UUID(project_id), project.revision)
    assert len(undone.markers) == HISTORY_DEPTH_LIMIT + 4


def test_working_state_survives_reload(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    projects.apply_command(
        uuid.UUID(project_id),
        SetDisplayOp(channel_display=ChannelDisplay(linked=False, scales=[2.0, 4.0])),
        0,
    )
    fresh = ProjectRepository(db_path)
    got = fresh.get_project(uuid.UUID(project_id))
    assert got is not None
    assert got.working_state.channel_display.linked is False
    assert got.working_state.channel_display.scales == [2.0, 4.0]
    listed = fresh.list_projects()
    assert all(p.id == got.id for p in listed if p.id == got.id)


def test_markers_visible_in_list_projects(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_marker(projects, project_id, 100)
    listed = projects.list_projects()
    match = next(p for p in listed if str(p.id) == project_id)
    assert len(match.markers) == 1
