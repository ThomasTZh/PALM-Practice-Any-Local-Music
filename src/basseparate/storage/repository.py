"""Repository layer for projects, assets, imports, representations, jobs,
and waveform caches (M0.5/M1.1/M1.4/M1.8).

Creates connections within each operation. Returns immutable domain
records. Uses parameterized SQL throughout.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from basseparate import PROJECT_SCHEMA_VERSION
from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.commands import (
    HISTORY_EXCLUDED_TYPES,
    CommandResult,
    ProjectCommandOp,
)
from basseparate.domain.export import ExportArtifact
from basseparate.domain.import_record import (
    AudioStreamInfo,
    ImportRecord,
    ProbeResult,
    TransferState,
)
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.media_job import (
    JobStage,
    JobState,
    JobType,
    MediaJob,
    assert_transition,
)
from basseparate.domain.portable import PortableArtifact
from basseparate.domain.practice import (
    DEFAULT_LOOP_COLOR,
    MAX_LOOP_NAME_LENGTH,
    MIN_REPEATABLE_LOOP_SECONDS,
    PlaybackMode,
    PracticeLoop,
    PracticeState,
    TrackSettings,
)
from basseparate.domain.project import (
    ProjectRecord,
    ProjectStatus,
    SelectionRange,
    WaveformStatus,
    WorkingState,
)
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
)
from basseparate.domain.separation import (
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    StemRecord,
    ValidationStatus,
)
from basseparate.domain.waveform import WaveformCacheRecord, WaveformLevelSummary, WaveformResult
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
        working_state=WorkingState.model_validate_json(row["working_state"]),
        practice_state=PracticeState.model_validate_json(row["practice_state"]),
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


def _row_to_waveform_cache(row: sqlite3.Row) -> WaveformCacheRecord:
    return WaveformCacheRecord(
        id=uuid.UUID(row["id"]),
        asset_id=uuid.UUID(row["asset_id"]),
        cache_version=row["cache_version"],
        source_hash=row["source_hash"],
        sample_rate=row["sample_rate"],
        frame_count=row["frame_count"],
        channel_count=row["channel_count"],
        levels=tuple(WaveformLevelSummary(**item) for item in json.loads(row["levels_json"])),
        manifest_path=row["manifest_path"],
        created_at=row["created_at"],
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


class ProjectMissingError(Exception):
    """The referenced project does not exist."""


class StaleRevisionError(Exception):
    """The command's base revision does not match the stored revision."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f"base revision is stale; current revision is {current_revision}")
        self.current_revision = current_revision


class NothingToUndoError(Exception):
    """The project has no undo history."""


class NothingToRedoError(Exception):
    """The project has no redo history."""


class MarkerNotFoundError(Exception):
    """The referenced marker does not exist in the project."""

    def __init__(self, marker_id: uuid.UUID) -> None:
        super().__init__(f"marker {marker_id} not found")
        self.marker_id = marker_id


class ResultSetNotFoundError(Exception):
    """The referenced separation result set does not belong to the project."""

    def __init__(self, result_set_id: uuid.UUID) -> None:
        super().__init__(f"result set {result_set_id} not found")
        self.result_set_id = result_set_id


class PlaybackModeRequiresResultSetError(Exception):
    """A stem playback mode requires an active separation result set."""


class LoopNotFoundError(Exception):
    """The referenced practice loop does not exist in the project."""

    def __init__(self, loop_id: uuid.UUID) -> None:
        super().__init__(f"loop {loop_id} not found")
        self.loop_id = loop_id


class LoopRangeInvalidError(Exception):
    """A loop's boundaries must satisfy ``0 ≤ start < end ≤ duration``."""

    def __init__(self, start: int, end: int, duration: int) -> None:
        super().__init__(
            f"loop range [{start}, {end}) is outside the source length {duration}"
        )
        self.start = start
        self.end = end
        self.duration = duration


class NoActiveLoopError(Exception):
    """Enabling looping requires an active loop."""


class LoopTooShortError(Exception):
    """Repeated playback requires an interval of at least 100 ms (§13.3.3)."""

    def __init__(self, frames: int, sample_rate: int) -> None:
        seconds = frames / sample_rate if sample_rate > 0 else 0.0
        super().__init__(
            f"loop of {seconds * 1000:.0f} ms is too short for repeated playback; "
            f"at least {MIN_REPEATABLE_LOOP_SECONDS * 1000:.0f} ms is required"
        )
        self.frames = frames
        self.sample_rate = sample_rate


class ProjectNotReady(Exception):
    """A position-valued op requires a ready project (a known duration)."""


#: Maximum history entries retained per project (M1.15, spec §17.4).
HISTORY_DEPTH_LIMIT = 200


def _row_to_marker(row: sqlite3.Row) -> MarkerRecord:
    return MarkerRecord(
        id=uuid.UUID(row["id"]),
        project_id=uuid.UUID(row["project_id"]),
        position_frames=row["position_frames"],
        label=row["label"],
        color=row["color"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _markers_for(conn: sqlite3.Connection, project_id: uuid.UUID | str) -> list[MarkerRecord]:
    rows = conn.execute(
        "SELECT * FROM markers WHERE project_id = ? ORDER BY position_frames, created_at",
        (str(project_id),),
    ).fetchall()
    return [_row_to_marker(r) for r in rows]


def _history_flags(
    conn: sqlite3.Connection, project_id: uuid.UUID | str, history_seq: int
) -> tuple[bool, bool]:
    """(can_undo, can_redo) for a project history pointer (M1.15 §17.4)."""
    can_undo = history_seq >= 0
    can_redo = False
    if can_undo:
        row = conn.execute(
            "SELECT 1 FROM project_history WHERE project_id = ? AND seq > ? LIMIT 1",
            (str(project_id), history_seq),
        ).fetchone()
        can_redo = row is not None
    return can_undo, can_redo


def _timestamp_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _history_snapshot(
    markers: list[MarkerRecord],
    working_state: WorkingState,
    practice_state: PracticeState,
) -> dict[str, object]:
    """A before/after history snapshot (M1.15, spec §17.4).

    ``last_position_frames`` is excluded so undo/redo never moves the
    playhead back to a position the playback clock had passed
    (§17.4.10); restore keeps the current position. The practice state
    (including the active result set selection, M2.7 §9.4.3) is carried
    so undo/redo restore it; pre-M2.7 snapshots lack the key and the
    restore keeps the current practice state.
    """
    ws = working_state.model_dump(mode="json")
    ws.pop("last_position_frames")
    return {
        "markers": [
            {
                "id": str(m.id),
                "position_frames": m.position_frames,
                "label": m.label,
                "color": m.color,
                "created_at": _timestamp_z(m.created_at),
                "updated_at": _timestamp_z(m.updated_at),
            }
            for m in markers
        ],
        "working_state": ws,
        "practice_state": practice_state.model_dump(mode="json"),
    }


def _markers_from_snapshot(
    snapshot: dict[str, object], project_id: uuid.UUID
) -> list[MarkerRecord]:
    raw_markers = cast(list[dict[str, object]], snapshot["markers"])
    return [
        MarkerRecord(
            id=uuid.UUID(str(m["id"])),
            project_id=project_id,
            position_frames=int(cast("int", m["position_frames"])),
            label=str(m["label"]),
            color=str(m["color"]),
            created_at=_parse_timestamp_z(str(m["created_at"])),
            updated_at=_parse_timestamp_z(str(m["updated_at"])),
        )
        for m in raw_markers
    ]


def _write_state(
    conn: sqlite3.Connection,
    project_id: str,
    markers: list[MarkerRecord],
    working_state: WorkingState,
    practice_state: PracticeState,
    revision: int,
    history_seq: int,
    now: str,
) -> None:
    """Write markers + working state + practice state + revision + history pointer atomically."""
    conn.execute("DELETE FROM markers WHERE project_id = ?", (project_id,))
    for m in markers:
        conn.execute(
            """
            INSERT INTO markers (id, project_id, position_frames, label, color,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(m.id),
                project_id,
                m.position_frames,
                m.label,
                m.color,
                _timestamp_z(m.created_at),
                _timestamp_z(m.updated_at),
            ),
        )
    conn.execute(
        """
        UPDATE projects SET working_state = ?, practice_state = ?, revision = ?,
                            updated_at = ?, history_seq = ?
        WHERE id = ?
        """,
        (
            working_state.model_dump_json(),
            practice_state.model_dump_json(),
            revision,
            now,
            history_seq,
            project_id,
        ),
    )


def _apply_op(
    project: ProjectRecord,
    markers: list[MarkerRecord],
    op: ProjectCommandOp,
) -> tuple[list[MarkerRecord], WorkingState, PracticeState]:
    """Apply one command op in memory.

    Returns (markers, working state, practice state); ops that do not
    touch the practice state return it unchanged.
    """
    ws = project.working_state
    ps = project.practice_state
    now = datetime.now(UTC)
    if op.type == "add_marker":
        marker = MarkerRecord(
            id=uuid.uuid4(),
            project_id=project.id,
            position_frames=op.position_frames,
            label=op.label,
            color=op.color,
            created_at=now,
            updated_at=now,
        )
        return [*markers, marker], ws, ps
    if op.type == "update_marker":
        current = next((m for m in markers if m.id == op.marker_id), None)
        if current is None:
            raise MarkerNotFoundError(op.marker_id)
        updated = [
            m
            if m.id != op.marker_id
            else MarkerRecord(
                id=m.id,
                project_id=m.project_id,
                position_frames=(
                    op.position_frames if op.position_frames is not None else m.position_frames
                ),
                label=op.label if op.label is not None else m.label,
                color=op.color if op.color is not None else m.color,
                created_at=m.created_at,
                updated_at=now,
            )
            for m in markers
        ]
        return updated, ws, ps
    if op.type == "delete_marker":
        if not any(m.id == op.marker_id for m in markers):
            raise MarkerNotFoundError(op.marker_id)
        return [m for m in markers if m.id != op.marker_id], ws, ps
    if op.type == "set_selection":
        selection = (
            None
            if op.start_frames is None
            else SelectionRange(start=op.start_frames, end=op.end_frames)
        )
        return markers, ws.model_copy(update={"selection": selection}), ps
    if op.type == "set_viewport":
        return markers, ws.model_copy(update={"viewport": op.viewport}), ps
    if op.type == "set_display":
        return markers, ws.model_copy(update={"channel_display": op.channel_display}), ps
    if op.type == "set_monitoring_volume":
        return markers, ws.model_copy(update={"monitoring_volume": op.volume}), ps
    if op.type == "set_position":
        return markers, ws.model_copy(update={"last_position_frames": op.position_frames}), ps
    if op.type == "set_follow_playhead":
        return markers, ws.model_copy(update={"follow_playhead": op.follow_playhead}), ps
    if op.type == "set_active_result_set":
        if op.result_set_id is None:
            # Clearing the selection reverts stem playback to the
            # original mix (PracticeState invariant: stem modes require
            # an active result set).
            ps_updated = ps.model_copy(update={"active_result_set_id": None})
            if ps_updated.playback_mode in (
                PlaybackMode.BASS_PAIR,
                PlaybackMode.FOUR_STEMS,
            ):
                ps_updated = ps_updated.model_copy(
                    update={"playback_mode": PlaybackMode.ORIGINAL}
                )
        else:
            ps_updated = ps.model_copy(update={"active_result_set_id": op.result_set_id})
        return markers, ws, ps_updated
    if op.type == "set_track_settings":
        # Patch semantics: None fields stay unchanged; a missing track
        # entry is created with defaults first (M2.8, spec §10.2).
        existing = ps.tracks.get(op.stem_role.value, TrackSettings())
        patch = {
            name: getattr(op, name)
            for name in (
                "gain",
                "balance",
                "mute",
                "solo",
                "visible",
                "display_height",
                "color",
            )
            if getattr(op, name) is not None
        }
        updated_track = existing.model_copy(update=patch)
        ps_updated = ps.model_copy(
            update={"tracks": {**ps.tracks, op.stem_role.value: updated_track}}
        )
        return markers, ws, ps_updated
    if op.type == "set_playback_mode":
        # Pre-validated in apply_command: stem modes require an active
        # result set.
        return markers, ws, ps.model_copy(update={"playback_mode": op.mode})
    if op.type == "set_master_gain":
        return markers, ws, ps.model_copy(update={"master_gain": op.gain})
    if op.type == "set_monitoring_limiter":
        return markers, ws, ps.model_copy(update={"monitoring_limiter": op.enabled})
    if op.type == "set_playback_speed":
        return markers, ws, ps.model_copy(update={"playback_speed": op.speed})
    if op.type == "add_loop":
        loop = PracticeLoop(
            id=uuid.uuid4(),
            name=op.name or f"Loop {len(ps.loops) + 1}",
            start_frames=op.start_frames,
            end_frames=op.end_frames,
            color=op.color or DEFAULT_LOOP_COLOR,
            repeat_count=op.repeat_count,
            boundary_fade=op.boundary_fade,
            created_at=now,
            updated_at=now,
        )
        return markers, ws, ps.model_copy(update={"loops": [*ps.loops, loop]})
    if op.type == "update_loop":
        current_loop = next((loop for loop in ps.loops if loop.id == op.loop_id), None)
        if current_loop is None:
            raise LoopNotFoundError(op.loop_id)
        loop_patch: dict[str, object] = {
            name: getattr(op, name)
            for name in ("start_frames", "end_frames", "name", "color", "boundary_fade")
            if getattr(op, name) is not None
        }
        if "repeat_count" in op.model_fields_set:
            # Absent = unchanged; explicit null = infinite (§13.1).
            loop_patch["repeat_count"] = op.repeat_count
        updated_loop = current_loop.model_copy(update={**loop_patch, "updated_at": now})
        return markers, ws, ps.model_copy(
            update={
                "loops": [
                    updated_loop if loop.id == op.loop_id else loop for loop in ps.loops
                ]
            }
        )
    if op.type == "delete_loop":
        if not any(loop.id == op.loop_id for loop in ps.loops):
            raise LoopNotFoundError(op.loop_id)
        ps_updated = ps.model_copy(
            update={"loops": [loop for loop in ps.loops if loop.id != op.loop_id]}
        )
        if ps.active_loop_id == op.loop_id:
            ps_updated = ps_updated.model_copy(
                update={"active_loop_id": None, "loop_enabled": False}
            )
        return markers, ws, ps_updated
    if op.type == "duplicate_loop":
        source = next((loop for loop in ps.loops if loop.id == op.loop_id), None)
        if source is None:
            raise LoopNotFoundError(op.loop_id)
        suffix = " copy"
        base_name = source.name[: MAX_LOOP_NAME_LENGTH - len(suffix)]
        copy = source.model_copy(
            update={
                "id": uuid.uuid4(),
                "name": f"{base_name}{suffix}",
                "created_at": now,
                "updated_at": now,
            }
        )
        return markers, ws, ps.model_copy(update={"loops": [*ps.loops, copy]})
    if op.type == "set_active_loop":
        ps_updated = ps.model_copy(update={"active_loop_id": op.loop_id})
        if op.loop_id is None:
            ps_updated = ps_updated.model_copy(update={"loop_enabled": False})
        return markers, ws, ps_updated
    if op.type == "set_loop_enabled":
        # Pre-validated in apply_command (active loop + ≥ 100 ms, §13.3.3).
        return markers, ws, ps.model_copy(update={"loop_enabled": op.enabled})
    raise ValueError(f"unknown command op type: {op.type}")


#: Ops that require a ready project (position-valued against a duration).
_READY_REQUIRED_TYPES: frozenset[str] = frozenset(
    {
        "add_marker",
        "set_position",
        "set_selection",
        "set_viewport",
        # M2.11: loop ranges are validated against the source duration and
        # the repeatable minimum (spec §13.3).
        "add_loop",
        "update_loop",
        "set_loop_enabled",
    }
)


def _validate_loop_range(start: int, end: int, duration: int) -> None:
    """``0 ≤ start < end ≤ duration`` (spec §13.3.1, §13.3.6)."""
    if start < 0 or end <= start or end > duration:
        raise LoopRangeInvalidError(start, end, duration)


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
            if row is None:
                return None
            record = _row_to_project(row)
            markers = _markers_for(conn, project_id)
            can_undo, can_redo = _history_flags(conn, project_id, row["history_seq"])
            return record.model_copy(
                update={"markers": markers, "can_undo": can_undo, "can_redo": can_redo}
            )
        finally:
            conn.close()

    def list_projects(self) -> list[ProjectRecord]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            records = [_row_to_project(r) for r in rows]
            marker_rows = conn.execute(
                "SELECT * FROM markers ORDER BY position_frames, created_at"
            ).fetchall()
            by_project: dict[str, list[MarkerRecord]] = {}
            for marker_row in marker_rows:
                by_project.setdefault(marker_row["project_id"], []).append(
                    _row_to_marker(marker_row)
                )
            return [
                record.model_copy(update={"markers": by_project.get(str(record.id), [])})
                for record in records
            ]
        finally:
            conn.close()

    def apply_command(
        self,
        project_id: uuid.UUID,
        op: ProjectCommandOp,
        base_revision: int,
    ) -> CommandResult:
        """Apply one project command transactionally (M1.15, spec §17.4).

        Validates the base revision (``StaleRevisionError`` on mismatch),
        applies the op, records one history entry (except ops in
        ``HISTORY_EXCLUDED_TYPES``), clears the redo branch, increments
        the revision, and returns the resulting project.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
            if row is None:
                raise ProjectMissingError()
            if row["revision"] != base_revision:
                raise StaleRevisionError(row["revision"])
            project = _row_to_project(row)
            if op.type in _READY_REQUIRED_TYPES and project.duration_frames is None:
                raise ProjectNotReady()
            if op.type == "set_active_result_set" and op.result_set_id is not None:
                rs_row = conn.execute(
                    "SELECT 1 FROM separation_result_sets WHERE id = ? AND project_id = ?",
                    (str(op.result_set_id), str(project_id)),
                ).fetchone()
                if rs_row is None:
                    raise ResultSetNotFoundError(op.result_set_id)
            if (
                op.type == "set_playback_mode"
                and op.mode in (PlaybackMode.BASS_PAIR, PlaybackMode.FOUR_STEMS)
                and project.practice_state.active_result_set_id is None
            ):
                raise PlaybackModeRequiresResultSetError()
            if op.type in ("add_loop", "update_loop"):
                # The ready check above guarantees a duration (M2.11 §13.3).
                assert project.duration_frames is not None
                if op.type == "add_loop":
                    _validate_loop_range(op.start_frames, op.end_frames, project.duration_frames)
                else:
                    current = next(
                        (
                            loop
                            for loop in project.practice_state.loops
                            if loop.id == op.loop_id
                        ),
                        None,
                    )
                    if current is None:
                        raise LoopNotFoundError(op.loop_id)
                    _validate_loop_range(
                        op.start_frames if op.start_frames is not None else current.start_frames,
                        op.end_frames if op.end_frames is not None else current.end_frames,
                        project.duration_frames,
                    )
            if op.type == "set_active_loop" and op.loop_id is not None and not any(
                loop.id == op.loop_id for loop in project.practice_state.loops
            ):
                raise LoopNotFoundError(op.loop_id)
            if op.type == "set_loop_enabled" and op.enabled:
                ps = project.practice_state
                active = next(
                    (loop for loop in ps.loops if loop.id == ps.active_loop_id), None
                )
                if active is None:
                    raise NoActiveLoopError()
                sample_rate = project.sample_rate or 0
                frames = active.end_frames - active.start_frames
                if frames < MIN_REPEATABLE_LOOP_SECONDS * sample_rate:
                    raise LoopTooShortError(frames, sample_rate)
            markers = _markers_for(conn, project_id)
            before = _history_snapshot(markers, project.working_state, project.practice_state)
            new_markers, new_ws, new_ps = _apply_op(project, markers, op)
            # Full re-validation (range checks against the duration).
            ProjectRecord(
                **{
                    **project.model_dump(),
                    "markers": new_markers,
                    "working_state": new_ws,
                    "practice_state": new_ps,
                }
            )
            now = _now()
            new_revision = row["revision"] + 1
            history_seq = row["history_seq"]
            if op.type not in HISTORY_EXCLUDED_TYPES:
                conn.execute(
                    "DELETE FROM project_history WHERE project_id = ? AND seq > ?",
                    (str(project_id), history_seq),
                )
                history_seq += 1
                after = _history_snapshot(new_markers, new_ws, new_ps)
                conn.execute(
                    """
                    INSERT INTO project_history (id, project_id, seq, kind,
                                                 before_json, after_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        str(project_id),
                        history_seq,
                        op.type,
                        json.dumps(before),
                        json.dumps(after),
                        now,
                    ),
                )
                count = conn.execute(
                    "SELECT COUNT(*) FROM project_history WHERE project_id = ?",
                    (str(project_id),),
                ).fetchone()[0]
                if count > HISTORY_DEPTH_LIMIT:
                    conn.execute(
                        """
                        DELETE FROM project_history
                        WHERE project_id = ? AND seq = (
                            SELECT MIN(seq) FROM project_history WHERE project_id = ?
                        )
                        """,
                        (str(project_id), str(project_id)),
                    )
            _write_state(
                conn,
                str(project_id),
                new_markers,
                new_ws,
                new_ps,
                new_revision,
                history_seq,
                now,
            )
            conn.execute("COMMIT")
        except (
            ProjectMissingError,
            StaleRevisionError,
            MarkerNotFoundError,
            ResultSetNotFoundError,
            PlaybackModeRequiresResultSetError,
            LoopNotFoundError,
            LoopRangeInvalidError,
            NoActiveLoopError,
            LoopTooShortError,
            ProjectNotReady,
        ):
            conn.execute("ROLLBACK")
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise DatabaseError(f"cannot apply command: {exc}") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        result = self.get_project(project_id)
        assert result is not None
        # The redo branch was deleted above: nothing to redo.
        return CommandResult(
            revision=result.revision,
            markers=result.markers,
            working_state=result.working_state,
            practice_state=result.practice_state,
            can_undo=history_seq >= 0,
            can_redo=False,
        )

    def _move_history(
        self,
        project_id: uuid.UUID,
        base_revision: int,
        direction: int,
    ) -> CommandResult:
        """Undo (direction -1) or redo (direction +1) one history entry."""
        no_entry_error: type[Exception]
        if direction < 0:
            no_entry_error = NothingToUndoError
            json_key = "before_json"
        else:
            no_entry_error = NothingToRedoError
            json_key = "after_json"
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
            if row is None:
                raise ProjectMissingError()
            if row["revision"] != base_revision:
                raise StaleRevisionError(row["revision"])
            seq = row["history_seq"]
            max_seq: int | None = None
            if direction < 0:
                if seq < 0:
                    raise no_entry_error()
                # Undo restores the *before* state of the entry at the
                # pointer, then moves the pointer back one.
                read_seq = seq
                target_seq = seq - 1
            else:
                max_seq = conn.execute(
                    "SELECT MAX(seq) FROM project_history WHERE project_id = ?",
                    (str(project_id),),
                ).fetchone()[0]
                if max_seq is None or seq + 1 > max_seq:
                    raise no_entry_error()
                # Redo restores the *after* state of the next entry.
                read_seq = seq + 1
                target_seq = seq + 1
            entry = conn.execute(
                f"SELECT {json_key} FROM project_history WHERE project_id = ? AND seq = ?",
                (str(project_id), read_seq),
            ).fetchone()
            assert entry is not None
            snapshot = json.loads(entry[json_key])
            # Undo/redo never moves the playhead (§17.4.10): keep the
            # current last position, restore everything else.
            current_ws = WorkingState.model_validate_json(row["working_state"])
            new_markers = _markers_from_snapshot(snapshot, project_id)
            ws_data = dict(snapshot["working_state"])
            ws_data["last_position_frames"] = current_ws.last_position_frames
            new_ws = WorkingState.model_validate(ws_data)
            # Pre-M2.7 snapshots have no practice_state key: keep the
            # current practice state (it was not undoable before).
            ps_data = snapshot.get("practice_state")
            if ps_data is None:
                new_ps = PracticeState.model_validate_json(row["practice_state"])
            else:
                new_ps = PracticeState.model_validate(ps_data)
            _write_state(
                conn,
                str(project_id),
                new_markers,
                new_ws,
                new_ps,
                row["revision"] + 1,
                target_seq,
                _now(),
            )
            conn.execute("COMMIT")
        except (ProjectMissingError, StaleRevisionError, NothingToUndoError, NothingToRedoError):
            conn.execute("ROLLBACK")
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        project = self.get_project(project_id)
        assert project is not None
        # After an undo the undone entry still exists (redoable); after a
        # redo only entries beyond the pointer are redoable.
        can_redo = True if direction < 0 else max_seq is not None and target_seq + 1 <= max_seq
        return CommandResult(
            revision=project.revision,
            markers=project.markers,
            working_state=project.working_state,
            practice_state=project.practice_state,
            can_undo=target_seq >= 0,
            can_redo=can_redo,
        )

    def undo(self, project_id: uuid.UUID, base_revision: int) -> CommandResult:
        """Undo the newest history entry (M1.15, spec §17.4.3)."""
        return self._move_history(project_id, base_revision, -1)

    def redo(self, project_id: uuid.UUID, base_revision: int) -> CommandResult:
        """Redo the newest undone history entry (M1.15, spec §17.4.3)."""
        return self._move_history(project_id, base_revision, 1)

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

    def list_project_assets(
        self, project_id: uuid.UUID
    ) -> list[tuple[AssetRecord, AssetRole]]:
        """Every asset linked to a project, with its project-level role.

        The same asset row can carry several links (e.g. one asset used as
        a stem by two result sets); each link is returned.
        """
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT a.*, pa.role AS link_role
                FROM project_assets pa JOIN assets a ON a.id = pa.asset_id
                WHERE pa.project_id = ?
                ORDER BY a.id, pa.role
                """,
                (str(project_id),),
            ).fetchall()
            return [(_row_to_asset(row), AssetRole(row["link_role"])) for row in rows]
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

    def set_practice_state(
        self, project_id: uuid.UUID, practice_state: PracticeState
    ) -> ProjectRecord:
        """Persist the project's mixer/practice state (M2.1, spec §3.5).

        Writes the serialized state and bumps the revision. Command/undo
        integration for practice state arrives with the M2.17 command set;
        this setter is the direct persistence path used in the meantime.
        """
        conn = _open(self._db_path)
        try:
            cur = conn.execute(
                """
                UPDATE projects SET
                    practice_state = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ?
                """,
                (practice_state.model_dump_json(), _now(), str(project_id)),
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

    def in_flight_export_asset_ids(self) -> set[uuid.UUID]:
        """Stem assets referenced by non-terminal export jobs (M2.13 §9.5.6).

        The §9.5 pin hook: callers pass the result as ``pinned_asset_ids``
        so explicit reclaim never deletes bytes an export is still reading.
        Interrupted jobs stay pinned because they can resume. Requested
        asset ids live in the job's stored ``parameters`` (written when
        the export job is created).
        """
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT parameters FROM media_jobs
                WHERE job_type = 'export'
                  AND state IN ('queued', 'running', 'cancelling', 'interrupted')
                """
            ).fetchall()
        finally:
            conn.close()
        pinned: set[uuid.UUID] = set()
        for row in rows:
            try:
                parameters = json.loads(row["parameters"])
            except (TypeError, ValueError):
                continue
            asset_ids = parameters.get("asset_ids")
            if not isinstance(asset_ids, list):
                continue
            for value in asset_ids:
                try:
                    pinned.add(uuid.UUID(str(value)))
                except ValueError:
                    continue
        return pinned

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


class WaveformCacheRepository:
    """Synchronous repository for waveform cache rows (M1.8).

    One row per canonical asset pins the final on-disk cache to the asset.
    The on-disk manifest remains the source of truth for progressive tile
    availability; this row only records that a complete, validated cache
    exists. The worker never touches the database (M1.4 boundary).
    """

    def __init__(self, db_path: Path, cache_root: Path) -> None:
        self._db_path = db_path
        self._cache_root = cache_root

    @staticmethod
    def _relative_manifest_path(manifest_path: str, cache_root: Path) -> str:
        """Anchor an absolute manifest path under the cache category.

        Stored storage-relative (``cache/waveforms/<hash>/manifest.json``)
        so ``StoragePaths.resolve_asset_path`` can resolve it back for both
        the explicit-storage-root and default XDG layouts.
        """
        absolute = Path(manifest_path)
        if not absolute.is_absolute():
            raise DatabaseError(f"waveform manifest path is not absolute: {manifest_path}")
        try:
            relative = absolute.relative_to(cache_root)
        except ValueError as exc:
            raise DatabaseError(
                f"waveform manifest {manifest_path} is outside cache root {cache_root}"
            ) from exc
        return f"cache/{relative.as_posix()}"

    def register(self, asset_id: uuid.UUID, result: WaveformResult) -> WaveformCacheRecord:
        """Pin a completed waveform cache to its asset (idempotent).

        An existing row for the asset wins; a row pinning a different source
        hash is a corruption and is rejected.
        """
        manifest_path = self._relative_manifest_path(result.manifest_path, self._cache_root)
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO waveform_caches (id, asset_id, cache_version,
                                                       source_hash, sample_rate,
                                                       frame_count, channel_count,
                                                       levels_json, manifest_path,
                                                       created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    str(asset_id),
                    result.cache_version,
                    result.source_hash,
                    result.sample_rate,
                    result.frame_count,
                    result.channel_count,
                    json.dumps([level.model_dump() for level in result.levels], sort_keys=True),
                    manifest_path,
                    _now(),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot register waveform cache: {exc}") from exc
        finally:
            conn.close()

        record = self.get_for_asset(asset_id)
        assert record is not None
        if record.source_hash != result.source_hash:
            raise DatabaseError(
                f"waveform cache for asset {asset_id} pins a different source hash"
            )
        return record

    def get_for_asset(self, asset_id: uuid.UUID) -> WaveformCacheRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM waveform_caches WHERE asset_id = ?", (str(asset_id),)
            ).fetchone()
            return _row_to_waveform_cache(row) if row else None
        finally:
            conn.close()

    def delete_for_asset(self, asset_id: uuid.UUID) -> None:
        """Remove the cache row (rebuild path for corrupt caches, spec §10.4)."""
        conn = _open(self._db_path)
        try:
            conn.execute("DELETE FROM waveform_caches WHERE asset_id = ?", (str(asset_id),))
            conn.execute("COMMIT")
        finally:
            conn.close()


class SeparationRepository:
    """Synchronous repository for separation runs, result sets, and stems.

    Each record is stored as a JSON blob (``record_json``) plus scalar key
    columns for indexing. This keeps the schema stable as the records grow
    across M2.5–M2.7 and makes the round-trip a single ``model_validate_json``.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    # -- Runs ----------------------------------------------------------------
    def create_run(self, run: SeparationRun) -> SeparationRun:
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO separation_runs (id, project_id, status, requested_mode,
                                             result_set_id, cache_key, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id),
                    str(run.project_id),
                    run.status.value,
                    run.requested_mode.value,
                    str(run.result_set_id) if run.result_set_id else None,
                    run.cache_key,
                    run.model_dump_json(),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create separation run: {exc}") from exc
        finally:
            conn.close()
        return run

    def get_run(self, run_id: uuid.UUID) -> SeparationRun | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM separation_runs WHERE id = ?", (str(run_id),)
            ).fetchone()
            return SeparationRun.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def list_runs_for_project(self, project_id: uuid.UUID) -> list[SeparationRun]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_json FROM separation_runs WHERE project_id = ? ORDER BY id",
                (str(project_id),),
            ).fetchall()
            return [SeparationRun.model_validate_json(r["record_json"]) for r in rows]
        finally:
            conn.close()

    def latest_run_elapsed_seconds(self) -> float | None:
        """Wall-clock seconds of the most recent separation run (M2.12 §14.4).

        Prefers the recorded start/end timestamps; falls back to the run's
        ``wall_seconds`` metric. Returns ``None`` when no run exists or the
        duration was never recorded.
        """

        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM separation_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        run = SeparationRun.model_validate_json(row["record_json"])
        if run.started_at is not None and run.ended_at is not None:
            return max(0.0, (run.ended_at - run.started_at).total_seconds())
        if run.metrics is not None:
            value = run.metrics.get("wall_seconds")
            if value is not None:
                return float(value)
        return None

    def find_active_run(
        self, project_id: uuid.UUID, cache_key: str
    ) -> SeparationRun | None:
        """A queued/running run for (project, cache key), if any (M2.7 §9.2.8).

        Cancelled, failed, interrupted, and completed runs never match:
        only a live in-flight run supports coalescing an identical
        request.
        """
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                """
                SELECT record_json FROM separation_runs
                WHERE project_id = ? AND cache_key = ?
                  AND status IN ('queued', 'running')
                ORDER BY id LIMIT 1
                """,
                (str(project_id), cache_key),
            ).fetchone()
            return SeparationRun.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    # -- Result sets ---------------------------------------------------------
    def create_result_set(self, result_set: SeparationResultSet) -> SeparationResultSet:
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO separation_result_sets (id, run_id, project_id,
                                                    validation_status, created_at,
                                                    cache_key, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result_set.id),
                    str(result_set.run_id),
                    str(result_set.project_id),
                    result_set.validation_status.value,
                    result_set.created_at.isoformat().replace("+00:00", "Z"),
                    result_set.cache_key,
                    result_set.model_dump_json(),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create separation result set: {exc}") from exc
        finally:
            conn.close()
        return result_set

    def get_result_set(self, result_set_id: uuid.UUID) -> SeparationResultSet | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM separation_result_sets WHERE id = ?",
                (str(result_set_id),),
            ).fetchone()
            return SeparationResultSet.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def list_result_sets_for_project(self, project_id: uuid.UUID) -> list[SeparationResultSet]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_json FROM separation_result_sets WHERE project_id = ? "
                "ORDER BY created_at",
                (str(project_id),),
            ).fetchall()
            return [SeparationResultSet.model_validate_json(r["record_json"]) for r in rows]
        finally:
            conn.close()

    def find_valid_result_set(
        self, project_id: uuid.UUID, cache_key: str
    ) -> SeparationResultSet | None:
        """The newest ``valid`` result set for (project, cache key) (M2.7 §9.2.1).

        Pending and invalid sets never match; among valid sets the
        newest (by ``created_at``) wins — it is the entry a lookup
        returns for the key.
        """
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                """
                SELECT record_json FROM separation_result_sets
                WHERE project_id = ? AND cache_key = ? AND validation_status = 'valid'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (str(project_id), cache_key),
            ).fetchone()
            return SeparationResultSet.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def get_result_set_detail(
        self, project_id: uuid.UUID, result_set_id: uuid.UUID
    ) -> tuple[SeparationResultSet, SeparationRun, list[StemRecord]] | None:
        """A project-owned result set with its run and stems, if any (M2.8).

        One connection serves the set, its completing run, and all stems,
        so the detail route never observes a partial state. Returns
        ``None`` when the set is missing or belongs to another project.
        """
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM separation_result_sets "
                "WHERE id = ? AND project_id = ?",
                (str(result_set_id), str(project_id)),
            ).fetchone()
            if row is None:
                return None
            result_set = SeparationResultSet.model_validate_json(row["record_json"])
            run_row = conn.execute(
                "SELECT record_json FROM separation_runs WHERE id = ?",
                (str(result_set.run_id),),
            ).fetchone()
            if run_row is None:
                raise DatabaseError(
                    f"separation run {result_set.run_id} for result set "
                    f"{result_set_id} is missing"
                )
            run = SeparationRun.model_validate_json(run_row["record_json"])
            stem_rows = conn.execute(
                "SELECT record_json FROM stems WHERE result_set_id = ? ORDER BY id",
                (str(result_set_id),),
            ).fetchall()
            stems = [StemRecord.model_validate_json(r["record_json"]) for r in stem_rows]
            return result_set, run, stems
        finally:
            conn.close()

    # -- Stems ---------------------------------------------------------------
    def create_stem(self, stem: StemRecord) -> StemRecord:
        conn = _open(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO stems (id, result_set_id, role, record_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(stem.id),
                    str(stem.result_set_id),
                    stem.role.value,
                    stem.model_dump_json(),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot create stem: {exc}") from exc
        finally:
            conn.close()
        return stem

    def get_stem(self, stem_id: uuid.UUID) -> StemRecord | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM stems WHERE id = ?", (str(stem_id),)
            ).fetchone()
            return StemRecord.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def list_stems_for_result_set(self, result_set_id: uuid.UUID) -> list[StemRecord]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_json FROM stems WHERE result_set_id = ? ORDER BY id",
                (str(result_set_id),),
            ).fetchall()
            return [StemRecord.model_validate_json(r["record_json"]) for r in rows]
        finally:
            conn.close()

    # -- Publication (M2.6) --------------------------------------------------
    def publish_result_set(
        self,
        run: SeparationRun,
        result_set: SeparationResultSet,
        stems: list[StemRecord],
        assets: list[AssetRecord],
    ) -> SeparationResultSet:
        """Atomically publish a completed run (M2.6, spec §8.7).

        One transaction registers the published stem assets
        (hash-idempotent), attaches them to the project as ``stem``
        assets, inserts the stem records and the result set, and marks
        the run complete with its result-set reference. Any failure rolls
        back every row; the audio files were moved into the
        content-addressed store beforehand, so a retry reuses them.
        """
        if run.status != SeparationRunStatus.COMPLETED or run.result_set_id != result_set.id:
            raise DatabaseError(
                "the run record must be completed and reference the published result set"
            )
        if result_set.validation_status != ValidationStatus.VALID:
            raise DatabaseError("only a valid result set can be published")
        if result_set.run_id != run.id or result_set.project_id != run.project_id:
            raise DatabaseError("result set and run identity mismatch")
        if (
            run.cache_key is not None
            and result_set.cache_key is not None
            and run.cache_key != result_set.cache_key
        ):
            raise DatabaseError("run and result set cache keys must match")
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM separation_runs WHERE id = ?", (str(run.id),)
            ).fetchone()
            if row is None:
                raise DatabaseError(f"separation run {run.id} does not exist")
            if row["status"] == SeparationRunStatus.COMPLETED.value:
                raise DatabaseError(f"separation run {run.id} is already published")
            for asset in assets:
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
                    (str(run.project_id), str(asset.id), AssetRole.STEM.value),
                )
            conn.execute(
                """
                INSERT INTO separation_result_sets (id, run_id, project_id,
                                                    validation_status, created_at,
                                                    cache_key, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result_set.id),
                    str(result_set.run_id),
                    str(result_set.project_id),
                    result_set.validation_status.value,
                    result_set.created_at.isoformat().replace("+00:00", "Z"),
                    result_set.cache_key,
                    result_set.model_dump_json(),
                ),
            )
            for stem in stems:
                conn.execute(
                    """
                    INSERT INTO stems (id, result_set_id, role, record_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(stem.id),
                        str(stem.result_set_id),
                        stem.role.value,
                        stem.model_dump_json(),
                    ),
                )
            conn.execute(
                """
                UPDATE separation_runs
                SET status = ?, result_set_id = ?, cache_key = ?, record_json = ?
                WHERE id = ?
                """,
                (
                    run.status.value,
                    str(result_set.id),
                    run.cache_key,
                    run.model_dump_json(),
                    str(run.id),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot publish separation result set: {exc}") from exc
        finally:
            conn.close()
        return result_set


class ExportArtifactRepository:
    """Synchronous repository for delivered export artifacts (M2.13 §15.5).

    One row per delivered WAV file. The published file itself lives in the
    managed export store (``data/exports/<sha256>.wav``); rows record the
    report required by §15.5 (source result set, stem, settings, gain,
    dither, hash, path) and survive cache reclaim because a delivered copy
    is user data, not a rebuildable cache entry.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def publish_artifacts(
        self, job_id: uuid.UUID, artifacts: list[ExportArtifact]
    ) -> list[ExportArtifact]:
        """Register the artifacts of one completed export job atomically.

        Any previous rows for the job are replaced in the same
        transaction, so a republish after an interruption cannot duplicate
        a job's artifacts. The files themselves were moved into managed
        storage beforehand; a retry reuses them.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM export_artifacts WHERE job_id = ?", (str(job_id),))
            for artifact in artifacts:
                if artifact.job_id != job_id:
                    raise DatabaseError("export artifact job_id mismatch")
                conn.execute(
                    """
                    INSERT INTO export_artifacts (
                        id, job_id, project_id, result_set_id, stem_id,
                        audio_asset_id, sha256, relative_path, download_filename,
                        created_at, record_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(artifact.id),
                        str(artifact.job_id),
                        str(artifact.project_id),
                        str(artifact.result_set_id),
                        str(artifact.stem_id),
                        str(artifact.audio_asset_id),
                        artifact.sha256,
                        artifact.relative_path,
                        artifact.download_filename,
                        artifact.created_at.isoformat().replace("+00:00", "Z"),
                        artifact.model_dump_json(),
                    ),
                )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot publish export artifacts: {exc}") from exc
        finally:
            conn.close()
        return artifacts

    def get_artifact(self, artifact_id: uuid.UUID) -> ExportArtifact | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM export_artifacts WHERE id = ?",
                (str(artifact_id),),
            ).fetchone()
            return ExportArtifact.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def list_artifacts_for_project(self, project_id: uuid.UUID) -> list[ExportArtifact]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_json FROM export_artifacts WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (str(project_id),),
            ).fetchall()
            return [ExportArtifact.model_validate_json(r["record_json"]) for r in rows]
        finally:
            conn.close()

    def list_artifacts_with_job_state(
        self, project_id: uuid.UUID
    ) -> list[tuple[ExportArtifact, JobState]]:
        """Artifacts with their job's current state (listing route)."""
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT a.record_json AS record_json, j.state AS job_state
                FROM export_artifacts a
                JOIN media_jobs j ON j.id = a.job_id
                WHERE a.project_id = ?
                ORDER BY a.created_at DESC, a.id DESC
                """,
                (str(project_id),),
            ).fetchall()
            return [
                (
                    ExportArtifact.model_validate_json(r["record_json"]),
                    JobState(r["job_state"]),
                )
                for r in rows
            ]
        finally:
            conn.close()


class PortableArtifactRepository:
    """Synchronous repository for portable project artifacts (M2.15 §17.5).

    One row per successfully published ``.basseparate`` archive. The
    published file itself lives in the managed portable store
    (``data/portable/<project_id>/<revision>-<sha12>.basseparate``); rows
    record the report required by §17.5 (saved revision, hash, size,
    download name) and survive cache reclaim because a portable save is
    user data, not a rebuildable cache entry.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def publish(self, artifact: PortableArtifact) -> PortableArtifact:
        """Record one published artifact.

        The file was moved into managed storage beforehand; a retry of the
        same save publishes the same row id and is a no-op.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO portable_artifacts (
                    id, project_id, saved_revision, sha256, byte_size,
                    relative_path, download_filename, created_at, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(artifact.id),
                    str(artifact.project_id),
                    artifact.saved_revision,
                    artifact.sha256,
                    artifact.byte_size,
                    artifact.relative_path,
                    artifact.download_filename,
                    artifact.created_at.isoformat().replace("+00:00", "Z"),
                    artifact.model_dump_json(),
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"cannot publish portable artifact: {exc}") from exc
        finally:
            conn.close()
        return artifact

    def delete_older(self, project_id: uuid.UUID, keep_ids: set[uuid.UUID]) -> int:
        """Remove artifact rows for the project not in ``keep_ids``.

        Files are removed by the caller; missing files are tolerated.
        Returns the number of rows removed.
        """
        conn = _open(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ", ".join("?" for _ in keep_ids) or "NULL"
            cur = conn.execute(
                f"""
                DELETE FROM portable_artifacts
                WHERE project_id = ? AND id NOT IN ({placeholders})
                """,
                (str(project_id), *sorted(str(i) for i in keep_ids)),
            )
            conn.execute("COMMIT")
            removed = cur.rowcount
        finally:
            conn.close()
        return removed

    def get(self, artifact_id: uuid.UUID) -> PortableArtifact | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM portable_artifacts WHERE id = ?",
                (str(artifact_id),),
            ).fetchone()
            return PortableArtifact.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()

    def list_for_project(self, project_id: uuid.UUID) -> list[PortableArtifact]:
        conn = _open(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_json FROM portable_artifacts WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (str(project_id),),
            ).fetchall()
            return [PortableArtifact.model_validate_json(r["record_json"]) for r in rows]
        finally:
            conn.close()

    def latest_for_project(self, project_id: uuid.UUID) -> PortableArtifact | None:
        conn = _open(self._db_path)
        try:
            row = conn.execute(
                "SELECT record_json FROM portable_artifacts WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (str(project_id),),
            ).fetchone()
            return PortableArtifact.model_validate_json(row["record_json"]) if row else None
        finally:
            conn.close()
