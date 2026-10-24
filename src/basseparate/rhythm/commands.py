"""Transactional rhythm editing commands with undo/redo (M3.10 §12).

Each command validates the project base revision and the active editable
branch, applies one semantic edit, records before/after branch snapshots,
and increments the branch and project revisions in one SQLite
transaction. Receipts make retries idempotent. A stale base revision is a
conflict, never a silent merge.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from basseparate.domain.common import Uuid
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterCandidate,
    MeterMap,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    AnchorLockState,
    BarOriginState,
    GridValidity,
    MeterRegion,
    MeterTempoUnit,
    MusicalInterval,
    ProjectRhythmState,
    PulseAcceptance,
    PulseRole,
    RhythmBranchRecord,
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
    RhythmCommandOp,
    RhythmCommandRequest,
    RhythmCommandResult,
    SetAnchorLockOp,
    SetBarOriginOp,
    SetDownbeatOp,
    SetReviewStateOp,
    UpdateMeterRegionOp,
)
from basseparate.domain.tempo import (
    PULSE_UNIT_QUARTER,
    TempoMap,
    TempoMapAnchor,
    summarize_bpm,
)
from basseparate.rhythm.tempo import TempoMapConflictError, reinterpret_tempo_map
from basseparate.storage.repository import StaleRevisionError


class RhythmCommandError(Exception):
    """The rhythm command cannot be applied."""


class RhythmCommandConflict(RhythmCommandError):
    """A stale revision or lock conflict; the caller must reload/confirm."""

    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


def _now() -> datetime:
    return datetime.now(UTC)


def _db_open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def tempo_map_for_branch(branch: RhythmBranchRecord, project_sample_rate: int) -> TempoMap:
    if len(branch.tempo_anchors) < 2:
        raise RhythmCommandError("a mapped edit needs at least two tempo anchors")
    anchors = [
        TempoMapAnchor(
            id=anchor.id,
            source_frame=anchor.source_frame,
            musical_position=anchor.musical_position,
            lock_state=anchor.lock_state,
            origin=anchor.origin,
            pulse_id=anchor.pulse_id,
            confidence=anchor.confidence,
            created_at=anchor.created_at,
            updated_at=anchor.updated_at,
        )
        for anchor in branch.tempo_anchors
    ]
    map_ = TempoMap(
        id=branch.id,
        project_id=branch.project_id,
        project_sample_rate=project_sample_rate,
        source_duration_frames=branch.source_duration_frames,
        hypothesis=PULSE_UNIT_QUARTER,
        anchors=anchors,
        summary_bpm=1.0,
        created_at=datetime.now(UTC),
    )
    return map_.model_copy(update={"summary_bpm": summarize_bpm(map_.segments)})


def meter_map_for_branch(branch: RhythmBranchRecord) -> MeterMap:
    regions = [
        ManualMeterRegion(
            start=region.start,
            candidate=manual_candidate(
                region.numerator,
                region.denominator,
                region.grouping,
                region.display_tempo_unit,
            ),
            origin=region.origin,
            confidence=region.confidence,
            uncertain=region.grid_validity is GridValidity.UNCERTAIN,
            alternatives=region.alternatives,
        )
        for region in branch.meter_regions
    ]
    if not regions:
        raise RhythmCommandError("the branch has no meter regions")
    return build_meter_map(regions)


def _rebuild(
    branch: RhythmBranchRecord,
    *,
    now: datetime,
    **updates: Any,
) -> RhythmBranchRecord:
    data = {
        **branch.model_dump(),
        **updates,
        "revision": branch.revision + 1,
        "updated_at": now,
    }
    data["grid_validity"] = _validity(
        updates.get("tempo_anchors", branch.tempo_anchors),
        updates.get("meter_regions", branch.meter_regions),
    )
    try:
        return RhythmBranchRecord.model_validate(data)
    except ValueError as exc:
        raise RhythmCommandError(str(exc)) from exc


def _validity(anchors: list[TempoAnchor], regions: list[MeterRegion]) -> GridValidity:
    if not anchors or not regions:
        return GridValidity.UNMAPPED
    if any(region.grid_validity is GridValidity.UNCERTAIN for region in regions):
        return GridValidity.UNCERTAIN
    return GridValidity.VALID


def _manual_confidence(method: str) -> Confidence:
    return Confidence(
        kind=ConfidenceKind.HEURISTIC,
        value=1.0,
        calibrated=False,
        method=method,
    )


def _find_pulse(branch: RhythmBranchRecord, pulse_id: Uuid) -> RhythmPulse:
    for pulse in branch.pulses:
        if pulse.id == pulse_id:
            return pulse
    raise RhythmCommandError(f"pulse {pulse_id} is not in the active branch")


def _find_anchor(branch: RhythmBranchRecord, anchor_id: Uuid) -> TempoAnchor:
    for anchor in branch.tempo_anchors:
        if anchor.id == anchor_id:
            return anchor
    raise RhythmCommandError(f"tempo anchor {anchor_id} is not in the active branch")


def _linked_anchor(branch: RhythmBranchRecord, pulse: RhythmPulse) -> TempoAnchor | None:
    for anchor in branch.tempo_anchors:
        if anchor.id == pulse.tempo_anchor_id or anchor.pulse_id == pulse.id:
            return anchor
    return None


def _validate_anchor_neighbors(anchors: list[TempoAnchor], anchor: TempoAnchor) -> None:
    ordered = sorted(anchors, key=lambda item: item.source_frame)
    index = ordered.index(anchor)
    if index > 0 and anchor.source_frame <= ordered[index - 1].source_frame:
        raise RhythmCommandError("tempo anchor would cross its predecessor")
    if index + 1 < len(ordered) and anchor.source_frame >= ordered[index + 1].source_frame:
        raise RhythmCommandError("tempo anchor would cross its successor")


def _apply_add_pulse(
    branch: RhythmBranchRecord, op: AddPulseOp, project_rate: int, now: datetime
) -> RhythmBranchRecord:
    if op.source_frame > branch.source_duration_frames:
        raise RhythmCommandError("pulse lies beyond the project duration")
    if any(pulse.source_frame == op.source_frame for pulse in branch.pulses):
        raise RhythmCommandError("a pulse already exists at that source frame")
    musical = ZERO_MUSICAL_POSITION
    if branch.tempo_anchors:
        try:
            musical = tempo_map_for_branch(branch, project_rate).map_source_to_musical(
                op.source_frame
            )
        except Exception as exc:
            raise RhythmCommandError(str(exc)) from exc
    pulse = RhythmPulse(
        id=uuid.uuid4(),
        parent_id=branch.id,
        source_frame=op.source_frame,
        model_frame_index=None,
        role=op.role,
        acceptance=PulseAcceptance.ACCEPTED,
        confidence=_manual_confidence("manual-pulse-v1"),
        origin=RhythmOrigin.MANUAL,
    )
    anchors = list(branch.tempo_anchors)
    if op.link_anchor:
        existing = next(
            (anchor for anchor in anchors if anchor.source_frame == op.source_frame),
            None,
        )
        if existing is not None:
            pulse = pulse.model_copy(update={"tempo_anchor_id": existing.id})
        else:
            anchor = TempoAnchor(
                id=uuid.uuid4(),
                branch_id=branch.id,
                source_frame=op.source_frame,
                musical_position=musical,
                origin=RhythmOrigin.MANUAL,
                pulse_id=pulse.id,
                confidence=pulse.confidence,
                created_at=now,
                updated_at=now,
            )
            anchors.append(anchor)
            anchors.sort(key=lambda item: item.source_frame)
            pulse = pulse.model_copy(update={"tempo_anchor_id": anchor.id})
    return _rebuild(
        branch,
        now=now,
        pulses=[*branch.pulses, pulse],
        tempo_anchors=anchors,
    )


def _apply_move_pulse(
    branch: RhythmBranchRecord, op: MovePulseOp, now: datetime
) -> RhythmBranchRecord:
    pulse = _find_pulse(branch, op.pulse_id)
    if op.source_frame > branch.source_duration_frames:
        raise RhythmCommandError("pulse lies beyond the project duration")
    if any(
        other.id != pulse.id and other.source_frame == op.source_frame for other in branch.pulses
    ):
        raise RhythmCommandError("another pulse already occupies that source frame")
    anchor = _linked_anchor(branch, pulse)
    anchors = list(branch.tempo_anchors)
    if anchor is not None:
        if anchor.lock_state is AnchorLockState.LOCKED and not op.force_locked:
            raise RhythmCommandError("the linked tempo anchor is locked")
        moved = anchor.model_copy(update={"source_frame": op.source_frame, "updated_at": now})
        anchors = [moved if item.id == anchor.id else item for item in anchors]
        anchors.sort(key=lambda item: item.source_frame)
        _validate_anchor_neighbors(anchors, moved)
    moved_pulse = pulse.model_copy(
        update={"source_frame": op.source_frame, "model_frame_index": None}
    )
    return _rebuild(
        branch,
        now=now,
        pulses=[moved_pulse if item.id == pulse.id else item for item in branch.pulses],
        tempo_anchors=anchors,
    )


def _apply_delete_pulse(
    branch: RhythmBranchRecord, op: DeletePulseOp, now: datetime
) -> RhythmBranchRecord:
    pulse = _find_pulse(branch, op.pulse_id)
    anchor = _linked_anchor(branch, pulse)
    if anchor is not None and anchor.lock_state is AnchorLockState.LOCKED and not op.force_locked:
        raise RhythmCommandError("the linked tempo anchor is locked")
    anchors = [item for item in branch.tempo_anchors if anchor is None or item.id != anchor.id]
    return _rebuild(
        branch,
        now=now,
        pulses=[item for item in branch.pulses if item.id != pulse.id],
        tempo_anchors=anchors,
    )


def _apply_set_downbeat(
    branch: RhythmBranchRecord, op: SetDownbeatOp, now: datetime
) -> RhythmBranchRecord:
    pulse = _find_pulse(branch, op.pulse_id)
    role = PulseRole.DOWNBEAT if op.is_downbeat else PulseRole.BEAT
    updated = pulse.model_copy(update={"role": role})
    return _rebuild(
        branch,
        now=now,
        pulses=[updated if item.id == pulse.id else item for item in branch.pulses],
    )


def _apply_add_anchor(
    branch: RhythmBranchRecord, op: AddTempoAnchorOp, now: datetime
) -> RhythmBranchRecord:
    if op.source_frame > branch.source_duration_frames:
        raise RhythmCommandError("anchor lies beyond the project duration")
    if any(a.source_frame == op.source_frame for a in branch.tempo_anchors):
        raise RhythmCommandError("a tempo anchor already exists at that source frame")
    if any(a.musical_position == op.musical_position for a in branch.tempo_anchors):
        raise RhythmCommandError("a tempo anchor already exists at that musical position")
    anchor = TempoAnchor(
        id=uuid.uuid4(),
        branch_id=branch.id,
        source_frame=op.source_frame,
        musical_position=op.musical_position,
        origin=RhythmOrigin.MANUAL,
        created_at=now,
        updated_at=now,
    )
    anchors = sorted([*branch.tempo_anchors, anchor], key=lambda a: a.source_frame)
    return _rebuild(branch, now=now, tempo_anchors=anchors)


def _apply_move_anchor(
    branch: RhythmBranchRecord, op: MoveTempoAnchorOp, now: datetime
) -> RhythmBranchRecord:
    anchor = _find_anchor(branch, op.anchor_id)
    if anchor.lock_state is AnchorLockState.LOCKED and not op.force_locked:
        raise RhythmCommandError("the tempo anchor is locked")
    changes: dict[str, Any] = {"updated_at": now}
    if op.axis == "source":
        assert op.source_frame is not None
        changes["source_frame"] = op.source_frame
    else:
        assert op.musical_position is not None
        changes["musical_position"] = op.musical_position
    moved = anchor.model_copy(update=changes)
    anchors = sorted(
        [moved if item.id == anchor.id else item for item in branch.tempo_anchors],
        key=lambda item: item.source_frame,
    )
    if op.axis == "source":
        _validate_anchor_neighbors(anchors, moved)
    pulses = branch.pulses
    if op.axis == "source" and anchor.pulse_id is not None:
        pulses = [
            pulse.model_copy(update={"source_frame": moved.source_frame})
            if pulse.id == anchor.pulse_id
            else pulse
            for pulse in pulses
        ]
    return _rebuild(branch, now=now, tempo_anchors=anchors, pulses=pulses)


def _apply_delete_anchor(
    branch: RhythmBranchRecord, op: DeleteTempoAnchorOp, now: datetime
) -> RhythmBranchRecord:
    anchor = _find_anchor(branch, op.anchor_id)
    if anchor.lock_state is AnchorLockState.LOCKED and not op.force_locked:
        raise RhythmCommandError("the tempo anchor is locked")
    pulses = [
        pulse.model_copy(update={"tempo_anchor_id": None})
        if pulse.tempo_anchor_id == anchor.id
        else pulse
        for pulse in branch.pulses
    ]
    return _rebuild(
        branch,
        now=now,
        tempo_anchors=[item for item in branch.tempo_anchors if item.id != anchor.id],
        pulses=pulses,
    )


def _apply_lock(
    branch: RhythmBranchRecord, op: SetAnchorLockOp, now: datetime
) -> RhythmBranchRecord:
    anchor = _find_anchor(branch, op.anchor_id).model_copy(
        update={"lock_state": op.lock_state, "updated_at": now}
    )
    return _rebuild(
        branch,
        now=now,
        tempo_anchors=[anchor if item.id == anchor.id else item for item in branch.tempo_anchors],
    )


def _meter_candidate(
    numerator: int,
    denominator: int,
    grouping: list[int],
    unit: MeterTempoUnit,
) -> MeterCandidate:
    try:
        return manual_candidate(numerator, denominator, grouping, unit)
    except ValueError as exc:
        raise RhythmCommandError(str(exc)) from exc


def _rebuild_meter_regions(
    branch: RhythmBranchRecord, regions: list[MeterRegion]
) -> list[MeterRegion]:
    ordered = sorted(regions, key=lambda region: region.start.as_quarter_notes())
    result: list[MeterRegion] = []
    for index, region in enumerate(ordered):
        end = ordered[index + 1].start if index + 1 < len(ordered) else None
        result.append(region.model_copy(update={"end": end}))
    return result


def _validate_meter(branch: RhythmBranchRecord) -> None:
    if branch.meter_regions:
        meter_map_for_branch(branch)


def _apply_add_meter(
    branch: RhythmBranchRecord, op: AddMeterRegionOp, now: datetime
) -> RhythmBranchRecord:
    candidate = _meter_candidate(op.numerator, op.denominator, op.grouping, op.display_tempo_unit)
    region = MeterRegion(
        id=uuid.uuid4(),
        branch_id=branch.id,
        start=op.start,
        numerator=candidate.numerator,
        denominator=candidate.denominator,
        grouping=candidate.grouping,
        display_tempo_unit=candidate.display_tempo_unit,
        origin=RhythmOrigin.MANUAL,
    )
    regions = _rebuild_meter_regions(branch, [*branch.meter_regions, region])
    updated = _rebuild(branch, now=now, meter_regions=regions)
    _validate_meter(updated)
    return updated


def _apply_update_meter(
    branch: RhythmBranchRecord, op: UpdateMeterRegionOp, now: datetime
) -> RhythmBranchRecord:
    current = next((region for region in branch.meter_regions if region.id == op.region_id), None)
    if current is None:
        raise RhythmCommandError("meter region is not in the active branch")
    candidate = _meter_candidate(
        op.numerator if op.numerator is not None else current.numerator,
        op.denominator if op.denominator is not None else current.denominator,
        op.grouping if op.grouping is not None else current.grouping,
        op.display_tempo_unit if op.display_tempo_unit is not None else current.display_tempo_unit,
    )
    updated_region = current.model_copy(
        update={
            "numerator": candidate.numerator,
            "denominator": candidate.denominator,
            "grouping": candidate.grouping,
            "display_tempo_unit": candidate.display_tempo_unit,
            "origin": RhythmOrigin.MANUAL,
            "grid_validity": GridValidity.VALID,
        }
    )
    regions = _rebuild_meter_regions(
        branch,
        [updated_region if region.id == current.id else region for region in branch.meter_regions],
    )
    updated = _rebuild(branch, now=now, meter_regions=regions)
    _validate_meter(updated)
    return updated


def _apply_delete_meter(
    branch: RhythmBranchRecord, op: DeleteMeterRegionOp, now: datetime
) -> RhythmBranchRecord:
    if not any(region.id == op.region_id for region in branch.meter_regions):
        raise RhythmCommandError("meter region is not in the active branch")
    regions = _rebuild_meter_regions(
        branch,
        [region for region in branch.meter_regions if region.id != op.region_id],
    )
    updated = _rebuild(branch, now=now, meter_regions=regions)
    _validate_meter(updated)
    return updated


def _apply_review(
    branch: RhythmBranchRecord, op: SetReviewStateOp, now: datetime
) -> RhythmBranchRecord:
    if op.target == "pulse":
        if not any(pulse.id == op.target_id for pulse in branch.pulses):
            raise RhythmCommandError("pulse is not in the active branch")
        pulses = [
            pulse.model_copy(update={"review_state": op.review_state})
            if pulse.id == op.target_id
            else pulse
            for pulse in branch.pulses
        ]
        return _rebuild(branch, now=now, pulses=pulses)
    if not any(region.id == op.target_id for region in branch.meter_regions):
        raise RhythmCommandError("meter region is not in the active branch")
    regions = [
        region.model_copy(update={"review_state": op.review_state})
        if region.id == op.target_id
        else region
        for region in branch.meter_regions
    ]
    return _rebuild(branch, now=now, meter_regions=regions)


def _apply_bar_origin(
    branch: RhythmBranchRecord,
    op: SetBarOriginOp,
    project_rate: int,
    now: datetime,
) -> RhythmBranchRecord:
    origin = branch.bar_origin
    updates: dict[str, Any] = {}
    if op.first_bar_number is not None:
        updates["first_bar_number"] = op.first_bar_number
    if op.first_downbeat_source is not None:
        try:
            updates["first_numbered_bar_position"] = tempo_map_for_branch(
                branch, project_rate
            ).map_source_to_musical(op.first_downbeat_source)
        except Exception as exc:
            raise RhythmCommandError(str(exc)) from exc
    if op.clear_pickup:
        updates["pickup"] = None
    if op.pickup_start_source is not None:
        if op.first_downbeat_source is None:
            raise RhythmCommandError("a pickup needs the first downbeat source in the same command")
        map_ = tempo_map_for_branch(branch, project_rate)
        try:
            start = map_.map_source_to_musical(op.pickup_start_source)
        except Exception as exc:
            raise RhythmCommandError(str(exc)) from exc
        end = updates["first_numbered_bar_position"]
        updates["pickup"] = MusicalInterval(start=start, end=end)
    try:
        new_origin = BarOriginState.model_validate({**origin.model_dump(), **updates})
    except ValueError as exc:
        raise RhythmCommandError(str(exc)) from exc
    return _rebuild(branch, now=now, bar_origin=new_origin)


def _apply_reinterpret(
    branch: RhythmBranchRecord,
    op: ReinterpretTempoOp,
    project_rate: int,
    now: datetime,
) -> RhythmBranchRecord:
    map_ = tempo_map_for_branch(branch, project_rate)
    try:
        changed = reinterpret_tempo_map(
            map_,
            start_anchor_id=op.start_anchor_id,
            end_anchor_id=op.end_anchor_id,
            mode=op.mode,
            updated_at=now,
        )
    except TempoMapConflictError as exc:
        raise RhythmCommandError(str(exc)) from exc
    anchors = [
        TempoAnchor(
            id=anchor.id,
            branch_id=branch.id,
            source_frame=anchor.source_frame,
            musical_position=anchor.musical_position,
            lock_state=anchor.lock_state,
            origin=anchor.origin,
            pulse_id=anchor.pulse_id,
            confidence=anchor.confidence,
            created_at=anchor.created_at,
            updated_at=anchor.updated_at,
        )
        for anchor in changed.anchors
    ]
    return _rebuild(branch, now=now, tempo_anchors=anchors)


def apply_rhythm_op(
    branch: RhythmBranchRecord,
    op: RhythmCommandOp,
    *,
    project_sample_rate: int,
    now: datetime | None = None,
) -> RhythmBranchRecord:
    """Pure branch edit used by the transactional command service."""
    moment = now or _now()
    if isinstance(op, AddPulseOp):
        return _apply_add_pulse(branch, op, project_sample_rate, moment)
    if isinstance(op, MovePulseOp):
        return _apply_move_pulse(branch, op, moment)
    if isinstance(op, DeletePulseOp):
        return _apply_delete_pulse(branch, op, moment)
    if isinstance(op, SetDownbeatOp):
        return _apply_set_downbeat(branch, op, moment)
    if isinstance(op, AddTempoAnchorOp):
        return _apply_add_anchor(branch, op, moment)
    if isinstance(op, MoveTempoAnchorOp):
        return _apply_move_anchor(branch, op, moment)
    if isinstance(op, DeleteTempoAnchorOp):
        return _apply_delete_anchor(branch, op, moment)
    if isinstance(op, SetAnchorLockOp):
        return _apply_lock(branch, op, moment)
    if isinstance(op, AddMeterRegionOp):
        return _apply_add_meter(branch, op, moment)
    if isinstance(op, UpdateMeterRegionOp):
        return _apply_update_meter(branch, op, moment)
    if isinstance(op, DeleteMeterRegionOp):
        return _apply_delete_meter(branch, op, moment)
    if isinstance(op, SetReviewStateOp):
        return _apply_review(branch, op, moment)
    if isinstance(op, SetBarOriginOp):
        return _apply_bar_origin(branch, op, project_sample_rate, moment)
    if isinstance(op, ReinterpretTempoOp):
        return _apply_reinterpret(branch, op, project_sample_rate, moment)
    raise RhythmCommandError(f"unsupported rhythm command {op!r}")


class RhythmCommandService:
    """Transactional command facade for one SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _branch(self, conn: sqlite3.Connection, row: sqlite3.Row) -> RhythmBranchRecord:
        state = ProjectRhythmState.model_validate_json(row["rhythm_state"])
        if state.active_branch_id is None:
            raise RhythmCommandError("the project has no active editable branch")
        branch_row = conn.execute(
            "SELECT record_json FROM rhythm_branches WHERE id = ? AND project_id = ?",
            (str(state.active_branch_id), row["id"]),
        ).fetchone()
        if branch_row is None:
            raise RhythmCommandError("the active editable branch does not exist")
        return RhythmBranchRecord.model_validate_json(branch_row["record_json"])

    def apply(self, project_id: Uuid, request: RhythmCommandRequest) -> RhythmCommandResult:
        conn = _db_open(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (str(project_id),)).fetchone()
            if row is None:
                raise RhythmCommandError("project does not exist")
            receipt = conn.execute(
                "SELECT * FROM rhythm_command_receipts "
                "WHERE project_id = ? AND idempotency_key = ?",
                (str(project_id), request.idempotency_key),
            ).fetchone()
            if receipt is not None:
                if receipt["command_id"] != str(request.command_id):
                    raise RhythmCommandConflict(
                        "idempotency key was already used by another command"
                    )
                result = RhythmCommandResult.model_validate_json(receipt["result_json"])
                conn.execute("COMMIT")
                return result
            if row["revision"] != request.base_revision:
                raise StaleRevisionError(row["revision"])
            branch = self._branch(conn, row)
            now = _now()
            new_branch = apply_rhythm_op(
                branch,
                request.op,
                project_sample_rate=int(row["sample_rate"] or 0),
                now=now,
            )
            updated = conn.execute(
                "UPDATE rhythm_branches SET revision = ?, updated_at = ?, "
                "record_json = ? WHERE id = ? AND revision = ?",
                (
                    new_branch.revision,
                    _timestamp(new_branch.updated_at),
                    new_branch.model_dump_json(),
                    str(branch.id),
                    branch.revision,
                ),
            )
            if updated.rowcount != 1:
                raise RhythmCommandConflict("the editable branch changed during the command")
            seq = int(row["rhythm_history_seq"]) + 1
            conn.execute(
                "DELETE FROM rhythm_command_history WHERE project_id = ? AND seq > ?",
                (str(project_id), int(row["rhythm_history_seq"])),
            )
            conn.execute(
                "INSERT INTO rhythm_command_history "
                "(id, project_id, seq, command_id, op_type, before_json, after_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    str(project_id),
                    seq,
                    str(request.command_id),
                    request.op.type,
                    branch.model_dump_json(),
                    new_branch.model_dump_json(),
                    _timestamp(now),
                ),
            )
            revision = int(row["revision"]) + 1
            conn.execute(
                "UPDATE projects SET revision = ?, updated_at = ?, rhythm_history_seq = ? "
                "WHERE id = ?",
                (revision, _timestamp(now), seq, str(project_id)),
            )
            result = RhythmCommandResult(
                revision=revision,
                branch=new_branch,
                can_undo=True,
                can_redo=False,
            )
            conn.execute(
                "INSERT INTO rhythm_command_receipts "
                "(project_id, idempotency_key, command_id, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(project_id),
                    request.idempotency_key,
                    str(request.command_id),
                    result.model_dump_json(),
                    _timestamp(now),
                ),
            )
            conn.execute("COMMIT")
            return result
        except (RhythmCommandError, StaleRevisionError):
            conn.execute("ROLLBACK")
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise RhythmCommandConflict(f"cannot apply rhythm command: {exc}") from exc
        finally:
            conn.close()

    def undo(self, project_id: Uuid, base_revision: int) -> RhythmCommandResult:
        return self._move(project_id, base_revision, -1)

    def redo(self, project_id: Uuid, base_revision: int) -> RhythmCommandResult:
        return self._move(project_id, base_revision, 1)

    def _move(self, project_id: Uuid, base_revision: int, direction: int) -> RhythmCommandResult:
        conn = _db_open(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (str(project_id),)).fetchone()
            if row is None:
                raise RhythmCommandError("project does not exist")
            if row["revision"] != base_revision:
                raise StaleRevisionError(row["revision"])
            seq = int(row["rhythm_history_seq"])
            if direction < 0:
                if seq < 0:
                    raise RhythmCommandError("there is no rhythm edit to undo")
                read_seq = seq
                target_seq = seq - 1
                key = "before_json"
            else:
                entry = conn.execute(
                    "SELECT MAX(seq) FROM rhythm_command_history WHERE project_id = ?",
                    (str(project_id),),
                ).fetchone()
                if entry is None or entry[0] is None or seq + 1 > entry[0]:
                    raise RhythmCommandError("there is no rhythm edit to redo")
                read_seq = seq + 1
                target_seq = seq + 1
                key = "after_json"
            entry = conn.execute(
                f"SELECT {key} FROM rhythm_command_history WHERE project_id = ? AND seq = ?",
                (str(project_id), read_seq),
            ).fetchone()
            assert entry is not None
            branch = RhythmBranchRecord.model_validate_json(entry[key])
            now = _now()
            conn.execute(
                "UPDATE rhythm_branches SET revision = ?, updated_at = ?, "
                "record_json = ? WHERE id = ?",
                (
                    branch.revision,
                    _timestamp(now),
                    branch.model_dump_json(),
                    str(branch.id),
                ),
            )
            revision = int(row["revision"]) + 1
            conn.execute(
                "UPDATE projects SET revision = ?, updated_at = ?, rhythm_history_seq = ? "
                "WHERE id = ?",
                (revision, _timestamp(now), target_seq, str(project_id)),
            )
            result = RhythmCommandResult(
                revision=revision,
                branch=branch,
                can_undo=target_seq >= 0,
                can_redo=True,
            )
            conn.execute("COMMIT")
            return result
        except (RhythmCommandError, StaleRevisionError):
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
