"""A relative --storage-root must still produce absolute worker paths.

Regression: launching `serve --storage-root storage/...` created relative
staging/source paths; the worker's RunPayload rejected them with
``path must be absolute`` and every import decode failed.
"""

from __future__ import annotations

import hashlib
import io
import time
import wave

from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import resolve_config

BASE_URL = "http://127.0.0.1:8765"


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(b"\x00\x00" * 2 * 4_800)
    return buffer.getvalue()


def test_relative_storage_root_decodes_canonical_audio(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "store").mkdir()
    app = create_app(resolve_config(env={}, cli={"storage_root": "store"}))
    with TestClient(app, base_url=BASE_URL) as client:
        auth = {"Authorization": f"Bearer {app.state.session_token}"}
        project = client.post("/api/v1/projects", json={"name": "Relative"}, headers=auth).json()
        data = _wav_bytes()
        session = client.post(
            "/api/v1/imports",
            json={
                "project_id": project["id"],
                "filename": "tone.wav",
                "declared_byte_count": len(data),
            },
            headers=auth,
        ).json()
        upload = client.put(
            f"/api/v1/imports/{session['import_id']}/chunks",
            params={"offset": 0},
            content=data,
            headers={
                **auth,
                "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
                "Content-Type": "application/octet-stream",
            },
        )
        assert upload.status_code == 200, upload.text
        completed = client.post(
            f"/api/v1/imports/{session['import_id']}/complete", headers=auth
        )
        assert completed.status_code == 200, completed.text
        job = client.post(
            f"/api/v1/projects/{project['id']}/jobs",
            json={"import_id": session["import_id"], "job_type": "canonical_decode"},
            headers=auth,
        )
        assert job.status_code == 201, job.text

        deadline = time.monotonic() + 60
        state = None
        while time.monotonic() < deadline:
            state = client.get(f"/api/v1/jobs/{job.json()['id']}", headers=auth).json()
            if state["state"] in {"completed", "failed", "interrupted", "cancelled"}:
                break
            time.sleep(0.2)

        assert state is not None
        assert state["state"] == "completed", state
        project = client.get(f"/api/v1/projects/{project['id']}", headers=auth).json()
        assert project["status"] == "ready"
        assert project["canonical_asset_id"] is not None
