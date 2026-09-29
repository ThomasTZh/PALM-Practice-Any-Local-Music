"""Confidence schema (M0.4).

Carries the main plan's confidence structure. Unknown confidence is
represented as ``kind="unavailable"`` with ``value=None``, never as
a fabricated zero.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConfidenceValue = Annotated[
    float,
    Field(ge=0.0, le=1.0, description="Normalized score in [0, 1]"),
]


class ConfidenceKind(StrEnum):
    PROBABILITY = "probability"
    PERIODICITY = "periodicity"
    HEURISTIC = "heuristic"
    AGREEMENT = "agreement"
    UNAVAILABLE = "unavailable"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"


class ConfidenceAlternative(BaseModel):
    """An alternative candidate with its own score."""

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    score: ConfidenceValue


class Confidence(BaseModel):
    """Structured confidence attached to every automatic result.

    - ``value`` is null when ``kind`` is ``unavailable``.
    - ``calibrated`` indicates whether the score has been calibrated.
    - ``alternatives`` carries runner-up candidates.
    - ``review_state`` tracks human review without overwriting
      the machine score.
    """

    model_config = ConfigDict(frozen=True)

    value: ConfidenceValue | None = None
    kind: ConfidenceKind
    method: str | None = Field(
        default=None,
        min_length=1,
        description="Method identifier and version, e.g. 'cnn-v2'",
    )
    calibrated: bool = False
    alternatives: list[ConfidenceAlternative] | None = None
    review_state: ReviewState = ReviewState.UNREVIEWED

    @model_validator(mode="after")
    def _check_unavailable(self) -> Confidence:
        if self.kind == ConfidenceKind.UNAVAILABLE and self.value is not None:
            raise ValueError("confidence value must be null when kind is 'unavailable'")
        if self.kind != ConfidenceKind.UNAVAILABLE and self.value is None:
            raise ValueError(
                f"confidence value must be present when kind is '{self.kind.value}', "
                "not null; use kind='unavailable' for unknown confidence"
            )
        return self
