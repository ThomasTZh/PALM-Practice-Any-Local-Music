"""Separation request planning (M2.17, spec §3.2, §6.1, §9.1).

Pure helpers shared by the runs route, the dispatch-time preparation
builder, and the publisher:

- the reference mix for a project (§6.1): canonical stereo/mono PCM, or
  the explicit M1 stereo downmix for a multichannel source;
- the deterministic transform identity and §9.1 cache key, computed at
  request time from project/asset/model identity (no file I/O);
- the versioned model identity and the requested quality parameters
  (the analysis worker receives exactly these values).

The app environment never imports torch here; model facts come from the
checked-in registry.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from basseparate.domain.asset import AssetRecord
from basseparate.domain.device import DeviceKind, DeviceRecord
from basseparate.domain.preparation import DownmixSpec, ReferenceMixPlan
from basseparate.domain.project import ProjectRecord
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SourceIdentity,
)
from basseparate.media.preparation import transform_identity_hash
from basseparate.media.separation_cache import compute_cache_key
from basseparate.models.registry import REGISTRY, ModelManifest

#: The bundled baseline (spec §5.1, §7.1).
SEPARATION_MODEL_ID = "htdemucs_ft"
#: Engine/adapter identity recorded on every run and in the cache key.
SEPARATION_ENGINE_VERSION = "demucs-4.1.0"
SEPARATION_ADAPTER_VERSION = "outer-window-v1"
#: Initial quality parameters (spec §7.1); the analysis worker receives
#: these explicitly so the cache key and the actual run always agree.
SEPARATION_SHIFTS = 2
SEPARATION_INTERNAL_OVERLAP = 0.5
SEPARATION_SEGMENT_SECONDS = 7.5
SEPARATION_WINDOW_SECONDS = 120.0
SEPARATION_OVERLAP_SECONDS = 8.0
SEPARATION_DEFAULT_SEED = 0


class SeparationRequestError(ValueError):
    """The project cannot form a valid separation request."""


def model_manifest() -> ModelManifest:
    """The bundled model manifest from the checked-in registry."""
    return REGISTRY[SEPARATION_MODEL_ID]


def model_manifest_id(manifest: ModelManifest) -> uuid.UUID:
    """Stable UUID identity of one model manifest (spec §3.2)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"basseparate:model:{manifest.model_id}")


def model_manifest_hash(manifest: ModelManifest) -> str:
    """Content hash of the manifest's identity and artifact hashes."""
    payload = {
        "model_id": manifest.model_id,
        "upstream_revision": manifest.upstream_revision,
        "artifacts": {artifact.name: artifact.sha256 for artifact in manifest.artifacts},
        "input_sample_rate": manifest.input_sample_rate,
        "input_channels": manifest.input_channels,
        "output_labels": list(manifest.output_labels),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def requested_parameters() -> dict[str, Any]:
    """The requested quality parameters recorded on the run (spec §7.1)."""
    return {
        "preset": SEPARATION_MODEL_ID,
        "shifts": SEPARATION_SHIFTS,
        "internal_overlap": SEPARATION_INTERNAL_OVERLAP,
        "segment_seconds": SEPARATION_SEGMENT_SECONDS,
        "window_seconds": SEPARATION_WINDOW_SECONDS,
        "overlap_seconds": SEPARATION_OVERLAP_SECONDS,
    }


def reference_mix_plan(
    project: ProjectRecord,
    canonical: AssetRecord | None,
    monitoring: AssetRecord | None,
) -> ReferenceMixPlan:
    """Resolve the reference mix for one project (spec §6.1).

    Stereo and mono sources use the canonical PCM; a multichannel source
    uses the explicit M1 stereo monitoring downmix and records whether it
    was the standard 5.1 matrix or a manual channel selection. The UI must
    present a multichannel separation as a separation of that downmix.
    """
    channels = project.source_channel_count
    if channels is None:
        raise SeparationRequestError("the project has no source channel count")
    if project.sample_rate is None or project.duration_frames is None:
        raise SeparationRequestError("the project has no source timing")
    canonical_audio = canonical.audio if canonical is not None else None
    if canonical is None or canonical_audio is None:
        raise SeparationRequestError("the project has no canonical audio asset")
    if canonical_audio.sample_rate != project.sample_rate:
        raise SeparationRequestError(
            "the canonical audio rate does not match the project rate"
        )
    if channels == 1:
        return ReferenceMixPlan(
            kind="mono",
            asset_id=canonical.id,
            source_hash=canonical.content_hash,
        )
    if channels == 2:
        return ReferenceMixPlan(
            kind="stereo",
            asset_id=canonical.id,
            source_hash=canonical.content_hash,
        )
    if monitoring is None or monitoring.audio is None:
        raise SeparationRequestError(
            "a multichannel project needs its stereo monitoring downmix before separation"
        )
    if (
        project.monitoring_left_channel is not None
        and project.monitoring_right_channel is not None
    ):
        downmix = DownmixSpec(
            mode="manual",
            left_channel=project.monitoring_left_channel,
            right_channel=project.monitoring_right_channel,
        )
    elif channels == 6:
        downmix = DownmixSpec(mode="standard_5_1")
    else:
        raise SeparationRequestError(
            "the multichannel source has no explicit stereo downmix selection"
        )
    return ReferenceMixPlan(
        kind="multichannel",
        asset_id=monitoring.id,
        source_hash=monitoring.content_hash,
        downmix=downmix,
    )


def source_identity(project: ProjectRecord, plan: ReferenceMixPlan) -> SourceIdentity:
    """The run/result source identity: the reference asset and geometry."""
    if project.sample_rate is None or project.duration_frames is None:
        raise SeparationRequestError("the project has no source timing")
    return SourceIdentity(
        asset_id=plan.asset_id,
        source_hash=plan.source_hash,
        sample_rate=project.sample_rate,
        duration_frames=project.duration_frames,
    )


def output_channel_count(plan: ReferenceMixPlan) -> int:
    """Published stem channel count: mono stays mono; stereo/downmix are 2."""
    return 1 if plan.kind == "mono" else 2


def request_cache_key(
    *,
    project: ProjectRecord,
    plan: ReferenceMixPlan,
    manifest: ModelManifest,
    mode: SeparationMode,
    seed: int,
    device_type: DeviceType,
    parameters: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """The §9.1 cache key and the §6.2 transform identity.

    Both are pure functions of the source, reference transform, model
    identity, parameters, seed, device profile, and output geometry, so
    an identical request is recognized before any file is prepared.
    """
    transform_hash = transform_identity_hash(plan, manifest.input_sample_rate)
    reference = ReferenceMixIdentity(
        asset_id=plan.asset_id,
        hash=plan.source_hash,
        transformation_hash=transform_hash,
    )
    source = source_identity(project, plan)
    cache_key = compute_cache_key(
        source=source,
        reference_mix=reference,
        downmix=plan.downmix,
        model_manifest_id=str(model_manifest_id(manifest)),
        model_artifact_hashes={
            artifact.name: artifact.sha256 for artifact in manifest.artifacts
        },
        engine_version=SEPARATION_ENGINE_VERSION,
        adapter_version=SEPARATION_ADAPTER_VERSION,
        mode=mode,
        requested_parameters=parameters or requested_parameters(),
        effective_parameters=None,
        random_seed=seed,
        device_type=device_type,
        output_sample_rate=source.sample_rate,
        output_channel_count=output_channel_count(plan),
    )
    return cache_key, transform_hash


def device_profile(record: DeviceRecord) -> tuple[DeviceType, str | None]:
    """The run's device type and GPU UUID from a selected device (§4.4)."""
    if record.kind is DeviceKind.CPU:
        return DeviceType.CPU, None
    return DeviceType.CUDA, record.identifier
