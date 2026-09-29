"""Project record schema (M0.4).

An empty project is a valid, persisted state. Source timing fields
(sample_rate, duration_samples) are present together or both null.
"""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from basseparate import PROJECT_SCHEMA_VERSION
from basseparate.domain.common import Revision, SamplePosition, SampleRate, UtcTimestamp, Uuid

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

NameStr = str


class ProjectStatus(StrEnum):
    EMPTY = "empty"
    READY = "ready"


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not 1 <= len(trimmed) <= 200:
        raise ValueError(
            f"project name must be 1-200 characters after trimming, got {len(trimmed)}"
        )
    if _CONTROL_CHAR_RE.search(trimmed):
        raise ValueError("project name must not contain embedded control characters")
    return trimmed


def _check_source_fields_together(sample_rate: int | None, duration_samples: int | None) -> None:
    if (sample_rate is None) != (duration_samples is None):
        raise ValueError("sample_rate and duration_samples must be present together or both null")


class ProjectRecord(BaseModel):
    """A persisted working project.

    An empty project has ``status == "empty"``, ``source_asset_id`` is null,
    and both source timing fields are null.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    schema_version: int = Field(
        default=PROJECT_SCHEMA_VERSION,
        ge=1,
        description="Project schema version",
    )
    id: Uuid
    name: NameStr = Field(min_length=1, max_length=200)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    revision: Revision = Field(default=0)
    source_asset_id: Uuid | None = None
    sample_rate: SampleRate | None = None
    duration_samples: SamplePosition | None = None
    status: ProjectStatus = ProjectStatus.EMPTY

    @field_validator("name", mode="before")
    @classmethod
    def _trim_and_validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("status", mode="before")
    @classmethod
    def _status_matches_source_fields(cls, v: str, info: object) -> str:
        return v

    def model_post_init(self, __context: object) -> None:
        _check_source_fields_together(self.sample_rate, self.duration_samples)
        if self.status == ProjectStatus.READY and self.source_asset_id is None:
            raise ValueError("a ready project must have a source_asset_id")
        if self.status == ProjectStatus.EMPTY and self.source_asset_id is not None:
            raise ValueError("an empty project must not have a source_asset_id")

    @field_serializer("id", "source_asset_id")
    def _serialize_uuid(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None
