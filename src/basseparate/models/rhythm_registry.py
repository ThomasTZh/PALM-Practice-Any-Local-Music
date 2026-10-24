"""Checked-in registry of separately installed rhythm models (M3.2, §4.2).

Beat This! is not bundled with the application: the user installs it
explicitly through the model-install boundary, or imports a verified
offline bundle. This registry is the source of truth for the pinned
adapter package, checkpoint identity, preprocessing, output semantics,
and licensing. Every hash and size was resolved from the official
artifacts on 2026-10-24; nothing here is a placeholder.

The module is import-safe in the main environment: no torch, no
beat_this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.ckpt$")

#: Stable basseparate model IDs. These are the IDs stored in rhythm run
#: records and exposed by the install API.
BEAT_THIS_FINAL0_ID = "beat_this_final0"
BEAT_THIS_SMALL0_ID = "beat_this_small0"

#: Adapter version implemented by the isolated rhythm runtime. Bumped
#: whenever preprocessing, frame mapping, or output interpretation
#: changes in a way that can alter results.
BEAT_THIS_ADAPTER_VERSION = "beat-this-adapter-v1"

#: Preprocessing profile (Beat This! LogMelSpect, pinned defaults).
BEAT_THIS_PREPROCESSING_PROFILE = "beat-this-logmel-22050-441-v1"
BEAT_THIS_PREPROCESSING_VERSION = 1

BEAT_THIS_SAMPLE_RATE = 22_050
BEAT_THIS_FRAME_HOP = 441
BEAT_THIS_FRAME_RATE = 50.0


class RhythmRegistryError(ValueError):
    """Raised when a rhythm model manifest violates the registry invariants."""


@dataclass(frozen=True, slots=True)
class RhythmCheckpoint:
    """One downloadable checkpoint artifact."""

    filename: str
    size_bytes: int
    sha256: str
    upstream_url: str


@dataclass(frozen=True, slots=True)
class RhythmModelManifest:
    """The complete, hash-pinned description of one rhythm model."""

    model_id: str
    display_name: str
    preset: str
    upstream_repository: str
    upstream_revision: str
    package_name: str
    package_version: str
    package_wheel_sha256: str
    checkpoint: RhythmCheckpoint
    adapter_version: str
    preprocessing_profile: str
    preprocessing_version: int
    input_sample_rate: int
    frame_hop: int
    frame_rate: float
    activation_dtype: str
    output_semantics: str
    device_capability: str
    code_license: str
    weights_license: str
    license_notice: str
    notices: tuple[str, ...]

    @property
    def total_size_bytes(self) -> int:
        return self.checkpoint.size_bytes


_LICENSE_NOTICE = (
    "Beat This! code and the published model weights are MIT licensed "
    "(CPJKU/beat_this LICENSE, Copyright (c) 2024 Institute of Computational "
    "Perception, JKU Linz). The upstream README states the published "
    "checkpoints are MIT; training annotations include fully copyrighted or "
    "limited Creative Commons material, so downstream users must assess "
    "training-data implications themselves. The checkpoint is downloaded "
    "only from the official CPJKU cloud space and its SHA-256 is verified "
    "against this registry before use."
)

_COMMON_NOTICES = (
    "Official implementation: CPJKU/beat_this, ISMIR 2024 paper "
    "'Beat This! Accurate Beat Tracking Without DBN Postprocessing'.",
    "Checkpoint format: PyTorch Lightning checkpoint with optimizer state "
    "stripped; inference converts it to vanilla BeatThis modules.",
    "Input: mono 22,050 Hz audio; the adapter resamples project audio itself. "
    "Output: two float32 framewise logit arrays at 50 fps (beat, downbeat); "
    "sigmoid gives probabilities. Frame f maps to source frame "
    "f * 441 * project_sample_rate / 22050.",
    "The application never downloads automatically. Installation is an "
    "explicit, offline-gated action; offline bundle import verifies the same "
    "hash and manifest identity.",
)


_BEAT_THIS_FINAL0 = RhythmModelManifest(
    model_id=BEAT_THIS_FINAL0_ID,
    display_name="Beat This! final0 (main beat/downbeat model)",
    preset="final0",
    upstream_repository="https://github.com/CPJKU/beat_this",
    upstream_revision=(
        "v1.1.0 (commit ad7974846029835307ba19a3d5cefbf40b243041); PyPI beat-this 1.1.0"
    ),
    package_name="beat-this",
    package_version="1.1.0",
    package_wheel_sha256="3f2b2d1e027c6dac380bf80c71555e3c28a4036a7f1af20129a945915a72a645",
    checkpoint=RhythmCheckpoint(
        filename="final0.ckpt",
        size_bytes=81_058_141,
        sha256="8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331",
        upstream_url="https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt",
    ),
    adapter_version=BEAT_THIS_ADAPTER_VERSION,
    preprocessing_profile=BEAT_THIS_PREPROCESSING_PROFILE,
    preprocessing_version=BEAT_THIS_PREPROCESSING_VERSION,
    input_sample_rate=BEAT_THIS_SAMPLE_RATE,
    frame_hop=BEAT_THIS_FRAME_HOP,
    frame_rate=BEAT_THIS_FRAME_RATE,
    activation_dtype="float32",
    output_semantics=(
        "framewise beat and downbeat logits (not probabilities) at 50 fps; "
        "sigmoid is applied by the decoder, never stored as if calibrated"
    ),
    device_capability="cpu; cuda when a qualified GPU and driver are available",
    code_license="MIT",
    weights_license="MIT",
    license_notice=_LICENSE_NOTICE,
    notices=_COMMON_NOTICES,
)


_BEAT_THIS_SMALL0 = RhythmModelManifest(
    model_id=BEAT_THIS_SMALL0_ID,
    display_name="Beat This! small0 (faster optional beat/downbeat model)",
    preset="small0",
    upstream_repository="https://github.com/CPJKU/beat_this",
    upstream_revision=(
        "v1.1.0 (commit ad7974846029835307ba19a3d5cefbf40b243041); PyPI beat-this 1.1.0"
    ),
    package_name="beat-this",
    package_version="1.1.0",
    package_wheel_sha256="3f2b2d1e027c6dac380bf80c71555e3c28a4036a7f1af20129a945915a72a645",
    checkpoint=RhythmCheckpoint(
        filename="small0.ckpt",
        size_bytes=8_451_101,
        sha256="6074be2c4d490c5f6101fcc374a1ec72ae93456e23bb6019783b849f5dc7d47b",
        upstream_url="https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/small0.ckpt",
    ),
    adapter_version=BEAT_THIS_ADAPTER_VERSION,
    preprocessing_profile=BEAT_THIS_PREPROCESSING_PROFILE,
    preprocessing_version=BEAT_THIS_PREPROCESSING_VERSION,
    input_sample_rate=BEAT_THIS_SAMPLE_RATE,
    frame_hop=BEAT_THIS_FRAME_HOP,
    frame_rate=BEAT_THIS_FRAME_RATE,
    activation_dtype="float32",
    output_semantics=(
        "framewise beat and downbeat logits (not probabilities) at 50 fps; "
        "sigmoid is applied by the decoder, never stored as if calibrated"
    ),
    device_capability="cpu; cuda when a qualified GPU and driver are available",
    code_license="MIT",
    weights_license="MIT",
    license_notice=_LICENSE_NOTICE,
    notices=_COMMON_NOTICES,
)


RHYTHM_MODELS: dict[str, RhythmModelManifest] = {}


def _validate_manifest(manifest: RhythmModelManifest) -> None:
    if not manifest.model_id:
        raise RhythmRegistryError("model_id must not be empty")
    if not manifest.preset:
        raise RhythmRegistryError(f"{manifest.model_id}: preset must not be empty")
    if not manifest.upstream_repository.startswith("https://"):
        raise RhythmRegistryError(f"{manifest.model_id}: upstream_repository must be https")
    if not _CHECKPOINT_NAME_RE.fullmatch(manifest.checkpoint.filename):
        raise RhythmRegistryError(
            f"{manifest.model_id}: checkpoint filename must be a plain .ckpt name"
        )
    if manifest.checkpoint.size_bytes <= 0:
        raise RhythmRegistryError(f"{manifest.model_id}: checkpoint size must be positive")
    if not _SHA256_RE.fullmatch(manifest.checkpoint.sha256):
        raise RhythmRegistryError(
            f"{manifest.model_id}: checkpoint sha256 must be 64 lowercase hex chars"
        )
    if not _SHA256_RE.fullmatch(manifest.package_wheel_sha256):
        raise RhythmRegistryError(
            f"{manifest.model_id}: package_wheel_sha256 must be 64 lowercase hex chars"
        )
    if not manifest.checkpoint.upstream_url.startswith("https://"):
        raise RhythmRegistryError(f"{manifest.model_id}: checkpoint upstream_url must be https")
    if manifest.input_sample_rate <= 0 or manifest.frame_hop <= 0:
        raise RhythmRegistryError(
            f"{manifest.model_id}: input sample rate and frame hop must be positive"
        )
    expected_rate = manifest.input_sample_rate / manifest.frame_hop
    if abs(expected_rate - manifest.frame_rate) > 1e-9:
        raise RhythmRegistryError(
            f"{manifest.model_id}: frame_rate must equal sample_rate / frame_hop"
        )
    if manifest.preprocessing_version < 1:
        raise RhythmRegistryError(f"{manifest.model_id}: preprocessing_version must be positive")
    if manifest.activation_dtype != "float32":
        raise RhythmRegistryError(
            f"{manifest.model_id}: only float32 activations are currently verified"
        )
    if not manifest.license_notice:
        raise RhythmRegistryError(f"{manifest.model_id}: license_notice is required")
    if not manifest.notices:
        raise RhythmRegistryError(f"{manifest.model_id}: notices must not be empty")


def _register(manifest: RhythmModelManifest) -> None:
    _validate_manifest(manifest)
    if manifest.model_id in RHYTHM_MODELS:
        raise RhythmRegistryError(f"duplicate rhythm model_id {manifest.model_id!r}")
    RHYTHM_MODELS[manifest.model_id] = manifest


_register(_BEAT_THIS_FINAL0)
_register(_BEAT_THIS_SMALL0)


def rhythm_manifest_hash(manifest: RhythmModelManifest) -> str:
    """Deterministic identity of one rhythm model manifest."""
    import hashlib
    import json

    payload = {
        "model_id": manifest.model_id,
        "preset": manifest.preset,
        "upstream_repository": manifest.upstream_repository,
        "upstream_revision": manifest.upstream_revision,
        "package_name": manifest.package_name,
        "package_version": manifest.package_version,
        "package_wheel_sha256": manifest.package_wheel_sha256,
        "checkpoint": {
            "filename": manifest.checkpoint.filename,
            "size_bytes": manifest.checkpoint.size_bytes,
            "sha256": manifest.checkpoint.sha256,
        },
        "adapter_version": manifest.adapter_version,
        "preprocessing_profile": manifest.preprocessing_profile,
        "preprocessing_version": manifest.preprocessing_version,
        "input_sample_rate": manifest.input_sample_rate,
        "frame_hop": manifest.frame_hop,
        "activation_dtype": manifest.activation_dtype,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_rhythm_model(model_id: str) -> RhythmModelManifest:
    """Look up a rhythm model by its stable basseparate ID."""
    try:
        return RHYTHM_MODELS[model_id]
    except KeyError:
        raise KeyError(f"no rhythm model registered with id {model_id!r}") from None


def list_rhythm_models() -> tuple[RhythmModelManifest, ...]:
    """All registered rhythm models in stable ID order."""
    return tuple(RHYTHM_MODELS[key] for key in sorted(RHYTHM_MODELS))
