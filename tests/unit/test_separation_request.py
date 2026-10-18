"""Separation request planning (M2.17, spec §3.2, §6.1, §9.1).

Pure reference-mix selection, model identity, device profile, and cache
key determinism — no file I/O, no torch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.device import DeviceKind, DeviceRecord, QualificationStatus
from basseparate.domain.project import ProjectRecord, ProjectStatus
from basseparate.domain.separation import DeviceType, SeparationMode
from basseparate.media.separation_request import (
    SeparationRequestError,
    device_profile,
    model_manifest,
    model_manifest_hash,
    model_manifest_id,
    output_channel_count,
    reference_mix_plan,
    request_cache_key,
)

NOW = datetime.now(UTC)


def _asset(hash_char: str, *, sample_rate: int = 48_000, channels: int = 2) -> AssetRecord:
    return AssetRecord(
        id=uuid.uuid4(),
        content_hash=hash_char * 64,
        role=AssetRole.SOURCE_PCM,
        relative_path=f"data/assets/{hash_char * 64}.pcm",
        media_type="application/octet-stream",
        byte_count=100 * channels * 4,
        created_at=NOW,
        audio=AudioMetadata(
            sample_rate=sample_rate,
            channel_count=channels,
            frame_count=100,
            sample_format="f32le",
        ),
    )


def _project(
    *,
    channels: int = 2,
    canonical: AssetRecord | None = None,
    monitoring: AssetRecord | None = None,
    left: int | None = None,
    right: int | None = None,
) -> ProjectRecord:
    return ProjectRecord(
        id=uuid.uuid4(),
        name="Song",
        created_at=NOW,
        updated_at=NOW,
        revision=1,
        status=ProjectStatus.READY,
        source_asset_id=uuid.uuid4(),
        canonical_asset_id=canonical.id if canonical else None,
        monitoring_asset_id=monitoring.id if monitoring else None,
        sample_rate=48_000,
        duration_frames=100,
        source_channel_count=channels,
        source_stream_index=0,
        source_channel_layout={1: "mono", 2: "stereo", 6: "5.1"}.get(
            channels, f"{channels} channels"
        ),
        decode_profile_version=1,
        monitoring_left_channel=left,
        monitoring_right_channel=right,
    )


class TestReferenceMix:
    def test_stereo_uses_the_canonical_asset(self) -> None:
        canonical = _asset("a", channels=2)
        plan = reference_mix_plan(_project(canonical=canonical), canonical, None)
        assert plan.kind == "stereo"
        assert plan.asset_id == canonical.id
        assert plan.source_hash == canonical.content_hash
        assert plan.downmix is None
        assert output_channel_count(plan) == 2

    def test_mono_uses_the_canonical_asset(self) -> None:
        canonical = _asset("b", channels=1)
        plan = reference_mix_plan(_project(channels=1, canonical=canonical), canonical, None)
        assert plan.kind == "mono"
        assert output_channel_count(plan) == 1

    def test_surround_uses_the_monitoring_downmix(self) -> None:
        canonical = _asset("c", channels=6)
        monitoring = _asset("d", channels=2)
        plan = reference_mix_plan(
            _project(channels=6, canonical=canonical, monitoring=monitoring),
            canonical,
            monitoring,
        )
        assert plan.kind == "multichannel"
        assert plan.asset_id == monitoring.id
        assert plan.downmix is not None
        assert plan.downmix.mode == "standard_5_1"
        assert output_channel_count(plan) == 2

    def test_manual_channel_selection_is_recorded(self) -> None:
        canonical = _asset("e", channels=4)
        monitoring = _asset("f", channels=2)
        plan = reference_mix_plan(
            _project(
                channels=4,
                canonical=canonical,
                monitoring=monitoring,
                left=1,
                right=3,
            ),
            canonical,
            monitoring,
        )
        assert plan.downmix is not None
        assert plan.downmix.mode == "manual"
        assert (plan.downmix.left_channel, plan.downmix.right_channel) == (1, 3)

    def test_multichannel_without_a_downmix_is_rejected(self) -> None:
        canonical = _asset("a", channels=6)
        with pytest.raises(SeparationRequestError):
            reference_mix_plan(_project(channels=6, canonical=canonical), canonical, None)

    def test_missing_canonical_audio_is_rejected(self) -> None:
        project = _project(channels=2, canonical=_asset("a"))
        with pytest.raises(SeparationRequestError):
            reference_mix_plan(project, None, None)


class TestModelIdentity:
    def test_manifest_identity_is_stable(self) -> None:
        manifest = model_manifest()
        assert model_manifest_id(manifest) == model_manifest_id(manifest)
        assert model_manifest_hash(manifest) == model_manifest_hash(manifest)
        assert len(model_manifest_hash(manifest)) == 64
        assert manifest.output_labels


class TestCacheKey:
    def _key(self, **overrides):
        canonical = _asset("a", channels=2)
        project = _project(canonical=canonical)
        plan = reference_mix_plan(project, canonical, None)
        inputs = {
            "project": project,
            "plan": plan,
            "manifest": model_manifest(),
            "mode": SeparationMode.FOUR_STEMS,
            "seed": 7,
            "device_type": DeviceType.CPU,
        }
        inputs.update(overrides)
        return request_cache_key(**inputs)

    def test_deterministic_for_identical_requests(self) -> None:
        first, transform = self._key()
        second, transform2 = self._key()
        assert first == second
        assert transform == transform2
        assert len(first) == 64 and len(transform) == 64

    def test_device_profile_seed_and_mode_change_the_key(self) -> None:
        base, _ = self._key()
        assert self._key(device_type=DeviceType.CUDA)[0] != base
        assert self._key(seed=8)[0] != base
        assert self._key(mode=SeparationMode.BASS_PAIR)[0] != base

    def test_parameters_change_the_key(self) -> None:
        base, _ = self._key()
        changed = {
            "preset": "htdemucs_ft",
            "shifts": 4,
            "internal_overlap": 0.5,
            "segment_seconds": 7.5,
            "window_seconds": 120.0,
            "overlap_seconds": 8.0,
        }
        assert self._key(parameters=changed)[0] != base


class TestDeviceProfile:
    def test_cpu_and_gpu_profiles(self) -> None:
        cpu = DeviceRecord(
            kind=DeviceKind.CPU,
            identifier="cpu",
            display_name="CPU",
            qualification_status=QualificationStatus.QUALIFIED,
            last_qualified_at=NOW,
        )
        assert device_profile(cpu) == (DeviceType.CPU, None)
        gpu = DeviceRecord(
            kind=DeviceKind.GPU,
            identifier="GPU-123",
            display_name="RTX",
            vram_total_mib=16_000,
            vram_free_mib=15_000,
            qualification_status=QualificationStatus.QUALIFIED,
            last_qualified_at=NOW,
        )
        assert device_profile(gpu) == (DeviceType.CUDA, "GPU-123")
