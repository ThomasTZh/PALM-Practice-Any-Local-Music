"""Format fixture round-trips (M1.16, spec §18.2).

Each codec/container combination is encoded with the installed ffmpeg
and decoded back through the production ``decode_canonical`` path.
Lossless formats must return the exact frame count; lossy formats
carry codec delay/priming and are checked with a tolerance. Missing
encoders skip (with a recorded reason) rather than fail.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from formats import (
    AUDIO_FORMATS,
    COVER_ART_ENCODER,
    VIDEO_ENCODER,
    AudioFormat,
    available_encoders,
    encode_audio,
    make_audio_with_cover_art,
    make_tone_wav,
    make_video_no_audio,
    make_video_one_audio,
    make_video_two_audio,
    probe_audio_names,
    probe_streams,
)
from synth import above_full_scale, sine, write_wav_f32, write_wav_s16

from basseparate.domain.representation import CanonicalDecodeResult
from basseparate.media.decode import DecodeFailedError, decode_canonical

SECONDS = 1.0
RATE = 48000
CHANNELS = 2

encoders = available_encoders()


def _skip_if_missing(fmt: AudioFormat) -> None:
    if fmt.encoder not in encoders:
        pytest.skip(f"installed ffmpeg lacks the '{fmt.encoder}' encoder")


def _decode(path: Path, stream_index: int = 0) -> CanonicalDecodeResult:
    out = path.with_suffix(".out.pcm")
    return asyncio.run(
        decode_canonical(
            source_path=path,
            output_path=out,
            stream_index=stream_index,
            sample_rate=RATE,
            channel_count=CHANNELS,
        )
    )


def _finite_nonzero(pcm: Path, channels: int = CHANNELS) -> np.ndarray:
    arr = np.frombuffer(pcm.read_bytes(), dtype="<f4").reshape(-1, channels)
    assert np.isfinite(arr).all(), "decoded samples must be finite"
    assert np.abs(arr).max() > 0.01, "decoded audio must have energy"
    return arr


class TestPcmWav:
    def test_s16_round_trip_is_exact(self, tmp_path: Path) -> None:
        src = tmp_path / "tone.wav"
        write_wav_s16(src, sine(SECONDS, RATE, channels=CHANNELS), RATE)
        res = _decode(src)
        assert res.sample_rate == RATE
        assert res.channel_count == CHANNELS
        assert res.frame_count == int(SECONDS * RATE)
        _finite_nonzero(src.with_suffix(".out.pcm"))

    def test_f32_round_trip_keeps_above_full_scale(self, tmp_path: Path) -> None:
        src = tmp_path / "hot.wav"
        mono = above_full_scale(int(SECONDS * RATE), RATE, peak=2.0)
        write_wav_f32(src, np.stack([mono, mono], axis=1), RATE)
        res = _decode(src)
        assert res.frame_count == int(SECONDS * RATE)
        arr = _finite_nonzero(src.with_suffix(".out.pcm"))
        assert arr.max() > 1.0, "above-full-scale content must survive the f32 path"


@pytest.mark.parametrize("fmt", AUDIO_FORMATS, ids=[f.name for f in AUDIO_FORMATS])
class TestAudioFormats:
    def test_round_trip(self, tmp_path: Path, fmt: AudioFormat) -> None:
        _skip_if_missing(fmt)
        tone = tmp_path / "tone.wav"
        make_tone_wav(tone, SECONDS, RATE)
        source = tmp_path / f"tone.{fmt.suffix}"
        encode_audio(tone, source, fmt)
        assert source.stat().st_size > 0

        res = _decode(source)
        assert res.sample_rate == RATE
        assert res.channel_count == CHANNELS
        expected = int(SECONDS * RATE)
        if fmt.lossless:
            assert res.frame_count == expected
        else:
            # Codec delay/priming shifts the count; tolerate +/-30 %.
            assert 0.7 * expected <= res.frame_count <= 1.3 * expected
        _finite_nonzero(source.with_suffix(".out.pcm"))

    def test_redecode_is_byte_identical(self, tmp_path: Path, fmt: AudioFormat) -> None:
        _skip_if_missing(fmt)
        tone = tmp_path / "tone.wav"
        make_tone_wav(tone, SECONDS, RATE)
        source = tmp_path / f"tone.{fmt.suffix}"
        encode_audio(tone, source, fmt)

        r1 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=tmp_path / "r1.pcm",
                stream_index=0,
                sample_rate=RATE,
                channel_count=CHANNELS,
            )
        )
        r2 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=tmp_path / "r2.pcm",
                stream_index=0,
                sample_rate=RATE,
                channel_count=CHANNELS,
            )
        )
        assert r1.content_hash == r2.content_hash
        assert (tmp_path / "r1.pcm").read_bytes() == (tmp_path / "r2.pcm").read_bytes()


class TestVideoContainers:
    def test_one_audio_stream_decodes_by_index(self, tmp_path: Path) -> None:
        if VIDEO_ENCODER not in encoders or "aac" not in encoders:
            pytest.skip("installed ffmpeg lacks a video/aac encoder")
        video = tmp_path / "one.mp4"
        make_video_one_audio(video, 1)
        streams = probe_streams(video)
        assert [t for _, t in streams] == ["video", "audio"]

        res = _decode(video, stream_index=1)
        assert res.sample_rate == RATE
        assert 0.7 * RATE <= res.frame_count <= 1.3 * RATE

    def test_two_labeled_audio_streams(self, tmp_path: Path) -> None:
        if VIDEO_ENCODER not in encoders or "aac" not in encoders:
            pytest.skip("installed ffmpeg lacks a video/aac encoder")
        video = tmp_path / "two.mp4"
        make_video_two_audio(video, 1)
        streams = probe_streams(video)
        assert [t for _, t in streams] == ["video", "audio", "audio"]

        names = probe_audio_names(video)
        assert names.get(1) == "Mix A"
        assert names.get(2) == "Mix B"

        res = _decode(video, stream_index=2)
        assert res.sample_rate == RATE
        assert 0.7 * RATE <= res.frame_count <= 1.3 * RATE

    def test_video_without_audio_fails(self, tmp_path: Path) -> None:
        if VIDEO_ENCODER not in encoders:
            pytest.skip("installed ffmpeg lacks a video encoder")
        video = tmp_path / "silent.mp4"
        make_video_no_audio(video, 1)
        streams = probe_streams(video)
        assert all(t != "audio" for _, t in streams)
        with pytest.raises(DecodeFailedError):
            _decode(video, stream_index=0)

    def test_audio_with_cover_art(self, tmp_path: Path) -> None:
        if VIDEO_ENCODER not in encoders or COVER_ART_ENCODER not in encoders:
            pytest.skip("installed ffmpeg lacks a video/mjpeg encoder")
        media = tmp_path / "art.mp4"
        make_audio_with_cover_art(media, 1)
        streams = probe_streams(media)
        assert [t for _, t in streams] == ["audio", "video"]

        res = _decode(media, stream_index=0)
        assert res.sample_rate == RATE
        assert 0.7 * RATE <= res.frame_count <= 1.3 * RATE


class TestCapabilityMatrix:
    def test_expected_audio_encoders_present(self) -> None:
        """Record the matrix: every planned audio encoder is available.

        If a future ffmpeg build drops one, the corresponding round-trip
        test skips and this assertion documents the gap.
        """
        missing = [fmt.encoder for fmt in AUDIO_FORMATS if fmt.encoder not in encoders]
        assert not missing, f"installed ffmpeg lacks: {missing}"

    def test_video_encoders_present(self) -> None:
        missing = [e for e in (VIDEO_ENCODER, COVER_ART_ENCODER, "aac") if e not in encoders]
        assert not missing, f"installed ffmpeg lacks: {missing}"
