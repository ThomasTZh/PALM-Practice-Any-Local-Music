"""Derived visible rhythm grid (M3.9, milestone3.md §11).

Grid lines are derived from the active tempo map, meter regions, and
bar-origin state for a requested musical range and detail level. They are
not persisted as independent rows. Source positions retain an exact
fraction internally and round once when an event or snap target needs an
integer frame.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import SamplePosition, UtcTimestamp
from basseparate.domain.rhythm import MusicalPosition
from basseparate.domain.rhythm_decode import SourceFrameFraction


class GridDetail(StrEnum):
    """Zoom/detail level for derived grid events (§11.9)."""

    BARS = "bars"
    PRIMARY = "primary"
    DENOMINATOR = "denominator"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"


class GridEventKind(StrEnum):
    BAR = "bar"
    PRIMARY = "primary"
    DENOMINATOR = "denominator"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"


class GridEvent(BaseModel):
    """One derived musical event with exact and rounded source positions."""

    model_config = ConfigDict(frozen=True)

    kind: GridEventKind
    musical_position: MusicalPosition
    source_fraction: SourceFrameFraction
    source_frame: SamplePosition
    bar_number: int | None = Field(default=None, ge=1)
    beat: int | None = Field(default=None, ge=1)
    subdivision: int | None = Field(default=None, ge=1)
    pickup: bool = False
    label: str = Field(min_length=1, max_length=32)


class GridGap(BaseModel):
    """An unmapped musical interval; no grid/snaps/metronome may appear."""

    model_config = ConfigDict(frozen=True)

    start: MusicalPosition
    end: MusicalPosition


class GridResult(BaseModel):
    """Derived grid for one visible range (§11.1, §11.8-§11.9)."""

    model_config = ConfigDict(frozen=True)

    detail: GridDetail
    start: MusicalPosition
    end: MusicalPosition
    events: list[GridEvent] = Field(max_length=100_000)
    gaps: list[GridGap] = Field(default_factory=list, max_length=64)
    unmapped_gap_detected: bool = False
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_order(self) -> GridResult:
        previous: MusicalPosition | None = None
        for event in self.events:
            if previous is not None and (
                event.musical_position.numerator * previous.denominator
                < previous.numerator * event.musical_position.denominator
            ):
                raise ValueError("grid events must be ordered by musical position")
            previous = event.musical_position
        return self


def grid_content_hash(result: GridResult) -> str:
    payload: dict[str, Any] = {
        "artifact": "derived-rhythm-grid",
        "version": 1,
        "detail": result.detail.value,
        "start": result.start.model_dump(mode="json"),
        "end": result.end.model_dump(mode="json"),
        "gaps": [gap.model_dump(mode="json") for gap in result.gaps],
        "events": [
            {
                "kind": event.kind.value,
                "musical": event.musical_position.model_dump(mode="json"),
                "source": event.source_frame,
                "label": event.label,
                "pickup": event.pickup,
            }
            for event in result.events
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
