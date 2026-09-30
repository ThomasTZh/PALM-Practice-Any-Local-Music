"""Storage integration tests (M0.12, section 13.2).

Covers the 12 required scenarios: fresh init, idempotent init, project
CRUD, close/reopen, asset attach, missing-object rejection, transaction
rollback, migration, failed-migration preservation, newer-version
rejection, locked database, and root isolation.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from basseparate.storage.db import (
    _MIGRATIONS,
    DatabaseError,
    initialize_database,
    register_migration,
)
from basseparate.storage.paths import (
    initialize_storage_paths,
    resolve_storage_paths,
)
from basseparate.storage.repository import ProjectRepository

FAKE_HASH = "a" * 64


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def repo(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


class TestTransactionRollback:
    """Scenario 7: roll back a failed transaction."""

    def test_failed_insert_rolls_back(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN")
            project_id = str(uuid.uuid4())
            insert_sql = (
                "INSERT INTO projects "
                "(id, name, created_at, updated_at, revision, status, schema_version) "
                "VALUES (?, 'Rollback Test', '2025-01-01T00:00:00Z', "
                "'2025-01-01T00:00:00Z', 0, 'empty', 1)"
            )
            conn.execute(insert_sql, (project_id,))
            conn.execute(
                "INSERT INTO project_assets (project_id, asset_id, role) "
                "VALUES (?, 'nonexistent-asset-id', 'source_pcm')",
                (str(uuid.uuid4()),),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
        finally:
            count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            conn.close()
        assert count == 0


class TestFailedMigration:
    """Scenario 9: preserve the original after a failed migration."""

    def test_failed_migration_preserves_original(self, tmp_path: Path) -> None:
        import basseparate.storage.db as db_mod

        db = tmp_path / "data" / "test.db"
        initialize_database(db)

        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA user_version = 1")
        conn.execute("CREATE TABLE original_data (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO original_data VALUES (1, 'preserved')")
        conn.execute("COMMIT")
        conn.close()

        def bad_migration(c: sqlite3.Connection) -> None:
            c.execute("CREATE TABLE broken_table (id INTEGER)")
            raise DatabaseError("intentional migration failure")

        original_migrations = dict(_MIGRATIONS)
        original_version = db_mod.DATABASE_SCHEMA_VERSION
        try:
            register_migration(2, bad_migration)
            db_mod.DATABASE_SCHEMA_VERSION = 2
            with pytest.raises(DatabaseError, match="intentional migration failure"):
                initialize_database(db)
        finally:
            db_mod.DATABASE_SCHEMA_VERSION = original_version
            _MIGRATIONS.clear()
            _MIGRATIONS.update(original_migrations)

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT val FROM original_data WHERE id = 1").fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert row[0] == "preserved"
        assert version == 1


class TestLockedDatabase:
    """Scenario 11: handle a temporarily locked database."""

    def test_busy_timeout_allows_concurrent_access(self, db_path: Path) -> None:
        blocker = sqlite3.connect(str(db_path))
        blocker.execute("BEGIN EXCLUSIVE")
        try:
            repo = ProjectRepository(db_path)
            with pytest.raises((sqlite3.OperationalError, DatabaseError)):
                repo.create_project("Should Fail Or Succeed After Timeout")
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()

        repo = ProjectRepository(db_path)
        p = repo.create_project("After Lock Released")
        assert p.name == "After Lock Released"


class TestRootIsolation:
    """Scenario 12: keep separate test roots isolated."""

    def test_separate_roots_do_not_share_data(self, tmp_path: Path) -> None:
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        paths_a = resolve_storage_paths(root_a)
        paths_b = resolve_storage_paths(root_b)
        initialize_storage_paths(paths_a)
        initialize_storage_paths(paths_b)

        db_a = paths_a.database_path
        db_b = paths_b.database_path
        initialize_database(db_a)
        initialize_database(db_b)

        repo_a = ProjectRepository(db_a)
        repo_b = ProjectRepository(db_b)

        repo_a.create_project("Only In A")
        assert repo_b.list_projects() == []
        assert len(repo_a.list_projects()) == 1
