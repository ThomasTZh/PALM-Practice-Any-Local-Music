"""Derived grid labels, pickups, gaps, and shared golden vectors (M3.9)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest

from basseparate.domain.grid import GridDetail, GridEventKind
from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterMap,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import (
    BarOriginState,
    MeterTempoUnit,
    MusicalInterval,
    MusicalPosition,
)
from basseparate.domain.tempo import PULSE_UNIT_QUARTER
from basseparate.rhythm.grid import (
    GridError,
    bar_beat_label,
    derive_grid,
    first_downbeat_origin,
    pickup_interval,
    set_first_numbered_bar,
)
from basseparate.rhythm.tempo import build_manual_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000
PROJECT_ID = uuid.uuid4()
FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/golden/rhythm-grid.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _pos(data: dict) -> MusicalPosition:
    return MusicalPosition(**data)


def _map_from_fixture(fixture: dict):
    points = [
        (anchor["sourceFrame"], _pos(anchor["musical"])) for anchor in fixture["tempoAnchors"]
    ]
    return build_manual_tempo_map(
        points,
        project_id=PROJECT_ID,
        project_sample_rate=fixture["projectSampleRate"],
        source_duration_frames=fixture["sourceDurationFrames"],
        hypothesis=PULSE_UNIT_QUARTER,
        created_at=NOW,
    )


def _meter_from_fixture(fixture: dict) -> MeterMap:
    regions = []
    for data in fixture["meterRegions"]:
        regions.append(
            ManualMeterRegion(
                start=_pos(data["start"]),
                candidate=manual_candidate(
                    data["numerator"],
                    data["denominator"],
                    data["grouping"],
                    MeterTempoUnit(data["displayTempoUnit"]),
                ),
            )
        )
    return build_meter_map(regions)


def _origin_from_fixture(fixture: dict) -> BarOriginState:
    origin = fixture["barOrigin"]
    return BarOriginState(
        first_numbered_bar_position=_pos(origin["firstNumberedBarPosition"]),
        first_bar_number=origin["firstBarNumber"],
    )


class TestGoldenVectors:
    def test_mapping_and_inverse(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        for query in fixture["mappingQueries"]:
            musical = _pos(query["musical"])
            expected = query["sourceFraction"]
            fraction = tempo.source_fraction_for_musical(musical)
            assert fraction == Fraction(expected["numerator"], expected["denominator"])
            assert tempo.map_musical_to_source(musical) == query["sourceFrame"]
        for query in fixture["inverseQueries"]:
            assert tempo.map_source_to_musical(query["sourceFrame"]) == _pos(query["musical"])

    def test_labels(self) -> None:
        fixture = _fixture()
        meter = _meter_from_fixture(fixture)
        origin = _origin_from_fixture(fixture)
        for query in fixture["labelQueries"]:
            bar, beat, pickup, label = bar_beat_label(meter, origin, _pos(query["musical"]))
            assert bar == query["barNumber"]
            assert beat == query["beat"]
            assert pickup is query["pickup"]
            assert label == query["label"]


class TestDerivedGrid:
    def test_primary_events_and_labels(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = _origin_from_fixture(fixture)
        result = derive_grid(tempo, meter, origin, detail=GridDetail.PRIMARY, created_at=NOW)
        bars = [event for event in result.events if event.kind is GridEventKind.BAR]
        primary = [event for event in result.events if event.kind is GridEventKind.PRIMARY]
        assert [event.label for event in bars] == ["1", "2", "3"]
        assert [event.label for event in primary] == [
            "1.1",
            "1.2",
            "1.3",
            "1.4",
            "2.1",
            "2.2",
            "2.3",
            "2.4",
            "3.1",
            "3.2",
            "3.3",
        ]
        assert [event.source_frame for event in bars] == [0, 10001, 20003]
        assert result.gaps == []
        assert not result.unmapped_gap_detected

    def test_detail_levels(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = _origin_from_fixture(fixture)
        bars = derive_grid(tempo, meter, origin, detail=GridDetail.BARS)
        assert len(bars.events) == 3
        denom = derive_grid(tempo, meter, origin, detail=GridDetail.DENOMINATOR)
        assert len(denom.events) > len(bars.events)
        half = derive_grid(tempo, meter, origin, detail=GridDetail.HALF_BEAT)
        quarter = derive_grid(tempo, meter, origin, detail=GridDetail.QUARTER_BEAT)
        assert len(quarter.events) > len(half.events) > len(bars.events)
        kinds = {event.kind for event in quarter.events}
        assert GridEventKind.HALF_BEAT in kinds
        assert GridEventKind.QUARTER_BEAT in kinds

    def test_pickup_labels(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = BarOriginState(
            first_numbered_bar_position=MusicalPosition(numerator=4, denominator=1)
        )
        result = derive_grid(tempo, meter, origin, detail=GridDetail.PRIMARY)
        bars = [event.label for event in result.events if event.kind is GridEventKind.BAR]
        assert bars == ["pickup", "1", "2"]
        assert all(event.pickup for event in result.events if event.label.startswith("pickup"))

    def test_unmapped_gaps_and_no_events_there(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = _origin_from_fixture(fixture)
        start = MusicalPosition(numerator=-2, denominator=1)
        end = MusicalPosition(numerator=12, denominator=1)
        result = derive_grid(tempo, meter, origin, start=start, end=end)
        assert result.unmapped_gap_detected
        assert len(result.gaps) == 2
        assert all(-2 <= event.musical_position.as_quarter_notes() <= 11 for event in result.events)

    def test_origin_must_be_bar_boundary(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = BarOriginState(
            first_numbered_bar_position=MusicalPosition(numerator=2, denominator=1)
        )
        with pytest.raises(GridError):
            derive_grid(tempo, meter, origin)

    def test_source_fraction_rounding(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        meter = _meter_from_fixture(fixture)
        origin = _origin_from_fixture(fixture)
        result = derive_grid(tempo, meter, origin, detail=GridDetail.PRIMARY)
        by_label = {event.label: event for event in result.events}
        assert by_label["1.2"].source_frame == 2500
        assert by_label["1.3"].source_frame == 5001
        assert by_label["3.1"].source_frame == 20003


class TestBarOrigin:
    def test_first_downbeat_and_pickup(self) -> None:
        fixture = _fixture()
        tempo = _map_from_fixture(fixture)
        origin = first_downbeat_origin(tempo, source_frame=10001, first_bar_number=1)
        assert origin.first_numbered_bar_position == MusicalPosition(numerator=4, denominator=1)
        pickup = pickup_interval(tempo, source_start=0, first_downbeat_source=10001)
        assert isinstance(pickup, MusicalInterval)
        assert pickup.start == MusicalPosition(numerator=0, denominator=1)
        assert pickup.end == MusicalPosition(numerator=4, denominator=1)
        renumbered = set_first_numbered_bar(origin, 5)
        assert renumbered.first_bar_number == 5
        with pytest.raises(GridError):
            set_first_numbered_bar(origin, 0)
