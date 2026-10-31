"""Peak levels: the binary format is shared with the browser waveform pane.

The reference in this file is computed independently (one slice per bucket) so
the encoder, decoder and streaming accumulator cannot agree with themselves and
still pass. Values are quantised to int16 by the wire format, so the assertion
is exact against the same quantisation applied to the reference.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest
from numpy.typing import NDArray

from basseparate.peaks import (
    PEAK_BUCKET_SIZES,
    PEAK_HEADER_SIZE,
    PEAK_MAGIC,
    PEAK_VERSION,
    PeakAccumulator,
    PeakBuckets,
    compute_peaks,
    compute_peaks_from_file,
    decode_peaks,
    encode_peaks,
)


def quantise(values: NDArray[np.float32]) -> NDArray[np.float32]:
    scaled = np.clip(values.astype(np.float64) * 32767.0, -32767.0, 32767.0)
    return (np.round(scaled) / 32767.0).astype(np.float32)


def reference(pcm: NDArray[np.float32], bucket_size: int) -> tuple[NDArray, NDArray]:
    frames, channels = pcm.shape
    count = (frames + bucket_size - 1) // bucket_size if frames else 0
    mins = np.zeros((count, channels), dtype=np.float32)
    maxs = np.zeros((count, channels), dtype=np.float32)
    for bucket in range(count):
        block = pcm[bucket * bucket_size : (bucket + 1) * bucket_size]
        mins[bucket] = block.min(axis=0)
        maxs[bucket] = block.max(axis=0)
    return mins, maxs


def sample_pcm(frames: int = 10_000, channels: int = 2) -> NDArray[np.float32]:
    """Deterministic signal with asymmetric peaks and a silent tail."""
    index = np.arange(frames, dtype=np.float32)
    left = 0.8 * np.sin(index * 0.01) + 0.05 * np.cos(index * 0.31)
    if channels == 1:
        return left.reshape(-1, 1).astype(np.float32)
    right = -0.6 * np.sin(index * 0.013) - 0.1 * np.cos(index * 0.07)
    pcm = np.stack([left, right], axis=1).astype(np.float32)
    pcm[-500:] = 0.0
    return pcm


def assert_peaks_match(peaks: PeakBuckets, pcm: NDArray[np.float32], size: int) -> None:
    expected_min, expected_max = reference(pcm, size)
    assert peaks.bucket_size == size
    assert peaks.channels == pcm.shape[1]
    assert peaks.frames == pcm.shape[0]
    assert peaks.bucket_count == expected_min.shape[0]
    np.testing.assert_array_equal(peaks.mins, expected_min)
    np.testing.assert_array_equal(peaks.maxs, expected_max)


@pytest.mark.parametrize("bucket_size", PEAK_BUCKET_SIZES)
@pytest.mark.parametrize("channels", [1, 2])
def test_compute_peaks_matches_reference(bucket_size: int, channels: int) -> None:
    pcm = sample_pcm(frames=70_000, channels=channels)
    peaks = compute_peaks(pcm, bucket_size)
    assert_peaks_match(peaks, pcm, bucket_size)


@pytest.mark.parametrize("bucket_size", PEAK_BUCKET_SIZES)
def test_encoded_peaks_match_quantised_reference(bucket_size: int) -> None:
    pcm = sample_pcm(frames=37_123)
    peaks = compute_peaks(pcm, bucket_size)
    payload = encode_peaks(peaks, sample_rate=48_000)

    assert payload[:4] == PEAK_MAGIC
    version, channels, reserved, sample_rate, count, samples_per_bucket = struct.unpack(
        "<BBHIII", payload[4:20]
    )
    assert (version, reserved, sample_rate, samples_per_bucket) == (
        PEAK_VERSION,
        0,
        48_000,
        bucket_size,
    )
    assert channels == 2
    assert len(payload) == PEAK_HEADER_SIZE + count * channels * 4

    decoded = decode_peaks(payload)
    assert decoded.sample_rate == 48_000
    assert decoded.bucket_size == bucket_size
    assert decoded.channels == 2
    assert decoded.bucket_count == count
    expected_min, expected_max = reference(pcm, bucket_size)
    np.testing.assert_array_equal(decoded.mins, quantise(expected_min))
    np.testing.assert_array_equal(decoded.maxs, quantise(expected_max))


@pytest.mark.parametrize("bucket_size", PEAK_BUCKET_SIZES)
def test_partial_final_bucket_uses_only_present_frames(bucket_size: int) -> None:
    frames = bucket_size * 2 + max(1, bucket_size // 3)
    pcm = sample_pcm(frames=frames, channels=2)
    peaks = compute_peaks(pcm, bucket_size)
    assert peaks.bucket_count == 3
    expected_min, expected_max = reference(pcm, bucket_size)
    np.testing.assert_array_equal(peaks.mins, expected_min)
    np.testing.assert_array_equal(peaks.maxs, expected_max)
    # The tail bucket is not padded with zeros: its extreme comes from real audio.
    assert peaks.maxs[-1, 0] == expected_max[-1, 0]
    assert peaks.mins[-1, 0] == expected_min[-1, 0]


def test_streaming_accumulator_matches_batch_for_ragged_blocks() -> None:
    pcm = sample_pcm(frames=25_000, channels=2)
    for bucket_size in PEAK_BUCKET_SIZES:
        accumulator = PeakAccumulator(bucket_size=bucket_size, channels=2)
        position = 0
        for block_frames in (1, 7, 255, 256, 1000, 4096, 16384, 3261):
            block = pcm[position : position + block_frames]
            if block.size == 0:
                continue
            accumulator.add(block)
            position += block.shape[0]
        if position < pcm.shape[0]:
            accumulator.add(pcm[position:])
        streamed = accumulator.finish()
        batch = compute_peaks(pcm, bucket_size)
        assert_peaks_match(streamed, pcm, bucket_size)
        np.testing.assert_array_equal(streamed.mins, batch.mins)
        np.testing.assert_array_equal(streamed.maxs, batch.maxs)


def test_empty_pcm_round_trips_to_empty_peaks() -> None:
    pcm = np.zeros((0, 2), dtype=np.float32)
    peaks = compute_peaks(pcm, 1024)
    assert peaks.bucket_count == 0
    decoded = decode_peaks(encode_peaks(peaks, sample_rate=44_100))
    assert decoded.bucket_count == 0
    assert decoded.mins.shape == (0, 2)


def test_peaks_from_file_match_in_memory(tmp_path) -> None:
    pcm = sample_pcm(frames=90_000, channels=2)
    path = tmp_path / "pcm.f32"
    path.write_bytes(pcm.astype("<f4").tobytes())
    for bucket_size in PEAK_BUCKET_SIZES:
        from_file = compute_peaks_from_file(
            path, channels=2, frames=pcm.shape[0], bucket_size=bucket_size, chunk_frames=4096
        )
        assert_peaks_match(from_file, pcm, bucket_size)


def test_decode_rejects_corrupt_headers() -> None:
    peaks = compute_peaks(sample_pcm(frames=2048, channels=1), 256)
    good = encode_peaks(peaks, sample_rate=44_100)
    with pytest.raises(ValueError, match="magic"):
        decode_peaks(b"XXXX" + good[4:])
    with pytest.raises(ValueError, match="version"):
        decode_peaks(good[:4] + bytes([PEAK_VERSION + 1]) + good[5:])
    with pytest.raises(ValueError, match="length"):
        decode_peaks(good[:-4])


def test_compute_peaks_rejects_invalid_shapes() -> None:
    with pytest.raises(ValueError, match="2-dimensional"):
        compute_peaks(np.zeros(10, dtype=np.float32), 256)
    with pytest.raises(ValueError, match="bucket size"):
        compute_peaks(np.zeros((10, 1), dtype=np.float32), 0)
