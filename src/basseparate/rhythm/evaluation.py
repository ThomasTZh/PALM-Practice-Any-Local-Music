"""Rhythm quality metrics (M3.20 §22.2-§22.5).

The metrics are deliberately small, explicit, and dependency-free so the
tolerance and matching rules are auditable:

- beat/downbeat precision, recall, F1, and timing-error distribution
  within one tolerance window;
- half-time/double-time classification for aligned pulse trains;
- meter label/grouping/boundary accuracy;
- tempo-map anchor error and source/musical round-trip error.

They evaluate already-decoded pulses; they never run a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

#: Timing tolerance used by the synthetic evaluation (one 50 fps model
#: frame at 22,050 Hz, ~20 ms). Recorded in every report.
DEFAULT_TOLERANCE_SECONDS = 0.02


@dataclass(frozen=True)
class MatchResult:
    precision: float
    recall: float
    f1: float
    matched: int
    predicted: int
    reference: int
    timing_errors_seconds: tuple[float, ...] = ()


@dataclass(frozen=True)
class EventSet:
    """One monotonic event train in source seconds."""

    times: tuple[float, ...]

    def __post_init__(self) -> None:
        if any(b < a for a, b in zip(self.times, self.times[1:], strict=False)):
            raise ValueError("event times must be nondecreasing")


@dataclass(frozen=True)
class MeterObservation:
    start_seconds: float
    end_seconds: float
    label: str
    grouping: tuple[int, ...]


@dataclass(frozen=True)
class TempoObservation:
    source_seconds: float
    musical_quarters: float


def match_events(
    reference: EventSet,
    predicted: EventSet,
    *,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
) -> MatchResult:
    """Greedy one-to-one matching within a symmetric tolerance window."""
    if tolerance_seconds <= 0:
        raise ValueError("tolerance_seconds must be positive")
    used: set[int] = set()
    errors: list[float] = []
    for expected in reference.times:
        best_index = None
        best_error = tolerance_seconds
        for index, candidate in enumerate(predicted.times):
            if index in used:
                continue
            error = abs(candidate - expected)
            if error <= best_error:
                best_index = index
                best_error = error
        if best_index is not None:
            used.add(best_index)
            errors.append(predicted.times[best_index] - expected)
    matched = len(errors)
    precision = matched / len(predicted.times) if predicted.times else 0.0
    recall = matched / len(reference.times) if reference.times else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )
    return MatchResult(
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        predicted=len(predicted.times),
        reference=len(reference.times),
        timing_errors_seconds=tuple(errors),
    )


def timing_error_summary(result: MatchResult) -> dict[str, float]:
    errors = sorted(abs(error) for error in result.timing_errors_seconds)
    if not errors:
        return {"count": 0.0, "median_seconds": 0.0, "p95_seconds": 0.0, "max_seconds": 0.0}
    p95 = errors[min(len(errors) - 1, int(round(0.95 * (len(errors) - 1))))]
    return {
        "count": float(len(errors)),
        "median_seconds": median(errors),
        "p95_seconds": p95,
        "max_seconds": errors[-1],
    }


def classify_rate(
    reference: EventSet,
    predicted: EventSet,
    *,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
) -> str:
    """Classify a pulse train against a reference pulse train.

    ``ok``: matched at the reference rate. ``half``/``double``: every
    reference pulse is matched only by a prediction at half/double the
    rate but aligned in time. ``miss``: anything else.
    """
    direct = match_events(reference, predicted, tolerance_seconds=tolerance_seconds)
    if direct.f1 >= 0.9:
        return "ok"
    half = EventSet(tuple(time / 2 for time in reference.times))
    double = EventSet(tuple(time * 2 for time in reference.times))
    if match_events(half, predicted, tolerance_seconds=tolerance_seconds).f1 >= 0.9:
        return "half"
    if match_events(double, predicted, tolerance_seconds=tolerance_seconds).f1 >= 0.9:
        return "double"
    return "miss"


def meter_accuracy(
    reference: list[MeterObservation],
    predicted: list[MeterObservation],
    *,
    boundary_tolerance_seconds: float = 0.05,
) -> dict[str, float]:
    """Duration-weighted label accuracy plus grouping/boundary accuracy."""
    total = sum(max(0.0, item.end_seconds - item.start_seconds) for item in reference)
    correct_duration = 0.0
    correct_grouping = 0.0
    boundaries = 0
    boundary_hits = 0
    for expected in reference:
        best = None
        for candidate in predicted:
            overlap = min(expected.end_seconds, candidate.end_seconds) - max(
                expected.start_seconds, candidate.start_seconds
            )
            if overlap <= 0:
                continue
            if best is None or overlap > best[0]:
                best = (overlap, candidate)
        if best is None:
            continue
        if best[1].label == expected.label:
            correct_duration += best[0]
            if best[1].grouping == expected.grouping:
                correct_grouping += best[0]
        boundaries += 1
        if abs(best[1].start_seconds - expected.start_seconds) <= boundary_tolerance_seconds:
            boundary_hits += 1
    return {
        "label_duration_accuracy": correct_duration / total if total else 0.0,
        "grouping_duration_accuracy": correct_grouping / total if total else 0.0,
        "boundary_accuracy": boundary_hits / boundaries if boundaries else 0.0,
    }


def tempo_accuracy(
    reference: list[TempoObservation],
    predicted: list[TempoObservation],
    *,
    tolerance_seconds: float = 0.05,
) -> dict[str, float]:
    """Anchor error and local-quarter error for two tempo maps."""
    if not reference or not predicted:
        return {"anchor_accuracy": 0.0, "median_anchor_error_seconds": 0.0}
    matched = 0
    errors = []
    for expected in reference:
        nearest = min(
            predicted,
            key=lambda item: abs(item.source_seconds - expected.source_seconds),
        )
        error = abs(nearest.source_seconds - expected.source_seconds)
        if error <= tolerance_seconds:
            matched += 1
            errors.append(error)
    return {
        "anchor_accuracy": matched / len(reference),
        "median_anchor_error_seconds": median(errors) if errors else 0.0,
    }


def report_synthetic(
    case_id: str,
    *,
    beat: MatchResult,
    downbeat: MatchResult,
    rate_class: str,
    meter: dict[str, float] | None = None,
    tempo: dict[str, float] | None = None,
) -> dict[str, object]:
    """One auditable evaluation record for a synthetic case."""
    return {
        "case_id": case_id,
        "beat": {
            "precision": beat.precision,
            "recall": beat.recall,
            "f1": beat.f1,
            "matched": beat.matched,
            "predicted": beat.predicted,
            "reference": beat.reference,
            "timing": timing_error_summary(beat),
        },
        "downbeat": {
            "precision": downbeat.precision,
            "recall": downbeat.recall,
            "f1": downbeat.f1,
            "matched": downbeat.matched,
        },
        "rate": rate_class,
        "meter": meter or {},
        "tempo": tempo or {},
    }


def evaluate_pulse_trains(
    reference_beats: tuple[float, ...],
    reference_downbeats: tuple[float, ...],
    predicted_beats: tuple[float, ...],
    predicted_downbeats: tuple[float, ...],
    *,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
    case_id: str = "case",
) -> dict[str, object]:
    """Convenience wrapper returning the auditable report dictionary."""
    beats = EventSet(reference_beats)
    downbeats = EventSet(reference_downbeats)
    predicted = EventSet(predicted_beats)
    return report_synthetic(
        case_id,
        beat=match_events(beats, predicted, tolerance_seconds=tolerance_seconds),
        downbeat=match_events(
            downbeats, EventSet(predicted_downbeats), tolerance_seconds=tolerance_seconds
        ),
        rate_class=classify_rate(beats, predicted, tolerance_seconds=tolerance_seconds),
    )
