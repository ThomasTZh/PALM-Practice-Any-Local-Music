"""Integration tests for the M1.7 derived PCM engines (real ffmpeg).

Covers:
- 5.1 → stereo downmix: spectral content of both output rows, coefficient
  energy ratios, frame-count preservation, determinism.
- Manual two-channel extraction from an unknown layout.
- Playback resampling 44100 ↔ 48000: exact integer-second lengths,
  endpoint difference, impulse position (start/middle/end), pitch
  preservation, determinism.
- Failure modes: missing source, bad filter, bad rates, pre-set and
  mid-run cancellation, disk budget. Every failure path removes its
  partial output file.
"""

from __future__ import annotations

import os
import struct
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest

from basseparate.media.derived import (
    DerivedCancelledError,
    DerivedFailedError,
    DerivedTimeoutError,
    InsufficientDiskSpaceError,
    downmix_monitoring,
    playback_resample_filter,
    resample_playback,
)
from basseparate.media.downmix import (
    manual_matrix,
    pan_expression,
    standard_51_matrix,
)

FFMPEG = "ffmpeg"


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data, dtype="<f4").tobytes())


def _sine(
    seconds: float, sample_rate: int, frequency: float, amplitude: float = 1.0
) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return amplitude * np.sin(2 * np.pi * frequency * t)


def _freq_energy(sig: np.ndarray, frequency: float, sample_rate: int) -> float:
    window = np.exp(-2j * np.pi * frequency * np.arange(len(sig)) / sample_rate)
    return float(abs(np.dot(sig, window)) ** 2 / len(sig))


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int, channels: int) -> None:
    interleaved = samples if samples.ndim == 2 else samples[:, None]
    s16 = np.clip(interleaved, -1.0, 1.0)
    pcm = (s16 * 32767.0).astype("<i2").tobytes()
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH", 16, 1, channels, sample_rate, sample_rate * channels * 2, channels * 2, 16
        )
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    path.write_bytes(header + pcm)


def _decode_wav_to_f32le(wav_path: Path, pcm_path: Path, channels: int) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(wav_path),
            "-f",
            "f32le",
            "-ac",
            str(channels),
            "-y",
            str(pcm_path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def five_one_source(tmp_path: Path) -> Path:
    """One second of 5.1 audio: a unique 100·(i+1) Hz tone per channel."""
    sr = 44100
    channels = [
        _sine(1.0, sr, 100.0 * (i + 1)) for i in range(6)
    ]
    data = np.stack(channels, axis=1)  # (N, 6)
    path = tmp_path / "51.pcm"
    _write_f32le_pcm(path, data)
    return path


class TestDownmixMonitoring:
    @pytest.mark.asyncio
    async def test_51_spectral_content(self, five_one_source: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.pcm"
        left, right = standard_51_matrix()
        result = await downmix_monitoring(
            source_path=five_one_source,
            output_path=out,
            sample_rate=44100,
            channel_count=6,
            pan_spec=pan_expression(left, right),
        )
        assert result.frame_count == 44100
        assert result.pcm_byte_count == 44100 * 2 * 4
        # Row-normalized: incoherent unit tones sum to at most 1.0.
        assert 0.5 < result.max_amplitude <= 1.0 + 1e-6

        stereo = np.fromfile(out, dtype="<f4").reshape(-1, 2)
        left_ch, right_ch = stereo[:, 0], stereo[:, 1]

        # Left row: FL(100) + C(300) + Ls(400) + LFE(600), no FR/Rs.
        assert _freq_energy(left_ch, 100, 44100) > 50
        for f in (300.0, 400.0, 600.0):
            assert _freq_energy(left_ch, f, 44100) > 5
        for f in (200.0, 500.0):
            assert _freq_energy(left_ch, f, 44100) < 1e-6

        # Right row: FR(200) + C(300) + Rs(500) + LFE(600), no FL/Ls.
        assert _freq_energy(right_ch, 200, 44100) > 50
        for f in (300.0, 500.0, 600.0):
            assert _freq_energy(right_ch, f, 44100) > 5
        for f in (100.0, 400.0):
            assert _freq_energy(right_ch, f, 44100) < 1e-6

        # Coefficient ratio: FL/FR (1.0) vs C (0.7071) → energy ratio 2.
        ratio = _freq_energy(left_ch, 100, 44100) / _freq_energy(left_ch, 300, 44100)
        assert ratio == pytest.approx(2.0, rel=1e-2)

    @pytest.mark.asyncio
    async def test_manual_extraction(self, tmp_path: Path) -> None:
        sr = 44100
        data = np.stack(
            [_sine(1.0, sr, 100.0 * (i + 1)) for i in range(4)], axis=1
        )
        src = tmp_path / "src.pcm"
        _write_f32le_pcm(src, data)
        out = tmp_path / "out.pcm"

        left, right = manual_matrix(1, 3)
        result = await downmix_monitoring(
            source_path=src,
            output_path=out,
            sample_rate=sr,
            channel_count=4,
            pan_spec=pan_expression(left, right),
        )
        stereo = np.fromfile(out, dtype="<f4").reshape(-1, 2)
        # Exact channel copies (coefficient 1.0, single term).
        assert np.allclose(stereo[:, 0], data[:, 1], atol=1e-6)
        assert np.allclose(stereo[:, 1], data[:, 3], atol=1e-6)
        assert result.max_amplitude == pytest.approx(1.0, rel=1e-3)

    @pytest.mark.asyncio
    async def test_deterministic(self, five_one_source: Path, tmp_path: Path) -> None:
        left, right = standard_51_matrix()
        spec = pan_expression(left, right)
        results = []
        for i in range(2):
            results.append(
                await downmix_monitoring(
                    source_path=five_one_source,
                    output_path=tmp_path / f"out{i}.pcm",
                    sample_rate=44100,
                    channel_count=6,
                    pan_spec=spec,
                )
            )
        assert results[0].content_hash == results[1].content_hash
        assert results[0].pcm_byte_count == 44100 * 2 * 4


class TestResamplePlayback:
    def _one_second(self, tmp_path: Path, rate: int, freq: float = 220.0) -> Path:
        data = np.stack([_sine(1.0, rate, freq), _sine(1.0, rate, freq, 0.5)], axis=1)
        path = tmp_path / f"src{rate}.pcm"
        _write_f32le_pcm(path, data)
        return path

    @pytest.mark.asyncio
    async def test_44100_to_48000_exact(self, tmp_path: Path) -> None:
        src = self._one_second(tmp_path, 44100)
        out = tmp_path / "out.pcm"
        result = await resample_playback(
            source_path=src,
            output_path=out,
            source_rate=44100,
            target_rate=48000,
            channel_count=2,
        )
        assert result.source_frame_count == 44100
        assert result.frame_count == 48000
        assert result.expected_frame_count == 48000
        assert result.endpoint_difference_frames == 0
        assert result.pcm_byte_count == 48000 * 2 * 4

    @pytest.mark.asyncio
    async def test_48000_to_44100_exact(self, tmp_path: Path) -> None:
        src = self._one_second(tmp_path, 48000)
        out = tmp_path / "out.pcm"
        result = await resample_playback(
            source_path=src,
            output_path=out,
            source_rate=48000,
            target_rate=44100,
            channel_count=2,
        )
        assert result.source_frame_count == 48000
        assert result.frame_count == 44100
        assert result.expected_frame_count == 44100
        assert result.endpoint_difference_frames == 0

    @pytest.mark.asyncio
    async def test_pitch_preserved(self, tmp_path: Path) -> None:
        """A 220 Hz tone at 44.1 kHz is still 220 Hz at 48 kHz (spec §9)."""
        src = self._one_second(tmp_path, 44100, freq=220.0)
        out = tmp_path / "out.pcm"
        await resample_playback(
            source_path=src,
            output_path=out,
            source_rate=44100,
            target_rate=48000,
            channel_count=2,
        )
        stereo = np.fromfile(out, dtype="<f4").reshape(-1, 2)
        # One channel, trimmed window (avoids the resampler's start transient).
        sig = stereo[1000:-1000, 0]
        energies = {f: _freq_energy(sig, f, 48000) for f in (219.0, 220.0, 221.0)}
        peak = max(energies, key=energies.get)
        assert peak == 220.0
        assert energies[220.0] > 50
        assert energies[220.0] > 50 * max(energies[219.0], energies[221.0])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("impulse_frame", "expected"),
        [(0, 0), (22050, 24000), (44099, 47999)],
        ids=["start", "middle", "end"],
    )
    async def test_impulse_position(
        self, tmp_path: Path, impulse_frame: int, expected: int
    ) -> None:
        n = 44100
        data = np.zeros((n, 2), dtype="<f4")
        data[impulse_frame] = [1.0, -1.0]
        src = tmp_path / "src.pcm"
        _write_f32le_pcm(src, data)
        out = tmp_path / "out.pcm"
        await resample_playback(
            source_path=src,
            output_path=out,
            source_rate=44100,
            target_rate=48000,
            channel_count=2,
        )
        resampled = np.fromfile(out, dtype="<f4").reshape(-1, 2)
        peak_left = int(np.argmax(np.abs(resampled[:, 0])))
        assert abs(peak_left - expected) <= 2
        # Sign is preserved on both channels.
        assert resampled[peak_left, 0] > 0
        assert resampled[peak_left, 1] < 0

    @pytest.mark.asyncio
    async def test_deterministic(self, tmp_path: Path) -> None:
        src = self._one_second(tmp_path, 44100)
        results = []
        for i in range(2):
            results.append(
                await resample_playback(
                    source_path=src,
                    output_path=tmp_path / f"out{i}.pcm",
                    source_rate=44100,
                    target_rate=48000,
                    channel_count=2,
                )
            )
        assert results[0].content_hash == results[1].content_hash

    def test_filter_string(self) -> None:
        assert (
            playback_resample_filter(48000)
            == "aresample=48000:filter_size=64:exact_rational=1:dither_method=0"
        )


class TestDerivedFailures:
    @pytest.mark.asyncio
    async def test_missing_source(self, tmp_path: Path) -> None:
        with pytest.raises(DerivedFailedError, match="not found"):
            await downmix_monitoring(
                source_path=tmp_path / "nope.pcm",
                output_path=tmp_path / "out.pcm",
                sample_rate=44100,
                channel_count=2,
                pan_spec="pan=stereo|c0=c0|c1=c1",
            )

    @pytest.mark.asyncio
    async def test_bad_filter_fails_and_cleans_up(
        self, five_one_source: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.pcm"
        with pytest.raises(DerivedFailedError):
            await downmix_monitoring(
                source_path=five_one_source,
                output_path=out,
                sample_rate=44100,
                channel_count=6,
                pan_spec="pan=stereo|c0=c99",  # channel 99 does not exist
            )
        assert not out.exists()

    @pytest.mark.asyncio
    async def test_invalid_rates(self, five_one_source: Path, tmp_path: Path) -> None:
        with pytest.raises(DerivedFailedError, match="positive"):
            await resample_playback(
                source_path=five_one_source,
                output_path=tmp_path / "out.pcm",
                source_rate=44100,
                target_rate=0,
                channel_count=6,
            )

    @pytest.mark.asyncio
    async def test_cancelled_before_start(self, five_one_source: Path, tmp_path: Path) -> None:
        event = threading.Event()
        event.set()
        with pytest.raises(DerivedCancelledError):
            await downmix_monitoring(
                source_path=five_one_source,
                output_path=tmp_path / "out.pcm",
                sample_rate=44100,
                channel_count=6,
                pan_spec="pan=stereo|c0=c0|c1=c1",
                cancel_event=event,
            )
        assert not (tmp_path / "out.pcm").exists()

    @pytest.mark.asyncio
    async def test_cancelled_mid_run_removes_partial(
        self, five_one_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = tmp_path / "fakebin"
        fake.mkdir()
        (fake / "ffmpeg").write_text(
            "#!/bin/sh\nsleep 30\n",
        )
        (fake / "ffmpeg").chmod(0o755)
        monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")

        event = threading.Event()

        def _cancel_later() -> None:
            import time

            time.sleep(0.5)
            event.set()

        canceller = threading.Thread(target=_cancel_later, daemon=True)
        canceller.start()
        out = tmp_path / "out.pcm"
        with pytest.raises(DerivedCancelledError):
            await resample_playback(
                source_path=five_one_source,
                output_path=out,
                source_rate=44100,
                target_rate=48000,
                channel_count=6,
                cancel_event=event,
            )
        assert not out.exists()

    @pytest.mark.asyncio
    async def test_timeout(self, five_one_source: Path, tmp_path: Path) -> None:
        with pytest.raises(DerivedTimeoutError):
            await resample_playback(
                source_path=five_one_source,
                output_path=tmp_path / "out.pcm",
                source_rate=44100,
                target_rate=48000,
                channel_count=6,
                timeout_seconds=0.05,
            )
        assert not (tmp_path / "out.pcm").exists()

    @pytest.mark.asyncio
    async def test_insufficient_disk_space(
        self, five_one_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil
        from collections import namedtuple

        disk_usage = namedtuple("disk_usage", ["total", "used", "free"])

        def _no_space(_path: Path) -> object:
            return disk_usage(0, 0, 0)

        monkeypatch.setattr(shutil, "disk_usage", _no_space)
        with pytest.raises(InsufficientDiskSpaceError):
            await downmix_monitoring(
                source_path=five_one_source,
                output_path=tmp_path / "out.pcm",
                sample_rate=44100,
                channel_count=6,
                pan_spec="pan=stereo|c0=c0|c1=c1",
            )


class TestWavRoundTrip:
    @pytest.mark.asyncio
    async def test_wav_generated_fixture_decodes_to_pcm(
        self, tmp_path: Path
    ) -> None:
        """Sanity: the WAV helper + ffmpeg produce the same PCM as numpy."""
        sr = 44100
        data = np.stack([_sine(0.1, sr, 440.0), _sine(0.1, sr, 440.0, 0.5)], axis=1)
        wav = tmp_path / "a.wav"
        _write_wav(wav, data, sr, 2)
        pcm = tmp_path / "a.pcm"
        _decode_wav_to_f32le(wav, pcm, 2)
        decoded = np.fromfile(pcm, dtype="<f4").reshape(-1, 2)
        assert decoded.shape[0] == data.shape[0]
        assert np.allclose(decoded, data, atol=8.0 / 32767)
