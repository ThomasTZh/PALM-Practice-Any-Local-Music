"""Migration 12→13 preserves Milestone 0–2 projects (M3.1, §3.11).

Builds a genuine v12 database, inserts an empty, imported, separated,
looped, and portable-opened project, migrates to the current schema, and
verifies that every project keeps its source timing, practice state, and
portable provenance while gaining defaulted rhythm state.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from basseparate import DATABASE_SCHEMA_VERSION, PROJECT_SCHEMA_VERSION
from basseparate.domain import (
    PlaybackMode,
    PracticeLoop,
    PracticeState,
    ProjectRecord,
    SeparationResultSet,
    SourceIdentity,
    ValidationStatus,
)
from basseparate.domain.rhythm import ProjectRhythmState
from basseparate.domain.separation import ReferenceMixIdentity
from basseparate.storage.db import _apply_migrations, initialize_database
from basseparate.storage.repository import ProjectRepository

NOW = "2026-10-22T17:00:00Z"
HASH = "ab" * 32


def _project_row(
    *,
    name: str,
    status: str,
    source: bool,
    practice_state: PracticeState,
    portable_provenance: str | None = None,
) -> tuple[str, tuple[object, ...]]:
    ident = str(uuid.uuid4())
    columns = (
        "id",
        "name",
        "created_at",
        "updated_at",
        "revision",
        "status",
        "schema_version",
        "working_state",
        "history_seq",
        "practice_state",
        "portable_provenance",
    )
    values: list[object] = [
        ident,
        name,
        NOW,
        NOW,
        7,
        status,
        4,
        "{}",
        -1,
        practice_state.model_dump_json(),
        portable_provenance,
    ]
    if source:
        columns += (
            "source_asset_id",
            "canonical_asset_id",
            "source_stream_index",
            "sample_rate",
            "duration_frames",
            "source_channel_count",
            "source_channel_layout",
            "decode_profile_version",
            "source_metadata",
        )
        values += [
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            0,
            48_000,
            1_411_200,
            2,
            "stereo",
            1,
            "{}",
        ]
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO projects ({', '.join(columns)}) VALUES ({placeholders})", tuple(values)


def _result_set(project_id: str) -> SeparationResultSet:
    return SeparationResultSet(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        project_id=uuid.UUID(project_id),
        source=SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash=HASH,
            sample_rate=48_000,
            duration_frames=1_411_200,
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=1_411_200,
        available_stem_roles=["bass", "other"],
        stem_ids=[uuid.uuid4(), uuid.uuid4()],
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash=HASH, transformation_hash=HASH
        ),
        validation_status=ValidationStatus.VALID,
        created_at=NOW,
    )


def test_migration_preserves_m2_projects(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA user_version = 0")
        _apply_migrations(conn, 0, 12)

        loop = PracticeLoop(
            id=uuid.uuid4(),
            name="Chorus",
            start_frames=48_000,
            end_frames=96_000,
            created_at=NOW,
            updated_at=NOW,
        )
        fixtures = {
            "empty": _project_row(
                name="Empty",
                status="empty",
                source=False,
                practice_state=PracticeState(),
            ),
            "imported": _project_row(
                name="Imported",
                status="ready",
                source=True,
                practice_state=PracticeState(
                    playback_mode=PlaybackMode.ORIGINAL, playback_speed=0.75
                ),
            ),
            "looped": _project_row(
                name="Looped",
                status="ready",
                source=True,
                practice_state=PracticeState(
                    playback_mode=PlaybackMode.ORIGINAL,
                    loops=[loop],
                    active_loop_id=loop.id,
                    loop_enabled=True,
                ),
            ),
            "portable": _project_row(
                name="Portable",
                status="ready",
                source=True,
                practice_state=PracticeState(),
                portable_provenance='{"archived_project_id": "abc", "saved_revision": 1}',
            ),
        }
        ids: dict[str, str] = {}
        for key, (sql, params) in fixtures.items():
            conn.execute(sql, params)
            ids[key] = str(params[0])

        # A separated project carries a result set row from M2.
        result_set = _result_set(ids["imported"])
        conn.execute(
            """
            INSERT INTO separation_result_sets
                (id, run_id, project_id, validation_status, created_at,
                 record_json, cache_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(result_set.id),
                str(result_set.run_id),
                str(result_set.project_id),
                result_set.validation_status.value,
                result_set.created_at.isoformat().replace("+00:00", "Z"),
                result_set.model_dump_json(),
                HASH,
            ),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    initialize_database(path)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "rhythm_analysis_runs",
            "rhythm_activation_artifacts",
            "rhythm_branches",
            "rhythm_results",
        } <= tables

        for key, project_id in ids.items():
            row = conn.execute(
                "SELECT name, revision, status, source_asset_id, canonical_asset_id, "
                "sample_rate, duration_frames, practice_state, portable_provenance, "
                "rhythm_state, schema_version FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            assert row is not None
            assert row["revision"] == 7, key
            assert row["rhythm_state"] == "{}", key
            assert row["schema_version"] == 4, key
            if key == "empty":
                assert row["status"] == "empty"
                assert row["source_asset_id"] is None
            else:
                assert row["status"] == "ready"
                assert row["sample_rate"] == 48_000
                assert row["duration_frames"] == 1_411_200
            if key == "portable":
                assert row["portable_provenance"] is not None

        assert (
            conn.execute(
                "SELECT COUNT(*) FROM separation_result_sets WHERE project_id = ?",
                (ids["imported"],),
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()

    projects = ProjectRepository(path)
    for project_id in ids.values():
        project = projects.get_project(uuid.UUID(project_id))
        assert project is not None
        assert project.rhythm_state == ProjectRhythmState()
        assert project.schema_version == 4
        assert project.duration_frames == (None if project.status.value == "empty" else 1_411_200)

    looped = projects.get_project(uuid.UUID(ids["looped"]))
    assert looped is not None
    assert len(looped.practice_state.loops) == 1
    assert looped.practice_state.loops[0].name == "Chorus"
    assert looped.practice_state.loop_enabled is True

    imported = projects.get_project(uuid.UUID(ids["imported"]))
    assert imported is not None
    assert imported.practice_state.playback_speed == 0.75
    # Reading an old project through the current record type fills the
    # new schema fields but never rewrites the stored row by itself.
    assert imported.rhythm_state.metronome.enabled is False


def test_new_projects_carry_current_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    project = ProjectRepository(path).create_project("New")
    assert isinstance(project, ProjectRecord)
    assert project.schema_version == PROJECT_SCHEMA_VERSION
    assert project.rhythm_state == ProjectRhythmState()


def test_migration_13_to_14_preserves_rhythm_rows(tmp_path: Path) -> None:
    """A v13 database keeps its rhythm run/artifact/branch rows."""
    path = tmp_path / "data" / "basseparate.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    artifact_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA user_version = 0")
        _apply_migrations(conn, 0, 13)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (project_id, "Rhythm v13", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO rhythm_analysis_runs "
            "(id, project_id, status, created_at, updated_at, record_json) "
            "VALUES (?, ?, 'completed', ?, ?, '{}')",
            (run_id, project_id, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO rhythm_activation_artifacts "
            "(id, project_id, run_id, content_hash, created_at, record_json) "
            "VALUES (?, ?, ?, ?, ?, '{}')",
            (artifact_id, project_id, run_id, HASH, NOW),
        )
        conn.execute(
            "INSERT INTO rhythm_branches "
            "(id, project_id, parent_automatic_result_id, revision, created_at, "
            "updated_at, record_json) VALUES (?, ?, NULL, 2, ?, ?, '{}')",
            (branch_id, project_id, NOW, NOW),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    initialize_database(path)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "rhythm_results" in tables
        assert conn.execute("SELECT COUNT(*) FROM rhythm_analysis_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rhythm_activation_artifacts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rhythm_branches").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rhythm_results").fetchone()[0] == 0
    finally:
        conn.close()
