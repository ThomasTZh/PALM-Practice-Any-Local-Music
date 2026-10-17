"""Portable save routes (M2.15, spec §17, §19.2).

HTTP surface: synchronous save with idempotency, listing, and
authenticated streaming download with ``Content-Disposition``.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.storage import ProjectRepository
from tests.unit.portable_seed import STEM1_HASH_A, create_seed_files, seed_two_projects

BASE_URL = "http://127.0.0.1:8765"


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
    return {"Authorization": f"Bearer {app.state.session_token}"}


@pytest.fixture()
def seeded(app):
    """A ready project (from the portable seed) with its files on disk."""
    paths = app.state.storage_paths
    seed = seed_two_projects(paths.data.parent)
    create_seed_files(paths.data.parent, seed)
    repo = ProjectRepository(paths.database_path)
    project = repo.get_project(seed.project_a)
    assert project is not None
    return seed


class TestPortableSaveRoutes:
    def test_save_creates_artifact(self, client, auth_headers, seeded) -> None:
        resp = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == seeded.project_a
        assert body["saved_revision"] == 5
        assert body["byte_size"] > 0
        assert len(body["sha256"]) == 64
        assert body["download_url"] == (
            f"/api/v1/portable-downloads/{body['artifact_id']}"
        )
        assert body["download_filename"].endswith(".basseparate")

    def test_save_idempotent_replay(self, client, auth_headers, seeded) -> None:
        key = str(uuid.uuid4())
        headers = {**auth_headers, "Idempotency-Key": key}
        first = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=headers
        )
        assert first.status_code == 201
        second = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=headers
        )
        assert second.status_code == 201
        assert second.json() == first.json()
        # The replay did not run a second save.
        listing = client.get(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers
        ).json()
        assert len(listing["saves"]) == 1

    def test_save_unknown_project_404(self, client, auth_headers) -> None:
        resp = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/portable-saves", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_save_missing_essential_409(self, client, auth_headers, seeded) -> None:
        paths = client.app.state.storage_paths
        stem1 = paths.data.parent / f"data/assets/{STEM1_HASH_A}.pcm"
        stem1.unlink()
        resp = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers
        )
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "SAVE_ASSET_MISSING"
        assert any(Path(m).name == f"{STEM1_HASH_A}.pcm" for m in error["details"]["missing"])

    def test_listing(self, client, auth_headers, seeded) -> None:
        client.post(f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers)
        resp = client.get(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers
        )
        assert resp.status_code == 200
        saves = resp.json()["saves"]
        assert len(saves) == 1
        assert saves[0]["saved_revision"] == 5

    def test_download_streams_verified_bytes(self, client, auth_headers, seeded) -> None:
        created = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves", headers=auth_headers
        ).json()
        resp = client.get(created["download_url"], headers=auth_headers)
        assert resp.status_code == 200
        data = resp.content
        assert len(data) == created["byte_size"]
        assert hashlib.sha256(data).hexdigest() == created["sha256"]
        assert resp.headers["Content-Type"] == "application/zip"
        assert resp.headers["X-Content-Sha256"] == created["sha256"]
        disposition = resp.headers["Content-Disposition"]
        assert 'attachment' in disposition
        assert created["download_filename"] in disposition

    def test_download_unknown_artifact_404(self, client, auth_headers) -> None:
        resp = client.get(f"/api/v1/portable-downloads/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PORTABLE_ARTIFACT_NOT_FOUND"

    def test_requires_auth(self, client, seeded) -> None:
        resp = client.post(f"/api/v1/projects/{seeded.project_a}/portable-saves")
        assert resp.status_code == 401
