"""Serve lifecycle and instance-lock tests (M0.10)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from basseparate.config import AppConfig, resolve_config
from basseparate.serve import (
    InstanceLockError,
    acquire_instance_lock,
    release_instance_lock,
)
from basseparate.storage import initialize_storage_paths, resolve_storage_paths


def _make_config(tmp_path: Path, port: int = 18765) -> AppConfig:
    return resolve_config(
        cli={
            "storage_root": str(tmp_path / "storage"),
            "port": port,
            "open_browser": False,
        }
    )


class TestInstanceLock:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        paths = resolve_storage_paths(tmp_path / "storage")
        initialize_storage_paths(paths)
        fd = acquire_instance_lock(paths.runtime)
        try:
            assert fd >= 0
            lock_file = paths.runtime / ".basseparate.lock"
            assert lock_file.is_file()
            content = lock_file.read_text()
            assert str(os.getpid()) in content
        finally:
            release_instance_lock(fd)

    def test_second_acquire_fails(self, tmp_path: Path) -> None:
        paths = resolve_storage_paths(tmp_path / "storage")
        initialize_storage_paths(paths)
        fd1 = acquire_instance_lock(paths.runtime)
        try:
            with pytest.raises(InstanceLockError, match="already running"):
                acquire_instance_lock(paths.runtime)
        finally:
            release_instance_lock(fd1)

    def test_separate_roots_allow_separate_locks(self, tmp_path: Path) -> None:
        paths_a = resolve_storage_paths(tmp_path / "storage_a")
        paths_b = resolve_storage_paths(tmp_path / "storage_b")
        initialize_storage_paths(paths_a)
        initialize_storage_paths(paths_b)
        fd_a = acquire_instance_lock(paths_a.runtime)
        try:
            fd_b = acquire_instance_lock(paths_b.runtime)
            try:
                assert fd_a >= 0
                assert fd_b >= 0
            finally:
                release_instance_lock(fd_b)
        finally:
            release_instance_lock(fd_a)

    def test_lock_released_after_release(self, tmp_path: Path) -> None:
        paths = resolve_storage_paths(tmp_path / "storage")
        initialize_storage_paths(paths)
        fd = acquire_instance_lock(paths.runtime)
        release_instance_lock(fd)
        fd2 = acquire_instance_lock(paths.runtime)
        try:
            assert fd2 >= 0
        finally:
            release_instance_lock(fd2)

    def test_lock_file_permissions(self, tmp_path: Path) -> None:
        paths = resolve_storage_paths(tmp_path / "storage")
        initialize_storage_paths(paths)
        fd = acquire_instance_lock(paths.runtime)
        try:
            mode = (paths.runtime / ".basseparate.lock").stat().st_mode & 0o777
            assert mode == 0o600
        finally:
            release_instance_lock(fd)


class TestServeLaunch:
    def test_serve_starts_and_stops(self, tmp_path: Path) -> None:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18770",
                "--storage-root",
                str(tmp_path / "storage"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        try:
            time.sleep(3)
            assert proc.poll() is None, "server should still be running"
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            assert proc.returncode == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_serve_already_running(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage"
        paths = resolve_storage_paths(storage)
        initialize_storage_paths(paths)
        fd = acquire_instance_lock(paths.runtime)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "basseparate.cli",
                    "serve",
                    "--no-browser",
                    "--port",
                    "18771",
                    "--storage-root",
                    str(storage),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            assert proc.returncode == 1
            assert "already running" in proc.stderr
        finally:
            release_instance_lock(fd)

    def test_serve_no_frontend_build(self, tmp_path: Path) -> None:
        script_file = tmp_path / "probe.py"
        script_file.write_text(
            "import sys\n"
            "from basseparate.config import resolve_config\n"
            "import basseparate.serve\n"
            "basseparate.serve._static_dir = lambda: None\n"
            f"config = resolve_config(cli={{'storage_root': {str(tmp_path / 's')!r}, "
            "'port': 18772, 'open_browser': False})\n"
            "sys.exit(basseparate.serve.run_server(config))\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(script_file)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 1
        assert "frontend build not found" in proc.stderr

    def test_port_conflict(self, tmp_path: Path) -> None:
        # Occupy the port first.
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 18773))
        sock.listen(1)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "basseparate.cli",
                    "serve",
                    "--no-browser",
                    "--port",
                    "18773",
                    "--storage-root",
                    str(tmp_path / "storage"),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            assert proc.returncode != 0
        finally:
            sock.close()

    def test_no_browser_prints_url(self, tmp_path: Path) -> None:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18774",
                "--storage-root",
                str(tmp_path / "storage"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        try:
            time.sleep(3)
            assert proc.poll() is None
            proc.send_signal(signal.SIGTERM)
            stdout, _ = proc.communicate(timeout=10)
            output = stdout.decode()
            assert "#token=" in output
            assert "18774" in output
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


class TestShutdown:
    def test_sigterm_clean_exit(self, tmp_path: Path) -> None:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18775",
                "--storage-root",
                str(tmp_path / "storage"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        try:
            time.sleep(3)
            assert proc.poll() is None
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            assert proc.returncode == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_no_orphan_after_shutdown(self, tmp_path: Path) -> None:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18776",
                "--storage-root",
                str(tmp_path / "storage"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        try:
            time.sleep(3)
            assert proc.poll() is None
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            # The lock should be released; a new instance can acquire it.
            storage = tmp_path / "storage"
            paths = resolve_storage_paths(storage)
            fd = acquire_instance_lock(paths.runtime)
            release_instance_lock(fd)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_restart_after_shutdown(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage"
        # First instance.
        proc1 = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18777",
                "--storage-root",
                str(storage),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        time.sleep(3)
        assert proc1.poll() is None
        proc1.send_signal(signal.SIGTERM)
        proc1.wait(timeout=10)
        assert proc1.returncode == 0

        # Second instance on the same storage root.
        proc2 = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "basseparate.cli",
                "serve",
                "--no-browser",
                "--port",
                "18777",
                "--storage-root",
                str(storage),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        try:
            time.sleep(3)
            assert proc2.poll() is None, "second instance should start after first stops"
            proc2.send_signal(signal.SIGTERM)
            proc2.wait(timeout=10)
            assert proc2.returncode == 0
        finally:
            if proc2.poll() is None:
                proc2.kill()
                proc2.wait()
