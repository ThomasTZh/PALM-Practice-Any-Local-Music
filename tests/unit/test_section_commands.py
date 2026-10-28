"""Repository tests for Song Map sections and section loops."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from basseparate.domain.commands import (
    AddSectionOp,
    DeleteSectionOp,
    LoopSectionOp,
    SetActiveSectionOp,
    SplitSectionOp,
    UpdateSectionOp,
)
from basseparate.domain.practice import PracticeState
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    ProjectRepository,
    SectionNotFoundError,
    SectionOverlapError,
    SectionRangeInvalidError,
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


def _make_ready_project(projects: ProjectRepository, db_path: Path) -> uuid.UUID:
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
    return project.id


def _state(projects: ProjectRepository, project_id: uuid.UUID) -> PracticeState:
    project = projects.get_project(project_id)
    assert project is not None
    return project.practice_state


def _add_section(
    projects: ProjectRepository,
    project_id: uuid.UUID,
    *,
    name: str = "Verse",
    start: int = 0,
    end: int = 10_000,
) -> uuid.UUID:
    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id,
        AddSectionOp(name=name, start_frames=start, end_frames=end),
        project.revision,
    )
    return next(s.id for s in result.practice_state.sections if s.name == name)


def test_add_section(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id, name="Intro", start=0, end=8_000)
    state = _state(projects, project_id)
    assert [s.name for s in state.sections] == ["Intro"]
    assert state.sections[0].start_frames == 0
    assert state.sections[0].end_frames == 8_000
    assert state.sections[0].id == section_id


def test_add_sections_are_ordered_by_start(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_section(projects, project_id, name="Chorus", start=20_000, end=30_000)
    _add_section(projects, project_id, name="Intro", start=0, end=10_000)
    state = _state(projects, project_id)
    assert [s.name for s in state.sections] == ["Intro", "Chorus"]


def test_add_section_rejects_overlap(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    _add_section(projects, project_id, start=0, end=10_000)
    project = projects.get_project(project_id)
    assert project is not None
    with pytest.raises(SectionOverlapError):
        projects.apply_command(
            project_id,
            AddSectionOp(name="Overlap", start_frames=9_000, end_frames=20_000),
            project.revision,
        )


def test_add_section_rejects_invalid_range_and_bounds(
    projects: ProjectRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(projects, db_path)
    project = projects.get_project(project_id)
    assert project is not None
    with pytest.raises(SectionRangeInvalidError):
        projects.apply_command(
            project_id,
            AddSectionOp(name="Empty", start_frames=10, end_frames=10),
            project.revision,
        )
    with pytest.raises(SectionRangeInvalidError):
        projects.apply_command(
            project_id,
            AddSectionOp(name="Late", start_frames=90_000, end_frames=DURATION + 1),
            project.revision,
        )


def test_update_section_and_linked_loop(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id)
    project = projects.get_project(project_id)
    assert project is not None
    projects.apply_command(project_id, LoopSectionOp(section_id=section_id), project.revision)

    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id,
        UpdateSectionOp(section_id=section_id, name="Verse A", end_frames=12_000),
        project.revision,
    )
    state = result.practice_state
    assert state.sections[0].name == "Verse A"
    assert state.sections[0].end_frames == 12_000
    assert len(state.loops) == 1
    assert state.loops[0].section_id == section_id
    assert state.loops[0].end_frames == 12_000


def test_loop_section_creates_one_linked_loop(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id, name="Chorus", start=20_000, end=30_000)
    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id, LoopSectionOp(section_id=section_id), project.revision
    )
    state = result.practice_state
    assert len(state.loops) == 1
    loop = state.loops[0]
    assert loop.section_id == section_id
    assert loop.name == "Chorus"
    assert loop.start_frames == 20_000
    assert loop.end_frames == 30_000
    assert state.active_loop_id == loop.id
    assert state.loop_enabled is True
    assert state.active_section_id == section_id

    result = projects.apply_command(
        project_id, LoopSectionOp(section_id=section_id), result.revision
    )
    assert len(result.practice_state.loops) == 1


def test_split_section_creates_adjacent_sections(
    projects: ProjectRepository, db_path: Path
) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id, name="Verse", start=0, end=10_000)
    project = projects.get_project(project_id)
    assert project is not None
    projects.apply_command(project_id, LoopSectionOp(section_id=section_id), project.revision)

    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id, SplitSectionOp(section_id=section_id, at_frame=4_000), project.revision
    )
    sections = result.practice_state.sections
    assert [(s.start_frames, s.end_frames) for s in sections] == [(0, 4_000), (4_000, 10_000)]
    assert sections[0].id == section_id
    assert result.practice_state.active_section_id == section_id
    assert result.practice_state.loops[0].section_id == section_id
    assert result.practice_state.loops[0].end_frames == 4_000


def test_delete_section_removes_linked_loop(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id)
    project = projects.get_project(project_id)
    assert project is not None
    projects.apply_command(project_id, LoopSectionOp(section_id=section_id), project.revision)
    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id, DeleteSectionOp(section_id=section_id), project.revision
    )
    state = result.practice_state
    assert state.sections == []
    assert state.loops == []
    assert state.active_section_id is None
    assert state.active_loop_id is None
    assert state.loop_enabled is False


def test_set_active_section(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id)
    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id, SetActiveSectionOp(section_id=section_id), project.revision
    )
    assert result.practice_state.active_section_id == section_id


def test_section_missing_errors(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    project = projects.get_project(project_id)
    assert project is not None
    missing = uuid.uuid4()
    for op in (
        UpdateSectionOp(section_id=missing, name="Nope"),
        DeleteSectionOp(section_id=missing),
        SplitSectionOp(section_id=missing, at_frame=100),
        LoopSectionOp(section_id=missing),
        SetActiveSectionOp(section_id=missing),
    ):
        with pytest.raises(SectionNotFoundError):
            projects.apply_command(project_id, op, project.revision)


def test_section_commands_undo_and_redo(projects: ProjectRepository, db_path: Path) -> None:
    project_id = _make_ready_project(projects, db_path)
    section_id = _add_section(projects, project_id)
    project = projects.get_project(project_id)
    assert project is not None
    projects.apply_command(project_id, LoopSectionOp(section_id=section_id), project.revision)
    undone = projects.undo(project_id, 2)
    assert undone.practice_state.loops == []
    redone = projects.redo(project_id, undone.revision)
    assert len(redone.practice_state.loops) == 1
