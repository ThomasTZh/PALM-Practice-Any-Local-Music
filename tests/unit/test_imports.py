"""Tests for the M1.2 bounded local file transfer and M1.3 probe integration."""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from synth import wav_s16_bytes

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config

BASE_URL = "http://127.0.0.1:8765"

# A 1x1 PNG: a valid container with no audio streams.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


#: 100 ms of 44.1 kHz mono silence as a 16-bit PCM WAV (probe/decode input).
_SILENT_WAV = wav_s16_bytes(b"\x00\x00" * 4410, 44100)


def _make_multi_audio_file(tmp_path: Path) -> bytes:
    """Build a Matroska file with two audio streams using ffmpeg."""
    out = tmp_path / "multi.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "quiet",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=0.2",
            "-map",
            "0:a",
            "-map",
            "1:a",
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        check=True,
    )
    return out.read_bytes()


@pytest.fixture()
def config(tmp_path) -> AppConfig:
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


def _make_project(client: TestClient, headers: dict) -> str:
    resp = client.post("/api/v1/projects", json={"name": "Import Target"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _make_import(
    client: TestClient,
    headers: dict,
    project_id: str,
    size: int = 100_000,
    filename: str = "take.wav",
) -> dict:
    resp = client.post(
        "/api/v1/imports",
        json={"project_id": project_id, "filename": filename, "declared_byte_count": size},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_chunks(
    client: TestClient,
    headers: dict,
    import_id: str,
    data: bytes,
    chunk_size: int,
) -> list[dict]:
    acks = []
    for offset in range(0, len(data), chunk_size):
        chunk = data[offset : offset + chunk_size]
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": offset},
            content=chunk,
            headers={**headers, "X-Chunk-SHA256": _sha256(chunk)},
        )
        assert resp.status_code == 200, resp.text
        acks.append(resp.json())
    return acks


class TestCreateImport:
    def test_create_session(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = _make_import(client, auth_headers, project_id, size=1234)
        assert data["project_id"] == project_id
        assert data["chunk_size"] == 8 * 1024 * 1024
        assert data["max_import_bytes"] == 20 * 1024**3
        assert data["state"] == "created"

    def test_create_requires_auth(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            "/api/v1/imports",
            json={"project_id": project_id, "filename": "a.wav", "declared_byte_count": 10},
        )
        assert resp.status_code == 401

    def test_create_unknown_project(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            "/api/v1/imports",
            json={
                "project_id": str(uuid.uuid4()),
                "filename": "a.wav",
                "declared_byte_count": 10,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_create_rejects_non_empty_project(self, client: TestClient, auth_headers: dict) -> None:
        import sqlite3

        project_id = _make_project(client, auth_headers)
        # Model a populated project (M1.4 flips the status when a source
        # asset is attached); imports must then be refused.
        db = client.app.state.storage_paths.database_path
        src_id = str(uuid.uuid4())
        canon_id = str(uuid.uuid4())
        with sqlite3.connect(db) as c:
            c.execute(
                "UPDATE projects SET status = 'ready', "
                "source_asset_id = ?, canonical_asset_id = ?, "
                "source_stream_index = 0, sample_rate = 44100, "
                "duration_frames = 1000, source_channel_count = 2, "
                "source_channel_layout = 'stereo', decode_profile_version = 1 "
                "WHERE id = ?",
                (src_id, canon_id, project_id),
            )
            c.commit()

        resp = client.post(
            "/api/v1/imports",
            json={"project_id": project_id, "filename": "b.wav", "declared_byte_count": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_EMPTY"

    def test_create_rejects_oversized_declaration(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            "/api/v1/imports",
            json={
                "project_id": project_id,
                "filename": "big.wav",
                "declared_byte_count": 20 * 1024**3 + 1,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "IMPORT_SIZE_LIMIT"

    def test_create_rejects_invalid_filename(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            "/api/v1/imports",
            json={
                "project_id": project_id,
                "filename": "bad\x00name.wav",
                "declared_byte_count": 10,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422


def app_db_path(client: TestClient):
    return client.app.state.storage_paths.database_path


class TestChunkUpload:
    def test_happy_path_multi_chunk(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = bytes(range(256)) * 700  # 179,200 bytes
        session = _make_import(client, auth_headers, project_id, size=len(data))
        import_id = session["import_id"]

        acks = _upload_chunks(client, auth_headers, import_id, data, chunk_size=64 * 1024)
        assert acks[0]["offset"] == 64 * 1024
        assert acks[-1]["offset"] == len(data)
        assert all(a["idempotent_replay"] is False for a in acks)

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["received_byte_count"] == len(data)
        assert state["transfer_state"] == "uploading"

    def test_repeated_identical_chunk_is_idempotent(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = b"y" * 1000
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]

        first = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=data,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(data)},
        )
        assert first.status_code == 200
        assert first.json()["offset"] == 1000

        # Retry the same chunk: same offset, same bytes.
        retry = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=data,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(data)},
        )
        assert retry.status_code == 200
        body = retry.json()
        assert body["idempotent_replay"] is True
        assert body["offset"] == 1000

    def test_repeated_offset_different_bytes_conflicts(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = b"y" * 1000
        import_id = _make_import(client, auth_headers, project_id, size=2000)["import_id"]

        first = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=data,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(data)},
        )
        assert first.status_code == 200

        other = b"z" * 1000
        conflict = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=other,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(other)},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "CHUNK_CONFLICT"

    def test_offset_beyond_expected_rejected(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=2000)["import_id"]

        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 500},
            content=b"a" * 500,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(b"a" * 500)},
        )
        assert resp.status_code == 400
        body = resp.json()["error"]
        assert body["code"] == "OFFSET_MISMATCH"
        assert body["details"]["expected_offset"] == 0

    def test_negative_offset_rejected(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=100)["import_id"]
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": -1},
            content=b"a",
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(b"a")},
        )
        assert resp.status_code == 400

    def test_oversized_body_rejected(self, client: TestClient, auth_headers: dict) -> None:
        # The import only needs to exist; its declared size is small so the
        # setup does not depend on the free disk space of the test volume.
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=16 * 1024**2)["import_id"]
        oversized = b"a" * (8 * 1024**2 + 16)  # exceeds 8 MiB chunk cap
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=oversized,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(oversized)},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "CHUNK_SIZE"

    def test_insufficient_disk_space_returns_507(
        self, client: TestClient, app, auth_headers: dict
    ) -> None:
        # Simulate a nearly-full upload volume so reserve() fails on space.
        app.state.upload_manager.free_bytes = lambda: 1024
        project_id = _make_project(client, auth_headers)
        resp = client.post(
            "/api/v1/imports",
            json={"project_id": project_id, "filename": "big.wav", "declared_byte_count": 100_000},
            headers=auth_headers,
        )
        assert resp.status_code == 507
        body = resp.json()["error"]
        assert body["code"] == "INSUFFICIENT_DISK_SPACE"
        assert body["details"]["free_bytes"] == 1024

    def test_missing_hash_header_rejected(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=10)["import_id"]
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=b"a" * 10,
            headers=auth_headers,
        )
        assert resp.status_code == 409

    def test_hash_mismatch_rolls_back(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=100)["import_id"]
        data = b"b" * 100
        # Declare the wrong hash on purpose.
        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=data,
            headers={**auth_headers, "X-Chunk-SHA256": "0" * 64},
        )
        assert resp.status_code == 409
        # The offset must not have advanced.
        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["received_byte_count"] == 0
        # A correct retry now succeeds.
        ok = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": 0},
            content=data,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(data)},
        )
        assert ok.status_code == 200
        assert ok.json()["offset"] == 100

    def test_unknown_import_404(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.put(
            f"/api/v1/imports/{uuid.uuid4()}/chunks",
            params={"offset": 0},
            content=b"a",
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(b"a")},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "IMPORT_NOT_FOUND"

    def test_chunks_rejected_after_completion(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = wav_s16_bytes(b"\x00\x00" * 32, 44100)
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 32)
        done = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert done.status_code == 200

        resp = client.put(
            f"/api/v1/imports/{import_id}/chunks",
            params={"offset": len(data)},
            content=b"d" * 8,
            headers={**auth_headers, "X-Chunk-SHA256": _sha256(b"d" * 8)},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IMPORT_STATE"


class TestCompleteImport:
    def test_complete_verifies_size_and_hashes(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = wav_s16_bytes(bytes(reversed(range(256))) * 166, 44100)
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 64 * 1024)

        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_sha256"] == _sha256(data)
        assert body["state"] == "complete"

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "complete"
        assert state["source_sha256"] == _sha256(data)

    def test_complete_before_all_bytes_rejected(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=1000)["import_id"]
        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IMPORT_STATE"

    def test_complete_twice_rejected(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = wav_s16_bytes(b"\x00\x00" * 16, 44100)
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 16)
        assert (
            client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers).status_code
            == 200
        )
        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 409


class TestCancelImport:
    def test_cancel_removes_temp_bytes(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = b"f" * 5000
        import_id = _make_import(client, auth_headers, project_id, size=10_000)["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 2500)

        resp = client.post(f"/api/v1/imports/{import_id}/cancel", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["state"] == "cancelled"

        uploads_dir = client.app.state.storage_paths.runtime / "uploads"
        part = uploads_dir / f"{import_id}.part"
        manifest = uploads_dir / f"{import_id}.manifest.json"
        assert not part.exists()
        assert not manifest.exists()

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "cancelled"
        assert state["error"] is not None

    def test_cancel_idempotent(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=100)["import_id"]
        first = client.post(f"/api/v1/imports/{import_id}/cancel", headers=auth_headers)
        assert first.status_code == 200
        second = client.post(f"/api/v1/imports/{import_id}/cancel", headers=auth_headers)
        assert second.status_code == 200
        assert second.json()["state"] == "cancelled"

    def test_cancel_completed_rejected(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        data = wav_s16_bytes(b"\x00\x00" * 8, 44100)
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 8)
        client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        resp = client.post(f"/api/v1/imports/{import_id}/cancel", headers=auth_headers)
        assert resp.status_code == 409

    def test_cancel_leaves_project_usable(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=100)["import_id"]
        client.post(f"/api/v1/imports/{import_id}/cancel", headers=auth_headers)

        # A fresh import into the same project succeeds.
        again = _make_import(client, auth_headers, project_id, size=100)
        assert again["state"] == "created"


class TestReloadRecovery:
    def test_list_project_imports(self, client: TestClient, auth_headers: dict) -> None:
        project_id = _make_project(client, auth_headers)
        a = _make_import(client, auth_headers, project_id, size=100)
        b = _make_import(client, auth_headers, project_id, size=200)

        resp = client.get(f"/api/v1/projects/{project_id}/imports", headers=auth_headers)
        assert resp.status_code == 200
        listed = resp.json()["imports"]
        assert {i["id"] for i in listed} == {a["import_id"], b["import_id"]}
        assert all(i["transfer_state"] == "created" for i in listed)

    def test_unknown_project_list_404(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/imports", headers=auth_headers)
        assert resp.status_code == 404

    def test_partial_state_survives_reopen(self, client: TestClient, auth_headers: dict) -> None:
        """The durable offset and chunk hashes persist across app instances."""
        project_id = _make_project(client, auth_headers)
        data = b"h" * 5000
        import_id = _make_import(client, auth_headers, project_id, size=10_000)["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 2500)
        client.close()

        # New application instance over the same storage root.
        from pathlib import Path

        from basseparate.app import create_app as _create
        from basseparate.config import resolve_config as _resolve

        root = Path(client.app.state.config.storage_root)  # type: ignore[arg-type]
        fresh = _create(_resolve(env={}, cli={"storage_root": str(root)}))
        with TestClient(fresh, base_url=BASE_URL) as c2:
            tok = fresh.state.session_token
            h = {"Authorization": f"Bearer {tok}"}
            state = c2.get(f"/api/v1/imports/{import_id}", headers=h).json()
            assert state["received_byte_count"] == 5000
            assert state["transfer_state"] == "uploading"

            # Resume: the next chunk goes at offset 5000.
            rest = data[2500:]
            resp = c2.put(
                f"/api/v1/imports/{import_id}/chunks",
                params={"offset": 2500},
                content=rest,
                headers={**h, "X-Chunk-SHA256": _sha256(rest)},
            )
            assert resp.status_code == 200
            assert resp.json()["offset"] == 5000

            # A replayed chunk from before the reload is still idempotent.
            first = data[:2500]
            replay = c2.put(
                f"/api/v1/imports/{import_id}/chunks",
                params={"offset": 0},
                content=first,
                headers={**h, "X-Chunk-SHA256": _sha256(first)},
            )
            assert replay.status_code == 200
            assert replay.json()["idempotent_replay"] is True


class TestConcurrency:
    def test_concurrent_chunks_do_not_interleave(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Two writers to the same import: exactly one advances the offset.

        The loser receives a clean offset-mismatch error instead of
        corrupted data.
        """
        import threading

        project_id = _make_project(client, auth_headers)
        chunk_a = b"AAA" * 1000
        chunk_b = b"BBB" * 1000
        import_id = _make_import(client, auth_headers, project_id, size=3000)["import_id"]

        results: dict[str, int] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, chunk: bytes) -> None:
            # TestClient runs its own portal; use a plain httpx call in a
            # dedicated client on the shared event loop is overkill here.
            # Instead synchronize both requests through the same client,
            # which serializes at the HTTP layer. To exercise the
            # in-process lock we issue both requests from two threads on
            # the same TestClient (starlette's portal is thread-safe).
            barrier.wait()
            resp = client.put(
                f"/api/v1/imports/{import_id}/chunks",
                params={"offset": 0},
                content=chunk,
                headers={**auth_headers, "X-Chunk-SHA256": _sha256(chunk)},
            )
            results[name] = resp.status_code

        threads = [
            threading.Thread(target=worker, args=("a", chunk_a)),
            threading.Thread(target=worker, args=("b", chunk_b)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        codes = sorted(results.values())
        assert codes == [200, 409]  # one ack, one chunk-conflict rejection

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["received_byte_count"] == 3000


def _complete_upload(
    client: TestClient,
    auth_headers: dict,
    project_id: str,
    data: bytes,
    filename: str = "take.wav",
) -> tuple[str, dict]:
    import_id = _make_import(client, auth_headers, project_id, size=len(data), filename=filename)[
        "import_id"
    ]
    _upload_chunks(client, auth_headers, import_id, data, 4096)
    resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return import_id, resp.json()


class TestProbeIntegration:
    def test_complete_single_stream_auto_selects(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = _SILENT_WAV
        import_id, body = _complete_upload(client, auth_headers, project_id, data)

        assert body["state"] == "complete"
        probe = body["probe_result"]
        assert probe["format_name"] == "wav"
        assert probe["byte_count"] == len(data)
        assert probe["ffmpeg_version"]
        assert probe["ffprobe_version"]
        assert len(probe["audio_streams"]) == 1
        stream = probe["audio_streams"][0]
        assert stream["index"] == 0
        assert stream["codec"] == "pcm_s16le"
        assert stream["sample_rate"] == 44100
        assert stream["channel_count"] == 1
        assert body["selected_stream_index"] == 0

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "complete"
        assert state["probe_result"]["format_name"] == "wav"
        assert state["selected_stream_index"] == 0

    def test_complete_multi_stream_defers_selection(
        self, client: TestClient, auth_headers: dict, tmp_path: Path
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = _make_multi_audio_file(tmp_path)
        _, body = _complete_upload(client, auth_headers, project_id, data)

        probe = body["probe_result"]
        assert len(probe["audio_streams"]) == 2
        assert body["selected_stream_index"] is None

    def test_select_stream_persists(
        self, client: TestClient, auth_headers: dict, tmp_path: Path
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = _make_multi_audio_file(tmp_path)
        import_id, _ = _complete_upload(client, auth_headers, project_id, data)

        resp = client.post(
            f"/api/v1/imports/{import_id}/select-stream",
            json={"stream_index": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["selected_stream_index"] == 1

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["selected_stream_index"] == 1

    def test_select_stream_invalid_index_rejected(
        self, client: TestClient, auth_headers: dict, tmp_path: Path
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = _make_multi_audio_file(tmp_path)
        import_id, _ = _complete_upload(client, auth_headers, project_id, data)

        resp = client.post(
            f"/api/v1/imports/{import_id}/select-stream",
            json={"stream_index": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_STREAM_SELECTION"
        assert resp.json()["error"]["details"]["available_streams"] == [0, 1]

    def test_select_stream_before_complete_rejected(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=1000)["import_id"]

        resp = client.post(
            f"/api/v1/imports/{import_id}/select-stream",
            json={"stream_index": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IMPORT_STATE"

    def test_complete_no_audio_stream_marks_failed(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=len(_PNG_BYTES))[
            "import_id"
        ]
        _upload_chunks(client, auth_headers, import_id, _PNG_BYTES, 1024)

        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "NO_AUDIO_STREAM"

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "failed"
        assert state["error"] is not None

    def test_complete_unsupported_sample_rate_marks_failed(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        data = wav_s16_bytes(b"\x00\x00" * 4410, 4000)
        import_id = _make_import(client, auth_headers, project_id, size=len(data))["import_id"]
        _upload_chunks(client, auth_headers, import_id, data, 4096)

        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA"

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "failed"


class TestFilenameEdgeCases:
    """Spec §18.3: unicode/space names, misleading extensions, duplicates."""

    def test_unicode_and_space_filename_round_trips(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        filename = "Töne & spaces (demo) — v2.wav"
        import_id, body = _complete_upload(client, auth_headers, project_id, _SILENT_WAV, filename)

        assert body["state"] == "complete"
        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["filename"] == filename

    def test_misleading_extension_reports_real_container(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        # Genuine WAV bytes under a .mp3 name: the probe must trust the
        # container bytes, not the filename.
        _, body = _complete_upload(client, auth_headers, project_id, _SILENT_WAV, "fake.mp3")

        assert body["probe_result"]["format_name"] == "wav"
        stream = body["probe_result"]["audio_streams"][0]
        assert stream["codec"] == "pcm_s16le"

    def test_duplicate_file_imports_independently(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        project_id = _make_project(client, auth_headers)
        first = _complete_upload(client, auth_headers, project_id, _SILENT_WAV, "copy-a.wav")
        second = _complete_upload(client, auth_headers, project_id, _SILENT_WAV, "copy-b.wav")

        assert first[0] != second[0]
        listing = client.get(
            f"/api/v1/projects/{project_id}/imports", headers=auth_headers
        ).json()["imports"]
        assert {i["id"] for i in listing} == {first[0], second[0]}
        assert all(i["transfer_state"] == "complete" for i in listing)


class TestProbeTimeout:
    """Spec §18.3: a hung ffprobe must fail the import, not hang it."""

    def test_complete_marks_failed_on_probe_timeout(
        self, client: TestClient, auth_headers: dict, tmp_path: Path, monkeypatch
    ) -> None:
        bin_dir = _install_fake_slow_ffprobe(tmp_path)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

        # The production timeout is 30 s; shorten it so the test stays fast
        # while still exercising the real subprocess + timeout machinery.
        import basseparate.api.import_routes as import_routes

        real_probe = import_routes.probe_media

        async def fast_probe(path, **kwargs):
            return await real_probe(path, timeout_seconds=0.5)

        monkeypatch.setattr(import_routes, "probe_media", fast_probe)

        project_id = _make_project(client, auth_headers)
        import_id = _make_import(client, auth_headers, project_id, size=len(_SILENT_WAV))[
            "import_id"
        ]
        _upload_chunks(client, auth_headers, import_id, _SILENT_WAV, 4096)

        resp = client.post(f"/api/v1/imports/{import_id}/complete", headers=auth_headers)
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "PROBE_TIMEOUT"

        state = client.get(f"/api/v1/imports/{import_id}", headers=auth_headers).json()
        assert state["transfer_state"] == "failed"
        assert state["error"] is not None


def _install_fake_slow_ffprobe(tmp_path: Path) -> Path:
    """Install a fake ``ffprobe`` on PATH that sleeps for 30 s on any probe.

    ``exec`` replaces the shell with sleep so SIGTERM reaches the sleeper
    directly (no orphaned child). ``-version`` answers immediately so
    ``tool_versions()`` works.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ffprobe"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-version" ]; then\n'
        '  echo "ffprobe version 6.0-fake"\n'
        "  exit 0\n"
        "fi\n"
        "exec sleep 30\n"
    )
    script.chmod(0o755)
    return bin_dir
