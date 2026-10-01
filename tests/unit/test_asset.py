"""Unit tests for AssetRecord and path rules (M0.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.asset import (
    AssetRecord,
    AssetRole,
    AudioMetadata,
    resolve_asset_path,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)
FAKE_HASH = "a" * 64


def _make_asset(**overrides: object) -> AssetRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "content_hash": FAKE_HASH,
        "role": AssetRole.SOURCE_PCM,
        "relative_path": "assets/source.wav",
        "media_type": "audio/wav",
        "byte_count": 1024,
        "created_at": NOW,
    }
    base.update(overrides)
    return AssetRecord(**base)


def test_basic_asset() -> None:
    a = _make_asset()
    assert a.role == AssetRole.SOURCE_PCM
    assert a.byte_count == 1024
    assert a.audio is None


def test_asset_with_audio_metadata() -> None:
    audio = AudioMetadata(
        sample_rate=48000,
        channel_count=2,
        frame_count=96_000,
        sample_format="s16le",
    )
    a = _make_asset(audio=audio)
    assert a.audio.sample_rate == 48000


def test_reject_absolute_path() -> None:
    with pytest.raises(ValidationError, match="relative"):
        _make_asset(relative_path="/etc/passwd")


def test_reject_dotdot_traversal() -> None:
    with pytest.raises(ValidationError, match="traversal"):
        _make_asset(relative_path="../escape.wav")


def test_reject_nul_byte() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        _make_asset(relative_path="assets/bad\x00.wav")


def test_reject_empty_path() -> None:
    with pytest.raises(ValidationError):
        _make_asset(relative_path="")


def test_reject_invalid_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        _make_asset(content_hash="not-a-hash")


def test_resolve_asset_path_containment(tmp_path: Path) -> None:
    resolved = resolve_asset_path(tmp_path, "assets/foo.wav")
    assert resolved == tmp_path / "assets" / "foo.wav"
    assert resolved.is_relative_to(tmp_path)


def test_resolve_asset_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="traversal"):
        resolve_asset_path(tmp_path, "../../etc/passwd")


def test_serialization_roundtrip() -> None:
    a = _make_asset()
    data = a.model_dump(mode="json")
    assert isinstance(data["id"], str)
    restored = AssetRecord.model_validate(data)
    assert restored == a
