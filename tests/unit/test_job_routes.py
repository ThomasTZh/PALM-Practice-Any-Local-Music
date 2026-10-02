"""API route tests for durable media jobs (M1.4)."""

from __future__ import annotations

import hashlib
import struct
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config

BASE_URL = "http://127.0.0.1:8765"


def _make_wav() -> bytes:
    pcm = b"\x00\x00" * 4410
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
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
    return hashlib.sha256(data).hexdigest()


def _complete_import(client: TestClient, headers: dict, project_id: str, data: bytes) -> str:
    """Run the full M1.2 upload flow and return the import id."""
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
    resp = client.post("/api/v1/projects", json={"name": "Jobs"}, headers=headers)
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


class TestCreateJob:
    def test_create_probe_job_and_poll_to_completion(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())

        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "probe", "import_id": import_id},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        job = resp.json()
        assert job["id"]
        assert job["state"] in ("queued", "running")
        assert job["job_type"] == "probe"
        assert job["import_id"] == import_id
        assert job["project_id"] == project_id

        final = _wait_for_job(client, auth_headers, job["id"])
        assert final["state"] == "completed"
        assert final["stage"] == "ready"
        assert final["result"]["format_name"] == "wav"
        assert len(final["result"]["audio_streams"]) == 1

        # The job id was linked to the import.
        resp = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers)
        assert resp.json()["job_ids"] == [job["id"]]

    def test_create_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/jobs",
            json={"job_type": "probe", "import_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_create_unknown_import(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "probe", "import_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "IMPORT_NOT_FOUND"

    def test_create_import_of_other_project(self, client: TestClient, auth_headers: dict) -> None:
        project_a = _make_project(client, auth_headers)
        project_b = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_a, _make_wav())

        resp = client.post(
            f"/api/v1/projects/{project_b}/jobs",
            json={"job_type": "probe", "import_id": import_id},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IMPORT_STATE"

    def test_create_incomplete_import(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            "/api/v1/imports",
            json={"project_id": project_id, "filename": "a.wav", "declared_byte_count": 100},
            headers=auth_headers,
        )
        import_id = resp.json()["import_id"]

        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "probe", "import_id": import_id},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IMPORT_STATE"

    def test_create_rejects_unknown_job_type(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())
        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "transpose", "import_id": import_id},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestGetJob:
    def test_get_job(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())
        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "probe", "import_id": import_id},
            headers=auth_headers,
        )
        job_id = resp.json()["id"]
        final = _wait_for_job(client, auth_headers, job_id)

        resp = client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["state"] == final["state"]

    def test_get_missing_job(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


class TestListJobs:
    def test_list_project_jobs(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())
        for job_type in ("probe", "waveform"):
            resp = client.post(
                f"/api/v1/projects/{project_id}/jobs",
                json={"job_type": job_type, "import_id": import_id},
                headers=auth_headers,
            )
            assert resp.status_code == 201, resp.text

        # Let the scheduler settle so both jobs reach terminal states.
        _wait_for_job(client, auth_headers, resp.json()["id"])

        resp = client.get(f"/api/v1/projects/{project_id}/jobs", headers=auth_headers)
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 2
        assert {j["job_type"] for j in jobs} == {"probe", "waveform"}

    def test_list_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/jobs", headers=auth_headers)
        assert resp.status_code == 404


class TestCancelJob:
    def test_cancel_completed_job_is_noop(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())
        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "probe", "import_id": import_id},
            headers=auth_headers,
        )
        job_id = resp.json()["id"]
        _wait_for_job(client, auth_headers, job_id)

        resp = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["state"] == "completed"

    def test_cancel_missing_job(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(f"/api/v1/jobs/{uuid.uuid4()}/cancel", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"

    def test_cancel_unimplemented_job_type_fails_cleanly(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _complete_import(client, auth_headers, project_id, _make_wav())
        resp = client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"job_type": "canonical_decode", "import_id": import_id},
            headers=auth_headers,
        )
        job_id = resp.json()["id"]
        final = _wait_for_job(client, auth_headers, job_id)
        assert final["state"] == "failed"
        assert final["error_code"] == "JOB_TYPE_NOT_IMPLEMENTED"
