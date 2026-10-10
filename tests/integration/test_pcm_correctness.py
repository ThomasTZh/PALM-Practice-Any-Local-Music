"""PCM correctness suite (M1.16, spec §18.4).

Verifies the canonical decode pipeline (ffmpeg → raw f32le) preserves
what the source contains: exact normalized values, channel order, time
zero, EOF, binary byte order, and above-full-scale finiteness. Lossless
inputs are compared exactly; the lossy (MP3) case is compared by marker
position and timing, per §18.4's lossy policy.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from synth import (
    above_full_scale,
    encode_with_ffmpeg,
    sine,
    wav_s16_bytes,
    write_wav_f32,
    write_wav_s16,
)

from basseparate.media.decode import decode_canonical

RATE = 44100


def _decode(path: Path, rate: int = RATE, channels: int = 1, stream_index: int = 0):
    out = path.with_name(path.stem + ".out.pcm")
    result = asyncio.run(
        decode_canonical(
            source_path=path,
            output_path=out,
            stream_index=stream_index,
            sample_rate=rate,
            channel_count=channels,
        )
    )
    return result, out


def _read(path: Path, channels: int) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype="<f4").reshape(-1, channels)


class TestLosslessValues:
    def test_s16_decodes_to_normalized_exact(self, tmp_path: Path) -> None:
        s16 = np.arange(-1000, 1000, dtype="<i2")
        src = tmp_path / "ramp.wav"
        src.write_bytes(wav_s16_bytes(s16.tobytes(), RATE))

        res, out = _decode(src, channels=1)
        assert res.frame_count == len(s16)

        decoded = _read(out, 1).ravel()
        expected = (s16.astype("<f8") / 32768.0).astype("<f4")
        assert np.array_equal(decoded, expected), "s16 decode must be v / 32768 exactly"

    def test_byte_order_is_little_endian(self, tmp_path: Path) -> None:
        s16 = np.arange(-500, 500, dtype="<i2")
        src = tmp_path / "order.wav"
        src.write_bytes(wav_s16_bytes(s16.tobytes(), RATE))

        _res, out = _decode(src, channels=1)
        expected = (s16.astype("<f8") / 32768.0).astype("<f4")
        assert out.read_bytes() == expected.tobytes(), (
            "decoded f32le bytes must match the normalized source byte-for-byte"
        )

    def test_channel_order_preserved(self, tmp_path: Path) -> None:
        n = 4410
        left = (0.5 * np.sin(2.0 * np.pi * 440.0 * np.arange(n) / RATE)).astype("<f4")
        right = np.zeros(n, dtype="<f4")
        right[100] = 1.0
        src = tmp_path / "channels.wav"
        write_wav_s16(src, np.stack([left, right], axis=1), RATE)

        _res, out = _decode(src, channels=2)
        arr = _read(out, 2)
        # The full-scale impulse is unique in the file: it must sit in
        # channel 1 at frame 100, not in channel 0.
        peak = np.unravel_index(np.argmax(np.abs(arr)), arr.shape)
        assert peak == (100, 1)
        assert arr[100, 1] == pytest.approx(32767.0 / 32768.0, abs=1e-6)
        assert np.abs(arr[:, 0]).max() < 0.51, "channel 0 must carry the tone only"


class TestTimeZeroAndEOF:
    def test_time_zero_first_frame_intact(self, tmp_path: Path) -> None:
        n = 4410
        sig = np.zeros(n, dtype="<f4")
        sig[0] = 1.0
        src = tmp_path / "t0.wav"
        write_wav_s16(src, sig, RATE)

        res, out = _decode(src, channels=1)
        assert res.frame_count == n, "no leading priming may be inserted"
        arr = _read(out, 1).ravel()
        assert arr[0] == pytest.approx(32767.0 / 32768.0, abs=1e-6)

    def test_eof_last_frame_intact(self, tmp_path: Path) -> None:
        n = 4410
        sig = np.zeros(n, dtype="<f4")
        sig[-1] = -1.0
        src = tmp_path / "eof.wav"
        write_wav_s16(src, sig, RATE)

        res, out = _decode(src, channels=1)
        assert res.frame_count == n, "no trailing silence, no cut-off tail"
        arr = _read(out, 1).ravel()
        assert arr[-1] == pytest.approx(-32767.0 / 32768.0, abs=1e-6)


class TestAboveFullScale:
    def test_f32_above_full_scale_finite(self, tmp_path: Path) -> None:
        mono = above_full_scale(RATE, RATE, peak=2.0)
        src = tmp_path / "hot.wav"
        write_wav_f32(src, np.stack([mono, mono], axis=1), RATE)

        res, out = _decode(src, channels=2)
        assert res.frame_count == RATE
        arr = _read(out, 2)
        assert np.isfinite(arr).all(), "above-full-scale input must stay finite"
        assert arr.max() > 1.0, "above-full-scale content must not be clipped"
        assert arr.max() == pytest.approx(float(mono.max()), abs=1e-6)
        assert arr.min() == pytest.approx(float(mono.min()), abs=1e-6)


class TestLossyTiming:
    def test_mp3_keeps_time_zero_marker(self, tmp_path: Path) -> None:
        """No double encoder-delay trim: the t=0 marker must survive.

        MP3 priming trim is applied once by the decoder. A second trim
        (≈3300+ frames) would erase a marker placed at frame 0.
        """
        n = RATE
        sig = np.zeros((n, 2), dtype="<f4")
        sig[:, 0] = 0.5 * np.sin(2.0 * np.pi * 440.0 * np.arange(n) / RATE)
        sig[0, :] = 1.0
        sig[n // 2, :] = 1.0
        wav = tmp_path / "imp.wav"
        write_wav_s16(wav, sig, RATE)
        mp3 = tmp_path / "imp.mp3"
        encode_with_ffmpeg(wav, mp3, "-c:a", "libmp3lame", "-b:a", "192k")

        res, out = _decode(mp3, channels=2)
        assert 0.7 * n <= res.frame_count <= 1.3 * n
        arr = _read(out, 2)
        mag = np.abs(arr).max(axis=1)

        # The t=0 impulse must land in the first 1000 frames (MP3 smears
        # it, but its peak stays near frame 0).
        assert mag[:1000].max() > 0.3, "t=0 marker lost: double delay trim?"
        # The mid-file marker must survive near n/2.
        window = n // 2 - 2000
        mid = mag[window : window + 4000]
        offset = int(mid.argmax())
        assert abs(window + offset - n // 2) < 500, "mid-file marker displaced"
        assert mid.max() > 0.3


class TestPartialFrames:
    def test_truncated_data_serves_no_partial_frame(self, tmp_path: Path) -> None:
        n = RATE
        src = tmp_path / "full.wav"
        write_wav_s16(src, sine(1.0, RATE), RATE)
        trunc = tmp_path / "trunc.wav"
        trunc.write_bytes(src.read_bytes()[:-1])  # drop one byte → odd frame count

        res, out = _decode(trunc, channels=1)
        assert res.frame_count == n - 1, "the partial frame must not be served"
        arr = _read(out, 1).ravel()
        source = sine(1.0, RATE)
        assert arr[-1] == pytest.approx(float(source[-2]), abs=0.01)
