"""Metronome schedule generation and deterministic render mapping (M3.14)."""

from __future__ import annotations

from basseparate.domain.grid import GridDetail, GridEventKind
from basseparate.domain.meter import MeterMap
from basseparate.domain.metronome import (
    MAX_SCHEDULE_EVENTS,
    ClickEvent,
    ClickStrength,
    MetronomeSchedule,
    RenderClick,
)
from basseparate.domain.rhythm import (
    BarOriginState,
    MetronomeSettings,
    MetronomeSubdivision,
    MusicalPosition,
)
from basseparate.domain.tempo import TempoMap
from basseparate.rhythm.grid import GridError, derive_grid

_DETAIL = {
    MetronomeSubdivision.PRIMARY: GridDetail.PRIMARY,
    MetronomeSubdivision.DENOMINATOR: GridDetail.DENOMINATOR,
    MetronomeSubdivision.HALF_BEAT: GridDetail.HALF_BEAT,
    MetronomeSubdivision.QUARTER_BEAT: GridDetail.QUARTER_BEAT,
}


class MetronomeError(ValueError):
    """The requested metronome range or settings are invalid."""


def build_metronome_schedule(
    tempo_map: TempoMap,
    meter_map: MeterMap,
    bar_origin: BarOriginState,
    settings: MetronomeSettings,
    *,
    start: MusicalPosition | None = None,
    end: MusicalPosition | None = None,
) -> MetronomeSchedule:
    """Build bounded clicks from derived grid events (§16.4-§16.6)."""
    if not settings.enabled:
        return MetronomeSchedule(
            start=start or tempo_map.musical_start,
            end=end or tempo_map.musical_end,
            subdivision=settings.subdivision,
        )
    detail = _DETAIL[settings.subdivision]
    try:
        grid = derive_grid(
            tempo_map,
            meter_map,
            bar_origin,
            start=start,
            end=end,
            detail=detail,
        )
    except GridError as exc:
        raise MetronomeError(str(exc)) from exc
    clicks: list[ClickEvent] = []
    seen: set[int] = set()
    for event in grid.events:
        if event.source_frame in seen:
            continue
        if event.kind is GridEventKind.BAR:
            strength = ClickStrength.DOWNBEAT
        elif event.kind is GridEventKind.PRIMARY:
            region = meter_map.region_at(event.musical_position)
            compound = bool(region and any(part > 1 for part in region.candidate.grouping))
            strength = (
                ClickStrength.GROUPING
                if compound and event.beat is not None and event.beat > 1
                else ClickStrength.BEAT
            )
        else:
            strength = ClickStrength.SUBDIVISION
        seen.add(event.source_frame)
        clicks.append(
            ClickEvent(
                musical_position=event.musical_position,
                source_frame=event.source_frame,
                strength=strength,
                subdivision=settings.subdivision,
                bar_number=event.bar_number,
                beat=event.beat,
            )
        )
        if len(clicks) > MAX_SCHEDULE_EVENTS:
            raise MetronomeError(
                f"schedule exceeds {MAX_SCHEDULE_EVENTS} clicks; request a smaller range"
            )
    return MetronomeSchedule(
        start=grid.start,
        end=grid.end,
        subdivision=settings.subdivision,
        clicks=clicks,
        unmapped_gap_detected=grid.unmapped_gap_detected,
    )


def map_clicks_to_render(
    schedule: MetronomeSchedule,
    *,
    source_start: int,
    output_start_frame: int,
    rate: float = 1.0,
) -> list[RenderClick]:
    """Map source-frame clicks to output frames at a constant playback rate.

    ``rate`` follows the transport convention (1.0 = source speed). Exact
    integer division is used per click, so repeated schedule builds do not
    accumulate rounding error.
    """
    if rate <= 0:
        raise MetronomeError("playback rate must be positive")
    return [
        RenderClick(
            render_frame=max(
                0,
                round(output_start_frame + (click.source_frame - source_start) / rate),
            ),
            source_frame=click.source_frame,
            strength=click.strength,
            loop_iteration=click.loop_iteration,
        )
        for click in schedule.clicks
        if click.source_frame >= source_start
    ]


def repeat_loop_clicks(
    schedule: MetronomeSchedule,
    *,
    loop_start: int,
    loop_end: int,
    output_start_frame: int,
    passes: int,
    rate: float = 1.0,
) -> list[RenderClick]:
    """Place loop-internal clicks for each pass using exact per-pass bases.

    Each pass's render base is computed from its integer source span, so
    fractional output rounding never accumulates independently per pass.
    """
    if loop_end <= loop_start:
        raise MetronomeError("loop end must be after its start")
    if passes < 1:
        raise MetronomeError("passes must be positive")
    if rate <= 0:
        raise MetronomeError("rate must be positive")
    internal = [click for click in schedule.clicks if loop_start <= click.source_frame < loop_end]
    span = loop_end - loop_start
    clicks: list[RenderClick] = []
    for iteration in range(1, passes + 1):
        base = output_start_frame + round((iteration - 1) * span / rate)
        for click in internal:
            clicks.append(
                RenderClick(
                    render_frame=max(0, base + round((click.source_frame - loop_start) / rate)),
                    source_frame=click.source_frame,
                    strength=click.strength,
                    loop_iteration=iteration,
                )
            )
    return clicks
