"""Unit tests for ProjectRecord schema (M0.4, extended M1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate import PROJECT_SCHEMA_VERSION
from basseparate.domain.project import ProjectRecord, ProjectStatus, WaveformStatus

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_project(**overrides: object) -> ProjectRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "name": "Test Project",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return ProjectRecord(**base)


def _ready_overrides() -> dict[str, object]:
    return {
        "status": ProjectStatus.READY,
        "source_asset_id": uuid4(),
        "canonical_asset_id": uuid4(),
        "source_stream_index": 0,
        "sample_rate": 48_000,
        "duration_frames": 1_000_000,
        "source_channel_count": 2,
        "source_channel_layout": "stereo",
        "decode_profile_version": 1,
    }


def test_empty_project_defaults() -> None:
    p = _make_project()
    assert p.status == ProjectStatus.EMPTY
    assert p.revision == 0
    assert p.source_asset_id is None
    assert p.canonical_asset_id is None
    assert p.monitoring_asset_id is None
    assert p.source_stream_index is None
    assert p.sample_rate is None
    assert p.duration_frames is None
    assert p.source_channel_count is None
    assert p.source_channel_layout is None
    assert p.decode_profile_version is None
    assert p.waveform_status == WaveformStatus.NONE
    assert p.source_metadata == {}
    assert p.schema_version == PROJECT_SCHEMA_VERSION


def test_ready_project_requires_all_source_fields() -> None:
    with pytest.raises(ValidationError, match="source"):
        _make_project(status=ProjectStatus.READY)


def test_ready_project_with_source() -> None:
    p = _make_project(**_ready_overrides())
    assert p.status == ProjectStatus.READY
    assert p.sample_rate == 48_000
    assert p.duration_frames == 1_000_000
    assert p.source_channel_count == 2


def test_ready_project_without_canonical_rejected() -> None:
    overrides = _ready_overrides()
    del overrides["canonical_asset_id"]
    with pytest.raises(ValidationError, match="together"):
        _make_project(**overrides)


def test_name_is_trimmed() -> None:
    p = _make_project(name="  padded name  ")
    assert p.name == "padded name"


def test_name_too_short_rejected() -> None:
    with pytest.raises(ValidationError, match="1-200"):
        _make_project(name="   ")


def test_name_too_long_rejected() -> None:
    with pytest.raises(ValidationError, match="1-200"):
        _make_project(name="x" * 201)


def test_name_with_control_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="control"):
        _make_project(name="bad\x00name")


def test_unicode_name_preserved() -> None:
    p = _make_project(name="Bass Séparateur – テスト")
    assert p.name == "Bass Séparateur – テスト"


def test_source_fields_must_come_together() -> None:
    with pytest.raises(ValidationError, match="together"):
        _make_project(status=ProjectStatus.READY, source_asset_id=uuid4(), sample_rate=44100)
    with pytest.raises(ValidationError, match="together"):
        _make_project(status=ProjectStatus.READY, source_asset_id=uuid4(), duration_frames=100)
    with pytest.raises(ValidationError, match="together"):
        _make_project(
            status=ProjectStatus.READY,
            source_asset_id=uuid4(),
            canonical_asset_id=uuid4(),
            source_stream_index=0,
            sample_rate=44100,
            duration_frames=100,
            source_channel_count=2,
            # missing source_channel_layout and decode_profile_version
        )


def test_empty_project_must_not_have_source_asset() -> None:
    # Setting only source_asset_id violates the togetherness rule first.
    with pytest.raises(ValidationError, match="together"):
        _make_project(source_asset_id=uuid4())
    # A full source set on an empty-status project is rejected.
    overrides = _ready_overrides()
    overrides["status"] = ProjectStatus.EMPTY
    with pytest.raises(ValidationError, match="empty project"):
        _make_project(**overrides)


def test_monitoring_asset_requires_canonical() -> None:
    with pytest.raises(ValidationError, match="monitoring"):
        _make_project(monitoring_asset_id=uuid4())


def test_waveform_status_requires_canonical() -> None:
    with pytest.raises(ValidationError, match="waveform"):
        _make_project(waveform_status=WaveformStatus.READY)


def test_waveform_pending_with_ready_audio() -> None:
    p = _make_project(**_ready_overrides(), waveform_status=WaveformStatus.PENDING)
    assert p.waveform_status == WaveformStatus.PENDING
    assert p.status == ProjectStatus.READY


def test_channel_count_bounds() -> None:
    overrides = _ready_overrides()
    overrides["source_channel_count"] = 9
    with pytest.raises(ValidationError, match="source_channel_count"):
        _make_project(**overrides)


def test_sample_rate_bounds() -> None:
    overrides = _ready_overrides()
    overrides["sample_rate"] = 4_000
    with pytest.raises(ValidationError, match="sample rate"):
        _make_project(**overrides)
    overrides["sample_rate"] = 192_001
    with pytest.raises(ValidationError, match="sample rate"):
        _make_project(**overrides)


def test_source_metadata_summary() -> None:
    p = _make_project(
        **_ready_overrides(),
        source_metadata={"title": "Track A", "artist": "Someone", "format": "wav"},
    )
    assert p.source_metadata["title"] == "Track A"


def test_serialization_roundtrip() -> None:
    p = _make_project(**_ready_overrides(), waveform_status=WaveformStatus.READY)
    data = p.model_dump(mode="json")
    assert isinstance(data["id"], str)
    assert isinstance(data["source_asset_id"], str)
    restored = ProjectRecord.model_validate(data)
    assert restored == p


def test_forward_compat_rejects_newer_schema() -> None:
    p = _make_project(schema_version=99)
    assert p.schema_version == 99


class TestPracticeState:
    def test_default_practice_state(self) -> None:
        from basseparate.domain import PlaybackMode, PracticeState

        p = _make_project()
        assert p.practice_state == PracticeState()
        assert p.practice_state.playback_mode == PlaybackMode.ORIGINAL

    def test_practice_state_roundtrip(self) -> None:
        from basseparate.domain import PlaybackMode, PracticeState, TrackSettings

        state = PracticeState(
            playback_mode=PlaybackMode.FOUR_STEMS,
            active_result_set_id=uuid4(),
            tracks={"bass": TrackSettings(gain=0.5, mute=True)},
            playback_speed=0.75,
            master_gain=1.5,
        )
        p = _make_project(**_ready_overrides(), practice_state=state)
        restored = ProjectRecord.model_validate(p.model_dump(mode="json"))
        assert restored.practice_state == state

    def test_v3_project_json_without_practice_state_loads(self) -> None:
        # A project serialized before M2.1 (schema v3, no practice_state key)
        # must deserialize with a defaulted practice state.
        from basseparate.domain import PracticeState

        p = _make_project(**_ready_overrides())
        data = p.model_dump(mode="json")
        data.pop("practice_state")
        data["schema_version"] = 3
        restored = ProjectRecord.model_validate(data)
        assert restored.practice_state == PracticeState()
