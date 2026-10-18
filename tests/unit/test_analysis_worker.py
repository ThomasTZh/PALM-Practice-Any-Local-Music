"""Analysis worker protocol (M2.17, spec §4.1.7, §19.5).

Drives `analysis/worker.py` over stdin/stdout with a fake separator
script, so the full protocol path is tested without torch: handshake,
capabilities, progress relay, completion payload, cancellation, failure,
and shutdown.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from basseparate.worker import analysis_root, analysis_worker_command

WORKER = Path(__file__).resolve().parents[2] / "analysis" / "worker.py"

FAKE_SEPARATOR = r'''
import argparse, json, sys, time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input")
parser.add_argument("--profile")
parser.add_argument("--bundle-dir")
parser.add_argument("--device", default="cpu")
parser.add_argument("--out", required=True)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--cancel")
parser.add_argument("--segment", type=float, default=7.5)
parser.add_argument("--window-seconds", type=float, default=120.0)
parser.add_argument("--overlap-seconds", type=float, default=8.0)
args = parser.parse_args()

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)


def record(status, **extra):
    (out / "run-record.json").write_text(json.dumps({"status": status, **extra}))


mode = Path(args.input).read_text().strip()
if mode == "fail":
    record("failed", error="synthetic separator failure")
    sys.exit(1)
if mode == "cancel":
    cancel = Path(args.cancel)
    for _ in range(500):
        if cancel.exists():
            record("cancelled")
            sys.exit(2)
        time.sleep(0.01)
    record("failed", error="cancel flag was never written")
    sys.exit(1)

attempt = out / "attempt-1"
attempt.mkdir()
(attempt / "bass.pcm").write_bytes(b"fake-stem")
print(json.dumps({
    "type": "segment", "window": 1, "window_count": 2, "fraction": 0.5,
    "completed_units": 1, "total_units": 2,
}), flush=True)
print(json.dumps({
    "type": "window", "window": 1, "window_count": 2,
    "frames": 5, "total_frames": 10,
}), flush=True)
record(
    "complete", outputs=str(attempt), labels=["bass"], frames=5,
    device=args.device, timings={"seconds": 0.01},
)
print(json.dumps({
    "type": "final", "status": "complete", "record": str(out / "run-record.json"),
}), flush=True)
sys.exit(0)
'''


class WorkerProcess:
    def __init__(self, tmp_path: Path, separator: Path) -> None:
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(WORKER),
                "--separate-script",
                str(separator),
                "--python",
                sys.executable,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, message_type: str, payload: dict) -> None:
        message = {
            "protocol_version": 2,
            "message_id": str(uuid.uuid4()),
            "request_id": None,
            "type": message_type,
            "payload": payload,
        }
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def receive(self, timeout: float = 20.0) -> dict:
        result: dict[str, str] = {}

        def read_line() -> None:
            assert self.proc.stdout is not None
            result["line"] = self.proc.stdout.readline()

        thread = threading.Thread(target=read_line, daemon=True)
        thread.start()
        thread.join(timeout)
        assert not thread.is_alive(), "timed out waiting for a worker message"
        line = result.get("line", "")
        assert line, f"worker closed stdout (return code {self.proc.poll()})"
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.send("shutdown", {})
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
                self.proc.wait(timeout=10)


@pytest.fixture()
def fake_separator(tmp_path: Path) -> Path:
    path = tmp_path / "fake_separator.py"
    path.write_text(FAKE_SEPARATOR, encoding="utf-8")
    return path


@pytest.fixture()
def worker(tmp_path: Path, fake_separator: Path):
    process = WorkerProcess(tmp_path, fake_separator)
    try:
        hello = process.receive()
        assert hello["type"] == "hello"
        assert hello["payload"]["worker"] == "analysis"
        assert hello["payload"]["protocol_version"] == 2
        yield process
    finally:
        process.close()


def _parameters(tmp_path: Path, mode: str = "complete") -> dict:
    input_path = tmp_path / "input.pcm"
    input_path.write_text(mode)
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    return {
        "input_path": str(input_path),
        "profile_path": str(profile),
        "out_dir": str(tmp_path / "out"),
        "bundle_dir": str(bundle),
        "device": "cpu",
        "seed": 7,
    }


def _run_payload(tmp_path: Path, mode: str = "complete", job_type: str = "separation") -> dict:
    return {
        "job_id": str(uuid.uuid4()),
        "job_type": job_type,
        "source_path": str((tmp_path / "input.pcm").resolve()),
        "staging_dir": str((tmp_path / "staging").resolve()),
        "max_threads": 4,
        "parameters": _parameters(tmp_path, mode),
    }


class TestAnalysisWorkerProtocol:
    def test_capabilities_declare_separation_schema(self, worker: WorkerProcess) -> None:
        worker.send("describe", {})
        message = worker.receive()
        assert message["type"] == "capabilities"
        payload = message["payload"]
        assert payload["worker"] == "analysis"
        assert payload["models"] == ["htdemucs_ft"]
        capability = payload["capabilities"][0]
        assert capability["id"] == "analysis.separation.v1"
        assert "input_path" in capability["description"]

    def test_ping_pong(self, worker: WorkerProcess) -> None:
        worker.send("ping", {"nonce": "abc"})
        message = worker.receive()
        assert message["type"] == "pong"
        assert message["payload"]["nonce"] == "abc"

    def test_run_relays_progress_and_completes(
        self, worker: WorkerProcess, tmp_path: Path
    ) -> None:
        payload = _run_payload(tmp_path, "complete")
        worker.send("run", payload)
        progress: list[dict] = []
        completed: dict | None = None
        for _ in range(20):
            message = worker.receive()
            if message["type"] == "progress":
                progress.append(message["payload"])
            elif message["type"] == "completed":
                completed = message["payload"]
                break
        assert progress, "the worker relayed no progress"
        assert progress[0]["stage"] == "separating"
        assert progress[0]["fraction"] == 0.5
        assert completed is not None
        assert completed["job_id"] == payload["job_id"]
        result = completed["result"]
        assert result["status"] == "complete"
        assert result["stem_labels"] == ["bass"]
        assert Path(result["attempt_dir"]).is_dir()
        assert Path(result["record_path"]).is_file()
        assert result["record"]["timings"]["seconds"] == 0.01

    def test_cancel_writes_flag_and_reports_cancelled(
        self, worker: WorkerProcess, tmp_path: Path
    ) -> None:
        payload = _run_payload(tmp_path, "cancel")
        worker.send("run", payload)
        worker.send("cancel", {"job_id": payload["job_id"]})
        message = worker.receive()
        assert message["type"] == "cancelled"
        assert message["payload"]["job_id"] == payload["job_id"]
        assert message["payload"]["staging_removed"] is True

    def test_failure_carries_the_separator_error(
        self, worker: WorkerProcess, tmp_path: Path
    ) -> None:
        payload = _run_payload(tmp_path, "fail")
        worker.send("run", payload)
        message = worker.receive()
        assert message["type"] == "failed"
        assert message["payload"]["code"] == "SEPARATION_FAILED"
        assert "synthetic separator failure" in message["payload"]["message"]

    def test_unknown_job_type_is_rejected(
        self, worker: WorkerProcess, tmp_path: Path
    ) -> None:
        payload = _run_payload(tmp_path, "complete", job_type="export")
        worker.send("run", payload)
        message = worker.receive()
        assert message["type"] == "failed"
        assert message["payload"]["code"] == "JOB_TYPE_NOT_IMPLEMENTED"

    def test_shutdown_reports_stopped(self, worker: WorkerProcess) -> None:
        worker.send("shutdown", {})
        message = worker.receive()
        assert message["type"] == "stopped"
        assert message["payload"]["exit_code"] == 0
        assert worker.proc.wait(timeout=10) == 0

    def test_malformed_message_is_rejected(self, worker: WorkerProcess) -> None:
        assert worker.proc.stdin is not None
        worker.proc.stdin.write("not-json\n")
        worker.proc.stdin.flush()
        message = worker.receive()
        assert message["type"] == "error"
        assert message["payload"]["code"] == "MALFORMED_MESSAGE"


class TestAnalysisWorkerCommand:
    def test_env_override_selects_the_explicit_interpreter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("BASSEPARATE_ANALYSIS_ROOT", str(tmp_path))
        assert analysis_root() == tmp_path
        command = analysis_worker_command()
        assert command == [
            str(tmp_path / ".venv" / "bin" / "python"),
            str(tmp_path / "worker.py"),
        ]

    def test_default_resolves_the_repository_analysis_directory(self) -> None:
        assert analysis_root().name == "analysis"
        assert analysis_worker_command()[1].endswith("analysis/worker.py")
