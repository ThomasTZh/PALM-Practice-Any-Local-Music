"""Project command operations (M1.15, milestone1.md §17.3).

A command carries a validated operation payload, a base project
revision, and an idempotency key. The server validates the revision,
applies the edit transactionally, records history (except continuous
playback position, §17.4.10), increments the revision, and returns the
resulting state.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import Revision, SamplePosition, Uuid
from basseparate.domain.marker import MAX_MARKER_LABEL_LENGTH, MarkerRecord
from basseparate.domain.practice import PracticeState
from basseparate.domain.project import ChannelDisplay, ViewportState, WorkingState

DEFAULT_MARKER_LABEL = "Marker"
DEFAULT_MARKER_COLOR = "#e11d48"


class AddMarkerOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["add_marker"] = "add_marker"
    position_frames: SamplePosition
    label: str = Field(default=DEFAULT_MARKER_LABEL, max_length=MAX_MARKER_LABEL_LENGTH)
    color: str = Field(default=DEFAULT_MARKER_COLOR, pattern=r"^#[0-9a-f]{6}$")


class UpdateMarkerOp(BaseModel):
    """Partial marker edit; absent fields stay unchanged."""

    model_config = ConfigDict(frozen=True)

    type: Literal["update_marker"] = "update_marker"
    marker_id: Uuid
    position_frames: SamplePosition | None = None
    label: str | None = Field(default=None, min_length=1, max_length=MAX_MARKER_LABEL_LENGTH)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")


class DeleteMarkerOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["delete_marker"] = "delete_marker"
    marker_id: Uuid


class SetSelectionOp(BaseModel):
    """Both null clears the selection; present together otherwise."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_selection"] = "set_selection"
    start_frames: SamplePosition | None = None
    end_frames: SamplePosition | None = None

    def model_post_init(self, __context: object) -> None:
        if (self.start_frames is None) != (self.end_frames is None):
            raise ValueError("selection start and end must be present together")


class SetViewportOp(BaseModel):
    """Null clears the stored viewport (editor falls back to fit)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_viewport"] = "set_viewport"
    viewport: ViewportState | None = None


class SetDisplayOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_display"] = "set_display"
    channel_display: ChannelDisplay


class SetMonitoringVolumeOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_monitoring_volume"] = "set_monitoring_volume"
    volume: float = Field(ge=0.0, le=2.0)


class SetPositionOp(BaseModel):
    """Continuous playback position — persisted, never in history (§17.4.10)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_position"] = "set_position"
    position_frames: SamplePosition


class SetFollowPlayheadOp(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["set_follow_playhead"] = "set_follow_playhead"
    follow_playhead: bool


class SetActiveResultSetOp(BaseModel):
    """Select the project's active separation result set (M2.7, §9.4.3).

    ``null`` clears the selection. The target must be a result set of
    the same project (validated by the repository, not here — this op
    is data, not a query). Undoable: it is part of the history.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_active_result_set"] = "set_active_result_set"
    result_set_id: Uuid | None = None


ProjectCommandOp = Annotated[
    (
        AddMarkerOp
        | UpdateMarkerOp
        | DeleteMarkerOp
        | SetSelectionOp
        | SetViewportOp
        | SetDisplayOp
        | SetMonitoringVolumeOp
        | SetPositionOp
        | SetFollowPlayheadOp
        | SetActiveResultSetOp
    ),
    Field(discriminator="type"),
]

#: Op types that are persisted but excluded from the undo/redo history.
HISTORY_EXCLUDED_TYPES: frozenset[str] = frozenset({"set_position"})


class CommandRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: Uuid
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: Revision
    op: ProjectCommandOp


class CommandResult(BaseModel):
    """The resulting project state after a command (§17.4.5)."""

    model_config = ConfigDict(frozen=True)

    revision: Revision
    markers: list[MarkerRecord]
    working_state: WorkingState
    #: The resulting practice state (including the active result set
    #: selection, M2.7 §9.4.3).
    practice_state: PracticeState
    can_undo: bool
    can_redo: bool
