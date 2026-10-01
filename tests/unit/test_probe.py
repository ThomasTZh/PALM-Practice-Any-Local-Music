"""Tests for the M1.3 ffprobe inspection module."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest

from basseparate.media.probe import (
    NoAudioStreamError,
    ProbeFailedError,
    ProbeTimeoutError,
    UnsupportedMediaError,
    parse_probe_data,
    probe_media,
    tool_versions,
)

_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def _make_wav(pcm: bytes | None = None, sample_rate: int = 44100, channels: int = 1) -> bytes:
    """Build a minimal valid 16-bit PCM WAV file."""
    if pcm is None:
        pcm = b"\x00\x00" * 4410
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    path = tmp_path / "tone.wav"
    path.write_bytes(_make_wav())
    return path


class TestProbeMedia:
    def test_wav_mono(self, wav_file: Path) -> None:
        result = asyncio.run(probe_media(wav_file))
        assert result.format_name == "wav"
        assert result.byte_count == wav_file.stat().st_size
        assert result.ffmpeg_version
        assert result.ffprobe_version
        assert len(result.audio_streams) == 1
        stream = result.audio_streams[0]
        assert stream.index == 0
        assert stream.codec == "pcm_s16le"
        assert stream.sample_rate == 44100
        assert stream.channel_count == 1

    def test_wav_stereo_layout(self, tmp_path: Path) -> None:
        path = tmp_path / "stereo.wav"
        path.write_bytes(_make_wav(pcm=b"\x00\x00" * 8820, channels=2))
        result = asyncio.run(probe_media(path))
        stream = result.audio_streams[0]
        assert stream.channel_count == 2
        assert stream.channel_layout == "stereo"

    def test_no_audio_stream(self, tmp_path: Path) -> None:
        path = tmp_path / "img.png"
        path.write_bytes(_PNG_BYTES)
        with pytest.raises(NoAudioStreamError):
            asyncio.run(probe_media(path))

    def test_unsupported_sample_rate(self, tmp_path: Path) -> None:
        path = tmp_path / "low.wav"
        path.write_bytes(_make_wav(sample_rate=4000))
        with pytest.raises(UnsupportedMediaError):
            asyncio.run(probe_media(path))

    def test_unsupported_channel_count(self, tmp_path: Path) -> None:
        path = tmp_path / "wide.wav"
        path.write_bytes(_make_wav(pcm=b"\x00\x00" * 16 * 9, channels=9))
        with pytest.raises(UnsupportedMediaError):
            asyncio.run(probe_media(path))

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ProbeFailedError):
            asyncio.run(probe_media(tmp_path / "nope.wav"))

    def test_timeout(self, wav_file: Path) -> None:
        with pytest.raises(ProbeTimeoutError):
            asyncio.run(probe_media(wav_file, timeout_seconds=0.001))

    def test_garbage_bytes_fail(self, tmp_path: Path) -> None:
        path = tmp_path / "garbage.bin"
        path.write_bytes(b"\x00\x01\x02" * 100)
        with pytest.raises(ProbeFailedError):
            asyncio.run(probe_media(path))


class TestToolVersions:
    def test_returns_non_empty_versions(self) -> None:
        ffmpeg_version, ffprobe_version = asyncio.run(tool_versions())
        assert ffmpeg_version
        assert ffprobe_version
        # Cached: a second call returns the same tuple object.
        again = asyncio.run(tool_versions())
        assert again == (ffmpeg_version, ffprobe_version)


class TestParseProbeData:
    def test_file_size_fallback(self) -> None:
        data = {
            "format": {"format_name": "wav", "tags": {}},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "44100",
                    "channels": 2,
                    "channel_layout": "stereo",
                    "disposition": {"default": 1},
                }
            ],
        }
        result = parse_probe_data(data, 12345, "7.1", "7.1")
        assert result.byte_count == 12345
        stream = result.audio_streams[0]
        assert stream.channel_count == 2
        assert stream.is_default is True

    def test_container_size_preferred(self) -> None:
        data = {
            "format": {"format_name": "wav", "size": "999", "tags": {}},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "44100",
                    "channels": 1,
                }
            ],
        }
        result = parse_probe_data(data, 12345, "7.1", "7.1")
        assert result.byte_count == 999

    def test_missing_format_rejected(self) -> None:
        with pytest.raises(ProbeFailedError):
            parse_probe_data({"streams": []}, 10, "7.1", "7.1")

    def test_missing_format_name_rejected(self) -> None:
        with pytest.raises(ProbeFailedError):
            parse_probe_data({"format": {}, "streams": []}, 10, "7.1", "7.1")

    def test_no_audio_streams_rejected(self) -> None:
        data = {
            "format": {"format_name": "png"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "png"}],
        }
        with pytest.raises(NoAudioStreamError):
            parse_probe_data(data, 10, "7.1", "7.1")

    def test_missing_sample_rate_rejected(self) -> None:
        data = {
            "format": {"format_name": "wav"},
            "streams": [{"index": 0, "codec_type": "audio", "codec_name": "pcm_s16le"}],
        }
        with pytest.raises(UnsupportedMediaError):
            parse_probe_data(data, 10, "7.1", "7.1")

    def test_video_streams_ignored(self) -> None:
        data = {
            "format": {"format_name": "matroska,webm"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "sample_rate": "1000",
                    "channels": 1,
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "48000",
                    "channels": 2,
                },
            ],
        }
        result = parse_probe_data(data, 10, "7.1", "7.1")
        assert len(result.audio_streams) == 1
        assert result.audio_streams[0].index == 1
