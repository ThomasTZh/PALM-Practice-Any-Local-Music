"""Checked-in registry of bundled inference models.

The registry is the source of truth for the hash-pinned bundled Demucs
baseline (spec §5.1): exact artifact names, sizes, SHA-256 hashes,
upstream provenance URLs, input/output requirements, and license notices.
All hashes and sizes were resolved and verified during implementation
(2026-10-10); nothing here is a placeholder.

This module is import-safe in the main environment: no torch, no demucs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ArtifactRole = Literal["preset_config", "checkpoint"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RegistryError(ValueError):
    """Raised when a manifest violates the registry invariants."""


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """One artifact of a bundled model (checkpoint or preset config)."""

    name: str
    role: ArtifactRole
    size_bytes: int
    sha256: str
    upstream_url: str


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """The complete, hash-pinned description of one bundled model preset."""

    model_id: str
    display_name: str
    engine_requirement: str
    upstream_revision: str
    artifacts: tuple[ArtifactSpec, ...]
    input_sample_rate: int
    input_channels: int
    output_labels: tuple[str, ...]
    license_notice: str
    notices: tuple[str, ...]
    bundle_prefix: str

    def artifact(self, name: str) -> ArtifactSpec:
        for spec in self.artifacts:
            if spec.name == name:
                return spec
        raise KeyError(name)

    @property
    def total_size_bytes(self) -> int:
        return sum(spec.size_bytes for spec in self.artifacts)


def _validate_manifest(manifest: ModelManifest) -> None:
    if not manifest.model_id:
        raise RegistryError("model_id must not be empty")
    if not manifest.bundle_prefix:
        raise RegistryError(f"{manifest.model_id}: bundle_prefix must not be empty")
    if any(part in {"", ".", ".."} for part in manifest.bundle_prefix.split("/")):
        raise RegistryError(
            f"{manifest.model_id}: bundle_prefix must be a relative path without traversal"
        )
    if not manifest.artifacts:
        raise RegistryError(f"{manifest.model_id}: a manifest needs at least one artifact")
    seen: set[str] = set()
    for spec in manifest.artifacts:
        if not _ARTIFACT_NAME_RE.fullmatch(spec.name) or "/" in spec.name:
            raise RegistryError(
                f"{manifest.model_id}: artifact name {spec.name!r} is not a plain file name"
            )
        if spec.name in seen:
            raise RegistryError(f"{manifest.model_id}: duplicate artifact name {spec.name!r}")
        seen.add(spec.name)
        if spec.size_bytes <= 0:
            raise RegistryError(f"{manifest.model_id}: {spec.name} size must be positive")
        if not _SHA256_RE.fullmatch(spec.sha256):
            raise RegistryError(
                f"{manifest.model_id}: {spec.name} sha256 must be 64 lowercase hex chars"
            )
        if not spec.upstream_url.startswith(("https://",)):
            raise RegistryError(f"{manifest.model_id}: {spec.name} upstream_url must be https")
    if manifest.input_sample_rate <= 0 or manifest.input_channels <= 0:
        raise RegistryError(f"{manifest.model_id}: input requirements must be positive")
    if not manifest.output_labels:
        raise RegistryError(f"{manifest.model_id}: output_labels must not be empty")
    if len(set(manifest.output_labels)) != len(manifest.output_labels):
        raise RegistryError(f"{manifest.model_id}: duplicate output label")


_DEMUCS_LICENSE_NOTICE = (
    "Demucs code is MIT licensed (LICENSE in the demucs repository, "
    "Copyright (c) Meta Platforms, Inc. and affiliates). The bundled "
    "checkpoints are the official demucs model weights distributed by Meta "
    "AI; no explicit license statement for the weights was found in the "
    "demucs README, the LICENSE file, or the Hugging Face model card "
    "(checked 2026-10-10). Weight terms are not assumed; provenance is "
    "recorded per artifact."
)

_HTDEMUCS_FT = ModelManifest(
    model_id="htdemucs_ft",
    display_name="Hybrid Transformer Demucs (fine-tuned 4-model ensemble)",
    engine_requirement=(
        "demucs 4.1.0 with torch >= 2.1 in the locked analysis environment "
        "(see analysis/uv.lock); inference only, no training"
    ),
    upstream_revision=(
        "preset config: demucs 4.1.0 sdist, demucs/remote/htdemucs_ft.yaml, "
        "byte-identical to upstream main on 2026-10-10; checkpoints: official "
        "demucs hybrid_transformer release on dl.fbaipublicfiles.com"
    ),
    artifacts=(
        ArtifactSpec(
            name="htdemucs_ft.yaml",
            role="preset_config",
            size_bytes=149,
            sha256="69470b8c1bbd674437b51bc9fb491327a10ab0396b702c93389b9cf750016346",
            upstream_url=(
                "https://github.com/adefossez/demucs/blob/main/demucs/remote/htdemucs_ft.yaml"
            ),
        ),
        ArtifactSpec(
            name="f7e0c4bc-ba3fe64a.th",
            role="checkpoint",
            size_bytes=84141271,
            sha256="ba3fe64ae8ef66ac9a4857222ce48efbdc5eb3ad375cb79dd13debee5aaa4066",
            upstream_url=(
                "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/f7e0c4bc-ba3fe64a.th"
            ),
        ),
        ArtifactSpec(
            name="d12395a8-e57c48e6.th",
            role="checkpoint",
            size_bytes=84141271,
            sha256="e57c48e6b0e38af4f7118d7bd08c49f0a0c0edf7d09143bdd902ea0d237303e6",
            upstream_url=(
                "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/d12395a8-e57c48e6.th"
            ),
        ),
        ArtifactSpec(
            name="92cfc3b6-ef3bcb9c.th",
            role="checkpoint",
            size_bytes=84141271,
            sha256="ef3bcb9c8b40d14ae5d51b6db2587339cc12c6b77c0be151ce6d69002e087bf2",
            upstream_url=(
                "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/92cfc3b6-ef3bcb9c.th"
            ),
        ),
        ArtifactSpec(
            name="04573f0d-f3cf25b2.th",
            role="checkpoint",
            size_bytes=84141271,
            sha256="f3cf25b222c4eed7cd49dd8b2c9597d50c18bd154090f7b919cfa5f93cf22c49",
            upstream_url=(
                "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th"
            ),
        ),
    ),
    input_sample_rate=44100,
    input_channels=2,
    output_labels=("drums", "bass", "other", "vocals"),
    license_notice=_DEMUCS_LICENSE_NOTICE,
    notices=(
        "htdemucs_ft is a bag of 4 models whose outputs are combined with the "
        "per-source weights in htdemucs_ft.yaml (identity ensemble: one "
        "component per source).",
        "Component signatures: f7e0c4bc, d12395a8, 92cfc3b6, 04573f0d. Each "
        "checkpoint file name embeds the first 8 hex characters of its "
        "SHA-256, matching demucs' built-in checksum format.",
        "Model: Hybrid Transformer Demucs, arXiv:2111.03600; weights trained "
        "by Meta AI and distributed via the official demucs channels "
        "(dl.fbaipublicfiles.com, huggingface.co/adefossez).",
    ),
    bundle_prefix="models/htdemucs_ft",
)

REGISTRY: dict[str, ModelManifest] = {}


def _register(manifest: ModelManifest) -> None:
    _validate_manifest(manifest)
    if manifest.model_id in REGISTRY:
        raise RegistryError(f"duplicate model_id {manifest.model_id!r}")
    REGISTRY[manifest.model_id] = manifest


_register(_HTDEMUCS_FT)


def get_manifest(model_id: str) -> ModelManifest:
    try:
        return REGISTRY[model_id]
    except KeyError:
        raise KeyError(f"no bundled model registered with id {model_id!r}") from None
