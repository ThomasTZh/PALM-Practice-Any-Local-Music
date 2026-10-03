"""Unit tests for the M1.5 canonical decode module (no subprocess)."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import struct
from collections import namedtuple
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.representation import CanonicalDecodeResult, compute_transform_key
from basseparate.media.decode import (
    DISK_HEADROOM_FACTOR,
    MINIMUM_FREE_DISK_BYTES,
    PUBLISH_RESERVE_BYTES,
    TIMING_REPAIR_TOLERANCE_SECONDS,
    DecodeFailedError,
    InsufficientDiskSpaceError,
    NonFiniteSamplesError,
    _required_free_bytes,
    check_frame_alignment,
    decode_canonical,
    duration_discrepancy_warnings,
    mime_type_for_format,
    parse_progress_line,
    validate_pcm,
)

_HASH = "ab" * 32


def _make_result(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "frame_count": 4410,
        "sample_rate": 44100,
        "channel_count": 1,
        "channel_layout": "mono",
        "content_hash": _HASH,
        "max_amplitude": 0.5,
        "pcm_byte_count": 4410 * 4,
        "decoded_duration_seconds": 0.1,
        "estimated_duration_seconds": 0.1,
        "duration_discrepancy_seconds": 0.0,
        "source_start_timestamp_seconds": None,
        "decoder_warnings": (),
        "timing_repair_warnings": (),
        "ffmpeg_version": "8.1",
        "profile_version": 1,
        "staging_pcm_path": "/tmp/staging/canonical.pcm",
    }
    base.update(overrides)
    return base


class TestCanonicalDecodeResult:
    def test_valid(self) -> None:
        result = CanonicalDecodeResult(**_make_result())
        assert result.frame_count == 4410
        assert result.channel_layout == "mono"

    def test_frame_count_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            CanonicalDecodeResult(**_make_result(frame_count=0))

    def test_amplitude_must_be_nonnegative(self) -> None:
        with pytest.raises(ValueError):
            CanonicalDecodeResult(**_make_result(max_amplitude=-0.1))

    def test_amplitude_may_exceed_one(self) -> None:
        result = CanonicalDecodeResult(**_make_result(max_amplitude=1.5))
        assert result.max_amplitude == 1.5

    def test_pcm_byte_count_consistency_not_enforced(self) -> None:
        # The byte count is validated against the file at decode time; the
        # model only requires a sane minimum.
        with pytest.raises(ValueError):
            CanonicalDecodeResult(**_make_result(pcm_byte_count=0))

    def test_warnings_default_empty(self) -> None:
        result = CanonicalDecodeResult(**_make_result())
        assert result.decoder_warnings == ()
        assert result.timing_repair_warnings == ()


class TestTransformKey:
    def test_deterministic(self) -> None:
        a = compute_transform_key("aa" * 32, 0, 1, "8.1")
        b = compute_transform_key("aa" * 32, 0, 1, "8.1")
        assert a == b
        assert len(a) == 64

    def test_sensitive_to_inputs(self) -> None:
        base = compute_transform_key("aa" * 32, 0, 1, "8.1")
        assert compute_transform_key("bb" * 32, 0, 1, "8.1") != base
        assert compute_transform_key("aa" * 32, 1, 1, "8.1") != base
        assert compute_transform_key("aa" * 32, 0, 2, "8.1") != base
        assert compute_transform_key("aa" * 32, 0, 1, "8.2") != base


class TestParseProgressLine:
    def test_key_value(self) -> None:
        assert parse_progress_line("out_time_us=1021678") == ("out_time_us", "1021678")

    def test_progress_end(self) -> None:
        assert parse_progress_line("progress=end") == ("progress", "end")

    def test_non_progress_lines(self) -> None:
        assert parse_progress_line("") is None
        assert parse_progress_line("total_size=0000000000") == ("total_size", "0000000000")
        # FFmpeg log lines are not progress lines.
        assert parse_progress_line("[mp3float @ 0x556] invalid new backstep -1") is None
        assert parse_progress_line("  frame=   12 fps=0.0") is None

    def test_empty_value_rejected(self) -> None:
        assert parse_progress_line("key=") is None


class TestFrameAlignment:
    def test_aligned(self) -> None:
        assert check_frame_alignment(4410 * 4, 1) == 4410
        assert check_frame_alignment(4410 * 8, 2) == 4410
        assert check_frame_alignment(4410 * 32, 8) == 4410

    def test_unaligned_raises(self) -> None:
        with pytest.raises(DecodeFailedError):
            check_frame_alignment(4410 * 4 + 3, 1)
        with pytest.raises(DecodeFailedError):
            check_frame_alignment(4410 * 6, 2)  # 6-byte frames: one short


class TestDurationDiscrepancy:
    def test_no_estimate(self) -> None:
        discrepancy, warnings = duration_discrepancy_warnings(1.0, None)
        assert discrepancy is None
        assert warnings == []

    def test_within_tolerance(self) -> None:
        tolerance = TIMING_REPAIR_TOLERANCE_SECONDS / 2
        discrepancy, warnings = duration_discrepancy_warnings(1.0, 1.0 + tolerance)
        assert discrepancy == pytest.approx(-tolerance)
        assert warnings == []

    def test_gap_padded(self) -> None:
        discrepancy, warnings = duration_discrepancy_warnings(2.0, 1.0)
        assert discrepancy == pytest.approx(1.0)
        assert len(warnings) == 1
        assert "padded with silence" in warnings[0]

    def test_boundary_is_inclusive(self) -> None:
        # Exactly at the tolerance: no warning.
        _, warnings = duration_discrepancy_warnings(
            1.0, 1.0 + TIMING_REPAIR_TOLERANCE_SECONDS
        )
        assert warnings == []

    def test_overlap_trimmed(self) -> None:
        discrepancy, warnings = duration_discrepancy_warnings(0.4, 1.0)
        assert discrepancy == pytest.approx(-0.6)
        assert len(warnings) == 1
        assert "trimmed" in warnings[0]


def _write_pcm(path: Path, samples: np.ndarray) -> None:
    path.write_bytes(np.ascontiguousarray(samples, dtype="<f4").tobytes())


class TestValidatePcm:
    def test_hash_and_amplitude(self, tmp_path: Path) -> None:
        samples = np.linspace(-0.5, 0.75, 1000, dtype="<f4")
        path = tmp_path / "a.pcm"
        _write_pcm(path, samples)
        content_hash, max_amplitude = validate_pcm(path, 1)
        assert content_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert max_amplitude == pytest.approx(0.75)

    def test_amplitude_keeps_values_beyond_one(self, tmp_path: Path) -> None:
        samples = np.array([1.25, -2.5, 0.0], dtype="<f4")
        path = tmp_path / "b.pcm"
        _write_pcm(path, samples)
        _, max_amplitude = validate_pcm(path, 1)
        assert max_amplitude == pytest.approx(2.5)

    def test_nan_raises(self, tmp_path: Path) -> None:
        samples = np.array([0.1, np.nan, 0.2], dtype="<f4")
        path = tmp_path / "nan.pcm"
        _write_pcm(path, samples)
        with pytest.raises(NonFiniteSamplesError):
            validate_pcm(path, 1)

    def test_infinity_raises(self, tmp_path: Path) -> None:
        samples = np.array([0.1, np.inf], dtype="<f4")
        path = tmp_path / "inf.pcm"
        _write_pcm(path, samples)
        with pytest.raises(NonFiniteSamplesError):
            validate_pcm(path, 1)

    def test_odd_size_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "odd.pcm"
        path.write_bytes(struct.pack("<f", 0.5) + b"\x00\x01")  # 6 bytes
        with pytest.raises(DecodeFailedError):
            validate_pcm(path, 1)

    def test_large_file_chunked(self, tmp_path: Path) -> None:
        # More than one 8 MiB validation chunk.
        samples = np.full(4_000_000, 0.25, dtype="<f4")  # 16 MiB
        path = tmp_path / "large.pcm"
        _write_pcm(path, samples)
        content_hash, max_amplitude = validate_pcm(path, 1)
        assert content_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert max_amplitude == pytest.approx(0.25)


class TestMimeType:
    @pytest.mark.parametrize(
        ("format_name", "expected"),
        [
            ("wav", "audio/wav"),
            ("mp3", "audio/mpeg"),
            ("m4a", "audio/mp4"),
            ("ogg", "audio/ogg"),
            ("opus", "audio/opus"),
            ("flac", "audio/flac"),
            ("matroska,webm", "audio/matroska"),  # first token wins
            ("MATROSKA", "audio/matroska"),
            ("unknown_format", "application/octet-stream"),
            ("", "application/octet-stream"),
        ],
    )
    def test_known_formats(self, format_name: str, expected: str) -> None:
        assert mime_type_for_format(format_name) == expected


class TestDiskBudget:
    """M1.6: pre-flight disk budgeting (milestone1.md §8.5)."""

    Usage = namedtuple("Usage", "total used free")

    def _tiny_wav(self, tmp_path: Path) -> Path:
        pcm = b"\x00\x00" * 441
        source = tmp_path / "tone.wav"
        source.write_bytes(
            b"RIFF"
            + struct.pack("<I", 36 + len(pcm))
            + b"WAVE"
            + b"fmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
            + b"data"
            + struct.pack("<I", len(pcm))
            + pcm
        )
        return source

    def test_budget_includes_original_pcm_and_reserve(self) -> None:
        required = _required_free_bytes(1.0, 44100, 2, 1_000_000)
        expected_pcm = int(1.0 * 44100 * 2 * 4)
        assert required == (
            int(expected_pcm * DISK_HEADROOM_FACTOR) + 1_000_000 + PUBLISH_RESERVE_BYTES
        )

    def test_budget_floor_without_estimate(self) -> None:
        # No duration estimate: retained original + reserve, above the floor.
        required = _required_free_bytes(None, 44100, 1, 10_000)
        assert required == 10_000 + PUBLISH_RESERVE_BYTES
        assert required > MINIMUM_FREE_DISK_BYTES

    def test_insufficient_space_fails_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = self._tiny_wav(tmp_path)
        out = tmp_path / "out.pcm"
        monkeypatch.setattr(
            shutil, "disk_usage", lambda path: self.Usage(10**10, 10**10 - 10**7, 10**7)
        )

        with pytest.raises(InsufficientDiskSpaceError):
            asyncio.run(
                decode_canonical(
                    source_path=source,
                    output_path=out,
                    stream_index=0,
                    sample_rate=44100,
                    channel_count=1,
                )
            )
        # The budget is checked before ffmpeg starts: nothing is written.
        assert not out.exists()
