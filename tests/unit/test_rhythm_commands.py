"""Transactional rhythm editing, undo/redo, and conflicts (M3.10, §12)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.confidence import Confidence, ConfidenceKind, ReviewState
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    AnchorLockState,
    BarOriginState,
    GridValidity,
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
from basseparate.domain.rhythm_commands import (
    AddMeterRegionOp,
    AddPulseOp,
    AddTempoAnchorOp,
    DeleteMeterRegionOp,
    DeletePulseOp,
    DeleteTempoAnchorOp,
    MovePulseOp,
    MoveTempoAnchorOp,
    ReinterpretTempoOp,
    RhythmCommandRequest,
    SetAnchorLockOp,
    SetBarOriginOp,
    SetDownbeatOp,
    SetReviewStateOp,
    UpdateMeterRegionOp,
)
from basseparate.rhythm.commands import (
    RhythmCommandError,
    RhythmCommandService,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    ProjectRepository,
    RhythmRepository,
    StaleRevisionError,
)

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000


def _confidence() -> Confidence:
    return Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9)


def _setup(tmp_path: Path):
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    projects = ProjectRepository(db)
    project = projects.create_project("Rhythm edits")
    conn = sqlite3.connect(str(db))
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
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                RATE,
                300_000,
                str(project.id),
            ),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    branch_id = uuid.uuid4()
    sources = [(0, 0), (48_000, 2), (96_000, 4)]
    anchor_ids = [uuid.uuid4() for _ in sources]
    pulse_ids = [uuid.uuid4() for _ in sources]
    pulses = [
        RhythmPulse(
            id=pulse_ids[index],
            parent_id=branch_id,
            source_frame=source,
            model_frame_index=index * 50,
            role=PulseRole.DOWNBEAT if index == 0 else PulseRole.BEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=_confidence(),
            origin=RhythmOrigin.AUTOMATIC,
            tempo_anchor_id=anchor_ids[index],
        )
        for index, (source, _musical) in enumerate(sources)
    ]
    anchors = [
        TempoAnchor(
            id=anchor_ids[index],
            branch_id=branch_id,
            source_frame=source,
            musical_position=MusicalPosition(numerator=musical, denominator=1),
            origin=RhythmOrigin.MANUAL,
            pulse_id=pulse_ids[index],
            confidence=_confidence(),
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (source, musical) in enumerate(sources)
    ]
    region = MeterRegion(
        id=uuid.uuid4(),
        branch_id=branch_id,
        start=MusicalPosition(numerator=0, denominator=1),
        numerator=4,
        denominator=4,
        grouping=[1, 1, 1, 1],
        display_tempo_unit=MeterTempoUnit.QUARTER,
        origin=RhythmOrigin.MANUAL,
    )
    branch = RhythmBranchRecord(
        id=branch_id,
        project_id=project.id,
        revision=0,
        source_duration_frames=300_000,
        pulses=pulses,
        tempo_anchors=anchors,
        meter_regions=[region],
        bar_origin=BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION),
        grid_validity=GridValidity.VALID,
        created_at=NOW,
        updated_at=NOW,
    )
    RhythmRepository(db).create_branch(branch)
    projects.set_rhythm_state(
        project.id,
        ProjectRhythmState(
            active_branch_id=branch.id,
            display_mode=RhythmDisplayMode.EDITED,
        ),
    )
    return db, projects.get_project(project.id), branch


def _request(project_revision: int, op, key: str | None = None) -> RhythmCommandRequest:
    return RhythmCommandRequest(
        command_id=uuid.uuid4(),
        idempotency_key=key or uuid.uuid4().hex,
        base_revision=project_revision,
        op=op,
    )


class TestCommands:
    def test_add_pulse_creates_anchor_and_is_idempotent(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        request = _request(project.revision, AddPulseOp(source_frame=24_000))
        result = service.apply(project.id, request)
        assert result.branch.revision == 1
        assert result.revision == project.revision + 1
        assert len(result.branch.pulses) == 4
        assert len(result.branch.tempo_anchors) == 4
        added = next(p for p in result.branch.pulses if p.source_frame == 24_000)
        assert added.tempo_anchor_id is not None
        assert added.origin is RhythmOrigin.MANUAL
        assert result.can_undo and not result.can_redo

        replay = service.apply(project.id, request)
        assert replay.revision == result.revision
        assert replay.branch == result.branch

        with pytest.raises(StaleRevisionError):
            service.apply(
                project.id,
                _request(project.revision, AddPulseOp(source_frame=72_000)),
            )

    def test_undo_redo_survive_restart(self, tmp_path: Path) -> None:
        db, project, _branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        result = service.apply(
            project.id, _request(project.revision, AddPulseOp(source_frame=24_000))
        )
        undone = service.undo(project.id, result.revision)
        assert len(undone.branch.pulses) == 3
        assert undone.can_redo

        restarted = RhythmCommandService(db)
        redone = restarted.redo(project.id, undone.revision)
        assert len(redone.branch.pulses) == 4
        assert redone.can_undo

    def test_move_pulse_moves_linked_anchor_and_respects_lock(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        pulse = next(p for p in branch.pulses if p.source_frame == 48_000)
        anchor = next(a for a in branch.tempo_anchors if a.id == pulse.tempo_anchor_id)
        result = service.apply(
            project.id,
            _request(project.revision, MovePulseOp(pulse_id=pulse.id, source_frame=60_000)),
        )
        moved_anchor = next(a for a in result.branch.tempo_anchors if a.id == anchor.id)
        assert moved_anchor.source_frame == 60_000
        assert moved_anchor.musical_position == anchor.musical_position

        lock = service.apply(
            project.id,
            _request(
                result.revision,
                SetAnchorLockOp(anchor_id=anchor.id, lock_state=AnchorLockState.LOCKED),
            ),
        )
        with pytest.raises(RhythmCommandError, match="locked"):
            service.apply(
                project.id,
                _request(
                    lock.revision,
                    MovePulseOp(pulse_id=pulse.id, source_frame=66_000),
                ),
            )
        forced = service.apply(
            project.id,
            _request(
                lock.revision,
                MovePulseOp(pulse_id=pulse.id, source_frame=66_000, force_locked=True),
            ),
        )
        assert next(p for p in forced.branch.pulses if p.id == pulse.id).source_frame == 66_000

    def test_downbeat_and_bar_origin(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        pulse = branch.pulses[1]
        result = service.apply(
            project.id,
            _request(project.revision, SetDownbeatOp(pulse_id=pulse.id, is_downbeat=True)),
        )
        changed = next(p for p in result.branch.pulses if p.id == pulse.id)
        assert changed.role is PulseRole.DOWNBEAT

        origin = service.apply(
            project.id,
            _request(
                result.revision,
                SetBarOriginOp(
                    first_bar_number=2,
                    first_downbeat_source=48_000,
                    pickup_start_source=0,
                ),
            ),
        )
        assert origin.branch.bar_origin.first_bar_number == 2
        assert origin.branch.bar_origin.first_numbered_bar_position == MusicalPosition(
            numerator=2, denominator=1
        )
        assert origin.branch.bar_origin.pickup is not None

    def test_meter_update_and_add_region(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        region = branch.meter_regions[0]
        result = service.apply(
            project.id,
            _request(
                project.revision,
                UpdateMeterRegionOp(
                    region_id=region.id,
                    numerator=3,
                    denominator=4,
                    grouping=[1, 1, 1],
                ),
            ),
        )
        assert result.branch.meter_regions[0].numerator == 3
        added = service.apply(
            project.id,
            _request(
                result.revision,
                AddMeterRegionOp(
                    start=MusicalPosition(numerator=3, denominator=1),
                    numerator=4,
                    denominator=4,
                    grouping=[1, 1, 1, 1],
                ),
            ),
        )
        assert len(added.branch.meter_regions) == 2
        assert added.branch.meter_regions[0].end == MusicalPosition(numerator=3, denominator=1)

    def test_anchor_add_move_delete(self, tmp_path: Path) -> None:
        db, project, _branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        added = service.apply(
            project.id,
            _request(
                project.revision,
                AddTempoAnchorOp(
                    source_frame=24_000,
                    musical_position=MusicalPosition(numerator=1, denominator=1),
                ),
            ),
        )
        anchor = next(a for a in added.branch.tempo_anchors if a.source_frame == 24_000)
        moved = service.apply(
            project.id,
            _request(
                added.revision,
                MoveTempoAnchorOp(
                    anchor_id=anchor.id,
                    axis="musical",
                    musical_position=MusicalPosition(numerator=3, denominator=2),
                ),
            ),
        )
        assert next(
            a for a in moved.branch.tempo_anchors if a.id == anchor.id
        ).musical_position == MusicalPosition(numerator=3, denominator=2)
        deleted = service.apply(
            project.id,
            _request(moved.revision, DeleteTempoAnchorOp(anchor_id=anchor.id)),
        )
        assert all(a.id != anchor.id for a in deleted.branch.tempo_anchors)

    def test_delete_pulse_removes_linked_anchor(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        pulse = next(p for p in branch.pulses if p.source_frame == 48_000)
        result = service.apply(
            project.id,
            _request(project.revision, DeletePulseOp(pulse_id=pulse.id)),
        )
        assert len(result.branch.pulses) == 2
        assert all(anchor.id != pulse.tempo_anchor_id for anchor in result.branch.tempo_anchors)
        assert result.branch.grid_validity is GridValidity.VALID

    def test_delete_meter_region_marks_unmapped(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        result = service.apply(
            project.id,
            _request(
                project.revision,
                DeleteMeterRegionOp(region_id=branch.meter_regions[0].id),
            ),
        )
        assert result.branch.meter_regions == []
        assert result.branch.grid_validity is GridValidity.UNMAPPED

    def test_half_time_reinterpretation_and_review(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        result = service.apply(
            project.id,
            _request(
                project.revision,
                ReinterpretTempoOp(
                    start_anchor_id=branch.tempo_anchors[0].id,
                    end_anchor_id=branch.tempo_anchors[-1].id,
                    mode="half_time",
                ),
            ),
        )
        positions = [anchor.musical_position for anchor in result.branch.tempo_anchors]
        assert positions[-1] == MusicalPosition(numerator=8, denominator=1)
        reviewed = service.apply(
            project.id,
            _request(
                result.revision,
                SetReviewStateOp(
                    target="pulse",
                    target_id=result.branch.pulses[0].id,
                    review_state=ReviewState.CORRECTED,
                ),
            ),
        )
        assert reviewed.branch.pulses[0].review_state is ReviewState.CORRECTED

    def test_invalid_edits_are_rejected_without_revision_change(self, tmp_path: Path) -> None:
        db, project, branch = _setup(tmp_path)
        service = RhythmCommandService(db)
        with pytest.raises(RhythmCommandError):
            service.apply(
                project.id,
                _request(project.revision, MovePulseOp(pulse_id=uuid.uuid4(), source_frame=1)),
            )
        with pytest.raises(RhythmCommandError):
            service.apply(
                project.id,
                _request(
                    project.revision,
                    AddMeterRegionOp(
                        start=MusicalPosition(numerator=2, denominator=1),
                        numerator=3,
                        denominator=4,
                        grouping=[1, 1, 1],
                    ),
                ),
            )
        fresh = ProjectRepository(db).get_project(project.id)
        assert fresh is not None
        assert fresh.revision == project.revision
