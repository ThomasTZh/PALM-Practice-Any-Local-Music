"""Integration tests for the M1.5 canonical decode engine (real ffmpeg).

Covers:
- Exact frame counts and preserved channel structure for PCM WAV input.
- Deterministic output (byte-identical re-decodes, stable SHA-256).
- Lossy containers (MP3 / AAC / Opus) with codec-delay tolerance.
- Failure modes: empty audio, truncated media, cancellation, timeout.
  Every failure path removes its partial output file.
- The discontinuity policy (``aresample=async=1``) at the resampler level:
  gaps are padded with silence, overlaps are trimmed, clean streams are
  untouched. File-level gap/overlap fixtures are not constructible with
  this toolset (container muxers normalize audio timestamps), so the
  policy is exercised on the exact filter the production decode runs.
"""

from __future__ import annotations

import asyncio
import struct
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest
from synth import FFMPEG, encode_with_ffmpeg, sine, write_wav_s16

from basseparate.media.decode import (
    DISCONTINUITY_FILTER,
    DecodeCancelledError,
    DecodeFailedError,
    DecodeProgress,
    DecodeTimeoutError,
    EmptyAudioError,
    decode_canonical,
)


def _run_filter_chain(filter_chain: str, out_path: Path) -> int:
    """Run the lavfi sine source through a filter chain; return output byte count."""
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-af",
            filter_chain,
            "-f",
            "f32le",
            "-y",
            str(out_path),
        ],
        check=True,
        capture_output=True,
    )
    return out_path.stat().st_size


class TestWavDecode:
    def test_mono_tone_exact_frames_and_amplitude(self, tmp_path: Path) -> None:
        source = tmp_path / "tone.wav"
        write_wav_s16(source, sine(0.1, 44100), 44100)
        out = tmp_path / "out.pcm"

        result = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out,
                stream_index=0,
                sample_rate=44100,
                channel_count=1,
                channel_layout="mono",  # production passes the probe's layout
            )
        )

        assert result.frame_count == 4410
        assert result.sample_rate == 44100
        assert result.channel_count == 1
        assert result.channel_layout == "mono"
        assert result.max_amplitude == pytest.approx(0.5, abs=0.02)
        assert result.pcm_byte_count == 4410 * 4
        assert result.decoded_duration_seconds == pytest.approx(0.1)
        assert result.estimated_duration_seconds is None
        assert out.is_file()
        assert out.stat().st_size == 4410 * 4

    def test_deterministic_two_runs(self, tmp_path: Path) -> None:
        source = tmp_path / "tone.wav"
        write_wav_s16(source, sine(0.25, 44100), 44100)
        out1 = tmp_path / "r1.pcm"
        out2 = tmp_path / "r2.pcm"

        r1 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out1,
                stream_index=0,
                sample_rate=44100,
                channel_count=1,
            )
        )
        r2 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out2,
                stream_index=0,
                sample_rate=44100,
                channel_count=1,
            )
        )

        assert r1.content_hash == r2.content_hash
        assert out1.read_bytes() == out2.read_bytes()

    def test_stereo_channels_preserved(self, tmp_path: Path) -> None:
        left = sine(0.1, 48000, frequency=440.0)
        right = sine(0.1, 48000, frequency=880.0)
        source = tmp_path / "stereo.wav"
        write_wav_s16(source, np.stack([left, right], axis=1), 48000)
        out = tmp_path / "out.pcm"

        result = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out,
                stream_index=0,
                sample_rate=48000,
                channel_count=2,
                channel_layout="stereo",
            )
        )

        assert result.frame_count == 4800
        assert result.channel_count == 2
        assert result.pcm_byte_count == 4800 * 8  # two float32 per frame

    def test_progress_reported(self, tmp_path: Path) -> None:
        source = tmp_path / "long.wav"
        write_wav_s16(source, sine(60.0, 48000), 48000)
        out = tmp_path / "out.pcm"
        events: list[DecodeProgress] = []

        asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out,
                stream_index=0,
                sample_rate=48000,
                channel_count=1,
                on_progress=events.append,
            )
        )

        assert len(events) >= 1
        for event in events:
            assert event.out_time_seconds >= 0
            assert event.dup_frames >= 0
            assert event.drop_frames >= 0
            assert event.fraction is None or 0.0 <= event.fraction <= 1.0
        times = [e.out_time_seconds for e in events]
        assert times == sorted(times)


@pytest.mark.parametrize(
    ("suffix", "encoder", "expected_rate"),
    [
        ("mp3", ["-c:a", "libmp3lame", "-q:a", "2"], 44100),
        ("m4a", ["-c:a", "aac", "-b:a", "128k"], 44100),
        ("ogg", ["-c:a", "libopus"], 48000),  # Opus is natively 48 kHz
    ],
)
class TestLossyContainers:
    def test_two_runs_byte_identical(
        self, tmp_path: Path, suffix: str, encoder: list[str], expected_rate: int
    ) -> None:
        tone = tmp_path / "tone.wav"
        write_wav_s16(tone, sine(1.0, 44100), 44100)
        source = tmp_path / f"tone.{suffix}"
        encode_with_ffmpeg(tone, source, *encoder)
        out1 = tmp_path / "r1.pcm"
        out2 = tmp_path / "r2.pcm"

        r1 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out1,
                stream_index=0,
                sample_rate=expected_rate,
                channel_count=1,
            )
        )
        r2 = asyncio.run(
            decode_canonical(
                source_path=source,
                output_path=out2,
                stream_index=0,
                sample_rate=expected_rate,
                channel_count=1,
            )
        )

        # Deterministic: identical bytes and hash across runs.
        assert r1.content_hash == r2.content_hash
        assert out1.read_bytes() == out2.read_bytes()
        assert r1.sample_rate == expected_rate
        # Codec delay/priming shifts the frame count; tolerate +/-30 %.
        assert 0.9 * expected_rate <= r1.frame_count <= 1.3 * expected_rate
        assert r1.max_amplitude > 0.1


class TestFailureModes:
    def test_empty_wav_raises_empty_audio(self, tmp_path: Path) -> None:
        # 78-byte WAV header with a zero-length data chunk.
        source = tmp_path / "empty.wav"
        header = (
            b"RIFF"
            + struct.pack("<I", 36)
            + b"WAVE"
            + b"fmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
            + b"data"
            + struct.pack("<I", 0)
        )
        source.write_bytes(header)
        out = tmp_path / "out.pcm"

        with pytest.raises(EmptyAudioError):
            asyncio.run(
                decode_canonical(
                    source_path=source,
                    output_path=out,
                    stream_index=0,
                    sample_rate=44100,
                    channel_count=1,
                )
            )
        assert not out.exists()

    def test_truncated_mp3_records_warnings(self, tmp_path: Path) -> None:
        tone = tmp_path / "tone.wav"
        write_wav_s16(tone, sine(1.0, 44100), 44100)
        full = tmp_path / "tone.mp3"
        encode_with_ffmpeg(tone, full, "-c:a", "libmp3lame", "-q:a", "2")
        truncated = tmp_path / "trunc.mp3"
        truncated.write_bytes(full.read_bytes()[:2000])
        out = tmp_path / "out.pcm"

        result = asyncio.run(
            decode_canonical(
                source_path=truncated,
                output_path=out,
                stream_index=0,
                sample_rate=44100,
                channel_count=1,
            )
        )

        # A truncated stream decodes, but the decoder warnings are recorded —
        # never a silent clean import.
        assert result.frame_count > 0
        assert len(result.decoder_warnings) > 0
        assert out.is_file()

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DecodeFailedError):
            asyncio.run(
                decode_canonical(
                    source_path=tmp_path / "nope.wav",
                    output_path=tmp_path / "out.pcm",
                    stream_index=0,
                    sample_rate=44100,
                    channel_count=1,
                )
            )

    def test_cancel_mid_decode_removes_output(self, tmp_path: Path) -> None:
        # An hour of audio: the decode (~1.2 s on fast hardware) outlasts the
        # cancel delay + 100 ms poll window by a wide margin. Cancellation is
        # triggered by a timer, not by progress events, because the progress
        # muxer emits sparsely during very fast decodes.
        import time

        source = tmp_path / "long.wav"
        write_wav_s16(source, sine(3600.0, 48000), 48000)
        out = tmp_path / "out.pcm"
        cancel_event = threading.Event()

        def _cancel_soon() -> None:
            time.sleep(0.2)
            cancel_event.set()

        t = threading.Thread(target=_cancel_soon, daemon=True)
        t.start()
        with pytest.raises(DecodeCancelledError):
            asyncio.run(
                decode_canonical(
                    source_path=source,
                    output_path=out,
                    stream_index=0,
                    sample_rate=48000,
                    channel_count=1,
                    cancel_event=cancel_event,
                )
            )
        t.join(timeout=5)
        assert cancel_event.is_set()
        assert not out.exists()

    def test_cancel_before_start_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "tone.wav"
        write_wav_s16(source, sine(0.1, 44100), 44100)
        cancel_event = threading.Event()
        cancel_event.set()

        with pytest.raises(DecodeCancelledError):
            asyncio.run(
                decode_canonical(
                    source_path=source,
                    output_path=tmp_path / "out.pcm",
                    stream_index=0,
                    sample_rate=44100,
                    channel_count=1,
                    cancel_event=cancel_event,
                )
            )

    def test_timeout_removes_output(self, tmp_path: Path) -> None:
        source = tmp_path / "long.wav"
        write_wav_s16(source, sine(600.0, 48000), 48000)
        out = tmp_path / "out.pcm"

        with pytest.raises(DecodeTimeoutError):
            asyncio.run(
                decode_canonical(
                    source_path=source,
                    output_path=out,
                    stream_index=0,
                    sample_rate=48000,
                    channel_count=1,
                    timeout_seconds=0.05,
                )
            )
        assert not out.exists()


class TestResamplerPolicy:
    """The production discontinuity filter, exercised at the resampler level.

    ``aresample=async=1`` fills timestamp gaps with silence and trims
    overlaps. The fixtures are generated by shifting frame PTS with
    ``asetpts`` on a raw stream — the exact component the production
    decode command configures.
    """

    def test_gap_padded_with_silence(self, tmp_path: Path) -> None:
        out = tmp_path / "gap.f32"
        size = _run_filter_chain(f"asetpts='if(lt(T,1),PTS,PTS+1/TB)',{DISCONTINUITY_FILTER}", out)
        # 2 s source + 1 s gap = 3 s @ 48 kHz mono.
        assert size == 3 * 48000 * 4

    def test_overlap_trimmed(self, tmp_path: Path) -> None:
        chain = f"asetpts='if(lt(T,1),PTS,PTS-0.5/TB)',{DISCONTINUITY_FILTER}"
        out = tmp_path / "ov.f32"
        size = _run_filter_chain(chain, out)
        # 2 s source - 0.5 s overlap = 1.5 s @ 48 kHz mono.
        assert size == int(1.5 * 48000) * 4

    def test_clean_stream_unmodified(self, tmp_path: Path) -> None:
        out = tmp_path / "clean.f32"
        size = _run_filter_chain(DISCONTINUITY_FILTER, out)
        # 2 s source, no discontinuities.
        assert size == 2 * 48000 * 4
