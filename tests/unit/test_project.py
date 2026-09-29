"""Unit tests for ProjectRecord schema (M0.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.project import ProjectRecord, ProjectStatus

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


def test_empty_project_defaults() -> None:
    p = _make_project()
    assert p.status == ProjectStatus.EMPTY
    assert p.revision == 0
    assert p.source_asset_id is None
    assert p.sample_rate is None
    assert p.duration_samples is None
    assert p.schema_version == 1


def test_ready_project_requires_source_asset() -> None:
    with pytest.raises(ValidationError, match="source_asset_id"):
        _make_project(status=ProjectStatus.READY)


def test_ready_project_with_source() -> None:
    asset_id = uuid4()
    p = _make_project(
        status=ProjectStatus.READY,
        source_asset_id=asset_id,
        sample_rate=44100,
        duration_samples=1_000_000,
    )
    assert p.status == ProjectStatus.READY
    assert p.source_asset_id == asset_id
    assert p.sample_rate == 44100


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
        _make_project(status=ProjectStatus.READY, source_asset_id=uuid4(), duration_samples=100)


def test_empty_project_must_not_have_source_asset() -> None:
    with pytest.raises(ValidationError, match="empty project"):
        _make_project(source_asset_id=uuid4())


def test_serialization_roundtrip() -> None:
    p = _make_project()
    data = p.model_dump(mode="json")
    assert isinstance(data["id"], str)
    assert data["source_asset_id"] is None
    restored = ProjectRecord.model_validate(data)
    assert restored == p


def test_forward_compat_rejects_newer_schema() -> None:
    p = _make_project(schema_version=99)
    assert p.schema_version == 99
