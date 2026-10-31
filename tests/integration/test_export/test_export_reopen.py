"""Export, reopen and doctor over the live FastAPI app."""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from conftest import fresh_client

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
TONE_44K = AUDIO / "tone_440hz.wav"
TONE_48K_STEREO = AUDIO / "tone_48k_stereo.wav"


def import_fixture(client: TestClient, path: Path, name: str = "Take") -> dict:
    response = client.post("/api/imports", json={"path": str(path), "name": name})
    assert response.status_code == 201, response.text
    return response.json()


def write_constant_pcm(path: Path, *, frames: int, channels: int, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.full(frames * channels, value, dtype="<f4")
    path.write_bytes(data.tobytes())


def add_stems(client: TestClient, settings, project: dict, stems: list[dict]) -> dict:
    assets = settings.data_paths.assets
    for stem in stems:
        write_constant_pcm(
            assets / stem["asset_id"] / "pcm.f32",
            frames=project["audio"]["frames"],
            channels=project["audio"]["channels"],
            value=stem.pop("value"),
        )
    response = client.put(
        f"/api/projects/{project['id']}",
        json={"document": {**project.get("document", {}), "stems": stems}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def read_wav(path: Path) -> tuple[int, int, int, np.ndarray]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        frames = handle.getnframes()
        payload = handle.readframes(frames)
    samples = np.frombuffer(payload, dtype="<i2").reshape(frames, channels)
    return rate, channels, frames, samples


def test_export_wav_matches_project_rate_and_duration(client: TestClient, settings) -> None:
    project = import_fixture(client, TONE_44K, "44.1k export")
    export = client.post(f"/api/projects/{project['id']}/exports", json={})
    assert export.status_code == 201, export.text
    metadata = export.json()
    assert metadata["frames"] == project["audio"]["frames"] == 88_200
    assert metadata["sample_rate"] == 44_100
    assert metadata["channels"] == project["audio"]["channels"] == 1

    download = client.get(metadata["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("audio/")
    path = settings.data_paths.root / "exports" / project["id"] / metadata["filename"]
    assert path.is_file()
    rate, channels, frames, _samples = read_wav(path)
    assert (rate, channels, frames) == (44_100, 1, 88_200)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]


def test_export_applies_stem_gains_and_solo(client: TestClient, settings) -> None:
    project = import_fixture(client, TONE_48K_STEREO, "Mixer take")
    project = add_stems(
        client,
        settings,
        project,
        [
            {"id": "bass", "name": "Bass", "asset_id": "stem-bass", "gain": 0.5, "value": 0.4},
            {"id": "drums", "name": "Drums", "asset_id": "stem-drums", "gain": 1.0, "value": 0.2},
        ],
    )
    assert project["document"]["stems"][0]["gain"] == 0.5

    # Document gains: 0.4*0.5 + 0.2*1.0 = 0.4.
    first = client.post(f"/api/projects/{project['id']}/exports", json={}).json()
    _rate, _channels, frames, samples = read_wav(
        settings.data_paths.root / "exports" / project["id"] / first["filename"]
    )
    assert frames == project["audio"]["frames"]
    assert np.max(np.abs(samples.astype(np.float64) / 32767.0 - 0.4)) < 2 / 32767.0

    # Request mixer overrides: 0.4*1.0 + 0.2*0.5 = 0.5.
    second = client.post(
        f"/api/projects/{project['id']}/exports",
        json={
            "mixer": {
                "stems": {
                    "bass": {"gain": 1.0},
                    "drums": {"gain": 0.5},
                }
            }
        },
    ).json()
    _rate, _channels, _frames, samples = read_wav(
        settings.data_paths.root / "exports" / project["id"] / second["filename"]
    )
    assert np.max(np.abs(samples.astype(np.float64) / 32767.0 - 0.5)) < 2 / 32767.0

    # Solo drums: only 0.2 remains.
    solo = client.post(
        f"/api/projects/{project['id']}/exports",
        json={"mixer": {"stems": {"drums": {"gain": 1.0, "solo": True}}}},
    ).json()
    _rate, _channels, _frames, samples = read_wav(
        settings.data_paths.root / "exports" / project["id"] / solo["filename"]
    )
    assert np.max(np.abs(samples.astype(np.float64) / 32767.0 - 0.2)) < 2 / 32767.0


def test_export_reports_a_missing_stem_clearly(client: TestClient, settings) -> None:
    project = import_fixture(client, TONE_44K)
    project = add_stems(
        client,
        settings,
        project,
        [{"id": "bass", "name": "Bass", "asset_id": "stem-bass", "gain": 1.0, "value": 0.3}],
    )
    (settings.data_paths.assets / "stem-bass" / "pcm.f32").unlink()
    response = client.post(f"/api/projects/{project['id']}/exports", json={})
    assert response.status_code == 400
    assert "bass" in response.json()["detail"]
    assert "pcm.f32" in response.json()["detail"]


def test_reopen_after_service_restart_restores_practice_state(
    client: TestClient, settings
) -> None:
    project = import_fixture(client, TONE_44K, "Reopen take")
    state = {
        "sections": [
            {"id": "s1", "name": "Verse", "start_bar": 1, "end_bar": 4},
            {"id": "s2", "name": "Chorus", "start_bar": 5, "end_bar": 8},
        ],
        "loop": {"start_frame": 44_100, "end_frame": 88_200, "repeat_count": 8},
        "speed": 0.75,
        "pitch_semitones": 3.0,
        "position_frame": 44_100,
        "analysis": {
            "cache_key": "cache-abc",
            "source_sha256": project["audio"]["content_sha256"],
            "sample_rate": 44_100,
            "bpm": 120.0,
            "key": "C major",
        },
        "mixer": {"bass": {"gain": 0.7, "solo": True}},
    }
    saved = client.put(f"/api/projects/{project['id']}/state", json={"state": state})
    assert saved.status_code == 200, saved.text
    assert saved.json()["project"]["revision"] == 2

    with fresh_client(settings) as restarted:
        reopened = restarted.get(f"/api/projects/{project['id']}/reopen")
        assert reopened.status_code == 200, reopened.text
        payload = reopened.json()
        restored = payload["state"]
        assert [(s["name"], s["start_bar"]) for s in restored["sections"]] == [
            ("Verse", 1),
            ("Chorus", 5),
        ]
        assert restored["loop"]["start_frame"] == 44_100
        assert restored["speed"] == 0.75
        assert restored["pitch_semitones"] == 3.0
        assert restored["analysis"]["cache_key"] == "cache-abc"
        assert restored["analysis"]["key"] == "C major"
        assert restored["mixer"]["bass"]["gain"] == 0.7
        assert payload["assets"] == {"ok": True, "missing": []}


def test_missing_asset_error_keeps_the_project_readable(client: TestClient, settings) -> None:
    project = import_fixture(client, TONE_44K)
    client.put(
        f"/api/projects/{project['id']}/state",
        json={"state": {"speed": 0.5, "sections": []}},
    )
    pcm = settings.data_paths.assets / project["audio"]["asset_id"] / "pcm.f32"
    pcm.unlink()

    reopen = client.get(f"/api/projects/{project['id']}/reopen")
    assert reopen.status_code == 409
    assert "asset" in reopen.json()["detail"]
    assert "pcm.f32" in reopen.json()["detail"]

    # The project JSON and its state are still readable; only the media is absent.
    still_there = client.get(f"/api/projects/{project['id']}")
    assert still_there.status_code == 200
    assert still_there.json()["id"] == project["id"]
    state = client.get(f"/api/projects/{project['id']}/state")
    assert state.status_code == 200
    assert state.json()["state"]["speed"] == 0.5
    assert state.json()["assets"]["ok"] is False
    assert "pcm.f32" in state.json()["assets"]["missing"][0]


def test_doctor_endpoint_reports_dependencies_without_writing(
    client: TestClient, settings
) -> None:
    before = {
        path: path.stat().st_mtime_ns
        for path in settings.data_paths.root.rglob("*")
        if path.is_file()
    }
    for url in ("/api/doctor", "/doctor"):
        response = client.get(url)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] in {"ok", "degraded"}
        checks = {check["id"]: check for check in payload["checks"]}
        for required in (
            "ffmpeg",
            "ffprobe",
            "data_root",
            "model_bundle",
            "vamp_plugins",
            "piper",
            "gpu",
        ):
            assert required in checks, required
            assert checks[required]["status"] in {"ok", "missing"}
        assert "missing" in payload
    after = {
        path: path.stat().st_mtime_ns
        for path in settings.data_paths.root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_state_save_and_export_paths_are_scoped_to_the_project(
    client: TestClient, settings
) -> None:
    project = import_fixture(client, TONE_44K)
    export = client.post(f"/api/projects/{project['id']}/exports", json={})
    assert export.status_code == 201
    metadata = export.json()
    assert metadata["download_url"].startswith(f"/api/projects/{project['id']}/exports/")
    missing = client.get(f"/api/projects/{project['id']}/exports/does-not-exist.wav")
    assert missing.status_code == 404
    other = client.get("/api/projects/other/exports/" + metadata["filename"])
    assert other.status_code == 404
    body = json.loads(
        (settings.data_paths.projects / f"{project['id']}.json").read_text()
    )
    assert body["document"]["state_version"] == 1
