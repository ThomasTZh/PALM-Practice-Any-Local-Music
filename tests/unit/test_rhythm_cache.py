"""Rhythm analysis cache identities (M3.18 §20.1-§20.4)."""

from __future__ import annotations

from basseparate.domain.rhythm_decode import BEAT_THIS_DECODER_PROFILE
from basseparate.domain.rhythm_input import BEAT_THIS_INPUT_PROFILE
from basseparate.rhythm.cache import (
    activation_cache_key,
    decoder_cache_key,
    meter_cache_key,
    tempo_cache_key,
)


def _activation(**overrides):
    values = {
        "source_hash": "ab" * 32,
        "input_role": "original_mix",
        "input_profile": BEAT_THIS_INPUT_PROFILE,
        "model_id": "beat_this_final0",
        "model_manifest_hash": "cd" * 32,
        "adapter_version": "beat-this-adapter-v1",
        "precision": "float32",
        "analysis_interval_frames": None,
    }
    values.update(overrides)
    return activation_cache_key(**values)


def test_activation_key_is_stable_and_sensitive() -> None:
    key = _activation()
    assert key == _activation()
    assert key != _activation(model_manifest_hash="ef" * 32)
    assert key != _activation(precision="float16")
    assert key != _activation(adapter_version="other")


def test_decoder_key_isolated_from_activation() -> None:
    base = decoder_cache_key(
        activation_content_hash="ab" * 32, decoder_profile=BEAT_THIS_DECODER_PROFILE
    )
    assert base == decoder_cache_key(
        activation_content_hash="ab" * 32, decoder_profile=BEAT_THIS_DECODER_PROFILE
    )
    assert base != decoder_cache_key(
        activation_content_hash="cd" * 32, decoder_profile=BEAT_THIS_DECODER_PROFILE
    )


def test_tempo_and_meter_keys_include_dependencies() -> None:
    tempo = tempo_cache_key(
        decoded_content_hash="ab" * 32,
        algorithm_version=1,
        pulse_unit_profile="quarter",
    )
    assert tempo != tempo_cache_key(
        decoded_content_hash="ab" * 32,
        algorithm_version=2,
        pulse_unit_profile="quarter",
    )
    meter = meter_cache_key(
        decoded_content_hash="ab" * 32,
        tempo_identity=tempo,
        feature_artifact_hash="cd" * 32,
        candidate_profile_version=1,
        transition_profile="v1",
    )
    assert meter != meter_cache_key(
        decoded_content_hash="ab" * 32,
        tempo_identity=tempo,
        feature_artifact_hash="ef" * 32,
        candidate_profile_version=1,
        transition_profile="v1",
    )
