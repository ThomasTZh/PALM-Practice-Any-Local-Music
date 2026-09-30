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


def _apply_migrations(
    conn: sqlite3.Connection, from_version: int, to_version: int
) -> None:
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
