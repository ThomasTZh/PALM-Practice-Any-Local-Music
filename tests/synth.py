"""Shared synthetic audio fixtures (M1.16, spec §18.1).

Pure Python + numpy; no external services. Signal generators return
``<f4`` arrays (mono ``(N,)``, multi-channel ``(N, C)``). The WAV
writers support 16-bit PCM and IEEE float — float is required for
above-full-scale content, which s16 would clip.

The long fixture (60-minute recording, §18.1.15) is generated on
demand into a temp path and never committed.

Timestamp gap/overlap fixtures (§18.1.13/14) are not constructible at
the file level with this toolset (container muxers normalize audio
timestamps); the production ``aresample=async=1`` discontinuity
policy is exercised at the filter level in
``tests/integration/test_decode.py`` (``TestResamplerPolicy``).
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import numpy as np

from basseparate.domain.waveform import BASE_BUCKET_FRAMES, TILE_BUCKETS

FFMPEG = "ffmpeg"

#: Frames per level-0 tile (bucket count × bucket frames).
TILE_FRAMES = TILE_BUCKETS * BASE_BUCKET_FRAMES


def _as_2d(samples: np.ndarray) -> np.ndarray:
    return samples if samples.ndim == 2 else samples[:, None]


def tone_frames(
    frames: int,
    rate: int,
    frequency: float = 440.0,
    amplitude: float = 0.5,
    channels: int = 1,
) -> np.ndarray:
    """A sine wave of an exact frame length, replicated per channel."""
    t = np.arange(frames, dtype="<f8") / rate
    mono = (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype("<f4")
    if channels == 1:
        return mono
    return np.tile(mono[:, None], (1, channels))


def sine(
    seconds: float,
    rate: int,
    frequency: float = 440.0,
    amplitude: float = 0.5,
    channels: int = 1,
) -> np.ndarray:
    """A sine wave of a whole-second duration (mono by default)."""
    return tone_frames(int(seconds * rate), rate, frequency, amplitude, channels)


def stereo_tones(
    seconds: float, rate: int, freq_left: float, freq_right: float
) -> np.ndarray:
    """Distinct left/right frequencies — the channel-order oracle."""
    t = np.arange(int(seconds * rate), dtype="<f8") / rate
    left = 0.5 * np.sin(2.0 * np.pi * freq_left * t)
    right = 0.5 * np.sin(2.0 * np.pi * freq_right * t)
    return np.stack([left, right], axis=1).astype("<f4")


def impulses(
    total_frames: int,
    rate: int,
    at: int | list[int],
    channels: int = 1,
    value: float = 1.0,
) -> np.ndarray:
    """Silence with impulses at known frames (sample-exact)."""
    out = np.zeros((total_frames, channels), dtype="<f4")
    for pos in at if isinstance(at, list) else [at]:
        if 0 <= pos < total_frames:
            out[pos] = value
    return out


def silence(frames: int, rate: int, channels: int = 1) -> np.ndarray:
    """Exact silence (all-zero samples)."""
    return np.zeros((frames, channels), dtype="<f4")


def dc_offset(frames: int, rate: int, offset: float = 0.25, channels: int = 1) -> np.ndarray:
    """A constant non-zero level (DC offset)."""
    return np.full((frames, channels), offset, dtype="<f4")


def full_scale(frames: int, rate: int) -> np.ndarray:
    """Alternating ±1.0 — the largest representable signal."""
    out = np.zeros(frames, dtype="<f4")
    out[::2] = 1.0
    out[1::2] = -1.0
    return out


def above_full_scale(frames: int, rate: int, peak: float = 2.0) -> np.ndarray:
    """Finite samples beyond ±1 (only representable in float WAV)."""
    t = np.arange(frames, dtype="<f8") / rate
    return (peak * np.sin(2.0 * np.pi * 440.0 * t)).astype("<f4")


def short_in_bucket(frames: int, rate: int, channels: int = 1) -> np.ndarray:
    """A tone whose length is not a multiple of the peak bucket.

    The default length is one bucket plus 7 frames, leaving a final
    partial bucket.
    """
    n = frames if frames % BASE_BUCKET_FRAMES else BASE_BUCKET_FRAMES + 7
    return tone_frames(n, rate, channels=channels)


def block_edge_impulses(total_frames: int, rate: int, channels: int = 1) -> np.ndarray:
    """Impulses one frame before/after bucket edges and tile boundaries."""
    at: set[int] = set()
    for edge in range(0, total_frames, BASE_BUCKET_FRAMES):
        if edge - 1 >= 0:
            at.add(edge - 1)
        at.add(edge)
    for tile_edge in range(0, total_frames, TILE_FRAMES):
        if tile_edge - 1 >= 0:
            at.add(tile_edge - 1)
        at.add(tile_edge)
    return impulses(total_frames, rate, sorted(at), channels=channels)


def channel_impulses(frames: int, rate: int, channels: int) -> np.ndarray:
    """One impulse per channel at a distinct frame (5.1 / 7.1 oracles)."""
    out = np.zeros((frames, channels), dtype="<f4")
    for c in range(channels):
        pos = min(c + 1, frames - 1)
        out[pos, c] = 1.0
    return out


def _wav_header(pcm: bytes, rate: int, channels: int, fmt: int, bits: int) -> bytes:
    byte_rate = rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, fmt, channels, rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
    )


def wav_s16_bytes(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    """Wrap raw 16-bit little-endian PCM in a WAV container (bytes)."""
    return _wav_header(pcm, rate, channels, fmt=1, bits=16) + pcm


def write_wav_s16(path: Path, samples: np.ndarray, rate: int) -> None:
    """Write samples (clipped to ±1) as a 16-bit PCM WAV file."""
    arr = _as_2d(samples)
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    path.write_bytes(_wav_header(pcm, rate, arr.shape[1], fmt=1, bits=16) + pcm)


def write_wav_f32(path: Path, samples: np.ndarray, rate: int) -> None:
    """Write samples as an IEEE float (32-bit) WAV file (no clipping)."""
    arr = _as_2d(samples).astype("<f4")
    pcm = arr.tobytes()
    path.write_bytes(_wav_header(pcm, rate, arr.shape[1], fmt=3, bits=32) + pcm)


def long_wav_s16(
    path: Path,
    seconds: int,
    rate: int,
    channels: int = 1,
    frequency: float = 220.0,
    amplitude: float = 0.25,
) -> Path:
    """Write a long s16 WAV in one-second chunks (the §18.1.15 fixture).

    Generated on demand; the file is never committed. Memory usage is
    bounded to one second of samples.
    """
    total_bytes = seconds * rate * channels * 2
    # The header sizes are known upfront: build it with the final length.
    header = _wav_header(b"", rate, channels, fmt=1, bits=16)
    header = header[:4] + struct.pack("<I", 36 + total_bytes) + header[8:]
    header = header[:40] + struct.pack("<I", total_bytes)
    with path.open("wb") as handle:
        handle.write(header)
        for _ in range(seconds):
            chunk = tone_frames(rate, rate, frequency, amplitude, channels)
            pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            handle.write(pcm)
    return path


def encode_with_ffmpeg(input_path: Path, output_path: Path, *extra: str) -> None:
    """Encode one file with the installed ffmpeg (raises on failure)."""
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(input_path),
            *extra,
            "-y",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )
