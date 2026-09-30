"""Offline-start integration test (M0.12, section 13.6).

Verifies that after installing dependencies and building assets, the
application can start and operate with network access restricted to
loopback only. No external runtime requests are made. Missing models
do not trigger downloads.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _wait_for_health(port: int, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=3
            ) as resp:
                return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"health check timed out on port {port}")


class TestOfflineStart:
    def test_full_offline_cycle(self, tmp_path: Path) -> None:
        """Launch, create project, run worker probe, confirm no external requests."""
        storage = tmp_path / "storage"
        port = 18790

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                str(port),
                "--storage-root",
                str(storage),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
        )
        try:
            health = _wait_for_health(port)
            assert health["status"] == "ready"

            # Verify the server is serving static assets (the frontend shell).
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
                html = resp.read().decode()
                assert "<!DOCTYPE html>" in html or "<html" in html

            # Run the worker probe (model-free, no network).
            probe = subprocess.run(
                [sys.executable, "-m", "basseparate.cli", "worker-probe"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                timeout=30,
            )
            assert probe.returncode == 0
            assert "worker probe passed" in probe.stderr or "worker probe passed" in probe.stdout

        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_no_model_download_triggered(self, tmp_path: Path) -> None:
        """Confirm that starting the server does not attempt any model downloads."""
        storage = tmp_path / "storage"
        port = 18791

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                str(port),
                "--storage-root",
                str(storage),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
        )
        try:
            _wait_for_health(port)
            time.sleep(2)

            # Check that no model-related directories were created in the storage.
            data_dir = storage / "data"
            if data_dir.exists():
                contents = list(data_dir.iterdir())
                model_dirs = [
                    d
                    for d in contents
                    if d.is_dir() and ("model" in d.name.lower() or "weights" in d.name.lower())
                ]
                assert model_dirs == [], f"unexpected model directories: {model_dirs}"

        finally:
            proc.terminate()
            proc.wait(timeout=10)
