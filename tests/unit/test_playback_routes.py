"""API route tests for monitoring channels and playback (M1.7).

Covers the four new routes end to end through the real app:
- PUT  /api/v1/projects/{id}/monitoring-channels
- GET  /api/v1/projects/{id}/source-info
- GET  /api/v1/projects/{id}/playback?rate=N
- GET  /api/v1/assets/{asset_id}/bytes (HTTP Range)
"""

from __future__ import annotations

import struct
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config

BASE_URL = "http://127.0.0.1:8765"


def _make_wav(channels: int = 1, sample_rate: int = 44100, frames: int = 4410) -> bytes:
    """A PCM16 WAV with the given channel count (no extensible layout tag)."""
    pcm = b"\x00\x00" * (frames * channels)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH", 16, 1, channels, sample_rate, sample_rate * channels * 2, channels * 2, 16
        )
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


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


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _complete_import(client: TestClient, headers: dict, project_id: str, data: bytes) -> str:
    resp = client.post(
        "/api/v1/imports",
        json={"project_id": project_id, "filename": "take.wav", "declared_byte_count": len(data)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    session = resp.json()
    import_id = session["import_id"]
    chunk_size = session["chunk_size"]
    for offset in range(0, len(data), chunk_size):
        chunk = data[offset : offset + chunk_size]
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": offset},
            content=chunk,
            headers={**headers, "X-Chunk-SHA256": _sha256(chunk)},
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=headers)
    assert resp.status_code == 200, resp.text
    return import_id


def _make_project(client: TestClient, headers: dict) -> str:
    resp = client.post("/api/v1/projects", json={"name": "Playback"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _wait_for_job(client: TestClient, headers: dict, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        job = resp.json()
        if job["state"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def _run_job(client: TestClient, headers: dict, project_id: str, import_id: str, job_type: str):
    resp = client.post(
        f"/api/v1/projects/{project_id}/jobs",
        json={"job_type": job_type, "import_id": import_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _ready_project(
    client: TestClient, headers: dict, channels: int = 1, sample_rate: int = 44100
) -> tuple[str, dict]:
    """A project with a decoded canonical asset (probe + decode)."""
    project_id = _make_project(client, headers)
    import_id = _complete_import(client, headers, project_id, _make_wav(channels, sample_rate))
    probe_job = _run_job(client, headers, project_id, import_id, "probe")
    probe = _wait_for_job(client, headers, probe_job)
    assert probe["state"] == "completed", probe
    decode_job = _run_job(client, headers, project_id, import_id, "canonical_decode")
    decode = _wait_for_job(client, headers, decode_job)
    assert decode["state"] == "completed", decode
    resp = client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    return project_id, resp.json()


class TestMonitoringChannels:
    def test_put_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.put(
            f"/api/v1/projects/{uuid.uuid4()}/monitoring-channels",
            json={"left": 0, "right": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_put_empty_project(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.put(
            f"/api/v1/projects/{project_id}/monitoring-channels",
            json={"left": 0, "right": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_put_out_of_range_channels(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=2)
        resp = client.put(
            f"/api/v1/projects/{project_id}/monitoring-channels",
            json={"left": 0, "right": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_MONITORING_SELECTION"

    def test_put_stores_selection(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=4)
        resp = client.put(
            f"/api/v1/projects/{project_id}/monitoring-channels",
            json={"left": 1, "right": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        project = resp.json()
        assert project["monitoring_left_channel"] == 1
        assert project["monitoring_right_channel"] == 3

        # The selection survives a re-read.
        resp = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
        assert resp.json()["monitoring_left_channel"] == 1
        assert resp.json()["monitoring_right_channel"] == 3


class TestSourceInfo:
    def test_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/source-info", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_empty_project(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.get(f"/api/v1/projects/{project_id}/source-info", headers=auth_headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_mono_source_info(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=1)
        resp = client.get(f"/api/v1/projects/{project_id}/source-info", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        info = resp.json()
        assert info["sample_rate"] == 44100
        assert info["duration_frames"] == 4410
        assert info["duration_seconds"] == pytest.approx(0.1)
        assert info["channel_count"] == 1
        assert info["channel_labels"] == ["Mono"]
        assert info["monitoring"] is None
        assert info["playback_rates"] == []

    def test_stereo_source_info(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=2)
        resp = client.get(f"/api/v1/projects/{project_id}/source-info", headers=auth_headers)
        assert resp.status_code == 200
        info = resp.json()
        assert info["channel_count"] == 2
        assert info["channel_labels"] == ["L", "R"]

    def test_multichannel_positional_labels(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=4)
        resp = client.get(f"/api/v1/projects/{project_id}/source-info", headers=auth_headers)
        assert resp.status_code == 200
        info = resp.json()
        assert info["channel_labels"] == ["Ch 0", "Ch 1", "Ch 2", "Ch 3"]


class TestPlaybackResolution:
    def test_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            f"/api/v1/projects/{uuid.uuid4()}/playback",
            params={"rate": 44100},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_empty_project(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.get(
            f"/api/v1/projects/{project_id}/playback",
            params={"rate": 44100},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    @pytest.mark.parametrize("rate", [7999, 192001])
    def test_rate_out_of_range(self, client: TestClient, auth_headers: dict, rate: int) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=1)
        resp = client.get(
            f"/api/v1/projects/{project_id}/playback",
            params={"rate": rate},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_source_rate_resolves_to_canonical(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id, project = _ready_project(client, auth_headers, channels=1)
        resp = client.get(
            f"/api/v1/projects/{project_id}/playback",
            params={"rate": 44100},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        playback = resp.json()
        assert playback["asset_id"] == project["canonical_asset_id"]
        assert playback["role"] == "canonical"
        assert playback["sample_rate"] == 44100
        assert playback["channel_count"] == 1
        assert playback["frame_count"] == 4410
        assert playback["byte_count"] == 4410 * 4
        assert playback["duration_seconds"] == pytest.approx(0.1)

    def test_missing_rate_is_404(self, client: TestClient, auth_headers: dict) -> None:
        project_id, _ = _ready_project(client, auth_headers, channels=1)
        resp = client.get(
            f"/api/v1/projects/{project_id}/playback",
            params={"rate": 48000},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NO_PLAYBACK_REPRESENTATION"


class TestAssetBytes:
    def _canonical(self, client: TestClient, headers: dict) -> tuple[str, str, bytes]:
        project_id, project = _ready_project(client, headers, channels=1)
        asset_id = project["canonical_asset_id"]
        return project_id, asset_id, b"\x00\x00\x00\x00" * 4410

    def test_unknown_asset(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            f"/api/v1/assets/{uuid.uuid4()}/bytes", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ASSET_NOT_FOUND"

    def test_full_body(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, expected = self._canonical(client, auth_headers)
        resp = client.get(f"/api/v1/assets/{asset_id}/bytes", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.headers["content-length"] == str(len(expected))
        assert resp.content == expected

    def test_partial_range(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, expected = self._canonical(client, auth_headers)
        resp = client.get(
            f"/api/v1/assets/{asset_id}/bytes",
            headers={**auth_headers, "Range": "bytes=10-19"},
        )
        assert resp.status_code == 206
        assert resp.headers["content-range"] == f"bytes 10-19/{len(expected)}"
        assert resp.headers["content-length"] == "10"
        assert resp.content == expected[10:20]

    def test_open_ended_range(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, expected = self._canonical(client, auth_headers)
        resp = client.get(
            f"/api/v1/assets/{asset_id}/bytes",
            headers={**auth_headers, "Range": "bytes=40-"},
        )
        assert resp.status_code == 206
        assert resp.headers["content-range"] == f"bytes 40-{len(expected) - 1}/{len(expected)}"
        assert resp.content == expected[40:]

    def test_suffix_range(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, expected = self._canonical(client, auth_headers)
        resp = client.get(
            f"/api/v1/assets/{asset_id}/bytes",
            headers={**auth_headers, "Range": "bytes=-8"},
        )
        assert resp.status_code == 206
        content_range = f"bytes {len(expected) - 8}-{len(expected) - 1}/{len(expected)}"
        assert resp.headers["content-range"] == content_range
        assert resp.content == expected[-8:]

    def test_start_beyond_end(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, expected = self._canonical(client, auth_headers)
        resp = client.get(
            f"/api/v1/assets/{asset_id}/bytes",
            headers={**auth_headers, "Range": f"bytes={len(expected)}-{len(expected) + 9}"},
        )
        assert resp.status_code == 416
        assert resp.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"

    def test_malformed_range(self, client: TestClient, auth_headers: dict) -> None:
        _, asset_id, _ = self._canonical(client, auth_headers)
        resp = client.get(
            f"/api/v1/assets/{asset_id}/bytes",
            headers={**auth_headers, "Range": "items=1-2"},
        )
        assert resp.status_code == 416
        assert resp.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"
