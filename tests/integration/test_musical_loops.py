"""Read-time resolution of musical practice loops (M3.13 §15.6-§15.7)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.practice import PracticeLoop, PracticeState
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    GridValidity,
    LoopAnchorMode,
    MeterRegion,
    MeterTempoUnit,
    MusicalPosition,
    ProjectRhythmState,
    PulseAcceptance,
    PulseRole,
    RhythmBranchRecord,
    RhythmDisplayMode,
    RhythmOrigin,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ProjectRepository, RhythmRepository

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000


def _branch(project_id: uuid.UUID, *, second_source: int = 48_000) -> RhythmBranchRecord:
    branch_id = uuid.uuid4()
    confidence = Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9)
    anchor_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    pulse_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    sources = [(0, 0), (second_source, 2), (96_000, 4)]
    anchors = [
        TempoAnchor(
            id=anchor_ids[index],
            branch_id=branch_id,
            source_frame=source,
            musical_position=MusicalPosition(numerator=musical, denominator=1),
            origin=RhythmOrigin.MANUAL,
            pulse_id=pulse_ids[index],
            confidence=confidence,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (source, musical) in enumerate(sources)
    ]
    pulses = [
        RhythmPulse(
            id=pulse_ids[index],
            parent_id=branch_id,
            source_frame=source,
            role=PulseRole.DOWNBEAT if index == 0 else PulseRole.BEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=confidence,
            origin=RhythmOrigin.AUTOMATIC,
            tempo_anchor_id=anchor_ids[index],
        )
        for index, (source, _musical) in enumerate(sources)
    ]
    return RhythmBranchRecord(
        id=branch_id,
        project_id=project_id,
        revision=0,
        source_duration_frames=200_000,
        pulses=pulses,
        tempo_anchors=anchors,
        meter_regions=[
            MeterRegion(
                id=uuid.uuid4(),
                branch_id=branch_id,
                start=ZERO_MUSICAL_POSITION,
                numerator=4,
                denominator=4,
                grouping=[1, 1, 1, 1],
                display_tempo_unit=MeterTempoUnit.QUARTER,
                origin=RhythmOrigin.MANUAL,
            )
        ],
        bar_origin=BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION),
        grid_validity=GridValidity.VALID,
        created_at=NOW,
        updated_at=NOW,
    )


def _setup(tmp_path: Path, *, loop_end: int = 2):
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    projects = ProjectRepository(db)
    project = projects.create_project("Loops")
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            UPDATE projects SET
                status = 'ready', source_asset_id = ?, canonical_asset_id = ?,
                source_stream_index = 0, sample_rate = ?, duration_frames = 200000,
                source_channel_count = 2, source_channel_layout = 'stereo',
                decode_profile_version = 1
            WHERE id = ?
            """,
            (str(uuid.uuid4()), str(uuid.uuid4()), RATE, str(project.id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    branch = _branch(project.id)
    RhythmRepository(db).create_branch(branch)
    projects.set_rhythm_state(
        project.id,
        ProjectRhythmState(active_branch_id=branch.id, display_mode=RhythmDisplayMode.EDITED),
    )
    loop = PracticeLoop(
        id=uuid.uuid4(),
        name="Musical",
        start_frames=0,
        end_frames=1,
        anchor_mode=LoopAnchorMode.MUSICAL,
        start_musical=MusicalPosition(numerator=0, denominator=1),
        end_musical=MusicalPosition(numerator=loop_end, denominator=1),
        created_at=NOW,
        updated_at=NOW,
    )
    source_loop = PracticeLoop(
        id=uuid.uuid4(),
        name="Source",
        start_frames=10,
        end_frames=20,
        created_at=NOW,
        updated_at=NOW,
    )
    practice = PracticeState(loops=[loop, source_loop])
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE projects SET practice_state = ? WHERE id = ?",
            (practice.model_dump_json(), str(project.id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    return db, project.id, branch.id


def test_musical_loop_resolves_on_read(tmp_path: Path) -> None:
    db, project_id, branch_id = _setup(tmp_path)
    project = ProjectRepository(db).get_project(project_id)
    assert project is not None
    musical, source = project.practice_state.loops
    assert musical.anchor_mode is LoopAnchorMode.MUSICAL
    assert (musical.start_frames, musical.end_frames) == (0, 48_000)
    assert musical.resolved_source_start == 0
    assert musical.grid_branch_id == branch_id
    assert source.start_frames == 10 and source.end_frames == 20


def test_grid_edit_re_resolves_musical_loop_only(tmp_path: Path) -> None:
    db, project_id, _branch_id = _setup(tmp_path)
    old = ProjectRepository(db).get_project(project_id)
    assert old is not None and old.practice_state.loops[0].end_frames == 48_000

    # Replace the branch with a corrected map where quarter 2 is at 24,000.
    branch = _branch(project_id, second_source=24_000)
    branch = branch.model_copy(update={"revision": 1})
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE rhythm_branches SET revision = ?, record_json = ? WHERE project_id = ?",
            (1, branch.model_dump_json(), str(project_id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    updated = ProjectRepository(db).get_project(project_id)
    assert updated is not None
    musical, source = updated.practice_state.loops
    assert musical.end_frames == 24_000
    assert musical.end_musical == MusicalPosition(numerator=2, denominator=1)
    assert source.start_frames == 10 and source.end_frames == 20


def test_unmapped_musical_loop_is_unresolved(tmp_path: Path) -> None:
    db, project_id, _branch_id = _setup(tmp_path, loop_end=20)
    project = ProjectRepository(db).get_project(project_id)
    assert project is not None
    musical = project.practice_state.loops[0]
    assert musical.unresolved is True
    assert musical.resolved_source_start is None


def test_add_musical_loop_command_and_undo(tmp_path: Path) -> None:
    from basseparate.domain.commands import AddMusicalLoopOp

    db, project_id, _branch_id = _setup(tmp_path)
    projects = ProjectRepository(db)
    project = projects.get_project(project_id)
    assert project is not None
    result = projects.apply_command(
        project_id,
        AddMusicalLoopOp(
            start_musical=MusicalPosition(numerator=0, denominator=1),
            end_musical=MusicalPosition(numerator=2, denominator=1),
            name="Bars",
        ),
        project.revision,
    )
    added = next(loop for loop in result.practice_state.loops if loop.name == "Bars")
    assert added.anchor_mode is LoopAnchorMode.MUSICAL
    assert (added.start_frames, added.end_frames) == (0, 48_000)
    undone = projects.undo(project_id, result.revision)
    assert not any(loop.name == "Bars" for loop in undone.practice_state.loops)


def test_convert_source_loop_needs_confirmation(tmp_path: Path) -> None:
    from basseparate.domain.commands import AddLoopOp, ConvertLoopOp
    from basseparate.storage.repository import (
        LoopAlignmentConfirmationRequiredError,
    )

    db, project_id, _branch_id = _setup(tmp_path)
    projects = ProjectRepository(db)
    project = projects.get_project(project_id)
    assert project is not None
    added = projects.apply_command(
        project_id,
        AddLoopOp(start_frames=3_000, end_frames=9_000, name="Off grid"),
        project.revision,
    )
    source = next(loop for loop in added.practice_state.loops if loop.name == "Off grid")
    project = projects.get_project(project_id)
    assert project is not None
    try:
        projects.apply_command(
            project_id,
            ConvertLoopOp(loop_id=source.id, target=LoopAnchorMode.MUSICAL),
            project.revision,
        )
        raise AssertionError("conversion should need confirmation")
    except LoopAlignmentConfirmationRequiredError as exc:
        assert exc.warnings
    result = projects.apply_command(
        project_id,
        ConvertLoopOp(
            loop_id=source.id,
            target=LoopAnchorMode.MUSICAL,
            confirm_off_grid=True,
        ),
        project.revision,
    )
    converted = next(loop for loop in result.practice_state.loops if loop.id == source.id)
    assert converted.anchor_mode is LoopAnchorMode.MUSICAL
    assert converted.start_musical is not None
    assert converted.end_musical is not None


def test_convert_musical_loop_to_source(tmp_path: Path) -> None:
    from basseparate.domain.commands import ConvertLoopOp

    db, project_id, _branch_id = _setup(tmp_path)
    projects = ProjectRepository(db)
    project = projects.get_project(project_id)
    assert project is not None
    musical = next(loop for loop in project.practice_state.loops if loop.name == "Musical")
    result = projects.apply_command(
        project_id,
        ConvertLoopOp(loop_id=musical.id, target=LoopAnchorMode.SOURCE),
        project.revision,
    )
    converted = next(loop for loop in result.practice_state.loops if loop.id == musical.id)
    assert converted.anchor_mode is LoopAnchorMode.SOURCE
    assert (converted.start_frames, converted.end_frames) == (0, 48_000)
