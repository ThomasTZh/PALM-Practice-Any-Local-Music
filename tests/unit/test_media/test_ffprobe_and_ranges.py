"""Boundary mapping for ffprobe output and frame-range validation."""

from __future__ import annotations

import numpy as np
import pytest

from basseparate.media import (
    MediaError,
    canonical_channels,
    file_sha256,
    parse_ffprobe,
    read_pcm_range,
    validate_frame_range,
)


def payload(rate: str = "44100", channels: int = 1, duration: str = "2.000000") -> dict:
    return {
        "streams": [
            {"codec_type": "video", "codec_name": "mjpeg"},
            {
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "sample_rate": rate,
                "channels": channels,
                "duration": duration,
                "bit_rate": "705600",
            },
        ],
        "format": {"format_name": "wav", "duration": duration},
    }


def test_parse_ffprobe_44k_mono() -> None:
    info = parse_ffprobe(payload())
    assert info.sample_rate == 44_100
    assert info.channels == 1
    assert info.duration_seconds == pytest.approx(2.0)
    assert info.codec == "pcm_s16le"
    assert info.bit_rate == 705_600
    assert info.source_format == "wav"


def test_parse_ffprobe_48k_stereo() -> None:
    info = parse_ffprobe(payload(rate="48000", channels=2, duration="1.5"))
    assert (info.sample_rate, info.channels, info.duration_seconds) == (48_000, 2, 1.5)


def test_parse_ffprobe_prefers_stream_duration_and_falls_back_to_format() -> None:
    data = payload()
    del data["streams"][1]["duration"]
    assert parse_ffprobe(data).duration_seconds == pytest.approx(2.0)
    data["format"]["duration"] = "3.25"
    assert parse_ffprobe(data).duration_seconds == pytest.approx(3.25)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["streams"].pop(1), "no audio stream"),
        (lambda data: data["streams"][1].update(sample_rate="fast"), "sample rate"),
        (lambda data: data["streams"][1].update(channels="many"), "channel"),
        (lambda data: data.update(streams=[]), "no audio stream"),
        (lambda data: data["streams"][1].pop("sample_rate"), "sample rate"),
    ],
)
def test_parse_ffprobe_rejects_invalid_payloads(mutate, message: str) -> None:
    data = payload()
    mutate(data)
    with pytest.raises(MediaError, match=message):
        parse_ffprobe(data)


def test_parse_ffprobe_requires_mapping() -> None:
    with pytest.raises(MediaError, match="object"):
        parse_ffprobe([])


def test_canonical_channels_keeps_mono_and_stereo() -> None:
    assert canonical_channels(1) == 1
    assert canonical_channels(2) == 2
    assert canonical_channels(6) == 2


def test_file_sha256_matches_hashlib(tmp_path) -> None:
    import hashlib

    path = tmp_path / "blob.bin"
    path.write_bytes(b"basseparate")
    assert file_sha256(path) == hashlib.sha256(b"basseparate").hexdigest()


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0, None, (0, 100)),
        (0, 100, (0, 100)),
        (10, 20, (10, 20)),
        (100, None, (100, 100)),
        (100, 100, (100, 100)),
    ],
)
def test_validate_frame_range_accepts_inside_range(
    start: int, end: int | None, expected: tuple[int, int]
) -> None:
    assert validate_frame_range(start, end, total_frames=100) == expected


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (-1, 10, "negative"),
        (0, 101, "outside"),
        (101, 101, "outside"),
        (30, 20, "before"),
        (0, -1, "negative"),
    ],
)
def test_validate_frame_range_rejects_outside(start: int, end: int | None, message: str) -> None:
    with pytest.raises(MediaError, match=message):
        validate_frame_range(start, end, total_frames=100)


def test_read_pcm_range_returns_exact_interleaved_frames(tmp_path) -> None:
    frames, channels = 64, 2
    pcm = np.arange(frames * channels, dtype="<f4").reshape(frames, channels)
    path = tmp_path / "pcm.f32"
    path.write_bytes(pcm.tobytes())

    block = read_pcm_range(path, channels=channels, start=10, end=25, total_frames=frames)
    assert len(block) == 15 * channels * 4
    np.testing.assert_array_equal(
        np.frombuffer(block, dtype="<f4").reshape(15, channels), pcm[10:25]
    )
    assert read_pcm_range(path, channels=channels, start=64, end=64, total_frames=frames) == b""


def test_read_pcm_range_rejects_truncated_file(tmp_path) -> None:
    path = tmp_path / "pcm.f32"
    path.write_bytes(np.zeros((10, 2), dtype="<f4").tobytes())
    with pytest.raises(MediaError, match="truncated"):
        read_pcm_range(path, channels=2, start=0, end=20, total_frames=20)
