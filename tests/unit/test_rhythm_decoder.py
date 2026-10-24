"""Beat/downbeat candidate decoder (M3.5, milestone3.md §7)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from pydantic import ValidationError

from basseparate.domain.rhythm import ActivationFrameMapping, PulseAcceptance, PulseRole
from basseparate.domain.rhythm_decode import (
    BEAT_THIS_DECODER_PROFILE,
    BeatDecoderProfile,
)
from basseparate.rhythm.decoder import DecodeInput, RhythmDecodeError, decode_arrays


def _mapping(
    *,
    project_rate: int = 48_000,
    model_rate: int = 22_050,
    hop: int = 441,
    offset: int = 0,
) -> ActivationFrameMapping:
    return ActivationFrameMapping(
        model_sample_rate=model_rate,
        project_sample_rate=project_rate,
        frame_hop=hop,
        offset_frames=offset,
    )


def _arrays(size: int) -> tuple[np.ndarray, np.ndarray]:
    return np.zeros(size, dtype=np.float32), np.zeros(size, dtype=np.float32)


def _decode(
    beat: np.ndarray,
    downbeat: np.ndarray,
    *,
    mapping: ActivationFrameMapping | None = None,
    duration: int = 10_000_000,
    profile: BeatDecoderProfile = BEAT_THIS_DECODER_PROFILE,
    content_hash: str = "ab" * 32,
):
    return decode_arrays(
        DecodeInput(
            artifact_id=uuid.uuid4(),
            content_hash=content_hash,
            frame_mapping=mapping or _mapping(),
            beat=beat,
            downbeat=downbeat,
        ),
        project_sample_rate=(mapping or _mapping()).project_sample_rate,
        source_duration_frames=duration,
        profile=profile,
    )


class TestPeakDecoding:
    def test_beats_and_snapped_downbeats(self) -> None:
        beat, downbeat = _arrays(200)
        beat[[10, 60, 110, 160]] = [2.0, 1.5, 1.8, 2.2]
        downbeat[[10, 110]] = [1.0, 0.8]

        result = _decode(beat, downbeat)

        assert len(result.accepted_pulses) == 4
        assert [pulse.source_frame for pulse in result.accepted_pulses] == [
            9_600,
            57_600,
            105_600,
            153_600,
        ]
        roles = [pulse.role for pulse in result.accepted_pulses]
        assert roles == [
            PulseRole.DOWNBEAT,
            PulseRole.BEAT,
            PulseRole.DOWNBEAT,
            PulseRole.BEAT,
        ]
        downbeat_pulse = result.accepted_pulses[0]
        assert downbeat_pulse.beat_logit == pytest.approx(2.0)
        assert downbeat_pulse.downbeat_logit == pytest.approx(1.0)
        assert downbeat_pulse.confidence.calibrated is False
        assert downbeat_pulse.confidence.value == pytest.approx(1.0 / (1.0 + np.exp(-1.0)))
        assert downbeat_pulse.source_frame_fraction.numerator == 9_600
        assert downbeat_pulse.source_frame_fraction.denominator == 1

    def test_rounding_half_up(self) -> None:
        beat, downbeat = _arrays(50)
        beat[1] = 1.0
        # project_rate 25 -> 0.5 source frames per model frame; frame 1 = 0.5 -> 1
        result = _decode(beat, downbeat, mapping=_mapping(project_rate=25), duration=100)
        assert result.accepted_pulses[0].source_frame == 1
        assert result.accepted_pulses[0].source_frame_fraction.numerator == 1
        assert result.accepted_pulses[0].source_frame_fraction.denominator == 2

    def test_downbeat_snapped_to_nearest_beat(self) -> None:
        beat, downbeat = _arrays(100)
        beat[[20, 21]] = 1.0
        downbeat[25] = 1.0
        result = _decode(beat, downbeat)
        downbeats = [p for p in result.accepted_pulses if p.role is PulseRole.DOWNBEAT]
        assert len(downbeats) == 1
        assert downbeats[0].model_frame == 20.5
        assert downbeats[0].peak_model_frame == 25.0
        assert "downbeat_snapped" in downbeats[0].flags

    def test_no_peaks_is_valid(self) -> None:
        beat, downbeat = _arrays(100)
        result = _decode(beat, downbeat)
        assert result.accepted_pulses == []
        assert result.candidate_pulses == []
        assert "no_accepted_pulses" in result.flags

    def test_downbeats_without_beats(self) -> None:
        beat, downbeat = _arrays(100)
        downbeat[40] = 1.0
        result = _decode(beat, downbeat)
        assert len(result.accepted_pulses) == 1
        assert result.accepted_pulses[0].role is PulseRole.DOWNBEAT
        assert "downbeats_without_beats" in result.flags


class TestCandidates:
    def test_low_confidence_candidates_retained(self) -> None:
        beat, downbeat = _arrays(200)
        beat[10] = 2.0
        beat[55:66] = -3.0
        beat[60] = -1.0
        downbeat[55:66] = -3.0
        downbeat[60] = -1.5
        result = _decode(beat, downbeat)
        assert len(result.accepted_pulses) == 1
        assert len(result.candidate_pulses) == 2
        assert all(
            pulse.acceptance is PulseAcceptance.CANDIDATE for pulse in result.candidate_pulses
        )
        assert all("low_confidence" in pulse.flags for pulse in result.candidate_pulses)

    def test_source_collision_keeps_strongest_and_retains_alternative(self) -> None:
        beat, downbeat = _arrays(100)
        beat[[10, 20]] = [2.0, 0.5]
        result = _decode(beat, downbeat, mapping=_mapping(project_rate=1), duration=10)
        assert len(result.accepted_pulses) == 1
        assert result.accepted_pulses[0].probability > 0.8
        assert result.candidate_pulses
        collision = result.candidate_pulses[0]
        assert "source_collision" in collision.flags
        assert collision.alternative_of == result.accepted_pulses[0].id

    def test_outside_source_is_candidate(self) -> None:
        beat, downbeat = _arrays(100)
        beat[0] = 1.0
        beat[10] = 1.0
        result = _decode(beat, downbeat, duration=1_000)
        assert [p.source_frame for p in result.accepted_pulses] == [0]
        outside = [p for p in result.candidate_pulses if "outside_source" in p.flags]
        assert len(outside) == 1

    def test_endpoint_rounding_is_clamped(self) -> None:
        beat, downbeat = _arrays(100)
        beat[1] = 1.0
        # frame 1 maps to 0.5 source frames; duration 0 with tolerance 1 clamps to 0
        result = _decode(beat, downbeat, mapping=_mapping(project_rate=25), duration=0)
        assert len(result.accepted_pulses) == 1
        assert "clamped_endpoint" in result.accepted_pulses[0].flags


class TestPlausibilityAndIdentity:
    def test_tiny_interval_and_long_gap(self) -> None:
        beat, downbeat = _arrays(300)
        beat[0] = 2.0
        beat[4] = 1.0
        beat[20] = 1.0
        beat[200] = 2.0
        result = _decode(beat, downbeat)
        assert "tiny_interval" in result.flags
        assert "long_gap" in result.flags

    def test_deterministic_content_hash_and_ids(self) -> None:
        beat, downbeat = _arrays(100)
        beat[10] = 1.0
        first = _decode(beat, downbeat)
        second = _decode(beat, downbeat)
        assert first.content_hash == second.content_hash
        assert first.id != second.id
        assert first.accepted_pulses[0].id != second.accepted_pulses[0].id

    def test_profile_version_changes_identity(self) -> None:
        beat, downbeat = _arrays(100)
        beat[10] = 1.0
        base = _decode(beat, downbeat)
        changed = _decode(
            beat,
            downbeat,
            profile=BeatDecoderProfile(**{**BEAT_THIS_DECODER_PROFILE.model_dump(), "version": 2}),
        )
        assert base.content_hash != changed.content_hash

    def test_invalid_arrays(self) -> None:
        beat, downbeat = _arrays(10)
        with pytest.raises(RhythmDecodeError):
            _decode(beat.astype(np.float64), downbeat)
        with pytest.raises(RhythmDecodeError):
            _decode(beat.reshape(2, 5), downbeat.reshape(2, 5))


class TestProfile:
    def test_default_matches_upstream_minimal(self) -> None:
        profile = BEAT_THIS_DECODER_PROFILE
        assert profile.profile_id == "beat-this-minimal-v1"
        assert profile.peak_window_frames == 7
        assert profile.accepted_logit_threshold == 0.0
        assert profile.snap_downbeats_to_beats is True
        assert profile.rounding == "half_up"

    def test_rejects_inverted_thresholds(self) -> None:
        with pytest.raises(ValidationError):
            BeatDecoderProfile(
                **{
                    **BEAT_THIS_DECODER_PROFILE.model_dump(),
                    "candidate_logit_threshold": 1.0,
                }
            )
