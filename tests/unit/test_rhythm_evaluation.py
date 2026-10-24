"""Rhythm evaluation metrics (M3.20 §22.2-§22.5)."""

from __future__ import annotations

import pytest

from basseparate.rhythm.evaluation import (
    EventSet,
    MeterObservation,
    TempoObservation,
    classify_rate,
    evaluate_pulse_trains,
    match_events,
    meter_accuracy,
    tempo_accuracy,
)


def test_exact_match_scores_one() -> None:
    events = EventSet((0.0, 0.5, 1.0, 1.5))
    result = match_events(events, events)
    assert result.f1 == 1.0
    assert result.precision == 1.0 and result.recall == 1.0


def test_missing_extra_and_shifted_pulses() -> None:
    reference = EventSet((0.0, 0.5, 1.0, 1.5))
    predicted = EventSet((0.0, 0.505, 1.5, 2.0))
    result = match_events(reference, predicted, tolerance_seconds=0.02)
    assert result.predicted == 4 and result.reference == 4
    assert result.matched == 3
    assert result.precision == pytest.approx(0.75)
    assert result.recall == pytest.approx(0.75)


def test_tolerance_is_enforced() -> None:
    result = match_events(
        EventSet((1.0,)), EventSet((1.03,)), tolerance_seconds=0.02
    )
    assert result.matched == 0
    assert result.f1 == 0.0


def test_rate_classification_separates_half_and_double() -> None:
    reference = EventSet(tuple(index * 0.5 for index in range(16)))
    half = EventSet(tuple(time / 2 for time in reference.times))
    double = EventSet(tuple(time * 2 for time in reference.times))
    assert classify_rate(reference, reference) == "ok"
    assert classify_rate(reference, half) == "half"
    assert classify_rate(reference, double) == "double"
    assert classify_rate(reference, EventSet((0.13, 7.7))) == "miss"


def test_meter_accuracy_weights_by_duration() -> None:
    reference = [
        MeterObservation(0.0, 8.0, "4/4", (1, 1, 1, 1)),
        MeterObservation(8.0, 14.0, "3/4", (1, 1, 1)),
    ]
    predicted = [
        MeterObservation(0.0, 8.0, "4/4", (1, 1, 1, 1)),
        MeterObservation(8.0, 14.0, "6/8", (3, 3)),
    ]
    result = meter_accuracy(reference, predicted)
    assert result["label_duration_accuracy"] == pytest.approx(8 / 14)
    assert result["grouping_duration_accuracy"] == pytest.approx(8 / 14)
    assert result["boundary_accuracy"] == 1.0


def test_tempo_anchor_accuracy() -> None:
    reference = [TempoObservation(0.0, 0.0), TempoObservation(2.0, 1.0)]
    predicted = [TempoObservation(0.01, 0.0), TempoObservation(2.01, 1.0)]
    result = tempo_accuracy(reference, predicted)
    assert result["anchor_accuracy"] == 1.0
    assert result["median_anchor_error_seconds"] == pytest.approx(0.01)


def test_pulse_train_report_is_auditable() -> None:
    report = evaluate_pulse_trains(
        (0.0, 0.5, 1.0, 1.5),
        (0.0, 1.5),
        (0.0, 0.5, 1.0, 1.5),
        (0.0, 1.5),
        case_id="4-4-exact",
    )
    assert report["case_id"] == "4-4-exact"
    assert report["rate"] == "ok"
    assert report["beat"]["f1"] == 1.0
    assert report["downbeat"]["f1"] == 1.0
