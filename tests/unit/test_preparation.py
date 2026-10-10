"""Unit tests for separation input preparation (M2.4).

Covers:
- Domain validators: DownmixSpec, ReferenceMixPlan, ChannelStats,
  NormalizationProfile mode/reference consistency, PreparedInput bounds.
- transform_identity_hash purity (same plan ⇒ same identity).
- compute_normalization_profile on synthetic f32le files: exact silence
  shortcut, DC, correlated stereo, anti-phase fallback, near-silence
  epsilon cap, single-channel signal, float64 accuracy, determinism, and
  malformed-input rejection.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.preparation import (
    NORMALIZATION_PROFILE_VERSION,
    ChannelStats,
    DownmixSpec,
    NormalizationProfile,
    PreparedInput,
    ReferenceMixPlan,
)
from basseparate.domain.representation import TimeMapping
from basseparate.media.preparation import (
    ENDPOINT_TOLERANCE_FRAMES,
    NORMALIZATION_EPSILON,
    PreparationError,
    compute_normalization_profile,
    sha256_file,
    transform_identity_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data).astype("<f4").tobytes())


def _plan(kind: str = "stereo", source_hash: str = HASH_A, downmix=None) -> ReferenceMixPlan:
    return ReferenceMixPlan(
        kind=kind,  # type: ignore[arg-type]
        asset_id=uuid.uuid4(),
        source_hash=source_hash,
        downmix=downmix,
    )


class TestDownmixSpec:
    def test_standard_51_ok(self) -> None:
        spec = DownmixSpec(mode="standard_5_1")
        assert spec.left_channel is None
        assert spec.right_channel is None

    def test_manual_requires_both_channels(self) -> None:
        spec = DownmixSpec(mode="manual", left_channel=0, right_channel=1)
        assert spec.left_channel == 0
        assert spec.right_channel == 1
        with pytest.raises(ValueError, match="both channel selections"):
            DownmixSpec(mode="manual", left_channel=0)

    def test_standard_rejects_channel_selections(self) -> None:
        with pytest.raises(ValueError, match="must not carry channel selections"):
            DownmixSpec(mode="standard_5_1", left_channel=0, right_channel=1)


class TestReferenceMixPlan:
    def test_stereo_without_downmix(self) -> None:
        plan = _plan("stereo")
        assert plan.downmix is None

    def test_mono_without_downmix(self) -> None:
        plan = _plan("mono")
        assert plan.downmix is None

    def test_multichannel_requires_downmix(self) -> None:
        with pytest.raises(ValueError, match="requires an explicit downmix"):
            _plan("multichannel")

    def test_multichannel_with_downmix(self) -> None:
        plan = _plan("multichannel", downmix=DownmixSpec(mode="standard_5_1"))
        assert plan.downmix is not None
        assert plan.downmix.mode == "standard_5_1"

    def test_stereo_rejects_downmix(self) -> None:
        with pytest.raises(ValueError, match="must not carry a downmix"):
            _plan("stereo", downmix=DownmixSpec(mode="standard_5_1"))

    def test_mono_rejects_downmix(self) -> None:
        with pytest.raises(ValueError, match="must not carry a downmix"):
            _plan("mono", downmix=DownmixSpec(mode="standard_5_1"))


class TestChannelStats:
    def test_finite_ok(self) -> None:
        stats = ChannelStats(mean=0.1, rms=0.2)
        assert stats.mean == 0.1

    def test_negative_rms_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChannelStats(mean=0.0, rms=-1.0)

    def test_non_finite_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            ChannelStats(mean=float("inf"), rms=0.0)
        # NaN fails the rms >= 0 constraint before the finiteness check.
        with pytest.raises(ValueError):
            ChannelStats(mean=0.0, rms=float("nan"))


def _profile(**overrides: object) -> NormalizationProfile:
    base: dict[str, object] = {
        "prepared_input_hash": HASH_A,
        "frame_count": 1000,
        "channel_count": 2,
        "max_abs": 0.5,
        "channel_mean": ChannelStats(mean=0.0, rms=0.4),
        "full_channel": ChannelStats(mean=0.0, rms=0.4),
        "mode": "normal",
        "reference": "channel_mean",
        "scale": 1.0 / 0.4,
        "epsilon": NORMALIZATION_EPSILON,
    }
    base.update(overrides)
    return NormalizationProfile(**base)  # type: ignore[arg-type]


class TestNormalizationProfile:
    def test_normal_defaults(self) -> None:
        profile = _profile()
        assert profile.version == NORMALIZATION_PROFILE_VERSION

    def test_scale_zero_iff_exact_silence(self) -> None:
        with pytest.raises(ValueError, match="if and only if"):
            _profile(scale=0.0)
        with pytest.raises(ValueError, match="if and only if"):
            _profile(mode="exact_silence", scale=1.0)

    def test_exact_silence_requires_zero_max_abs(self) -> None:
        with pytest.raises(ValueError, match="max_abs to be zero"):
            _profile(mode="exact_silence", scale=0.0, max_abs=0.1)

    def test_fallback_reference_consistency(self) -> None:
        with pytest.raises(ValueError, match="full_channel reference"):
            _profile(mode="full_channel_fallback", reference="channel_mean")

    def test_normal_reference_consistency(self) -> None:
        with pytest.raises(ValueError, match="channel_mean reference"):
            _profile(reference="full_channel")

    def test_non_finite_scale_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            _profile(scale=float("inf"))


class TestPreparedInput:
    def _input(self, **overrides: object) -> PreparedInput:
        base: dict[str, object] = {
            "asset_id": uuid.uuid4(),
            "content_hash": HASH_A,
            "transform_hash": HASH_B,
            "sample_rate": 44100,
            "channel_count": 2,
            "frame_count": 44100,
            "source_asset_id": uuid.uuid4(),
            "source_hash": HASH_A,
            "source_rate": 48000,
            "source_frame_count": 48000,
            "endpoint_difference_frames": 0,
            "time_mapping": TimeMapping(project_rate=48000, representation_rate=44100),
            "created_at": datetime.now(UTC),
        }
        base.update(overrides)
        return PreparedInput(**base)  # type: ignore[arg-type]

    def test_construction(self) -> None:
        record = self._input()
        assert record.channel_count == 2

    def test_endpoint_difference_bounded(self) -> None:
        with pytest.raises(ValueError):
            self._input(endpoint_difference_frames=17)
        with pytest.raises(ValueError):
            self._input(endpoint_difference_frames=-17)

    def test_endpoint_difference_within_tolerance_ok(self) -> None:
        record = self._input(endpoint_difference_frames=ENDPOINT_TOLERANCE_FRAMES)
        assert record.endpoint_difference_frames == ENDPOINT_TOLERANCE_FRAMES


class TestTransformIdentityHash:
    def test_same_plan_same_hash(self) -> None:
        plan = _plan("stereo")
        assert transform_identity_hash(plan, 44100) == transform_identity_hash(plan, 44100)

    def test_different_source_hash_differs(self) -> None:
        assert transform_identity_hash(_plan("stereo", HASH_A), 44100) != transform_identity_hash(
            _plan("stereo", HASH_B), 44100
        )

    def test_different_model_rate_differs(self) -> None:
        plan = _plan("stereo")
        assert transform_identity_hash(plan, 44100) != transform_identity_hash(plan, 88200)

    def test_different_downmix_differs(self) -> None:
        a = _plan(
            "multichannel",
            downmix=DownmixSpec(mode="standard_5_1"),
        )
        b = _plan(
            "multichannel",
            downmix=DownmixSpec(mode="manual", left_channel=0, right_channel=3),
        )
        assert transform_identity_hash(a, 44100) != transform_identity_hash(b, 44100)

    def test_mono_flag_changes_identity(self) -> None:
        # Same source hash, different kind ⇒ different mono-duplication flag.
        assert transform_identity_hash(_plan("mono"), 44100) != transform_identity_hash(
            _plan("stereo"), 44100
        )

    def test_is_valid_sha256_hex(self) -> None:
        digest = transform_identity_hash(_plan("stereo"), 44100)
        assert len(digest) == 64
        int(digest, 16)


def _sine(frames: int, rate: int, hz: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / rate
    return (amp * np.sin(2.0 * np.pi * hz * t)).astype("<f4")


class TestNormalizationProfileComputation:
    def test_exact_silence_shortcut(self, tmp_path: Path) -> None:
        pcm = tmp_path / "silence.pcm"
        _write_f32le_pcm(pcm, np.zeros((1000, 2), dtype="<f4"))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "exact_silence"
        assert profile.scale == 0.0
        assert profile.max_abs == 0.0
        assert profile.reference == "full_channel"
        assert profile.frame_count == 1000

    def test_dc_signal_normal_mode(self, tmp_path: Path) -> None:
        pcm = tmp_path / "dc.pcm"
        _write_f32le_pcm(pcm, np.full((500, 2), 0.25, dtype="<f4"))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "normal"
        assert profile.reference == "channel_mean"
        assert profile.scale == pytest.approx(1.0 / 0.25, rel=1e-6)

    def test_correlated_stereo_normal(self, tmp_path: Path) -> None:
        mono = _sine(2048, 44100, 440.0, amp=0.5)
        pcm = tmp_path / "stereo.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, mono], axis=1))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "normal"
        assert profile.reference == "channel_mean"
        expected_rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
        assert profile.channel_mean.rms == pytest.approx(expected_rms, rel=1e-6)
        assert profile.scale == pytest.approx(1.0 / expected_rms, rel=1e-6)

    def test_anti_phase_fallback(self, tmp_path: Path) -> None:
        mono = _sine(2048, 44100, 440.0, amp=0.5)
        pcm = tmp_path / "antiphase.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, -mono], axis=1))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "full_channel_fallback"
        assert profile.reference == "full_channel"
        expected_rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
        assert profile.full_channel.rms == pytest.approx(expected_rms, rel=1e-6)
        assert profile.scale == pytest.approx(1.0 / expected_rms, rel=1e-6)

    def test_near_silence_epsilon_cap(self, tmp_path: Path) -> None:
        mono = _sine(2048, 44100, 440.0, amp=1e-8)
        pcm = tmp_path / "near.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, mono], axis=1))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "normal"
        assert profile.scale <= 1.0 / NORMALIZATION_EPSILON
        assert profile.scale == pytest.approx(1.0 / NORMALIZATION_EPSILON, rel=1e-9)

    def test_near_silence_anti_phase_fallback_cap(self, tmp_path: Path) -> None:
        mono = _sine(2048, 44100, 440.0, amp=1e-8)
        pcm = tmp_path / "near_anti.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, -mono], axis=1))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.mode == "full_channel_fallback"
        assert profile.scale <= 1.0 / NORMALIZATION_EPSILON

    def test_single_channel_signal_normal(self, tmp_path: Path) -> None:
        mono = _sine(2048, 44100, 440.0, amp=0.5)
        pcm = tmp_path / "lonly.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, np.zeros_like(mono)], axis=1))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        # Channel-mean variance is a quarter of the full variance: above
        # FALLBACK_RATIO, so the normal path with the halved center level.
        assert profile.mode == "normal"
        exact = mono.astype(np.float64)
        expected_center_rms = float(np.sqrt(np.mean((exact / 2) ** 2)))
        assert profile.channel_mean.rms == pytest.approx(expected_center_rms, rel=1e-6)
        full_rms = float(np.sqrt(np.mean(exact**2)))
        assert profile.scale == pytest.approx(2.0 / full_rms, rel=1e-6)

    def test_float64_accuracy(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(42)
        frames = 100_000
        data = (rng.standard_normal((frames, 2)) * 0.3).astype("<f4")
        pcm = tmp_path / "noise.pcm"
        _write_f32le_pcm(pcm, data)
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)

        exact = data.astype(np.float64)
        expected_full_rms = float(np.sqrt(np.mean(exact**2)))
        exact_mean_signal = exact.mean(axis=1)
        expected_mean_rms = float(np.sqrt(np.mean(exact_mean_signal**2)))
        expected_mean = float(exact_mean_signal.mean())

        assert profile.full_channel.rms == pytest.approx(expected_full_rms, rel=1e-9)
        assert profile.channel_mean.rms == pytest.approx(expected_mean_rms, rel=1e-9)
        assert profile.channel_mean.mean == pytest.approx(expected_mean, rel=1e-9)
        assert profile.max_abs == pytest.approx(float(np.abs(exact).max()), rel=0.0)

    def test_deterministic(self, tmp_path: Path) -> None:
        mono = _sine(4096, 44100, 220.0)
        pcm = tmp_path / "det.pcm"
        _write_f32le_pcm(pcm, np.stack([mono, mono * 0.9], axis=1))
        first = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        second = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert first == second

    def test_max_abs_recorded(self, tmp_path: Path) -> None:
        pcm = tmp_path / "peak.pcm"
        _write_f32le_pcm(pcm, np.array([[0.1, -0.75], [0.2, 0.3]], dtype="<f4"))
        profile = compute_normalization_profile(pcm, 44100, 2, HASH_A)
        assert profile.max_abs == pytest.approx(0.75, rel=0.0)

    def test_misaligned_file_rejected(self, tmp_path: Path) -> None:
        pcm = tmp_path / "bad.pcm"
        pcm.write_bytes(np.zeros(7, dtype="<f4").tobytes())  # 7 f32 ≠ multiple of 2ch
        with pytest.raises(PreparationError, match="frame-aligned"):
            compute_normalization_profile(pcm, 44100, 2, HASH_A)

    def test_non_finite_samples_rejected(self, tmp_path: Path) -> None:
        pcm = tmp_path / "nan.pcm"
        data = np.zeros((10, 2), dtype="<f4")
        data[3, 1] = np.nan
        _write_f32le_pcm(pcm, data)
        with pytest.raises(PreparationError, match="non-finite"):
            compute_normalization_profile(pcm, 44100, 2, HASH_A)

    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        pcm = tmp_path / "empty.pcm"
        pcm.write_bytes(b"")
        with pytest.raises(PreparationError, match="empty"):
            compute_normalization_profile(pcm, 44100, 2, HASH_A)


class TestHashHelper:
    def test_sha256_file(self, tmp_path: Path) -> None:
        pcm = tmp_path / "x.pcm"
        payload = b"0123456789" * 100
        pcm.write_bytes(payload)
        assert sha256_file(pcm) == hashlib.sha256(payload).hexdigest()
