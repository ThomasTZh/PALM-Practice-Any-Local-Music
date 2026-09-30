"""Repository layer for projects and assets (M0.5).

Creates connections within each operation. Returns immutable domain
records. Uses parameterized SQL throughout.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from basseparate.domain.asset import AssetRecord, AssetRole
from basseparate.domain.project import ProjectRecord, ProjectStatus
from basseparate.storage.db import DatabaseError

SCHEMA_VERSION = 1


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_project(row: sqlite3.Row) -> ProjectRecord:
    return ProjectRecord(
        schema_version=row["schema_version"],
        id=uuid.UUID(row["id"]),
        name=row["name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=row["revision"],
        source_asset_id=uuid.UUID(row["source_asset_id"]) if row["source_asset_id"] else None,
        sample_rate=row["sample_rate"],
        duration_samples=row["duration_samples"],
        status=ProjectStatus(row["status"]),
    )


class ProjectRepository:
    """Synchronous repository for project and asset operations.

    Each method opens its own connection, performs the operation, and
    closes the connection. Safe to call from a thread pool.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def create_project(self, name: str) -> ProjectRecord:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        project_id = str(uuid.uuid4())
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO projects (id, name, created_at, updated_at, revision,
                                      source_asset_id, sample_rate, duration_samples,
                                      status, schema_version)
                VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, 'empty', ?)
                """,
                (project_id, name.strip(), now, now, SCHEMA_VERSION),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create project: {exc}") from exc
        finally:
            conn.close()

        record = self.get_project(uuid.UUID(project_id))
        assert record is not None
        return record

    def get_project(self, project_id: uuid.UUID) -> ProjectRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
            return _row_to_project(row) if row else None
        finally:
            conn.close()

    def list_projects(self) -> list[ProjectRecord]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
            return [_row_to_project(r) for r in rows]
        finally:
            conn.close()

    def register_asset(self, asset: AssetRecord) -> None:
        conn = _open(self._db_path)
        try:
            audio = asset.audio
            conn.execute(
                """
                INSERT INTO assets (id, content_hash, role, relative_path,
                                    media_type, byte_count, created_at,
                                    audio_sample_rate, audio_channel_count,
                                    audio_sample_count, audio_sample_format,
                                    revision)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(asset.id),
                    asset.content_hash,
                    asset.role.value,
                    asset.relative_path,
                    asset.media_type,
                    asset.byte_count,
                    asset.created_at.isoformat().replace("+00:00", "Z"),
                    audio.sample_rate if audio else None,
                    audio.channel_count if audio else None,
                    audio.sample_count if audio else None,
                    audio.sample_format if audio else None,
                    asset.revision,
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot register asset: {exc}") from exc
        finally:
            conn.close()

    def attach_asset(
        self, project_id: uuid.UUID, asset_id: uuid.UUID, role: AssetRole
    ) -> None:
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO project_assets (project_id, asset_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), str(asset_id), role.value),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot attach asset: {exc}") from exc
        finally:
            conn.close()
