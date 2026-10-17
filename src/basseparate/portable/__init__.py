"""Portable project format (M2.14, spec §16).

Defines the portable project container: layout and manifest schema
(``format``), the dependency closure (``closure``), and the
project-only database builder (``database``). Writing archives is
M2.15; opening and validating them is M2.16.
"""

from basseparate.portable.closure import (
    PROVENANCE_PAYLOAD_VERSION,
    PortableAsset,
    PortableFormatError,
    PortablePlan,
    PortableWaveformCache,
    compute_portable_plan,
    model_manifests_payload,
    separation_runs_payload,
)
from basseparate.portable.database import build_portable_database
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

__all__ = [
    "ASSETS_PREFIX",
    "CONTAINER_VERSION",
    "DATABASE_MEMBER",
    "DEFLATED",
    "FALLBACK_SUFFIX",
    "FORMAT_ID",
    "MANIFEST_MEMBER",
    "PCM_SUFFIX",
    "PROVENANCE_MODELS_MEMBER",
    "PROVENANCE_RUNS_MEMBER",
    "PROVENANCE_PAYLOAD_VERSION",
    "STORED",
    "WAVEFORM_CACHE_PREFIX",
    "ManifestAsset",
    "ManifestMember",
    "ManifestProvenance",
    "MemberCategory",
    "PortableAsset",
    "PortableFormatError",
    "PortableManifest",
    "PortablePlan",
    "PortableWaveformCache",
    "asset_member_path",
    "asset_member_suffix",
    "build_portable_database",
    "category_for",
    "compression_for",
    "compression_name",
    "compute_portable_plan",
    "model_manifests_payload",
    "separation_runs_payload",
    "waveform_cache_member_prefix",
]
