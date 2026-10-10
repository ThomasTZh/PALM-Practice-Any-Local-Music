"""FFmpeg-based format fixtures (M1.16, spec §18.2).

Generates one fixture per codec/container combination with the
installed ffmpeg and probes which combinations the build actually
supports. Lossless formats must round-trip to the exact frame count;
lossy formats carry codec delay/priming and are checked with a
tolerance (same policy as ``tests/integration/test_decode.py``).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from synth import FFMPEG, sine, write_wav_s16


@dataclass(frozen=True)
class AudioFormat:
    name: str
    suffix: str
    encoder: str
    encoder_args: tuple[str, ...]
    lossless: bool


AUDIO_FORMATS: tuple[AudioFormat, ...] = (
    AudioFormat("flac", "flac", "flac", ("-c:a", "flac"), True),
    AudioFormat("mp3-cbr", "mp3", "libmp3lame", ("-c:a", "libmp3lame", "-b:a", "192k"), False),
    AudioFormat("mp3-vbr", "mp3", "libmp3lame", ("-c:a", "libmp3lame", "-q:a", "4"), False),
    AudioFormat("aac-mp4", "mp4", "aac", ("-c:a", "aac", "-f", "mp4"), False),
    AudioFormat("ogg-vorbis", "ogg", "libvorbis", ("-c:a", "libvorbis", "-f", "ogg"), False),
    AudioFormat("opus", "opus", "libopus", ("-c:a", "libopus", "-f", "ogg"), False),
    AudioFormat("aiff", "aiff", "pcm_s16le", ("-c:a", "pcm_s16le", "-f", "aiff"), True),
)

#: The video + cover-art fixtures need a video encoder and mjpeg.
VIDEO_ENCODER = "libx264"
COVER_ART_ENCODER = "mjpeg"


def available_encoders() -> set[str]:
    """The encoder names the installed ffmpeg can use (audio and video)."""
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Lines look like `` A....D aac ...`` / `` V....D libx264 ...``.
    return {
        line.split()[1]
        for line in out.splitlines()
        if line[:2] in (" A", " V") and len(line.split()) >= 2
    }


def _run(args: list[str]) -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", *args, "-y"],
        check=True,
        capture_output=True,
    )


def make_tone_wav(path: Path, seconds: float = 1.0, rate: int = 48000) -> None:
    """A two-channel tone WAV — the common encode source."""
    write_wav_s16(path, sine(seconds, rate, channels=2), rate)


def encode_audio(source_wav: Path, target: Path, fmt: AudioFormat) -> None:
    _run(["-i", str(source_wav), *fmt.encoder_args, str(target)])


def make_video_one_audio(path: Path, seconds: int = 1) -> None:
    """A video with exactly one audio stream (video = stream 0)."""
    _run(
        [
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", VIDEO_ENCODER, "-c:a", "aac", "-ac", "2", "-shortest", str(path),
        ]
    )


def make_video_two_audio(path: Path, seconds: int = 1) -> None:
    """A video with two labeled audio streams (1 = A, 2 = B)."""
    _run(
        [
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=880:duration={seconds}",
            "-map", "0", "-map", "1", "-map", "2",
            "-metadata:s:a:0", "title=Mix A",
            "-metadata:s:a:1", "title=Mix B",
            "-c:v", VIDEO_ENCODER, "-c:a", "aac", "-ac", "2", "-shortest", str(path),
        ]
    )


def make_video_no_audio(path: Path, seconds: int = 1) -> None:
    """A video with no audio stream at all."""
    _run(
        [
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=10",
            "-c:v", VIDEO_ENCODER, "-an", str(path),
        ]
    )


def make_audio_with_cover_art(path: Path, seconds: int = 1) -> None:
    """Audio with an attached cover-art picture (stream 1 = attached_pic)."""
    _run(
        [
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-f", "lavfi", "-i", f"color=c=red:size=64x64:rate=1:duration={seconds}",
            "-map", "0:a", "-map", "1:v",
            "-c:a", "aac", "-ac", "2", "-c:v", COVER_ART_ENCODER,
            "-disposition:v:0", "attached_pic", str(path),
        ]
    )


def probe_streams(path: Path) -> list[tuple[int, str]]:
    """(index, codec_type) for every stream in the file."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_type",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [(int(parts[0]), parts[1]) for parts in (line.split(",") for line in out.splitlines())]


def probe_audio_names(path: Path) -> dict[int, str]:
    """stream index -> ``name`` tag for audio streams ({} when absent).

    MP4 stores a stream's title in the ``name`` handler tag, so this is
    where the labels written with ``-metadata:s:a:N title=...`` land.
    """
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index:stream_tags=name",
            "-of", "default=nw=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names: dict[int, str] = {}
    index: int | None = None
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key == "index":
            index = int(value)
        elif key == "TAG:name" and index is not None:
            names[index] = value
    return names
