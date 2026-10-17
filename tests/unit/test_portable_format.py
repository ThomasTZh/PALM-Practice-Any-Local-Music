"""Portable format constants, member naming, compression, manifest (M2.14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from basseparate.portable.format import (
    ASSETS_PREFIX,
    CONTAINER_VERSION,
    DATABASE_MEMBER,
    DEFLATED,
    FALLBACK_SUFFIX,
    FORMAT_ID,
    MANIFEST_MEMBER,
    PCM_SUFFIX,
    PROVENANCE_MODELS_MEMBER,
    PROVENANCE_RUNS_MEMBER,
    STORED,
    WAVEFORM_CACHE_PREFIX,
    ManifestAsset,
    ManifestMember,
    ManifestProvenance,
    MemberCategory,
    PortableManifest,
    asset_member_path,
    asset_member_suffix,
    category_for,
    compression_for,
    compression_name,
    waveform_cache_member_prefix,
)

HASH = "ab" * 32


class TestMemberNaming:
    def test_pcm_roles_get_pcm_suffix(self) -> None:
        for role in ("source_pcm", "derived_pcm", "stem"):
            assert asset_member_suffix(role, "song.wav") == PCM_SUFFIX

    def test_source_original_keeps_upload_extension(self) -> None:
        assert asset_member_suffix("source_original", "song.wav") == ".wav"
        assert asset_member_suffix("source_original", "Mix Final.MP3") == ".MP3"

    def test_source_original_falls_back_to_bin(self) -> None:
        assert asset_member_suffix("source_original", None) == FALLBACK_SUFFIX
        assert asset_member_suffix("source_original", "noextension") == FALLBACK_SUFFIX

    def test_other_roles_fall_back_to_bin(self) -> None:
        assert asset_member_suffix("analysis_artifact", "x.json") == FALLBACK_SUFFIX
        assert asset_member_suffix("waveform_cache", None) == FALLBACK_SUFFIX

    def test_asset_member_path(self) -> None:
        assert (
            asset_member_path(HASH, "stem")
            == f"{ASSETS_PREFIX}{HASH}{PCM_SUFFIX}"
        )
        assert (
            asset_member_path(HASH, "source_original", "song.wav")
            == f"{ASSETS_PREFIX}{HASH}.wav"
        )

    def test_waveform_cache_member_prefix(self) -> None:
        assert waveform_cache_member_prefix("cd" * 32) == f"{WAVEFORM_CACHE_PREFIX}{'cd' * 32}/"


class TestCompressionPolicy:
    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (f"{ASSETS_PREFIX}{HASH}.pcm", STORED),
            (f"{ASSETS_PREFIX}{HASH}.wav", STORED),
            (f"{WAVEFORM_CACHE_PREFIX}{HASH}/level_0/tile_0.bin", STORED),
            (f"{WAVEFORM_CACHE_PREFIX}{HASH}/manifest.json", STORED),
            (DATABASE_MEMBER, STORED),
            (MANIFEST_MEMBER, DEFLATED),
            (PROVENANCE_RUNS_MEMBER, DEFLATED),
            (PROVENANCE_MODELS_MEMBER, DEFLATED),
        ],
    )
    def test_compression_for(self, member: str, expected: int) -> None:
        assert compression_for(member) == expected

    def test_compression_name(self) -> None:
        assert compression_name(DATABASE_MEMBER) == "stored"
        assert compression_name(MANIFEST_MEMBER) == "deflate"

    def test_category_for(self) -> None:
        assert category_for(MANIFEST_MEMBER) is MemberCategory.MANIFEST
        assert category_for(DATABASE_MEMBER) is MemberCategory.DATABASE
        assert category_for(f"{ASSETS_PREFIX}{HASH}.pcm") is MemberCategory.MEDIA
        assert category_for(f"{WAVEFORM_CACHE_PREFIX}{HASH}/x.bin") is MemberCategory.CACHE
        assert category_for(PROVENANCE_RUNS_MEMBER) is MemberCategory.PROVENANCE

    def test_category_for_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="unrecognized archive member"):
            category_for("model-weights.bin")


def _manifest() -> PortableManifest:
    project_id = uuid.uuid4()
    return PortableManifest(
        project_schema_version=9,
        application_version="0.1.0-dev",
        project_id=project_id,
        saved_revision=3,
        saved_at=datetime.now(UTC),
        assets=[
            ManifestAsset(
                asset_id=uuid.uuid4(),
                content_hash=HASH,
                role="source_pcm",
                member=asset_member_path(HASH, "source_pcm"),
                essential=True,
            )
        ],
        members=[
            ManifestMember(
                name=MANIFEST_MEMBER,
                uncompressed_size_bytes=1234,
                sha256="cd" * 32,
                essential=True,
                compression="deflate",
                category=MemberCategory.MANIFEST,
            ),
            ManifestMember(
                name=f"{ASSETS_PREFIX}{HASH}.pcm",
                uncompressed_size_bytes=8_820_000,
                sha256=HASH,
                essential=True,
                compression="stored",
                category=MemberCategory.MEDIA,
            ),
        ],
        provenance=ManifestProvenance(
            separation_runs=[{"id": str(uuid.uuid4())}], model_manifests=[]
        ),
    )


class TestManifestSchema:
    def test_defaults(self) -> None:
        manifest = _manifest()
        assert manifest.format_id == FORMAT_ID
        assert manifest.container_version == CONTAINER_VERSION

    def test_json_round_trip(self) -> None:
        manifest = _manifest()
        payload = manifest.model_dump_json()
        restored = PortableManifest.model_validate_json(payload)
        assert restored == manifest
        data = restored.model_dump(mode="json")
        assert data["format_id"] == FORMAT_ID
        assert isinstance(data["project_id"], str)
        assert data["saved_at"].endswith("Z")
        assert data["members"][0]["sha256"] == "cd" * 32

    def test_rejects_bad_sha256(self) -> None:
        with pytest.raises(ValidationError):
            ManifestMember(
                name=MANIFEST_MEMBER,
                uncompressed_size_bytes=1,
                sha256="NOPE",
                essential=True,
                compression="deflate",
                category=MemberCategory.MANIFEST,
            )

    def test_rejects_negative_size(self) -> None:
        with pytest.raises(ValidationError):
            ManifestMember(
                name=MANIFEST_MEMBER,
                uncompressed_size_bytes=-1,
                sha256="cd" * 32,
                essential=True,
                compression="deflate",
                category=MemberCategory.MANIFEST,
            )

    def test_rejects_negative_revision(self) -> None:
        with pytest.raises(ValidationError):
            PortableManifest(
                project_schema_version=9,
                application_version="0.1.0-dev",
                project_id=uuid.uuid4(),
                saved_revision=-1,
                saved_at=datetime.now(UTC),
            )

    def test_manifest_is_frozen(self) -> None:
        manifest = _manifest()
        with pytest.raises(ValidationError):
            manifest.saved_revision = 4  # type: ignore[misc]
