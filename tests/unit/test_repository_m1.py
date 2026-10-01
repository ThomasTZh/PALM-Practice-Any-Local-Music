"""Repository tests for imports and representations (M1.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole
from basseparate.domain.import_record import (
    AudioStreamInfo,
    ProbeResult,
    TransferState,
)
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    ImportRepository,
    ProjectRepository,
    RepresentationRepository,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)
FAKE_HASH = "f" * 64
OTHER_HASH = "1" * 64
PCM_HASH = "9" * 64


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def projects(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def imports(db_path: Path) -> ImportRepository:
    return ImportRepository(db_path)


@pytest.fixture()
def representations(db_path: Path) -> RepresentationRepository:
    return RepresentationRepository(db_path)


def _probe() -> ProbeResult:
    return ProbeResult(
        format_name="mp4",
        estimated_duration_seconds=120.0,
        byte_count=2_000_000,
        title="Concert",
        artist="Bassist",
        ffmpeg_version="8.1.2",
        ffprobe_version="8.1.2",
        audio_streams=(
            AudioStreamInfo(
                index=1,
                codec="aac",
                sample_rate=48_000,
                channel_count=2,
                channel_layout="stereo",
                language="eng",
                title="Main",
                is_default=True,
            ),
            AudioStreamInfo(
                index=2,
                codec="mp3",
                sample_rate=44_100,
                channel_count=2,
                channel_layout="stereo",
                language="fre",
                title="Commentary",
            ),
        ),
    )


class TestImportRepository:
    def test_create_and_get(self, projects: ProjectRepository, imports: ImportRepository) -> None:
        project = projects.create_project("Import Target")
        record = imports.create_import(project.id, "song (final) v2.mp4", 2_000_000)
        assert record.transfer_state == TransferState.CREATED
        assert record.received_byte_count == 0

        fetched = imports.get_import(record.id)
        assert fetched is not None
        assert fetched == record
        assert fetched.filename == "song (final) v2.mp4"

    def test_get_nonexistent_returns_none(self, imports: ImportRepository) -> None:
        assert imports.get_import(uuid.uuid4()) is None

    def test_list_imports_for_project(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        project_a = projects.create_project("A")
        project_b = projects.create_project("B")
        imports.create_import(project_a.id, "a1.wav", 100)
        imports.create_import(project_a.id, "a2.wav", 200)
        imports.create_import(project_b.id, "b1.wav", 300)

        list_a = imports.list_imports_for_project(project_a.id)
        assert {i.filename for i in list_a} == {"a1.wav", "a2.wav"}
        assert len(imports.list_imports_for_project(project_b.id)) == 1

    def test_update_transfer_state(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        project = projects.create_project("T")
        record = imports.create_import(project.id, "x.wav", 1_000)

        updated = imports.update_transfer_state(
            record.id, TransferState.UPLOADING, received_byte_count=512
        )
        assert updated.transfer_state == TransferState.UPLOADING
        assert updated.received_byte_count == 512

        completed = imports.update_transfer_state(
            record.id,
            TransferState.COMPLETE,
            received_byte_count=1_000,
            source_sha256=FAKE_HASH,
        )
        assert completed.transfer_state == TransferState.COMPLETE
        assert completed.source_sha256 == FAKE_HASH

    def test_update_nonexistent_raises(self, imports: ImportRepository) -> None:
        from basseparate.storage.db import DatabaseError

        with pytest.raises(DatabaseError, match="not found"):
            imports.update_transfer_state(uuid.uuid4(), TransferState.UPLOADING)

    def test_set_probe_result_roundtrip(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        project = projects.create_project("T")
        record = imports.create_import(project.id, "x.mp4", 2_000_000)
        updated = imports.set_probe_result(record.id, _probe())

        assert updated.probe_result is not None
        assert updated.probe_result.format_name == "mp4"
        assert len(updated.probe_result.audio_streams) == 2
        assert updated.probe_result.audio_streams[0].is_default is True
        assert updated.probe_result.audio_streams[1].language == "fre"

        refetched = imports.get_import(record.id)
        assert refetched is not None
        assert refetched.probe_result == updated.probe_result

    def test_set_selected_stream_and_job_ids(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        project = projects.create_project("T")
        record = imports.create_import(project.id, "x.mp4", 2_000_000)

        updated = imports.set_selected_stream(record.id, 2)
        assert updated.selected_stream_index == 2

        job_id = uuid.uuid4()
        with_job = imports.add_job_id(record.id, job_id)
        assert with_job.job_ids == (job_id,)

        job_id2 = uuid.uuid4()
        with_jobs = imports.add_job_id(record.id, job_id2)
        assert with_jobs.job_ids == (job_id, job_id2)

    def test_cancel_with_error(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        project = projects.create_project("T")
        record = imports.create_import(project.id, "x.wav", 1_000)
        cancelled = imports.update_transfer_state(
            record.id, TransferState.CANCELLED, error="user cancelled"
        )
        assert cancelled.transfer_state == TransferState.CANCELLED
        assert cancelled.error == "user cancelled"

    def test_import_cascades_with_project(
        self, projects: ProjectRepository, imports: ImportRepository
    ) -> None:
        import sqlite3

        project = projects.create_project("T")
        record = imports.create_import(project.id, "x.wav", 1_000)

        conn = sqlite3.connect(str(imports._db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM projects WHERE id = ?", (str(project.id),))
        conn.execute("COMMIT")
        conn.close()

        assert imports.get_import(record.id) is None


def _make_asset(asset_id: uuid.UUID, content_hash: str, role: object, path: str) -> AssetRecord:
    return AssetRecord(
        id=asset_id,
        content_hash=content_hash,
        role=role,  # type: ignore[arg-type]
        relative_path=path,
        media_type="audio/wav",
        byte_count=100,
        created_at=NOW,
    )


class TestRepresentationRepository:
    def _register_parent(self, projects: ProjectRepository, parent_id: uuid.UUID) -> None:
        projects.register_asset(
            _make_asset(parent_id, FAKE_HASH, AssetRole.SOURCE_ORIGINAL, "assets/original/p.wav")
        )

    def _asset_and_rep(self, parent_id: uuid.UUID, **rep_overrides: object) -> AudioRepresentation:
        base: dict[str, object] = {
            "asset_id": uuid.uuid4(),
            "parent_asset_id": parent_id,
            "role": RepresentationRole.CANONICAL,
            "sample_rate": 48_000,
            "channel_count": 2,
            "channel_layout": "stereo",
            "frame_count": 4_800_000,
            "content_hash": PCM_HASH,
            "transform_key": OTHER_HASH,
            "time_mapping": TimeMapping(project_rate=48_000, representation_rate=48_000),
            "provenance": RepresentationProvenance(
                tool="ffmpeg",
                tool_version="8.1.2",
                profile_version=1,
                created_at=NOW,
            ),
        }
        base.update(rep_overrides)
        return AudioRepresentation(**base)

    def test_register_and_get(
        self,
        projects: ProjectRepository,
        representations: RepresentationRepository,
    ) -> None:
        parent_id = uuid.uuid4()
        self._register_parent(projects, parent_id)

        rep = self._asset_and_rep(parent_id)
        projects.register_asset(
            _make_asset(rep.asset_id, rep.content_hash, AssetRole.SOURCE_PCM, "assets/pcm/abc.f32")
        )
        representations.register_representation(rep)

        fetched = representations.get_representation(rep.asset_id)
        assert fetched is not None
        assert fetched == rep
        assert fetched.content_hash == PCM_HASH

    def test_get_nonexistent_returns_none(self, representations: RepresentationRepository) -> None:
        assert representations.get_representation(uuid.uuid4()) is None

    def test_list_for_parent_asset(
        self,
        projects: ProjectRepository,
        representations: RepresentationRepository,
    ) -> None:
        parent = uuid.uuid4()
        self._register_parent(projects, parent)

        canonical = self._asset_and_rep(parent)
        playback = self._asset_and_rep(
            parent,
            role=RepresentationRole.PLAYBACK_RATE,
            sample_rate=44_100,
            frame_count=4_410_000,
            content_hash="2" * 64,
            transform_key="3" * 64,
            time_mapping=TimeMapping(project_rate=48_000, representation_rate=44_100),
        )
        for rep in (canonical, playback):
            projects.register_asset(
                _make_asset(
                    rep.asset_id,
                    rep.content_hash,
                    AssetRole.SOURCE_PCM,
                    f"assets/pcm/{rep.asset_id}.f32",
                )
            )
            representations.register_representation(rep)

        derived = representations.list_representations_for_asset(parent)
        assert {r.role for r in derived} == {
            RepresentationRole.CANONICAL,
            RepresentationRole.PLAYBACK_RATE,
        }

    def test_duplicate_asset_rejected(
        self,
        projects: ProjectRepository,
        representations: RepresentationRepository,
    ) -> None:
        from basseparate.storage.db import DatabaseError

        parent_id = uuid.uuid4()
        self._register_parent(projects, parent_id)

        rep = self._asset_and_rep(parent_id)
        projects.register_asset(
            _make_asset(rep.asset_id, rep.content_hash, AssetRole.SOURCE_PCM, "assets/pcm/dup.f32")
        )
        representations.register_representation(rep)

        with pytest.raises(DatabaseError, match="cannot register representation"):
            representations.register_representation(rep)
