"""Unit tests for the mixer and practice state (M2.1, spec §3.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain import (
    DEFAULT_LOOP_COLOR,
    MAX_GAIN,
    MAX_LOOP_REPEAT,
    MAX_PLAYBACK_SPEED,
    MIN_PLAYBACK_SPEED,
    PlaybackMode,
    PracticeLoop,
    PracticeState,
    SongSection,
    TrackSettings,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _section(**overrides: object) -> SongSection:
    base: dict[str, object] = {
        "id": uuid4(),
        "name": "Verse",
        "start_frames": 0,
        "end_frames": 1000,
        "color": "#22c55e",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return SongSection(**base)


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
        assert t.color == "#8fa3bf"

    def test_gain_bounds(self) -> None:
        assert TrackSettings(gain=MAX_GAIN).gain == MAX_GAIN
        with pytest.raises(ValidationError):
            TrackSettings(gain=MAX_GAIN + 0.1)
        with pytest.raises(ValidationError):
            TrackSettings(gain=-0.1)

    def test_gain_cap_is_plus_12_db(self) -> None:
        # Spec §10.3.2: the cap is +12 dB, not the old 2.0.
        assert pytest.approx(10.0 ** (12.0 / 20.0)) == MAX_GAIN
        assert TrackSettings(gain=2.0).gain == 2.0

    def test_color(self) -> None:
        assert TrackSettings(color="#ABC123").color == "#ABC123"
        with pytest.raises(ValidationError):
            TrackSettings(color="#12345")
        with pytest.raises(ValidationError):
            TrackSettings(color="123456")

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

    def test_m211_defaults(self) -> None:
        loop = _loop()
        assert loop.color == DEFAULT_LOOP_COLOR
        assert loop.repeat_count is None
        assert loop.boundary_fade is True

    def test_color_validated(self) -> None:
        assert _loop(color="#00ff00").color == "#00ff00"
        with pytest.raises(ValidationError, match="color"):
            _loop(color="green")

    def test_repeat_count_bounds(self) -> None:
        assert _loop(repeat_count=1).repeat_count == 1
        assert _loop(repeat_count=MAX_LOOP_REPEAT).repeat_count == MAX_LOOP_REPEAT
        with pytest.raises(ValidationError, match="repeat_count"):
            _loop(repeat_count=0)
        with pytest.raises(ValidationError, match="repeat_count"):
            _loop(repeat_count=MAX_LOOP_REPEAT + 1)


class TestPracticeState:
    def test_defaults(self) -> None:
        s = PracticeState()
        assert s.playback_mode == PlaybackMode.ORIGINAL
        assert s.active_result_set_id is None
        assert s.tracks == {}
        assert s.master_gain == 1.0
        assert s.monitoring_limiter is True
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

    def test_loop_enabled_requires_active_loop(self) -> None:
        # M2.11 invariant: looping without a selected loop is impossible.
        with pytest.raises(ValidationError, match="loop_enabled"):
            PracticeState(loop_enabled=True)
        loop = _loop()
        with pytest.raises(ValidationError, match="loop_enabled"):
            PracticeState(loops=[loop], loop_enabled=True)

    def test_playback_speed_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PracticeState(playback_speed=MIN_PLAYBACK_SPEED - 0.01)
        with pytest.raises(ValidationError):
            PracticeState(playback_speed=MAX_PLAYBACK_SPEED + 0.01)
        assert PracticeState(playback_speed=0.25).playback_speed == 0.25
        assert PracticeState(playback_speed=2.0).playback_speed == 2.0

    def test_master_gain_bounds(self) -> None:
        assert PracticeState(master_gain=MAX_GAIN).master_gain == MAX_GAIN
        with pytest.raises(ValidationError):
            PracticeState(master_gain=MAX_GAIN + 0.1)

    def test_monitoring_limiter_can_be_disabled(self) -> None:
        assert PracticeState(monitoring_limiter=False).monitoring_limiter is False


class TestSongSection:
    def test_valid_section(self) -> None:
        section = _section(name="  Chorus  ")
        assert section.name == "Chorus"
        assert section.start_frames == 0
        assert section.end_frames == 1000

    def test_reverse_or_empty_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="end_frames"):
            _section(start_frames=1000, end_frames=1000)
        with pytest.raises(ValidationError, match="end_frames"):
            _section(start_frames=2000, end_frames=1000)

    def test_name_and_color_validated(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            _section(name="   ")
        with pytest.raises(ValidationError, match="color"):
            _section(color="green")


class TestPracticeStateSections:
    def test_defaults(self) -> None:
        state = PracticeState()
        assert state.sections == []
        assert state.active_section_id is None

    def test_sections_must_be_ordered_and_non_overlapping(self) -> None:
        a = _section(id=uuid4(), start_frames=0, end_frames=1000)
        b = _section(id=uuid4(), start_frames=1000, end_frames=2000)
        state = PracticeState(sections=[a, b])
        assert [s.id for s in state.sections] == [a.id, b.id]
        with pytest.raises(ValidationError, match="order"):
            PracticeState(sections=[b, a])
        overlap = _section(id=uuid4(), start_frames=500, end_frames=1500)
        with pytest.raises(ValidationError, match="overlap"):
            PracticeState(sections=[a, overlap])

    def test_active_section_must_exist(self) -> None:
        with pytest.raises(ValidationError, match="active_section_id"):
            PracticeState(active_section_id=uuid4())
        section = _section()
        assert (
            PracticeState(sections=[section], active_section_id=section.id).active_section_id
            == section.id
        )

    def test_loop_can_reference_a_section(self) -> None:
        section = _section()
        loop = _loop(section_id=section.id)
        state = PracticeState(sections=[section], loops=[loop], active_loop_id=loop.id)
        assert state.loops[0].section_id == section.id

    def test_loop_section_must_exist(self) -> None:
        with pytest.raises(ValidationError, match="section_id"):
            PracticeState(loops=[_loop(section_id=uuid4())])


def test_sections_and_linked_loops_round_trip_project_json() -> None:
    from uuid import UUID

    from basseparate.domain.project import ProjectRecord, ProjectStatus

    section = _section()
    loop = _loop(section_id=section.id)
    project = ProjectRecord(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        name="Round trip",
        created_at=NOW,
        updated_at=NOW,
        status=ProjectStatus.READY,
        source_asset_id=uuid4(),
        canonical_asset_id=uuid4(),
        source_stream_index=0,
        sample_rate=48_000,
        duration_frames=48_000,
        source_channel_count=2,
        source_channel_layout="stereo",
        decode_profile_version=1,
        practice_state=PracticeState(
            sections=[section],
            active_section_id=section.id,
            loops=[loop],
            active_loop_id=loop.id,
        ),
    )
    restored = ProjectRecord.model_validate_json(project.model_dump_json())
    assert restored.practice_state.sections[0].id == section.id
    assert restored.practice_state.loops[0].section_id == section.id
    assert restored.practice_state.active_section_id == section.id
