"""Application/client fixtures for the real analysis job integration tests."""

from __future__ import annotations

import math
import time
import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import Settings

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
CLICK = AUDIO / "click_120bpm.wav"
CHORDS = AUDIO / "chords_c_am_f_g.wav"
TONE = AUDIO / "tone_440hz.wav"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "webdist")


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def import_audio(client: TestClient, path: Path, *, sample_rate: int = 48_000) -> dict:
    response = client.post("/api/imports", json={"path": str(path), "sample_rate": sample_rate})
    assert response.status_code == 201, response.text
    return response.json()


def start_analysis(client: TestClient, project_id: str, bpb: int = 4) -> dict:
    response = client.post(
        "/api/jobs",
        json={"kind": "analysis", "params": {"project_id": project_id, "bpb": bpb}},
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait_job(client: TestClient, job_id: str, *, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish in {timeout} s")


def write_long_wav(path: Path, *, seconds: float = 60.0, rate: int = 48_000) -> Path:
    """A deterministic 60 s click train, long enough to cancel mid-inference."""
    total = int(seconds * rate)
    samples = np.zeros(total, dtype=np.int16)
    beat = int(0.5 * rate)
    for start in range(0, total, beat):
        length = min(int(0.03 * rate), total - start)
        envelope = np.linspace(1.0, 0.0, length, dtype=np.float32)
        samples[start : start + length] = (
            12_000.0 * envelope * np.sin(2.0 * math.pi * 1000.0 * np.arange(length) / rate)
        ).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path
