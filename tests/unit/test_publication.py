"""Unit tests for stem publication transforms (M2.6, milestone2.md §8).

No ffmpeg, no GPU:
- identity restore fast path (byte-exact) and its frame-count policy;
- stereo→mono collapse: the documented ``(L + R) / 2`` average with a
  float64 intermediate and float32 output;
- ``validate_stems``: the §8.2 checklist (roles, frames, alignment,
  finiteness, hash, max amplitude);
- ``compute_reconstruction_error``: exact and known-offset diagnostics;
- ``derive_bass_residual``: byte-exact float32 residual, the rounding
  verification, the tolerance, and partial-output cleanup.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from synth import full_scale, tone_frames

from basseparate.media.decode import NonFiniteSamplesError
from basseparate.media.publication import (
    PublicationError,
    StemsValidationError,
    _collapse_stereo_to_mono,
    _residual_rounding_tolerance,
    compute_reconstruction_error,
    derive_bass_residual,
    restore_stem_project_representation,
    validate_stems,
)


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N,) or (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data, dtype="<f4").tobytes())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRestoreIdentityFastPath:
    @pytest.mark.asyncio
    async def test_byte_exact_copy(self, tmp_path: Path) -> None:
        frames = 120
        data = tone_frames(frames, 44100, frequency=110.0, amplitude=0.5, channels=2)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        outcome = await restore_stem_project_representation(
            source_path=src,
            source_rate=44100,
            source_channels=2,
            output_path=out,
            target_rate=44100,
            target_channels=2,
            target_frame_count=frames,
        )

        assert out.read_bytes() == src.read_bytes()
        assert outcome.content_hash == _sha256(out)
        assert outcome.frame_count == frames
        assert outcome.channel_count == 2
        assert outcome.endpoint_difference_frames == 0
        assert outcome.resampled is False
        assert outcome.mono_collapsed is False
        assert outcome.max_amplitude == pytest.approx(0.5, abs=1e-3)

    @pytest.mark.asyncio
    async def test_frame_count_mismatch_fails_and_cleans(self, tmp_path: Path) -> None:
        data = tone_frames(120, 44100, channels=2)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        with pytest.raises(PublicationError, match="requires exactly 121"):
            await restore_stem_project_representation(
                source_path=src,
                source_rate=44100,
                source_channels=2,
                output_path=out,
                target_rate=44100,
                target_channels=2,
                target_frame_count=121,
            )
        assert not out.exists()

    @pytest.mark.asyncio
    async def test_unsupported_channel_conversion(self, tmp_path: Path) -> None:
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, tone_frames(10, 44100, channels=1))

        with pytest.raises(PublicationError, match="unsupported channel conversion"):
            await restore_stem_project_representation(
                source_path=src,
                source_rate=44100,
                source_channels=1,
                output_path=out,
                target_rate=44100,
                target_channels=2,
                target_frame_count=10,
            )
        assert not out.exists()

    @pytest.mark.asyncio
    async def test_non_positive_rate_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "staged.pcm"
        _write_f32le_pcm(src, tone_frames(10, 44100, channels=2))

        with pytest.raises(PublicationError, match="must be positive"):
            await restore_stem_project_representation(
                source_path=src,
                source_rate=0,
                source_channels=2,
                output_path=tmp_path / "restored.pcm",
                target_rate=44100,
                target_channels=2,
                target_frame_count=10,
            )


class TestMonoCollapse:
    def test_documented_average(self, tmp_path: Path) -> None:
        data = np.array([[1.0, 3.0], [2.0, 2.0], [3.0, 1.0]], dtype="<f4")
        src = tmp_path / "stereo.pcm"
        out = tmp_path / "mono.pcm"
        _write_f32le_pcm(src, data)

        _collapse_stereo_to_mono(src, out)

        mono = np.fromfile(out, dtype="<f4")
        np.testing.assert_array_equal(mono, np.array([2.0, 2.0, 2.0], dtype="<f4"))

    def test_float64_intermediate(self, tmp_path: Path) -> None:
        # 0.1 + 0.2 rounds differently in float32 arithmetic; the
        # documented average goes through a float64 intermediate.
        left = np.float32(0.1)
        right = np.float32(0.2)
        expected = np.float32((np.float64(left) + np.float64(right)) * 0.5)
        data = np.stack(
            [np.array([left], dtype="<f4"), np.array([right], dtype="<f4")], axis=1
        )
        src = tmp_path / "stereo.pcm"
        out = tmp_path / "mono.pcm"
        _write_f32le_pcm(src, data)

        _collapse_stereo_to_mono(src, out)

        assert np.fromfile(out, dtype="<f4")[0] == expected

    def test_misaligned_input_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "stereo.pcm"
        out = tmp_path / "mono.pcm"
        src.write_bytes(b"\x00" * 10)  # not a multiple of 8 bytes

        with pytest.raises(PublicationError, match="sample-aligned"):
            _collapse_stereo_to_mono(src, out)


class TestValidateStems:
    def _four_stems(self, tmp_path: Path, frames: int = 64) -> dict[str, Path]:
        paths = {}
        for role, freq in (
            ("vocals", 440.0),
            ("drums", 110.0),
            ("bass", 55.0),
            ("other", 880.0),
        ):
            path = tmp_path / f"{role}.pcm"
            _write_f32le_pcm(path, tone_frames(frames, 48000, frequency=freq, channels=2))
            paths[role] = path
        return paths

    @pytest.mark.asyncio
    async def test_happy_path_records_hash_and_amplitude(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)

        results = await validate_stems(
            stems=[(role, paths[role]) for role in ("vocals", "drums", "bass", "other")],
            expected_roles=["vocals", "drums", "bass", "other"],
            frame_count=64,
            channel_count=2,
            sample_rate=48000,
        )

        assert {r.role for r in results} == {"vocals", "drums", "bass", "other"}
        vocals = next(r for r in results if r.role == "vocals")
        assert vocals.content_hash == _sha256(paths["vocals"])
        assert vocals.max_amplitude == pytest.approx(0.5, abs=1e-3)
        assert vocals.frame_count == 64

    @pytest.mark.asyncio
    async def test_missing_role_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)

        with pytest.raises(StemsValidationError, match=r"missing=\['bass'\]"):
            await validate_stems(
                stems=[(role, paths[role]) for role in ("vocals", "drums", "other")],
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=48000,
            )

    @pytest.mark.asyncio
    async def test_duplicate_role_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)

        with pytest.raises(StemsValidationError, match="extra="):
            await validate_stems(
                stems=[
                    ("vocals", paths["vocals"]),
                    ("drums", paths["drums"]),
                    ("bass", paths["bass"]),
                    ("bass", paths["other"]),
                ],
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=48000,
            )

    @pytest.mark.asyncio
    async def test_frame_count_mismatch_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)
        # One stem is one frame short.
        short = tmp_path / "short.pcm"
        _write_f32le_pcm(short, tone_frames(63, 48000, channels=2))

        with pytest.raises(StemsValidationError, match="expected exactly 64"):
            await validate_stems(
                stems=[
                    ("vocals", paths["vocals"]),
                    ("drums", paths["drums"]),
                    ("bass", short),
                    ("other", paths["other"]),
                ],
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=48000,
            )

    @pytest.mark.asyncio
    async def test_non_finite_samples_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)
        bad = tmp_path / "bad.pcm"
        data = tone_frames(64, 48000, channels=2)
        data[5, 0] = np.nan
        _write_f32le_pcm(bad, data)

        with pytest.raises(StemsValidationError, match="non-finite"):
            await validate_stems(
                stems=[
                    ("vocals", paths["vocals"]),
                    ("drums", paths["drums"]),
                    ("bass", bad),
                    ("other", paths["other"]),
                ],
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=48000,
            )

    @pytest.mark.asyncio
    async def test_misaligned_file_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)
        ragged = tmp_path / "ragged.pcm"
        ragged.write_bytes(b"\x00" * 100)  # not a multiple of 8 bytes

        with pytest.raises(StemsValidationError):
            await validate_stems(
                stems=[
                    ("vocals", paths["vocals"]),
                    ("drums", paths["drums"]),
                    ("bass", ragged),
                    ("other", paths["other"]),
                ],
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=48000,
            )

    @pytest.mark.asyncio
    async def test_non_positive_rate_rejected(self, tmp_path: Path) -> None:
        paths = self._four_stems(tmp_path)

        with pytest.raises(PublicationError, match="must be positive"):
            await validate_stems(
                stems=list(paths.items()),
                expected_roles=["vocals", "drums", "bass", "other"],
                frame_count=64,
                channel_count=2,
                sample_rate=0,
            )


class TestReconstructionError:
    @pytest.mark.asyncio
    async def test_exact_reconstruction_is_zero(self, tmp_path: Path) -> None:
        # Powers-of-two amplitudes on a ±1 carrier: every sample and the
        # sum are exactly representable in float32.
        carrier = full_scale(32, 48000)
        stems = [carrier * (2.0**-k) for k in (1, 2, 3, 4)]
        ref = stems[0] + stems[1] + stems[2] + stems[3]
        ref_path = tmp_path / "ref.pcm"
        _write_f32le_pcm(ref_path, ref)
        stem_paths = []
        for index, stem in enumerate(stems):
            path = tmp_path / f"stem{index}.pcm"
            _write_f32le_pcm(path, stem)
            stem_paths.append(path)

        diag = await compute_reconstruction_error(
            reference_path=ref_path,
            stem_paths=stem_paths,
            channel_count=1,
            expected_frame_count=32,
        )

        assert diag.rms == 0.0
        assert diag.max_abs == 0.0
        assert diag.sample_count == 32

    @pytest.mark.asyncio
    async def test_known_offset(self, tmp_path: Path) -> None:
        n = 16
        ref = np.zeros(n, dtype="<f4")
        ref[3] = 0.5
        ref_path = tmp_path / "ref.pcm"
        s1 = tmp_path / "s1.pcm"
        s2 = tmp_path / "s2.pcm"
        _write_f32le_pcm(ref_path, ref)
        _write_f32le_pcm(s1, np.zeros(n, dtype="<f4"))
        _write_f32le_pcm(s2, np.zeros(n, dtype="<f4"))

        diag = await compute_reconstruction_error(
            reference_path=ref_path,
            stem_paths=[s1, s2],
            channel_count=1,
            expected_frame_count=n,
        )

        assert diag.max_abs == 0.5
        assert diag.rms == pytest.approx(0.5 / (n**0.5), rel=1e-12)
        assert diag.sample_count == n

    @pytest.mark.asyncio
    async def test_length_mismatch_rejected(self, tmp_path: Path) -> None:
        ref_path = tmp_path / "ref.pcm"
        stem_path = tmp_path / "stem.pcm"
        _write_f32le_pcm(ref_path, np.zeros(16, dtype="<f4"))
        _write_f32le_pcm(stem_path, np.zeros(15, dtype="<f4"))

        with pytest.raises(StemsValidationError, match="expected exactly 16"):
            await compute_reconstruction_error(
                reference_path=ref_path,
                stem_paths=[stem_path],
                channel_count=1,
                expected_frame_count=16,
            )

    @pytest.mark.asyncio
    async def test_no_stems_rejected(self, tmp_path: Path) -> None:
        ref_path = tmp_path / "ref.pcm"
        _write_f32le_pcm(ref_path, np.zeros(16, dtype="<f4"))

        with pytest.raises(PublicationError, match="at least one stem"):
            await compute_reconstruction_error(
                reference_path=ref_path,
                stem_paths=[],
                channel_count=1,
                expected_frame_count=16,
            )


class TestBassResidual:
    @pytest.mark.asyncio
    async def test_byte_exact_residual(self, tmp_path: Path) -> None:
        # Exactly representable values: the verification must be 0.0.
        ref = np.array([0.75, -0.5, 0.25, 1.0], dtype="<f4")
        bass = np.array([0.25, 0.5, 0.25, -0.5], dtype="<f4")
        expected = (ref.astype(np.float64) - bass.astype(np.float64)).astype("<f4")
        ref_path = tmp_path / "ref.pcm"
        bass_path = tmp_path / "bass.pcm"
        out = tmp_path / "others.pcm"
        _write_f32le_pcm(ref_path, ref)
        _write_f32le_pcm(bass_path, bass)

        outcome = await derive_bass_residual(
            reference_path=ref_path,
            bass_path=bass_path,
            output_path=out,
            channel_count=1,
            expected_frame_count=4,
        )

        assert out.read_bytes() == expected.tobytes()
        assert outcome.verification_max_abs == 0.0
        assert outcome.content_hash == _sha256(out)
        assert outcome.frame_count == 4
        assert outcome.pcm_byte_count == 4 * 4

    @pytest.mark.asyncio
    async def test_general_values_within_rounding(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(7)
        ref = (rng.standard_normal(100) * 0.8).astype("<f4")
        bass = (rng.standard_normal(100) * 0.3).astype("<f4")
        expected = (ref.astype(np.float64) - bass.astype(np.float64)).astype("<f4")
        ref_path = tmp_path / "ref.pcm"
        bass_path = tmp_path / "bass.pcm"
        out = tmp_path / "others.pcm"
        _write_f32le_pcm(ref_path, ref)
        _write_f32le_pcm(bass_path, bass)

        outcome = await derive_bass_residual(
            reference_path=ref_path,
            bass_path=bass_path,
            output_path=out,
            channel_count=1,
            expected_frame_count=100,
        )

        assert out.read_bytes() == expected.tobytes()
        peak = float(np.abs(ref).max()) + float(np.abs(bass).max())
        assert outcome.verification_max_abs <= _residual_rounding_tolerance(peak)
        assert outcome.verification_max_abs < 1e-6

    @pytest.mark.asyncio
    async def test_stereo_residual(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(11)
        ref = (rng.standard_normal((20, 2)) * 0.5).astype("<f4")
        bass = (rng.standard_normal((20, 2)) * 0.2).astype("<f4")
        expected = (ref.astype(np.float64) - bass.astype(np.float64)).astype("<f4")
        ref_path = tmp_path / "ref.pcm"
        bass_path = tmp_path / "bass.pcm"
        out = tmp_path / "others.pcm"
        _write_f32le_pcm(ref_path, ref)
        _write_f32le_pcm(bass_path, bass)

        outcome = await derive_bass_residual(
            reference_path=ref_path,
            bass_path=bass_path,
            output_path=out,
            channel_count=2,
            expected_frame_count=20,
        )

        assert out.read_bytes() == expected.tobytes()
        assert outcome.verification_max_abs < 1e-6

    @pytest.mark.asyncio
    async def test_non_finite_input_cleans_partial(self, tmp_path: Path) -> None:
        ref = np.zeros(8, dtype="<f4")
        ref[2] = np.nan
        ref_path = tmp_path / "ref.pcm"
        bass_path = tmp_path / "bass.pcm"
        out = tmp_path / "others.pcm"
        _write_f32le_pcm(ref_path, ref)
        _write_f32le_pcm(bass_path, np.zeros(8, dtype="<f4"))

        with pytest.raises(NonFiniteSamplesError):
            await derive_bass_residual(
                reference_path=ref_path,
                bass_path=bass_path,
                output_path=out,
                channel_count=1,
                expected_frame_count=8,
            )
        assert not out.exists()

    @pytest.mark.asyncio
    async def test_frame_count_mismatch_rejected(self, tmp_path: Path) -> None:
        ref_path = tmp_path / "ref.pcm"
        bass_path = tmp_path / "bass.pcm"
        _write_f32le_pcm(ref_path, np.zeros(8, dtype="<f4"))
        _write_f32le_pcm(bass_path, np.zeros(7, dtype="<f4"))

        with pytest.raises(PublicationError, match="expected exactly 8"):
            await derive_bass_residual(
                reference_path=ref_path,
                bass_path=bass_path,
                output_path=tmp_path / "others.pcm",
                channel_count=1,
                expected_frame_count=8,
            )

    def test_tolerance_helper(self) -> None:
        assert _residual_rounding_tolerance(0.0) == 0.0
        assert _residual_rounding_tolerance(1.0) == 2.0**-22
        assert _residual_rounding_tolerance(2.0) == 2.0**-21
