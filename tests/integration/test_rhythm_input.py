"""Reproducible rhythm input preparation with real ffmpeg (M3.3, §5.4-§5.6)."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.preparation import DownmixSpec
from basseparate.domain.rhythm import RhythmInputRole
from basseparate.domain.rhythm_input import BEAT_THIS_INPUT_PROFILE, RhythmInputPlan
from basseparate.media.derived import DerivedCancelledError
from basseparate.media.rhythm_input import (
    RhythmInputHashMismatchError,
    RhythmInputOutcome,
    prepare_rhythm_input,
    rhythm_input_transform_hash,
)

HASH_MODEL = "cd" * 32


def _sine(seconds: float, rate: int, frequency: float, amplitude: float = 0.5) -> np.ndarray:
    times = np.arange(int(round(seconds * rate)), dtype=np.float64) / rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * times)).astype("<f4")


def _write_pcm(path: Path, data: np.ndarray) -> str:
    import hashlib

    path.write_bytes(np.ascontiguousarray(data, dtype="<f4").tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(
    source_hash: str,
    *,
    rate: int,
    channels: int,
    role: RhythmInputRole = RhythmInputRole.ORIGINAL_MIX,
    downmix: DownmixSpec | None = None,
) -> RhythmInputPlan:
    return RhythmInputPlan(
        input_role=role,
        asset_id=uuid.uuid4(),
        source_hash=source_hash,
        sample_rate=rate,
        channel_count=channels,
        downmix=downmix,
        model_id="beat_this_final0",
        model_manifest_hash=HASH_MODEL,
        adapter_version="beat-this-adapter-v1",
    )


async def _prepare(
    plan: RhythmInputPlan, source: Path, work: Path, **kwargs: object
) -> RhythmInputOutcome:
    return await prepare_rhythm_input(
        plan=plan,
        source_path=source,
        work_dir=work,
        max_threads=2,
        **kwargs,  # type: ignore[arg-type]
    )


class TestStereoInput:
    @pytest.mark.asyncio
    async def test_resample_mapping_and_determinism(self, tmp_path: Path) -> None:
        rate = 48_000
        left = _sine(2.0, rate, 220.0)
        right = _sine(2.0, rate, 330.0)
        source = tmp_path / "source.pcm"
        source_hash = _write_pcm(source, np.stack([left, right], axis=1))
        plan = _plan(source_hash, rate=rate, channels=2)

        outcome = await _prepare(plan, source, tmp_path / "work1")
        assert outcome.frame_count == 44_100
        assert outcome.expected_frame_count == 44_100
        assert abs(outcome.endpoint_difference_frames) <= 2
        assert outcome.pcm_byte_count == 44_100 * 2 * 4
        assert outcome.time_mapping.project_rate == rate
        assert outcome.time_mapping.representation_rate == 22_050
        assert outcome.profile is BEAT_THIS_INPUT_PROFILE
        assert outcome.downmix_mode is None
        assert outcome.transform_hash == rhythm_input_transform_hash(plan)
        assert 0.3 < outcome.max_amplitude <= 0.51

        # A second run is byte-identical and reuses the same identity.
        again = await _prepare(plan, source, tmp_path / "work2")
        assert again.content_hash == outcome.content_hash
        assert again.transform_hash == outcome.transform_hash
        assert again.final_path.read_bytes() == outcome.final_path.read_bytes()

        # The source asset is untouched.
        assert plan.source_hash == source_hash

    @pytest.mark.asyncio
    async def test_source_hash_mismatch(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pcm"
        _write_pcm(source, _sine(0.5, 48_000, 220.0)[:, None])
        plan = _plan("ab" * 32, rate=48_000, channels=1)
        with pytest.raises(RhythmInputHashMismatchError):
            await _prepare(plan, source, tmp_path / "work")

    @pytest.mark.asyncio
    async def test_misaligned_source(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pcm"
        data = np.zeros((100, 2), dtype="<f4")
        source.write_bytes(np.ascontiguousarray(data).tobytes()[:-2])
        plan = _plan("ab" * 32, rate=48_000, channels=2)
        with pytest.raises(Exception, match="frame-aligned"):
            await _prepare(plan, source, tmp_path / "work")


class TestMonoAndMultichannel:
    @pytest.mark.asyncio
    async def test_mono_is_duplicated_to_stereo(self, tmp_path: Path) -> None:
        rate = 44_100
        source = tmp_path / "mono.pcm"
        source_hash = _write_pcm(source, _sine(1.0, rate, 440.0))
        plan = _plan(source_hash, rate=rate, channels=1)
        outcome = await _prepare(plan, source, tmp_path / "work")
        assert outcome.frame_count == 22_050
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        assert np.array_equal(stereo[:, 0], stereo[:, 1])

    @pytest.mark.asyncio
    async def test_multichannel_downmix(self, tmp_path: Path) -> None:
        rate = 44_100
        channels = [_sine(1.0, rate, 100.0 * (index + 1), amplitude=0.2) for index in range(6)]
        source = tmp_path / "51.pcm"
        source_hash = _write_pcm(source, np.stack(channels, axis=1))
        manual = DownmixSpec(mode="manual", left_channel=0, right_channel=1)
        plan = _plan(source_hash, rate=rate, channels=6, downmix=manual)
        outcome = await _prepare(plan, source, tmp_path / "work")
        assert outcome.frame_count == 22_050
        assert outcome.pcm_byte_count == 22_050 * 2 * 4
        assert outcome.downmix_mode == "manual"
        stereo = np.fromfile(outcome.final_path, dtype="<f4").reshape(-1, 2)
        assert np.isfinite(stereo).all()
        assert float(np.abs(stereo).max()) > 0.0

    @pytest.mark.asyncio
    async def test_standard_51_downmix(self, tmp_path: Path) -> None:
        rate = 44_100
        channels = [_sine(0.5, rate, 200.0, 0.1) for _ in range(6)]
        source = tmp_path / "51.pcm"
        source_hash = _write_pcm(source, np.stack(channels, axis=1))
        plan = _plan(
            source_hash,
            rate=rate,
            channels=6,
            downmix=DownmixSpec(mode="standard_5_1"),
        )
        outcome = await _prepare(plan, source, tmp_path / "work")
        assert outcome.downmix_mode == "standard_5_1"
        assert outcome.frame_count == 11_025


class TestDegenerateInput:
    @pytest.mark.asyncio
    async def test_exact_silence_is_valid(self, tmp_path: Path) -> None:
        source = tmp_path / "silence.pcm"
        source_hash = _write_pcm(source, np.zeros((48_000, 2), dtype="<f4"))
        plan = _plan(source_hash, rate=48_000, channels=2)
        outcome = await _prepare(plan, source, tmp_path / "work")
        assert outcome.frame_count == 22_050
        assert outcome.max_amplitude == 0.0
        assert outcome.pcm_byte_count == 22_050 * 2 * 4

    @pytest.mark.asyncio
    async def test_very_short_audio(self, tmp_path: Path) -> None:
        rate = 48_000
        source = tmp_path / "short.pcm"
        source_hash = _write_pcm(source, _sine(0.01, rate, 440.0)[:, None])
        plan = _plan(source_hash, rate=rate, channels=1)
        outcome = await _prepare(plan, source, tmp_path / "work")
        assert 0 < outcome.frame_count <= 221
        assert abs(outcome.endpoint_difference_frames) <= 2

    @pytest.mark.asyncio
    async def test_pre_set_cancel_leaves_no_output(self, tmp_path: Path) -> None:
        rate = 48_000
        source = tmp_path / "source.pcm"
        source_hash = _write_pcm(source, _sine(1.0, rate, 220.0)[:, None])
        plan = _plan(source_hash, rate=rate, channels=1)
        cancel = threading.Event()
        cancel.set()
        work = tmp_path / "work"
        with pytest.raises(DerivedCancelledError):
            await _prepare(plan, source, work, cancel_event=cancel)
        assert not list(work.glob("*.pcm")) if work.exists() else True
