"""Integration tests for the FastAPI application (M0.6)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config


@pytest.fixture()
def config(tmp_path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def client(config: AppConfig) -> TestClient:
    app = create_app(config)
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_ready(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["api_version"] == 1

    def test_no_sensitive_data(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        body = resp.text
        assert "token" not in body.lower()
        assert "/home" not in body
        assert "gpu" not in body.lower()


class TestSystem:
    def test_system_info(self, client: TestClient) -> None:
        resp = client.get("/api/v1/system")
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_version"] == 1
        assert data["ready"] is True
        assert "app_version" in data


class TestProjects:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json()["projects"] == []

    def test_create_project(self, client: TestClient) -> None:
        resp = client.post("/api/v1/projects", json={"name": "My First Project"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My First Project"
        assert data["status"] == "empty"
        assert data["revision"] == 0
        assert data["source_asset_id"] is None
        assert data["sample_rate"] is None
        assert data["duration_samples"] is None
        assert data["schema_version"] == 1
        # Server-generated ID
        uuid.UUID(data["id"])

    def test_create_project_trims_name(self, client: TestClient) -> None:
        resp = client.post("/api/v1/projects", json={"name": "  padded  "})
        assert resp.status_code == 201
        assert resp.json()["name"] == "padded"

    def test_create_project_rejects_empty_name(self, client: TestClient) -> None:
        resp = client.post("/api/v1/projects", json={"name": "   "})
        assert resp.status_code == 422

    def test_get_project(self, client: TestClient) -> None:
        created = client.post("/api/v1/projects", json={"name": "Fetch Me"})
        project_id = created.json()["id"]
        resp = client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Fetch Me"

    def test_get_project_not_found(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "PROJECT_NOT_FOUND"
        assert "request_id" in data["error"]

    def test_list_after_create(self, client: TestClient) -> None:
        client.post("/api/v1/projects", json={"name": "A"})
        client.post("/api/v1/projects", json={"name": "B"})
        resp = client.get("/api/v1/projects")
        names = {p["name"] for p in resp.json()["projects"]}
        assert names == {"A", "B"}

    def test_idempotency_key_replay(self, client: TestClient) -> None:
        key = "test-key-123"
        resp1 = client.post(
            "/api/v1/projects",
            json={"name": "Idem"},
            headers={"Idempotency-Key": key},
        )
        resp2 = client.post(
            "/api/v1/projects",
            json={"name": "Idem"},
            headers={"Idempotency-Key": key},
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_idempotency_key_conflict(self, client: TestClient) -> None:
        key = "test-key-456"
        client.post(
            "/api/v1/projects",
            json={"name": "First"},
            headers={"Idempotency-Key": key},
        )
        resp = client.post(
            "/api/v1/projects",
            json={"name": "Different"},
            headers={"Idempotency-Key": key},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


class TestModulesAndModels:
    def test_modules_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/modules")
        assert resp.status_code == 200
        assert resp.json()["modules"] == []

    def test_models_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        assert resp.json()["models"] == []


class TestRequestTracing:
    def test_request_id_header(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert "x-request-id" in resp.headers

    def test_request_id_in_error(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}")
        request_id = resp.headers["x-request-id"]
        assert resp.json()["error"]["request_id"] == request_id
