"""Child-process tests for analysis/separate_msst.py with a stub msst module.

The worker runs in the main test interpreter, where torch/msst are absent; a
temporary ``msst.inference.Separator`` stub provides deterministic stems. This
covers argument mapping, label validation, resampling/trimming, progress, kill
cancellation and failure mapping without any real weights.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "analysis" / "separate_msst.py"
STUB_SOURCE = """\
import json
import os
import time

import numpy as np


class Separator:
    def __init__(
        self,
        *,
        config_path,
        checkpoint_path,
        model_type="mdx23c",
        device_ids=0,
        force_cpu=False,
        detailed_progress=True,
        **kwargs,
    ):
        log = os.environ.get("STUB_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "event": "init",
                    "config": str(config_path),
                    "checkpoint": str(checkpoint_path),
                    "model_type": model_type,
                    "force_cpu": force_cpu,
                }) + "\\n")
        if os.environ.get("STUB_FAIL") == "init":
            raise RuntimeError("stub init failure")
        self.sample_rate = 44100
        self.device = "cpu"
        self.instruments = tuple(
            os.environ.get("STUB_INSTRUMENTS", "drums,bass,other,vocals").split(",")
        )

    def separate(self, audio, *, sample_rate=None, channels_first=True):
        log = os.environ.get("STUB_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "event": "separate",
                    "shape": list(audio.shape),
                    "dtype": str(audio.dtype),
                    "sample_rate": sample_rate,
                    "channels_first": channels_first,
                }) + "\\n")
        if os.environ.get("STUB_FAIL") == "separate":
            raise RuntimeError("stub separation failure")
        time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
        frames = int(audio.shape[-1] * self.sample_rate / sample_rate) + 123
        return {
            label: np.full((2, frames), 0.01 * (index + 1), dtype=np.float32)
            for index, label in enumerate(self.instruments)
        }

    def close(self):
        pass
"""


def write_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "stub"
    (stub / "msst").mkdir(parents=True)
    (stub / "msst" / "__init__.py").write_text('__version__ = "0.1.0-stub"\n', encoding="utf-8")
    (stub / "msst" / "inference.py").write_text(STUB_SOURCE, encoding="utf-8")
    return stub


def make_root(tmp_path: Path, *, labels: list[str] | None = None) -> Path:
    labels = labels or ["drums", "bass", "other", "vocals"]
    checkpoint = b"checkpoint"
    config = b"model: {}\n"
    root = tmp_path / "root"
    model_dir = root / "models" / "scnet-xl-ihf"
    (root / "analysis").mkdir(parents=True)
    model_dir.mkdir(parents=True)
    (model_dir / "model.ckpt").write_bytes(checkpoint)
    (model_dir / "model.yaml").write_bytes(config)
    entry = {
        "id": "scnet-xl-ihf",
        "name": "Stub SCNet",
        "engine": "msst",
        "engine_command": "echo",
        "labels": labels,
        "sample_rate": 44100,
        "size_bytes": len(checkpoint) + len(config),
        "source_url": "https://example.invalid/model",
        "license": "test",
        "install_dir": "models/scnet-xl-ihf",
        "files": [
            {
                "role": "checkpoint",
                "name": "model.ckpt",
                "url": "https://example.invalid/model.ckpt",
                "size_bytes": len(checkpoint),
                "sha256": hashlib.sha256(checkpoint).hexdigest(),
            },
            {
                "role": "config",
                "name": "model.yaml",
                "url": "https://example.invalid/model.yaml",
                "size_bytes": len(config),
                "sha256": hashlib.sha256(config).hexdigest(),
            },
        ],
    }
    (root / "analysis" / "models.json").write_text(
        json.dumps({"schema_version": 2, "models": [entry]}), encoding="utf-8"
    )
    frames = 4800
    (root / "input.f32").write_bytes(b"\x00" * (frames * 2 * 4))
    return root


def command(root: Path, out: Path, stub: Path) -> tuple[list[str], dict[str, str]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(stub)
    return (
        [
            sys.executable,
            str(WORKER),
            "--input",
            str(root / "input.f32"),
            "--out",
            str(out),
            "--model-id",
            "scnet-xl-ihf",
            "--sample-rate",
            "48000",
            "--channels",
            "2",
            "--models-root",
            str(root),
            "--registry",
            str(root / "analysis" / "models.json"),
            "--device",
            "cpu",
        ],
        env,
    )


def run_worker(root: Path, out: Path, stub: Path, *, env_extra: dict[str, str] | None = None):
    cmd, env = command(root, out, stub)
    env.update(env_extra or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)


def test_child_contract_arguments_progress_stems_and_meta(tmp_path: Path) -> None:
    stub = write_stub(tmp_path)
    root = make_root(tmp_path)
    out = root / "out"
    log = tmp_path / "stub.log"
    result = run_worker(root, out, stub, env_extra={"STUB_LOG": str(log)})
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "progress",
        "progress",
        "done",
    ]
    assert [event["stage"] for event in events[:-1]] == [
        "loading",
        "separating",
        "resampling",
        "writing",
    ]
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    init = next(call for call in calls if call["event"] == "init")
    separate = next(call for call in calls if call["event"] == "separate")
    assert init["config"] == str(root / "models" / "scnet-xl-ihf" / "model.yaml")
    assert init["checkpoint"] == str(root / "models" / "scnet-xl-ihf" / "model.ckpt")
    assert init["model_type"] == "scnet"
    assert init["force_cpu"] is True
    assert separate == {
        "event": "separate",
        "shape": [2, 4800],
        "dtype": "float32",
        "sample_rate": 48000,
        "channels_first": True,
    }
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "complete"
    assert meta["model_id"] == "scnet-xl-ihf"
    assert meta["labels"] == ["drums", "bass", "other", "vocals"]
    assert meta["frames"] == 4800
    assert meta["sample_rate"] == 48000
    assert meta["channels"] == 2
    assert meta["device"] == "cpu"
    assert meta["elapsed_seconds"] >= 0
    assert meta["peak_rss_kb"] > 0
    for label in meta["labels"]:
        path = out / f"{label}.f32"
        assert path.is_file()
        assert path.stat().st_size == 4800 * 2 * 4
    assert not list(out.glob(".msst-stage-*"))


def test_label_mismatch_fails_without_partial_output(tmp_path: Path) -> None:
    stub = write_stub(tmp_path)
    root = make_root(tmp_path)
    out = root / "out"
    result = run_worker(root, out, stub, env_extra={"STUB_INSTRUMENTS": "drums,bass"})
    assert result.returncode == 1
    assert "does not match" in result.stderr
    assert not (out / "meta.json").exists()
    assert not list(out.glob("*.f32")) if out.exists() else True


def test_separation_failure_is_reported_and_leaves_no_meta(tmp_path: Path) -> None:
    stub = write_stub(tmp_path)
    root = make_root(tmp_path)
    out = root / "out"
    result = run_worker(root, out, stub, env_extra={"STUB_FAIL": "separate"})
    assert result.returncode == 1
    assert "failed" in result.stdout
    assert "stub separation failure" in result.stderr
    assert not (out / "meta.json").exists()


def test_sigterm_removes_staging_and_leaves_no_meta(tmp_path: Path) -> None:
    stub = write_stub(tmp_path)
    root = make_root(tmp_path)
    out = root / "out"
    cmd, env = command(root, out, stub)
    env["STUB_SLEEP"] = "60"
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + 20
        saw_separating = False
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            if event.get("stage") == "separating":
                saw_separating = True
                break
        assert saw_separating
        process.terminate()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode in (2, -15)
    assert not (out / "meta.json").exists()
    assert not list(out.glob("*.f32")) if out.exists() else True
    assert not list(out.glob(".msst-stage-*")) if out.exists() else True


def test_app_package_import_does_not_pull_torch_or_msst(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, basseparate.app, basseparate.stems, basseparate.analysis_jobs; "
            "mods = set(sys.modules); "
            "assert 'torch' not in mods, 'torch imported by the app'; "
            "assert 'msst' not in mods, 'msst imported by the app'; print('clean')",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean"
