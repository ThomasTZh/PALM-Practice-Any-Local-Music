"""Route tests for local Vamp analysis."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def client(config: AppConfig):
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c, app


def _auth(app) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.session_token}"}


def _ready_project(client: TestClient, app) -> str:
    created = client.post("/api/v1/projects", json={"name": "Vamp"}, headers=_auth(app))
    assert created.status_code == 201
    project_id = created.json()["id"]
    conn = sqlite3.connect(str(Path(app.state.storage_paths.database_path)))
    try:
        conn.execute(
            """
            UPDATE projects SET status='ready', source_asset_id=?, canonical_asset_id=?,
                source_stream_index=0, sample_rate=48000, duration_frames=480000,
                source_channel_count=1, source_channel_layout='mono',
                decode_profile_version=1
            WHERE id=?
            """,
            (str(uuid.uuid4()), str(uuid.uuid4()), project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return project_id


def test_unconfigured_vamp_returns_actionable_error(client) -> None:
    test_client, app = client
    project_id = _ready_project(test_client, app)
    response = test_client.post(
        f"/api/v1/projects/{project_id}/vamp-analysis",
        json={"bpb": 4},
        headers=_auth(app),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VAMP_UNAVAILABLE"


def test_unknown_project_returns_404(client) -> None:
    test_client, app = client
    response = test_client.post(
        f"/api/v1/projects/{uuid.uuid4()}/vamp-analysis",
        json={"bpb": 4},
        headers=_auth(app),
    )
    assert response.status_code == 404
