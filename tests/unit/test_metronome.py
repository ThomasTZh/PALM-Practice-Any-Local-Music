"""Metronome click schedules and deterministic render mapping (M3.14)."""

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
from basseparate.domain.metronome import ClickStrength
from basseparate.domain.rhythm import (
    BarOriginState,
    MetronomeSettings,
    MetronomeSubdivision,
    MusicalPosition,
)
from basseparate.domain.tempo import PULSE_UNIT_QUARTER
from basseparate.rhythm.metronome import (
    MetronomeError,
    build_metronome_schedule,
    map_clicks_to_render,
    repeat_loop_clicks,
)
from basseparate.rhythm.tempo import build_manual_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/golden/rhythm-grid.json"


def _pos(data: dict) -> MusicalPosition:
    return MusicalPosition(**data)


def _setup(meter: tuple[int, int, list[int], MeterTempoUnit] | None = None):
    fixture = json.loads(FIXTURE.read_text())
    tempo = build_manual_tempo_map(
        [(anchor["sourceFrame"], _pos(anchor["musical"])) for anchor in fixture["tempoAnchors"]],
        project_id=uuid.uuid4(),
        project_sample_rate=fixture["projectSampleRate"],
        source_duration_frames=fixture["sourceDurationFrames"],
        hypothesis=PULSE_UNIT_QUARTER,
        created_at=NOW,
    )
    if meter is None:
        regions = [
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
        meter_map = build_meter_map(regions)
    else:
        numerator, denominator, grouping, unit = meter
        meter_map = build_meter_map(
            [
                ManualMeterRegion(
                    start=_pos({"numerator": 0, "denominator": 1}),
                    candidate=manual_candidate(numerator, denominator, grouping, unit),
                )
            ]
        )
    origin = BarOriginState(
        first_numbered_bar_position=_pos(fixture["barOrigin"]["firstNumberedBarPosition"])
    )
    return tempo, meter_map, origin


def _settings(**overrides) -> MetronomeSettings:
    return MetronomeSettings(enabled=True, **overrides)


class TestSchedule:
    def test_primary_clicks_and_downbeats(self) -> None:
        tempo, meter, origin = _setup()
        schedule = build_metronome_schedule(tempo, meter, origin, _settings())
        clicks = schedule.clicks
        assert clicks[0].source_frame == 0
        assert clicks[0].strength is ClickStrength.DOWNBEAT
        assert clicks[0].bar_number == 1
        assert any(click.strength is ClickStrength.BEAT for click in clicks)
        assert clicks[-1].source_frame == 24_004
        assert len({click.source_frame for click in clicks}) == len(clicks)

    def test_disabled_schedule_is_empty(self) -> None:
        tempo, meter, origin = _setup()
        schedule = build_metronome_schedule(tempo, meter, origin, MetronomeSettings(enabled=False))
        assert schedule.clicks == []

    def test_subdivision_adds_weaker_clicks(self) -> None:
        tempo, meter, origin = _setup()
        primary = build_metronome_schedule(tempo, meter, origin, _settings())
        detailed = build_metronome_schedule(
            tempo,
            meter,
            origin,
            _settings(subdivision=MetronomeSubdivision.HALF_BEAT),
        )
        assert len(detailed.clicks) > len(primary.clicks)
        assert any(click.strength is ClickStrength.SUBDIVISION for click in detailed.clicks)

    def test_compound_meter_grouping(self) -> None:
        tempo, _meter, _origin = _setup((6, 8, [3, 3], MeterTempoUnit.DOTTED_QUARTER))
        meter = build_meter_map(
            [
                ManualMeterRegion(
                    start=MusicalPosition(numerator=0, denominator=1),
                    candidate=manual_candidate(6, 8, [3, 3], MeterTempoUnit.DOTTED_QUARTER),
                )
            ]
        )
        schedule = build_metronome_schedule(tempo, meter, _origin, _settings())
        strengths = [click.strength for click in schedule.clicks]
        assert ClickStrength.DOWNBEAT in strengths
        assert ClickStrength.GROUPING in strengths

    def test_loop_repeat_has_exact_per_pass_bases(self) -> None:
        tempo, meter, origin = _setup()
        schedule = build_metronome_schedule(
            tempo,
            meter,
            origin,
            _settings(),
            start=MusicalPosition(numerator=0, denominator=1),
            end=MusicalPosition(numerator=4, denominator=1),
        )
        clicks = repeat_loop_clicks(
            schedule,
            loop_start=0,
            loop_end=10_001,
            output_start_frame=0,
            passes=3,
        )
        first = [click for click in clicks if click.loop_iteration == 1]
        second = [click for click in clicks if click.loop_iteration == 2]
        assert len(first) == len(second)
        assert [click.render_frame for click in second] == [
            click.render_frame + 10_001 for click in first
        ]
        assert all(click.source_frame < 10_001 for click in clicks)

    def test_render_mapping_follows_rate(self) -> None:
        tempo, meter, origin = _setup()
        schedule = build_metronome_schedule(
            tempo,
            meter,
            origin,
            _settings(),
            start=MusicalPosition(numerator=0, denominator=1),
            end=MusicalPosition(numerator=2, denominator=1),
        )
        normal = map_clicks_to_render(schedule, source_start=0, output_start_frame=0, rate=1.0)
        slow = map_clicks_to_render(schedule, source_start=0, output_start_frame=0, rate=0.5)
        assert [click.render_frame for click in slow] == [
            click.render_frame * 2 for click in normal
        ]

    def test_invalid_rate(self) -> None:
        tempo, meter, origin = _setup()
        schedule = build_metronome_schedule(tempo, meter, origin, _settings())
        with pytest.raises(MetronomeError):
            map_clicks_to_render(schedule, source_start=0, output_start_frame=0, rate=0)
