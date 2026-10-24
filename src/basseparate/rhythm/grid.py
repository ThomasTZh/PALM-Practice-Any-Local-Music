"""Derived bar/beat/subdivision grid and bar-origin operations (M3.9 §11).

Only full bars inside the mapped interval are emitted. Bar numbering is
continuous through meter changes; material before the first numbered bar
is labelled pickup. Requests outside the tempo map produce explicit gaps
and no events there.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from fractions import Fraction

from basseparate.domain.common import SamplePosition
from basseparate.domain.grid import (
    GridDetail,
    GridEvent,
    GridEventKind,
    GridGap,
    GridResult,
)
from basseparate.domain.meter import ManualMeterRegion, MeterMap
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    MusicalInterval,
    MusicalPosition,
)
from basseparate.domain.rhythm_decode import SourceFrameFraction
from basseparate.domain.tempo import TempoMap

MAX_GRID_EVENTS = 20_000
_EPSILON = Fraction(1, 1_000_000)


class GridError(ValueError):
    """The grid request or meter/origin alignment is invalid."""


def _musical(value: Fraction) -> MusicalPosition:
    return MusicalPosition(numerator=value.numerator, denominator=value.denominator)


def _quarter(value: MusicalPosition) -> Fraction:
    return value.as_quarter_notes()


def _round_half_up(value: Fraction) -> int:
    return int(math.floor(value + Fraction(1, 2)))


def _bar_start_positions(
    tempo_map: TempoMap, meter_map: MeterMap
) -> list[tuple[MusicalPosition, ManualMeterRegion, Fraction]]:
    """Full bar starts over the mapped interval, with their region."""
    bars: list[tuple[MusicalPosition, ManualMeterRegion, Fraction]] = []
    map_start = _quarter(tempo_map.musical_start)
    map_end = _quarter(tempo_map.musical_end)
    for index, region in enumerate(meter_map.regions):
        start = max(_quarter(region.start), map_start)
        if index + 1 < len(meter_map.regions):
            end = _quarter(meter_map.regions[index + 1].start)
        else:
            end = map_end
        end = min(end, map_end)
        bar_length = region.candidate.bar_length_quarters
        if bar_length <= 0:
            continue
        current = start
        while current + bar_length <= end + _EPSILON:
            bars.append((_musical(current), region, bar_length))
            current += bar_length
    return bars


def _bar_label(bar_number: int | None, pickup: bool) -> str:
    if pickup or bar_number is None:
        return "pickup"
    return str(bar_number)


def _primary_positions(
    region: ManualMeterRegion,
) -> list[tuple[Fraction, int]]:
    """Primary beat offsets in quarter notes and their 1-based beat index."""
    denominator = region.candidate.denominator
    total = 0
    result: list[tuple[Fraction, int]] = []
    for beat, part in enumerate(region.candidate.grouping, start=1):
        result.append((Fraction(total * 4, denominator), beat))
        total += part
    return result


def derive_grid(
    tempo_map: TempoMap,
    meter_map: MeterMap,
    bar_origin: BarOriginState,
    *,
    start: MusicalPosition | None = None,
    end: MusicalPosition | None = None,
    detail: GridDetail = GridDetail.PRIMARY,
    max_events: int = MAX_GRID_EVENTS,
    created_at: datetime | None = None,
) -> GridResult:
    """Derive visible grid events for a musical range (§11.1-§11.9)."""
    if max_events <= 0:
        raise GridError("max_events must be positive")
    map_start = _quarter(tempo_map.musical_start)
    map_end = _quarter(tempo_map.musical_end)
    requested_start = _quarter(start) if start is not None else map_start
    requested_end = _quarter(end) if end is not None else map_end
    if requested_end <= requested_start:
        raise GridError("grid range end must be after start")

    gaps: list[GridGap] = []
    if requested_start < map_start:
        gaps.append(GridGap(start=_musical(requested_start), end=_musical(map_start)))
        requested_start = map_start
    if requested_end > map_end:
        gaps.append(GridGap(start=_musical(map_end), end=_musical(requested_end)))
        requested_end = map_end
    if requested_end <= requested_start:
        return GridResult(
            detail=detail,
            start=_musical(requested_start),
            end=_musical(requested_end),
            events=[],
            gaps=gaps,
            unmapped_gap_detected=bool(gaps),
            created_at=created_at or datetime.now(UTC),
        )

    bars = _bar_start_positions(tempo_map, meter_map)
    if not bars:
        raise GridError("no full bar fits inside the mapped tempo interval")
    origin = _quarter(bar_origin.first_numbered_bar_position)
    origin_index = None
    for index, (bar_start, _region, _length) in enumerate(bars):
        if _quarter(bar_start) == origin:
            origin_index = index
            break
    if origin_index is None:
        raise GridError("the first numbered bar must start on a bar boundary")

    events: list[GridEvent] = []
    seen: set[tuple[Fraction, GridEventKind]] = set()

    def add_event(
        kind: GridEventKind,
        position: Fraction,
        *,
        bar_number: int | None,
        beat: int | None,
        subdivision: int | None,
        pickup: bool,
        label: str,
    ) -> None:
        if position < requested_start - _EPSILON or position > requested_end + _EPSILON:
            return
        if position < map_start - _EPSILON or position > map_end + _EPSILON:
            return
        key = (position, kind)
        if key in seen:
            return
        source_fraction = tempo_map.source_fraction_for_musical(_musical(position))
        source = _round_half_up(source_fraction)
        seen.add(key)
        events.append(
            GridEvent(
                kind=kind,
                musical_position=_musical(position),
                source_fraction=SourceFrameFraction(
                    numerator=source_fraction.numerator,
                    denominator=source_fraction.denominator,
                ),
                source_frame=SamplePosition(source),
                bar_number=bar_number,
                beat=beat,
                subdivision=subdivision,
                pickup=pickup,
                label=label,
            )
        )

    for index, (bar_start, region, _length) in enumerate(bars):
        if index > origin_index:
            bar_number: int | None = bar_origin.first_bar_number + (index - origin_index)
            pickup = False
        elif index == origin_index:
            bar_number = bar_origin.first_bar_number
            pickup = False
        else:
            bar_number = None
            pickup = True
        bar_label = _bar_label(bar_number, pickup)
        bar_quarter = _quarter(bar_start)
        bar_length = region.candidate.bar_length_quarters
        bar_end = bar_quarter + bar_length
        if bar_end < requested_start - _EPSILON or bar_quarter > requested_end + _EPSILON:
            continue

        add_event(
            GridEventKind.BAR,
            bar_quarter,
            bar_number=bar_number,
            beat=None,
            subdivision=None,
            pickup=pickup,
            label=bar_label,
        )
        if detail is GridDetail.BARS:
            continue

        primaries = _primary_positions(region)
        for offset, beat in primaries:
            add_event(
                GridEventKind.PRIMARY,
                bar_quarter + offset,
                bar_number=bar_number,
                beat=beat,
                subdivision=None,
                pickup=pickup,
                label=f"{bar_label}.{beat}",
            )
        if detail is GridDetail.PRIMARY:
            continue

        denominator = region.candidate.denominator
        unit = Fraction(4, denominator)
        primary_offsets = {offset for offset, _beat in primaries}
        for denominator_index in range(region.candidate.numerator):
            offset = denominator_index * unit
            if offset in primary_offsets:
                continue
            add_event(
                GridEventKind.DENOMINATOR,
                bar_quarter + offset,
                bar_number=bar_number,
                beat=None,
                subdivision=denominator_index + 1,
                pickup=pickup,
                label=f"{bar_label}.{denominator_index + 1}",
            )
        if detail is GridDetail.DENOMINATOR:
            continue

        for beat_index, (offset, beat) in enumerate(primaries, start=1):
            next_offset = primaries[beat_index][0] if beat_index < len(primaries) else bar_length
            span = next_offset - offset
            if span <= 0:
                continue
            levels = (
                ((2, GridEventKind.HALF_BEAT),)
                if detail is GridDetail.HALF_BEAT
                else (
                    (2, GridEventKind.HALF_BEAT),
                    (4, GridEventKind.QUARTER_BEAT),
                )
            )
            for numerator, kind in levels:
                for step in range(1, numerator):
                    if kind is GridEventKind.QUARTER_BEAT and step == numerator // 2:
                        continue  # already emitted as a half-beat
                    add_event(
                        kind,
                        bar_quarter + offset + span * Fraction(step, numerator),
                        bar_number=bar_number,
                        beat=beat,
                        subdivision=step,
                        pickup=pickup,
                        label=f"{bar_label}.{beat}.{step}",
                    )

    events.sort(key=lambda event: _quarter(event.musical_position))
    if len(events) > max_events:
        raise GridError(
            f"grid request produced {len(events)} events, exceeding {max_events}; "
            "request a narrower musical range"
        )
    return GridResult(
        detail=detail,
        start=_musical(requested_start),
        end=_musical(requested_end),
        events=events,
        gaps=gaps,
        unmapped_gap_detected=bool(gaps),
        created_at=created_at or datetime.now(UTC),
    )


def first_downbeat_origin(
    tempo_map: TempoMap,
    *,
    source_frame: int,
    first_bar_number: int = 1,
    pickup: MusicalInterval | None = None,
) -> BarOriginState:
    """Create the bar origin from a source downbeat (§11.4)."""
    position = tempo_map.map_source_to_musical(source_frame)
    return BarOriginState(
        first_numbered_bar_position=position,
        first_bar_number=first_bar_number,
        pickup=pickup,
    )


def pickup_interval(
    tempo_map: TempoMap, *, source_start: int, first_downbeat_source: int
) -> MusicalInterval:
    """Musical pickup span ending at the first numbered downbeat (§11.6)."""
    start = tempo_map.map_source_to_musical(source_start)
    end = tempo_map.map_source_to_musical(first_downbeat_source)
    return MusicalInterval(start=start, end=end)


def set_first_numbered_bar(origin: BarOriginState, number: int) -> BarOriginState:
    """Change display numbering without moving timing (§11.5)."""
    if number < 1:
        raise GridError("bar numbers must be positive")
    return origin.model_copy(update={"first_bar_number": number})


def default_bar_origin() -> BarOriginState:
    return BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION)


def bar_beat_label(
    meter_map: MeterMap, bar_origin: BarOriginState, position: MusicalPosition
) -> tuple[int | None, int | None, bool, str]:
    """Bar/beat label for a musical position, shared with the TypeScript port."""
    origin = _quarter(bar_origin.first_numbered_bar_position)
    value = _quarter(position)
    if value < origin - _EPSILON:
        return None, None, True, "pickup"
    all_bars: list[tuple[Fraction, ManualMeterRegion]] = []
    for index, region in enumerate(meter_map.regions):
        start = _quarter(region.start)
        end = (
            _quarter(meter_map.regions[index + 1].start)
            if index + 1 < len(meter_map.regions)
            else None
        )
        bar_length = region.candidate.bar_length_quarters
        current = start
        while end is None or current < end - _EPSILON:
            all_bars.append((current, region))
            current += bar_length
            if end is None and current > value + _EPSILON:
                break
    if not all_bars:
        raise GridError("no meter bars are available for labelling")
    origin_index = next(
        (index for index, (start, _region) in enumerate(all_bars) if start == origin),
        None,
    )
    if origin_index is None:
        raise GridError("the first numbered bar must start on a bar boundary")
    value = _quarter(position)
    containing_region = meter_map.region_at(position)
    if containing_region is None:
        raise GridError("the musical position is before the first meter region")
    containing_index = None
    for index, (start, candidate_region) in enumerate(all_bars):
        if candidate_region is containing_region and start <= value:
            containing_index = index
        elif candidate_region is containing_region and start > value:
            break
    if containing_index is None or containing_index < origin_index:
        return None, None, True, "pickup"
    bar_number = bar_origin.first_bar_number + (containing_index - origin_index)
    bar_start = all_bars[containing_index][0]
    beat = 1
    cumulative = Fraction(0)
    for index, part in enumerate(containing_region.candidate.grouping, start=1):
        boundary = bar_start + cumulative
        if value >= boundary:
            beat = index
        cumulative += Fraction(part * 4, containing_region.candidate.denominator)
    return bar_number, beat, False, f"{bar_number}.{beat}"
