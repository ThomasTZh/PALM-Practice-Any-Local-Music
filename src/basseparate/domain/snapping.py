"""Musical snapping modes and results (M3.12, milestone3.md §14).

Snapping is a pure, edit-time decision: an approximately eight CSS-pixel
radius converted through the current viewport scale, candidates near the
pointer only, and no change when no eligible target is inside the radius.
Changing the mode never moves existing objects.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import SamplePosition

SNAP_RADIUS_CSS_PX = 8.0


class SnapMode(StrEnum):
    OFF = "off"
    BEAT = "beat"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"
    BAR = "bar"
    EVENT = "event"


class SnapTargetKind(StrEnum):
    NONE = "none"
    BAR = "bar"
    PRIMARY = "primary"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"
    EVENT = "event"


class SnapResult(BaseModel):
    """One edit-time snap decision; ``position_frames`` is always echoed."""

    model_config = ConfigDict(frozen=True)

    mode: SnapMode
    position_frames: SamplePosition
    snapped_frame: SamplePosition
    snapped: bool
    target_kind: SnapTargetKind = SnapTargetKind.NONE
    target_label: str | None = None
    distance_frames: float = Field(default=0.0, ge=0.0)
    radius_frames: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _check(self) -> SnapResult:
        if not self.snapped and self.snapped_frame != self.position_frames:
            raise ValueError("an unsnapped result must preserve the input position")
        if self.snapped and self.target_kind is SnapTargetKind.NONE:
            raise ValueError("a snapped result needs a target kind")
        return self
