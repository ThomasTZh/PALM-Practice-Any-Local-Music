"""Portable open routes (M2.16, spec §18.1).

HTTP surface: create an archive transfer session, chunk upload with the
import protocol, transfer state, synchronous open on complete, and an
idempotent cancel. The store already holds the seeded project, so a
successful open also exercises content-addressed asset reuse.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.portable.save import perform_portable_save
from basseparate.storage import PortableArtifactRepository, ProjectRepository
from tests.unit.portable_seed import create_seed_files, seed_two_projects

BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app):
    with TestClient(app, base_url=BASE_URL) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(app) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.session_token}"}


@pytest.fixture()
def seeded(app):
    paths = app.state.storage_paths
    seed = seed_two_projects(paths.data.parent)
    create_seed_files(paths.data.parent, seed)
    repo = ProjectRepository(paths.database_path)
    project = repo.get_project(seed.project_a)
    assert project is not None
    return seed


@pytest.fixture()
def archive(app, seeded) -> bytes:
    paths = app.state.storage_paths
    repo = ProjectRepository(paths.database_path)
    artifacts = PortableArtifactRepository(paths.database_path)
    project = repo.get_project(seeded.project_a)
    assert project is not None
    artifact, _manifest = perform_portable_save(
        paths.database_path, paths, project, artifacts
    )
    return paths.resolve_asset_path(artifact.relative_path).read_bytes()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    data: bytes,
    *,
    filename: str = "song.basseparate",
    open_mode: str = "new-copy",
    project_name: str | None = None,
) -> uuid.UUID:
    created = client.post(
        "/api/v1/projects/open",
        headers=headers,
        json={
            "filename": filename,
            "declared_byte_count": len(data),
            "open_mode": open_mode,
            **({"project_name": project_name} if project_name else {}),
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    session_id = uuid.UUID(payload["open_session_id"])
    chunk_size = payload["chunk_size"]
    offset = 0
    while offset < len(data):
        piece = data[offset : offset + chunk_size]
        response = client.put(
            f"/api/v1/projects/open/{session_id}/chunks",
            params={"offset": offset},
            headers={
                **headers,
                "X-Chunk-SHA256": hashlib.sha256(piece).hexdigest(),
            },
            content=piece,
        )
        assert response.status_code == 200, response.text
        assert response.json()["offset"] == offset + len(piece)
        offset += len(piece)
    return session_id


def _complete(client: TestClient, headers: dict[str, str], session_id: uuid.UUID):
    return client.post(
        f"/api/v1/projects/open/{session_id}/complete", headers=headers
    )


def _session_state(client: TestClient, headers: dict[str, str], session_id: uuid.UUID):
    return client.get(f"/api/v1/projects/open/{session_id}", headers=headers)


class TestOpenSessionRoutes:
    def test_create_validates_filename(self, client, auth_headers) -> None:
        response = client.post(
            "/api/v1/projects/open",
            headers=auth_headers,
            json={"filename": "song.zip", "declared_byte_count": 10},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ARCHIVE_BAD_FILENAME"

    def test_create_size_limit(self, tmp_path: Path) -> None:
        base = resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})
        config = replace(
            base,
            import_chunk_bytes=1024,
            max_project_archive_bytes=4096,
            max_archive_uncompressed_bytes=8192,
        )
        app = create_app(config)
        with TestClient(app, base_url=BASE_URL) as client:
            headers = {"Authorization": f"Bearer {app.state.session_token}"}
            response = client.post(
                "/api/v1/projects/open",
                headers=headers,
                json={"filename": "song.basseparate", "declared_byte_count": 5000},
            )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "ARCHIVE_SIZE_LIMIT"

    def test_chunk_protocol_errors(self, client, auth_headers) -> None:
        created = client.post(
            "/api/v1/projects/open",
            headers=auth_headers,
            json={"filename": "song.basseparate", "declared_byte_count": 16},
        ).json()
        session_id = created["open_session_id"]
        chunk_hash = hashlib.sha256(b"abcdefgh").hexdigest()

        skipped = client.put(
            f"/api/v1/projects/open/{session_id}/chunks",
            params={"offset": 8},
            headers={**auth_headers, "X-Chunk-SHA256": chunk_hash},
            content=b"abcdefgh",
        )
        assert skipped.status_code == 400
        assert skipped.json()["error"]["code"] == "OFFSET_MISMATCH"

        bad_hash = client.put(
            f"/api/v1/projects/open/{session_id}/chunks",
            params={"offset": 0},
            headers={**auth_headers, "X-Chunk-SHA256": "0" * 64},
            content=b"abcdefgh",
        )
        assert bad_hash.status_code == 409
        assert bad_hash.json()["error"]["code"] == "CHUNK_CONFLICT"

        missing = client.get(
            f"/api/v1/projects/open/{uuid.uuid4()}", headers=auth_headers
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "OPEN_SESSION_NOT_FOUND"

    def test_state_and_incomplete_complete(
        self, client, auth_headers, archive: bytes
    ) -> None:
        created = client.post(
            "/api/v1/projects/open",
            headers=auth_headers,
            json={"filename": "song.basseparate", "declared_byte_count": len(archive)},
        ).json()
        session_id = created["open_session_id"]

        state = _session_state(client, auth_headers, session_id).json()
        assert state["state"] == "created"
        assert state["received_byte_count"] == 0
        assert state["open_mode"] == "new-copy"

        # One byte short of the declared size: still uploading.
        piece = archive[:-1]
        uploaded = client.put(
            f"/api/v1/projects/open/{session_id}/chunks",
            params={"offset": 0},
            headers={
                **auth_headers,
                "X-Chunk-SHA256": hashlib.sha256(piece).hexdigest(),
            },
            content=piece,
        )
        assert uploaded.status_code == 200
        state = _session_state(client, auth_headers, session_id).json()
        assert state["state"] == "uploading"
        assert state["received_byte_count"] == len(piece)

        incomplete = _complete(client, auth_headers, session_id)
        assert incomplete.status_code == 409
        assert incomplete.json()["error"]["code"] == "OPEN_SESSION_INCOMPLETE"

        tail = archive[-1:]
        finished = client.put(
            f"/api/v1/projects/open/{session_id}/chunks",
            params={"offset": len(piece)},
            headers={
                **auth_headers,
                "X-Chunk-SHA256": hashlib.sha256(tail).hexdigest(),
            },
            content=tail,
        )
        assert finished.status_code == 200
        assert _session_state(client, auth_headers, session_id).json()["state"] == "complete"

    def test_cancel_is_idempotent(self, client, auth_headers, archive: bytes) -> None:
        session_id = _upload(client, auth_headers, archive)
        first = client.post(
            f"/api/v1/projects/open/{session_id}/cancel", headers=auth_headers
        )
        assert first.status_code == 200
        assert first.json()["state"] == "cancelled"
        assert _session_state(client, auth_headers, session_id).status_code == 404
        second = client.post(
            f"/api/v1/projects/open/{session_id}/cancel", headers=auth_headers
        )
        assert second.status_code == 200

    def test_open_round_trip(self, client, auth_headers, seeded, archive: bytes) -> None:
        session_id = _upload(client, auth_headers, archive, project_name="Opened Copy")
        response = _complete(client, auth_headers, session_id)
        assert response.status_code == 201, response.text
        project = response.json()
        assert project["project_id"] != seeded.project_a
        assert project["name"] == "Opened Copy"
        assert project["status"] == "ready"
        # The session is gone after success.
        assert _session_state(client, auth_headers, session_id).status_code == 404
        listing = client.get("/api/v1/projects", headers=auth_headers)
        assert listing.status_code == 200
        ids = {item["id"] for item in listing.json()["projects"]}
        assert project["project_id"] in ids
        assert seeded.project_a in ids

    def test_as_archived_conflict(
        self, client, auth_headers, seeded, archive: bytes
    ) -> None:
        # The archive was saved from the seeded project; remove that
        # project so the archived identity is free.
        _delete_project(client, seeded.project_a)
        first = _upload(client, auth_headers, archive, open_mode="as-archived")
        assert _complete(client, auth_headers, first).status_code == 201
        second = _upload(client, auth_headers, archive, open_mode="as-archived")
        response = _complete(client, auth_headers, second)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "OPEN_ID_CONFLICT"
        # The failed session survives for a retry and carries the error.
        state = _session_state(client, auth_headers, second).json()
        assert state["last_error"] is not None
        client.post(f"/api/v1/projects/open/{second}/cancel", headers=auth_headers)

    def test_failed_complete_keeps_session(self, client, auth_headers) -> None:
        payload = b"this is not a zip archive"
        session_id = _upload(client, auth_headers, payload)
        response = _complete(client, auth_headers, session_id)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ARCHIVE_NOT_ZIP"
        state = _session_state(client, auth_headers, session_id).json()
        assert state["state"] == "complete"  # transfer is complete; open failed
        assert "ZIP" in state["last_error"]
        # Retry is possible, then cancel removes the retained bytes.
        retry = _complete(client, auth_headers, session_id)
        assert retry.status_code == 422
        cancelled = client.post(
            f"/api/v1/projects/open/{session_id}/cancel", headers=auth_headers
        )
        assert cancelled.status_code == 200
        uploads_dir = client.app.state.storage_paths.runtime / "archive-uploads"
        assert not any(uploads_dir.iterdir())

    def test_open_reuses_assets_in_same_store(
        self, client, auth_headers, archive: bytes
    ) -> None:
        before = _asset_count(client)
        session_id = _upload(client, auth_headers, archive)
        response = _complete(client, auth_headers, session_id)
        assert response.status_code == 201
        assert _asset_count(client) == before


def _delete_project(client, project_id: str) -> None:
    db = client.app.state.storage_paths.database_path
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def _asset_count(client) -> int:
    db = client.app.state.storage_paths.database_path
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    finally:
        conn.close()
