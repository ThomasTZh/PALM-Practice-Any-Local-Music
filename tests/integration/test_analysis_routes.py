"""Analysis, model, and separation-run routes (M2.17, spec §19).

HTTP surface: run requests with cache/coalescing/device rules, the
spec-named result-set listing, hardware qualification state, model
listing, and local bundle verification. Separation execution is faked:
the analysis worker path is covered by its own tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from basseparate.api import analysis_routes
from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.devices import QualificationStore, record_qualification
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.storage import SeparationRepository
from tests.unit.portable_seed import create_seed_files, seed_two_projects

BASE_URL = "http://127.0.0.1:8765"
MODEL_ID = "htdemucs_ft"


class FakeManager:
    """Records separation jobs without executing them."""

    def __init__(self) -> None:
        self.created: list[tuple[uuid.UUID, JobType, dict]] = []
        self.live_job: MediaJob | None = None

    async def create_job(self, project_id, job_type, **kwargs):
        self.created.append((project_id, job_type, kwargs))
        now = datetime.now(UTC)
        self.live_job = MediaJob(
            id=uuid.uuid4(),
            project_id=project_id,
            job_type=job_type,
            state=JobState.QUEUED,
            parameters=kwargs.get("parameters", {}),
            created_at=now,
            updated_at=now,
        )
        return self.live_job

    async def list_project_jobs(self, project_id):
        return [self.live_job] if self.live_job is not None else []


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
    return seed


@pytest.fixture()
def fake_manager(app, monkeypatch: pytest.MonkeyPatch) -> FakeManager:
    manager = FakeManager()
    monkeypatch.setattr(app.state, "job_manager", manager)
    return manager


@pytest.fixture()
def gpu_qualified(app):
    store = QualificationStore(
        app.state.storage_paths.state / "analysis" / "devices.json"
    )
    record_qualification(store, "GPU-QUALIFIED", True, "test qualification")


class TestHardwareRoute:
    def test_default_selection_prefers_the_first_qualified_gpu(
        self, client, auth_headers, app, gpu_qualified, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            analysis_routes,
            "discover_gpus",
            lambda: [
                SimpleNamespace(
                    uuid="GPU-UNTESTED",
                    name="RTX Untested",
                    vram_total_mib=16_000,
                    vram_free_mib=15_000,
                ),
                SimpleNamespace(
                    uuid="GPU-QUALIFIED",
                    name="RTX Qualified",
                    vram_total_mib=16_000,
                    vram_free_mib=14_000,
                ),
            ],
        )
        body = client.get("/api/v1/hardware", headers=auth_headers).json()
        assert [device["identifier"] for device in body["devices"]] == [
            "GPU-UNTESTED",
            "GPU-QUALIFIED",
            "cpu",
        ]
        assert body["selected"]["identifier"] == "GPU-QUALIFIED"
        assert body["cpu_offered"] is False

    def test_no_gpu_offers_the_cpu_explicitly(
        self, client, auth_headers, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        body = client.get("/api/v1/hardware", headers=auth_headers).json()
        assert [device["kind"] for device in body["devices"]] == ["cpu"]
        assert body["selected"] is None
        assert body["cpu_offered"] is True


class TestModelRoutes:
    def test_models_list_the_registry(self, client, auth_headers) -> None:
        body = client.get("/api/v1/models", headers=auth_headers).json()
        assert [model["model_id"] for model in body["models"]] == [MODEL_ID]
        model = body["models"][0]
        assert model["bundle_state"] in {"available", "missing", "corrupt"}
        assert model["qualification_status"] == "not-qualified"
        assert model["last_verification"] is None

    def test_verify_records_the_result(
        self, client, auth_headers, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            analysis_routes,
            "default_bundle_dir",
            lambda manifest: tmp_path / "absent",
        )
        body = client.post(
            f"/api/v1/models/{MODEL_ID}/verify", headers=auth_headers
        ).json()
        assert body["state"] == "missing"
        assert body["missing"]

        listed = client.get("/api/v1/models", headers=auth_headers).json()
        model = listed["models"][0]
        assert model["last_verification"]["state"] == "missing"

    def test_unknown_model_is_404(self, client, auth_headers) -> None:
        response = client.post(
            "/api/v1/models/unknown/verify", headers=auth_headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


class TestRunRoutes:
    def test_run_requires_a_ready_project(self, client, auth_headers, fake_manager) -> None:
        project = client.post(
            "/api/v1/projects", headers=auth_headers, json={"name": "Empty"}
        ).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_explicit_cpu_creates_a_run_and_job(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        response = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu", "mode": "bass_pair", "seed": 9},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["run_id"] is not None
        assert body["job_id"] is not None
        assert body["device"] == "cpu"
        assert not body["cached"] and not body["coalesced"]
        assert len(fake_manager.created) == 1
        project_id, job_type, kwargs = fake_manager.created[0]
        assert project_id == uuid.UUID(seeded.project_a)
        assert job_type is JobType.SEPARATION
        assert kwargs["parameters"]["run_id"] == body["run_id"]

        db = client.app.state.storage_paths.database_path
        run = SeparationRepository(db).get_run(uuid.UUID(body["run_id"]))
        assert run is not None
        assert run.requested_mode.value == "bass_pair"
        assert run.random_seed == 9
        assert run.cache_key is not None
        assert run.input_transform_hash

    def test_no_qualified_device_is_409(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        response = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "NO_QUALIFIED_DEVICE"
        assert error["details"]["cpu_offered"] is True

    def test_unknown_gpu_is_rejected(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        response = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "GPU-MISSING"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEVICE_UNAVAILABLE"

    def test_live_run_is_coalesced(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        first = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        second = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["coalesced"] is True
        assert second.json()["run_id"] == first.json()["run_id"]
        assert second.json()["job_id"] == first.json()["job_id"]
        assert len(fake_manager.created) == 1

    def test_stale_run_is_failed_and_replaced(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        first = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        fake_manager.live_job = None  # the job vanished
        second = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        assert second.status_code == 201
        assert second.json()["run_id"] != first.json()["run_id"]
        db = client.app.state.storage_paths.database_path
        old = SeparationRepository(db).get_run(uuid.UUID(first.json()["run_id"]))
        assert old is not None
        assert old.status.value == "failed"

    def test_cache_hit_returns_the_result_without_a_job(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        result_set_id = uuid.uuid4()
        monkeypatch.setattr(
            analysis_routes,
            "lookup_cached_result",
            lambda **kwargs: SimpleNamespace(id=result_set_id),
        )
        response = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["cached"] is True
        assert body["result_set_id"] == str(result_set_id)
        assert body["job_id"] is None
        assert fake_manager.created == []

    def test_save_is_consistent_while_a_separation_is_queued(
        self, client, auth_headers, seeded, fake_manager, monkeypatch
    ) -> None:
        """A portable save captures the committed state (spec §20.7.3).

        The separation job is queued in the analysis class; the save runs
        on a read-only snapshot and must return the current revision with
        a valid archive.
        """
        import zipfile

        from basseparate.portable.format import PortableManifest

        monkeypatch.setattr(analysis_routes, "discover_gpus", lambda: [])
        run = client.post(
            f"/api/v1/projects/{seeded.project_a}/runs",
            headers=auth_headers,
            json={"device": "cpu"},
        )
        assert run.status_code == 201, run.text

        saved = client.post(
            f"/api/v1/projects/{seeded.project_a}/portable-saves",
            headers=auth_headers,
        )
        assert saved.status_code == 201, saved.text
        body = saved.json()
        assert body["saved_revision"] == 5
        paths = client.app.state.storage_paths
        archive = (
            paths.data
            / "portable"
            / seeded.project_a
            / f"{body['saved_revision']}-{body['sha256'][:12]}.basseparate"
        )
        assert archive.is_file()
        with zipfile.ZipFile(archive) as zf:
            assert zf.testzip() is None
            manifest = PortableManifest.model_validate_json(
                zf.read("manifest.json").decode("utf-8")
            )
        assert manifest.saved_revision == 5

    def test_separation_results_alias(self, client, auth_headers, seeded) -> None:
        response = client.get(
            f"/api/v1/projects/{seeded.project_a}/separation-results",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [seeded.rs_a]
