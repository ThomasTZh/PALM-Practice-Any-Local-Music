"""Unit tests for the project command op models (M1.15, spec §17.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.commands import (
    HISTORY_EXCLUDED_TYPES,
    AddMarkerOp,
    CommandRequest,
    CommandResult,
    DeleteMarkerOp,
    SetActiveResultSetOp,
    SetDisplayOp,
    SetFollowPlayheadOp,
    SetMasterGainOp,
    SetMonitoringLimiterOp,
    SetMonitoringVolumeOp,
    SetPlaybackModeOp,
    SetPlaybackSpeedOp,
    SetPositionOp,
    SetSelectionOp,
    SetTrackSettingsOp,
    SetViewportOp,
    UpdateMarkerOp,
)
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.practice import (
    MAX_GAIN,
    MAX_PLAYBACK_SPEED,
    MIN_PLAYBACK_SPEED,
    PlaybackMode,
    PracticeState,
)
from basseparate.domain.project import ChannelDisplay, ViewportState, WorkingState
from basseparate.domain.rhythm import ProjectRhythmState
from basseparate.domain.separation import StemRole

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def test_add_marker_op_defaults() -> None:
    op = AddMarkerOp(position_frames=1_200)
    assert op.type == "add_marker"
    assert op.label == "Marker"
    assert op.color == "#e11d48"


def test_add_marker_op_rejects_bad_color() -> None:
    with pytest.raises(ValidationError, match="color"):
        AddMarkerOp(position_frames=0, color="red")


def test_update_marker_op_is_partial() -> None:
    op = UpdateMarkerOp(marker_id=uuid4(), label="New name")
    assert op.position_frames is None
    assert op.color is None
    assert op.label == "New name"
    with pytest.raises(ValidationError):
        UpdateMarkerOp(marker_id=uuid4(), label="")


def test_delete_marker_op() -> None:
    op = DeleteMarkerOp(marker_id=uuid4())
    assert op.type == "delete_marker"


def test_set_selection_op_clears_with_nulls() -> None:
    assert SetSelectionOp().start_frames is None
    assert SetSelectionOp().end_frames is None


def test_set_viewport_op_accepts_null() -> None:
    assert SetViewportOp().viewport is None
    v = ViewportState(start_frame=10, frames_per_css_pixel=8.0)
    assert SetViewportOp(viewport=v).viewport == v


def test_set_display_op_requires_channel_display() -> None:
    op = SetDisplayOp(channel_display=ChannelDisplay(linked=False, scales=[2.0]))
    assert op.channel_display.scales == [2.0]


def test_set_monitoring_volume_bounds() -> None:
    assert SetMonitoringVolumeOp(volume=0.0).volume == 0.0
    assert SetMonitoringVolumeOp(volume=2.0).volume == 2.0
    with pytest.raises(ValidationError):
        SetMonitoringVolumeOp(volume=2.1)


def test_set_position_op() -> None:
    op = SetPositionOp(position_frames=48_000)
    assert op.type == "set_position"


def test_set_follow_playhead_op() -> None:
    assert SetFollowPlayheadOp(follow_playhead=False).follow_playhead is False


def test_set_active_result_set_op() -> None:
    # Null clears the selection (M2.7, spec §9.4.3).
    assert SetActiveResultSetOp().result_set_id is None
    target = uuid4()
    op = SetActiveResultSetOp(result_set_id=target)
    assert op.type == "set_active_result_set"
    assert op.result_set_id == target
    # The switch is undoable: it must stay out of the history exclusion.
    assert "set_active_result_set" not in HISTORY_EXCLUDED_TYPES


def test_command_request_parses_set_active_result_set_op() -> None:
    req = CommandRequest(**_request(SetActiveResultSetOp(result_set_id=uuid4())))
    assert isinstance(req.op, SetActiveResultSetOp)


def test_set_track_settings_op_patch_semantics() -> None:
    op = SetTrackSettingsOp(stem_role=StemRole.BASS, gain=0.5)
    assert op.type == "set_track_settings"
    assert op.stem_role == StemRole.BASS
    assert op.gain == 0.5
    assert op.balance is None
    assert op.mute is None
    assert op.solo is None
    assert op.visible is None
    assert op.display_height is None
    assert op.color is None


def test_set_track_settings_op_requires_a_field() -> None:
    with pytest.raises(ValidationError, match="at least one field"):
        SetTrackSettingsOp(stem_role=StemRole.BASS)


def test_set_track_settings_op_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError, match="stem_role"):
        SetTrackSettingsOp(stem_role="guitar", gain=0.5)


def test_set_track_settings_op_field_bounds() -> None:
    with pytest.raises(ValidationError):
        SetTrackSettingsOp(stem_role=StemRole.BASS, gain=MAX_GAIN + 0.1)
    with pytest.raises(ValidationError):
        SetTrackSettingsOp(stem_role=StemRole.BASS, balance=1.5)
    with pytest.raises(ValidationError):
        SetTrackSettingsOp(stem_role=StemRole.BASS, display_height=0.1)
    with pytest.raises(ValidationError, match="color"):
        SetTrackSettingsOp(stem_role=StemRole.BASS, color="red")
    # Every field is accepted when in range.
    op = SetTrackSettingsOp(
        stem_role=StemRole.BASS,
        gain=MAX_GAIN,
        balance=-1.0,
        mute=True,
        solo=True,
        visible=False,
        display_height=2.0,
        color="#ABCDEF",
    )
    assert op.color == "#ABCDEF"


def test_set_playback_mode_op() -> None:
    op = SetPlaybackModeOp(mode=PlaybackMode.BASS_PAIR)
    assert op.type == "set_playback_mode"
    assert op.mode == PlaybackMode.BASS_PAIR
    with pytest.raises(ValidationError):
        SetPlaybackModeOp(mode="loop")


def test_set_master_gain_op_bounds() -> None:
    assert SetMasterGainOp(gain=0.0).gain == 0.0
    assert SetMasterGainOp(gain=MAX_GAIN).gain == MAX_GAIN
    with pytest.raises(ValidationError):
        SetMasterGainOp(gain=MAX_GAIN + 0.1)
    with pytest.raises(ValidationError):
        SetMasterGainOp(gain=-0.1)


def test_set_monitoring_limiter_op() -> None:
    assert SetMonitoringLimiterOp(enabled=True).enabled is True
    assert SetMonitoringLimiterOp(enabled=False).enabled is False


def test_set_playback_speed_op_bounds() -> None:
    # M2.9: 0.25x to 2.0x, inclusive (spec §11.6).
    assert SetPlaybackSpeedOp(speed=MIN_PLAYBACK_SPEED).speed == 0.25
    assert SetPlaybackSpeedOp(speed=MAX_PLAYBACK_SPEED).speed == 2.0
    with pytest.raises(ValidationError):
        SetPlaybackSpeedOp(speed=MAX_PLAYBACK_SPEED + 0.01)
    with pytest.raises(ValidationError):
        SetPlaybackSpeedOp(speed=MIN_PLAYBACK_SPEED - 0.01)


def test_mixer_ops_are_undoable() -> None:
    # M2.8: every mixer op joins the history (none are excluded).
    # M2.9: the playback-speed op is undoable too.
    for op_type in (
        "set_track_settings",
        "set_playback_mode",
        "set_master_gain",
        "set_monitoring_limiter",
        "set_playback_speed",
    ):
        assert op_type not in HISTORY_EXCLUDED_TYPES


def test_command_request_parses_mixer_ops() -> None:
    for op in (
        SetTrackSettingsOp(stem_role=StemRole.BASS, mute=True),
        SetPlaybackModeOp(mode=PlaybackMode.FOUR_STEMS),
        SetMasterGainOp(gain=1.5),
        SetMonitoringLimiterOp(enabled=False),
        SetPlaybackSpeedOp(speed=1.5),
    ):
        req = CommandRequest(**_request(op))
        assert req.op is op


def test_position_is_excluded_from_history() -> None:
    assert frozenset({"set_position"}) == HISTORY_EXCLUDED_TYPES


def _request(op: object, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "command_id": uuid4(),
        "idempotency_key": "key-1",
        "base_revision": 3,
        "op": op,
    }
    base.update(overrides)
    return base


def test_command_request_parses_discriminated_op() -> None:
    req = CommandRequest(**_request(AddMarkerOp(position_frames=0)))
    assert isinstance(req.op, AddMarkerOp)
    assert req.base_revision == 3


def test_command_request_rejects_unknown_op_type() -> None:
    with pytest.raises(ValidationError, match="does not match any of the expected tags"):
        CommandRequest(**_request({"type": "explode_marker", "marker_id": str(uuid4())}))


def test_command_request_requires_idempotency_key() -> None:
    with pytest.raises(ValidationError, match="idempotency_key"):
        CommandRequest(**_request(AddMarkerOp(position_frames=0), idempotency_key=""))


def test_command_request_requires_nonnegative_revision() -> None:
    with pytest.raises(ValidationError):
        CommandRequest(**_request(AddMarkerOp(position_frames=0), base_revision=-1))


def test_command_result_shape() -> None:
    marker = MarkerRecord(
        id=uuid4(),
        project_id=uuid4(),
        position_frames=0,
        label="Marker",
        color="#e11d48",
        created_at=NOW,
        updated_at=NOW,
    )
    result = CommandResult(
        revision=4,
        markers=[marker],
        working_state=WorkingState(),
        practice_state=PracticeState(),
        rhythm_state=ProjectRhythmState(),
        can_undo=True,
        can_redo=False,
    )
    assert result.revision == 4
    assert result.can_undo is True
    assert result.can_redo is False
