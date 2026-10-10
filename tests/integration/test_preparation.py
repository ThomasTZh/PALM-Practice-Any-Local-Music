"""Integration tests for separation input preparation (M2.4, real ffmpeg).

Covers:
- Stereo 48 kHz → 44.1 kHz: frame count, endpoint difference, content hash,
  transform identity, intermediate cleanup.
- Mono → stereo duplication (byte-exact L == R), at and off the model rate.
- 5.1 → stereo downmix → 44.1 kHz and manual two-channel extraction.
- Determinism: two runs on the same source produce byte-identical prepared
  inputs with identical transform identity and normalization profile
  (the M2.4 acceptance criterion).
- Failure modes: source hash mismatch, plan kind/channel mismatch; every
  failure removes its staging files.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.preparation import (
    DownmixSpec,
    ReferenceMixPlan,
)
from basseparate.media.preparation import (
    ENDPOINT_TOLERANCE_FRAMES,
    PreparationError,
    PreparedInputOutcome,
    SourceHashMismatchError,
    prepare_separation_input,
    sha256_file,
    transform_identity_hash,
)

MODEL_RATE = 44100


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data).astype("<f4").tobytes())


def _sine(seconds: float, rate: int, hz: float, amp: float = 0.4) -> np.ndarray:
    frames = int(seconds * rate)
    t = np.arange(frames, dtype=np.float64) / rate
    return (amp * np.sin(2.0 * np.pi * hz * t)).astype("<f4")


def _freq_energy(sig: np.ndarray, frequency: float, sample_rate: int) -> float:
    window = np.exp(-2j * np.pi * frequency * np.arange(len(sig)) / sample_rate)
    return float(abs(np.dot(sig, window)) ** 2 / len(sig))


def _plan(
    path: Path,
    kind: str,
    downmix: DownmixSpec | None = None,
    hash_override: str | None = None,
) -> ReferenceMixPlan:
    return ReferenceMixPlan(
        kind=kind,  # type: ignore[arg-type]
        asset_id=uuid.uuid4(),
        source_hash=hash_override or sha256_file(path),
        downmix=downmix,
    )


@pytest.fixture
def stereo_48k(tmp_path: Path) -> Path:
    """One second of 48 kHz stereo with distinct tones per channel."""
    data = np.stack([_sine(1.0, 48000, 300.0), _sine(1.0, 48000, 600.0)], axis=1)
    path = tmp_path / "stereo48.pcm"
    _write_f32le_pcm(path, data)
    return path


@pytest.fixture
def mono_48k(tmp_path: Path) -> Path:
    """One second of 48 kHz mono."""
    path = tmp_path / "mono48.pcm"
    _write_f32le_pcm(path, _sine(1.0, 48000, 440.0).reshape(-1, 1))
    return path


@pytest.fixture
def mono_44100(tmp_path: Path) -> Path:
    """One second of 44.1 kHz mono (already at the model rate)."""
    path = tmp_path / "mono44.pcm"
    _write_f32le_pcm(path, _sine(1.0, MODEL_RATE, 440.0).reshape(-1, 1))
    return path


@pytest.fixture
def five_one_48k(tmp_path: Path) -> Path:
    """One second of 48 kHz 5.1: a unique 100·(i+1) Hz tone per channel."""
    channels = [_sine(1.0, 48000, 100.0 * (i + 1)) for i in range(6)]
    path = tmp_path / "51.pcm"
    _write_f32le_pcm(path, np.stack(channels, axis=1))
    return path


class TestStereoPreparation:
    @pytest.mark.asyncio
    async def test_resample_to_model_rate(
        self, stereo_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(stereo_48k, "stereo")
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=stereo_48k,
            source_rate=48000,
            source_channels=2,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        assert outcome.frame_count == MODEL_RATE  # 1 s at 44.1 kHz
        assert outcome.source_frame_count == 48000
        assert abs(outcome.endpoint_difference_frames) <= ENDPOINT_TOLERANCE_FRAMES
        assert outcome.content_hash == sha256_file(outcome.final_path)
        assert outcome.transform_hash == transform_identity_hash(plan, MODEL_RATE)
        assert outcome.downmix_mode is None
        assert outcome.profile.frame_count == outcome.frame_count
        assert outcome.profile.channel_count == 2
        assert outcome.profile.mode == "normal"
        assert outcome.final_path.exists()

    @pytest.mark.asyncio
    async def test_intermediates_removed_on_success(
        self, stereo_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(stereo_48k, "stereo")
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=stereo_48k,
            source_rate=48000,
            source_channels=2,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        remaining = sorted(p.name for p in work.iterdir())
        assert remaining == [outcome.final_path.name]


class TestMonoPreparation:
    @pytest.mark.asyncio
    async def test_duplicated_to_stereo_byte_exact(
        self, mono_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(mono_48k, "mono")
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=mono_48k,
            source_rate=48000,
            source_channels=1,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        assert stereo.shape[0] == MODEL_RATE
        np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])
        assert outcome.profile.channel_count == 2

    @pytest.mark.asyncio
    async def test_at_model_rate_identity(
        self, mono_44100: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(mono_44100, "mono")
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=mono_44100,
            source_rate=MODEL_RATE,
            source_channels=1,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        assert outcome.endpoint_difference_frames == 0
        assert outcome.frame_count == MODEL_RATE
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])


class TestMultichannelPreparation:
    @pytest.mark.asyncio
    async def test_51_downmix_then_resample(
        self, five_one_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(
            five_one_48k, "multichannel", downmix=DownmixSpec(mode="standard_5_1")
        )
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=five_one_48k,
            source_rate=48000,
            source_channels=6,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        assert outcome.downmix_mode == "standard_5_1"
        assert outcome.frame_count == MODEL_RATE
        assert outcome.source_frame_count == 48000
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        assert stereo.shape == (MODEL_RATE, 2)
        assert np.isfinite(stereo).all()

    @pytest.mark.asyncio
    async def test_manual_two_channel_extraction(
        self, five_one_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(
            five_one_48k,
            "multichannel",
            downmix=DownmixSpec(mode="manual", left_channel=0, right_channel=1),
        )
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=five_one_48k,
            source_rate=48000,
            source_channels=6,
            model_rate=MODEL_RATE,
            work_dir=work,
        )
        assert outcome.downmix_mode == "manual"
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        # Manual extraction of FL/FR: the 100 Hz (FL) and 200 Hz (FR)
        # tones survive; the 300 Hz center tone does not.
        assert _freq_energy(stereo[:, 0], 100.0, MODEL_RATE) > 10
        assert _freq_energy(stereo[:, 1], 200.0, MODEL_RATE) > 10
        for ch in stereo.T:
            assert _freq_energy(ch, 300.0, MODEL_RATE) < 1e-6


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_two_runs_byte_identical(
        self, stereo_48k: Path, tmp_path: Path
    ) -> None:
        plan = _plan(stereo_48k, "stereo")
        results: list[PreparedInputOutcome] = []
        for i in range(2):
            outcome = await prepare_separation_input(
                plan=plan,
                source_path=stereo_48k,
                source_rate=48000,
                source_channels=2,
                model_rate=MODEL_RATE,
                work_dir=tmp_path / f"work{i}",
            )
            results.append(outcome)
        first, second = results
        assert first.final_path.read_bytes() == second.final_path.read_bytes()
        assert first.content_hash == second.content_hash
        assert first.transform_hash == second.transform_hash
        assert first.profile == second.profile

    @pytest.mark.asyncio
    async def test_transform_identity_is_pure_function_of_plan(
        self, stereo_48k: Path, tmp_path: Path
    ) -> None:
        plan = _plan(stereo_48k, "stereo")
        outcome = await prepare_separation_input(
            plan=plan,
            source_path=stereo_48k,
            source_rate=48000,
            source_channels=2,
            model_rate=MODEL_RATE,
            work_dir=tmp_path / "work",
        )
        assert outcome.transform_hash == transform_identity_hash(plan, MODEL_RATE)
        assert outcome.profile.prepared_input_hash == outcome.content_hash


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_source_hash_mismatch(
        self, stereo_48k: Path, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        plan = _plan(stereo_48k, "stereo", hash_override="f" * 64)
        with pytest.raises(SourceHashMismatchError, match="mismatch"):
            await prepare_separation_input(
                plan=plan,
                source_path=stereo_48k,
                source_rate=48000,
                source_channels=2,
                model_rate=MODEL_RATE,
                work_dir=work,
            )
        assert not work.exists() or not any(work.iterdir())

    @pytest.mark.asyncio
    async def test_kind_channel_mismatch(
        self, mono_48k: Path, tmp_path: Path
    ) -> None:
        plan = _plan(mono_48k, "stereo")
        with pytest.raises(PreparationError, match="does not match"):
            await prepare_separation_input(
                plan=plan,
                source_path=mono_48k,
                source_rate=48000,
                source_channels=1,
                model_rate=MODEL_RATE,
                work_dir=tmp_path / "work",
            )

    @pytest.mark.asyncio
    async def test_missing_source(
        self, tmp_path: Path
    ) -> None:
        plan = ReferenceMixPlan(
            kind="stereo",
            asset_id=uuid.uuid4(),
            source_hash="e" * 64,
        )
        with pytest.raises(PreparationError):
            await prepare_separation_input(
                plan=plan,
                source_path=tmp_path / "absent.pcm",
                source_rate=48000,
                source_channels=2,
                model_rate=MODEL_RATE,
                work_dir=tmp_path / "work",
            )
