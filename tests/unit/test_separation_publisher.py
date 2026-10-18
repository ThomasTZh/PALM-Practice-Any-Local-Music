"""Separation publisher wiring (M2.17, spec §8.7, §19.5).

The publisher re-derives the run, validates the analysis result payload,
and calls the M2.6 `publish_separation_result` with the stored
project-rate reference and geometry. The heavy publication pipeline is
covered by the M2.6 tests; here the call contract and failure guards are
pinned.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.media_job import JobStage, JobType
from basseparate.domain.separation import (
    DeviceType,
    SeparationJobResult,
    SeparationMode,
    SeparationRun,
    SeparationRunStatus,
)
from basseparate.jobs import publisher as publisher_module
from basseparate.jobs.publisher import PublishError, build_publishers
from basseparate.storage import (
    ExportArtifactRepository,
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    SeparationRepository,
    StoragePaths,
    WaveformCacheRepository,
)
from basseparate.storage.db import initialize_database

NOW = "2026-10-18T00:00:00Z"


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    projects = ProjectRepository(db)
    project = projects.create_project("Song")
    canonical_hash = "a" * 64
    canonical = AssetRecord(
        id=uuid.uuid4(),
        content_hash=canonical_hash,
        role=AssetRole.SOURCE_PCM,
        relative_path=f"data/assets/{canonical_hash}.pcm",
        media_type="application/octet-stream",
        byte_count=100 * 2 * 4,
        created_at=datetime.now(UTC),
        audio=AudioMetadata(
            sample_rate=48_000,
            channel_count=2,
            frame_count=100,
            sample_format="f32le",
        ),
    )
    projects.register_asset(canonical)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE projects SET status = 'ready', sample_rate = 48000, "
            "duration_frames = 100, source_channel_count = 2, "
            "source_channel_layout = 'stereo', source_stream_index = 0, "
            "decode_profile_version = 1, source_asset_id = ?, "
            "canonical_asset_id = ? WHERE id = ?",
            (str(canonical.id), str(canonical.id), str(project.id)),
        )
        conn.commit()
    finally:
        conn.close()
    project = projects.get_project(project.id)
    assert project is not None
    paths = StoragePaths(
        config=tmp_path / "config",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
        runtime=tmp_path / "runtime",
    )
    separations = SeparationRepository(db)
    jobs = JobRepository(db)
    asset_id = uuid.uuid4()
    run = separations.create_run(
        SeparationRun(
            id=uuid.uuid4(),
            project_id=project.id,
            input_asset_id=asset_id,
            input_transform_hash="c" * 64,
            requested_mode=SeparationMode.FOUR_STEMS,
            model_manifest_id=uuid.uuid4(),
            model_manifest_hash="d" * 64,
            engine_version="demucs-4.1.0",
            adapter_version="outer-window-v1",
            device_type=DeviceType.CPU,
            random_seed=0,
            status=SeparationRunStatus.QUEUED,
            cache_key="b" * 64,
        )
    )
    attempt = tmp_path / "attempt-1"
    attempt.mkdir()
    for label in ("bass", "drums", "other", "vocals"):
        (attempt / f"{label}.pcm").write_bytes(b"\x00" * 16)
    reference = tmp_path / "reference.pcm"
    reference.write_bytes(b"\x00" * 16)
    return {
        "db": db,
        "project": project,
        "paths": paths,
        "separations": separations,
        "jobs": jobs,
        "asset_id": asset_id,
        "canonical_id": canonical.id,
        "canonical_hash": canonical_hash,
        "run": run,
        "attempt": attempt,
        "reference": reference,
    }


def _job(env: dict):
    return env["jobs"].create_job(
        env["project"].id,
        JobType.SEPARATION,
        parameters={
            "run_id": str(env["run"].id),
            "requested_mode": "four_stems",
            "device": "cpu",
        },
    )


def _publisher(env: dict):
    return build_publishers(
        ImportRepository(env["db"]),
        ProjectRepository(env["db"]),
        RepresentationRepository(env["db"]),
        env["paths"],
        env["jobs"],
        WaveformCacheRepository(env["db"], env["paths"].cache),
        ExportArtifactRepository(env["db"]),
        separation_repository=env["separations"],
    )


def _result(env: dict) -> dict:
    return SeparationJobResult(
        status="complete",
        attempt_dir=str(env["attempt"]),
        record_path=str(env["attempt"] / "run-record.json"),
        stem_labels=["bass", "drums", "other", "vocals"],
        frames=100,
        device="cpu",
        elapsed_seconds=1.25,
        record={"status": "complete"},
    ).model_dump()


class TestSeparationPublisher:
    def test_calls_publication_with_run_geometry_and_reference(
        self, env: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: dict = {}

        async def fake_publish(**kwargs):
            calls.update(kwargs)

        monkeypatch.setattr(publisher_module, "publish_separation_result", fake_publish)
        job = _job(env)
        _publisher(env)(job, _result(env))

        assert calls["run"].id == env["run"].id
        assert calls["attempt_dir"] == env["attempt"]
        assert calls["stem_labels"] == ["bass", "drums", "other", "vocals"]
        assert calls["reference_path"] == env["paths"].resolve_asset_path(
            f"data/assets/{env['canonical_hash']}.pcm"
        )
        assert calls["source"].asset_id == env["canonical_id"]
        assert calls["source"].source_hash == env["canonical_hash"]
        assert calls["sample_rate"] == 48_000
        assert calls["duration_frames"] == 100
        assert calls["channel_count"] == 2
        assert calls["model_rate"] == 44_100
        assert calls["cache_key"] == "b" * 64
        assert calls["job_repository"] is env["jobs"]
        assert calls["asset_dir"] == env["paths"].data / "assets"
        expected_staging = env["paths"].runtime / "jobs" / job.id.hex / "staging"
        assert calls["staging_dir"] == expected_staging

        # Publication progress lands on the still-running job.
        calls["on_progress"](SimpleNamespace(fraction=0.25))
        refreshed = env["jobs"].get_job(job.id)
        assert refreshed is not None
        assert refreshed.stage is JobStage.VERIFYING_STEMS
        assert refreshed.progress_fraction == 0.25

    def test_missing_run_fails_publication(
        self, env: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_publish(**kwargs):  # pragma: no cover - must not run
            raise AssertionError("publication must not start")

        monkeypatch.setattr(publisher_module, "publish_separation_result", fake_publish)
        job = _job(env)
        job = job.model_copy(update={"parameters": {**job.parameters, "run_id": str(uuid.uuid4())}})
        with pytest.raises(PublishError, match="no longer exists"):
            _publisher(env)(job, _result(env))

    def test_missing_attempt_dir_fails_publication(
        self, env: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_publish(**kwargs):  # pragma: no cover - must not run
            raise AssertionError("publication must not start")

        monkeypatch.setattr(publisher_module, "publish_separation_result", fake_publish)
        job = _job(env)
        result = _result(env)
        result["attempt_dir"] = str(env["attempt"] / "missing")
        with pytest.raises(PublishError, match="attempt directory"):
            _publisher(env)(job, result)
