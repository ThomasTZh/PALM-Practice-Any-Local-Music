"""Small helpers shared by the media server integration tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
TONE_44K = AUDIO / "tone_440hz.wav"
TONE_48K_STEREO = AUDIO / "tone_48k_stereo.wav"
CLICK = AUDIO / "click_120bpm.wav"
CHORDS = AUDIO / "chords_c_am_f_g.wav"


def import_path(client: TestClient, path: Path, **extra: object) -> dict:
    response = client.post("/api/imports", json={"path": str(path), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def project_file(settings, project_id: str) -> Path:
    return settings.data_paths.projects / f"{project_id}.json"


def asset_pcm(settings, payload: dict) -> Path:
    asset_id = payload["audio"]["asset_id"]
    return settings.data_paths.assets / asset_id / "pcm.f32"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pcm_bytes(path: Path, start: int, end: int, channels: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start * channels * 4)
        return handle.read((end - start) * channels * 4)
