"""Real Piper analysis jobs through the shared JobManager and project store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate import features
from basseparate.app import create_app
from basseparate.config import Settings

from .conftest import (
    CHORDS,
    CLICK,
    TONE,
    import_audio,
    start_analysis,
    wait_job,
    write_long_wav,
)


def _analysis_count(client: TestClient, project_id: str) -> int:
    project = client.get(f"/api/projects/{project_id}").json()
    return 1 if "analysis" in project.get("document", {}) else 0


def test_click_and_chord_fixtures_produce_the_ui_contract(client: TestClient) -> None:
    for path, bpb, expected_key in (
        (CLICK, 4, None),
        (CHORDS, 4, "C major"),
    ):
        project = import_audio(client, path)
        job = wait_job(client, start_analysis(client, project["id"], bpb)["id"])
        assert job["state"] == "succeeded", job.get("error")
        result = job["result"]
        assert set(result) == {"cached", "bpb", "bpm", "key", "chords", "beats", "bars"}
        assert result["cached"] is False
        assert result["bpb"] == bpb
        assert result["bpm"] is not None and result["bpm"] > 0
        assert isinstance(result["beats"], list)
        assert isinstance(result["bars"], list)
        assert all(isinstance(value, (int, float)) for value in result["beats"])
        assert all(isinstance(value, (int, float)) for value in result["bars"])
        for chord in result["chords"]:
            assert set(chord) == {"start_seconds", "end_seconds", "label"}
        if path is CLICK:
            assert abs(result["bpm"] - 120.0) <= 0.5
            assert len(result["beats"]) == 8
            assert len(result["bars"]) == 2
        else:
            assert result["key"] == expected_key
            labels = [chord["label"] for chord in result["chords"] if chord["label"] != "N"]
            assert labels == ["C", "Am", "F", "G"]


def test_second_run_is_cached_and_starts_no_piper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = import_audio(client, CLICK)
    first = wait_job(client, start_analysis(client, project["id"], 4)["id"])
    assert first["state"] == "succeeded"
    assert first["result"]["cached"] is False

    class ExplodingSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("cached analysis must not start Piper")

    monkeypatch.setattr(features, "PiperSession", ExplodingSession)
    second = wait_job(client, start_analysis(client, project["id"], 4)["id"])
    assert second["state"] == "succeeded", second.get("error")
    assert second["result"]["cached"] is True
    for key in ("bpb", "bpm", "key", "chords", "beats", "bars"):
        assert second["result"][key] == first["result"][key]
    document = client.get(f"/api/projects/{project['id']}").json()["document"]
    assert document["analysis"]["cached"] is True


def test_project_document_survives_an_app_restart(client: TestClient, settings: Settings) -> None:
    project = import_audio(client, CHORDS)
    job = wait_job(client, start_analysis(client, project["id"], 4)["id"])
    assert job["state"] == "succeeded"
    saved = client.get(f"/api/projects/{project['id']}").json()
    assert saved["grid"]["bpb"] == 4
    assert saved["grid"]["beats"] == job["result"]["beats"]
    assert saved["grid"]["bars"] == job["result"]["bars"]
    assert saved["key"] == "C major"
    assert saved["document"]["chords"] == job["result"]["chords"]
    assert saved["document"]["analysis"]["cache_key"]
    assert saved["document"]["analysis"]["plugins"]

    restarted_app = create_app(settings)
    with TestClient(restarted_app) as restarted:
        reopened = restarted.get(f"/api/projects/{project['id']}").json()
    assert reopened["grid"] == saved["grid"]
    assert reopened["key"] == saved["key"]
    assert reopened["document"]["chords"] == saved["document"]["chords"]
    assert reopened["document"]["analysis"] == saved["document"]["analysis"]


def test_cancel_kills_the_run_and_keeps_the_previous_document(
    client: TestClient, tmp_path: Path
) -> None:
    source = write_long_wav(tmp_path / "long-click.wav", seconds=60.0)
    project = import_audio(client, source)
    revision = client.get(f"/api/projects/{project['id']}").json()["revision"]
    started = start_analysis(client, project["id"], 4)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        running = client.get(f"/api/jobs/{started['id']}").json()
        if running["progress"] >= 0.1:
            break
        if running["state"] in {"succeeded", "failed", "cancelled"}:
            pytest.fail(f"job ended before it could be cancelled: {running}")
        time.sleep(0.02)
    else:
        pytest.fail("analysis never reached 10% progress")
    cancel_started = time.perf_counter()
    client.post(f"/api/jobs/{started['id']}/cancel")
    finished = wait_job(client, started["id"], timeout=5.0)
    elapsed = time.perf_counter() - cancel_started
    assert finished["state"] == "cancelled", finished
    print(f"analysis cancellation terminal in {elapsed:.3f} s")
    assert elapsed < 2.0, f"cancellation took {elapsed:.3f} s"
    project_after = client.get(f"/api/projects/{project['id']}")
    assert project_after.status_code == 200
    assert project_after.json()["revision"] == revision
    assert "analysis" not in project_after.json()["document"]


def test_bad_params_missing_project_and_missing_pack_are_actionable(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = client.post(
        "/api/jobs",
        json={"kind": "analysis", "params": {"project_id": "does-not-exist", "bpb": 4}},
    )
    assert missing.status_code == 404, missing.text

    invalid = client.post(
        "/api/jobs",
        json={"kind": "analysis", "params": {"project_id": "does-not-exist", "bpb": 1}},
    )
    assert invalid.status_code == 400, invalid.text

    project = import_audio(client, TONE)
    revision = client.get(f"/api/projects/{project['id']}").json()["revision"]
    monkeypatch.setenv("BASSEPARATE_VAMP_PLUGINS", str(tmp_path / "missing-plugins"))
    failed = wait_job(client, start_analysis(client, project["id"], 3)["id"])
    assert failed["state"] == "failed"
    assert "Vamp plugin pack not found" in (failed["error"] or "")
    assert _analysis_count(client, project["id"]) == 0
    assert client.get(f"/api/projects/{project['id']}").json()["revision"] == revision


def test_analysis_job_is_registered_on_the_shared_job_route(client: TestClient) -> None:
    project = import_audio(client, TONE)
    job = start_analysis(client, project["id"], 4)
    assert job["id"]
    assert job["kind"] == "analysis"
    wait_job(client, job["id"])
