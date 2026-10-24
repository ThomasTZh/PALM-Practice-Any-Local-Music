"""Portable project format: container layout, manifest schema, compression.

M2.14 (spec §16) defines the portable project container. This module
pins the format constants, the archive member naming rules, the
compression policy, and the versioned manifest schema. M2.15 writes
archives from this definition; M2.16 validates them against it.

Container layout (§16.1)::

    song.basseparate
    ├── manifest.json
    ├── project.sqlite
    ├── assets/
    │   └── sha256/...
    ├── caches/
    │   └── waveforms/...
    └── provenance/
        ├── separation-runs.json
        └── model-manifests.json

The container is ZIP64 (Python's ``zipfile`` provides ZIP64 and
streamed member handling); members are addressed by path and
uncompressed size so the complete archive is never loaded into
memory.
"""

from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import Sha256Hash, UtcTimestamp, Uuid

#: Format identifier recorded in every manifest (§16.4).
FORMAT_ID = "basseparate.project"

#: Container format version. Bump only for layout/manifest changes.
CONTAINER_VERSION = 1

#: Fixed archive member names (§16.1).
MANIFEST_MEMBER = "manifest.json"
DATABASE_MEMBER = "project.sqlite"
PROVENANCE_RUNS_MEMBER = "provenance/separation-runs.json"
PROVENANCE_MODELS_MEMBER = "provenance/model-manifests.json"

#: Member prefixes for the variable members (§16.1).
ASSETS_PREFIX = "assets/sha256/"
WAVEFORM_CACHE_PREFIX = "caches/waveforms/"
#: Optional rhythm activation arrays (M3.18 §20.9). Rebuildable, so
#: members under this prefix are not essential for practice.
RHYTHM_ACTIVATION_PREFIX = "caches/rhythm/activations/"

#: Compression: stored for large media/PCM and the database, deflate
#: for compact text/metadata (§16.1).
STORED = zipfile.ZIP_STORED
DEFLATED = zipfile.ZIP_DEFLATED

#: PCM asset suffix. PCM assets are content-addressed raw PCM
#: (f32le, interleaved) with no container of their own.
PCM_SUFFIX = ".pcm"

#: Fallback suffix for assets whose original name is unknown.
FALLBACK_SUFFIX = ".bin"


class MemberCategory(StrEnum):
    """Archive member categories (manifest metadata)."""

    MANIFEST = "manifest"
    DATABASE = "database"
    MEDIA = "media"
    CACHE = "cache"
    PROVENANCE = "provenance"


def _suffix_from_filename(filename: str | None) -> str:
    if not filename:
        return FALLBACK_SUFFIX
    suffix = PurePosixPath(filename).suffix
    return suffix if suffix else FALLBACK_SUFFIX


def asset_member_suffix(role: str, original_filename: str | None = None) -> str:
    """Archive suffix for an asset member (§16.1 naming).

    PCM roles carry ``.pcm``; the original upload keeps its file
    extension (e.g. ``.wav``) when the import record provides one;
    everything else falls back to ``.bin``.
    """
    if role in ("source_pcm", "derived_pcm", "stem"):
        return PCM_SUFFIX
    if role == "source_original":
        return _suffix_from_filename(original_filename)
    return FALLBACK_SUFFIX


def asset_member_path(content_hash: str, role: str, original_filename: str | None = None) -> str:
    """Archive member path for one asset (``assets/sha256/<hash><ext>``)."""
    return f"{ASSETS_PREFIX}{content_hash}{asset_member_suffix(role, original_filename)}"


def waveform_cache_member_prefix(source_hash: str) -> str:
    """Archive member prefix for one waveform cache directory tree."""
    return f"{WAVEFORM_CACHE_PREFIX}{source_hash}/"


def category_for(member: str) -> MemberCategory:
    """Classify an archive member path into its category."""
    if member == MANIFEST_MEMBER:
        return MemberCategory.MANIFEST
    if member == DATABASE_MEMBER:
        return MemberCategory.DATABASE
    if member.startswith(ASSETS_PREFIX):
        return MemberCategory.MEDIA
    if member.startswith(WAVEFORM_CACHE_PREFIX):
        return MemberCategory.CACHE
    if member.startswith(RHYTHM_ACTIVATION_PREFIX):
        return MemberCategory.CACHE
    if member.startswith("provenance/"):
        return MemberCategory.PROVENANCE
    raise ValueError(f"unrecognized archive member: {member!r}")


def compression_for(member: str) -> int:
    """Compression policy per member (§16.1).

    Stored (0) for large media/PCM, the waveform cache tiles, and the
    database; deflate (8) for compact text/metadata.
    """
    category = category_for(member)
    if category in (MemberCategory.MEDIA, MemberCategory.CACHE, MemberCategory.DATABASE):
        return STORED
    return DEFLATED


def compression_name(member: str) -> Literal["stored", "deflate"]:
    """The manifest spelling of the member's compression policy."""
    return "stored" if compression_for(member) == STORED else "deflate"


class ManifestMember(BaseModel):
    """One archive member with its integrity data (§16.4)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, description="Archive member path")
    uncompressed_size_bytes: int = Field(ge=0)
    sha256: Sha256Hash
    essential: bool = Field(
        description="False ⇒ optional/reproducible; safe to be missing"
    )
    compression: Literal["stored", "deflate"]
    category: MemberCategory


class ManifestAsset(BaseModel):
    """One project asset in the archive (§16.4 asset list)."""

    model_config = ConfigDict(frozen=True)

    asset_id: Uuid
    content_hash: Sha256Hash
    role: str = Field(min_length=1)
    member: str = Field(min_length=1, description="Archive member path")
    essential: bool


class ManifestProvenance(BaseModel):
    """Model/run provenance references (§16.4, §16.2 analysis provenance).

    The payloads are the checked-in registry metadata (names, hashes,
    sizes, licenses) and the project's separation run records. Model
    weights are never part of the archive (§16.3).
    """

    model_config = ConfigDict(frozen=True)

    separation_runs: list[dict[str, Any]]
    model_manifests: list[dict[str, Any]]


class PortableManifest(BaseModel):
    """The versioned manifest at the root of a portable project (§16.4)."""

    model_config = ConfigDict(frozen=True)

    format_id: str = Field(default=FORMAT_ID, min_length=1)
    container_version: int = Field(default=CONTAINER_VERSION, ge=1)
    project_schema_version: int = Field(ge=1)
    application_version: str = Field(min_length=1)
    project_id: Uuid
    saved_revision: int = Field(ge=0, description="projects.revision at save time")
    saved_at: UtcTimestamp
    assets: list[ManifestAsset] = Field(default_factory=list)
    members: list[ManifestMember] = Field(default_factory=list)
    provenance: ManifestProvenance = Field(
        default_factory=lambda: ManifestProvenance(
            separation_runs=[], model_manifests=[]
        )
    )
