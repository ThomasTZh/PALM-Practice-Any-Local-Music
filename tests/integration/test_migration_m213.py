"""Migration 8 -> 9 tests (M2.13, spec §15).

Verifies that a genuine v8 database upgrades to v9: the rebuilt
``media_jobs`` table accepts the ``export`` job type, preserves every
existing row and column, still rejects unknown job types, and the
``export_artifacts`` table appears.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from basseparate.domain.media_job import JobState, JobType
from basseparate.storage.db import _apply_migrations, initialize_database
from basseparate.storage.repository import JobRepository, ProjectRepository

PROJECT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
JOB_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _build_v8_db(path: Path) -> None:
    """Create a database at exactly schema version 8 with one waveform job."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        _apply_migrations(conn, 0, 8)
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at, revision) "
            "VALUES (?, ?, ?, ?, 0)",
            (str(PROJECT_ID), "Old Song", "2025-06-01T00:00:00Z", "2025-06-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO media_jobs (id, project_id, import_id, job_type, state, "
            "stage, progress_fraction, progress_detail, result, error_code, error, "
            "max_threads, created_at, updated_at, parameters) "
            "VALUES (?, ?, NULL, 'waveform', 'completed', 'ready', 1.0, NULL, "
            "'{\"levels\": []}', NULL, NULL, 4, ?, ?, '{\"asset_id\": \"a\"}')",
            (
                str(JOB_ID),
                str(PROJECT_ID),
                "2025-06-01T00:00:00Z",
                "2025-06-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_v8_to_v9_preserves_jobs_and_allows_export(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    _build_v8_db(path)

    initialize_database(path)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 11

        # The rebuilt table kept the old job row and its columns.
        row = conn.execute("SELECT * FROM media_jobs WHERE id = ?", (str(JOB_ID),)).fetchone()
        assert row is not None
        assert row["job_type"] == "waveform"
        assert row["state"] == "completed"
        assert row["parameters"] == '{"asset_id": "a"}'
        assert row["max_threads"] == 4

        # The export artifact table exists with its indexes.
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "export_artifacts" in tables
        indexes = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        assert "idx_export_artifacts_job" in indexes
        assert "idx_media_jobs_project" in indexes
        assert "idx_media_jobs_state" in indexes
    finally:
        conn.close()


def test_unknown_job_type_is_still_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at, revision) "
            "VALUES (?, ?, ?, ?, 0)",
            (str(PROJECT_ID), "Song", "2025-06-01T00:00:00Z", "2025-06-01T00:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO media_jobs (id, project_id, job_type, state, max_threads, "
                "created_at, updated_at) VALUES (?, ?, 'bogus', 'queued', 4, ?, ?)",
                (
                    str(JOB_ID),
                    str(PROJECT_ID),
                    "2025-06-01T00:00:00Z",
                    "2025-06-01T00:00:00Z",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_export_job_round_trips_through_the_repository(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    _build_v8_db(path)
    initialize_database(path)

    projects = ProjectRepository(path)
    jobs = JobRepository(path)
    project = projects.get_project(PROJECT_ID)
    assert project is not None

    job = jobs.create_job(
        project.id,
        JobType.EXPORT,
        parameters={"result_set_id": str(uuid.uuid4()), "asset_ids": ["a", "b"]},
    )
    assert job.job_type is JobType.EXPORT
    assert job.state is JobState.QUEUED
    fetched = jobs.get_job(job.id)
    assert fetched is not None
    assert fetched.parameters["asset_ids"] == ["a", "b"]
