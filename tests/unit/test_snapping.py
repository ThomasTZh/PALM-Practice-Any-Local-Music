"""Musical snapping modes, radius semantics, and targets (M3.12)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterTempoUnit,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import BarOriginState, MusicalPosition
from basseparate.domain.snapping import SnapMode, SnapTargetKind
from basseparate.domain.tempo import PULSE_UNIT_QUARTER
from basseparate.rhythm.snapping import (
    SnapError,
    effective_snap_mode,
    snap_to_grid,
)
from basseparate.rhythm.tempo import build_manual_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/golden/rhythm-grid.json"


def _pos(data: dict) -> MusicalPosition:
    return MusicalPosition(**data)


def _setup():
    fixture = json.loads(FIXTURE.read_text())
    tempo = build_manual_tempo_map(
        [(anchor["sourceFrame"], _pos(anchor["musical"])) for anchor in fixture["tempoAnchors"]],
        project_id=uuid.uuid4(),
        project_sample_rate=fixture["projectSampleRate"],
        source_duration_frames=fixture["sourceDurationFrames"],
        hypothesis=PULSE_UNIT_QUARTER,
        created_at=NOW,
    )
    meter = build_meter_map(
        [
            ManualMeterRegion(
                start=_pos(region["start"]),
                candidate=manual_candidate(
                    region["numerator"],
                    region["denominator"],
                    region["grouping"],
                    MeterTempoUnit(region["displayTempoUnit"]),
                ),
            )
            for region in fixture["meterRegions"]
        ]
    )
    origin = BarOriginState(
        first_numbered_bar_position=_pos(fixture["barOrigin"]["firstNumberedBarPosition"]),
        first_bar_number=fixture["barOrigin"]["firstBarNumber"],
    )
    return tempo, meter, origin


def _snap(position: int, mode: SnapMode, fpp: float, **kwargs):
    tempo, meter, origin = _setup()
    return snap_to_grid(
        position,
        mode=mode,
        tempo_map=tempo,
        meter_map=meter,
        bar_origin=origin,
        frames_per_pixel=fpp,
        **kwargs,
    )


class TestSnapModes:
    def test_off_preserves_position(self) -> None:
        result = _snap(2400, SnapMode.OFF, 1.0)
        assert not result.snapped
        assert result.snapped_frame == 2400
        assert result.mode is SnapMode.OFF

    def test_beat_snaps_within_visual_radius(self) -> None:
        result = _snap(2400, SnapMode.BEAT, 100.0, radius_css_px=8)
        assert result.snapped
        assert result.snapped_frame == 2500
        assert result.target_kind is SnapTargetKind.PRIMARY
        assert result.radius_frames == pytest.approx(800)
        assert result.distance_frames == pytest.approx(100)

    def test_far_position_is_preserved(self) -> None:
        result = _snap(2400, SnapMode.BEAT, 10.0, radius_css_px=8)
        assert not result.snapped
        assert result.snapped_frame == 2400
        assert result.radius_frames == pytest.approx(80)

    def test_half_and_quarter_beat_subdivide_in_musical_space(self) -> None:
        half = _snap(1200, SnapMode.HALF_BEAT, 1000.0)
        assert half.snapped_frame == 1250
        assert half.target_kind is SnapTargetKind.HALF_BEAT
        quarter = _snap(700, SnapMode.QUARTER_BEAT, 1000.0)
        assert quarter.snapped_frame == 625
        assert quarter.target_kind is SnapTargetKind.QUARTER_BEAT

    def test_bar_snaps_only_to_bar_boundaries(self) -> None:
        result = _snap(12_000, SnapMode.BAR, 1000.0)
        assert result.snapped
        assert result.snapped_frame == 10_001
        assert result.target_kind is SnapTargetKind.BAR
        assert result.target_label == "2"

    def test_variable_tempo_beat_target(self) -> None:
        result = _snap(21_900, SnapMode.BEAT, 1000.0)
        assert result.snapped_frame == 22_003
        assert result.target_kind is SnapTargetKind.PRIMARY

    def test_event_candidates(self) -> None:
        result = _snap(
            4800,
            SnapMode.EVENT,
            100.0,
            event_candidates=[(100, "marker A"), (5000, "loop end")],
        )
        assert result.snapped_frame == 5000
        assert result.target_kind is SnapTargetKind.EVENT
        assert result.target_label == "loop end"

    def test_no_target_in_unmapped_position(self) -> None:
        with pytest.raises(SnapError):
            _snap(30_000, SnapMode.BEAT, 100.0)

    def test_mode_override(self) -> None:
        assert (
            effective_snap_mode(
                SnapMode.BEAT,
                modifier_pressed=True,
                last_non_off=SnapMode.BEAT,
            )
            is SnapMode.OFF
        )
        assert (
            effective_snap_mode(
                SnapMode.OFF,
                modifier_pressed=True,
                last_non_off=SnapMode.BAR,
            )
            is SnapMode.BAR
        )
        assert (
            effective_snap_mode(
                SnapMode.BAR,
                modifier_pressed=False,
                last_non_off=SnapMode.BEAT,
            )
            is SnapMode.BAR
        )

    def test_invalid_radius_or_position(self) -> None:
        with pytest.raises(SnapError):
            _snap(-1, SnapMode.BEAT, 1.0)
        with pytest.raises(SnapError):
            _snap(0, SnapMode.BEAT, 0.0)
