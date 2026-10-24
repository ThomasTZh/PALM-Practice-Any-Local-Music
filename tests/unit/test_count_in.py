"""Count-in plans at local tempo/meter (M3.15)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterTempoUnit,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    CountInMode,
    CountInRepetition,
    CountInSettings,
    MusicalPosition,
)
from basseparate.rhythm.count_in import CountInError, build_count_in_plan
from basseparate.rhythm.tempo import build_manual_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000


def _map():
    return build_manual_tempo_map(
        [
            (0, MusicalPosition(numerator=0, denominator=1)),
            (96_000, MusicalPosition(numerator=4, denominator=1)),
        ],
        project_id=uuid.uuid4(),
        project_sample_rate=RATE,
        source_duration_frames=400_000,
        created_at=NOW,
    )


def _meter(numerator=4, denominator=4, grouping=None, unit=MeterTempoUnit.QUARTER):
    return build_meter_map(
        [
            ManualMeterRegion(
                start=ZERO_MUSICAL_POSITION,
                candidate=manual_candidate(
                    numerator, denominator, grouping or [1] * numerator, unit
                ),
            )
        ]
    )


def _plan(mode=CountInMode.ONE_BAR, target=0, rate=1.0, meter=None):
    return build_count_in_plan(
        _map(),
        meter or _meter(),
        CountInSettings(mode=mode, repetition=CountInRepetition.ONCE),
        target_source_frame=target,
        playback_rate=rate,
        source_sample_rate=RATE,
    )


class TestCountIn:
    def test_downbeat_one_bar(self) -> None:
        plan = _plan(target=0)
        assert plan.available
        assert plan.bars == 1 and plan.beats == 4
        assert plan.total_frames == 96_000
        assert [click.offset_frames for click in plan.clicks] == [0, 24_000, 48_000, 72_000]
        assert [click.strength for click in plan.clicks][0].value == "downbeat"
        assert not plan.off_grid

    def test_two_bars_and_speed(self) -> None:
        two = _plan(mode=CountInMode.TWO_BARS, target=0)
        assert two.total_frames == 192_000
        assert two.beats == 8
        slow = _plan(target=0, rate=0.5)
        assert slow.total_frames == 192_000
        assert slow.clicks[1].offset_frames == 48_000

    def test_mid_bar_phase(self) -> None:
        plan = _plan(target=24_000)  # musical quarter 1 = beat 2
        assert plan.available
        assert [click.phase for click in plan.clicks] == [2, 3, 4, 1]
        assert [click.offset_frames for click in plan.clicks] == [0, 24_000, 48_000, 72_000]

    def test_compound_meter(self) -> None:
        meter = _meter(6, 8, [3, 3], MeterTempoUnit.DOTTED_QUARTER)
        plan = _plan(target=0, meter=meter)
        assert plan.bars == 1 and plan.beats == 2
        assert plan.total_frames == 72_000
        assert [click.offset_frames for click in plan.clicks] == [0, 36_000]

    def test_off_grid_target_still_counts(self) -> None:
        plan = _plan(target=12_000)
        assert plan.available
        assert plan.off_grid is True
        assert plan.total_frames == 96_000

    def test_unavailable_without_meter(self) -> None:
        from basseparate.domain.meter import MeterMap

        plan = build_count_in_plan(
            _map(),
            MeterMap(
                regions=[
                    ManualMeterRegion(
                        start=MusicalPosition(numerator=4, denominator=1),
                        candidate=manual_candidate(4, 4, [1, 1, 1, 1]),
                    )
                ]
            ),
            CountInSettings(mode=CountInMode.ONE_BAR),
            target_source_frame=0,
            source_sample_rate=RATE,
        )
        assert plan.available is False
        assert plan.reason

    def test_off_mode(self) -> None:
        plan = _plan(mode=CountInMode.OFF)
        assert plan.available is False
        assert plan.total_frames == 0

    def test_invalid_inputs(self) -> None:
        with pytest.raises(CountInError):
            _plan(target=0, rate=0)
        with pytest.raises(CountInError):
            _plan(target=999_999)
