"""Real htdemucs_ft integration: stems, cache, cancellation, failure and HTTP.

These tests are opt-in through ``RUN_SEPARATION=1`` because the 8 s fixture
runs four model bags on CPU. ``make test-separation TESTS="tests/integration/test_stems"``
sets that flag.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate import stems
from basseparate.app import create_app
from basseparate.config import DataPaths
from basseparate.stems import (
    STEM_LABELS,
    StemError,
    StemsCancelled,
    separate_asset,
    separate_project,
)

from .conftest import ROOT, StemWorkspace

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_SEPARATION") != "1",
        reason="set RUN_SEPARATION=1 (make test-separation) for real Demucs inference",
    ),
]


def test_four_equal_length_stems_at_the_project_rate(stem_workspace: StemWorkspace) -> None:
    stem_set = stem_workspace.stem_set
    project = stem_workspace.project
    assert stem_set.cached is False
    assert stem_set.sample_rate == project.audio.sample_rate == 48_000
    assert stem_set.channels == 2
    assert stem_set.frames == project.audio.frames == 384_000
    assert [stem.label for stem in stem_set.stems] == list(STEM_LABELS)
    assert {stem.frames for stem in stem_set.stems} == {stem_set.frames}
    assert {stem.channels for stem in stem_set.stems} == {2}
    expected_bytes = stem_set.frames * stem_set.channels * 4
    for stem in stem_set.stems:
        assert stem.path.is_file()
        assert stem.path.stat().st_size == expected_bytes
    assert stem_set.elapsed_seconds > 0
    assert stem_workspace.wall_seconds > 0
    print(
        f"CPU separation: {project.audio.duration_seconds:.2f} s audio in "
        f"{stem_workspace.wall_seconds:.2f} s wall "
        f"({stem_set.elapsed_seconds:.2f} s child)"
    )
    assert stem_workspace.progress
    assert stem_workspace.progress[-1][0] == 1.0


def test_second_run_reuses_cache_and_starts_no_child(
    stem_workspace: StemWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding_spawn(*args: object, **kwargs: object) -> object:
        raise AssertionError("a cached stem run must not start the analysis child")

    monkeypatch.setattr(stems.subprocess, "Popen", exploding_spawn)
    again = separate_project(
        stem_workspace.project,
        paths=stem_workspace.paths,
        model_id="htdemucs_ft",
        device="cpu",
    )
    assert again.cached is True
    assert again.key == stem_workspace.stem_set.key
    assert again.frames == stem_workspace.stem_set.frames


def test_tampered_checkpoint_fails_before_inference_with_stderr_tail(
    stem_workspace: StemWorkspace, tmp_path: Path
) -> None:
    bundle = tmp_path / "tampered-bundle"
    bundle.mkdir()
    model_dir = ROOT / "models" / "htdemucs_ft"
    (bundle / "htdemucs_ft.yaml").symlink_to(model_dir / "htdemucs_ft.yaml")
    manifest = json.loads((ROOT / "analysis" / "checkpoints.json").read_text(encoding="utf-8"))
    names = sorted(manifest["checkpoints"])
    for name in names[:-1]:
        (bundle / name).symlink_to(model_dir / name)
    tampered = bundle / names[-1]
    shutil.copy2(model_dir / names[-1], tampered)
    with tampered.open("r+b") as handle:
        handle.seek(8192)
        value = handle.read(1)
        handle.seek(8192)
        handle.write(bytes([value[0] ^ 0x80]))
    paths = DataPaths.from_root(tmp_path / "tamper-data").ensure()
    pcm = stem_workspace.paths.asset_dir(stem_workspace.project.audio.asset_id) / "pcm.f32"
    with pytest.raises(StemError) as error:
        separate_asset(
            pcm,
            sample_rate=stem_workspace.project.audio.sample_rate,
            channels=stem_workspace.project.audio.channels,
            paths=paths,
            model_id="htdemucs_ft",
            bundle_dir=bundle,
            device="cpu",
        )
    message = str(error.value)
    assert "checkpoint hash mismatch" in message
    assert "worker stderr tail" in message
    cache = paths.root / "stems"
    assert not cache.exists() or not any(cache.iterdir())


def test_real_worker_honours_the_cancel_file(stem_workspace: StemWorkspace, tmp_path: Path) -> None:
    paths = DataPaths.from_root(tmp_path / "cancel-real").ensure()
    pcm = stem_workspace.paths.asset_dir(stem_workspace.project.audio.asset_id) / "pcm.f32"
    stop = __import__("threading").Event()

    def progress(fraction: float, message: str) -> None:
        if fraction >= 0.1:
            stop.set()

    with pytest.raises(StemsCancelled):
        separate_asset(
            pcm,
            sample_rate=stem_workspace.project.audio.sample_rate,
            channels=stem_workspace.project.audio.channels,
            paths=paths,
            model_id="htdemucs_ft",
            device="cpu",
            is_cancelled=stop.is_set,
            progress=progress,
        )
    cache = paths.root / "stems"
    assert not cache.exists() or not any(cache.iterdir())


def test_cancel_kills_the_child_and_publishes_nothing(
    stem_workspace: StemWorkspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "fake_worker.py"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "from pathlib import Path as P\n"
        "P(os.environ['FAKE_PID_FILE']).write_text(str(os.getpid()))\n"
        "print(json.dumps({'type': 'progress', 'stage': 'separating', 'fraction': 0.1}),"
        " flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    paths = DataPaths.from_root(tmp_path / "cancel-data").ensure()
    pcm = stem_workspace.paths.asset_dir(stem_workspace.project.audio.asset_id) / "pcm.f32"
    stop = __import__("threading").Event()
    pid_file = tmp_path / "fake-pid.txt"
    monkeypatch.setenv("FAKE_PID_FILE", str(pid_file))

    def progress(fraction: float, message: str) -> None:
        if fraction >= 0.1:
            stop.set()

    monkeypatch.setattr(stems, "CANCEL_GRACE_SECONDS", 0.5)
    with pytest.raises(StemsCancelled):
        separate_asset(
            pcm,
            sample_rate=stem_workspace.project.audio.sample_rate,
            channels=stem_workspace.project.audio.channels,
            paths=paths,
            model_id="htdemucs_ft",
            analysis_python=Path(sys.executable),
            worker_script=fake,
            device="cpu",
            is_cancelled=stop.is_set,
            progress=progress,
        )
    assert pid_file.is_file()
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    cache = paths.root / "stems"
    assert not cache.exists() or not any(cache.iterdir())


def test_separate_endpoint_and_ranged_stem_pcm(stem_workspace: StemWorkspace) -> None:
    app = create_app(stem_workspace.settings)
    project_id = stem_workspace.project.id
    with TestClient(app) as client:
        metadata = client.get(f"/api/projects/{project_id}/stems")
        assert metadata.status_code == 200, metadata.text
        body = metadata.json()
        assert body["key"] == stem_workspace.stem_set.key
        assert [entry["label"] for entry in body["stems"]] == list(STEM_LABELS)

        ranged = client.get(
            f"/api/projects/{project_id}/stems/drums/pcm", params={"start": 100, "end": 200}
        )
        assert ranged.status_code == 200, ranged.text
        assert len(ranged.content) == 100 * 2 * 4
        assert ranged.headers["x-stem-label"] == "drums"
        assert ranged.headers["x-sample-rate"] == "48000"
        assert ranged.headers["x-channels"] == "2"
        assert ranged.headers["x-total-frames"] == "384000"

        response = client.post(
            "/api/separate",
            json={"project_id": project_id, "model_id": "htdemucs_ft", "device": "cpu"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 30.0
        job: dict[str, object] = {}
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job.get("state") in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert job.get("state") == "succeeded", job
        result = job.get("result")
        assert isinstance(result, dict)
        assert [entry["label"] for entry in result["stems"]] == list(STEM_LABELS)


def test_project_document_lists_stems(stem_workspace: StemWorkspace) -> None:
    stored = stem_workspace.store.get(stem_workspace.project.id)
    entries = stored.document.get("stems")
    assert isinstance(entries, list)
    assert [entry["label"] for entry in entries] == list(STEM_LABELS)
    assert stored.document.get("stemCacheKey") == stem_workspace.stem_set.key
