"""Snap target resolution for the editor (M3.12, milestone3.md §14)."""

from __future__ import annotations

from basseparate.domain.grid import GridDetail, GridEventKind
from basseparate.domain.meter import MeterMap
from basseparate.domain.rhythm import BarOriginState
from basseparate.domain.snapping import (
    SNAP_RADIUS_CSS_PX,
    SnapMode,
    SnapResult,
    SnapTargetKind,
)
from basseparate.domain.tempo import TempoMap
from basseparate.rhythm.grid import GridError, derive_grid


class SnapError(ValueError):
    """Snapping input or the mapped grid is invalid."""


_DETAIL_FOR_MODE = {
    SnapMode.BEAT: GridDetail.PRIMARY,
    SnapMode.HALF_BEAT: GridDetail.HALF_BEAT,
    SnapMode.QUARTER_BEAT: GridDetail.QUARTER_BEAT,
    SnapMode.BAR: GridDetail.BARS,
}

_KINDS_FOR_MODE = {
    SnapMode.BEAT: {GridEventKind.PRIMARY},
    SnapMode.HALF_BEAT: {GridEventKind.PRIMARY, GridEventKind.HALF_BEAT},
    SnapMode.QUARTER_BEAT: {
        GridEventKind.PRIMARY,
        GridEventKind.HALF_BEAT,
        GridEventKind.QUARTER_BEAT,
    },
    SnapMode.BAR: {GridEventKind.BAR},
}


def effective_snap_mode(
    mode: SnapMode, *, modifier_pressed: bool, last_non_off: SnapMode
) -> SnapMode:
    """Temporary inversion while a drag modifier is held (§14.7)."""
    if not modifier_pressed:
        return mode
    if mode is SnapMode.OFF:
        return last_non_off if last_non_off is not SnapMode.OFF else SnapMode.BEAT
    return SnapMode.OFF


def snap_to_grid(
    position_frames: int,
    *,
    mode: SnapMode,
    tempo_map: TempoMap,
    meter_map: MeterMap,
    bar_origin: BarOriginState,
    frames_per_pixel: float,
    radius_css_px: float = SNAP_RADIUS_CSS_PX,
    event_candidates: list[tuple[int, str]] | None = None,
) -> SnapResult:
    """Resolve the nearest eligible target inside the visual radius.

    ``event_candidates`` are (source frame, label) for markers, loops,
    selection edges, or pulses; they are only used in EVENT mode. No
    target inside the radius preserves the unsnapped position.
    """
    if position_frames < 0:
        raise SnapError("position must be nonnegative")
    if frames_per_pixel <= 0 or radius_css_px < 0:
        raise SnapError("viewport scale and radius must be valid")
    radius_frames = frames_per_pixel * radius_css_px
    if mode is SnapMode.OFF:
        return SnapResult(
            mode=mode,
            position_frames=position_frames,
            snapped_frame=position_frames,
            snapped=False,
            radius_frames=radius_frames,
        )

    candidates: list[tuple[int, SnapTargetKind, str | None]] = []
    if mode is SnapMode.EVENT:
        for frame, label in event_candidates or []:
            if abs(frame - position_frames) <= radius_frames:
                candidates.append((frame, SnapTargetKind.EVENT, label))
    else:
        try:
            tempo_map.map_source_to_musical(position_frames)
            grid = derive_grid(
                tempo_map,
                meter_map,
                bar_origin,
                detail=_DETAIL_FOR_MODE[mode],
            )
        except (ValueError, GridError) as exc:
            raise SnapError(str(exc)) from exc
        eligible = _KINDS_FOR_MODE[mode]
        for event in (
            event
            for event in grid.events
            if event.kind in eligible and abs(event.source_frame - position_frames) <= radius_frames
        ):
            candidates.append(
                (
                    event.source_frame,
                    SnapTargetKind(event.kind.value),
                    event.label,
                )
            )

    if not candidates:
        return SnapResult(
            mode=mode,
            position_frames=position_frames,
            snapped_frame=position_frames,
            snapped=False,
            radius_frames=radius_frames,
        )
    target_frame, kind, target_label = min(
        candidates,
        key=lambda item: (abs(item[0] - position_frames), item[0]),
    )
    return SnapResult(
        mode=mode,
        position_frames=position_frames,
        snapped_frame=target_frame,
        snapped=True,
        target_kind=kind,
        target_label=target_label,
        distance_frames=float(abs(target_frame - position_frames)),
        radius_frames=radius_frames,
    )
