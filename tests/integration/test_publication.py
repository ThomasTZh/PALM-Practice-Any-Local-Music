"""Integration tests for stem publication transforms (M2.6, real ffmpeg).

Covers:
- restore with the pinned SWR profile: 44.1 kHz → 48 kHz (stereo), the
  mono-project collapse (stereo → mono at 48 kHz), and the identity
  fast path;
- the endpoint policy: a restored frame count that misses the project
  frame count fails (never a blind trim) and leaves no staging file;
- a full mini pipeline: four synthetic stems + reference mix restored to
  the project rate, the §8.2 validation, four-stem reconstruction
  diagnostics, and the Bass + Others residual (validated as a fifth
  stem);
- restore determinism (same staged bytes ⇒ same asset hash).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest
from synth import dc_offset, stereo_tones, tone_frames

from basseparate.domain.separation import (
    DeviceType,
    SeparationMode,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
)
from basseparate.media.publication import (
    PublicationError,
    compute_reconstruction_error,
    derive_bass_residual,
    publish_separation_result,
    queue_stem_waveforms,
    restore_stem_project_representation,
    validate_stems,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    JobRepository,
    ProjectRepository,
    SeparationRepository,
)

MODEL_RATE = 44100
PROJECT_RATE = 48000


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N,) or (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data, dtype="<f4").tobytes())


class TestRestore:
    @pytest.mark.asyncio
    async def test_stereo_44100_to_48000(self, tmp_path: Path) -> None:
        data = tone_frames(44100, MODEL_RATE, frequency=220.0, amplitude=0.5, channels=2)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        outcome = await restore_stem_project_representation(
            source_path=src,
            source_rate=MODEL_RATE,
            source_channels=2,
            output_path=out,
            target_rate=PROJECT_RATE,
            target_channels=2,
            target_frame_count=48000,
        )

        assert outcome.frame_count == 48000
        assert outcome.channel_count == 2
        assert outcome.resampled is True
        assert outcome.mono_collapsed is False
        assert abs(outcome.endpoint_difference_frames) <= 2
        assert out.stat().st_size == 48000 * 2 * 4
        assert src.exists()  # the source is never modified

    @pytest.mark.asyncio
    async def test_mono_project_collapse(self, tmp_path: Path) -> None:
        data = stereo_tones(1.0, MODEL_RATE, 220.0, 440.0)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        outcome = await restore_stem_project_representation(
            source_path=src,
            source_rate=MODEL_RATE,
            source_channels=2,
            output_path=out,
            target_rate=PROJECT_RATE,
            target_channels=1,
            target_frame_count=48000,
        )

        assert outcome.frame_count == 48000
        assert outcome.channel_count == 1
        assert outcome.mono_collapsed is True
        assert out.stat().st_size == 48000 * 1 * 4
        # No intermediate stereo file is left behind.
        assert not (tmp_path / "restored.pcm.stereo.tmp").exists()

    @pytest.mark.asyncio
    async def test_identity_fast_path(self, tmp_path: Path) -> None:
        data = tone_frames(44100, MODEL_RATE, frequency=220.0, amplitude=0.5, channels=2)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        outcome = await restore_stem_project_representation(
            source_path=src,
            source_rate=MODEL_RATE,
            source_channels=2,
            output_path=out,
            target_rate=MODEL_RATE,
            target_channels=2,
            target_frame_count=44100,
        )

        assert outcome.resampled is False
        assert out.read_bytes() == src.read_bytes()

    @pytest.mark.asyncio
    async def test_frame_count_miss_fails_without_trim(self, tmp_path: Path) -> None:
        data = tone_frames(44100, MODEL_RATE, frequency=220.0, amplitude=0.5, channels=2)
        src = tmp_path / "staged.pcm"
        out = tmp_path / "restored.pcm"
        _write_f32le_pcm(src, data)

        with pytest.raises(PublicationError, match="requires exactly 48001"):
            await restore_stem_project_representation(
                source_path=src,
                source_rate=MODEL_RATE,
                source_channels=2,
                output_path=out,
                target_rate=PROJECT_RATE,
                target_channels=2,
                target_frame_count=48001,
            )
        assert not out.exists()


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_four_stems_restore_validate_diagnostics_residual(
        self, tmp_path: Path
    ) -> None:
        # A perfect synthetic "model": the reference mix is the exact
        # float32 sum of four in-phase stems at the model rate.
        frames = 44100
        t = np.arange(frames, dtype="<f8") / MODEL_RATE
        components = [
            (0.25 * np.sin(2.0 * np.pi * freq * t)).astype("<f4")
            for freq in (55.0, 110.0, 220.0, 440.0)
        ]
        ref = components[0].copy()
        for component in components[1:]:
            ref = (ref + component).astype("<f4")

        def to_stereo(mono: np.ndarray) -> np.ndarray:
            return np.tile(mono[:, None], (1, 2))

        staged = tmp_path / "staged"
        staged.mkdir()
        _write_f32le_pcm(staged / "ref.pcm", to_stereo(ref))
        roles = ("vocals", "drums", "bass", "other")
        for role, component in zip(roles, components, strict=True):
            _write_f32le_pcm(staged / f"{role}.pcm", to_stereo(component))

        restored = tmp_path / "restored"
        restored.mkdir()
        project_frames = 48000
        outcomes = {}
        for name in ("ref", *roles):
            outcome = await restore_stem_project_representation(
                source_path=staged / f"{name}.pcm",
                source_rate=MODEL_RATE,
                source_channels=2,
                output_path=restored / f"{name}.pcm",
                target_rate=PROJECT_RATE,
                target_channels=2,
                target_frame_count=project_frames,
            )
            outcomes[name] = outcome

        # Determinism: restoring the same bytes again yields the same hash.
        again = await restore_stem_project_representation(
            source_path=staged / "drums.pcm",
            source_rate=MODEL_RATE,
            source_channels=2,
            output_path=restored / "drums-again.pcm",
            target_rate=PROJECT_RATE,
            target_channels=2,
            target_frame_count=project_frames,
        )
        assert again.content_hash == outcomes["drums"].content_hash

        # §8.2 validation of the four restored stems.
        validations = await validate_stems(
            stems=[(role, restored / f"{role}.pcm") for role in roles],
            expected_roles=list(roles),
            frame_count=project_frames,
            channel_count=2,
            sample_rate=PROJECT_RATE,
        )
        assert {v.role for v in validations} == set(roles)
        for validation in validations:
            assert validation.frame_count == project_frames

        # §8.3 four-stem reconstruction diagnostics (resampling round-trip
        # error only — the synthetic model is exact at the model rate).
        diag = await compute_reconstruction_error(
            reference_path=restored / "ref.pcm",
            stem_paths=[restored / f"{role}.pcm" for role in roles],
            channel_count=2,
            expected_frame_count=project_frames,
        )
        assert diag.sample_count == project_frames * 2
        assert diag.max_abs < 1e-4
        assert diag.rms < 1e-5

        # §8.4 the Bass + Others residual, validated as a fifth stem.
        residual = await derive_bass_residual(
            reference_path=restored / "ref.pcm",
            bass_path=restored / "bass.pcm",
            output_path=restored / "others.pcm",
            channel_count=2,
            expected_frame_count=project_frames,
        )
        assert residual.verification_max_abs < 1e-6

        all_validations = await validate_stems(
            stems=[(role, restored / f"{role}.pcm") for role in roles]
            + [("others", restored / "others.pcm")],
            expected_roles=[*roles, "others"],
            frame_count=project_frames,
            channel_count=2,
            sample_rate=PROJECT_RATE,
        )
        assert {v.role for v in all_validations} == set(roles) | {"others"}


class TestPublishSeparationResult:
    """End-to-end publication of a synthetic staged run (no GPU).

    DC components resample exactly (a constant signal is invariant under
    the pinned SWR profile), so the reconstruction diagnostics and the
    residual verification must be at float32 rounding level.
    """

    LABELS = ("vocals", "drums", "bass", "other")
    LEVELS = (0.1, 0.2, 0.4, 0.3)

    def _staged_run(
        self,
        tmp_path: Path,
        mode: SeparationMode,
        status: SeparationRunStatus = SeparationRunStatus.RUNNING,
    ) -> tuple[SeparationRun, Path, Path, Path]:
        data = tmp_path / "data"
        db_path = data / "basseparate.db"
        initialize_database(db_path)
        projects = ProjectRepository(db_path)
        separation = SeparationRepository(db_path)
        project = projects.create_project("Song")

        run = SeparationRun(
            id=uuid.uuid4(),
            project_id=project.id,
            input_asset_id=uuid.uuid4(),
            input_transform_hash="ab" * 32,
            requested_mode=mode,
            model_manifest_id=uuid.uuid4(),
            model_manifest_hash="cd" * 32,
            engine_version="demucs-4.1.0",
            adapter_version="outer-window-v1",
            device_type=DeviceType.CPU,
            started_at="2026-10-11T00:00:00Z"
            if status is SeparationRunStatus.RUNNING
            else None,
            status=status,
        )
        separation.create_run(run)

        # Staging: attempt-1/<label>.pcm at the model rate (1 second).
        staging_dir = tmp_path / "staging"
        attempt_dir = staging_dir / "attempt-1"
        attempt_dir.mkdir(parents=True)
        for label, level in zip(self.LABELS, self.LEVELS, strict=True):
            _write_f32le_pcm(
                attempt_dir / f"{label}.pcm",
                dc_offset(MODEL_RATE, MODEL_RATE, level, channels=2),
            )
        (staging_dir / "run-record.json").write_text('{"status": "completed"}')

        # The project-rate reference mix (the sum of the DC components).
        reference_path = tmp_path / "reference.pcm"
        _write_f32le_pcm(
            reference_path,
            dc_offset(PROJECT_RATE, PROJECT_RATE, 1.0, channels=2),
        )
        return run, staging_dir, attempt_dir, reference_path

    @pytest.mark.asyncio
    async def test_four_stems_end_to_end(self, tmp_path: Path) -> None:
        run, staging_dir, attempt_dir, reference_path = self._staged_run(
            tmp_path, SeparationMode.FOUR_STEMS
        )
        data = tmp_path / "data"
        db_path = data / "basseparate.db"
        projects = ProjectRepository(db_path)
        separation = SeparationRepository(db_path)
        jobs = JobRepository(db_path)
        source = SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
        )

        outcome = await publish_separation_result(
            run=run,
            staging_dir=staging_dir,
            attempt_dir=attempt_dir,
            stem_labels=list(self.LABELS),
            reference_path=reference_path,
            source=source,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
            channel_count=2,
            asset_dir=data / "assets",
            separation_repository=separation,
            job_repository=jobs,
        )

        # Run completion and result set.
        assert outcome.run.status is SeparationRunStatus.COMPLETED
        assert outcome.run.result_set_id == outcome.result_set.id
        got_run = separation.get_run(run.id)
        assert got_run is not None and got_run.status is SeparationRunStatus.COMPLETED
        got_set = separation.get_result_set(outcome.result_set.id)
        assert got_set is not None
        assert got_set.validation_status.value == "valid"
        assert sorted(r.value for r in got_set.available_stem_roles) == sorted(self.LABELS)
        assert got_set.bass_residual_asset_id is None
        assert got_set.output_frame_count == PROJECT_RATE
        assert "reconstruction_rms" in got_set.reconstruction_metrics
        assert "reconstruction_max" in got_set.reconstruction_metrics
        assert "residual_reconstruction_max" not in got_set.reconstruction_metrics
        # The pinned SWR profile has a start transient at float32 rounding
        # level for a DC signal (zero-padded filter history).
        assert got_set.reconstruction_metrics["reconstruction_max"] < 1e-5

        # Stems: four, one per label, aligned, confidence unavailable.
        got_stems = separation.list_stems_for_result_set(outcome.result_set.id)
        assert sorted(s.role.value for s in got_stems) == sorted(self.LABELS)
        for stem in got_stems:
            assert stem.frame_count == PROJECT_RATE
            assert stem.alignment_offset_frames == 0
            assert stem.confidence.kind.value == "unavailable"
            assert stem.provenance is not None
            assert stem.provenance["kind"] == "demucs"

        # Assets on disk, deduplicated by content hash.
        asset_dir = data / "assets"
        for asset in outcome.assets:
            on_disk = asset_dir / f"{asset.content_hash}.pcm"
            assert on_disk.is_file()
            assert on_disk.stat().st_size == PROJECT_RATE * 2 * 4
            assert projects.get_asset(asset.id) is not None

        # Project linkage: stem-role rows only.
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT asset_id, role FROM project_assets WHERE project_id = ?",
            (str(run.project_id),),
        ).fetchall()
        conn.close()
        assert {(r[0], r[1]) for r in rows} == {
            (str(a.id), "stem") for a in outcome.assets
        }

        # One waveform job per published stem asset.
        assert len(outcome.waveform_jobs) == 4
        queued = jobs.list_jobs_for_project(run.project_id)
        waveform_jobs = [j for j in queued if j.job_type.value == "waveform"]
        assert len(waveform_jobs) == 4
        assert {j.parameters["asset_id"] for j in waveform_jobs} == {
            str(a.id) for a in outcome.assets
        }

        # Staging is removed on success; no partial files remain.
        assert not staging_dir.exists()

    @pytest.mark.asyncio
    async def test_bass_pair_publishes_residual(self, tmp_path: Path) -> None:
        run, staging_dir, attempt_dir, reference_path = self._staged_run(
            tmp_path, SeparationMode.BASS_PAIR
        )
        data = tmp_path / "data"
        db_path = data / "basseparate.db"
        separation = SeparationRepository(db_path)
        jobs = JobRepository(db_path)
        source = SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
        )

        outcome = await publish_separation_result(
            run=run,
            staging_dir=staging_dir,
            attempt_dir=attempt_dir,
            stem_labels=list(self.LABELS),
            reference_path=reference_path,
            source=source,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
            channel_count=2,
            asset_dir=data / "assets",
            separation_repository=separation,
            job_repository=jobs,
        )

        # All four model stems plus the residual are published (§8.5).
        got_stems = separation.list_stems_for_result_set(outcome.result_set.id)
        assert sorted(s.role.value for s in got_stems) == sorted(
            [*self.LABELS, "others"]
        )
        others = next(s for s in got_stems if s.role.value == "others")
        assert others.display_name == "Others"
        assert others.provenance == {
            "kind": "bass_residual",
            "formula": "reference_mix - bass",
        }

        got_set = separation.get_result_set(outcome.result_set.id)
        assert got_set is not None
        assert got_set.bass_residual_asset_id == others.audio_asset_id
        assert others.audio_asset_id in {a.id for a in outcome.assets}

        metrics = got_set.reconstruction_metrics
        assert metrics is not None
        assert metrics["residual_reconstruction_max"] < 1e-5

        # The residual is reference − bass: DC 1.0 − 0.4 = 0.6, up to the
        # resampler's start transient on the bass stem.
        residual_asset = next(a for a in outcome.assets if a.id == others.audio_asset_id)
        residual_path = data / "assets" / f"{residual_asset.content_hash}.pcm"
        residual = np.fromfile(residual_path, dtype="<f4")
        np.testing.assert_allclose(residual, 0.6, atol=1e-5)

        # Five waveform jobs (one per published asset).
        queued = jobs.list_jobs_for_project(run.project_id)
        assert len([j for j in queued if j.job_type.value == "waveform"]) == 5

    @pytest.mark.asyncio
    async def test_failure_leaves_no_partial_records(self, tmp_path: Path) -> None:
        run, staging_dir, attempt_dir, reference_path = self._staged_run(
            tmp_path, SeparationMode.FOUR_STEMS
        )
        # One stem is one frame long at the model rate: the restore's
        # endpoint policy fails (48001 != 48000), never a blind trim.
        _write_f32le_pcm(
            attempt_dir / "drums.pcm",
            dc_offset(MODEL_RATE + 1, MODEL_RATE, 0.2, channels=2),
        )
        data = tmp_path / "data"
        db_path = data / "basseparate.db"
        separation = SeparationRepository(db_path)
        jobs = JobRepository(db_path)
        source = SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
        )

        with pytest.raises(PublicationError):
            await publish_separation_result(
                run=run,
                staging_dir=staging_dir,
                attempt_dir=attempt_dir,
                stem_labels=list(self.LABELS),
                reference_path=reference_path,
                source=source,
                sample_rate=PROJECT_RATE,
                duration_frames=PROJECT_RATE,
                channel_count=2,
                asset_dir=data / "assets",
                separation_repository=separation,
                job_repository=jobs,
            )

        # No partial records, no published assets, no waveform jobs.
        assert separation.list_result_sets_for_project(run.project_id) == []
        assert separation.list_runs_for_project(run.project_id)[0].status is (
            SeparationRunStatus.RUNNING
        )
        assert (data / "assets").is_dir() is False
        assert jobs.list_jobs_for_project(run.project_id) == []
        # Staging is kept for diagnostics on failure.
        assert (attempt_dir / "drums.pcm").is_file()
        assert (staging_dir / "run-record.json").is_file()
        assert not (staging_dir / "restored").exists()

    @pytest.mark.asyncio
    async def test_queued_run_gets_started_at_backfilled(self, tmp_path: Path) -> None:
        # A queued run never started: no started_at.
        run, staging_dir, attempt_dir, reference_path = self._staged_run(
            tmp_path, SeparationMode.FOUR_STEMS, status=SeparationRunStatus.QUEUED
        )
        separation = SeparationRepository(tmp_path / "data" / "basseparate.db")
        source = SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
        )

        outcome = await publish_separation_result(
            run=run,
            staging_dir=staging_dir,
            attempt_dir=attempt_dir,
            stem_labels=list(self.LABELS),
            reference_path=reference_path,
            source=source,
            sample_rate=PROJECT_RATE,
            duration_frames=PROJECT_RATE,
            channel_count=2,
            asset_dir=tmp_path / "data" / "assets",
            separation_repository=separation,
        )

        got_run = separation.get_run(run.id)
        assert got_run is not None
        assert got_run.started_at is not None
        assert got_run.ended_at is not None
        assert outcome.run.started_at is not None

    def test_waveform_queueing_dedupes_per_asset(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        db_path = data / "basseparate.db"
        initialize_database(db_path)
        projects = ProjectRepository(db_path)
        jobs = JobRepository(db_path)
        project = projects.create_project("Song")
        from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata

        def asset(seed: int) -> AssetRecord:
            content_hash = f"{seed:02d}" * 32
            return AssetRecord(
                id=uuid.uuid4(),
                content_hash=content_hash,
                role=AssetRole.STEM,
                relative_path=f"data/assets/{content_hash}.pcm",
                media_type="application/octet-stream",
                byte_count=48000 * 2 * 4,
                created_at="2026-10-11T00:00:00Z",
                audio=AudioMetadata(
                    sample_rate=48000,
                    channel_count=2,
                    frame_count=48000,
                    sample_format="f32le",
                ),
            )

        a1, a2, a3 = asset(1), asset(2), asset(3)
        queued = queue_stem_waveforms(jobs, project.id, [a1, a2, a3])
        assert len(queued) == 3
        # A second pass over the same assets queues nothing new.
        assert queue_stem_waveforms(jobs, project.id, [a1, a2, a3]) == []
        # A fourth asset is queued.
        assert len(queue_stem_waveforms(jobs, project.id, [a1, asset(4)])) == 1
