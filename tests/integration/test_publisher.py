"""Publisher tests for derived assets (M1.7).

Seeds ready projects directly through ``ProjectRepository.publish_source``
(no ffmpeg) and drives the real publisher with verified result dicts:
monitoring downmix (standard 5.1 and manual) and playback-rate conversion,
including the parent-asset chain and idempotency.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.media_job import JobType
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_transform_key,
)
from basseparate.jobs import PublishError, build_publishers
from basseparate.storage import (
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
)
from basseparate.storage.db import initialize_database

FRAME_COUNT = 4410
SAMPLE_RATE = 44100


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    db = tmp_path / "basseparate.db"
    initialize_database(db)
    paths = StoragePaths(
        config=tmp_path / "config",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
        runtime=tmp_path / "runtime",
    )
    return {
        "root": tmp_path,
        "db": db,
        "paths": paths,
        "projects": ProjectRepository(db),
        "imports": ImportRepository(db),
        "jobs": JobRepository(db),
        "representations": RepresentationRepository(db),
    }


def _seed_ready_project(
    env: dict,
    *,
    channels: int = 2,
    layout: str,
    sample_rate: int = SAMPLE_RATE,
    frames: int = FRAME_COUNT,
) -> tuple[uuid.UUID, AssetRecord]:
    """A ready project with a canonical PCM asset (and its on-disk file)."""
    projects = env["projects"]
    project = projects.create_project("publisher")
    pcm_bytes = b"\x00\x00\x00\x00" * (frames * channels)
    pcm_hash = _hash(pcm_bytes)
    original = AssetRecord(
        id=uuid.uuid4(),
        content_hash="ab" * 32,
        role=AssetRole.SOURCE_ORIGINAL,
        relative_path="runtime/uploads/seed.part",
        media_type="audio/wav",
        byte_count=100,
        created_at=datetime.now(UTC),
    )
    pcm = AssetRecord(
        id=uuid.uuid4(),
        content_hash=pcm_hash,
        role=AssetRole.SOURCE_PCM,
        relative_path=f"data/assets/{pcm_hash}.pcm",
        media_type="application/octet-stream",
        byte_count=len(pcm_bytes),
        created_at=datetime.now(UTC),
        audio=AudioMetadata(
            sample_rate=sample_rate,
            channel_count=channels,
            frame_count=frames,
            sample_format="f32le",
        ),
    )
    representation = AudioRepresentation(
        asset_id=pcm.id,
        parent_asset_id=original.id,
        role=RepresentationRole.CANONICAL,
        sample_rate=sample_rate,
        channel_count=channels,
        channel_layout=layout,
        frame_count=frames,
        content_hash=pcm_hash,
        transform_key=compute_transform_key("ab" * 32, 0, 1, "ffmpeg 8.1.2"),
        time_mapping=TimeMapping(project_rate=sample_rate, representation_rate=sample_rate),
        provenance=RepresentationProvenance(
            tool="ffmpeg",
            tool_version="ffmpeg 8.1.2",
            profile_version=1,
            created_at=datetime.now(UTC),
        ),
    )
    projects.publish_source(
        project_id=project.id,
        original_asset=original,
        pcm_asset=pcm,
        representation=representation,
        source_stream_index=0,
        sample_rate=sample_rate,
        duration_frames=frames,
        channel_count=channels,
        channel_layout=layout,
        decode_profile_version=1,
        source_metadata={"format": "wav"},
    )
    # The canonical PCM file on disk (what the worker would have produced).
    asset_dir = env["paths"].data / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / f"{pcm_hash}.pcm").write_bytes(pcm_bytes)
    return project.id, pcm


def _stage(env: dict, job_id: uuid.UUID, name: str, data: bytes) -> Path:
    staging = env["root"] / "jobs" / job_id.hex / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / name
    staged.write_bytes(data)
    return staged


def _downmix_result(staged: Path, *, mode: str, left: int, right: int, frames: int) -> dict:
    data = staged.read_bytes()
    return {
        "frame_count": frames,
        "sample_rate": SAMPLE_RATE,
        "channel_count": 2,
        "content_hash": _hash(data),
        "max_amplitude": 0.0,
        "pcm_byte_count": len(data),
        "source_frame_count": FRAME_COUNT,
        "downmix_mode": mode,
        "left_channel": left,
        "right_channel": right,
        "ffmpeg_version": "ffmpeg 8.1.2",
        "profile_version": 1,
        "staging_pcm_path": str(staged),
    }


def _downmix_result_dict(*, staging_path: str) -> dict:
    """A downmix result dict without a staged file (failure-path tests)."""
    return {
        "frame_count": FRAME_COUNT,
        "sample_rate": SAMPLE_RATE,
        "channel_count": 2,
        "content_hash": _hash(b"placeholder"),
        "max_amplitude": 0.0,
        "pcm_byte_count": len(b"placeholder"),
        "source_frame_count": FRAME_COUNT,
        "downmix_mode": "manual",
        "left_channel": 0,
        "right_channel": 1,
        "ffmpeg_version": "ffmpeg 8.1.2",
        "profile_version": 1,
        "staging_pcm_path": staging_path,
    }


def _playback_result(staged: Path, *, frames: int, source_frames: int) -> dict:
    data = staged.read_bytes()
    return {
        "frame_count": frames,
        "sample_rate": 48000,
        "channel_count": 2,
        "content_hash": _hash(data),
        "max_amplitude": 0.0,
        "pcm_byte_count": len(data),
        "source_frame_count": source_frames,
        "source_sample_rate": SAMPLE_RATE,
        "target_sample_rate": 48000,
        "expected_frame_count": frames,
        "endpoint_difference_frames": 0,
        "ffmpeg_version": "ffmpeg 8.1.2",
        "profile_version": 1,
        "staging_pcm_path": str(staged),
    }


def _playback_result_dict(*, staging_path: str) -> dict:
    """A playback result dict without a staged file (failure-path tests)."""
    return {
        "frame_count": 4800,
        "sample_rate": 48000,
        "channel_count": 2,
        "content_hash": _hash(b"placeholder"),
        "max_amplitude": 0.0,
        "pcm_byte_count": len(b"placeholder"),
        "source_frame_count": FRAME_COUNT,
        "source_sample_rate": SAMPLE_RATE,
        "target_sample_rate": 48000,
        "expected_frame_count": 4800,
        "endpoint_difference_frames": 0,
        "ffmpeg_version": "ffmpeg 8.1.2",
        "profile_version": 1,
        "staging_pcm_path": staging_path,
    }


def _publisher(env: dict):
    return build_publishers(
        env["imports"], env["projects"], env["representations"], env["paths"]
    )


class TestPublishDownmix:
    def test_standard_51_publishes_asset_representation_and_attach(self, env: dict) -> None:
        project_id, canonical = _seed_ready_project(env, channels=6, layout="5.1")
        job_id = uuid.uuid4()
        stereo = b"\x01\x00\x00\x00" * (FRAME_COUNT * 2)
        staged = _stage(env, job_id, "monitoring.pcm", stereo)

        job = env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX)
        result = _downmix_result(staged, mode="standard_5_1", left=0, right=1, frames=FRAME_COUNT)
        _publisher(env)(job, result)

        # The derived asset is content-addressed and the staging file is gone.
        asset = env["projects"].get_asset_by_hash(_hash(stereo))
        assert asset is not None
        assert asset.role is AssetRole.DERIVED_PCM
        assert asset.relative_path == f"data/assets/{_hash(stereo)}.pcm"
        on_disk = env["paths"].data / "assets" / f"{_hash(stereo)}.pcm"
        assert on_disk.is_file()
        assert on_disk.read_bytes() == stereo
        assert not staged.exists()

        # The representation chains from the canonical asset (identity time).
        rep = env["representations"].get_representation(asset.id)
        assert rep is not None
        assert rep.role is RepresentationRole.MONITORING_DOWNMIX
        assert rep.parent_asset_id == canonical.id
        assert rep.sample_rate == SAMPLE_RATE
        assert rep.channel_count == 2
        assert rep.channel_layout == "stereo"
        assert rep.frame_count == FRAME_COUNT
        assert rep.is_identity

        # The project is attached to its monitoring asset (FL/FR).
        project = env["projects"].get_project(project_id)
        assert project.monitoring_asset_id == asset.id
        assert project.monitoring_left_channel == 0
        assert project.monitoring_right_channel == 1

    def test_manual_publishes_with_user_selection(self, env: dict) -> None:
        project_id, _canonical = _seed_ready_project(env, channels=4, layout="quad")
        job_id = uuid.uuid4()
        stereo = b"\x02\x00\x00\x00" * (FRAME_COUNT * 2)
        staged = _stage(env, job_id, "monitoring.pcm", stereo)

        job = env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX)
        result = _downmix_result(staged, mode="manual", left=1, right=3, frames=FRAME_COUNT)
        _publisher(env)(job, result)

        project = env["projects"].get_project(project_id)
        assert project.monitoring_asset_id is not None
        assert project.monitoring_left_channel == 1
        assert project.monitoring_right_channel == 3

    def test_requires_canonical_asset(self, env: dict) -> None:
        projects = env["projects"]
        project = projects.create_project("empty")
        job = env["jobs"].create_job(project.id, JobType.MONITORING_DOWNMIX)
        result = _downmix_result_dict(staging_path="/nonexistent/monitoring.pcm")
        with pytest.raises(PublishError, match="no canonical asset"):
            _publisher(env)(job, result)

    def test_missing_staged_file_fails(self, env: dict) -> None:
        project_id, _canonical = _seed_ready_project(env, channels=6, layout="5.1")
        job = env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX)
        result = _downmix_result_dict(staging_path="/nonexistent/monitoring.pcm")
        with pytest.raises(PublishError, match="missing"):
            _publisher(env)(job, result)

    def test_publish_is_idempotent(self, env: dict) -> None:
        import sqlite3

        project_id, _canonical = _seed_ready_project(env, channels=6, layout="5.1")
        job_id = uuid.uuid4()
        stereo = b"\x03\x00\x00\x00" * (FRAME_COUNT * 2)
        staged = _stage(env, job_id, "monitoring.pcm", stereo)
        result = _downmix_result(staged, mode="standard_5_1", left=0, right=1, frames=FRAME_COUNT)

        publish = _publisher(env)
        publish(env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX), result)
        # Second run: the staging file is gone, the asset is deduplicated.
        publish(env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX), result)

        conn = sqlite3.connect(env["db"])
        try:
            asset_count = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE content_hash = ?", (_hash(stereo),)
            ).fetchone()[0]
            rep_count = conn.execute(
                "SELECT COUNT(*) FROM representations r JOIN assets a ON a.id = r.asset_id "
                "WHERE a.content_hash = ?",
                (_hash(stereo),),
            ).fetchone()[0]
        finally:
            conn.close()
        assert asset_count == 1
        assert rep_count == 1


class TestPublishPlayback:
    def test_publishes_asset_and_representation(self, env: dict) -> None:
        project_id, canonical = _seed_ready_project(env, channels=2, layout="stereo")
        job_id = uuid.uuid4()
        pcm = b"\x04\x00\x00\x00" * (4800 * 2)
        staged = _stage(env, job_id, "playback.pcm", pcm)

        job = env["jobs"].create_job(project_id, JobType.PLAYBACK_RATE)
        _publisher(env)(job, _playback_result(staged, frames=4800, source_frames=FRAME_COUNT))

        asset = env["projects"].get_asset_by_hash(_hash(pcm))
        assert asset is not None
        assert asset.role is AssetRole.DERIVED_PCM
        assert asset.audio is not None
        assert asset.audio.sample_rate == 48000
        assert asset.audio.frame_count == 4800
        on_disk = env["paths"].data / "assets" / f"{_hash(pcm)}.pcm"
        assert on_disk.read_bytes() == pcm
        assert not staged.exists()

        rep = env["representations"].get_representation(asset.id)
        assert rep is not None
        assert rep.role is RepresentationRole.PLAYBACK_RATE
        assert rep.parent_asset_id == canonical.id
        assert rep.sample_rate == 48000
        assert rep.frame_count == 4800
        assert rep.time_mapping.project_rate == SAMPLE_RATE
        assert rep.time_mapping.representation_rate == 48000
        assert not rep.is_identity

        # No project field is set by playback publishing.
        project = env["projects"].get_project(project_id)
        assert project.monitoring_asset_id is None

    def test_parent_is_monitoring_asset_when_present(self, env: dict) -> None:
        project_id, _canonical = _seed_ready_project(env, channels=6, layout="5.1")
        job_id = uuid.uuid4()
        stereo = b"\x05\x00\x00\x00" * (FRAME_COUNT * 2)
        staged = _stage(env, job_id, "monitoring.pcm", stereo)
        publish = _publisher(env)
        publish(
            env["jobs"].create_job(project_id, JobType.MONITORING_DOWNMIX),
            _downmix_result(staged, mode="standard_5_1", left=0, right=1, frames=FRAME_COUNT),
        )
        project = env["projects"].get_project(project_id)
        monitoring_id = project.monitoring_asset_id
        assert monitoring_id is not None

        # The playback representation derives from the monitoring asset.
        pcm = b"\x06\x00\x00\x00" * (4800 * 2)
        staged = _stage(env, uuid.uuid4(), "playback.pcm", pcm)
        job = env["jobs"].create_job(project_id, JobType.PLAYBACK_RATE)
        publish(job, _playback_result(staged, frames=4800, source_frames=FRAME_COUNT))

        rep = env["representations"].get_representation(
            env["projects"].get_asset_by_hash(_hash(pcm)).id  # type: ignore[union-attr]
        )
        assert rep is not None
        assert rep.parent_asset_id == monitoring_id

        # source-info style lookup: the playback is found under the monitoring parent.
        found = env["representations"].find_playback(monitoring_id, 48000)
        assert found is not None
        assert found.asset_id == rep.asset_id

    def test_requires_source_audio(self, env: dict) -> None:
        project = env["projects"].create_project("empty")
        job = env["jobs"].create_job(project.id, JobType.PLAYBACK_RATE)
        result = _playback_result_dict(staging_path="/nonexistent/playback.pcm")
        with pytest.raises(PublishError, match="no source audio asset"):
            _publisher(env)(job, result)

    def test_publish_is_idempotent(self, env: dict) -> None:
        import sqlite3

        project_id, _canonical = _seed_ready_project(env, channels=2, layout="stereo")
        job_id = uuid.uuid4()
        pcm = b"\x07\x00\x00\x00" * (4800 * 2)
        staged = _stage(env, job_id, "playback.pcm", pcm)
        result = _playback_result(staged, frames=4800, source_frames=FRAME_COUNT)

        publish = _publisher(env)
        publish(env["jobs"].create_job(project_id, JobType.PLAYBACK_RATE), result)
        publish(env["jobs"].create_job(project_id, JobType.PLAYBACK_RATE), result)

        conn = sqlite3.connect(env["db"])
        try:
            asset_count = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE content_hash = ?", (_hash(pcm),)
            ).fetchone()[0]
            rep_count = conn.execute(
                "SELECT COUNT(*) FROM representations r JOIN assets a ON a.id = r.asset_id "
                "WHERE a.content_hash = ?",
                (_hash(pcm),),
            ).fetchone()[0]
        finally:
            conn.close()
        assert asset_count == 1
        assert rep_count == 1
