"""The serve CLI binds loopback, prints a working URL and serves the built UI."""

from __future__ import annotations

import ast
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import ROOT, TONE_44K

from basseparate.app import create_app
from basseparate.config import Settings

CLI_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/")


def http_get(url: str, timeout: float = 10.0) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(), response.headers.get("content-type", "")


def wait_for_url(
    process: subprocess.Popen[str], timeout: float = 30.0
) -> tuple[str | None, list[str]]:
    messages: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            messages.put(line.rstrip())
        messages.put(None)

    threading.Thread(target=pump, daemon=True).start()
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=0.25)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        lines.append(line)
        match = CLI_URL.search(line)
        if match and line.startswith("bootstrap:"):
            return match.group(0), lines
    return None, lines


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def run_server(tmp_path: Path, web_dir: Path) -> tuple[str, subprocess.Popen[str], list[str]]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cli = ROOT / ".venv" / "bin" / "basseparate"
    command = [str(cli)] if cli.is_file() else [sys.executable, "-m", "basseparate.cli"]
    process = subprocess.Popen(
        [
            *command,
            "serve",
            "--no-browser",
            "--port",
            "0",
            "--data-root",
            str(tmp_path / "data"),
            "--web-dir",
            str(web_dir),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url, lines = wait_for_url(process)
    if url is None:
        stop(process)
        pytest.fail("server did not print a loopback URL:\n" + "\n".join(lines))
    return url, process, lines


def test_serve_prints_a_working_bootstrap_url_and_serves_the_built_ui(tmp_path: Path) -> None:
    web_dir = tmp_path / "dist"
    web_dir.mkdir()
    (web_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root">basseparate-ui-marker</div></body></html>'
    )
    (web_dir / "app.js").write_text("console.log('ui');")

    url, process, lines = run_server(tmp_path, web_dir)
    try:
        assert CLI_URL.fullmatch(url), url
        assert f"bootstrap: {url}" in lines

        status, body, content_type = http_get(url + "api/health")
        assert status == 200
        assert b"ok" in body
        assert "application/json" in content_type

        status, body, content_type = http_get(url)
        assert status == 200
        assert "text/html" in content_type
        assert b"basseparate-ui-marker" in body

        status, body, content_type = http_get(url + "app.js")
        assert status == 200
        assert b"console.log('ui')" in body

        # The running process can import a fixture and expose ranged PCM.
        import json

        request = urllib.request.Request(
            url + "api/imports",
            data=json.dumps({"path": str(TONE_44K), "name": "Served import"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            project = json.loads(response.read())
        assert project["name"] == "Served import"
        status, pcm, _ = http_get(url + f"api/projects/{project['id']}/pcm?start=0&end=10")
        assert status == 200
        assert len(pcm) == 40
    finally:
        stop(process)


def test_serve_without_a_built_ui_still_answers_with_a_placeholder(tmp_path: Path) -> None:
    url, process, _lines = run_server(tmp_path, tmp_path / "no-dist")
    try:
        status, body, content_type = http_get(url)
        assert status == 200
        assert "text/html" in content_type
        assert b"basseparate" in body.lower()
    finally:
        stop(process)


def test_serve_refuses_to_bind_anything_but_loopback(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "basseparate.cli",
            "serve",
            "--port",
            "0",
            "--host",
            "0.0.0.0",
            "--data-root",
            str(tmp_path / "data"),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "loopback" in (result.stdout + result.stderr).lower()


def test_in_process_app_serves_ui_from_configured_dist(tmp_path: Path) -> None:
    web_dir = tmp_path / "dist"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html><body>marker</body></html>")
    app = create_app(Settings(data_dir=tmp_path / "data", web_dir=web_dir))
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "marker" in response.text
        assert client.get("/api/health").json()["status"] == "ok"


def test_service_modules_do_not_import_torch_demucs_or_the_analysis_package() -> None:
    sources = [
        ROOT / "src" / "basseparate" / name
        for name in (
            "app.py",
            "cli.py",
            "config.py",
            "media.py",
            "peaks.py",
            "projects.py",
            "jobs.py",
            "events.py",
        )
    ]
    sources.extend(sorted((ROOT / "src" / "basseparate" / "api").glob("*.py")))
    forbidden = ("torch", "demucs", "vamp", "piper")
    for source in sources:
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in forbidden, f"{source.name} imports forbidden module {name}"


def test_running_app_keeps_the_analysis_environment_out_of_sys_modules(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "BASSEPARATE_DATA_DIR": str(tmp_path / "data"),
    }
    script = """
import sys
from fastapi.testclient import TestClient
from basseparate.app import create_app

app = create_app()
with TestClient(app) as client:
    assert client.get("/api/health").status_code == 200
bad = [name for name in sys.modules if name.split(".")[0] in {"torch", "demucs", "vamp", "piper"}]
print("BAD=" + ",".join(sorted(bad)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BAD=\n" in result.stdout or result.stdout.rstrip().endswith("BAD=")
