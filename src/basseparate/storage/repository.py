"""Repository layer for projects, assets, imports, representations, jobs
(M0.5/M1.1/M1.4).

Creates connections within each operation. Returns immutable domain
records. Uses parameterized SQL throughout.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from basseparate import PROJECT_SCHEMA_VERSION
from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.import_record import (
    AudioStreamInfo,
    ImportRecord,
    ProbeResult,
    TransferState,
)
from basseparate.domain.media_job import (
    JobStage,
    JobState,
    JobType,
    MediaJob,
    assert_transition,
)
from basseparate.domain.project import ProjectRecord, ProjectStatus, WaveformStatus
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
)
from basseparate.storage.db import DatabaseError


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _row_to_project(row: sqlite3.Row) -> ProjectRecord:
    return ProjectRecord(
        schema_version=row["schema_version"],
        id=uuid.UUID(row["id"]),
        name=row["name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=row["revision"],
        status=ProjectStatus(row["status"]),
        source_asset_id=uuid.UUID(row["source_asset_id"]) if row["source_asset_id"] else None,
        canonical_asset_id=(
            uuid.UUID(row["canonical_asset_id"]) if row["canonical_asset_id"] else None
        ),
        monitoring_asset_id=(
            uuid.UUID(row["monitoring_asset_id"]) if row["monitoring_asset_id"] else None
        ),
        monitoring_left_channel=row["monitoring_left_channel"],
        monitoring_right_channel=row["monitoring_right_channel"],
        source_stream_index=row["source_stream_index"],
        sample_rate=row["sample_rate"],
        duration_frames=row["duration_frames"],
        source_channel_count=row["source_channel_count"],
        source_channel_layout=row["source_channel_layout"],
        decode_profile_version=row["decode_profile_version"],
        waveform_status=WaveformStatus(row["waveform_status"]),
        source_metadata=json.loads(row["source_metadata"]),
    )


def _row_to_asset(row: sqlite3.Row) -> AssetRecord:
    audio = None
    if row["audio_sample_rate"] is not None:
        audio = AudioMetadata(
            sample_rate=row["audio_sample_rate"],
            channel_count=row["audio_channel_count"],
            frame_count=row["audio_frame_count"],
            sample_format=row["audio_sample_format"],
        )
    return AssetRecord(
        id=uuid.UUID(row["id"]),
        content_hash=row["content_hash"],
        role=AssetRole(row["role"]),
        relative_path=row["relative_path"],
        media_type=row["media_type"],
        byte_count=row["byte_count"],
        created_at=row["created_at"],
        audio=audio,
        revision=row["revision"],
    )


def _row_to_probe_result(value: str | None) -> ProbeResult | None:
    if value is None:
        return None
    data = json.loads(value)
    streams = tuple(AudioStreamInfo(**s) for s in data.pop("audio_streams"))
    return ProbeResult(audio_streams=streams, **data)


def _row_to_import(row: sqlite3.Row) -> ImportRecord:
    return ImportRecord(
        id=uuid.UUID(row["id"]),
        project_id=uuid.UUID(row["project_id"]),
        filename=row["filename"],
        declared_byte_count=row["declared_byte_count"],
        received_byte_count=row["received_byte_count"],
        source_sha256=row["source_sha256"],
        transfer_state=TransferState(row["transfer_state"]),
        probe_result=_row_to_probe_result(row["probe_result"]),
        selected_stream_index=row["selected_stream_index"],
        job_ids=tuple(uuid.UUID(j) for j in json.loads(row["job_ids"])),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_representation(row: sqlite3.Row) -> AudioRepresentation:
    return AudioRepresentation(
        asset_id=uuid.UUID(row["asset_id"]),
        parent_asset_id=(uuid.UUID(row["parent_asset_id"]) if row["parent_asset_id"] else None),
        role=RepresentationRole(row["role"]),
        sample_rate=row["sample_rate"],
        channel_count=row["channel_count"],
        channel_layout=row["channel_layout"],
        frame_count=row["frame_count"],
        encoding=row["encoding"],
        interleaving=row["interleaving"],
        content_hash=row["content_hash"],
        transform_key=row["transform_key"],
        time_mapping=TimeMapping(
            project_rate=row["project_rate"],
            representation_rate=row["representation_rate"],
        ),
        provenance=RepresentationProvenance(
            tool=row["tool"],
            tool_version=row["tool_version"],
            profile_version=row["profile_version"],
            created_at=row["created_at"],
        ),
    )


def _row_to_job(row: sqlite3.Row) -> MediaJob:
    return MediaJob(
        id=uuid.UUID(row["id"]),
        project_id=uuid.UUID(row["project_id"]),
        import_id=uuid.UUID(row["import_id"]) if row["import_id"] else None,
        job_type=JobType(row["job_type"]),
        state=JobState(row["state"]),
        stage=JobStage(row["stage"]) if row["stage"] else None,
        progress_fraction=row["progress_fraction"],
        progress_detail=row["progress_detail"],
        result=json.loads(row["result"]) if row["result"] else None,
        error_code=row["error_code"],
        error=row["error"],
        max_threads=row["max_threads"],
        parameters=json.loads(row["parameters"]) if row["parameters"] else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProjectRepository:
    """Synchronous repository for project and asset operations.

    Each method opens its own connection, performs the operation, and
    closes the connection. Safe to call from a thread pool.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def create_project(self, name: str) -> ProjectRecord:
        now = _now()
        project_id = str(uuid.uuid4())
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO projects (id, name, created_at, updated_at, revision,
                                      source_asset_id, sample_rate, duration_frames,
                                      status, schema_version)
                VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, 'empty', ?)
                """,
                (project_id, name.strip(), now, now, PROJECT_SCHEMA_VERSION),
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
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (str(project_id),)).fetchone()
            return _row_to_project(row) if row else None
        finally:
            conn.close()

    def list_projects(self) -> list[ProjectRecord]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
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
                                    audio_frame_count, audio_sample_format,
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
                    audio.frame_count if audio else None,
                    audio.sample_format if audio else None,
                    asset.revision,
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot register asset: {exc}") from exc
        finally:
            conn.close()

    def attach_asset(self, project_id: uuid.UUID, asset_id: uuid.UUID, role: AssetRole) -> None:
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

    def get_asset_by_hash(self, content_hash: str) -> AssetRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM assets WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            return _row_to_asset(row) if row else None
        finally:
            conn.close()

    def get_asset(self, asset_id: uuid.UUID) -> AssetRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM assets WHERE id = ?", (str(asset_id),)
            ).fetchone()
            return _row_to_asset(row) if row else None
        finally:
            conn.close()

    def publish_source(
        self,
        project_id: uuid.UUID,
        original_asset: AssetRecord,
        pcm_asset: AssetRecord,
        representation: AudioRepresentation,
        source_stream_index: int,
        sample_rate: int,
        duration_frames: int,
        channel_count: int,
        channel_layout: str,
        decode_profile_version: int,
        source_metadata: dict[str, str],
    ) -> ProjectRecord:
        """Atomically publish a decoded source to a project (M1.5).

        One transaction: register both assets (idempotent), attach them,
        register the canonical representation (idempotent), and set all eight
        source-readiness fields together with ``status='ready'``. The
        co-presence invariant of ``ProjectRecord`` holds by construction.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for asset in (original_asset, pcm_asset):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO assets (id, content_hash, role, relative_path,
                                                  media_type, byte_count, created_at,
                                                  audio_sample_rate, audio_channel_count,
                                                  audio_frame_count, audio_sample_format,
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
                        asset.audio.sample_rate if asset.audio else None,
                        asset.audio.channel_count if asset.audio else None,
                        asset.audio.frame_count if asset.audio else None,
                        asset.audio.sample_format if asset.audio else None,
                        asset.revision,
                    ),
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO project_assets (project_id, asset_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), str(original_asset.id), AssetRole.SOURCE_ORIGINAL.value),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO project_assets (project_id, asset_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), str(pcm_asset.id), AssetRole.SOURCE_PCM.value),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO representations (asset_id, parent_asset_id, role,
                                                       sample_rate, channel_count,
                                                       channel_layout, frame_count,
                                                       encoding, interleaving,
                                                       transform_key, project_rate,
                                                       representation_rate, tool,
                                                       tool_version, profile_version,
                                                       created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(representation.asset_id),
                    str(representation.parent_asset_id)
                    if representation.parent_asset_id
                    else None,
                    representation.role.value,
                    representation.sample_rate,
                    representation.channel_count,
                    representation.channel_layout,
                    representation.frame_count,
                    representation.encoding,
                    representation.interleaving,
                    representation.transform_key,
                    representation.time_mapping.project_rate,
                    representation.time_mapping.representation_rate,
                    representation.provenance.tool,
                    representation.provenance.tool_version,
                    representation.provenance.profile_version,
                    representation.provenance.created_at.isoformat().replace("+00:00", "Z"),
                ),
            )
            conn.execute(
                """
                UPDATE projects SET
                    source_asset_id = ?,
                    canonical_asset_id = ?,
                    monitoring_asset_id = NULL,
                    monitoring_left_channel = NULL,
                    monitoring_right_channel = NULL,
                    source_stream_index = ?,
                    sample_rate = ?,
                    duration_frames = ?,
                    source_channel_count = ?,
                    source_channel_layout = ?,
                    decode_profile_version = ?,
                    source_metadata = ?,
                    status = 'ready',
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ?
                """,
                (
                    str(original_asset.id),
                    str(pcm_asset.id),
                    source_stream_index,
                    sample_rate,
                    duration_frames,
                    channel_count,
                    channel_layout,
                    decode_profile_version,
                    json.dumps(source_metadata, sort_keys=True),
                    _now(),
                    str(project_id),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise DatabaseError(f"cannot publish source: {exc}") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        updated = self.get_project(project_id)
        assert updated is not None
        return updated

    def set_monitoring(
        self,
        project_id: uuid.UUID,
        asset: AssetRecord,
        left_channel: int,
        right_channel: int,
    ) -> ProjectRecord:
        """Attach a monitoring representation to a project (M1.7).

        One transaction: register the asset (idempotent), attach it as
        ``derived_pcm``, and set ``monitoring_asset_id`` with the effective
        left/right source channels. A project without a canonical asset
        cannot gain a monitoring representation.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT canonical_asset_id FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
            if row is None:
                raise DatabaseError(f"project {project_id} not found")
            if row["canonical_asset_id"] is None:
                raise DatabaseError(f"project {project_id} has no canonical asset")
            audio = asset.audio
            conn.execute(
                """
                INSERT OR IGNORE INTO assets (id, content_hash, role, relative_path,
                                              media_type, byte_count, created_at,
                                              audio_sample_rate, audio_channel_count,
                                              audio_frame_count, audio_sample_format,
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
                    audio.frame_count if audio else None,
                    audio.sample_format if audio else None,
                    asset.revision,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO project_assets (project_id, asset_id, role)
                VALUES (?, ?, ?)
                """,
                (str(project_id), str(asset.id), AssetRole.DERIVED_PCM.value),
            )
            conn.execute(
                """
                UPDATE projects SET
                    monitoring_asset_id = ?,
                    monitoring_left_channel = ?,
                    monitoring_right_channel = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ?
                """,
                (str(asset.id), left_channel, right_channel, _now(), str(project_id)),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise DatabaseError(f"cannot set monitoring representation: {exc}") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        updated = self.get_project(project_id)
        assert updated is not None
        return updated

    def set_monitoring_channels(
        self, project_id: uuid.UUID, left_channel: int, right_channel: int
    ) -> ProjectRecord:
        """Store the user's L/R monitoring selection for an unknown layout.

        The project must be ready; the channels are validated against the
        source channel count by the caller (and by the domain model).
        """
        conn = _open(self._db_path)
        try:
            cur = conn.execute(
                """
                UPDATE projects SET
                    monitoring_left_channel = ?,
                    monitoring_right_channel = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ?
                """,
                (left_channel, right_channel, _now(), str(project_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"project {project_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()

        updated = self.get_project(project_id)
        assert updated is not None
        return updated


class ImportRepository:
    """Synchronous repository for import sessions."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def create_import(
        self,
        project_id: uuid.UUID,
        filename: str,
        declared_byte_count: int,
    ) -> ImportRecord:
        now = _now()
        import_id = str(uuid.uuid4())
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO imports (id, project_id, filename, declared_byte_count,
                                     received_byte_count, transfer_state,
                                     job_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 'created', '[]', ?, ?)
                """,
                (import_id, str(project_id), filename, declared_byte_count, now, now),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create import: {exc}") from exc
        finally:
            conn.close()

        record = self.get_import(uuid.UUID(import_id))
        assert record is not None
        return record

    def get_import(self, import_id: uuid.UUID) -> ImportRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute("SELECT * FROM imports WHERE id = ?", (str(import_id),)).fetchone()
            return _row_to_import(row) if row else None
        finally:
            conn.close()

    def list_imports_for_project(self, project_id: uuid.UUID) -> list[ImportRecord]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM imports WHERE project_id = ? ORDER BY created_at DESC",
                (str(project_id),),
            ).fetchall()
            return [_row_to_import(r) for r in rows]
        finally:
            conn.close()

    def update_transfer_state(
        self,
        import_id: uuid.UUID,
        state: TransferState,
        received_byte_count: int | None = None,
        source_sha256: str | None = None,
        error: str | None = None,
    ) -> ImportRecord:
        conn = _open(self._db_path)
        try:
            sets = ["transfer_state = ?", "updated_at = ?"]
            params: list[object] = [state.value, _now()]
            if received_byte_count is not None:
                sets.append("received_byte_count = ?")
                params.append(received_byte_count)
            if source_sha256 is not None:
                sets.append("source_sha256 = ?")
                params.append(source_sha256)
            if error is not None:
                sets.append("error = ?")
                params.append(error)
            params.append(str(import_id))
            cur = conn.execute(f"UPDATE imports SET {', '.join(sets)} WHERE id = ?", params)
            if cur.rowcount != 1:
                raise DatabaseError(f"import {import_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_import(import_id)
        assert record is not None
        return record

    def set_probe_result(self, import_id: uuid.UUID, probe: ProbeResult) -> ImportRecord:
        payload = {
            "format_name": probe.format_name,
            "estimated_duration_seconds": probe.estimated_duration_seconds,
            "byte_count": probe.byte_count,
            "title": probe.title,
            "artist": probe.artist,
            "ffmpeg_version": probe.ffmpeg_version,
            "ffprobe_version": probe.ffprobe_version,
            "audio_streams": [s.model_dump() for s in probe.audio_streams],
        }
        conn = _open(self._db_path)
        try:
            cur = conn.execute(
                "UPDATE imports SET probe_result = ?, updated_at = ? WHERE id = ?",
                (json.dumps(payload), _now(), str(import_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"import {import_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_import(import_id)
        assert record is not None
        return record

    def set_selected_stream(self, import_id: uuid.UUID, stream_index: int) -> ImportRecord:
        conn = _open(self._db_path)
        try:
            cur = conn.execute(
                "UPDATE imports SET selected_stream_index = ?, updated_at = ? WHERE id = ?",
                (stream_index, _now(), str(import_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"import {import_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_import(import_id)
        assert record is not None
        return record

    def add_job_id(self, import_id: uuid.UUID, job_id: uuid.UUID) -> ImportRecord:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT job_ids FROM imports WHERE id = ?", (str(import_id),)
            ).fetchone()
            if row is None:
                raise DatabaseError(f"import {import_id} not found")
            jobs: list[str] = json.loads(row["job_ids"])
            jobs.append(str(job_id))
            conn.execute(
                "UPDATE imports SET job_ids = ?, updated_at = ? WHERE id = ?",
                (json.dumps(jobs), _now(), str(import_id)),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_import(import_id)
        assert record is not None
        return record


class JobRepository:
    """Synchronous repository for durable media jobs (M1.4).

    The backend owns every job state write. State transitions are
    validated against the job state machine; invalid transitions raise
    ``InvalidJobTransition``.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def create_job(
        self,
        project_id: uuid.UUID,
        job_type: JobType,
        import_id: uuid.UUID | None = None,
        max_threads: int = 4,
        parameters: dict[str, Any] | None = None,
    ) -> MediaJob:
        now = _now()
        job_id = str(uuid.uuid4())
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO media_jobs (id, project_id, import_id, job_type, state,
                                        max_threads, parameters, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(project_id),
                    str(import_id) if import_id else None,
                    job_type.value,
                    max_threads,
                    json.dumps(parameters or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create job: {exc}") from exc
        finally:
            conn.close()

        record = self.get_job(uuid.UUID(job_id))
        assert record is not None
        return record

    def get_job(self, job_id: uuid.UUID) -> MediaJob | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute("SELECT * FROM media_jobs WHERE id = ?", (str(job_id),)).fetchone()
            return _row_to_job(row) if row else None
        finally:
            conn.close()

    def list_jobs_for_project(self, project_id: uuid.UUID) -> list[MediaJob]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM media_jobs WHERE project_id = ? ORDER BY created_at",
                (str(project_id),),
            ).fetchall()
            return [_row_to_job(r) for r in rows]
        finally:
            conn.close()

    def list_jobs_by_state(self, state: JobState) -> list[MediaJob]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM media_jobs WHERE state = ? ORDER BY created_at",
                (state.value,),
            ).fetchall()
            return [_row_to_job(r) for r in rows]
        finally:
            conn.close()

    def _current_state(self, job_id: uuid.UUID, conn: sqlite3.Connection) -> JobState:
        row = conn.execute("SELECT state FROM media_jobs WHERE id = ?", (str(job_id),)).fetchone()
        if row is None:
            raise DatabaseError(f"job {job_id} not found")
        return JobState(row["state"])

    def set_state(self, job_id: uuid.UUID, state: JobState) -> MediaJob:
        """Transition a job to ``state``, validating the state machine."""
        conn = _open(self._db_path)
        try:
            current = self._current_state(job_id, conn)
            assert_transition(current, state)
            cur = conn.execute(
                "UPDATE media_jobs SET state = ?, updated_at = ? WHERE id = ?",
                (state.value, _now(), str(job_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"job {job_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_job(job_id)
        assert record is not None
        return record

    def set_progress(
        self,
        job_id: uuid.UUID,
        stage: JobStage | None = None,
        fraction: float | None = None,
        detail: str | None = None,
    ) -> MediaJob:
        conn = _open(self._db_path)
        try:
            self._current_state(job_id, conn)
            sets = ["updated_at = ?"]
            params: list[object] = [_now()]
            if stage is not None:
                sets.append("stage = ?")
                params.append(stage.value)
            if fraction is not None:
                sets.append("progress_fraction = ?")
                params.append(fraction)
            if detail is not None:
                sets.append("progress_detail = ?")
                params.append(detail)
            params.append(str(job_id))
            cur = conn.execute(f"UPDATE media_jobs SET {', '.join(sets)} WHERE id = ?", params)
            if cur.rowcount != 1:
                raise DatabaseError(f"job {job_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_job(job_id)
        assert record is not None
        return record

    def complete_job(self, job_id: uuid.UUID, result: dict[str, Any]) -> MediaJob:
        """Mark a job completed with its verified result payload."""
        conn = _open(self._db_path)
        try:
            current = self._current_state(job_id, conn)
            assert_transition(current, JobState.COMPLETED)
            cur = conn.execute(
                "UPDATE media_jobs SET state = 'completed', stage = 'ready', "
                "result = ?, progress_fraction = 1, updated_at = ? WHERE id = ?",
                (json.dumps(result), _now(), str(job_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"job {job_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_job(job_id)
        assert record is not None
        return record

    def fail_job(self, job_id: uuid.UUID, code: str, message: str) -> MediaJob:
        """Mark a job failed with a structured error."""
        conn = _open(self._db_path)
        try:
            current = self._current_state(job_id, conn)
            assert_transition(current, JobState.FAILED)
            cur = conn.execute(
                "UPDATE media_jobs SET state = 'failed', error_code = ?, error = ?, "
                "updated_at = ? WHERE id = ?",
                (code, message[:2000], _now(), str(job_id)),
            )
            if cur.rowcount != 1:
                raise DatabaseError(f"job {job_id} not found")
            conn.execute("COMMIT")
        finally:
            conn.close()
        record = self.get_job(job_id)
        assert record is not None
        return record

    def mark_interrupted(self) -> int:
        """Flip running/cancelling jobs to interrupted (application restart).

        Returns the number of jobs flipped.
        """
        conn = _open(self._db_path)
        try:
            cur = conn.execute(
                "UPDATE media_jobs SET state = 'interrupted', updated_at = ? "
                "WHERE state IN ('running', 'cancelling')",
                (_now(),),
            )
            conn.execute("COMMIT")
            return cur.rowcount
        finally:
            conn.close()


class RepresentationRepository:
    """Synchronous repository for audio representation metadata."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def register_representation(self, representation: AudioRepresentation) -> None:
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO representations (asset_id, parent_asset_id, role,
                                             sample_rate, channel_count,
                                             channel_layout, frame_count,
                                             encoding, interleaving,
                                             transform_key, project_rate,
                                             representation_rate, tool,
                                             tool_version, profile_version,
                                             created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(representation.asset_id),
                    str(representation.parent_asset_id) if representation.parent_asset_id else None,
                    representation.role.value,
                    representation.sample_rate,
                    representation.channel_count,
                    representation.channel_layout,
                    representation.frame_count,
                    representation.encoding,
                    representation.interleaving,
                    representation.transform_key,
                    representation.time_mapping.project_rate,
                    representation.time_mapping.representation_rate,
                    representation.provenance.tool,
                    representation.provenance.tool_version,
                    representation.provenance.profile_version,
                    representation.provenance.created_at.isoformat().replace("+00:00", "Z"),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot register representation: {exc}") from exc
        finally:
            conn.close()

    def get_representation(self, asset_id: uuid.UUID) -> AudioRepresentation | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                """
                SELECT r.*, a.content_hash FROM representations r
                JOIN assets a ON a.id = r.asset_id
                WHERE r.asset_id = ?
                """,
                (str(asset_id),),
            ).fetchone()
            if row is None:
                return None
            return _row_to_representation(row)
        finally:
            conn.close()

    def find_playback(
        self, parent_asset_id: uuid.UUID, representation_rate: int
    ) -> AudioRepresentation | None:
        """The playback-rate representation of a parent asset at a rate (M1.7)."""
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                """
                SELECT r.*, a.content_hash FROM representations r
                JOIN assets a ON a.id = r.asset_id
                WHERE r.parent_asset_id = ?
                  AND r.role = 'playback_rate'
                  AND r.representation_rate = ?
                """,
                (str(parent_asset_id), representation_rate),
            ).fetchone()
            if row is None:
                return None
            return _row_to_representation(row)
        finally:
            conn.close()

    def list_representations_for_asset(
        self, parent_asset_id: uuid.UUID
    ) -> list[AudioRepresentation]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT r.*, a.content_hash FROM representations r
                JOIN assets a ON a.id = r.asset_id
                WHERE r.parent_asset_id = ?
                ORDER BY r.created_at
                """,
                (str(parent_asset_id),),
            ).fetchall()
            return [_row_to_representation(row) for row in rows]
        finally:
            conn.close()
