"""Marker record schema (M1.15, milestone1.md §17.1).

A marker is a per-project annotation at a source-frame position.
Positions are inclusive at both ends: zero and exactly the project's
``duration_frames`` are valid. The upper bound is checked against the
project's duration at the ``ProjectRecord`` level.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from basseparate.domain.common import SamplePosition, UtcTimestamp, Uuid

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_MARKER_LABEL_LENGTH = 80


def _validate_label(label: str) -> str:
    trimmed = label.strip()
    if not 1 <= len(trimmed) <= MAX_MARKER_LABEL_LENGTH:
        raise ValueError(
            f"marker label must be 1-{MAX_MARKER_LABEL_LENGTH} characters "
            f"after trimming, got {len(trimmed)}"
        )
    if _CONTROL_CHAR_RE.search(trimmed):
        raise ValueError("marker label must not contain embedded control characters")
    return trimmed


class MarkerRecord(BaseModel):
    """A single marker annotation in a project (§17.1)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    position_frames: SamplePosition
    label: str = Field(min_length=1, max_length=MAX_MARKER_LABEL_LENGTH)
    color: str = Field(pattern=r"^#[0-9a-f]{6}$", description="Hex color #rrggbb")
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @field_validator("label", mode="before")
    @classmethod
    def _trim_and_validate_label(cls, v: str) -> str:
        return _validate_label(v)
