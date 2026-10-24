"""Metronome click schedule domain (M3.14, milestone3.md §16).

The metronome is scheduled from musical grid events converted to source
frames, then to output render frames by the transport. Clicks are not a
source asset and are never exported.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import SamplePosition
from basseparate.domain.rhythm import MetronomeSubdivision, MusicalPosition

MAX_SCHEDULE_EVENTS = 20_000


class ClickStrength(StrEnum):
    DOWNBEAT = "downbeat"
    BEAT = "beat"
    GROUPING = "grouping"
    SUBDIVISION = "subdivision"


class ClickEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    musical_position: MusicalPosition
    source_frame: SamplePosition
    strength: ClickStrength
    subdivision: MetronomeSubdivision = MetronomeSubdivision.PRIMARY
    bar_number: int | None = None
    beat: int | None = None
    loop_iteration: int | None = Field(default=None, ge=1)


class RenderClick(BaseModel):
    """A click placed in output render frames for deterministic tests."""

    model_config = ConfigDict(frozen=True)

    render_frame: int = Field(ge=0)
    source_frame: SamplePosition
    strength: ClickStrength
    loop_iteration: int | None = None


class MetronomeSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: MusicalPosition
    end: MusicalPosition
    subdivision: MetronomeSubdivision
    clicks: list[ClickEvent] = Field(default_factory=list, max_length=MAX_SCHEDULE_EVENTS)
    unmapped_gap_detected: bool = False
