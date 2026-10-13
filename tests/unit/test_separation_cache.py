"""Unit tests for the deterministic separation cache key (M2.7, §9.1, §9.3)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

import pytest

from basseparate.domain.preparation import DownmixSpec
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SourceIdentity,
)
from basseparate.media import separation_cache
from basseparate.media.separation_cache import compute_cache_key

Inputs = Callable[[], dict[str, object]]


def _inputs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source": SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=48_000,
            duration_frames=48_000,
        ),
        "reference_mix": ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash="cd" * 32, transformation_hash="ef" * 32
        ),
        "downmix": None,
        "model_manifest_id": str(uuid.uuid4()),
        "model_artifact_hashes": {"convolutions.th": "11" * 32, "tensors.th": "22" * 32},
        "engine_version": "demucs-4.1.0",
        "adapter_version": "outer-window-v1",
        "mode": SeparationMode.FOUR_STEMS,
        "requested_parameters": {"segment": 384_000, "shift": 120_000},
        "effective_parameters": None,
        "random_seed": 0,
        "device_type": DeviceType.CPU,
        "output_sample_rate": 48_000,
        "output_channel_count": 2,
    }
    base.update(overrides)
    return base


def _source(hash: str = "ab" * 32, rate: int = 48_000, duration: int = 48_000) -> SourceIdentity:
    return SourceIdentity(
        asset_id=uuid.uuid4(), source_hash=hash, sample_rate=rate, duration_frames=duration
    )


def _reference(hash: str = "cd" * 32, transform: str = "ef" * 32) -> ReferenceMixIdentity:
    return ReferenceMixIdentity(
        asset_id=uuid.uuid4(), hash=hash, transformation_hash=transform
    )


def test_key_is_sha256_hex() -> None:
    key = compute_cache_key(**_inputs())
    assert re.fullmatch(r"[0-9a-f]{64}", key) is not None


def test_key_is_deterministic_and_order_independent() -> None:
    inputs = _inputs()
    first = compute_cache_key(**inputs)
    assert compute_cache_key(**inputs) == first
    # Dict insertion order must not matter (canonical serialization).
    reordered = {
        **inputs,
        "model_artifact_hashes": {"tensors.th": "22" * 32, "convolutions.th": "11" * 32},
    }
    assert compute_cache_key(**reordered) == first


def test_asset_ids_are_not_part_of_the_key() -> None:
    """The key identifies the request, not the project's asset rows."""
    base = _inputs()
    source = base["source"]
    reference = base["reference_mix"]
    assert isinstance(source, SourceIdentity)
    assert isinstance(reference, ReferenceMixIdentity)
    key_a = compute_cache_key(**base)
    key_b = compute_cache_key(
        **{
            **base,
            "source": source.model_copy(update={"asset_id": uuid.uuid4()}),
            "reference_mix": reference.model_copy(update={"asset_id": uuid.uuid4()}),
        }
    )
    assert key_a == key_b


@pytest.mark.parametrize(
    "override",
    [
        lambda: _inputs(source=_source(hash="ba" * 32)),
        lambda: _inputs(source=_source(rate=44_100)),
        lambda: _inputs(source=_source(duration=96_000)),
        lambda: _inputs(reference_mix=_reference(hash="dc" * 32)),
        lambda: _inputs(reference_mix=_reference(transform="fe" * 32)),
        lambda: _inputs(downmix=DownmixSpec(mode="standard_5_1")),
        lambda: _inputs(model_manifest_id="2" * 32),
        lambda: _inputs(
            model_artifact_hashes={"convolutions.th": "33" * 32, "tensors.th": "22" * 32}
        ),
        lambda: _inputs(model_artifact_hashes={"conv_th": "11" * 32, "tensors.th": "22" * 32}),
        lambda: _inputs(engine_version="demucs-4.2.0"),
        lambda: _inputs(adapter_version="outer-window-v2"),
        lambda: _inputs(mode=SeparationMode.BASS_PAIR),
        lambda: _inputs(requested_parameters={"segment": 192_000, "shift": 60_000}),
        lambda: _inputs(random_seed=42),
        lambda: _inputs(device_type=DeviceType.CUDA),
        lambda: _inputs(output_sample_rate=44_100),
        lambda: _inputs(output_channel_count=1),
    ],
    ids=[
        "source_hash",
        "source_rate",
        "source_duration",
        "reference_hash",
        "reference_transformation",
        "downmix",
        "manifest_id",
        "artifact_hash",
        "artifact_name",
        "engine_version",
        "adapter_version",
        "mode",
        "parameters",
        "seed",
        "device_profile",
        "output_rate",
        "output_channels",
    ],
)
def test_each_input_changes_the_key(override: Inputs) -> None:
    base_key = compute_cache_key(**_inputs())
    assert compute_cache_key(**override()) != base_key


def test_effective_parameters_take_precedence() -> None:
    """§9.3: a recovered result is keyed by the profile it actually used."""
    requested = {"segment": 384_000, "shift": 120_000}
    effective = {"segment": 192_000, "shift": 60_000}
    base = _inputs(requested_parameters=requested)
    recovered = compute_cache_key(**{**base, "effective_parameters": effective})
    labeled_as_effective = compute_cache_key(
        **{**base, "requested_parameters": effective, "effective_parameters": None}
    )
    labeled_as_requested = compute_cache_key(**base)
    assert recovered == labeled_as_effective
    assert recovered != labeled_as_requested


def test_identical_effective_and_requested_share_a_key() -> None:
    params = {"segment": 384_000, "shift": 120_000}
    base = _inputs(requested_parameters=params)
    with_effective = compute_cache_key(**{**base, "effective_parameters": params})
    without = compute_cache_key(**base)
    assert with_effective == without


def test_gpu_identity_is_excluded() -> None:
    """Same device profile, different GPU: the float32 pin makes results
    reusable, so the key must not depend on a specific GPU. The key has no
    GPU input at all; only the profile (cpu vs cuda) matters."""
    base = _inputs()
    cuda = compute_cache_key(**{**base, "device_type": DeviceType.CUDA})
    assert compute_cache_key(**{**base, "device_type": DeviceType.CUDA}) == cuda
    assert cuda != compute_cache_key(**base)


def test_key_version_prefix_changes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _inputs()
    base_key = compute_cache_key(**inputs)
    monkeypatch.setattr(separation_cache, "CACHE_KEY_VERSION", "v2")
    assert compute_cache_key(**inputs) != base_key


def test_non_serializable_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="not JSON-serializable"):
        compute_cache_key(**_inputs(requested_parameters={"segment": object()}))
