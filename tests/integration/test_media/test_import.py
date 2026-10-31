"""Import from a path and from an upload; project JSON records the media facts."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from helpers import (
    CLICK,
    TONE_44K,
    TONE_48K_STEREO,
    asset_pcm,
    import_path,
    project_file,
    sha256,
)


def test_import_44100_fixture_records_media_facts(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_44K, name="Tone 44.1k")

    assert payload["name"] == "Tone 44.1k"
    assert payload["audio"]["sample_rate"] == 44_100
    assert payload["audio"]["frames"] == 88_200
    assert payload["audio"]["channels"] == 1
    assert payload["audio"]["duration_seconds"] == 2.0
    assert payload["audio"]["content_sha256"] == sha256(TONE_44K)
    assert payload["title"] == "Tone 44.1k"
    assert payload["durationSeconds"] == 2.0
    assert payload["asset"]["sampleRate"] == 44_100
    assert payload["revision"] == 1

    stored = json.loads(project_file(settings, payload["id"]).read_text())
    assert stored["id"] == payload["id"]
    assert stored["audio"]["sample_rate"] == 44_100
    assert stored["audio"]["frames"] == 88_200
    assert stored["audio"]["channels"] == 1
    assert stored["audio"]["duration_seconds"] == 2.0
    assert stored["audio"]["content_sha256"] == sha256(TONE_44K)

    pcm = asset_pcm(settings, payload)
    assert pcm.is_file()
    assert pcm.stat().st_size == 88_200 * 1 * 4
    peaks = sorted((settings.data_paths.assets / payload["audio"]["asset_id"]).glob("peaks-*.bin"))
    assert {path.name for path in peaks} == {
        "peaks-256.bin",
        "peaks-1024.bin",
        "peaks-4096.bin",
        "peaks-16384.bin",
    }


def test_import_48000_stereo_fixture_records_rate_and_channels(
    client: TestClient, settings
) -> None:
    payload = import_path(client, TONE_48K_STEREO)

    assert payload["audio"]["sample_rate"] == 48_000
    assert payload["audio"]["frames"] == 48_000
    assert payload["audio"]["channels"] == 2
    assert payload["audio"]["duration_seconds"] == 1.0
    assert payload["audio"]["content_sha256"] == sha256(TONE_48K_STEREO)
    assert asset_pcm(settings, payload).stat().st_size == 48_000 * 2 * 4


def test_import_resamples_when_a_project_rate_is_requested(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_44K, sample_rate=48_000)
    assert payload["audio"]["sample_rate"] == 48_000
    assert payload["audio"]["frames"] == 96_000
    assert payload["audio"]["duration_seconds"] == 2.0
    # The source digest still describes the imported file bytes.
    assert payload["audio"]["content_sha256"] == sha256(TONE_44K)


def test_import_upload_via_multipart_library_endpoint(client: TestClient, settings) -> None:
    with CLICK.open("rb") as handle:
        response = client.post(
            "/api/library/import",
            files={"file": ("click_120bpm.wav", handle, "audio/wav")},
            data={"name": "Click take"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    entry = body["entry"]
    assert entry["title"] == "Click take"
    assert entry["durationSeconds"] == 4.0
    assert entry["sampleRate"] == 44_100
    assert entry["channels"] == 1
    assert entry["projectId"] == entry["id"]
    assert entry["projectId"] == body["project"]["id"]
    assert asset_pcm(settings, body["project"]).is_file()

    listing = client.get("/api/library").json()["entries"]
    assert [item["id"] for item in listing] == [entry["id"]]


def test_reimport_of_same_source_reuses_the_content_addressed_asset(
    client: TestClient, settings
) -> None:
    first = import_path(client, TONE_44K, name="One")
    second = import_path(client, TONE_44K, name="Two")
    assert first["id"] != second["id"]
    assert first["audio"]["asset_id"] == second["audio"]["asset_id"]
    assert len(list(settings.data_paths.assets.iterdir())) == 1


def test_import_rejects_a_missing_or_relative_path(client: TestClient) -> None:
    missing = client.post("/api/imports", json={"path": "/definitely/not/here.wav"})
    assert missing.status_code in {400, 422}
    relative = client.post("/api/imports", json={"path": "tests/fixtures/audio/tone_440hz.wav"})
    assert relative.status_code in {400, 422}
    assert "absolute" in relative.text


def test_project_list_and_media_endpoints(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    listing = client.get("/api/projects").json()["projects"]
    assert [project["id"] for project in listing] == [payload["id"]]
    media = client.get(f"/api/projects/{payload['id']}/media").json()
    assert media["sample_rate"] == 44_100
    assert media["frames"] == 88_200
    assert set(media["peaks"]) == {"256", "1024", "4096", "16384"}
    assert client.get("/api/projects/missing").status_code == 404
