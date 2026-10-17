"""Publisher tests for WAV stem exports (M2.13, spec §15.5).

Drives the real publisher with verified export result dicts: staged WAV
files are re-verified and moved into ``data/exports/<sha256>.wav``,
artifact rows record the whole report, republishing replaces the job's
rows instead of duplicating them, and tampered staged files are rejected
before anything is committed.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.export import (
    ExportFormat,
    ExportResult,
    ExportStemResult,
)
from basseparate.domain.media_job import JobType
from basseparate.domain.separation import StemRole
from basseparate.jobs import PublishError, build_publishers
from basseparate.storage import (
    ExportArtifactRepository,
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
    WaveformCacheRepository,
)
from basseparate.storage.db import initialize_database

SET_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    paths = StoragePaths(
        config=tmp_path / "config",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
        runtime=tmp_path / "runtime",
    )
    projects = ProjectRepository(db)
    jobs = JobRepository(db)
    exports = ExportArtifactRepository(db)
    project = projects.create_project("exporter")
    job = jobs.create_job(
        project.id,
        JobType.EXPORT,
        parameters={"result_set_id": str(SET_ID), "asset_ids": []},
    )
    publish = build_publishers(
        ImportRepository(db),
        projects,
        RepresentationRepository(db),
        paths,
        jobs,
        WaveformCacheRepository(db, paths.cache),
        exports,
    )
    return {
        "root": tmp_path,
        "db": db,
        "paths": paths,
        "projects": projects,
        "jobs": jobs,
        "exports": exports,
        "project": project,
        "job": job,
        "publish": publish,
    }


def _stage(env: dict, name: str, payload: bytes) -> Path:
    staging = env["root"] / "jobs" / env["job"].id.hex / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / name
    path.write_bytes(payload)
    return path


def _result(
    env: dict,
    *,
    staged: Path,
    payload: bytes,
    stem_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    role: StemRole = StemRole.BASS,
    download_filename: str = "Bass-444444-48k-24bit.wav",
    declared_size: int | None = None,
    declared_hash: str | None = None,
) -> dict:
    return ExportResult(
        result_set_id=SET_ID,
        joint_peak=1.0,
        artifacts=[
            ExportStemResult(
                stem_id=stem_id or env["stem_id"],
                audio_asset_id=asset_id or env["asset_id"],
                role=role,
                format=ExportFormat.WAV24,
                sample_rate=48000,
                channel_count=2,
                frame_count=1000,
                source_frame_count=1000,
                normalized=False,
                gain_db=None,
                dither="triangular",
                sha256=declared_hash or _sha256(payload),
                byte_size=declared_size if declared_size is not None else len(payload),
                download_filename=download_filename,
                staging_path=str(staged),
            )
        ],
    ).model_dump(mode="json")


@pytest.fixture()
def staged_env(env: dict) -> dict:
    payload = b"RIFF" + b"\x00" * 60 + b"wave-data"
    env["stem_id"] = uuid.uuid4()
    env["asset_id"] = uuid.uuid4()
    env["payload"] = payload
    env["staged"] = _stage(env, "Bass.wav", payload)
    return env


class TestPublishExport:
    def test_moves_file_and_records_artifact(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(env, staged=env["staged"], payload=env["payload"])
        env["publish"](env["job"], result)

        digest = _sha256(env["payload"])
        destination = env["paths"].data / "exports" / f"{digest}.wav"
        assert destination.is_file()
        assert destination.read_bytes() == env["payload"]
        assert not env["staged"].exists()

        artifacts = env["exports"].list_artifacts_for_project(env["project"].id)
        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert artifact.job_id == env["job"].id
        assert artifact.result_set_id == SET_ID
        assert artifact.stem_id == env["stem_id"]
        assert artifact.audio_asset_id == env["asset_id"]
        assert artifact.role is StemRole.BASS
        assert artifact.format is ExportFormat.WAV24
        assert artifact.sample_rate == 48000
        assert artifact.channel_count == 2
        assert artifact.frame_count == 1000
        assert artifact.normalized is False
        assert artifact.gain_db is None
        assert artifact.dither == "triangular"
        assert artifact.sha256 == digest
        assert artifact.byte_size == len(env["payload"])
        assert artifact.relative_path == f"data/exports/{digest}.wav"
        assert artifact.download_filename == "Bass-444444-48k-24bit.wav"
        assert artifact.created_at.tzinfo is not None

    def test_republish_replaces_rows_and_reuses_file(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(env, staged=env["staged"], payload=env["payload"])
        env["publish"](env["job"], result)

        again = _stage(env, "Bass.wav", env["payload"])
        env["publish"](env["job"], _result(env, staged=again, payload=env["payload"]))

        artifacts = env["exports"].list_artifacts_for_project(env["project"].id)
        assert len(artifacts) == 1
        assert not again.exists()
        exports_dir = env["paths"].data / "exports"
        assert len(list(exports_dir.glob("*.wav"))) == 1

    def test_size_mismatch_rejected_before_commit(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(
            env,
            staged=env["staged"],
            payload=env["payload"],
            declared_size=len(env["payload"]) + 1,
        )
        with pytest.raises(PublishError, match="size mismatch"):
            env["publish"](env["job"], result)
        assert env["exports"].list_artifacts_for_project(env["project"].id) == []
        assert env["staged"].is_file()  # not moved

    def test_hash_mismatch_rejected_before_commit(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(
            env,
            staged=env["staged"],
            payload=env["payload"],
            declared_hash="b" * 64,
        )
        with pytest.raises(PublishError, match="hash mismatch"):
            env["publish"](env["job"], result)
        assert env["exports"].list_artifacts_for_project(env["project"].id) == []

    def test_missing_staged_file_rejected(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(env, staged=env["staged"], payload=env["payload"])
        env["staged"].unlink()
        with pytest.raises(PublishError, match="missing"):
            env["publish"](env["job"], result)
        assert env["exports"].list_artifacts_for_project(env["project"].id) == []

    def test_listing_reports_job_state(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(env, staged=env["staged"], payload=env["payload"])
        env["publish"](env["job"], result)
        entries = env["exports"].list_artifacts_with_job_state(env["project"].id)
        assert len(entries) == 1
        artifact, state = entries[0]
        assert artifact.id is not None
        assert state.value == "queued"

    def test_artifact_created_at_is_utc(self, staged_env: dict) -> None:
        env = staged_env
        result = _result(env, staged=env["staged"], payload=env["payload"])
        env["publish"](env["job"], result)
        artifact = env["exports"].list_artifacts_for_project(env["project"].id)[0]
        assert artifact.created_at <= datetime.now(UTC)
