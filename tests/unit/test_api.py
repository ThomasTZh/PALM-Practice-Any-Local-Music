"""Integration tests for the FastAPI application (M0.6/M0.7)."""

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
def app(config: AppConfig):
    return create_app(config)


BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture()
def auth_headers(app) -> dict[str, str]:
    token = app.state.session_token
    return {"Authorization": f"Bearer {token}"}


class TestHealth:
    def test_ready_no_auth(self, client: TestClient) -> None:
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
    def test_system_info(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/v1/system", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_version"] == 1
        assert data["ready"] is True
        assert "app_version" in data

    def test_system_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/v1/system")
        assert resp.status_code == 401


class TestProjects:
    def test_list_empty(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["projects"] == []

    def test_create_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            "/api/v1/projects", json={"name": "My First Project"}, headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My First Project"
        assert data["status"] == "empty"
        assert data["revision"] == 0
        assert data["source_asset_id"] is None
        assert data["sample_rate"] is None
        assert data["duration_samples"] is None
        assert data["schema_version"] == 1
        uuid.UUID(data["id"])

    def test_create_project_trims_name(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post("/api/v1/projects", json={"name": "  padded  "}, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["name"] == "padded"

    def test_create_project_rejects_empty_name(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        resp = client.post("/api/v1/projects", json={"name": "   "}, headers=auth_headers)
        assert resp.status_code == 422

    def test_get_project(self, client: TestClient, auth_headers: dict) -> None:
        created = client.post("/api/v1/projects", json={"name": "Fetch Me"}, headers=auth_headers)
        project_id = created.json()["id"]
        resp = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Fetch Me"

    def test_get_project_not_found(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "PROJECT_NOT_FOUND"
        assert "request_id" in data["error"]

    def test_list_after_create(self, client: TestClient, auth_headers: dict) -> None:
        client.post("/api/v1/projects", json={"name": "A"}, headers=auth_headers)
        client.post("/api/v1/projects", json={"name": "B"}, headers=auth_headers)
        resp = client.get("/api/v1/projects", headers=auth_headers)
        names = {p["name"] for p in resp.json()["projects"]}
        assert names == {"A", "B"}

    def test_idempotency_key_replay(self, client: TestClient, auth_headers: dict) -> None:
        key = "test-key-123"
        headers = {**auth_headers, "Idempotency-Key": key}
        resp1 = client.post("/api/v1/projects", json={"name": "Idem"}, headers=headers)
        resp2 = client.post("/api/v1/projects", json={"name": "Idem"}, headers=headers)
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_idempotency_key_conflict(self, client: TestClient, auth_headers: dict) -> None:
        key = "test-key-456"
        headers = {**auth_headers, "Idempotency-Key": key}
        client.post("/api/v1/projects", json={"name": "First"}, headers=headers)
        resp = client.post("/api/v1/projects", json={"name": "Different"}, headers=headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


class TestModulesAndModels:
    def test_modules_empty(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/v1/modules", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["modules"] == []

    def test_models_empty(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/v1/models", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["models"] == []


class TestRequestTracing:
    def test_request_id_header(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert "x-request-id" in resp.headers

    def test_request_id_in_error(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=auth_headers)
        request_id = resp.headers["x-request-id"]
        assert resp.json()["error"]["request_id"] == request_id


class TestSecurity:
    def test_valid_token_succeeds(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200

    def test_missing_token_fails(self, client: TestClient) -> None:
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_incorrect_token_fails(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_hostile_origin_fails(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            "/api/v1/projects",
            headers={**auth_headers, "Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_unexpected_host_fails(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            "/api/v1/projects",
            headers={**auth_headers, "Host": "evil.example.com"},
        )
        assert resp.status_code == 403

    def test_health_reveals_no_sensitive_info(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        body = resp.text.lower()
        assert "token" not in body
        assert "bearer" not in body
        assert "/home" not in body

    def test_security_headers_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert resp.headers.get("cross-origin-opener-policy") == "same-origin"
        assert "content-security-policy" in resp.headers

    def test_loopback_origin_allowed(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(
            "/api/v1/projects",
            headers={**auth_headers, "Origin": "http://127.0.0.1:8765"},
        )
        assert resp.status_code == 200

    def test_no_origin_header_allowed(self, client: TestClient, auth_headers: dict) -> None:
        """CLI requests without Origin header should work with valid token."""
        resp = client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
