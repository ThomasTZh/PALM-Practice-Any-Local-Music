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
    SetMonitoringVolumeOp,
    SetPositionOp,
    SetSelectionOp,
    SetViewportOp,
    UpdateMarkerOp,
)
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.practice import PracticeState
from basseparate.domain.project import ChannelDisplay, ViewportState, WorkingState

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
        can_undo=True,
        can_redo=False,
    )
    assert result.revision == 4
    assert result.can_undo is True
    assert result.can_redo is False
