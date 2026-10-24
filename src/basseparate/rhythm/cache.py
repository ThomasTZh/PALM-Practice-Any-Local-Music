"""Analysis cache identities for the rhythm pipeline (M3.18 §20.1-§20.4).

Keys are deterministic SHA-256 identities over exact inputs/profiles, so
changing one stage invalidates only that stage and its dependants.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from basseparate.domain.rhythm_decode import BeatDecoderProfile
from basseparate.domain.rhythm_input import RhythmInputProfile


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def activation_cache_key(
    *,
    source_hash: str,
    input_role: str,
    input_profile: RhythmInputProfile,
    model_id: str,
    model_manifest_hash: str,
    adapter_version: str,
    precision: str = "float32",
    analysis_interval_frames: int | None = None,
) -> str:
    return _hash(
        {
            "stage": "activation",
            "source_hash": source_hash,
            "input_role": input_role,
            "input_profile": input_profile.model_dump(mode="json"),
            "model_id": model_id,
            "model_manifest_hash": model_manifest_hash,
            "adapter_version": adapter_version,
            "precision": precision,
            "interval": analysis_interval_frames,
        }
    )


def decoder_cache_key(*, activation_content_hash: str, decoder_profile: BeatDecoderProfile) -> str:
    return _hash(
        {
            "stage": "decoder",
            "activation_content_hash": activation_content_hash,
            "decoder": decoder_profile.model_dump(mode="json"),
        }
    )


def tempo_cache_key(
    *,
    decoded_content_hash: str,
    algorithm_version: int,
    pulse_unit_profile: str,
    meter_evidence_hash: str | None = None,
) -> str:
    return _hash(
        {
            "stage": "tempo_map",
            "decoded_content_hash": decoded_content_hash,
            "algorithm_version": algorithm_version,
            "pulse_unit_profile": pulse_unit_profile,
            "meter_evidence_hash": meter_evidence_hash,
        }
    )


def meter_cache_key(
    *,
    decoded_content_hash: str,
    tempo_identity: str,
    feature_artifact_hash: str,
    candidate_profile_version: int,
    transition_profile: str,
) -> str:
    return _hash(
        {
            "stage": "meter",
            "decoded_content_hash": decoded_content_hash,
            "tempo_identity": tempo_identity,
            "feature_artifact_hash": feature_artifact_hash,
            "candidate_profile_version": candidate_profile_version,
            "transition_profile": transition_profile,
        }
    )
