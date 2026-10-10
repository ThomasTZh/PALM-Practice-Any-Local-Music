"""Unit tests for the mixer and practice state (M2.1, spec §3.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain import (
    MAX_GAIN,
    MAX_PLAYBACK_SPEED,
    MIN_PLAYBACK_SPEED,
    PlaybackMode,
    PracticeLoop,
    PracticeState,
    TrackSettings,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _loop(**overrides: object) -> PracticeLoop:
    base: dict[str, object] = {
        "id": uuid4(),
        "name": "Verse",
        "start_frames": 0,
        "end_frames": 1000,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return PracticeLoop(**base)


class TestPlaybackMode:
    def test_values(self) -> None:
        assert {m.value for m in PlaybackMode} == {"original", "bass_pair", "four_stems"}


class TestTrackSettings:
    def test_defaults(self) -> None:
        t = TrackSettings()
        assert t.gain == 1.0
        assert t.mute is False
        assert t.solo is False
        assert t.balance == 0.0
        assert t.visible is True
        assert t.display_height == 1.0

    def test_gain_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TrackSettings(gain=2.1)
        with pytest.raises(ValidationError):
            TrackSettings(gain=-0.1)

    def test_balance_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TrackSettings(balance=1.5)

    def test_display_height_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TrackSettings(display_height=0.1)
        with pytest.raises(ValidationError):
            TrackSettings(display_height=2.5)


class TestPracticeLoop:
    def test_valid_loop(self) -> None:
        loop = _loop()
        assert loop.end_frames > loop.start_frames

    def test_end_must_exceed_start(self) -> None:
        with pytest.raises(ValidationError, match="end_frames"):
            _loop(start_frames=1000, end_frames=1000)
        with pytest.raises(ValidationError, match="end_frames"):
            _loop(start_frames=2000, end_frames=1000)

    def test_name_trimmed_and_validated(self) -> None:
        loop = _loop(name="  Verse  ")
        assert loop.name == "Verse"

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            _loop(name="   ")


class TestPracticeState:
    def test_defaults(self) -> None:
        s = PracticeState()
        assert s.playback_mode == PlaybackMode.ORIGINAL
        assert s.active_result_set_id is None
        assert s.tracks == {}
        assert s.master_gain == 1.0
        assert s.monitoring_limiter is False
        assert s.playback_speed == 1.0
        assert s.loops == []
        assert s.active_loop_id is None
        assert s.loop_enabled is False

    def test_original_mode_allows_remembered_result_set(self) -> None:
        # A project that did a separation can switch back to original while
        # still remembering the active result set.
        s = PracticeState(playback_mode=PlaybackMode.ORIGINAL, active_result_set_id=uuid4())
        assert s.active_result_set_id is not None

    def test_bass_pair_requires_result_set(self) -> None:
        with pytest.raises(ValidationError, match="result set"):
            PracticeState(playback_mode=PlaybackMode.BASS_PAIR)

    def test_four_stems_requires_result_set(self) -> None:
        with pytest.raises(ValidationError, match="result set"):
            PracticeState(playback_mode=PlaybackMode.FOUR_STEMS)

    def test_stem_mode_with_result_set_ok(self) -> None:
        s = PracticeState(
            playback_mode=PlaybackMode.FOUR_STEMS,
            active_result_set_id=uuid4(),
            tracks={"bass": TrackSettings(gain=0.5), "vocals": TrackSettings(mute=True)},
        )
        assert s.tracks["bass"].gain == 0.5
        assert s.tracks["vocals"].mute is True

    def test_track_keys_must_be_stem_roles(self) -> None:
        with pytest.raises(ValidationError, match="stem role"):
            PracticeState(tracks={"guitar": TrackSettings()})

    def test_active_loop_must_exist(self) -> None:
        with pytest.raises(ValidationError, match="active_loop_id"):
            PracticeState(active_loop_id=uuid4())

    def test_active_loop_reference_ok(self) -> None:
        loop = _loop()
        s = PracticeState(loops=[loop], active_loop_id=loop.id, loop_enabled=True)
        assert s.active_loop_id == loop.id
        assert s.loop_enabled is True

    def test_playback_speed_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PracticeState(playback_speed=MIN_PLAYBACK_SPEED - 0.01)
        with pytest.raises(ValidationError):
            PracticeState(playback_speed=MAX_PLAYBACK_SPEED + 0.01)
        assert PracticeState(playback_speed=0.25).playback_speed == 0.25
        assert PracticeState(playback_speed=2.0).playback_speed == 2.0

    def test_master_gain_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PracticeState(master_gain=MAX_GAIN + 0.1)
