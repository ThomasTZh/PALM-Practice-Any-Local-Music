"""Deterministic rhythm corpus verification (M3.19 §21.1-§21.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basseparate.domain.grid import GridEventKind
from basseparate.rhythm.grid import bar_beat_label, derive_grid
from tests.unit.rhythm_corpus import (
    SAMPLE_RATE,
    corpus_cases,
    golden_mapping,
)

CASES = corpus_cases()


@pytest.mark.parametrize("case", [c for c in CASES if c.bars > 0], ids=lambda c: c.id)
def test_case_derives_a_deterministic_bar_grid(case) -> None:
    from tests.unit.rhythm_corpus import build_case

    tempo_map, meter_map, pulses, origin = build_case(case)
    assert pulses
    assert len(tempo_map.anchors) == len(pulses)
    assert len(meter_map.regions) >= 1

    grid = derive_grid(tempo_map, meter_map, origin)
    bars = [event for event in grid.events if event.kind is GridEventKind.BAR]
    assert bars, "every non-silent case must produce bar events"
    numbered = [bar for bar in bars if bar.bar_number is not None]
    assert numbered and numbered[0].bar_number == 1
    assert all(event.label for event in grid.events)

    again = derive_grid(tempo_map, meter_map, origin)
    assert [event.model_dump() for event in grid.events] == [
        event.model_dump() for event in again.events
    ]


def test_pure_silence_has_no_grid_input() -> None:
    case = next(c for c in CASES if c.id == "pure-silence")
    assert case.bars == 0


def test_pickup_and_mid_bar_origins_are_labelled() -> None:
    from tests.unit.rhythm_corpus import build_case

    pickup = next(c for c in CASES if c.id == "pickup")
    tempo_map, meter_map, _pulses, origin = build_case(pickup)
    label = bar_beat_label(meter_map, origin, tempo_map.map_source_to_musical(0))
    assert label[3] == "pickup"

    mid = next(c for c in CASES if c.id == "mid-bar-start")
    mid_tempo, mid_meter, _pulses, mid_origin = build_case(mid)
    assert mid_origin.first_numbered_bar_position.numerator > 0
    first = bar_beat_label(mid_meter, mid_origin, mid_origin.first_numbered_bar_position)
    assert first[1] == 1


def test_meter_changes_keep_two_regions() -> None:
    from tests.unit.rhythm_corpus import build_case

    for case_id in ("meter-4-4-to-3-4", "meter-4-4-to-6-8"):
        case = next(c for c in CASES if c.id == case_id)
        _tempo, meter_map, _pulses, _origin = build_case(case)
        assert len(meter_map.regions) == 2
        assert meter_map.regions[0].start.numerator == 0
        assert meter_map.regions[1].start.numerator > 0


def test_tempo_segments_change_the_map() -> None:
    from tests.unit.rhythm_corpus import build_case

    case = next(c for c in CASES if c.id == "tempo-jump")
    tempo_map, _meter, _pulses, _origin = build_case(case)
    intervals = {
        tempo_map.anchors[index + 1].source_frame - tempo_map.anchors[index].source_frame
        for index in range(len(tempo_map.anchors) - 1)
    }
    assert len(intervals) >= 2


def test_corpus_fixture_matches_the_code() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "rhythm-corpus.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in data["cases"]]
    assert ids == [case.id for case in CASES]
    assert len(ids) >= 21


def test_golden_mapping_round_trips_within_one_frame() -> None:
    golden = golden_mapping()
    assert golden["sample_rate"] == SAMPLE_RATE
    for sample in golden["samples"]:
        assert abs(int(sample["back_to_source"]) - int(sample["source_frame"])) <= 1
    first = golden["anchors"][0]
    assert first["musical_position"] == {"numerator": 0, "denominator": 1}


def test_sixty_minute_variable_tempo_fixture_is_generated_in_memory() -> None:
    """§21.1.21: a long variable-tempo fixture, generated not committed."""
    from tests.unit.rhythm_corpus import TempoSegment, _case, build_case

    case = _case(
        "long-variable",
        "60-minute variable tempo",
        120,
        4,
        4,
        (1, 1, 1, 1),
        bars=1800,
        tempo_segments=(
            TempoSegment(100, 400),
            TempoSegment(120, 600),
            TempoSegment(140, 800),
        ),
    )
    tempo_map, meter_map, pulses, origin = build_case(case)
    assert len(pulses) == 1800 * 4
    assert len(tempo_map.anchors) == len(pulses)
    # Full-range derivation on 7,200 anchors is unnecessary; a bounded
    # window proves the long map is usable without dominating the suite.
    end = tempo_map.map_source_to_musical(tempo_map.anchors[400].source_frame)
    grid = derive_grid(tempo_map, meter_map, origin, end=end)
    bars = [event for event in grid.events if event.kind is GridEventKind.BAR]
    assert len(bars) >= 100
