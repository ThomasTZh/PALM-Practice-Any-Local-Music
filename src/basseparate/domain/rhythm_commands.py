"""Rhythm editing commands (M3.10, milestone3.md §12).

Every semantic correction is one command with an explicit base project
revision and an idempotency key. The service validates the active branch,
applies exactly one operation, records before/after branch snapshots, and
increments both the branch and project revisions transactionally.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import (
    Revision,
    SamplePosition,
    Uuid,
)
from basseparate.domain.confidence import ReviewState
from basseparate.domain.rhythm import (
    AnchorLockState,
    MeterDenominator,
    MeterNumerator,
    MeterTempoUnit,
    MusicalPosition,
    PulseRole,
    RhythmBranchRecord,
)


class AddPulseOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["add_pulse"] = "add_pulse"
    source_frame: SamplePosition
    role: PulseRole = PulseRole.BEAT
    link_anchor: bool = True


class MovePulseOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["move_pulse"] = "move_pulse"
    pulse_id: Uuid
    source_frame: SamplePosition
    force_locked: bool = False


class DeletePulseOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["delete_pulse"] = "delete_pulse"
    pulse_id: Uuid
    force_locked: bool = False


class SetDownbeatOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_downbeat"] = "set_downbeat"
    pulse_id: Uuid
    is_downbeat: bool


class AddTempoAnchorOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["add_tempo_anchor"] = "add_tempo_anchor"
    source_frame: SamplePosition
    musical_position: MusicalPosition


class MoveTempoAnchorOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["move_tempo_anchor"] = "move_tempo_anchor"
    anchor_id: Uuid
    axis: Literal["source", "musical"]
    source_frame: SamplePosition | None = None
    musical_position: MusicalPosition | None = None
    force_locked: bool = False

    @model_validator(mode="after")
    def _check_axis(self) -> MoveTempoAnchorOp:
        if self.axis == "source" and self.source_frame is None:
            raise ValueError("source-axis movement requires source_frame")
        if self.axis == "musical" and self.musical_position is None:
            raise ValueError("musical-axis movement requires musical_position")
        return self


class DeleteTempoAnchorOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["delete_tempo_anchor"] = "delete_tempo_anchor"
    anchor_id: Uuid
    force_locked: bool = False


class SetAnchorLockOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_anchor_lock"] = "set_anchor_lock"
    anchor_id: Uuid
    lock_state: AnchorLockState


class AddMeterRegionOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["add_meter_region"] = "add_meter_region"
    start: MusicalPosition
    numerator: MeterNumerator
    denominator: MeterDenominator
    grouping: list[int] = Field(min_length=1, max_length=32)
    display_tempo_unit: MeterTempoUnit = MeterTempoUnit.QUARTER


class UpdateMeterRegionOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["update_meter_region"] = "update_meter_region"
    region_id: Uuid
    numerator: MeterNumerator | None = None
    denominator: MeterDenominator | None = None
    grouping: list[int] | None = Field(default=None, min_length=1, max_length=32)
    display_tempo_unit: MeterTempoUnit | None = None


class DeleteMeterRegionOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["delete_meter_region"] = "delete_meter_region"
    region_id: Uuid


class SetReviewStateOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_review_state"] = "set_review_state"
    target: Literal["pulse", "meter_region"]
    target_id: Uuid
    review_state: ReviewState


class SetBarOriginOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_bar_origin"] = "set_bar_origin"
    first_bar_number: int | None = Field(default=None, ge=1)
    first_downbeat_source: SamplePosition | None = None
    pickup_start_source: SamplePosition | None = None
    clear_pickup: bool = False


class ReinterpretTempoOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["reinterpret_tempo"] = "reinterpret_tempo"
    start_anchor_id: Uuid
    end_anchor_id: Uuid
    mode: Literal["half_time", "double_time"]


RhythmCommandOp = Annotated[
    AddPulseOp
    | MovePulseOp
    | DeletePulseOp
    | SetDownbeatOp
    | AddTempoAnchorOp
    | MoveTempoAnchorOp
    | DeleteTempoAnchorOp
    | SetAnchorLockOp
    | AddMeterRegionOp
    | UpdateMeterRegionOp
    | DeleteMeterRegionOp
    | SetReviewStateOp
    | SetBarOriginOp
    | ReinterpretTempoOp,
    Field(discriminator="type"),
]


class RhythmCommandRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: Uuid
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: Revision
    op: RhythmCommandOp


class RhythmCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision: Revision
    branch: RhythmBranchRecord
    can_undo: bool
    can_redo: bool
