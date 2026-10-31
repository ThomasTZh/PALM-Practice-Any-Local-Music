"""Atomic project writes, crash recovery and concurrent autosaves."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import TONE_44K, import_path, project_file

from basseparate.projects import ProjectStore, RevisionConflict


def test_save_is_atomic_and_a_crash_between_writes_keeps_the_previous_file(
    client: TestClient, settings, monkeypatch
) -> None:
    payload = import_path(client, TONE_44K)
    store = ProjectStore(settings.data_paths.projects)
    project = store.get(payload["id"])
    project = store.update(project.id, document={"step": 1})
    before = project_file(settings, project.id).read_bytes()
    assert json.loads(before)["document"] == {"step": 1}

    import basseparate.projects as projects_module

    def explode(*args, **kwargs):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(projects_module.os, "replace", explode)
    with pytest.raises(OSError, match="simulated crash"):
        store.update(project.id, document={"step": 2})
    monkeypatch.undo()

    after = project_file(settings, project.id).read_bytes()
    assert after == before
    assert json.loads(after)["document"] == {"step": 1}
    assert list(settings.data_paths.projects.glob(".*.tmp")) == []


def test_concurrent_saves_are_serialised_and_never_corrupt_the_file(
    client: TestClient, settings
) -> None:
    payload = import_path(client, TONE_44K)
    store = ProjectStore(settings.data_paths.projects)

    def save(index: int) -> int:
        updated = store.update(payload["id"], document={"writer": index})
        return updated.revision

    with ThreadPoolExecutor(max_workers=12) as pool:
        revisions = list(pool.map(save, range(24)))

    assert sorted(revisions) == list(range(2, 26))
    document = json.loads(project_file(settings, payload["id"]).read_text())
    assert document["revision"] == 25
    assert 0 <= document["document"]["writer"] < 24
    assert store.get(payload["id"]).revision == 25
    assert list(settings.data_paths.projects.glob(".*.tmp")) == []


def test_stale_revision_is_rejected_without_touching_the_file(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_44K)
    store = ProjectStore(settings.data_paths.projects)
    current = store.get(payload["id"])
    first = store.save(current, expected_revision=1)
    assert first.revision == 2

    with pytest.raises(RevisionConflict) as error:
        store.save(first, expected_revision=1)
    assert error.value.expected == 1
    assert error.value.actual == 2
    assert store.get(payload["id"]).revision == 2


def test_autosave_put_updates_document_and_returns_revision(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    response = client.put(
        f"/api/projects/{payload['id']}",
        json={"document": {"grid": {"bpm": 120.0}, "loops": []}, "revision": 1},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 2
    assert saved["document"]["grid"]["bpm"] == 120.0
    assert saved["audio"]["content_sha256"] == payload["audio"]["content_sha256"]

    stale = client.put(
        f"/api/projects/{payload['id']}",
        json={"document": {"grid": {"bpm": 90.0}}, "revision": 1},
    )
    assert stale.status_code == 409
    assert "revision" in stale.json()["detail"]
    assert client.get(f"/api/projects/{payload['id']}").json()["revision"] == 2


def test_put_name_and_document_preserve_media_facts(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    response = client.put(
        f"/api/projects/{payload['id']}",
        json={"name": "Renamed take", "document": {"sections": [{"bar": 1}]}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed take"
    assert body["document"]["sections"] == [{"bar": 1}]
    assert body["audio"] == payload["audio"]


def test_project_json_round_trips_after_process_boundary(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_44K)
    client.put(f"/api/projects/{payload['id']}", json={"document": {"note": "kept"}})
    reopened = ProjectStore(settings.data_paths.projects).get(payload["id"])
    assert reopened.document == {"note": "kept"}
    assert reopened.audio.sample_rate == 44_100


def test_projects_directory_contains_no_partial_temporary_files(
    client: TestClient, settings
) -> None:
    import_path(client, TONE_44K)
    assert sorted(path.name for path in Path(settings.data_paths.projects).glob("*.json"))
    assert list(Path(settings.data_paths.projects).glob("*.tmp")) == []
