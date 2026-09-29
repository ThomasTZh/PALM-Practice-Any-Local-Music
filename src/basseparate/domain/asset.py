"""Asset record schema and path rules (M0.4).

Assets are content-addressed blobs stored under managed storage.
Internal paths are relative, never absolute, and never traverse
outside the storage root.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from basseparate.domain.common import (
    Revision,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)


class AssetRole(StrEnum):
    SOURCE_ORIGINAL = "source_original"
    SOURCE_PCM = "source_pcm"
    STEM = "stem"
    ANALYSIS_ARTIFACT = "analysis_artifact"
    WAVEFORM_CACHE = "waveform_cache"


class AudioMetadata(BaseModel):
    """Optional audio-specific metadata.

    Present for PCM and source audio assets; absent for non-audio
    artifacts like waveform caches.
    """

    model_config = ConfigDict(frozen=True)

    sample_rate: int = Field(ge=1, description="Sample rate in Hz")
    channel_count: int = Field(ge=1, description="Number of audio channels")
    sample_count: int = Field(ge=0, description="Total sample frames")
    sample_format: str = Field(
        min_length=1,
        description="Sample format identifier (e.g. 's16le', 'f32le')",
    )


def _validate_relative_path(value: str) -> str:
    if "\x00" in value:
        raise ValueError("asset path must not contain NUL bytes")
    p = PurePosixPath(value)
    if p.is_absolute():
        raise ValueError(f"asset path must be relative, got absolute path: {value!r}")
    parts = p.parts
    if any(part == ".." for part in parts):
        raise ValueError(f"asset path must not contain '..' traversal: {value!r}")
    if not parts:
        raise ValueError("asset path must not be empty")
    return value


def resolve_asset_path(storage_root: Path, relative_path: str) -> Path:
    """Resolve an asset's relative path against the storage root.

    Verifies containment: the resolved path must remain inside
    ``storage_root``. Raises ``ValueError`` on escape.
    """
    _validate_relative_path(relative_path)
    root = storage_root.resolve()
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"resolved asset path {resolved!r} escapes storage root {root!r}")
    return resolved


class AssetRecord(BaseModel):
    """A content-addressed asset stored under managed storage."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    content_hash: Sha256Hash
    role: AssetRole
    relative_path: str = Field(min_length=1)
    media_type: str = Field(min_length=1, description="MIME type, e.g. 'audio/wav'")
    byte_count: int = Field(ge=0)
    created_at: UtcTimestamp
    audio: AudioMetadata | None = None
    revision: Revision = Field(default=0)

    @field_validator("relative_path", mode="before")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        return _validate_relative_path(v)

    @field_serializer("id")
    def _serialize_uuid(self, v: UUID) -> str:
        return str(v)
