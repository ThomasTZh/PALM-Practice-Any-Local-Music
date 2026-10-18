"""Database connection, initialization, and migration (M0.5).

Initialization sequence:
1. Resolve the database location.
2. Open a connection.
3. Enable foreign keys.
4. Configure the busy timeout.
5. Enable WAL mode.
6. Use synchronous=FULL.
7. Read the database schema version.
8. Reject newer unsupported versions.
9. Apply required migrations.
10. Verify the resulting version.
11. Close the initialization connection.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from basseparate import DATABASE_SCHEMA_VERSION

log = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000

Migration = Callable[[sqlite3.Connection], None]


class DatabaseError(Exception):
    """Raised for unrecoverable database errors."""


class UnsupportedSchemaVersion(DatabaseError):
    """Raised when the database schema is newer than this application supports."""


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")


def _read_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


_MIGRATIONS: dict[int, Migration] = {}


def register_migration(target_version: int, fn: Migration) -> None:
    _MIGRATIONS[target_version] = fn


_MIGRATION_1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id               TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        revision         INTEGER NOT NULL DEFAULT 0,
        source_asset_id  TEXT,
        sample_rate      INTEGER,
        duration_samples INTEGER,
        status           TEXT NOT NULL DEFAULT 'empty'
                         CHECK (status IN ('empty', 'ready')),
        schema_version   INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id                    TEXT PRIMARY KEY,
        content_hash          TEXT NOT NULL UNIQUE,
        role                  TEXT NOT NULL,
        relative_path         TEXT NOT NULL,
        media_type            TEXT NOT NULL,
        byte_count            INTEGER NOT NULL DEFAULT 0,
        created_at            TEXT NOT NULL,
        audio_sample_rate     INTEGER,
        audio_channel_count   INTEGER,
        audio_sample_count    INTEGER,
        audio_sample_format   TEXT,
        revision              INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_assets (
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        asset_id    TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        role        TEXT NOT NULL,
        PRIMARY KEY (project_id, asset_id, role)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)",
    "CREATE INDEX IF NOT EXISTS idx_assets_content_hash ON assets(content_hash)",
)


def _migration_0_to_1(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_1_STATEMENTS:
        conn.execute(statement)


register_migration(1, _migration_0_to_1)

_MIGRATION_2_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE projects RENAME COLUMN duration_samples TO duration_frames",
    """
    ALTER TABLE projects ADD COLUMN canonical_asset_id TEXT
    """,
    "ALTER TABLE projects ADD COLUMN source_stream_index INTEGER",
    "ALTER TABLE projects ADD COLUMN source_channel_count INTEGER",
    "ALTER TABLE projects ADD COLUMN source_channel_layout TEXT",
    "ALTER TABLE projects ADD COLUMN decode_profile_version INTEGER",
    """
    ALTER TABLE projects ADD COLUMN waveform_status TEXT NOT NULL DEFAULT 'none'
        CHECK (waveform_status IN ('none', 'pending', 'ready'))
    """,
    "ALTER TABLE projects ADD COLUMN monitoring_asset_id TEXT",
    "ALTER TABLE projects ADD COLUMN source_metadata TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE assets RENAME COLUMN audio_sample_count TO audio_frame_count",
    """
    CREATE TABLE IF NOT EXISTS imports (
        id                   TEXT PRIMARY KEY,
        project_id           TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        filename             TEXT NOT NULL,
        declared_byte_count  INTEGER NOT NULL,
        received_byte_count  INTEGER NOT NULL DEFAULT 0,
        source_sha256        TEXT,
        transfer_state       TEXT NOT NULL DEFAULT 'created'
                             CHECK (transfer_state IN
                                    ('created', 'uploading', 'complete',
                                     'cancelled', 'failed')),
        probe_result         TEXT,
        selected_stream_index INTEGER,
        job_ids              TEXT NOT NULL DEFAULT '[]',
        error                TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS representations (
        asset_id          TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
        parent_asset_id   TEXT REFERENCES assets(id) ON DELETE SET NULL,
        role              TEXT NOT NULL
                          CHECK (role IN ('canonical', 'monitoring_downmix',
                                          'playback_rate')),
        sample_rate       INTEGER NOT NULL,
        channel_count     INTEGER NOT NULL,
        channel_layout    TEXT,
        frame_count       INTEGER NOT NULL,
        encoding          TEXT NOT NULL DEFAULT 'f32le',
        interleaving      TEXT NOT NULL DEFAULT 'interleaved',
        transform_key     TEXT NOT NULL,
        project_rate      INTEGER NOT NULL,
        representation_rate INTEGER NOT NULL,
        tool              TEXT NOT NULL,
        tool_version      TEXT NOT NULL,
        profile_version   INTEGER NOT NULL,
        created_at        TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_imports_project ON imports(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_representations_parent ON representations(parent_asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_representations_role ON representations(role)",
)


def _migration_1_to_2(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_2_STATEMENTS:
        conn.execute(statement)


register_migration(2, _migration_1_to_2)

_MIGRATION_3_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS media_jobs (
        id                 TEXT PRIMARY KEY,
        project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        import_id          TEXT REFERENCES imports(id) ON DELETE SET NULL,
        job_type           TEXT NOT NULL
                           CHECK (job_type IN ('probe', 'canonical_decode',
                                               'monitoring_downmix', 'playback_rate',
                                               'waveform')),
        state              TEXT NOT NULL DEFAULT 'queued'
                           CHECK (state IN ('queued', 'running', 'completed',
                                           'failed', 'cancelling', 'cancelled',
                                           'interrupted')),
        stage              TEXT
                           CHECK (stage IN ('transferring', 'verifying', 'inspecting',
                                            'decoding', 'preparing_playback',
                                            'building_waveform', 'ready')),
        progress_fraction  REAL CHECK (progress_fraction IS NULL
                                       OR (progress_fraction >= 0
                                           AND progress_fraction <= 1)),
        progress_detail    TEXT,
        result             TEXT,
        error_code         TEXT,
        error              TEXT,
        max_threads        INTEGER NOT NULL DEFAULT 4,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_project ON media_jobs(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_state ON media_jobs(state)",
)


def _migration_2_to_3(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_3_STATEMENTS:
        conn.execute(statement)


register_migration(3, _migration_2_to_3)

_MIGRATION_4_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE media_jobs ADD COLUMN parameters TEXT NOT NULL DEFAULT '{}'
    """,
    "ALTER TABLE projects ADD COLUMN monitoring_left_channel INTEGER",
    "ALTER TABLE projects ADD COLUMN monitoring_right_channel INTEGER",
)


def _migration_3_to_4(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_4_STATEMENTS:
        conn.execute(statement)


register_migration(4, _migration_3_to_4)

_MIGRATION_5_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS waveform_caches (
        id              TEXT PRIMARY KEY,
        asset_id        TEXT NOT NULL UNIQUE REFERENCES assets(id) ON DELETE CASCADE,
        cache_version   INTEGER NOT NULL,
        source_hash     TEXT NOT NULL,
        sample_rate     INTEGER NOT NULL,
        frame_count     INTEGER NOT NULL,
        channel_count   INTEGER NOT NULL,
        levels_json     TEXT NOT NULL,
        manifest_path   TEXT NOT NULL,
        created_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_waveform_caches_source_hash ON waveform_caches(source_hash)",
)


def _migration_4_to_5(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_5_STATEMENTS:
        conn.execute(statement)


register_migration(5, _migration_4_to_5)

_MIGRATION_6_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE projects ADD COLUMN working_state TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE projects ADD COLUMN history_seq INTEGER NOT NULL DEFAULT -1",
    """
    CREATE TABLE IF NOT EXISTS markers (
        id              TEXT PRIMARY KEY,
        project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        position_frames INTEGER NOT NULL CHECK (position_frames >= 0),
        label           TEXT NOT NULL,
        color           TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_markers_project ON markers(project_id)",
    """
    CREATE TABLE IF NOT EXISTS project_history (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        seq         INTEGER NOT NULL,
        kind        TEXT NOT NULL,
        before_json TEXT NOT NULL,
        after_json  TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        UNIQUE (project_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_project_history ON project_history(project_id, seq)",
)


def _migration_5_to_6(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_6_STATEMENTS:
        conn.execute(statement)


register_migration(6, _migration_5_to_6)

_MIGRATION_7_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS separation_runs (
        id              TEXT PRIMARY KEY,
        project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        status          TEXT NOT NULL
                        CHECK (status IN ('queued', 'running', 'completed',
                                          'failed', 'cancelled', 'interrupted')),
        requested_mode  TEXT NOT NULL,
        result_set_id   TEXT,
        record_json     TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_separation_runs_project ON separation_runs(project_id)",
    """
    CREATE TABLE IF NOT EXISTS separation_result_sets (
        id                TEXT PRIMARY KEY,
        run_id            TEXT NOT NULL REFERENCES separation_runs(id) ON DELETE CASCADE,
        project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        validation_status TEXT NOT NULL
                          CHECK (validation_status IN ('pending', 'valid', 'invalid')),
        created_at        TEXT NOT NULL,
        record_json       TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_separation_result_sets_project "
    "ON separation_result_sets(project_id)",
    """
    CREATE TABLE IF NOT EXISTS stems (
        id              TEXT PRIMARY KEY,
        result_set_id   TEXT NOT NULL
                        REFERENCES separation_result_sets(id) ON DELETE CASCADE,
        role            TEXT NOT NULL,
        record_json     TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_stems_result_set ON stems(result_set_id)",
    "ALTER TABLE projects ADD COLUMN practice_state TEXT NOT NULL DEFAULT '{}'",
)


def _migration_6_to_7(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_7_STATEMENTS:
        conn.execute(statement)


register_migration(7, _migration_6_to_7)

_MIGRATION_8_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE separation_runs ADD COLUMN cache_key TEXT",
    "ALTER TABLE separation_result_sets ADD COLUMN cache_key TEXT",
    "CREATE INDEX IF NOT EXISTS idx_separation_runs_key "
    "ON separation_runs(project_id, cache_key)",
    "CREATE INDEX IF NOT EXISTS idx_separation_result_sets_key "
    "ON separation_result_sets(project_id, cache_key)",
)


def _migration_7_to_8(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_8_STATEMENTS:
        conn.execute(statement)


register_migration(8, _migration_7_to_8)

#: Migration 9 (M2.13 §15): extend the media job types with ``export``
#: and the stage vocabulary with the export stages, and add the
#: per-stem export artifact table. SQLite cannot alter a CHECK
#: constraint, so ``media_jobs`` is rebuilt (rename, create, copy,
#: drop) with the copied columns listed explicitly.
_MIGRATION_9_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE media_jobs RENAME TO media_jobs_old",
    """
    CREATE TABLE media_jobs (
        id                 TEXT PRIMARY KEY,
        project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        import_id          TEXT REFERENCES imports(id) ON DELETE SET NULL,
        job_type           TEXT NOT NULL
                           CHECK (job_type IN ('probe', 'canonical_decode',
                                               'monitoring_downmix', 'playback_rate',
                                               'waveform', 'export')),
        state              TEXT NOT NULL DEFAULT 'queued'
                           CHECK (state IN ('queued', 'running', 'completed',
                                           'failed', 'cancelling', 'cancelled',
                                           'interrupted')),
        stage              TEXT
                           CHECK (stage IN ('transferring', 'verifying', 'inspecting',
                                            'decoding', 'preparing_playback',
                                            'building_waveform', 'verifying_stems',
                                            'encoding', 'verifying_export', 'ready')),
        progress_fraction  REAL CHECK (progress_fraction IS NULL
                                       OR (progress_fraction >= 0
                                           AND progress_fraction <= 1)),
        progress_detail    TEXT,
        result             TEXT,
        error_code         TEXT,
        error              TEXT,
        max_threads        INTEGER NOT NULL DEFAULT 4,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL,
        parameters         TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    INSERT INTO media_jobs (
        id, project_id, import_id, job_type, state, stage,
        progress_fraction, progress_detail, result, error_code, error,
        max_threads, created_at, updated_at, parameters
    )
    SELECT
        id, project_id, import_id, job_type, state, stage,
        progress_fraction, progress_detail, result, error_code, error,
        max_threads, created_at, updated_at, parameters
    FROM media_jobs_old
    """,
    "DROP TABLE media_jobs_old",
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_project ON media_jobs(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_state ON media_jobs(state)",
    """
    CREATE TABLE IF NOT EXISTS export_artifacts (
        id                TEXT PRIMARY KEY,
        job_id            TEXT NOT NULL REFERENCES media_jobs(id) ON DELETE CASCADE,
        project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        result_set_id     TEXT NOT NULL,
        stem_id           TEXT NOT NULL,
        audio_asset_id    TEXT NOT NULL,
        sha256            TEXT NOT NULL,
        relative_path     TEXT NOT NULL,
        download_filename TEXT NOT NULL,
        created_at        TEXT NOT NULL,
        record_json       TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_project "
    "ON export_artifacts(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_job ON export_artifacts(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_sha256 ON export_artifacts(sha256)",
)


def _migration_8_to_9(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_9_STATEMENTS:
        conn.execute(statement)


register_migration(9, _migration_8_to_9)


_MIGRATION_10_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS portable_artifacts (
        id                TEXT PRIMARY KEY,
        project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        saved_revision    INTEGER NOT NULL,
        sha256            TEXT NOT NULL,
        byte_size         INTEGER NOT NULL,
        relative_path     TEXT NOT NULL,
        download_filename TEXT NOT NULL,
        created_at        TEXT NOT NULL,
        record_json       TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_portable_artifacts_project "
    "ON portable_artifacts(project_id)",
)


def _migration_9_to_10(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_10_STATEMENTS:
        conn.execute(statement)


register_migration(10, _migration_9_to_10)


_MIGRATION_11_STATEMENTS: tuple[str, ...] = (
    # Provenance for projects opened from a portable archive (M2.16,
    # spec §18.5): JSON with the archived project identity
    # (archived_project_id, saved_revision, saved_at, source_filename).
    "ALTER TABLE projects ADD COLUMN portable_provenance TEXT",
)


def _migration_10_to_11(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_11_STATEMENTS:
        conn.execute(statement)


register_migration(11, _migration_10_to_11)


#: M2.17 adds the separation job type and its progress stages. SQLite
#: cannot alter a CHECK constraint, so ``media_jobs`` is rebuilt with the
#: migration-9 pattern (rename, create, copy, drop).
_MIGRATION_12_STATEMENTS: tuple[str, ...] = (
    # SQLite rewrites REFERENCES clauses when a table is renamed, so both
    # the parent (media_jobs) and its referencing table (export_artifacts)
    # are rebuilt: rename, create the new shape, copy, drop.
    "ALTER TABLE export_artifacts RENAME TO export_artifacts_old",
    "ALTER TABLE media_jobs RENAME TO media_jobs_old",
    """
    CREATE TABLE media_jobs (
        id                 TEXT PRIMARY KEY,
        project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        import_id          TEXT REFERENCES imports(id) ON DELETE SET NULL,
        job_type           TEXT NOT NULL
                           CHECK (job_type IN ('probe', 'canonical_decode',
                                               'monitoring_downmix', 'playback_rate',
                                               'waveform', 'export', 'separation')),
        state              TEXT NOT NULL DEFAULT 'queued'
                           CHECK (state IN ('queued', 'running', 'completed',
                                           'failed', 'cancelling', 'cancelled',
                                           'interrupted')),
        stage              TEXT
                           CHECK (stage IN ('transferring', 'verifying', 'inspecting',
                                            'decoding', 'preparing_playback',
                                            'preparing_input', 'separating',
                                            'building_waveform', 'verifying_stems',
                                            'encoding', 'verifying_export', 'ready')),
        progress_fraction  REAL CHECK (progress_fraction IS NULL
                                       OR (progress_fraction >= 0
                                           AND progress_fraction <= 1)),
        progress_detail    TEXT,
        result             TEXT,
        error_code         TEXT,
        error              TEXT,
        max_threads        INTEGER NOT NULL DEFAULT 4,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL,
        parameters         TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    INSERT INTO media_jobs (
        id, project_id, import_id, job_type, state, stage,
        progress_fraction, progress_detail, result, error_code, error,
        max_threads, created_at, updated_at, parameters
    )
    SELECT
        id, project_id, import_id, job_type, state, stage,
        progress_fraction, progress_detail, result, error_code, error,
        max_threads, created_at, updated_at, parameters
    FROM media_jobs_old
    """,
    """
    CREATE TABLE export_artifacts (
        id                TEXT PRIMARY KEY,
        job_id            TEXT NOT NULL REFERENCES media_jobs(id) ON DELETE CASCADE,
        project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        result_set_id     TEXT NOT NULL,
        stem_id           TEXT NOT NULL,
        audio_asset_id    TEXT NOT NULL,
        sha256            TEXT NOT NULL,
        relative_path     TEXT NOT NULL,
        download_filename TEXT NOT NULL,
        created_at        TEXT NOT NULL,
        record_json       TEXT NOT NULL
    )
    """,
    """
    INSERT INTO export_artifacts (
        id, job_id, project_id, result_set_id, stem_id, audio_asset_id,
        sha256, relative_path, download_filename, created_at, record_json
    )
    SELECT
        id, job_id, project_id, result_set_id, stem_id, audio_asset_id,
        sha256, relative_path, download_filename, created_at, record_json
    FROM export_artifacts_old
    """,
    "DROP TABLE export_artifacts_old",
    "DROP TABLE media_jobs_old",
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_project ON media_jobs(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_jobs_state ON media_jobs(state)",
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_project "
    "ON export_artifacts(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_job ON export_artifacts(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_export_artifacts_sha256 ON export_artifacts(sha256)",
)


def _migration_11_to_12(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATION_12_STATEMENTS:
        conn.execute(statement)


register_migration(12, _migration_11_to_12)


def initialize_database(db_path: Path) -> None:
    """Open, configure, migrate, and close the database.

    Creates parent directories if needed. Refuses to write a database
    whose schema version is newer than ``DATABASE_SCHEMA_VERSION``.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        _configure_connection(conn)

        current = _read_schema_version(conn)
        if current > DATABASE_SCHEMA_VERSION:
            raise UnsupportedSchemaVersion(
                f"database schema version {current} is newer than supported "
                f"version {DATABASE_SCHEMA_VERSION}; refusing to modify"
            )

        if current < DATABASE_SCHEMA_VERSION:
            _apply_migrations(conn, current, DATABASE_SCHEMA_VERSION)

        final = _read_schema_version(conn)
        if final != DATABASE_SCHEMA_VERSION:
            raise DatabaseError(
                f"schema version mismatch after migration: expected "
                f"{DATABASE_SCHEMA_VERSION}, got {final}"
            )
    finally:
        conn.close()


def _apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    for target in range(from_version + 1, to_version + 1):
        migration = _MIGRATIONS.get(target)
        if migration is None:
            raise DatabaseError(f"no migration registered for version {target}")
        log.info("applying migration %d → %d", from_version, target)
        try:
            conn.execute("BEGIN IMMEDIATE")
            migration(conn)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("migration %d → %d failed; rolled back", from_version, target)
            raise
        from_version = target
