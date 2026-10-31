"""Waveform peak levels in the binary format shared with the browser.

Wire format (little endian, all integers unsigned unless stated)::

    0..3   "BSPK"
    4      u8   version (1)
    5      u8   channels
    6..7   u16  reserved (0)
    8..11  u32  sample rate
    12..15 u32  bucket count
    16..19 u32  samples per bucket
    then per bucket, per channel: int16 min, int16 max

Samples are normalised to [-1, 1] before quantisation by 32767. Keeping the
min/max pair preserves transients, which a single absolute peak would flatten.
The pure functions here are also used by the ranged PCM tests as the reference
implementation, so they stay free of FastAPI and filesystem concerns (the file
helper takes an explicit path).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]

PEAK_MAGIC = b"BSPK"
PEAK_VERSION = 1
PEAK_HEADER = struct.Struct("<4sBBHIII")
PEAK_HEADER_SIZE = PEAK_HEADER.size
PEAK_BUCKET_SIZES: tuple[int, ...] = (256, 1024, 4096, 16384)
PEAK_SCALE = 32767.0


def _quantise(values: FloatArray) -> NDArray[np.int16]:
    scaled = np.clip(np.asarray(values, dtype=np.float64) * PEAK_SCALE, -PEAK_SCALE, PEAK_SCALE)
    return np.round(scaled).astype(np.int16)


@dataclass(frozen=True)
class PeakBuckets:
    """Computed levels; ``mins``/``maxs`` are ``(bucket, channel)`` float arrays."""

    bucket_size: int
    channels: int
    frames: int
    mins: FloatArray
    maxs: FloatArray

    def __post_init__(self) -> None:
        expected = (self.bucket_count, self.channels)
        if self.bucket_size <= 0:
            raise ValueError("bucket size must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.frames < 0:
            raise ValueError("frames must not be negative")
        if self.mins.shape != expected or self.maxs.shape != expected:
            shapes = f"{self.mins.shape} and {self.maxs.shape}"
            raise ValueError(f"peak arrays must have shape {expected}, got {shapes}")

    @property
    def bucket_count(self) -> int:
        return bucket_count(self.frames, self.bucket_size)


def bucket_count(frames: int, bucket_size: int) -> int:
    if bucket_size <= 0:
        raise ValueError("bucket size must be positive")
    if frames <= 0:
        return 0
    return (frames + bucket_size - 1) // bucket_size


def compute_peaks(pcm: FloatArray, bucket_size: int) -> PeakBuckets:
    """Min/max per bucket for interleaved-by-row PCM shaped ``(frames, channels)``."""
    array = np.asarray(pcm, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError(f"PCM must be 2-dimensional (frames, channels), got {array.shape}")
    frames, channels = array.shape
    if bucket_size <= 0:
        raise ValueError("bucket size must be positive")

    full_buckets = frames // bucket_size
    mins = np.zeros((0, channels), dtype=np.float32)
    maxs = np.zeros((0, channels), dtype=np.float32)
    if full_buckets:
        blocks = array[: full_buckets * bucket_size].reshape(full_buckets, bucket_size, channels)
        mins = blocks.min(axis=1)
        maxs = blocks.max(axis=1)
    remainder = frames - full_buckets * bucket_size
    if remainder:
        tail = array[full_buckets * bucket_size :]
        mins = np.concatenate([mins, tail.min(axis=0, keepdims=True)], axis=0)
        maxs = np.concatenate([maxs, tail.max(axis=0, keepdims=True)], axis=0)
    return PeakBuckets(
        bucket_size=bucket_size,
        channels=channels,
        frames=frames,
        mins=np.asarray(mins, dtype=np.float32),
        maxs=np.asarray(maxs, dtype=np.float32),
    )


def encode_peaks(peaks: PeakBuckets, *, sample_rate: int) -> bytes:
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")
    count = peaks.bucket_count
    header = PEAK_HEADER.pack(
        PEAK_MAGIC,
        PEAK_VERSION,
        peaks.channels,
        0,
        sample_rate,
        count,
        peaks.bucket_size,
    )
    pairs = np.empty((count, peaks.channels, 2), dtype="<i2")
    pairs[..., 0] = _quantise(peaks.mins)
    pairs[..., 1] = _quantise(peaks.maxs)
    return header + pairs.tobytes()


@dataclass(frozen=True)
class DecodedPeaks:
    sample_rate: int
    bucket_size: int
    channels: int
    bucket_count: int
    mins: FloatArray
    maxs: FloatArray


def decode_peaks(payload: bytes) -> DecodedPeaks:
    if len(payload) < PEAK_HEADER_SIZE:
        raise ValueError(f"peak payload is shorter than the {PEAK_HEADER_SIZE}-byte header")
    header = PEAK_HEADER.unpack_from(payload, 0)
    magic, version, channels, _reserved, sample_rate, count, samples_per_bucket = header
    if magic != PEAK_MAGIC:
        raise ValueError(f"bad peak magic {magic!r}, expected {PEAK_MAGIC!r}")
    if version != PEAK_VERSION:
        raise ValueError(f"unsupported peak version {version}, expected {PEAK_VERSION}")
    if channels == 0:
        raise ValueError("peak payload declares zero channels")
    if samples_per_bucket == 0:
        raise ValueError("peak payload declares a zero bucket size")
    expected = PEAK_HEADER_SIZE + count * channels * 2 * 2
    if len(payload) != expected:
        raise ValueError(f"peak payload length {len(payload)} does not match header {expected}")
    pairs = np.frombuffer(payload, dtype="<i2", offset=PEAK_HEADER_SIZE, count=count * channels * 2)
    pairs = pairs.reshape(count, channels, 2)
    return DecodedPeaks(
        sample_rate=sample_rate,
        bucket_size=samples_per_bucket,
        channels=channels,
        bucket_count=count,
        mins=(pairs[..., 0].astype(np.float32) / PEAK_SCALE),
        maxs=(pairs[..., 1].astype(np.float32) / PEAK_SCALE),
    )


class PeakAccumulator:
    """Streaming min/max accumulator for blocks read from a decoded PCM file."""

    def __init__(self, *, bucket_size: int, channels: int) -> None:
        if bucket_size <= 0:
            raise ValueError("bucket size must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        self._bucket_size = bucket_size
        self._channels = channels
        self._frames = 0
        self._mins: list[FloatArray] = []
        self._maxs: list[FloatArray] = []
        self._pending = np.zeros((0, channels), dtype=np.float32)
        self._finished = False

    @property
    def frames(self) -> int:
        return self._frames

    def add(self, block: FloatArray) -> None:
        if self._finished:
            raise ValueError("cannot add frames after finish()")
        array = np.asarray(block, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self._channels:
            raise ValueError(f"block must have shape (frames, {self._channels}), got {array.shape}")
        if array.shape[0] == 0:
            return
        self._frames += array.shape[0]
        pending = (
            np.concatenate([self._pending, array], axis=0) if self._pending.shape[0] else array
        )
        full = pending.shape[0] // self._bucket_size
        if full:
            blocks = pending[: full * self._bucket_size].reshape(
                full, self._bucket_size, self._channels
            )
            self._mins.extend(blocks.min(axis=1))
            self._maxs.extend(blocks.max(axis=1))
            pending = pending[full * self._bucket_size :]
        self._pending = pending

    def finish(self) -> PeakBuckets:
        if self._finished:
            raise ValueError("finish() was already called")
        self._finished = True
        mins = list(self._mins)
        maxs = list(self._maxs)
        if self._pending.shape[0]:
            mins.append(self._pending.min(axis=0))
            maxs.append(self._pending.max(axis=0))
        mins_array = (
            np.stack(mins).astype(np.float32)
            if mins
            else np.zeros((0, self._channels), dtype=np.float32)
        )
        maxs_array = (
            np.stack(maxs).astype(np.float32)
            if maxs
            else np.zeros((0, self._channels), dtype=np.float32)
        )
        return PeakBuckets(
            bucket_size=self._bucket_size,
            channels=self._channels,
            frames=self._frames,
            mins=mins_array,
            maxs=maxs_array,
        )


def compute_peaks_from_file(
    path: Path,
    *,
    channels: int,
    frames: int,
    bucket_size: int,
    chunk_frames: int = 1 << 20,
) -> PeakBuckets:
    """Chunked peak extraction from an interleaved little-endian float32 file."""
    if frames < 0:
        raise ValueError("frames must not be negative")
    if chunk_frames <= 0:
        raise ValueError("chunk frames must be positive")
    accumulator = PeakAccumulator(bucket_size=bucket_size, channels=channels)
    frame_bytes = channels * 4
    chunk_bytes = chunk_frames * frame_bytes
    with Path(path).open("rb") as handle:
        while True:
            data = handle.read(chunk_bytes)
            if not data:
                break
            usable = len(data) // frame_bytes
            if usable == 0:
                break
            block = np.frombuffer(data[: usable * frame_bytes], dtype="<f4").reshape(
                usable, channels
            )
            accumulator.add(block)
    peaks = accumulator.finish()
    if peaks.frames != frames:
        raise ValueError(f"PCM file has {peaks.frames} frames, expected {frames}")
    return peaks
