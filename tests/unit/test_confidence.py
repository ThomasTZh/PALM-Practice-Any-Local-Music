"""Unit tests for Confidence schema (M0.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from basseparate.domain.confidence import (
    Confidence,
    ConfidenceAlternative,
    ConfidenceKind,
    ReviewState,
)


def test_probability_confidence() -> None:
    c = Confidence(value=0.92, kind=ConfidenceKind.PROBABILITY, method="cnn-v2")
    assert c.value == 0.92
    assert c.calibrated is False
    assert c.review_state == ReviewState.UNREVIEWED


def test_unavailable_must_have_null_value() -> None:
    c = Confidence(kind=ConfidenceKind.UNAVAILABLE)
    assert c.value is None


def test_unavailable_with_value_rejected() -> None:
    with pytest.raises(ValidationError, match="must be null"):
        Confidence(value=0.5, kind=ConfidenceKind.UNAVAILABLE)


def test_non_unavailable_requires_value() -> None:
    with pytest.raises(ValidationError, match="must be present"):
        Confidence(kind=ConfidenceKind.PROBABILITY)


def test_value_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        Confidence(value=1.5, kind=ConfidenceKind.PROBABILITY)
    with pytest.raises(ValidationError):
        Confidence(value=-0.1, kind=ConfidenceKind.HEURISTIC)


def test_boundary_values_accepted() -> None:
    assert Confidence(value=0.0, kind=ConfidenceKind.AGREEMENT).value == 0.0
    assert Confidence(value=1.0, kind=ConfidenceKind.PERIODICITY).value == 1.0


def test_alternatives() -> None:
    alts = [
        ConfidenceAlternative(label="C major", score=0.9),
        ConfidenceAlternative(label="A minor", score=0.1),
    ]
    c = Confidence(value=0.9, kind=ConfidenceKind.PROBABILITY, alternatives=alts)
    assert len(c.alternatives) == 2
    assert c.alternatives[0].label == "C major"


def test_review_state_does_not_change_value() -> None:
    c = Confidence(
        value=0.7,
        kind=ConfidenceKind.PROBABILITY,
        review_state=ReviewState.CORRECTED,
    )
    assert c.value == 0.7
    assert c.review_state == ReviewState.CORRECTED


def test_serialization_roundtrip() -> None:
    c = Confidence(value=0.85, kind=ConfidenceKind.HEURISTIC, method="onset-v1")
    data = c.model_dump(mode="json")
    assert data["kind"] == "heuristic"
    restored = Confidence.model_validate(data)
    assert restored == c
