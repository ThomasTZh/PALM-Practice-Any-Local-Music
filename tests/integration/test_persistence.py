"""Persistence and restart integration tests (spec section 18.7).

Each test runs a full application (FastAPI app plus media worker) against
one storage root, closes it, and starts a second instance on the same
root. The durable state must survive the restart: the import and its
decoded PCM, markers, working (view) state, and the undo/redo history.
Stale revisions must conflict safely, an interrupted job must be
recovered, and the original user file must remain byte-identical.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from synth import wav_s16_bytes

from basseparate.app import create_app
from basseparate.config import resolve_config
from basseparate.domain.media_job import JobType
from basseparate.storage.paths import resolve_storage_paths
from basseparate.storage.repository import JobRepository

BASE_URL = "http://127.0.0.1:8765"
RATE = 44_100
FRAMES = 4_410  # a one-tenth-of-a-second mono source
_PCM = (0.5 * np.sin(2.0 * np.pi * 440.0 * (np.arange(FRAMES, dtype="<f8") / RATE))).astype(
    "<i2"
)
WAV = wav_s16_bytes(_PCM.tobytes(), RATE)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@contextmanager
def _app(root: Path) -> Iterator[tuple[TestClient, dict[str, str]]]:
    """One full application instance on ``root`` (the 'process' under test)."""
    app = create_app(resolve_config(env={}, cli={"storage_root": str(root)}))
    with TestClient(app, base_url=BASE_URL) as client:
        yield client, {"Authorization": f"Bearer {app.state.session_token}"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _db_path(root: Path) -> Path:
    return resolve_storage_paths(root).database_path


def _asset_path(root: Path, asset_id: str) -> Path:
    conn = sqlite3.connect(str(_db_path(root)))
    try:
        row = conn.execute(
            "SELECT relative_path FROM assets WHERE id = ?", (asset_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"asset {asset_id} not found"
    return resolve_storage_paths(root).resolve_asset_path(row[0])


def _job_row_count(root: Path) -> int:
    conn = sqlite3.connect(str(_db_path(root)))
    try:
        return conn.execute("SELECT COUNT(*) FROM media_jobs").fetchone()[0]
    finally:
        conn.close()


def _make_project(client: TestClient, headers: dict[str, str], name: str = "Persistence") -> str:
    resp = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client: TestClient, headers: dict[str, str], project_id: str, data: bytes) -> str:
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


def _wait_for_job(
    client: TestClient, headers: dict[str, str], job_id: str, timeout: float = 60.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        job = resp.json()
        if job["state"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def _run_job(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    job_type: str,
    import_id: str,
) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/projects/{project_id}/jobs",
        json={"job_type": job_type, "import_id": import_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    job = _wait_for_job(client, headers, resp.json()["id"])
    assert job["state"] == "completed", job
    return job


def _ready_project(root: Path, client: TestClient, headers: dict[str, str]) -> tuple[str, int]:
    """Create a project, import the test WAV, probe, and decode to ready.

    Returns the project id and its current revision (the ready transition
    itself bumps the revision to 1).
    """
    project_id = _make_project(client, headers)
    import_id = _upload(client, headers, project_id, WAV)
    _run_job(client, headers, project_id, "probe", import_id)
    _run_job(client, headers, project_id, "canonical_decode", import_id)
    project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert project["status"] == "ready", project
    return project_id, project["revision"]


def _command_body(op: dict[str, Any], base_revision: int) -> dict[str, Any]:
    return {
        "command_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "base_revision": base_revision,
        "op": op,
    }


def _post_command(
    client: TestClient, headers: dict[str, str], project_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/projects/{project_id}/commands", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestImportPersistence:
    def test_import_and_decode_survive_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, _ = _ready_project(root, client, headers)
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            pcm_sha = _file_sha256(_asset_path(root, project["canonical_asset_id"]))
            original_sha = _file_sha256(_asset_path(root, project["source_asset_id"]))

        with _app(root) as (client, headers):
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            assert project["status"] == "ready"
            assert project["sample_rate"] == RATE
            assert project["duration_frames"] == FRAMES
            # The same assets are still attached, and the files on disk
            # are byte-identical.
            assert _file_sha256(_asset_path(root, project["canonical_asset_id"])) == pcm_sha
            assert _file_sha256(_asset_path(root, project["source_asset_id"])) == original_sha

    def test_reopen_does_not_redecode(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, _ = _ready_project(root, client, headers)
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            pcm_path = _asset_path(root, project["canonical_asset_id"])
            pcm_sha = _file_sha256(pcm_path)
            pcm_mtime = pcm_path.stat().st_mtime
            jobs_before = _job_row_count(root)

        with _app(root) as (client, headers):
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            assert project["status"] == "ready"
            # Reopening created no new jobs and left none active.
            assert _job_row_count(root) == jobs_before
            conn = sqlite3.connect(str(_db_path(root)))
            try:
                active = conn.execute(
                    "SELECT COUNT(*) FROM media_jobs WHERE state IN ('queued', 'running')"
                ).fetchone()[0]
            finally:
                conn.close()
            assert active == 0
            # The canonical PCM was not re-decoded: bytes and mtime unchanged.
            assert _file_sha256(pcm_path) == pcm_sha
            assert pcm_path.stat().st_mtime == pcm_mtime


class TestMarkerPersistence:
    def test_markers_persist_across_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, rev = _ready_project(root, client, headers)
            _post_command(
                client,
                headers,
                project_id,
                _command_body({"type": "add_marker", "position_frames": 100}, rev),
            )
            _post_command(
                client,
                headers,
                project_id,
                _command_body(
                    {"type": "add_marker", "position_frames": 2000, "label": "Drop"}, rev + 1
                ),
            )
            before = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()

        with _app(root) as (client, headers):
            after = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            assert after["markers"] == before["markers"]
            assert [m["position_frames"] for m in after["markers"]] == [100, 2000]
            assert [m["label"] for m in after["markers"]] == ["Marker", "Drop"]
            assert after["revision"] == before["revision"]


class TestViewStatePersistence:
    def test_view_state_persists_across_restart(self, root: Path) -> None:
        ops = [
            {"type": "set_viewport", "viewport": {"start_frame": 100, "frames_per_css_pixel": 0.5}},
            {"type": "set_selection", "start_frames": 100, "end_frames": 200},
            {"type": "set_display", "channel_display": {"linked": False, "scales": [2.0]}},
            {"type": "set_monitoring_volume", "volume": 0.7},
            {"type": "set_position", "position_frames": 1234},
            {"type": "set_follow_playhead", "follow_playhead": False},
        ]
        with _app(root) as (client, headers):
            project_id, rev = _ready_project(root, client, headers)
            for i, op in enumerate(ops):
                _post_command(client, headers, project_id, _command_body(op, rev + i))
            before = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()

        with _app(root) as (client, headers):
            after = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            assert after["working_state"] == before["working_state"]
            state = after["working_state"]
            assert state["viewport"] == {"start_frame": 100, "frames_per_css_pixel": 0.5}
            assert state["selection"] == {"start": 100, "end": 200}
            assert state["channel_display"] == {"linked": False, "scales": [2.0]}
            assert state["monitoring_volume"] == 0.7
            assert state["last_position_frames"] == 1234
            assert state["follow_playhead"] is False


class TestUndoRedoPersistence:
    def test_undo_redo_persists_across_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, rev = _ready_project(root, client, headers)
            added = _post_command(
                client,
                headers,
                project_id,
                _command_body({"type": "add_marker", "position_frames": 10}, rev),
            )
            marker_id = added["markers"][0]["id"]
            _post_command(
                client,
                headers,
                project_id,
                _command_body(
                    {"type": "update_marker", "marker_id": marker_id, "label": "B"}, rev + 1
                ),
            )
            undone = client.post(
                f"/api/v1/projects/{project_id}/undo",
                json={"base_revision": rev + 2},
                headers=headers,
            )
            assert undone.status_code == 200, undone.text

        with _app(root) as (client, headers):
            data = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            # The undo survived: the label is back and redo is offered.
            assert data["markers"][0]["label"] == "Marker"
            assert data["revision"] == rev + 3
            assert data["can_redo"] is True

            redone = client.post(
                f"/api/v1/projects/{project_id}/redo",
                json={"base_revision": rev + 3},
                headers=headers,
            )
            assert redone.status_code == 200, redone.text
            data = redone.json()
            assert data["markers"][0]["label"] == "B"
            assert data["can_redo"] is False


class TestStaleRevision:
    def test_stale_revision_conflicts_after_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, rev = _ready_project(root, client, headers)
            _post_command(
                client,
                headers,
                project_id,
                _command_body({"type": "add_marker", "position_frames": 10}, rev),
            )

        with _app(root) as (client, headers):
            # A client that never saw the marker's revision must be rejected.
            resp = client.post(
                f"/api/v1/projects/{project_id}/commands",
                json=_command_body({"type": "add_marker", "position_frames": 20}, rev),
                headers=headers,
            )
            assert resp.status_code == 409
            assert resp.json()["error"]["code"] == "STALE_REVISION"

            data = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            assert data["revision"] == rev + 1
            assert len(data["markers"]) == 1

            # The current revision is still accepted.
            resp = client.post(
                f"/api/v1/projects/{project_id}/commands",
                json=_command_body({"type": "add_marker", "position_frames": 20}, rev + 1),
                headers=headers,
            )
            assert resp.status_code == 200, resp.text


class TestInterruptedJobRecovery:
    def test_interrupted_job_marked_on_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id = _make_project(client, headers)
            # Simulate a crash mid-decode: a job left in the running state.
            jobs = JobRepository(_db_path(root))
            job = jobs.create_job(uuid.UUID(project_id), JobType.CANONICAL_DECODE)
            conn = sqlite3.connect(str(_db_path(root)))
            try:
                conn.execute(
                    "UPDATE media_jobs SET state = 'running' WHERE id = ?", (str(job.id),)
                )
                conn.commit()
            finally:
                conn.close()

        with _app(root) as (client, headers):
            resp = client.get(f"/api/v1/jobs/{job.id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["state"] == "interrupted"


class TestOriginalFileImmutability:
    def test_original_file_unchanged_across_restart(self, root: Path) -> None:
        with _app(root) as (client, headers):
            project_id, _ = _ready_project(root, client, headers)
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            original_path = _asset_path(root, project["source_asset_id"])
            original_sha = _file_sha256(original_path)
            original_mtime = original_path.stat().st_mtime

        with _app(root) as (client, headers):
            project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
            path = _asset_path(root, project["source_asset_id"])
            assert _file_sha256(path) == original_sha
            assert path.stat().st_mtime == original_mtime
