"""Route tests for project commands, undo/redo, and idempotency (M1.15)."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config

DURATION = 100_000


@pytest.fixture()
def config(tmp_path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


@pytest.fixture()
def auth_headers(app) -> dict[str, str]:
    token = app.state.session_token
    return {"Authorization": f"Bearer {token}"}


def _db_path(app) -> Path:
    return Path(app.state.storage_paths.database_path)


def _ready_project(client: TestClient, auth_headers: dict, app) -> str:
    """Create a project and flip it to ready with a full source row."""
    created = client.post("/api/v1/projects", json={"name": "Ready"}, headers=auth_headers)
    assert created.status_code == 201
    project_id = created.json()["id"]
    conn = sqlite3.connect(str(_db_path(app)))
    try:
        conn.execute(
            """
            UPDATE projects SET
                status = 'ready',
                source_asset_id = ?,
                canonical_asset_id = ?,
                source_stream_index = 0,
                sample_rate = 48000,
                duration_frames = ?,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1
            WHERE id = ?
            """,
            (str(uuid.uuid4()), str(uuid.uuid4()), DURATION, project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return project_id


def _command_body(op: dict, base_revision: int, key: str | None = None) -> dict:
    return {
        "command_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "base_revision": base_revision,
        "op": op,
    }


def _post_command(
    client: TestClient, auth_headers: dict, project_id: str, body: dict
) -> Response:
    return client.post(
        f"/api/v1/projects/{project_id}/commands", json=body, headers=auth_headers
    )


class TestCommands:
    def test_add_marker_returns_resulting_state(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 1_200}, 0),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["revision"] == 1
        assert data["can_undo"] is True
        assert data["can_redo"] is False
        assert len(data["markers"]) == 1
        assert data["markers"][0]["position_frames"] == 1_200
        assert data["markers"][0]["label"] == "Marker"
        assert data["working_state"]["follow_playhead"] is True


    def test_add_section_returns_section_state(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {
                    "type": "add_section",
                    "name": "Intro",
                    "start_frames": 0,
                    "end_frames": 8_000,
                },
                0,
            ),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["practice_state"]["sections"] == [
            {
                "id": data["practice_state"]["sections"][0]["id"],
                "name": "Intro",
                "start_frames": 0,
                "end_frames": 8_000,
                "color": "#22c55e",
                "created_at": data["practice_state"]["sections"][0]["created_at"],
                "updated_at": data["practice_state"]["sections"][0]["updated_at"],
            }
        ]

    def test_overlapping_section_is_rejected(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "add_section", "name": "A", "start_frames": 0, "end_frames": 8_000},
                0,
            ),
        )
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "add_section", "name": "B", "start_frames": 7_000, "end_frames": 9_000},
                1,
            ),
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SECTION_OVERLAP"
    def test_stale_revision_conflict(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 1}, 0),
        )
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 2}, 0),
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "STALE_REVISION"
        assert data["error"]["details"]["current_revision"] == 1

    def test_idempotent_replay(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        body = _command_body({"type": "add_marker", "position_frames": 5}, 0, key="key-1")
        resp1 = _post_command(client, auth_headers, project_id, body)
        resp2 = _post_command(client, auth_headers, project_id, body)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()
        # The command was applied exactly once.
        got = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
        assert got.json()["revision"] == 1
        assert len(got.json()["markers"]) == 1

    def test_idempotency_conflict(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 5}, 0, key="key-2"),
        )
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 6}, 0, key="key-2"),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    def test_unknown_project_404(self, client: TestClient, auth_headers: dict) -> None:
        resp = _post_command(
            client,
            auth_headers,
            str(uuid.uuid4()),
            _command_body({"type": "add_marker", "position_frames": 0}, 0),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_invalid_payload_422(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "explode_marker"}, 0),
        )
        assert resp.status_code == 422

    def test_position_op_on_empty_project_409(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        created = client.post("/api/v1/projects", json={"name": "Empty"}, headers=auth_headers)
        project_id = created.json()["id"]
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 0}, 0),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_marker_beyond_duration_422(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": DURATION + 1}, 0),
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_COMMAND"

    def test_update_missing_marker_404(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "update_marker", "marker_id": str(uuid.uuid4()), "label": "X"}, 0
            ),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MARKER_NOT_FOUND"

    def test_working_state_ops_on_empty_project(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        created = client.post("/api/v1/projects", json={"name": "Empty"}, headers=auth_headers)
        project_id = created.json()["id"]
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {
                    "type": "set_monitoring_volume",
                    "volume": 0.5,
                },
                0,
            ),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["working_state"]["monitoring_volume"] == 0.5

    def test_get_project_includes_markers_and_working_state(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 42}, 0),
        )
        got = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
        assert got.status_code == 200
        data = got.json()
        assert len(data["markers"]) == 1
        assert data["markers"][0]["position_frames"] == 42
        assert data["working_state"]["last_position_frames"] == 0


class TestUndoRedo:
    def test_undo_and_redo_roundtrip(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        added = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 10}, 0),
        )
        assert added.status_code == 200
        marker_id = added.json()["markers"][0]["id"]
        renamed = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "update_marker", "marker_id": marker_id, "label": "B"}, 1
            ),
        )
        assert renamed.status_code == 200

        undone = client.post(
            f"/api/v1/projects/{project_id}/undo",
            json={"base_revision": 2},
            headers=auth_headers,
        )
        assert undone.status_code == 200, undone.text
        data = undone.json()
        assert data["markers"][0]["label"] == "Marker"
        assert data["revision"] == 3
        assert data["can_redo"] is True

        redone = client.post(
            f"/api/v1/projects/{project_id}/redo",
            json={"base_revision": 3},
            headers=auth_headers,
        )
        assert redone.status_code == 200, redone.text
        data = redone.json()
        assert data["markers"][0]["label"] == "B"
        assert data["revision"] == 4
        assert data["can_redo"] is False

    def test_nothing_to_undo_409(self, client: TestClient, auth_headers: dict) -> None:
        created = client.post("/api/v1/projects", json={"name": "Empty"}, headers=auth_headers)
        project_id = created.json()["id"]
        resp = client.post(
            f"/api/v1/projects/{project_id}/undo",
            json={"base_revision": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NOTHING_TO_UNDO"
        resp = client.post(
            f"/api/v1/projects/{project_id}/redo",
            json={"base_revision": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NOTHING_TO_REDO"

    def test_stale_undo_409(self, client: TestClient, auth_headers: dict, app) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 10}, 0),
        )
        resp = client.post(
            f"/api/v1/projects/{project_id}/undo",
            json={"base_revision": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "STALE_REVISION"

    def test_undo_preserves_playhead_position(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "add_marker", "position_frames": 10}, 0),
        )
        positioned = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "set_position", "position_frames": 55_000}, 1),
        )
        assert positioned.status_code == 200
        undone = client.post(
            f"/api/v1/projects/{project_id}/undo",
            json={"base_revision": 2},
            headers=auth_headers,
        )
        assert undone.status_code == 200
        data = undone.json()
        assert data["markers"] == []
        assert data["working_state"]["last_position_frames"] == 55_000


class TestLoopCommands:
    """M2.11 loop ops through the command endpoint (spec §13)."""

    def _add_loop(
        self,
        client: TestClient,
        auth_headers: dict,
        project_id: str,
        base_revision: int,
        *,
        start: int = 1_000,
        end: int = 5_800,
    ) -> Response:
        return _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "add_loop", "start_frames": start, "end_frames": end},
                base_revision,
            ),
        )

    def test_add_loop_returns_resulting_state(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = self._add_loop(client, auth_headers, project_id, 0)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["revision"] == 1
        assert len(data["practice_state"]["loops"]) == 1
        loop = data["practice_state"]["loops"][0]
        assert loop["name"] == "Loop 1"
        assert loop["start_frames"] == 1_000
        assert loop["end_frames"] == 5_800
        assert loop["repeat_count"] is None
        assert loop["boundary_fade"] is True

    def test_update_missing_loop_404(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body(
                {"type": "update_loop", "loop_id": str(uuid.uuid4()), "name": "X"}, 0
            ),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "LOOP_NOT_FOUND"

    def test_loop_beyond_duration_422(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = self._add_loop(client, auth_headers, project_id, 0, start=0, end=DURATION + 1)
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "LOOP_RANGE_INVALID"
        assert body["error"]["details"]["duration_frames"] == DURATION

    def test_enable_without_active_loop_409(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "set_loop_enabled", "enabled": True}, 0),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NO_ACTIVE_LOOP"

    def test_short_loop_enable_409_explains_minimum(
        self, client: TestClient, auth_headers: dict, app
    ) -> None:
        project_id = _ready_project(client, auth_headers, app)
        added = self._add_loop(
            client, auth_headers, project_id, 0, start=1_000, end=1_000 + 4_799
        )
        assert added.status_code == 200
        loop_id = added.json()["practice_state"]["loops"][0]["id"]
        active = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "set_active_loop", "loop_id": loop_id}, 1),
        )
        assert active.status_code == 200
        resp = _post_command(
            client,
            auth_headers,
            project_id,
            _command_body({"type": "set_loop_enabled", "enabled": True}, 2),
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "LOOP_TOO_SHORT"
        assert "100 ms" in body["error"]["message"]
        assert body["error"]["details"]["minimum_ms"] == 100
        # The loop is retained and still selectable (§13.3.2).
        assert body["error"]["details"]["frames"] == 4_799
