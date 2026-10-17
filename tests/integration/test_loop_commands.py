"""Integration tests for the practice-loop commands (M2.11, spec §13).

The six loop ops (``add_loop``, ``update_loop``, ``delete_loop``,
``duplicate_loop``, ``set_active_loop``, ``set_loop_enabled``) are
undoable commands on the project's practice state: patch semantics,
range validation against the source duration, the repeatable 100 ms
minimum, the active-loop invariants, history, and persistence.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.commands import (
    AddLoopOp,
    DeleteLoopOp,
    DuplicateLoopOp,
    SetActiveLoopOp,
    SetLoopEnabledOp,
    UpdateLoopOp,
)
from basseparate.domain.practice import DEFAULT_LOOP_COLOR, MAX_LOOP_NAME_LENGTH
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    LoopNotFoundError,
    LoopRangeInvalidError,
    LoopTooShortError,
    NoActiveLoopError,
    ProjectNotReady,
    ProjectRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
DURATION = 100_000
SAMPLE_RATE = 48_000
MIN_LOOP_FRAMES = 4_800  # 100 ms at 48 kHz (§13.3.3)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def repo(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


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
                sample_rate = ?,
                duration_frames = ?,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1
            WHERE id = ?
            """,
            (
                str(uuid4()),
                str(uuid4()),
                SAMPLE_RATE,
                DURATION,
                str(project.id),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return project.id


def _current(repo: ProjectRepository, project_id: uuid.UUID):
    project = repo.get_project(project_id)
    assert project is not None
    return project


def _add_loop(
    repo: ProjectRepository,
    project_id: uuid.UUID,
    *,
    start: int = 1_000,
    end: int = 5_800,
    **kwargs: object,
):
    project = _current(repo, project_id)
    return repo.apply_command(
        project_id,
        AddLoopOp(start_frames=start, end_frames=end, **kwargs),
        project.revision,
    )


class TestAddLoop:
    def test_defaults(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        base = _current(repo, project_id).revision

        result = _add_loop(repo, project_id)

        assert len(result.practice_state.loops) == 1
        loop = result.practice_state.loops[0]
        assert loop.name == "Loop 1"
        assert loop.start_frames == 1_000
        assert loop.end_frames == 5_800
        assert loop.color == DEFAULT_LOOP_COLOR
        assert loop.repeat_count is None
        assert loop.boundary_fade is True
        assert result.revision == base + 1
        assert result.can_undo is True

    def test_name_and_color_supplied(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        result = _add_loop(repo, project_id, name="Verse", color="#00ff00")
        loop = result.practice_state.loops[0]
        assert loop.name == "Verse"
        assert loop.color == "#00ff00"

    def test_default_name_counts_existing_loops(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        _add_loop(repo, project_id)
        result = _add_loop(repo, project_id, start=10_000, end=20_000)
        assert [loop.name for loop in result.practice_state.loops] == [
            "Loop 1",
            "Loop 2",
        ]

    def test_end_must_exceed_start(self, repo: ProjectRepository, db_path: Path) -> None:
        with pytest.raises(ValidationError, match="end_frames"):
            AddLoopOp(start_frames=5, end_frames=5)
        with pytest.raises(ValidationError, match="end_frames"):
            AddLoopOp(start_frames=9, end_frames=5)

    def test_range_validated_against_duration(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        # Negative frames are rejected at the op level (422).
        with pytest.raises(ValidationError):
            AddLoopOp(start_frames=-1, end_frames=100)
        # Past the source length is rejected against the project duration.
        with pytest.raises(LoopRangeInvalidError):
            _add_loop(repo, project_id, start=0, end=DURATION + 1)

    def test_ready_project_required(self, repo: ProjectRepository) -> None:
        project = repo.create_project("Empty")
        with pytest.raises(ProjectNotReady):
            repo.apply_command(
                project.id,
                AddLoopOp(start_frames=0, end_frames=100),
                project.revision,
            )

    def test_undo_removes_the_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        result = _add_loop(repo, project_id)
        undone = repo.undo(project_id, result.revision)
        assert undone.practice_state.loops == []
        assert undone.can_redo is True


class TestUpdateLoop:
    def test_patch_semantics(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id

        result = repo.apply_command(
            project_id,
            UpdateLoopOp(loop_id=loop_id, name="Chorus", start_frames=2_000),
            added.revision,
        )

        loop = result.practice_state.loops[0]
        assert loop.name == "Chorus"
        assert loop.start_frames == 2_000
        # Untouched fields keep their values.
        assert loop.end_frames == 5_800
        assert loop.color == DEFAULT_LOOP_COLOR
        assert loop.boundary_fade is True
        assert loop.repeat_count is None
        assert loop.updated_at >= loop.created_at

    def test_repeat_count_absent_means_unchanged(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id, repeat_count=4)
        loop_id = added.practice_state.loops[0].id

        result = repo.apply_command(
            project_id, UpdateLoopOp(loop_id=loop_id, name="Keep"), added.revision
        )
        assert result.practice_state.loops[0].repeat_count == 4

        # Explicit null sets infinite.
        result = repo.apply_command(
            project_id,
            UpdateLoopOp(loop_id=loop_id, repeat_count=None),
            result.revision,
        )
        assert result.practice_state.loops[0].repeat_count is None

        # And a finite value round-trips back.
        result = repo.apply_command(
            project_id, UpdateLoopOp(loop_id=loop_id, repeat_count=2), result.revision
        )
        assert result.practice_state.loops[0].repeat_count == 2

    def test_empty_patch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one field"):
            UpdateLoopOp(loop_id=uuid4())

    def test_unknown_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        with pytest.raises(LoopNotFoundError):
            repo.apply_command(
                project_id, UpdateLoopOp(loop_id=uuid4(), name="X"), project.revision
            )

    def test_range_revalidated(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id
        with pytest.raises(LoopRangeInvalidError):
            repo.apply_command(
                project_id,
                UpdateLoopOp(loop_id=loop_id, end_frames=DURATION + 1),
                added.revision,
            )
        with pytest.raises(LoopRangeInvalidError):
            repo.apply_command(
                project_id,
                UpdateLoopOp(loop_id=loop_id, start_frames=6_000),
                added.revision,
            )

    def test_undo_restores_boundaries(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id
        updated = repo.apply_command(
            project_id,
            UpdateLoopOp(loop_id=loop_id, start_frames=2_000, end_frames=3_000),
            added.revision,
        )
        undone = repo.undo(project_id, updated.revision)
        loop = undone.practice_state.loops[0]
        assert (loop.start_frames, loop.end_frames) == (1_000, 5_800)


class TestDeleteLoop:
    def test_removes_and_undoes(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id

        result = repo.apply_command(
            project_id, DeleteLoopOp(loop_id=loop_id), added.revision
        )
        assert result.practice_state.loops == []

        undone = repo.undo(project_id, result.revision)
        assert len(undone.practice_state.loops) == 1

    def test_deleting_active_loop_clears_selection(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id
        active = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=loop_id), added.revision
        )
        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )

        result = repo.apply_command(
            project_id, DeleteLoopOp(loop_id=loop_id), enabled.revision
        )
        assert result.practice_state.active_loop_id is None
        assert result.practice_state.loop_enabled is False

    def test_unknown_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        with pytest.raises(LoopNotFoundError):
            repo.apply_command(project_id, DeleteLoopOp(loop_id=uuid4()), project.revision)


class TestDuplicateLoop:
    def test_copies_with_new_id_and_name(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id, name="Verse", color="#112233", repeat_count=3)
        source = added.practice_state.loops[0]

        result = repo.apply_command(
            project_id, DuplicateLoopOp(loop_id=source.id), added.revision
        )

        assert len(result.practice_state.loops) == 2
        copy = result.practice_state.loops[1]
        assert copy.id != source.id
        assert copy.name == "Verse copy"
        assert copy.color == "#112233"
        assert copy.repeat_count == 3
        assert (copy.start_frames, copy.end_frames) == (
            source.start_frames,
            source.end_frames,
        )
        # The active selection is untouched.
        assert result.practice_state.active_loop_id is None

    def test_copy_name_truncated(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        long_name = "x" * MAX_LOOP_NAME_LENGTH
        added = _add_loop(repo, project_id, name=long_name)
        source = added.practice_state.loops[0]
        result = repo.apply_command(
            project_id, DuplicateLoopOp(loop_id=source.id), added.revision
        )
        copy = result.practice_state.loops[1]
        assert len(copy.name) == MAX_LOOP_NAME_LENGTH
        assert copy.name.endswith(" copy")

    def test_unknown_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        with pytest.raises(LoopNotFoundError):
            repo.apply_command(
                project_id, DuplicateLoopOp(loop_id=uuid4()), project.revision
            )


class TestSetActiveLoop:
    def test_select_and_clear(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id

        result = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=loop_id), added.revision
        )
        assert result.practice_state.active_loop_id == loop_id
        assert result.practice_state.loop_enabled is False

        cleared = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=None), result.revision
        )
        assert cleared.practice_state.active_loop_id is None

    def test_clearing_disables_looping(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id
        active = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=loop_id), added.revision
        )
        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )
        cleared = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=None), enabled.revision
        )
        assert cleared.practice_state.loop_enabled is False

    def test_switching_keeps_looping_enabled(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        first = _add_loop(repo, project_id)
        first_id = first.practice_state.loops[0].id
        second = _add_loop(repo, project_id, start=10_000, end=20_000)
        second_id = second.practice_state.loops[1].id

        active = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=first_id), second.revision
        )
        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )
        switched = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=second_id), enabled.revision
        )
        assert switched.practice_state.active_loop_id == second_id
        assert switched.practice_state.loop_enabled is True

    def test_unknown_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        with pytest.raises(LoopNotFoundError):
            repo.apply_command(
                project_id, SetActiveLoopOp(loop_id=uuid4()), project.revision
            )


class TestSetLoopEnabled:
    def _active_loop(
        self, repo: ProjectRepository, project_id: uuid.UUID, *, frames: int = MIN_LOOP_FRAMES
    ):
        added = _add_loop(repo, project_id, start=1_000, end=1_000 + frames)
        loop_id = added.practice_state.loops[0].id
        return repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=loop_id), added.revision
        )

    def test_enable_and_disable(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        active = self._active_loop(repo, project_id)

        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )
        assert enabled.practice_state.loop_enabled is True

        disabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=False), enabled.revision
        )
        assert disabled.practice_state.loop_enabled is False

    def test_requires_active_loop(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        with pytest.raises(NoActiveLoopError):
            repo.apply_command(
                project_id, SetLoopEnabledOp(enabled=True), project.revision
            )

    def test_short_loop_can_be_saved_but_not_enabled(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        # §13.3.2–3: short intervals may be saved; repeated playback
        # needs ≥ 100 ms and must not silently expand the interval.
        project_id = _make_ready_project(repo, db_path)
        active = self._active_loop(repo, project_id, frames=MIN_LOOP_FRAMES - 1)

        with pytest.raises(LoopTooShortError) as excinfo:
            repo.apply_command(
                project_id, SetLoopEnabledOp(enabled=True), active.revision
            )
        assert "100 ms" in str(excinfo.value)
        # The saved interval is untouched.
        loop = _current(repo, project_id).practice_state.loops[0]
        assert loop.end_frames - loop.start_frames == MIN_LOOP_FRAMES - 1

    def test_exactly_100ms_enables(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        active = self._active_loop(repo, project_id, frames=MIN_LOOP_FRAMES)
        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )
        assert enabled.practice_state.loop_enabled is True

    def test_disable_without_active_loop_is_allowed(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        result = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=False), project.revision
        )
        assert result.practice_state.loop_enabled is False


class TestHistoryAndPersistence:
    def test_undo_redo_sequence(self, repo: ProjectRepository, db_path: Path) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(repo, project_id)
        loop_id = added.practice_state.loops[0].id
        active = repo.apply_command(
            project_id, SetActiveLoopOp(loop_id=loop_id), added.revision
        )
        enabled = repo.apply_command(
            project_id, SetLoopEnabledOp(enabled=True), active.revision
        )

        # Undo all three, then redo all three.
        undone = repo.undo(project_id, enabled.revision)
        undone = repo.undo(project_id, undone.revision)
        undone = repo.undo(project_id, undone.revision)
        assert undone.practice_state.loops == []
        assert undone.practice_state.active_loop_id is None
        assert undone.practice_state.loop_enabled is False

        redone = repo.redo(project_id, undone.revision)
        redone = repo.redo(project_id, redone.revision)
        redone = repo.redo(project_id, redone.revision)
        assert len(redone.practice_state.loops) == 1
        assert redone.practice_state.active_loop_id == loop_id
        assert redone.practice_state.loop_enabled is True

    def test_loops_persist_across_reads(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        added = _add_loop(
            repo,
            project_id,
            name="Solo",
            color="#abcdef",
            repeat_count=5,
            boundary_fade=False,
        )
        loop_id = added.practice_state.loops[0].id
        repo.apply_command(project_id, SetActiveLoopOp(loop_id=loop_id), added.revision)

        reloaded = _current(repo, project_id)
        loop = reloaded.practice_state.loops[0]
        assert loop.name == "Solo"
        assert loop.color == "#abcdef"
        assert loop.repeat_count == 5
        assert loop.boundary_fade is False
        assert reloaded.practice_state.active_loop_id == loop_id
