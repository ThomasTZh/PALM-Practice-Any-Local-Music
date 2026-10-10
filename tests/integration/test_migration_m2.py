"""Migration 6 -> 7 tests (M2.1, spec §3.6).

Verifies that a genuine v6 database (pre-Milestone-2) upgrades to v7:
the separation tables appear, ``projects`` gains a defaulted
``practice_state`` column, and existing projects survive unchanged.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from basseparate.domain import ProjectRecord
from basseparate.storage.db import _apply_migrations, initialize_database
from basseparate.storage.repository import ProjectRepository

OLD_PROJECT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _build_v6_db(path: Path, project_id: uuid.UUID = OLD_PROJECT_ID) -> None:
    """Create a database at exactly schema version 6 with one project."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        _apply_migrations(conn, 0, 6)
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at, revision) "
            "VALUES (?, ?, ?, ?, 0)",
            (str(project_id), "Old Song", "2025-06-01T00:00:00Z", "2025-06-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def test_v6_to_v7_adds_separation_tables(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    _build_v6_db(path)

    # Sanity: the pre-migration database is at version 6.
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    conn.close()

    initialize_database(path)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"separation_runs", "separation_result_sets", "stems"} <= tables
        project_columns = {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
        assert "practice_state" in project_columns
    finally:
        conn.close()


def test_v6_project_survives_with_defaulted_practice_state(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    _build_v6_db(path)

    initialize_database(path)

    # The raw row carries an empty (defaulted) practice_state.
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT name, practice_state FROM projects WHERE id = ?",
            (str(OLD_PROJECT_ID),),
        ).fetchone()
        assert row["name"] == "Old Song"
        assert row["practice_state"] == "{}"
    finally:
        conn.close()

    # And the repository reconstructs a valid project with the default state.
    repo = ProjectRepository(path)
    project = repo.get_project(OLD_PROJECT_ID)
    assert project is not None
    assert project.name == "Old Song"
    assert isinstance(project, ProjectRecord)
    assert project.practice_state is not None
    assert project.practice_state.loop_enabled is False
