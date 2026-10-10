"""Unit tests for MarkerRecord and WorkingState (M1.15, spec §17.1/§17.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.marker import MarkerRecord
from basseparate.domain.project import (
    ChannelDisplay,
    ProjectRecord,
    ProjectStatus,
    SelectionRange,
    ViewportState,
    WorkingState,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_marker(**overrides: object) -> MarkerRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "position_frames": 1_200,
        "label": "Marker",
        "color": "#e11d48",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return MarkerRecord(**base)


def test_marker_defaults_and_fields() -> None:
    m = _make_marker(label="  Intro  ", color="#112233")
    assert m.position_frames == 1_200
    assert m.label == "Intro"
    assert m.color == "#112233"
    assert m.created_at == NOW
    assert m.updated_at == NOW


def test_marker_label_must_be_nonempty_after_trim() -> None:
    with pytest.raises(ValidationError, match="label"):
        _make_marker(label="   ")


def test_marker_label_too_long() -> None:
    with pytest.raises(ValidationError, match="label"):
        _make_marker(label="x" * 81)


def test_marker_label_rejects_control_chars() -> None:
    with pytest.raises(ValidationError, match="control"):
        _make_marker(label="bad\x07label")


def test_marker_color_must_be_hex() -> None:
    for bad in ("red", "#12345", "#GGHHII", "112233"):
        with pytest.raises(ValidationError, match="color"):
            _make_marker(color=bad)


def test_marker_position_must_be_nonnegative() -> None:
    with pytest.raises(ValidationError):
        _make_marker(position_frames=-1)


def test_selection_range_requires_ordered_bounds() -> None:
    s = SelectionRange(start=100, end=200)
    assert s.start == 100
    assert s.end == 200
    with pytest.raises(ValidationError, match="end"):
        SelectionRange(start=200, end=100)


def test_viewport_state_requires_positive_scale() -> None:
    v = ViewportState(start_frame=0, frames_per_css_pixel=64.0)
    assert v.frames_per_css_pixel == 64.0
    with pytest.raises(ValidationError):
        ViewportState(start_frame=0, frames_per_css_pixel=0)


def test_channel_display_scale_bounds() -> None:
    d = ChannelDisplay(linked=False, scales=[1.0, 2.5])
    assert d.scales == [1.0, 2.5]
    with pytest.raises(ValidationError, match="scale"):
        ChannelDisplay(scales=[0.2])
    with pytest.raises(ValidationError, match="scale"):
        ChannelDisplay(scales=[16.5])
    with pytest.raises(ValidationError):
        ChannelDisplay(scales=[1.0] * 9)


def test_working_state_defaults() -> None:
    ws = WorkingState()
    assert ws.selection is None
    assert ws.viewport is None
    assert ws.channel_display.linked is True
    assert ws.channel_display.scales == []
    assert ws.monitoring_volume == 1.0
    assert ws.last_position_frames == 0
    assert ws.follow_playhead is True


def test_working_state_volume_bounds() -> None:
    with pytest.raises(ValidationError):
        WorkingState(monitoring_volume=-0.1)
    with pytest.raises(ValidationError):
        WorkingState(monitoring_volume=2.1)


def _ready_project(**overrides: object) -> ProjectRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "name": "Ready",
        "created_at": NOW,
        "updated_at": NOW,
        "status": ProjectStatus.READY,
        "source_asset_id": uuid4(),
        "canonical_asset_id": uuid4(),
        "source_stream_index": 0,
        "sample_rate": 48_000,
        "duration_frames": 10_000,
        "source_channel_count": 2,
        "source_channel_layout": "stereo",
        "decode_profile_version": 1,
    }
    base.update(overrides)
    return ProjectRecord(**base)


def test_project_carries_markers_and_working_state() -> None:
    project_id = uuid4()
    marker = _make_marker(project_id=project_id)
    p2 = _ready_project(
        id=project_id, markers=[marker], working_state=WorkingState(follow_playhead=False)
    )
    assert p2.markers == [marker]
    assert p2.working_state.follow_playhead is False


def test_empty_project_cannot_have_markers() -> None:
    p = ProjectRecord(id=uuid4(), name="Empty", created_at=NOW, updated_at=NOW)
    with pytest.raises(ValidationError, match="empty project"):
        ProjectRecord(
            id=p.id,
            name="Empty",
            created_at=NOW,
            updated_at=NOW,
            markers=[_make_marker(project_id=p.id)],
        )


def test_marker_position_inclusive_at_zero_and_end() -> None:
    project_id = uuid4()
    for position in (0, 10_000):
        marker = _make_marker(project_id=project_id, position_frames=position)
        p2 = _ready_project(id=project_id, markers=[marker])
        assert p2.markers[0].position_frames == position


def test_marker_position_beyond_duration_rejected() -> None:
    project_id = uuid4()
    marker = _make_marker(project_id=project_id, position_frames=10_001)
    with pytest.raises(ValidationError, match="duration"):
        _ready_project(id=project_id, markers=[marker])


def test_marker_from_other_project_rejected() -> None:
    project_id = uuid4()
    marker = _make_marker(project_id=uuid4())
    with pytest.raises(ValidationError, match="another project"):
        _ready_project(id=project_id, markers=[marker])


def test_working_state_position_beyond_duration_rejected() -> None:
    with pytest.raises(ValidationError, match="duration"):
        _ready_project(working_state=WorkingState(last_position_frames=10_001))


def test_working_state_selection_beyond_duration_rejected() -> None:
    ws = WorkingState(selection=SelectionRange(start=9_000, end=10_001))
    with pytest.raises(ValidationError, match="duration"):
        _ready_project(working_state=ws)


def test_working_state_viewport_beyond_duration_rejected() -> None:
    ws = WorkingState(viewport=ViewportState(start_frame=10_001, frames_per_css_pixel=8.0))
    with pytest.raises(ValidationError, match="duration"):
        _ready_project(working_state=ws)
