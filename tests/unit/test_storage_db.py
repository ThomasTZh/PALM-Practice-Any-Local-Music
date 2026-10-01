"""Unit tests for SQLite storage foundation (M0.5)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.project import ProjectStatus
from basseparate.storage.db import (
    DatabaseError,
    UnsupportedSchemaVersion,
    initialize_database,
)
from basseparate.storage.repository import ProjectRepository

NOW = datetime(2025, 1, 1, tzinfo=UTC)
FAKE_HASH = "b" * 64


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def repo(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


class TestInitialization:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "c" / "test.db"
        initialize_database(path)
        assert path.exists()

    def test_idempotent(self, db_path: Path) -> None:
        initialize_database(db_path)
        initialize_database(db_path)

    def test_rejects_newer_schema(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 999")
        conn.close()
        with pytest.raises(UnsupportedSchemaVersion, match="newer than supported"):
            initialize_database(db_path)

    def test_wal_mode_enabled(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_tables_created(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert {"projects", "assets", "project_assets", "imports", "representations"} <= tables

    def test_schema_version_is_2(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 2

    def test_projects_table_has_m1_columns(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        conn.close()
        assert {
            "duration_frames",
            "canonical_asset_id",
            "source_stream_index",
            "source_channel_count",
            "source_channel_layout",
            "decode_profile_version",
            "waveform_status",
            "monitoring_asset_id",
            "source_metadata",
        } <= columns
        assert "duration_samples" not in columns

    def test_assets_table_frame_count_column(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(assets)")}
        conn.close()
        assert "audio_frame_count" in columns
        assert "audio_sample_count" not in columns


class TestProjectRepository:
    def test_create_and_get(self, repo: ProjectRepository) -> None:
        p = repo.create_project("My Test Project")
        assert p.name == "My Test Project"
        assert p.status == ProjectStatus.EMPTY
        assert p.revision == 0

        fetched = repo.get_project(p.id)
        assert fetched is not None
        assert fetched == p

    def test_get_nonexistent_returns_none(self, repo: ProjectRepository) -> None:
        assert repo.get_project(uuid.uuid4()) is None

    def test_list_projects(self, repo: ProjectRepository) -> None:
        repo.create_project("First")
        repo.create_project("Second")
        projects = repo.list_projects()
        assert len(projects) == 2
        assert {p.name for p in projects} == {"First", "Second"}

    def test_list_projects_empty(self, repo: ProjectRepository) -> None:
        assert repo.list_projects() == []

    def test_create_project_trims_name(self, repo: ProjectRepository) -> None:
        p = repo.create_project("  padded  ")
        assert p.name == "padded"

    def test_project_survives_reopen(self, repo: ProjectRepository) -> None:
        p = repo.create_project("Persistent")
        repo2 = ProjectRepository(repo._db_path)
        fetched = repo2.get_project(p.id)
        assert fetched is not None
        assert fetched.name == "Persistent"


class TestAssetRepository:
    def _make_asset(self, **kw: object) -> AssetRecord:
        base: dict[str, object] = {
            "id": uuid.uuid4(),
            "content_hash": FAKE_HASH,
            "role": AssetRole.SOURCE_PCM,
            "relative_path": "assets/test.wav",
            "media_type": "audio/wav",
            "byte_count": 2048,
            "created_at": NOW,
        }
        base.update(kw)
        return AssetRecord(**base)

    def test_register_asset(self, repo: ProjectRepository) -> None:
        asset = self._make_asset()
        repo.register_asset(asset)
        conn = sqlite3.connect(str(repo._db_path))
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (str(asset.id),)).fetchone()
        conn.close()
        assert row is not None

    def test_register_asset_with_audio_metadata(self, repo: ProjectRepository) -> None:
        audio = AudioMetadata(
            sample_rate=44100,
            channel_count=2,
            frame_count=88200,
            sample_format="s16le",
        )
        asset = self._make_asset(audio=audio)
        repo.register_asset(asset)
        conn = sqlite3.connect(str(repo._db_path))
        row = conn.execute(
            "SELECT audio_sample_rate, audio_channel_count FROM assets WHERE id = ?",
            (str(asset.id),),
        ).fetchone()
        conn.close()
        assert row[0] == 44100
        assert row[1] == 2

    def test_register_duplicate_hash_rejected(self, repo: ProjectRepository) -> None:
        asset = self._make_asset()
        repo.register_asset(asset)
        duplicate = self._make_asset(id=uuid.uuid4())
        with pytest.raises(DatabaseError, match="cannot register asset"):
            repo.register_asset(duplicate)

    def test_attach_asset(self, repo: ProjectRepository) -> None:
        project = repo.create_project("With Asset")
        asset = self._make_asset()
        repo.register_asset(asset)
        repo.attach_asset(project.id, asset.id, AssetRole.SOURCE_PCM)

        conn = sqlite3.connect(str(repo._db_path))
        row = conn.execute(
            "SELECT asset_id, role FROM project_assets WHERE project_id = ?",
            (str(project.id),),
        ).fetchone()
        conn.close()
        assert row[0] == str(asset.id)
        assert row[1] == "source_pcm"

    def test_attach_nonexistent_project_fails(self, repo: ProjectRepository) -> None:
        asset = self._make_asset()
        repo.register_asset(asset)
        with pytest.raises(DatabaseError, match="cannot attach asset"):
            repo.attach_asset(uuid.uuid4(), asset.id, AssetRole.SOURCE_PCM)
