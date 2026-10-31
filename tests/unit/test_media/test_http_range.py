"""HTTP single-range parsing and f32le slicing (t19)."""

from __future__ import annotations

import numpy as np
import pytest

from basseparate.media import (
    ByteRange,
    PcmSlice,
    RangeError,
    parse_http_range,
    pcm_response_headers,
    read_pcm_slice,
    unsatisfiable_range_headers,
)


def write_pcm(tmp_path):
    frames, channels = 10, 2
    samples = np.arange(frames * channels, dtype="<f4").reshape(frames, channels)
    path = tmp_path / "pcm.f32"
    path.write_bytes(samples.tobytes())
    return path, samples, frames, channels


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-9", (0, 9)),
        ("bytes=0-0", (0, 0)),
        ("bytes=90-", (90, 99)),
        ("bytes=-10", (90, 99)),
        ("bytes=-1000", (0, 99)),
        ("bytes=0-1000", (0, 99)),
    ],
)
def test_parse_http_range_accepts_single_ranges(header: str, expected: tuple[int, int]) -> None:
    parsed = parse_http_range(header, 100)
    assert parsed == ByteRange(start=expected[0], end=expected[1], total=100)
    assert parsed.content_range == f"bytes {expected[0]}-{expected[1]}/100"


def test_parse_http_range_ignores_other_units_and_missing_header() -> None:
    assert parse_http_range(None, 100) is None
    assert parse_http_range("", 100) is None
    assert parse_http_range("items=0-1", 100) is None


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("bytes=100-200", "outside"),
        ("bytes=10-9", "before"),
        ("bytes=-0", "outside"),
        ("bytes=0-1,3-4", "multiple"),
        ("bytes=abc", "invalid"),
        ("bytes=", "empty"),
    ],
)
def test_parse_http_range_rejects_unsatisfiable_or_unsupported(header: str, message: str) -> None:
    with pytest.raises(RangeError, match=message):
        parse_http_range(header, 100)


@pytest.mark.parametrize("header", ["bytes=0-0", "bytes=0-", "bytes=-1"])
def test_any_range_on_an_empty_asset_is_unsatisfiable(header: str) -> None:
    with pytest.raises(RangeError, match="outside"):
        parse_http_range(header, 0)


def test_read_pcm_slice_returns_exact_frame_aligned_bytes(tmp_path) -> None:
    path, samples, frames, channels = write_pcm(tmp_path)
    frame_size = channels * 4
    result = read_pcm_slice(
        path,
        channels=channels,
        total_frames=frames,
        range_header=f"bytes={2 * frame_size}-{4 * frame_size - 1}",
        start=0,
        end=None,
    )
    assert isinstance(result, PcmSlice)
    assert result.status_code == 206
    assert (result.start_frame, result.end_frame) == (2, 4)
    assert result.content_range == (
        f"bytes {2 * frame_size}-{4 * frame_size - 1}/{frames * frame_size}"
    )
    assert result.payload == path.read_bytes()[2 * frame_size : 4 * frame_size]
    assert np.frombuffer(result.payload, dtype="<f4").reshape(-1, channels).tolist() == (
        samples[2:4].tolist()
    )


def test_read_pcm_slice_keeps_query_behaviour_without_range(tmp_path) -> None:
    path, samples, frames, channels = write_pcm(tmp_path)
    result = read_pcm_slice(
        path,
        channels=channels,
        total_frames=frames,
        range_header=None,
        start=3,
        end=6,
    )
    assert result.status_code == 200
    assert result.content_range is None
    assert result.payload == samples[3:6].tobytes()
    assert (result.start_frame, result.end_frame) == (3, 6)

    full = read_pcm_slice(
        path,
        channels=channels,
        total_frames=frames,
        range_header=None,
        start=0,
        end=None,
    )
    assert full.payload == path.read_bytes()
    assert full.status_code == 200


def test_read_pcm_slice_rejects_non_frame_aligned_range(tmp_path) -> None:
    path, _samples, frames, channels = write_pcm(tmp_path)
    with pytest.raises(RangeError, match="aligned"):
        read_pcm_slice(
            path,
            channels=channels,
            total_frames=frames,
            range_header="bytes=1-8",
            start=0,
            end=None,
        )


def test_read_pcm_slice_rejects_a_file_size_mismatch(tmp_path) -> None:
    path, _samples, frames, channels = write_pcm(tmp_path)
    with pytest.raises(Exception, match="size"):
        read_pcm_slice(
            path,
            channels=channels,
            total_frames=frames + 1,
            range_header=None,
            start=0,
            end=None,
        )


def test_response_headers_include_accept_ranges_and_content_range() -> None:
    headers = pcm_response_headers(
        start_frame=2,
        end_frame=5,
        total_frames=10,
        sample_rate=48_000,
        channels=2,
        content_range="bytes 16-39/80",
    )
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-range"] == "bytes 16-39/80"
    assert headers["x-frame-count"] == "3"
    assert headers["x-total-frames"] == "10"
    assert unsatisfiable_range_headers(80) == {
        "accept-ranges": "bytes",
        "content-range": "bytes */80",
    }
