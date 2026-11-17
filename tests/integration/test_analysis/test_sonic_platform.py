"""Windows/macOS default-backend selection through the real analysis server.

The host is Linux, so the platform attribute is patched and a fake Sonic binary
is supplied. This exercises the production default_backend/features/job path,
not a direct backend call.
"""

from __future__ import annotations

import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from basseparate import analysis_backend
from basseparate.app import create_app
from basseparate.config import Settings

ROOT = Path(__file__).resolve().parents[3]
CHORDS = ROOT / "tests" / "fixtures" / "audio" / "chords_c_am_f_g.wav"
FAKE = '''#!/usr/bin/env python3
import sys
from pathlib import Path

args = sys.argv[1:]
if "--list" in args:
    print("vamp:embed-chord:chordino:simplechord")
    print("vamp:qm:qm-keydetector:key")
    print("vamp:qm:qm-keydetector:tonic")
    print("vamp:qm:qm-keydetector:mode")
    print("vamp:qm:qm-barbeattracker:beats")
    print("vamp:qm:qm-barbeattracker:bars")
    sys.exit(0)
if "-s" in args:
    print('vamp:plugin_version """1"""')
    sys.exit(0)
out = Path(args[args.index("--csv-one-file") + 1])
transform = "custom:simplechord" if "-t" in args else args[args.index("-d") + 1]
if transform.endswith("simplechord"):
    text = '0.0,"N"\\n0.5,"C"\\n'
elif transform.endswith("key"):
    text = '0.0,1,"C major"\\n'
elif transform.endswith("tonic"):
    text = '0.0,1,"C"\\n'
elif transform.endswith("mode"):
    text = '0.0,0,"Major"\\n'
elif transform.endswith("beats"):
    text = '0.5,"1"\\n1.0,"2"\\n'
elif transform.endswith("bars"):
    text = '0.5,"1"\\n'
else:
    text = ""
out.write_text(text, encoding="utf-8")
'''


def fake_binary(tmp_path: Path) -> Path:
    path = tmp_path / "fake sonic"
    path.write_text(FAKE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def import_audio(client: TestClient) -> dict:
    response = client.post("/api/imports", json={"path": str(CHORDS), "sample_rate": 48_000})
    assert response.status_code == 201, response.text
    return response.json()


def wait_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("analysis job did not finish")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_default_sonic_backend_runs_through_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    binary = fake_binary(tmp_path)
    monkeypatch.setenv("BASSEPARATE_SONIC_ANNOTATOR", str(binary))
    monkeypatch.setattr(analysis_backend, "sys", SimpleNamespace(platform=platform))
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web")
    with TestClient(create_app(settings)) as client:
        project = import_audio(client)
        started = client.post(
            "/api/jobs",
            json={"kind": "analysis", "params": {"project_id": project["id"], "bpb": 4}},
        )
        assert started.status_code == 202, started.text
        job = wait_job(client, started.json()["id"])
        assert job["state"] == "succeeded", job.get("error")
        result = job["result"]
        assert result["key"] == "C major"
        assert [chord["label"] for chord in result["chords"] if chord["label"] != "N"] == ["C"]
        assert abs(result["bpm"] - 120.0) <= 0.5
        assert result["beats"] == [0.5, 1.0]
        assert result["bars"] == [0.5]


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_missing_sonic_tools_surface_the_setup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    missing = tmp_path / "not-installed" / "sonic-annotator"
    monkeypatch.setenv("BASSEPARATE_SONIC_ANNOTATOR", str(missing))
    monkeypatch.setattr(analysis_backend, "sys", SimpleNamespace(platform=platform))
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web")
    with TestClient(create_app(settings)) as client:
        project = import_audio(client)
        started = client.post(
            "/api/jobs",
            json={"kind": "analysis", "params": {"project_id": project["id"], "bpb": 4}},
        )
        assert started.status_code == 202, started.text
        job = wait_job(client, started.json()["id"])
    assert job["state"] == "failed"
    detail = str(job.get("error"))
    assert "Sonic Annotator is not installed" in detail
    assert "PALM Setup" in detail
    assert "Vamp Plugin Pack" in detail
