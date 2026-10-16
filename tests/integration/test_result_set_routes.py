"""Integration tests for the result-set routes (M2.8, spec §10.1.6).

Covers the read-only list and detail endpoints
(``GET /api/v1/projects/{id}/result-sets[/{id}]``: happy path, missing
set, foreign project, missing project) and the ``set_playback_mode`` 409
mapping at the command endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SourceIdentity,
    StemRecord,
    StemRole,
)
from basseparate.storage import SeparationRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64
DURATION = 100_000


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


@pytest.fixture()
def separation(app) -> SeparationRepository:
    return SeparationRepository(app.state.storage_paths.database_path)


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


def _result_set_with_stems(
    separation: SeparationRepository, project_id: uuid.UUID
) -> uuid.UUID:
    run = SeparationRun(
        id=uuid4(),
        project_id=project_id,
        input_asset_id=uuid4(),
        input_transform_hash=HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid4(),
        model_manifest_hash=HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
    )
    separation.create_run(run)
    result_set = SeparationResultSet(
        id=uuid4(),
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid4(), source_hash=HASH, sample_rate=48_000, duration_frames=DURATION
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=DURATION,
        available_stem_roles=[StemRole.BASS, StemRole.OTHER],
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid4(), hash=HASH, transformation_hash=HASH
        ),
        created_at=NOW,
        cache_key=HASH,
    )
    separation.create_result_set(result_set)
    for role, name in ((StemRole.BASS, "Bass"), (StemRole.OTHER, "Other")):
        separation.create_stem(
            StemRecord(
                id=uuid4(),
                result_set_id=result_set.id,
                role=role,
                display_name=name,
                audio_asset_id=uuid4(),
                sample_rate=48_000,
                channel_count=2,
                frame_count=DURATION,
                confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
            )
        )
    return result_set.id


class TestResultSetDetailRoute:
    def test_detail_happy_path(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        separation: SeparationRepository,
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        rs_id = _result_set_with_stems(separation, uuid.UUID(project_id))

        resp = client.get(
            f"/api/v1/projects/{project_id}/result-sets/{rs_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(rs_id)
        assert body["validation_status"] == "pending"
        assert body["cache_key"] == HASH
        assert body["created_at"] == NOW.isoformat().replace("+00:00", "Z")
        # Provenance comes from the completing run.
        assert body["engine_version"] == "demucs-4.1.0"
        assert body["adapter_version"] == "adapter-1"
        assert body["model_manifest_hash"] == HASH
        assert len(body["model_manifest_id"]) == 36
        # Stems carry the fields the track stack needs.
        roles = {stem["role"] for stem in body["stems"]}
        assert roles == {"bass", "other"}
        for stem in body["stems"]:
            assert stem["sample_rate"] == 48_000
            assert stem["channel_count"] == 2
            assert stem["frame_count"] == DURATION
            assert stem["display_name"]
            assert len(stem["audio_asset_id"]) == 36

    def test_missing_set_is_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        resp = client.get(
            f"/api/v1/projects/{project_id}/result-sets/{uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_SET_NOT_FOUND"

    def test_foreign_project_set_is_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        separation: SeparationRepository,
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        other_id = _create_project(client, auth_headers, "Q")
        foreign_rs = _result_set_with_stems(separation, uuid.UUID(other_id))

        resp = client.get(
            f"/api/v1/projects/{project_id}/result-sets/{foreign_rs}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_SET_NOT_FOUND"

    def test_missing_project_is_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f"/api/v1/projects/{uuid4()}/result-sets/{uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get(f"/api/v1/projects/{uuid4()}/result-sets/{uuid4()}")
        assert resp.status_code == 401


class TestResultSetListRoute:
    def test_list_empty_project(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        resp = client.get(f"/api/v1/projects/{project_id}/result-sets", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_summaries(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        separation: SeparationRepository,
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        first = _result_set_with_stems(separation, uuid.UUID(project_id))
        second = _result_set_with_stems(separation, uuid.UUID(project_id))

        resp = client.get(f"/api/v1/projects/{project_id}/result-sets", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert [s["id"] for s in body] == [str(first), str(second)]
        for summary in body:
            assert summary["validation_status"] == "pending"
            assert summary["available_stem_roles"] == ["bass", "other"]
            assert len(summary["created_at"]) > 0

    def test_list_excludes_foreign_project_sets(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        separation: SeparationRepository,
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        other_id = _create_project(client, auth_headers, "Q")
        _result_set_with_stems(separation, uuid.UUID(other_id))

        resp = client.get(f"/api/v1/projects/{project_id}/result-sets", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_missing_project_is_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(f"/api/v1/projects/{uuid4()}/result-sets", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_list_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get(f"/api/v1/projects/{uuid4()}/result-sets")
        assert resp.status_code == 401


class TestPlaybackModeCommandMapping:
    def test_stem_mode_without_set_is_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        resp = client.post(
            f"/api/v1/projects/{project_id}/commands",
            json={
                "command_id": str(uuid4()),
                "idempotency_key": "mode-1",
                "base_revision": 0,
                "op": {"type": "set_playback_mode", "mode": "bass_pair"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PLAYBACK_MODE_REQUIRES_RESULT_SET"

    def test_stem_mode_with_active_set_succeeds(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        separation: SeparationRepository,
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        rs_id = _result_set_with_stems(separation, uuid.UUID(project_id))

        resp = client.post(
            f"/api/v1/projects/{project_id}/commands",
            json={
                "command_id": str(uuid4()),
                "idempotency_key": "select-1",
                "base_revision": 0,
                "op": {"type": "set_active_result_set", "result_set_id": str(rs_id)},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        revision = resp.json()["revision"]

        resp = client.post(
            f"/api/v1/projects/{project_id}/commands",
            json={
                "command_id": str(uuid4()),
                "idempotency_key": "mode-2",
                "base_revision": revision,
                "op": {"type": "set_playback_mode", "mode": "four_stems"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["practice_state"]["playback_mode"] == "four_stems"

    def test_mixer_ops_round_trip_through_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        revision = 0
        for idem, op in (
            ("mix-1", {"type": "set_track_settings", "stem_role": "bass", "gain": 0.5}),
            (
                "mix-2",
                {
                    "type": "set_track_settings",
                    "stem_role": "bass",
                    "mute": True,
                    "color": "#ABC123",
                },
            ),
            ("mix-3", {"type": "set_master_gain", "gain": 3.5}),
            ("mix-4", {"type": "set_monitoring_limiter", "enabled": False}),
        ):
            resp = client.post(
                f"/api/v1/projects/{project_id}/commands",
                json={
                    "command_id": str(uuid4()),
                    "idempotency_key": idem,
                    "base_revision": revision,
                    "op": op,
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200, resp.text
            revision = resp.json()["revision"]

        state = resp.json()["practice_state"]
        track = state["tracks"]["bass"]
        assert track["gain"] == 0.5
        assert track["mute"] is True
        assert track["color"] == "#ABC123"
        assert track["solo"] is False
        assert state["master_gain"] == 3.5
        assert state["monitoring_limiter"] is False

    def test_track_settings_without_fields_is_422(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        project_id = _create_project(client, auth_headers, "P")
        resp = client.post(
            f"/api/v1/projects/{project_id}/commands",
            json={
                "command_id": str(uuid4()),
                "idempotency_key": "empty-patch",
                "base_revision": 0,
                "op": {"type": "set_track_settings", "stem_role": "bass"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422
