"""API route tests for the M1.9 media interfaces (milestone1.md §11.3).

Covers the new routes through the real app (TestClient):
- GET  /api/v1/assets/{id}/metadata
- GET  /api/v1/assets/{id}/pcm?start_frame=&frame_count= (contract §11.4)
- GET  /api/v1/assets/{id}/peaks/manifest
- GET  /api/v1/assets/{id}/peaks?level=&tile=
- POST /api/v1/projects/{id}/playback-preparations

Ready projects and waveform caches are seeded directly through the
repositories and the real engine (no ffmpeg), keeping the focus on the
route logic.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.media_job import JobType
from basseparate.domain.representation import (
    AudioRepresentation,
    PlaybackRateResult,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_transform_key,
)
from basseparate.domain.waveform import WaveformResult
from basseparate.jobs import build_publishers
from basseparate.media.waveform import build_waveform_cache
from basseparate.storage import (
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
)

BASE_URL = "http://127.0.0.1:8765"

FRAME_COUNT = 4410
SAMPLE_RATE = 44100


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture()
def auth_headers(app) -> dict[str, str]:
    token = app.state.session_token
    return {"Authorization": f"Bearer {token}"}


def _projects(app) -> ProjectRepository:
    return app.state.repository


def _paths(app) -> StoragePaths:
    return app.state.storage_paths


def _seed_ready_project(
    app,
    *,
    channels: int = 2,
    layout: str = "stereo",
    sample_rate: int = SAMPLE_RATE,
    frames: int = FRAME_COUNT,
    pcm_bytes: bytes | None = None,
) -> tuple[str, AssetRecord]:
    """A ready project with a canonical PCM asset and its on-disk file."""
    projects = _projects(app)
    project = projects.create_project("asset routes")
    if pcm_bytes is None:
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
    asset_dir = _paths(app).data / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / f"{pcm_hash}.pcm").write_bytes(pcm_bytes)
    return str(project.id), pcm


def _seed_playback_representation(
    app, canonical: AssetRecord, target_rate: int = 48000
) -> AssetRecord:
    """A published playback representation at ``target_rate``."""
    projects = _projects(app)
    paths = _paths(app)
    audio = canonical.audio
    assert audio is not None
    frames = round(audio.frame_count * target_rate / audio.sample_rate)
    pcm_bytes = b"\x07\x00\x00\x00" * (frames * audio.channel_count)
    staged = paths.runtime / "jobs" / "seed" / "staging" / "playback.pcm"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(pcm_bytes)
    result = PlaybackRateResult(
        frame_count=frames,
        sample_rate=target_rate,
        channel_count=audio.channel_count,
        content_hash=_hash(pcm_bytes),
        max_amplitude=0.5,
        pcm_byte_count=len(pcm_bytes),
        source_frame_count=audio.frame_count,
        source_sample_rate=audio.sample_rate,
        target_sample_rate=target_rate,
        expected_frame_count=frames,
        endpoint_difference_frames=0,
        ffmpeg_version="ffmpeg 8.1.2",
        profile_version=1,
        staging_pcm_path=str(staged),
    )
    job = app.state.job_repository.create_job(
        _seeded_project_id(app, canonical),
        JobType.PLAYBACK_RATE,
    )
    build_publishers(
        app.state.import_repository,
        projects,
        cast_repr(app),
        paths,
        app.state.job_repository,
        app.state.waveform_cache_repository,
        app.state.export_repository,
    )(job, result.model_dump(mode="json"))
    rep = cast_repr(app).find_playback(canonical.id, target_rate)
    assert rep is not None
    asset = projects.get_asset(rep.asset_id)
    assert asset is not None
    return asset


def _seeded_project_id(app, canonical: AssetRecord) -> uuid.UUID:
    """Find the project whose canonical asset is ``canonical``."""
    projects = _projects(app)
    for project in projects.list_projects():
        if project.canonical_asset_id == canonical.id:
            return project.id
    raise AssertionError("no project references the canonical asset")


def cast_repr(app) -> RepresentationRepository:
    return app.state.representation_repository


def _build_waveform_cache(app, asset: AssetRecord) -> None:
    """Build a real on-disk waveform cache for the asset (engine, no worker)."""
    paths = _paths(app)
    audio = asset.audio
    assert audio is not None
    build_waveform_cache(
        paths.resolve_asset_path(asset.relative_path),
        paths.cache / "waveforms" / asset.content_hash,
        source_hash=asset.content_hash,
        sample_rate=audio.sample_rate,
        frame_count=audio.frame_count,
        channel_count=audio.channel_count,
    )


def _manifest_path(app, asset: AssetRecord) -> Path:
    return _paths(app).cache / "waveforms" / asset.content_hash / "manifest.json"


class TestAssetMetadata:
    def test_unknown_asset(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/assets/{uuid.uuid4()}/metadata", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ASSET_NOT_FOUND"

    def test_canonical_without_cache(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        resp = client.get(f"/api/v1/assets/{pcm.id}/metadata", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["asset_id"] == str(pcm.id)
        assert body["role"] == "source_pcm"
        assert body["content_hash"] == pcm.content_hash
        assert body["byte_count"] == pcm.byte_count
        assert body["sample_rate"] == SAMPLE_RATE
        assert body["frame_count"] == FRAME_COUNT
        assert body["channel_count"] == 2
        assert body["waveform"] is None

    def test_with_waveform_cache(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        resp = client.get(f"/api/v1/assets/{pcm.id}/metadata", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        waveform = resp.json()["waveform"]
        assert waveform is not None
        assert waveform["final"] is True
        assert waveform["source_hash"] == pcm.content_hash
        assert waveform["sample_rate"] == SAMPLE_RATE
        assert waveform["frame_count"] == FRAME_COUNT
        assert waveform["levels"][0]["bucket_frame_count"] == 64
        assert waveform["levels"][0]["bucket_count"] == 69  # ceil(4410 / 64)
        assert waveform["available_tiles"]["0"] == [[0, 0]]  # one tile at level 0

    def test_progressive_manifest_reflected(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        """While a WAVEFORM job runs, the on-disk manifest (not the DB row)
        answers with partial availability."""
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        path = _manifest_path(app, pcm)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["final"] = False
        data["available_tiles"] = {}
        path.write_text(json.dumps(data), encoding="utf-8")

        resp = client.get(f"/api/v1/assets/{pcm.id}/metadata", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        waveform = resp.json()["waveform"]
        assert waveform["final"] is False
        assert waveform["available_tiles"] == {}

    def test_db_row_fallback_without_manifest(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        """No on-disk manifest but a registered DB row: final geometry,
        no progressive availability."""
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        manifest = json.loads(_manifest_path(app, pcm).read_text(encoding="utf-8"))
        result = WaveformResult(
            cache_version=manifest["cache_version"],
            source_hash=manifest["source_hash"],
            sample_rate=manifest["sample_rate"],
            frame_count=manifest["frame_count"],
            channel_count=manifest["channel_count"],
            final_bucket_frames=64,
            levels=manifest["levels"],
            manifest_path=str(_manifest_path(app, pcm).resolve()),
        )
        app.state.waveform_cache_repository.register(pcm.id, result)
        _manifest_path(app, pcm).unlink()  # simulate a cache dir that vanished

        resp = client.get(f"/api/v1/assets/{pcm.id}/metadata", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        waveform = resp.json()["waveform"]
        assert waveform["final"] is True
        assert waveform["available_tiles"] == {}
        assert waveform["levels"][0]["bucket_count"] == 69


class TestAssetPcm:
    def test_unknown_asset(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            f"/api/v1/assets/{uuid.uuid4()}/pcm",
            params={"start_frame": 0, "frame_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ASSET_NOT_FOUND"

    def test_pcm_window_bytes_and_headers(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        pcm_bytes = bytes(range(256)) * (FRAME_COUNT * 2 // 256)
        _, pcm = _seed_ready_project(app, channels=2, pcm_bytes=pcm_bytes)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": 10, "frame_count": 20},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == pcm_bytes[10 * 8 : 30 * 8]
        assert resp.headers["content-length"] == str(20 * 8)
        assert resp.headers["x-asset-id"] == str(pcm.id)
        assert resp.headers["x-content-hash"] == pcm.content_hash
        assert resp.headers["x-sample-rate"] == str(SAMPLE_RATE)
        assert resp.headers["x-channel-count"] == "2"
        assert resp.headers["x-start-frame"] == "10"
        assert resp.headers["x-frame-count"] == "20"
        assert resp.headers["x-eof"] == "false"

    def test_clips_at_eof(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=1)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": FRAME_COUNT - 5, "frame_count": 1000},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.content) == 5 * 4
        assert resp.headers["x-frame-count"] == "5"
        assert resp.headers["x-eof"] == "true"

    def test_zero_frames_at_exact_end(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=1)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": FRAME_COUNT, "frame_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == b""
        assert resp.headers["content-length"] == "0"
        assert resp.headers["x-frame-count"] == "0"
        assert resp.headers["x-eof"] == "true"

    def test_start_beyond_end_rejected(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=1)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": FRAME_COUNT + 1, "frame_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PCM_RANGE_OUT_OF_BOUNDS"

    def test_negative_start_rejected(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=1)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": -1, "frame_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_zero_frame_count_rejected(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=1)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": 0, "frame_count": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_eight_mib_cap(self, client: TestClient, app, auth_headers: dict) -> None:
        """One response is bounded to 8 MiB of raw PCM (spec §11.4 rule 2)."""
        frames = 3_000_000
        _, pcm = _seed_ready_project(
            app, channels=1, frames=frames, pcm_bytes=b"\x00\x00\x00\x01" * frames
        )
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/pcm",
            params={"start_frame": 0, "frame_count": 5_000_000},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        max_frames = (8 * 1024 * 1024) // 4  # 2 097 152 mono frames
        assert len(resp.content) == 8 * 1024 * 1024
        assert resp.headers["x-frame-count"] == str(max_frames)
        assert resp.headers["x-eof"] == "false"

    def test_non_pcm_asset_rejected(self, client: TestClient, app, auth_headers: dict) -> None:
        """Source originals are encoded containers, not raw PCM."""
        _, pcm = _seed_ready_project(app, channels=1)
        original = _projects(app).get_asset_by_hash("ab" * 32)
        assert original is not None
        resp = client.get(
            f"/api/v1/assets/{original.id}/pcm",
            params={"start_frame": 0, "frame_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "NOT_PCM_ASSET"


class TestPeaks:
    def test_manifest_unknown_asset(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/assets/{uuid.uuid4()}/peaks/manifest", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ASSET_NOT_FOUND"

    def test_manifest_without_cache(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        resp = client.get(f"/api/v1/assets/{pcm.id}/peaks/manifest", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NO_WAVEFORM_CACHE"

    def test_manifest_final(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        resp = client.get(f"/api/v1/assets/{pcm.id}/peaks/manifest", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_hash"] == pcm.content_hash
        assert body["final"] is True
        assert body["levels"][0]["bucket_count"] == 69
        assert body["available_tiles"]["0"] == [[0, 0]]

    def test_tile_bytes_and_headers(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/peaks",
            params={"level": 0, "tile": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        expected = (
            _paths(app).cache / "waveforms" / pcm.content_hash / "level_0" / "tile_000000.bin"
        )
        assert resp.content == expected.read_bytes()
        # 69 buckets (the level's only, final, partial tile) x 2 channels x 8 bytes.
        assert len(resp.content) == 69 * 2 * 8
        assert resp.headers["x-level"] == "0"
        assert resp.headers["x-tile"] == "0"
        assert resp.headers["x-bucket-frames"] == "64"
        assert resp.headers["x-tile-buckets"] == "69"

    def test_tile_level_out_of_range(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/peaks",
            params={"level": 5, "tile": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PEAK_RANGE_OUT_OF_BOUNDS"

    def test_tile_index_out_of_range(self, client: TestClient, app, auth_headers: dict) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        resp = client.get(
            f"/api/v1/assets/{pcm.id}/peaks",
            params={"level": 0, "tile": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PEAK_RANGE_OUT_OF_BOUNDS"

    def test_tile_not_ready_progressive(self, client: TestClient, app, auth_headers: dict) -> None:
        """A manifest mid-build lists no tiles: 404 TILE_NOT_READY, not 500."""
        _, pcm = _seed_ready_project(app, channels=2)
        _build_waveform_cache(app, pcm)
        path = _manifest_path(app, pcm)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["final"] = False
        data["available_tiles"] = {}
        path.write_text(json.dumps(data), encoding="utf-8")

        resp = client.get(
            f"/api/v1/assets/{pcm.id}/peaks",
            params={"level": 0, "tile": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TILE_NOT_READY"


class TestPlaybackPreparations:
    def test_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/playback-preparations",
            json={"target_sample_rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_not_ready_project(self, client: TestClient, app, auth_headers: dict) -> None:
        project = _projects(app).create_project("empty")
        resp = client.post(
            f"/api/v1/projects/{project.id}/playback-preparations",
            json={"target_sample_rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_invalid_rate_rejected(self, client: TestClient, app, auth_headers: dict) -> None:
        project_id, _ = _seed_ready_project(app, channels=2)
        resp = client.post(
            f"/api/v1/projects/{project_id}/playback-preparations",
            json={"target_sample_rate": 1000},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_same_rate_ready(self, client: TestClient, app, auth_headers: dict) -> None:
        project_id, pcm = _seed_ready_project(app, channels=2)
        resp = client.post(
            f"/api/v1/projects/{project_id}/playback-preparations",
            json={"target_sample_rate": SAMPLE_RATE},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ready"
        assert body["asset_id"] == str(pcm.id)
        assert body["sample_rate"] == SAMPLE_RATE
        assert body["frame_count"] == FRAME_COUNT
        assert body["channel_count"] == 2
        assert body["job_id"] is None

    def test_existing_representation_ready(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        _, pcm = _seed_ready_project(app, channels=2)
        rep_asset = _seed_playback_representation(app, pcm, target_rate=48000)
        project_id = _seeded_project_id(app, pcm)
        resp = client.post(
            f"/api/v1/projects/{project_id}/playback-preparations",
            json={"target_sample_rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ready"
        assert body["asset_id"] == str(rep_asset.id)
        assert body["sample_rate"] == 48000
        assert body["job_id"] is None

    def test_no_representation_creates_job(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        project_id, _ = _seed_ready_project(app, channels=2)
        resp = client.post(
            f"/api/v1/projects/{project_id}/playback-preparations",
            json={"target_sample_rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "preparing"
        assert body["job_id"] is not None
        assert body["asset_id"] is None

        # The job is real and listed on the project.
        resp = client.get(f"/api/v1/projects/{project_id}/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        playback_jobs = [j for j in jobs if j["job_type"] == "playback_rate"]
        assert len(playback_jobs) == 1
        assert playback_jobs[0]["id"] == body["job_id"]
        assert playback_jobs[0]["parameters"] == {"target_sample_rate": 48000}

    def test_live_job_is_shared_not_duplicated(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        """A queued playback job for the same rate is reused (spec §6.5.6)."""
        project_id, _ = _seed_ready_project(app, channels=2)
        existing = app.state.job_repository.create_job(
            uuid.UUID(project_id),
            JobType.PLAYBACK_RATE,
            parameters={"target_sample_rate": 48000},
        )

        resp = client.post(
            f"/api/v1/projects/{project_id}/playback-preparations",
            json={"target_sample_rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "preparing"
        assert body["job_id"] == str(existing.id)

        resp = client.get(f"/api/v1/projects/{project_id}/jobs", headers=auth_headers)
        playback_jobs = [
            j for j in resp.json()["jobs"] if j["job_type"] == "playback_rate"
        ]
        assert len(playback_jobs) == 1
