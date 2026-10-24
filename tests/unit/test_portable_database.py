"""Project-only database builder (M2.14, spec §16.5)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate import DATABASE_SCHEMA_VERSION
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    BarOriginState,
    BeatModelPreset,
    GridValidity,
    MusicalPosition,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmBranchRecord,
    RhythmInputRole,
)
from basseparate.domain.separation import DeviceType
from basseparate.portable.closure import PortableFormatError
from basseparate.portable.database import build_portable_database
from basseparate.storage.repository import RhythmRepository
from tests.unit.portable_seed import seed_two_projects


@pytest.fixture()
def seed(tmp_path: Path):
    return seed_two_projects(tmp_path)


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables
        }
    finally:
        conn.close()


class TestPortableDatabase:
    def test_single_project_only(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "out" / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        assert destination.is_file()
        conn = sqlite3.connect(destination)
        try:
            projects = conn.execute("SELECT id, name FROM projects").fetchall()
            assert projects == [(seed.project_a, "Song A")]
            # Closure rows present, unrelated rows absent.
            assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 7
            assert conn.execute("SELECT COUNT(*) FROM project_assets").fetchone()[0] == 7
            assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM markers").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM separation_result_sets").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM stems").fetchone()[0] == 2
            # No rows of project B anywhere.
            for table in (
                "project_assets",
                "imports",
                "media_jobs",
                "separation_runs",
                "separation_result_sets",
            ):
                stray = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id != ?",
                    (seed.project_a,),
                ).fetchone()[0]
                assert stray == 0, table
        finally:
            conn.close()

    def test_ids_preserved(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        conn = sqlite3.connect(destination)
        try:
            asset_ids = {row[0] for row in conn.execute("SELECT id FROM assets")}
            assert asset_ids == {
                seed.src_a,
                seed.can_a,
                seed.dmx_a,
                seed.stem1_a,
                seed.stem2_a,
                seed.res_a,
                seed.pb_a,
            }
            assert conn.execute("SELECT id FROM separation_result_sets").fetchone()[0] == seed.rs_a
            assert conn.execute("SELECT id FROM separation_runs").fetchone()[0] == seed.run_a
            # The project row kept its internal revision.
            assert (
                conn.execute(
                    "SELECT revision FROM projects WHERE id = ?", (seed.project_a,)
                ).fetchone()[0]
                == 5
            )
        finally:
            conn.close()

    def test_schema_and_version_preserved(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        conn = sqlite3.connect(destination)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            expected = {
                "projects",
                "portable_artifacts",
                "assets",
                "project_assets",
                "imports",
                "representations",
                "media_jobs",
                "waveform_caches",
                "markers",
                "project_history",
                "separation_runs",
                "separation_result_sets",
                "stems",
                "export_artifacts",
                "rhythm_analysis_runs",
                "rhythm_activation_artifacts",
                "rhythm_branches",
            }
            assert expected <= tables
        finally:
            conn.close()

    def test_foreign_keys_clean(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        conn = sqlite3.connect(destination)
        try:
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()

    def test_no_wal_sidecars(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        assert not destination.with_suffix(destination.suffix + "-wal").exists()
        assert not destination.with_suffix(destination.suffix + "-shm").exists()
        assert not destination.with_name(destination.name + "-journal").exists()

    def test_source_database_untouched(self, seed, tmp_path: Path) -> None:
        before = _counts(seed.db_path)
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        assert _counts(seed.db_path) == before
        # No WAL sidecars created on the source store.
        assert not seed.db_path.with_name(seed.db_path.name + "-wal").exists()
        assert not seed.db_path.with_name(seed.db_path.name + "-shm").exists()

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PortableFormatError, match="source database not found"):
            build_portable_database(tmp_path / "nope.db", "x", tmp_path / "out.sqlite")

    def test_missing_project_raises_and_leaves_no_file(self, seed, tmp_path: Path) -> None:
        import uuid

        destination = tmp_path / "out" / "project.sqlite"
        with pytest.raises(PortableFormatError, match="no such project"):
            build_portable_database(seed.db_path, str(uuid.uuid4()), destination)
        assert not destination.exists()
        assert not destination.with_name(destination.name + ".part").exists()

    def test_wal_mode_source(self, seed, tmp_path: Path) -> None:
        """A source database in WAL mode with a live -wal file (a
        concurrent connection holding it open) is snapshotted
        consistently."""
        conn = sqlite3.connect(seed.db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "INSERT INTO markers (id, project_id, position_frames, label, color, "
            "created_at, updated_at) VALUES (?, ?, 100, 'wal-marker', '#fff', ?, ?)",
            (
                "11111111-1111-4111-8111-111111111111",
                seed.project_a,
                "2026-10-17T00:00:00Z",
                "2026-10-17T00:00:00Z",
            ),
        )
        conn.commit()
        try:
            # The WAL file exists while this connection is open.
            assert seed.db_path.with_name(seed.db_path.name + "-wal").exists()
            destination = tmp_path / "project.sqlite"
            build_portable_database(seed.db_path, seed.project_a, destination)
            out = sqlite3.connect(destination)
            try:
                labels = [row[0] for row in out.execute("SELECT label FROM markers")]
                assert labels == ["wal-marker"]
            finally:
                out.close()
        finally:
            conn.close()

    def test_rhythm_rows_follow_the_project(self, seed, tmp_path: Path) -> None:
        """M3.1 rhythm rows are project-scoped and copied with the project."""
        repo = RhythmRepository(seed.db_path)
        now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
        hash_a = "ab" * 32
        hash_b = "cd" * 32

        def build(project_id: uuid.UUID, asset_id: str):
            run = RhythmAnalysisRun(
                id=uuid.uuid4(),
                project_id=project_id,
                input_asset_id=uuid.UUID(asset_id),
                input_hash=hash_a,
                input_role=RhythmInputRole.ORIGINAL_MIX,
                model_manifest_id="beat_this_final0",
                model_manifest_hash=hash_b,
                model_preset=BeatModelPreset.FINAL0,
                adapter_version="adapter-1",
                preprocessing_profile="beat-input-v1",
                preprocessing_version=1,
                requested_device=DeviceType.CPU,
                started_at=now,
                ended_at=now,
                status=RhythmAnalysisStatus.COMPLETED,
                activation_artifact_id=uuid.uuid4(),
            )
            manifest = ActivationArtifactManifest(
                artifact_id=run.activation_artifact_id,
                content_hash=hash_b,
                parent_run_id=run.id,
                source_asset_id=run.input_asset_id,
                source_hash=hash_a,
                model_frame_count=2,
                beat=ActivationArrayRef(
                    relative_path="rhythm/beats.npy", sha256=hash_a, element_count=2
                ),
                downbeat=ActivationArrayRef(
                    relative_path="rhythm/downbeats.npy", sha256=hash_b, element_count=2
                ),
                frame_mapping=ActivationFrameMapping(
                    model_sample_rate=22_050,
                    project_sample_rate=48_000,
                    frame_hop=512,
                ),
                output_semantics="sigmoid activation per model frame",
            )
            branch = RhythmBranchRecord(
                id=uuid.uuid4(),
                project_id=project_id,
                source_duration_frames=441_000,
                bar_origin=BarOriginState(
                    first_numbered_bar_position=MusicalPosition(numerator=0, denominator=1)
                ),
                grid_validity=GridValidity.UNMAPPED,
                created_at=now,
                updated_at=now,
            )
            repo.create_run(run)
            repo.create_artifact(project_id, manifest)
            repo.create_branch(branch)
            return run, manifest, branch

        run_a, manifest_a, branch_a = build(uuid.UUID(seed.project_a), seed.can_a)
        run_b, manifest_b, branch_b = build(uuid.UUID(seed.project_b), seed.can_b)
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)

        conn = sqlite3.connect(destination)
        conn.row_factory = sqlite3.Row
        try:
            assert conn.execute("SELECT id FROM rhythm_analysis_runs").fetchone()[0] == str(
                run_a.id
            )
            assert conn.execute("SELECT id FROM rhythm_activation_artifacts").fetchone()[0] == str(
                manifest_a.artifact_id
            )
            assert conn.execute("SELECT id FROM rhythm_branches").fetchone()[0] == str(branch_a.id)
            for table, other in (
                ("rhythm_analysis_runs", run_b.id),
                ("rhythm_activation_artifacts", manifest_b.artifact_id),
                ("rhythm_branches", branch_b.id),
            ):
                assert (
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE id = ?", (str(other),)
                    ).fetchone()[0]
                    == 0
                )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()
