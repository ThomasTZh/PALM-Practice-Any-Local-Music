"""Unit tests for the export domain helpers (M2.13, spec §15).

Covers the safe-filename generator, the encoding specs, the dither
policy, and the linked peak-normalization gain. No ffmpeg involved.
"""

from __future__ import annotations

import math
import uuid

import pytest

from basseparate.domain.export import (
    ExportFormat,
    ExportNormalization,
    ExportStemResult,
    export_dither_for,
    export_download_filename,
    export_download_filenames,
    export_format_spec,
    normalize_gain_db,
    sanitize_filename_part,
)
from basseparate.domain.separation import StemRole

SET_ID = uuid.UUID("12345678-9abc-4def-8123-456789abcdef")


class TestSanitizeFilenamePart:
    def test_keeps_safe_characters(self) -> None:
        assert sanitize_filename_part("Bass_24bit.wav", fallback="stem") == "Bass_24bit.wav"

    def test_replaces_unsafe_runs_with_one_dash(self) -> None:
        assert sanitize_filename_part("Lead Vocals (L)", fallback="stem") == "Lead-Vocals-L"

    def test_maps_non_ascii_and_trims_edges(self) -> None:
        assert sanitize_filename_part("  Bässe -- ", fallback="stem") == "B-sse"

    def test_empty_or_fully_unsafe_uses_fallback(self) -> None:
        assert sanitize_filename_part("", fallback="stem") == "stem"
        assert sanitize_filename_part("///", fallback="stem") == "stem"

    def test_clamps_length(self) -> None:
        part = sanitize_filename_part("x" * 100, fallback="stem")
        assert part == "x" * 48


class TestDownloadFilenames:
    def test_deterministic_pattern(self) -> None:
        name = export_download_filename(
            label="Bass",
            role=StemRole.BASS,
            result_set_id=SET_ID,
            sample_rate=48000,
            format=ExportFormat.WAV24,
        )
        assert name == "Bass-123456-48k-24bit.wav"

    def test_fractional_rate_label(self) -> None:
        name = export_download_filename(
            label="Bass",
            role=StemRole.BASS,
            result_set_id=SET_ID,
            sample_rate=44100,
            format=ExportFormat.WAV32F,
        )
        assert name == "Bass-123456-44.1k-float32.wav"

    def test_role_fallback_and_collision_suffix(self) -> None:
        first = uuid.uuid4()
        second = uuid.uuid4()
        names = export_download_filenames(
            [(first, "!!!", StemRole.OTHERS), (second, "???", StemRole.OTHERS)],
            result_set_id=SET_ID,
            sample_rate=48000,
            format=ExportFormat.WAV16,
        )
        assert names[first] == "others-123456-48k-16bit.wav"
        assert names[second] == "others-123456-48k-16bit-2.wav"


class TestFormatSpecs:
    def test_specs(self) -> None:
        assert export_format_spec(ExportFormat.WAV16).bytes_per_sample == 2
        assert export_format_spec(ExportFormat.WAV24).encoder == "pcm_s24le"
        assert export_format_spec(ExportFormat.WAV32F).encoder == "pcm_f32le"
        assert export_format_spec(ExportFormat.WAV32F).integer_full_scale is None

    def test_integer_full_scale_bounds(self) -> None:
        assert export_format_spec(ExportFormat.WAV16).integer_full_scale == 32767 / 32768
        assert (
            export_format_spec(ExportFormat.WAV24).integer_full_scale == 8388607 / 8388608
        )

    def test_dither_only_for_integer(self) -> None:
        assert export_dither_for(ExportFormat.WAV16) == "triangular"
        assert export_dither_for(ExportFormat.WAV24) == "triangular"
        assert export_dither_for(ExportFormat.WAV32F) is None


class TestNormalizeGain:
    def test_full_scale_peak_maps_to_minus_one_dbfs(self) -> None:
        gain = normalize_gain_db(1.0)
        assert gain is not None
        assert gain == pytest.approx(-1.0, abs=1e-9)

    def test_quiet_peak_is_boosted_to_target(self) -> None:
        gain = normalize_gain_db(0.5)
        assert gain is not None
        peak_after = 0.5 * 10 ** (gain / 20)
        assert peak_after == pytest.approx(10 ** (-1 / 20), abs=1e-12)
        assert gain > 0

    def test_silence_has_no_gain(self) -> None:
        assert normalize_gain_db(0.0) is None


class TestExportStemResult:
    def test_round_trip(self) -> None:
        result = ExportStemResult(
            stem_id=uuid.uuid4(),
            audio_asset_id=uuid.uuid4(),
            role=StemRole.BASS,
            format=ExportFormat.WAV24,
            sample_rate=48000,
            channel_count=2,
            frame_count=1000,
            source_frame_count=1000,
            normalized=True,
            gain_db=-1.0,
            dither="triangular",
            sha256="a" * 64,
            byte_size=6000,
            download_filename="Bass-123456-48k-24bit.wav",
            staging_path="/tmp/staging/Bass.wav",
        )
        assert result.normalized is True
        assert ExportNormalization.LINKED_PEAK.value == "linked_peak"

    def test_rejects_unknown_normalization(self) -> None:
        with pytest.raises(ValueError):
            ExportNormalization("per_stem")

    def test_gain_is_a_real_number(self) -> None:
        gain = normalize_gain_db(2.0)  # already above full scale
        assert gain is not None
        assert math.isclose(2.0 * 10 ** (gain / 20), 10 ** (-1 / 20), rel_tol=1e-12)
