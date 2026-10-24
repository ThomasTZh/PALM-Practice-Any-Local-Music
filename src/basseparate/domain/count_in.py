"""Count-in plan domain (M3.15, milestone3.md §17).

A count-in is an output-only phase: source playback is held at the target
while virtual bars are clicked at the local tempo. It never modifies
source time, loop boundaries, or repeat counts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import SamplePosition
from basseparate.domain.metronome import ClickStrength
from basseparate.domain.rhythm import CountInMode, CountInRepetition, MusicalPosition


class CountInClick(BaseModel):
    model_config = ConfigDict(frozen=True)

    offset_frames: int = Field(ge=0)
    strength: ClickStrength
    phase: int = Field(ge=0)
    label: str


class CountInPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: CountInMode
    repetition: CountInRepetition
    available: bool
    reason: str | None = None
    target_source_frame: SamplePosition
    target_musical: MusicalPosition
    meter_label: str | None = None
    grouping: list[int] = Field(default_factory=list)
    local_quarter_bpm: float | None = Field(default=None, gt=0)
    playback_rate: float = Field(default=1.0, gt=0)
    bars: int = Field(default=0, ge=0)
    beats: int = Field(default=0, ge=0)
    total_frames: int = Field(default=0, ge=0)
    clicks: list[CountInClick] = Field(default_factory=list, max_length=64)
    off_grid: bool = False
    virtual_pre_roll: bool = True
