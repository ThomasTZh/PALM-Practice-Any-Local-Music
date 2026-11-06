"""Setup HTTP surface with local fake downloader, uv and tool installer."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import RuntimePaths, Settings
from basseparate.setup.service import SetupService

PAYLOAD = b"setup fake model"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def make_runtime(tmp_path: Path) -> RuntimePaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    (app / "analysis").mkdir(parents=True)
    (app / "analysis" / "envs" / "cpu").mkdir(parents=True)
    (app / "analysis" / "envs" / "cuda").mkdir(parents=True)
    (app / "scripts").mkdir(parents=True)
    return RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)


def write_registry(runtime: RuntimePaths) -> None:
    entry = {
        "id": "fake-model",
        "name": "Fake model",
        "engine": "msst",
        "engine_command": "echo",
        "labels": ["bass", "other"],
        "sample_rate": 44100,
        "size_bytes": len(PAYLOAD),
        "source_url": "https://example.invalid/model",
        "license": "test licence",
        "install_dir": "models/fake-model",
        "files": [
            {
                "role": "checkpoint",
                "name": "model.ckpt",
                "url": "https://example.invalid/model.ckpt",
                "size_bytes": len(PAYLOAD),
                "sha256": SHA,
            }
        ],
    }
    runtime.registry_path.write_text(
        json.dumps({"schema_version": 2, "models": [entry]}), encoding="utf-8"
    )


def fake_fetch(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(PAYLOAD)


def fake_uv(command: list[str], env: dict[str, str], cwd: Path) -> None:
    target = Path(env["UV_PROJECT_ENVIRONMENT"])
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "python").write_text("python", encoding="utf-8")


def fake_tools(runtime: RuntimePaths, progress, cancel) -> None:
    piper = runtime.tools_root / "sv/squashfs-root/usr/bin/piper-vamp-simple-server"
    piper.parent.mkdir(parents=True)
    piper.write_text("piper", encoding="utf-8")
    plugin = runtime.tools_root / "vamp-plugins/qm-vamp-plugins.so"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("plugin", encoding="utf-8")


def make_client(tmp_path: Path) -> tuple[TestClient, RuntimePaths, SetupService]:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    service = SetupService(
        runtime,
        fetch=fake_fetch,
        run_uv=fake_uv,
        tool_installer=fake_tools,
        which=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
        disk_probe=lambda _root: type("Usage", (), {"free": 10 * 1024**3})(),
    )
    settings = Settings(data_dir=runtime.data_root, web_dir=runtime.web_dir)
    return TestClient(create_app(settings, setup_service=service)), runtime, service


def wait_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    job: dict = {}
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job.get("state") in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not finish: {job}")


def test_status_is_local_and_reports_equal_models(tmp_path: Path) -> None:
    client, runtime, _service = make_client(tmp_path)
    with client:
        response = client.get("/api/setup/status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "packaged"
    assert body["roots"]["data_root"] == str(runtime.data_root)
    assert set(body["checks"]) == {"glibc", "disk", "ffmpeg"}
    assert body["checks"]["ffmpeg"]["ok"] is True
    assert set(body["environments"]) == {"cpu", "cuda"}
    assert [model["id"] for model in body["models"]] == ["fake-model"]
    assert body["readiness"]["ready"] is False
    assert body["skipped"] is False


def test_setup_jobs_require_consent_and_persist_state(tmp_path: Path) -> None:
    client, runtime, _service = make_client(tmp_path)
    with client:
        denied = client.post(
            "/api/setup/models",
            json={"model_ids": ["fake-model"], "accept_licenses": False},
        )
        assert denied.status_code == 400
        assert "licence" in denied.json()["detail"].lower()
        assert not runtime.setup_state.exists()

        accepted = client.post(
            "/api/setup/models",
            json={
                "model_ids": ["fake-model"],
                "accept_licenses": True,
                "accepted_model_ids": ["fake-model"],
            },
        )
        assert accepted.status_code == 202
        job = wait_job(client, accepted.json()["id"])
        assert job["state"] == "succeeded", job
        assert job["result"]["models"][0]["status"] == "installed"
        assert (runtime.models_root / "models/fake-model/model.ckpt").is_file()

        env = client.post(
            "/api/setup/environments",
            json={"variant": "cpu", "accept_licenses": True},
        )
        assert env.status_code == 202
        env_job = wait_job(client, env.json()["id"])
        assert env_job["state"] == "succeeded", env_job
        assert (runtime.data_root / "environments/cpu/bin/python").is_file()

        tools = client.post("/api/setup/tools", json={"accept_licenses": True})
        assert tools.status_code == 202
        tools_job = wait_job(client, tools.json()["id"])
        assert tools_job["state"] == "succeeded", tools_job
        assert (runtime.tools_root / "vamp-plugins/qm-vamp-plugins.so").is_file()

        status = client.get("/api/setup/status").json()
        assert status["readiness"]["model_ready"] is True
        assert status["readiness"]["environment_ready"] is True
        assert status["tools"]["sonic_visualiser"]["installed"] is True

    state = json.loads(runtime.setup_state.read_text(encoding="utf-8"))
    assert state["models_completed"] is True
    assert state["environments_completed"] is True
    assert state["tools_completed"] is True
    assert runtime.setup_state.is_relative_to(runtime.data_root)


def test_tools_and_models_reject_unknown_or_unconsented(tmp_path: Path) -> None:
    client, _runtime, _service = make_client(tmp_path)
    with client:
        assert client.post("/api/setup/tools", json={}).status_code == 400
        unknown = client.post(
            "/api/setup/models",
            json={
                "model_ids": ["missing"],
                "accept_licenses": True,
                "accepted_model_ids": ["missing"],
            },
        )
        assert unknown.status_code == 400
        assert "setup" in unknown.json()["detail"].lower()
        bad_variant = client.post("/api/setup/environments", json={"variants": ["tpu"]})
        assert bad_variant.status_code == 422


def test_skip_state_persists_and_is_reported(tmp_path: Path) -> None:
    client, runtime, _service = make_client(tmp_path)
    with client:
        skipped = client.post("/api/setup/skip", json={"skip": True})
        assert skipped.status_code == 200
        assert skipped.json()["skipped"] is True
    assert json.loads(runtime.setup_state.read_text())["skipped"] is True


def test_default_source_status_lists_three_equal_models(tmp_path: Path) -> None:
    from basseparate.app import create_app
    from basseparate.config import Settings

    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web")
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/setup/status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "source"
    assert [model["id"] for model in body["models"]] == [
        "htdemucs_ft",
        "scnet-xl-ihf",
        "bs-roformer-sw",
    ]
    assert all("default" not in model for model in body["models"])
    assert set(body["environments"]) == {"cpu", "cuda"}
    assert body["checks"]["glibc"]["ok"] is True
    assert body["checks"]["disk"]["ok"] is True


def test_setup_tool_job_can_be_cancelled(tmp_path: Path) -> None:
    client, _runtime, service = make_client(tmp_path)

    def slow_tools(runtime, progress, cancel) -> None:
        while not cancel():
            time.sleep(0.01)

    service.tool_installer = slow_tools
    with client:
        created = client.post("/api/setup/tools", json={"accept_licenses": True})
        assert created.status_code == 202
        job_id = created.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] == "running":
                break
            time.sleep(0.01)
        cancel = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel.status_code == 200
        job = wait_job(client, job_id)
        assert job["state"] == "cancelled"


def test_environment_consent_is_required_before_queueing(tmp_path: Path) -> None:
    client, runtime, _service = make_client(tmp_path)
    with client:
        rejected = client.post("/api/setup/environments", json={"variant": "cpu"})
        assert rejected.status_code == 400
        assert "licence" in rejected.json()["detail"].lower()
        assert not runtime.setup_state.exists()
        assert not (runtime.data_root / "environments").exists()
        assert client.get("/api/setup/status").json()["environments"]["cpu"]["installed"] is False
        accepted = client.post(
            "/api/setup/environments",
            json={"variant": "cpu", "accept_licenses": True},
        )
        assert accepted.status_code == 202


def test_each_requested_model_needs_its_own_acceptance(tmp_path: Path) -> None:
    client, runtime, _service = make_client(tmp_path)
    with client:
        blanket = client.post(
            "/api/setup/models",
            json={"model_ids": ["fake-model"], "accept_licenses": True},
        )
        assert blanket.status_code == 400
        assert "fake-model" in blanket.json()["detail"]
        default_all = client.post("/api/setup/models", json={"accept_licenses": True})
        assert default_all.status_code == 400
        partial = client.post(
            "/api/setup/models",
            json={
                "model_ids": ["fake-model"],
                "accept_licenses": True,
                "accepted_model_ids": [],
            },
        )
        assert partial.status_code == 400
        accepted = client.post(
            "/api/setup/models",
            json={
                "model_ids": ["fake-model"],
                "accept_licenses": True,
                "accepted_model_ids": ["fake-model"],
            },
        )
        assert accepted.status_code == 202
        job = wait_job(client, accepted.json()["id"])
        assert job["state"] == "succeeded", job
