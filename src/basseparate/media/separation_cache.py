"""Analysis cache key and cache lookup (M2.7, milestone2.md §9.1–9.2).

A separation request is identified by a deterministic cache key: the
same source, model, engine, parameters, and output profile always
produces the same key, so an identical request can be served from an
existing valid result set instead of re-running the model.

The key is pure and versioned: a ``CACHE_KEY_VERSION`` prefix makes any
payload-format change a clean miss (old keys stop matching) instead of
a silent collision. Serialization is canonical
(``sort_keys``, compact separators, ASCII) before the SHA-256.

The lookup verifies the cached result is actually usable: every stem
asset (plus the Bass + Others residual when present) must exist with
exactly the expected byte count (``frames × channels × 4``) — a
short/partial file is a miss, never a hit (§9.2.2, §9.2.5). The fast
path trusts the content-addressed filename plus the size check;
``verify_hashes`` adds a full re-hash against the recorded content hash
for when integrity is in doubt (§9.2.3).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from basseparate.domain.asset import AssetRecord
from basseparate.domain.preparation import DownmixSpec
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SourceIdentity,
)
from basseparate.storage.repository import ProjectRepository, SeparationRepository

#: Version of the cache-key payload format. Bump when the payload shape
#: changes: existing keys then simply stop matching (clean miss).
CACHE_KEY_VERSION = "v1"

#: Read size for the optional re-hash pass.
_HASH_CHUNK_BYTES = 1024 * 1024


def compute_cache_key(
    *,
    source: SourceIdentity,
    reference_mix: ReferenceMixIdentity,
    downmix: DownmixSpec | None,
    model_manifest_id: str,
    model_artifact_hashes: Mapping[str, str],
    engine_version: str,
    adapter_version: str,
    mode: SeparationMode,
    requested_parameters: dict[str, Any],
    effective_parameters: dict[str, Any] | None,
    random_seed: int,
    device_type: DeviceType,
    output_sample_rate: int,
    output_channel_count: int,
) -> str:
    """Deterministic SHA-256 key of a separation request (§9.1, §9.3).

    The ``parameters`` entry is the **effective** parameter dict when the
    run recorded one (memory recovery), else the requested dict — a
    recovered result is stored under the key of the profile it actually
    used, never mislabeled as the requested one (§9.3).

    ``device_type`` is the execution profile (cpu vs cuda), not a
    specific GPU identity: the float32/TF32 pin (M2.5) makes results
    reusable across devices of the same profile, so ``gpu_uuid`` is
    deliberately excluded.
    """
    payload: dict[str, Any] = {
        "version": CACHE_KEY_VERSION,
        "source": {
            "hash": source.source_hash,
            "sample_rate": source.sample_rate,
            "duration_frames": source.duration_frames,
        },
        "reference_mix": {
            "hash": reference_mix.hash,
            "transformation_hash": reference_mix.transformation_hash,
        },
        "downmix": downmix.model_dump(mode="json") if downmix is not None else None,
        "model": {
            "manifest_id": model_manifest_id,
            "artifact_hashes": dict(model_artifact_hashes),
        },
        "engine_version": engine_version,
        "adapter_version": adapter_version,
        "mode": mode,
        "parameters": (
            effective_parameters
            if effective_parameters is not None
            else requested_parameters
        ),
        "random_seed": random_seed,
        "device_profile": device_type.value,
        "output": {
            "sample_rate": output_sample_rate,
            "channel_count": output_channel_count,
        },
    }
    try:
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cache key payload is not JSON-serializable: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _expected_stem_bytes(frame_count: int, channel_count: int) -> int:
    """Exact byte size of interleaved f32le PCM (``frames × channels × 4``)."""
    return frame_count * channel_count * 4


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_usable(
    asset: AssetRecord,
    storage_root: Path,
    expected_bytes: int,
    verify_hash: bool,
) -> bool:
    """Exist + exact size (+ optional re-hash) of one cached asset.

    A missing file, a size mismatch (partial write), or a hash mismatch
    is a miss — the caller rebuilds the result set.
    """
    if asset.byte_count != expected_bytes:
        return False
    path = storage_root / asset.relative_path
    if not path.is_file():
        return False
    if path.stat().st_size != expected_bytes:
        return False
    if verify_hash:
        return _sha256_file(path) == asset.content_hash
    return True


def lookup_cached_result(
    *,
    project_id: uuid.UUID,
    cache_key: str,
    storage_root: Path,
    separation_repository: SeparationRepository,
    asset_repository: ProjectRepository,
    verify_hashes: bool = False,
) -> SeparationResultSet | None:
    """Return the project's valid result set for a cache key, if usable.

    Steps (§9.2.1–9.2.4): find the newest ``valid`` result set for
    (project, key); resolve every stem asset and the Bass + Others
    residual (when present); require each file to exist with exactly
    the expected byte count; optionally re-hash. Any miss returns
    ``None`` — the caller schedules a (re)run.
    """
    result_set = separation_repository.find_valid_result_set(project_id, cache_key)
    if result_set is None:
        return None
    stems = separation_repository.list_stems_for_result_set(result_set.id)
    if not stems:
        return None
    for stem in stems:
        asset = asset_repository.get_asset(stem.audio_asset_id)
        if asset is None:
            return None
        expected = _expected_stem_bytes(stem.frame_count, stem.channel_count)
        if not _asset_usable(asset, storage_root, expected, verify_hashes):
            return None
    if result_set.bass_residual_asset_id is not None:
        residual = asset_repository.get_asset(result_set.bass_residual_asset_id)
        if residual is None:
            return None
        expected = _expected_stem_bytes(
            result_set.output_frame_count, result_set.output_channel_count
        )
        if not _asset_usable(residual, storage_root, expected, verify_hashes):
            return None
    return result_set
