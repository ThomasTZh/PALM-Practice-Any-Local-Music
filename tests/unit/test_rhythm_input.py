"""Rhythm input plan/profile and transform identity (M3.3, §5.3-§5.7)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from basseparate.domain.preparation import DownmixSpec
from basseparate.domain.rhythm import RhythmInputRole
from basseparate.domain.rhythm_input import (
    BEAT_THIS_INPUT_PROFILE,
    RhythmInputPlan,
    RhythmInputProfile,
)
from basseparate.media.rhythm_input import rhythm_input_transform_hash

HASH_A = "ab" * 32
HASH_B = "cd" * 32


def _plan(**overrides: object) -> RhythmInputPlan:
    data: dict[str, object] = {
        "input_role": RhythmInputRole.ORIGINAL_MIX,
        "asset_id": uuid.uuid4(),
        "source_hash": HASH_A,
        "sample_rate": 48_000,
        "channel_count": 2,
        "model_id": "beat_this_final0",
        "model_manifest_hash": HASH_B,
        "adapter_version": "beat-this-adapter-v1",
    }
    data.update(overrides)
    return RhythmInputPlan.model_validate(data)  # type: ignore[arg-type]


class TestRhythmInputPlan:
    def test_stereo_plan(self) -> None:
        plan = _plan()
        assert plan.downmix is None
        assert plan.input_role is RhythmInputRole.ORIGINAL_MIX

    def test_multichannel_requires_downmix(self) -> None:
        with pytest.raises(ValidationError):
            _plan(channel_count=6)
        plan = _plan(
            channel_count=6,
            downmix=DownmixSpec(mode="standard_5_1"),
        )
        assert plan.downmix is not None

    def test_mono_and_stereo_forbid_downmix(self) -> None:
        with pytest.raises(ValidationError):
            _plan(channel_count=2, downmix=DownmixSpec(mode="standard_5_1"))

    def test_channel_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _plan(channel_count=0)
        with pytest.raises(ValidationError):
            _plan(channel_count=9)

    def test_roles(self) -> None:
        plan = _plan(input_role=RhythmInputRole.DRUM_STEM)
        assert plan.input_role is RhythmInputRole.DRUM_STEM


class TestRhythmInputProfile:
    def test_pinned_geometry(self) -> None:
        profile = BEAT_THIS_INPUT_PROFILE
        assert profile.model_sample_rate == 22_050
        assert profile.frame_hop == 441
        assert profile.frame_rate == 50.0
        assert profile.prepared_channels == 2
        assert profile.channel_transform == "adapter_mean_over_prepared_channels"
        assert profile.amplitude_transform == "none"
        assert profile.long_track_strategy == "upstream_split_predict_aggregate"
        assert profile.long_track_chunk_frames == 1_500
        assert profile.long_track_border_frames == 6

    def test_profile_rejects_bad_geometry(self) -> None:
        with pytest.raises(ValidationError):
            RhythmInputProfile(
                **{
                    **BEAT_THIS_INPUT_PROFILE.model_dump(),
                    "frame_rate": 49.0,
                }
            )

    def test_matches_registry_adapter(self) -> None:
        from basseparate.models.rhythm_registry import get_rhythm_model

        model = get_rhythm_model("beat_this_final0")
        assert model.adapter_version == "beat-this-adapter-v1"
        assert model.input_sample_rate == BEAT_THIS_INPUT_PROFILE.model_sample_rate
        assert model.frame_hop == BEAT_THIS_INPUT_PROFILE.frame_hop
        assert model.frame_rate == BEAT_THIS_INPUT_PROFILE.frame_rate


class TestTransformHash:
    def test_deterministic(self) -> None:
        plan = _plan()
        first = rhythm_input_transform_hash(plan)
        second = rhythm_input_transform_hash(plan)
        assert first == second
        assert len(first) == 64

    def test_asset_id_is_not_part_of_identity(self) -> None:
        a = _plan(asset_id=uuid.uuid4())
        b = _plan(asset_id=uuid.uuid4())
        assert rhythm_input_transform_hash(a) == rhythm_input_transform_hash(b)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("source_hash", HASH_B),
            ("input_role", RhythmInputRole.DRUM_STEM),
            ("model_id", "beat_this_small0"),
            ("model_manifest_hash", "ef" * 32),
            ("adapter_version", "other-adapter"),
            ("sample_rate", 44_100),
        ],
    )
    def test_sensitive_fields(self, field: str, value: object) -> None:
        base = _plan()
        changed = _plan(**{field: value})
        assert rhythm_input_transform_hash(base) != rhythm_input_transform_hash(changed)

    def test_downmix_changes_identity(self) -> None:
        base = _plan(
            channel_count=6,
            downmix=DownmixSpec(mode="standard_5_1"),
        )
        manual = _plan(
            channel_count=6,
            downmix=DownmixSpec(mode="manual", left_channel=0, right_channel=2),
        )
        assert rhythm_input_transform_hash(base) != rhythm_input_transform_hash(manual)
