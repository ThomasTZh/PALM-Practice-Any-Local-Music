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
from basseparate.domain.practice import (
    MAX_DISPLAY_HEIGHT,
    MAX_GAIN,
    MAX_LOOP_NAME_LENGTH,
    MAX_LOOP_REPEAT,
    MAX_PLAYBACK_SPEED,
    MIN_DISPLAY_HEIGHT,
    MIN_PLAYBACK_SPEED,
    PlaybackMode,
    PracticeState,
)
from basseparate.domain.project import ChannelDisplay, ViewportState, WorkingState
from basseparate.domain.rhythm import LoopAnchorMode, MusicalPosition
from basseparate.domain.separation import StemRole

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


class SetTrackSettingsOp(BaseModel):
    """Patch one stem track's mixer settings (M2.8, spec §10.2).

    ``None`` fields stay unchanged; at least one field must be present.
    The track entry is created with defaults when absent.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_track_settings"] = "set_track_settings"
    stem_role: StemRole
    gain: float | None = Field(default=None, ge=0.0, le=MAX_GAIN)
    balance: float | None = Field(default=None, ge=-1.0, le=1.0)
    mute: bool | None = None
    solo: bool | None = None
    visible: bool | None = None
    display_height: float | None = Field(default=None, ge=MIN_DISPLAY_HEIGHT, le=MAX_DISPLAY_HEIGHT)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    def model_post_init(self, __context: object) -> None:
        patch = (
            self.gain,
            self.balance,
            self.mute,
            self.solo,
            self.visible,
            self.display_height,
            self.color,
        )
        if all(value is None for value in patch):
            raise ValueError("set_track_settings requires at least one field to change")


class SetPlaybackModeOp(BaseModel):
    """Select the playback mode (M2.8, spec §10.4.5–6).

    Stem modes require an active result set; the repository pre-validates
    and raises ``PlaybackModeRequiresResultSetError`` (409) when none is
    active.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_playback_mode"] = "set_playback_mode"
    mode: PlaybackMode


class SetMasterGainOp(BaseModel):
    """Set the master monitoring gain (M2.8, spec §10.3)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_master_gain"] = "set_master_gain"
    gain: float = Field(ge=0.0, le=MAX_GAIN)


class SetMonitoringLimiterOp(BaseModel):
    """Enable or disable the monitoring-path limiter (M2.8, spec §10.6)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_monitoring_limiter"] = "set_monitoring_limiter"
    enabled: bool


class SetPlaybackSpeedOp(BaseModel):
    """Set the pitch-preserving playback speed (M2.9, spec §11).

    Writes ``practice_state.playback_speed``. Undoable: like the other
    mixer ops it is part of the history (not in
    ``HISTORY_EXCLUDED_TYPES``). Speed is independent of the result set,
    so there is no pre-validation beyond the range (422 on violation).
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_playback_speed"] = "set_playback_speed"
    speed: float = Field(ge=MIN_PLAYBACK_SPEED, le=MAX_PLAYBACK_SPEED)


class AddLoopOp(BaseModel):
    """Create a saved practice loop (M2.11, spec §13.2.1).

    The name defaults to "Loop N" and the color to the default loop
    color server-side. The repository validates
    ``0 ≤ start < end ≤ duration_frames`` (422 ``LOOP_RANGE_INVALID``).
    ``repeat_count`` is the total number of passes; ``None`` = infinite.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["add_loop"] = "add_loop"
    start_frames: SamplePosition
    end_frames: SamplePosition
    name: str | None = Field(default=None, min_length=1, max_length=MAX_LOOP_NAME_LENGTH)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    repeat_count: int | None = Field(default=None, ge=1, le=MAX_LOOP_REPEAT)
    boundary_fade: bool = True

    def model_post_init(self, __context: object) -> None:
        if self.end_frames <= self.start_frames:
            raise ValueError("loop end_frames must be strictly greater than start_frames")


class UpdateLoopOp(BaseModel):
    """Partial loop edit; absent fields stay unchanged (M2.11, spec §13.2).

    ``repeat_count`` distinguishes absent (unchanged) from an explicit
    ``null`` (infinite) via ``model_fields_set``. The repository
    re-validates the resulting range against the duration.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["update_loop"] = "update_loop"
    loop_id: Uuid
    start_frames: SamplePosition | None = None
    end_frames: SamplePosition | None = None
    name: str | None = Field(default=None, min_length=1, max_length=MAX_LOOP_NAME_LENGTH)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    repeat_count: int | None = Field(default=None, ge=1, le=MAX_LOOP_REPEAT)
    boundary_fade: bool | None = None

    def model_post_init(self, __context: object) -> None:
        patch = (
            self.start_frames,
            self.end_frames,
            self.name,
            self.color,
            self.repeat_count,
            self.boundary_fade,
        )
        if all(value is None for value in patch) and "repeat_count" not in self.model_fields_set:
            raise ValueError("update_loop requires at least one field to change")


class AddMusicalLoopOp(BaseModel):
    """Create a loop anchored to exact musical positions (M3.13 §15.3)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["add_musical_loop"] = "add_musical_loop"
    start_musical: MusicalPosition
    end_musical: MusicalPosition
    name: str | None = Field(default=None, min_length=1, max_length=MAX_LOOP_NAME_LENGTH)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    repeat_count: int | None = Field(default=None, ge=1, le=MAX_LOOP_REPEAT)
    boundary_fade: bool = True

    def model_post_init(self, __context: object) -> None:
        if (
            self.end_musical.numerator * self.start_musical.denominator
            <= self.start_musical.numerator * self.end_musical.denominator
        ):
            raise ValueError("musical loop end must be after its start")


class ConvertLoopOp(BaseModel):
    """Convert a loop between source and musical authority (M3.13 §15.4-§15.5)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["convert_loop"] = "convert_loop"
    loop_id: Uuid
    target: LoopAnchorMode
    confirm_off_grid: bool = False


class DeleteLoopOp(BaseModel):
    """Delete a saved loop (M2.11, spec §13.2.8).

    When the deleted loop was active, the selection is cleared and
    looping disabled; other loops are untouched.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["delete_loop"] = "delete_loop"
    loop_id: Uuid


class DuplicateLoopOp(BaseModel):
    """Duplicate a saved loop as "<name> copy" (M2.11, spec §13.2.7)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["duplicate_loop"] = "duplicate_loop"
    loop_id: Uuid


class SetActiveLoopOp(BaseModel):
    """Select the active loop; ``null`` clears the selection (M2.11 §13.2.9).

    Clearing also disables looping (the ``loop_enabled requires an
    active loop`` invariant). Selecting a different loop keeps looping
    enabled.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_active_loop"] = "set_active_loop"
    loop_id: Uuid | None = None


class SetLoopEnabledOp(BaseModel):
    """Enable or disable repeated practice playback (M2.11 §13.2.10, §13.4).

    Enabling requires an active loop of at least
    :data:`MIN_REPEATABLE_LOOP_SECONDS` (spec §13.3.3): the repository
    pre-validates and raises ``NoActiveLoopError`` (409) or
    ``LoopTooShortError`` (409, message names the 100 ms minimum).
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["set_loop_enabled"] = "set_loop_enabled"
    enabled: bool


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
        | SetTrackSettingsOp
        | SetPlaybackModeOp
        | SetMasterGainOp
        | SetMonitoringLimiterOp
        | SetPlaybackSpeedOp
        | AddLoopOp
        | AddMusicalLoopOp
        | ConvertLoopOp
        | UpdateLoopOp
        | DeleteLoopOp
        | DuplicateLoopOp
        | SetActiveLoopOp
        | SetLoopEnabledOp
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
