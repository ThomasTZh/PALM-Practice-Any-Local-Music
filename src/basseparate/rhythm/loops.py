"""Musical/source loop resolution and conversion (M3.13, §15).

Source loops remain authoritative in source frames. Musical loops keep
exact musical boundaries and resolve/cached source frames through the
active branch; an unmapped range becomes explicitly unresolved rather
than being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from basseparate.domain.common import Revision, Uuid
from basseparate.domain.grid import GridDetail
from basseparate.domain.meter import MeterMap
from basseparate.domain.practice import PracticeLoop
from basseparate.domain.rhythm import BarOriginState, LoopAnchorMode, MusicalPosition
from basseparate.domain.tempo import TempoMap
from basseparate.rhythm.grid import derive_grid

#: Boundaries farther than this from a bar/primary grid point need explicit
#: confirmation before converting source→musical.
GRID_ALIGNMENT_TOLERANCE_QUARTERS = Fraction(1, 10)


class LoopResolutionError(ValueError):
    """A loop boundary cannot be resolved through the active grid."""


class LoopAlignmentError(LoopResolutionError):
    """Conversion needs explicit confirmation because a boundary is off-grid."""

    def __init__(self, warnings: list[str]) -> None:
        super().__init__("; ".join(warnings))
        self.warnings = warnings


@dataclass(frozen=True)
class LoopConversion:
    loop: PracticeLoop
    warnings: list[str] = field(default_factory=list)


def _musical(value: Fraction) -> MusicalPosition:
    return MusicalPosition(numerator=value.numerator, denominator=value.denominator)


def resolve_loop(
    loop: PracticeLoop,
    tempo_map: TempoMap,
    *,
    branch_id: Uuid,
    branch_revision: Revision,
) -> PracticeLoop:
    """Resolve a musical loop through the active map; leave source loops alone."""
    if loop.anchor_mode is LoopAnchorMode.SOURCE:
        return loop
    if loop.start_musical is None or loop.end_musical is None:
        raise LoopResolutionError("a musical loop is missing musical boundaries")
    try:
        start = tempo_map.map_musical_to_source(loop.start_musical)
        end = tempo_map.map_musical_to_source(loop.end_musical)
    except ValueError:
        return loop.model_copy(
            update={
                "unresolved": True,
                "resolved_source_start": None,
                "resolved_source_end": None,
                "grid_branch_id": branch_id,
                "grid_branch_revision": branch_revision,
            }
        )
    if end <= start:
        return loop.model_copy(
            update={
                "unresolved": True,
                "resolved_source_start": None,
                "resolved_source_end": None,
                "grid_branch_id": branch_id,
                "grid_branch_revision": branch_revision,
            }
        )
    return loop.model_copy(
        update={
            "start_frames": start,
            "end_frames": end,
            "resolved_source_start": start,
            "resolved_source_end": end,
            "grid_branch_id": branch_id,
            "grid_branch_revision": branch_revision,
            "unresolved": False,
        }
    )


def resolve_loops(
    loops: list[PracticeLoop],
    tempo_map: TempoMap,
    *,
    branch_id: Uuid,
    branch_revision: Revision,
) -> list[PracticeLoop]:
    return [
        resolve_loop(loop, tempo_map, branch_id=branch_id, branch_revision=branch_revision)
        for loop in loops
    ]


def _boundary_grid_distance(
    tempo_map: TempoMap,
    meter_map: MeterMap,
    bar_origin: BarOriginState,
    position: MusicalPosition,
    *,
    include_beats: bool,
) -> Fraction:
    grid = derive_grid(
        tempo_map,
        meter_map,
        bar_origin,
        detail=GridDetail.PRIMARY if include_beats else GridDetail.BARS,
    )
    target = position.as_quarter_notes()
    distances = [
        abs(tempo_map.map_source_to_musical(event.source_frame).as_quarter_notes() - target)
        for event in grid.events
        if event.kind.value == "bar" or (include_beats and event.kind.value == "primary")
    ]
    return min(distances) if distances else Fraction(10**9)


def convert_loop(
    loop: PracticeLoop,
    tempo_map: TempoMap,
    meter_map: MeterMap,
    bar_origin: BarOriginState,
    *,
    target: LoopAnchorMode,
    branch_id: Uuid,
    branch_revision: Revision,
    confirm_off_grid: bool = False,
) -> LoopConversion:
    """Convert source↔musical loop authority as one explicit operation."""
    if target is loop.anchor_mode:
        return LoopConversion(loop)
    if target is LoopAnchorMode.MUSICAL:
        start_musical = tempo_map.map_source_to_musical(loop.start_frames)
        end_musical = tempo_map.map_source_to_musical(loop.end_frames)
        warnings: list[str] = []
        for label, position in (
            ("start", start_musical),
            ("end", end_musical),
        ):
            distance = _boundary_grid_distance(
                tempo_map,
                meter_map,
                bar_origin,
                position,
                include_beats=True,
            )
            if distance > GRID_ALIGNMENT_TOLERANCE_QUARTERS:
                warnings.append(
                    f"{label} boundary is {float(distance):.3f} quarter notes from the grid"
                )
        if warnings and not confirm_off_grid:
            raise LoopAlignmentError(warnings)
        return LoopConversion(
            loop.model_copy(
                update={
                    "anchor_mode": LoopAnchorMode.MUSICAL,
                    "start_musical": start_musical,
                    "end_musical": end_musical,
                    "resolved_source_start": loop.start_frames,
                    "resolved_source_end": loop.end_frames,
                    "grid_branch_id": branch_id,
                    "grid_branch_revision": branch_revision,
                    "unresolved": False,
                }
            ),
            warnings=warnings,
        )
    if loop.start_musical is None or loop.end_musical is None:
        raise LoopResolutionError("a musical loop is missing musical boundaries")
    try:
        start = tempo_map.map_musical_to_source(loop.start_musical)
        end = tempo_map.map_musical_to_source(loop.end_musical)
    except ValueError as exc:
        raise LoopResolutionError(str(exc)) from exc
    if end <= start:
        raise LoopResolutionError("the musical loop collapses to an empty source range")
    return LoopConversion(
        loop.model_copy(
            update={
                "anchor_mode": LoopAnchorMode.SOURCE,
                "start_frames": start,
                "end_frames": end,
                "resolved_source_start": start,
                "resolved_source_end": end,
                "grid_branch_id": branch_id,
                "grid_branch_revision": branch_revision,
                "unresolved": False,
            }
        )
    )
