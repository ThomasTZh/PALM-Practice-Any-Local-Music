"""Unit tests for AudioRepresentation schemas (M1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)
FAKE_HASH = "d" * 64
OTHER_HASH = "e" * 64


def _make_provenance(**overrides: object) -> RepresentationProvenance:
    base: dict[str, object] = {
        "tool": "ffmpeg",
        "tool_version": "8.1.2",
        "profile_version": 1,
        "created_at": NOW,
    }
    base.update(overrides)
    return RepresentationProvenance(**base)


def _make_representation(**overrides: object) -> AudioRepresentation:
    base: dict[str, object] = {
        "asset_id": uuid4(),
        "parent_asset_id": uuid4(),
        "role": RepresentationRole.CANONICAL,
        "sample_rate": 48_000,
        "channel_count": 2,
        "channel_layout": "stereo",
        "frame_count": 4_800_000,
        "content_hash": FAKE_HASH,
        "transform_key": OTHER_HASH,
        "time_mapping": TimeMapping(project_rate=48_000, representation_rate=48_000),
        "provenance": _make_provenance(),
    }
    base.update(overrides)
    return AudioRepresentation(**base)


class TestTimeMapping:
    def test_identity_mapping(self) -> None:
        m = TimeMapping(project_rate=48_000, representation_rate=48_000)
        assert m.project_rate == m.representation_rate

    def test_rate_mismatch_mapping(self) -> None:
        m = TimeMapping(project_rate=44_100, representation_rate=48_000)
        assert m.project_rate != m.representation_rate
        # project_position = rep_frame * project_rate / representation_rate
        assert m.project_rate * 100 / m.representation_rate == 100 * 44_100 / 48_000


class TestAudioRepresentation:
    def test_canonical_representation(self) -> None:
        r = _make_representation()
        assert r.role == RepresentationRole.CANONICAL
        assert r.encoding == "f32le"
        assert r.interleaving == "interleaved"
        assert r.is_identity

    def test_playback_rate_representation(self) -> None:
        r = _make_representation(
            role=RepresentationRole.PLAYBACK_RATE,
            sample_rate=48_000,
            frame_count=5_224_138,
            time_mapping=TimeMapping(project_rate=44_100, representation_rate=48_000),
        )
        assert not r.is_identity
        assert r.sample_rate == 48_000

    def test_monitoring_downmix_representation(self) -> None:
        r = _make_representation(
            role=RepresentationRole.MONITORING_DOWNMIX,
            channel_count=2,
            channel_layout="stereo",
        )
        assert r.role == RepresentationRole.MONITORING_DOWNMIX

    def test_encoding_fixed_to_f32le(self) -> None:
        with pytest.raises(ValidationError, match="encoding"):
            _make_representation(encoding="s16le")  # type: ignore[arg-type]

    def test_interleaving_fixed(self) -> None:
        with pytest.raises(ValidationError, match="interleaving"):
            _make_representation(interleaving="planar")  # type: ignore[arg-type]

    def test_channel_count_bounds(self) -> None:
        with pytest.raises(ValidationError, match="channel_count"):
            _make_representation(channel_count=9)

    def test_transform_key_must_be_sha256(self) -> None:
        with pytest.raises(ValidationError, match="transform_key"):
            _make_representation(transform_key="nope")

    def test_serialization_roundtrip(self) -> None:
        r = _make_representation()
        data = r.model_dump(mode="json")
        assert isinstance(data["asset_id"], str)
        restored = AudioRepresentation.model_validate(data)
        assert restored == r
