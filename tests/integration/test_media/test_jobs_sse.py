"""Jobs over HTTP: SSE progress, terminal frames and cancellation under 2 s."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from helpers import TONE_44K, import_path

from basseparate.jobs import JobContext


def register_test_jobs(app) -> None:
    manager = app.state.jobs

    def steps(ctx: JobContext, params: dict) -> dict:
        for step in range(3):
            time.sleep(0.05)
            ctx.progress((step + 1) / 3, f"step {step}")
        return {"answer": 42}

    def cooperative(ctx: JobContext, params: dict) -> None:
        while True:
            ctx.check_cancelled()
            ctx.progress(0.5, "waiting for cancel")
            time.sleep(0.02)

    manager.register("steps", steps)
    manager.register("cooperative", cooperative)


def read_sse(client: TestClient, url: str) -> list[str]:
    with client.stream("GET", url) as response:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        return list(response.iter_lines())


def test_job_endpoint_reports_progress_over_sse(client: TestClient, app) -> None:
    register_test_jobs(app)
    created = client.post("/api/jobs", json={"kind": "steps", "params": {}})
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    lines = read_sse(client, f"/api/jobs/{job_id}/events")
    body = "\n".join(lines)
    assert "event: progress" in body
    assert "event: done" in body
    assert '"state": "succeeded"' in body
    assert '"result": {"answer": 42}' in body
    snapshot = client.get(f"/api/jobs/{job_id}").json()
    assert snapshot["state"] == "succeeded"
    assert snapshot["progress"] == 1.0


def test_cooperative_job_cancels_within_two_seconds(client: TestClient, app) -> None:
    register_test_jobs(app)
    created = client.post("/api/jobs", json={"kind": "cooperative"})
    assert created.status_code == 202
    job_id = created.json()["id"]

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if client.get(f"/api/jobs/{job_id}").json()["progress"] > 0:
            break
        time.sleep(0.01)
    request_time = time.monotonic()
    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    while time.monotonic() - request_time < 2.0:
        state = client.get(f"/api/jobs/{job_id}").json()["state"]
        if state in {"cancelled", "failed", "succeeded"}:
            break
        time.sleep(0.01)
    assert state == "cancelled"
    assert time.monotonic() - request_time < 2.0

    # The stream after cancellation still terminates with a done frame.
    body = "\n".join(read_sse(client, f"/api/jobs/{job_id}/events"))
    assert "event: done" in body
    assert '"state": "cancelled"' in body


def test_import_as_a_background_job_creates_the_project(client: TestClient, app) -> None:
    created = client.post(
        "/api/jobs",
        json={"kind": "import", "params": {"path": str(TONE_44K), "name": "Job import"}},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    body = "\n".join(read_sse(client, f"/api/jobs/{job_id}/events"))
    assert '"state": "succeeded"' in body
    result = client.get(f"/api/jobs/{job_id}").json()["result"]
    project = client.get(f"/api/projects/{result['id']}").json()
    assert project["name"] == "Job import"
    assert project["audio"]["sample_rate"] == 44_100


def test_unknown_job_kind_is_a_clear_400(client: TestClient) -> None:
    response = client.post("/api/jobs", json={"kind": "does-not-exist"})
    assert response.status_code == 400
    assert "unknown job kind" in response.json()["detail"]
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/missing/events").status_code == 404


def test_job_listing(client: TestClient, app) -> None:
    register_test_jobs(app)
    first = client.post("/api/jobs", json={"kind": "steps"}).json()
    assert first["id"]
    listing = client.get("/api/jobs").json()["jobs"]
    assert any(job["id"] == first["id"] for job in listing)


def test_sync_import_still_available_while_jobs_run(client: TestClient, app) -> None:
    register_test_jobs(app)
    client.post("/api/jobs", json={"kind": "steps"})
    payload = import_path(client, TONE_44K, name="Sync while job runs")
    assert payload["name"] == "Sync while job runs"
