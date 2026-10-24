"""Tempo-map construction and region reinterpretation (M3.7, §9).

Automatic maps start from accepted decoded pulses: one anchor per pulse,
musical positions assigned by the selected pulse-unit hypothesis, source
frames unchanged. This preserves natural timing variation instead of
fitting a global BPM. Manual/sparse maps take explicit anchor points.

Half/double-time reinterpretation rescales musical distances in a region
while keeping source frames fixed. Locked anchors are never moved
silently; a conflict is raised instead.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from fractions import Fraction
from typing import Literal

from basseparate.domain.common import SampleRate, Uuid
from basseparate.domain.rhythm import (
    AnchorLockState,
    MeterTempoUnit,
    MusicalPosition,
    PulseAcceptance,
    RhythmOrigin,
    RhythmPulse,
    tempo_unit_quarter_length,
)
from basseparate.domain.tempo import (
    PULSE_UNIT_QUARTER,
    STANDARD_PULSE_UNIT_HYPOTHESES,
    PulseUnitHypothesis,
    TempoMap,
    TempoMapAnchor,
    summarize_bpm,
)

ReinterpretMode = Literal["half_time", "double_time"]


class TempoMapBuildError(ValueError):
    """The inputs cannot form a valid monotonic tempo map."""


class TempoMapConflictError(ValueError):
    """A reinterpretation would move a locked anchor or cross a neighbor."""


def _now() -> datetime:
    return datetime.now(UTC)


def _musical(value: Fraction) -> MusicalPosition:
    return MusicalPosition(numerator=value.numerator, denominator=value.denominator)


def build_automatic_tempo_map(
    pulses: list[RhythmPulse],
    *,
    project_id: Uuid,
    project_sample_rate: SampleRate,
    source_duration_frames: int,
    hypothesis: PulseUnitHypothesis = PULSE_UNIT_QUARTER,
    alternatives: list[PulseUnitHypothesis] | None = None,
    map_id: Uuid | None = None,
    created_at: datetime | None = None,
) -> TempoMap:
    """Build one anchor per accepted pulse with the chosen pulse unit (§9.3)."""
    accepted = [
        pulse for pulse in pulses if pulse.acceptance is PulseAcceptance.ACCEPTED
    ]
    if len(accepted) < 2:
        raise TempoMapBuildError("a tempo map needs at least two accepted pulses")
    accepted.sort(key=lambda pulse: pulse.source_frame)
    if len({pulse.source_frame for pulse in accepted}) != len(accepted):
        raise TempoMapBuildError("accepted pulses share a source frame")

    now = created_at or _now()
    anchors: list[TempoMapAnchor] = []
    musical = Fraction(0)
    for index, pulse in enumerate(accepted):
        if index > 0:
            distance = hypothesis.distance_for(index - 1)
            musical += Fraction(distance.numerator, distance.denominator)
        anchors.append(
            TempoMapAnchor(
                id=uuid.uuid4(),
                source_frame=pulse.source_frame,
                musical_position=_musical(musical),
                lock_state=AnchorLockState.UNLOCKED,
                origin=RhythmOrigin.AUTOMATIC,
                pulse_id=pulse.id,
                confidence=pulse.confidence,
                created_at=now,
                updated_at=now,
            )
        )
    alternatives_used = alternatives
    if alternatives_used is None:
        alternatives_used = [
            candidate
            for candidate in STANDARD_PULSE_UNIT_HYPOTHESES
            if candidate.unit is not hypothesis.unit
        ]
    try:
        map_ = TempoMap(
            id=map_id or uuid.uuid4(),
            project_id=project_id,
            project_sample_rate=project_sample_rate,
            source_duration_frames=source_duration_frames,
            hypothesis=hypothesis,
            alternatives=alternatives_used,
            anchors=anchors,
            summary_bpm=1.0,
            created_at=now,
        )
    except ValueError as exc:
        raise TempoMapBuildError(str(exc)) from exc
    return map_.model_copy(update={"summary_bpm": summarize_bpm(map_.segments)})


def build_manual_tempo_map(
    points: list[tuple[int, MusicalPosition]],
    *,
    project_id: Uuid,
    project_sample_rate: SampleRate,
    source_duration_frames: int,
    hypothesis: PulseUnitHypothesis = PULSE_UNIT_QUARTER,
    locks: list[AnchorLockState] | None = None,
    map_id: Uuid | None = None,
    created_at: datetime | None = None,
) -> TempoMap:
    """Build a sparse/manual map from explicit (source, musical) anchors (§9.11)."""
    if len(points) < 2:
        raise TempoMapBuildError("a manual tempo map needs at least two anchors")
    if locks is not None and len(locks) != len(points):
        raise TempoMapBuildError("lock states must match the anchor count")
    now = created_at or _now()
    ordered = sorted(points, key=lambda point: point[0])
    anchors = [
        TempoMapAnchor(
            id=uuid.uuid4(),
            source_frame=source,
            musical_position=musical,
            lock_state=(locks[index] if locks else AnchorLockState.UNLOCKED),
            origin=RhythmOrigin.MANUAL,
            created_at=now,
            updated_at=now,
        )
        for index, (source, musical) in enumerate(ordered)
    ]
    try:
        map_ = TempoMap(
            id=map_id or uuid.uuid4(),
            project_id=project_id,
            project_sample_rate=project_sample_rate,
            source_duration_frames=source_duration_frames,
            hypothesis=hypothesis,
            anchors=anchors,
            summary_bpm=1.0,
            created_at=now,
        )
    except ValueError as exc:
        raise TempoMapBuildError(str(exc)) from exc
    return map_.model_copy(update={"summary_bpm": summarize_bpm(map_.segments)})


def reinterpret_tempo_map(
    map_: TempoMap,
    *,
    start_anchor_id: Uuid,
    end_anchor_id: Uuid,
    mode: ReinterpretMode,
    updated_at: datetime | None = None,
) -> TempoMap:
    """Halve or double the musical distances inside an anchor region (§9.9).

    ``half_time`` doubles each musical distance (a pulse is reinterpreted as
    a longer note value); ``double_time`` halves it. Source frames never
    move. The start anchor stays fixed; a locked end anchor or a locked
    interior anchor whose position would change is a conflict, not a
    silent shift.
    """
    if mode not in ("half_time", "double_time"):
        raise ValueError(f"unsupported reinterpretation {mode!r}")
    factor = Fraction(2) if mode == "half_time" else Fraction(1, 2)
    ids = [anchor.id for anchor in map_.anchors]
    try:
        start_index = ids.index(start_anchor_id)
        end_index = ids.index(end_anchor_id)
    except ValueError as exc:
        raise TempoMapConflictError("the region anchors are not in this map") from exc
    if start_index >= end_index:
        raise TempoMapConflictError("the region needs at least two anchors in order")

    start = map_.anchors[start_index]
    end = map_.anchors[end_index]
    if end.lock_state is AnchorLockState.LOCKED:
        raise TempoMapConflictError("the region end anchor is locked")
    start_musical = start.musical_position.as_quarter_notes()
    now = updated_at or _now()
    new_anchors: list[TempoMapAnchor] = []
    for index, anchor in enumerate(map_.anchors):
        if index < start_index or index > end_index:
            new_anchors.append(anchor)
            continue
        if index == start_index:
            new_anchors.append(anchor.model_copy(update={"updated_at": now}))
            continue
        delta = anchor.musical_position.as_quarter_notes() - start_musical
        new_position = start_musical + delta * factor
        if (
            anchor.lock_state is AnchorLockState.LOCKED
            and new_position != anchor.musical_position.as_quarter_notes()
        ):
            raise TempoMapConflictError(
                f"locked anchor {anchor.id} would move during reinterpretation"
            )
        new_anchors.append(
            anchor.model_copy(
                update={
                    "musical_position": _musical(new_position),
                    "updated_at": now,
                }
            )
        )
    try:
        candidate = TempoMap(
            id=map_.id,
            project_id=map_.project_id,
            project_sample_rate=map_.project_sample_rate,
            source_duration_frames=map_.source_duration_frames,
            hypothesis=map_.hypothesis,
            alternatives=map_.alternatives,
            anchors=new_anchors,
            summary_bpm=1.0,
            summary_unit=map_.summary_unit,
            max_edge_extension_quarters=map_.max_edge_extension_quarters,
            diagnostics={
                **map_.diagnostics,
                "reinterpretation": mode,
                "region_start": str(start.id),
                "region_end": str(end.id),
            },
            created_at=now,
        )
    except ValueError as exc:
        raise TempoMapConflictError(str(exc)) from exc
    summary = summarize_bpm(candidate.segments)
    if not math.isfinite(summary):
        raise TempoMapConflictError("the reinterpreted map has a non-finite tempo")
    return candidate.model_copy(update={"summary_bpm": summary})


def map_round_trip_error_frames(map_: TempoMap, sample_step: int = 97) -> int:
    """Maximum |frame − round(map(frame))| over the mapped source interval.

    Diagnostic helper for the acceptance evidence; the documented tolerance
    is one frame because rounding happens once.
    """
    first = map_.anchors[0].source_frame
    last = map_.anchors[-1].source_frame
    worst = 0
    for frame in range(first, last + 1, max(1, sample_step)):
        musical = map_.map_source_to_musical(frame)
        back = map_.map_musical_to_source(musical)
        worst = max(worst, abs(back - frame))
    return worst


def bpm_for_display_unit(
    quarter_bpm: float, unit: MeterTempoUnit = MeterTempoUnit.QUARTER
) -> float:
    """Convert a quarter-note BPM to another explicitly labeled display unit."""
    length = float(tempo_unit_quarter_length(unit))
    return quarter_bpm / length
