"""Project-only database builder (M2.14, spec §16.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basseparate.portable.closure import PortableFormatError
from basseparate.portable.database import build_portable_database
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
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
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
            assert (
                conn.execute("SELECT COUNT(*) FROM separation_result_sets").fetchone()[0]
                == 1
            )
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
            assert conn.execute(
                "SELECT id FROM separation_result_sets"
            ).fetchone()[0] == seed.rs_a
            assert conn.execute("SELECT id FROM separation_runs").fetchone()[0] == seed.run_a
            # The project row kept its internal revision.
            assert conn.execute(
                "SELECT revision FROM projects WHERE id = ?", (seed.project_a,)
            ).fetchone()[0] == 5
        finally:
            conn.close()

    def test_schema_and_version_preserved(self, seed, tmp_path: Path) -> None:
        destination = tmp_path / "project.sqlite"
        build_portable_database(seed.db_path, seed.project_a, destination)
        conn = sqlite3.connect(destination)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
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
            build_portable_database(
                tmp_path / "nope.db", "x", tmp_path / "out.sqlite"
            )

    def test_missing_project_raises_and_leaves_no_file(
        self, seed, tmp_path: Path
    ) -> None:
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
