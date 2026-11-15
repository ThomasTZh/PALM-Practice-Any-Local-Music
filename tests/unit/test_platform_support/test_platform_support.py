"""Platform boundary: portable locks, processes, interpreters and tool paths."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from basseparate import platform_support as ps
from basseparate.config import RuntimePaths


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.signals: list[int] = []

    def is_running(self) -> bool:
        return True

    def status(self) -> str:
        return "running"

    def cmdline(self) -> list[str]:
        return ["python", "-m", "palm"]

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class FakePsutil(types.SimpleNamespace):
    STATUS_ZOMBIE = "zombie"

    def __init__(self, process: FakeProcess | None = None) -> None:
        super().__init__()
        self.process = process or FakeProcess()
        self.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        self.AccessDenied = type("AccessDenied", (Exception,), {})

    def Process(self, _pid: int) -> FakeProcess:
        return self.process


def test_posix_file_lock_is_exclusive(tmp_path: Path) -> None:
    first = ps.FileLock(tmp_path / "locks" / "one.lock", blocking=False)
    second = ps.FileLock(tmp_path / "locks" / "one.lock", blocking=False)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_windows_file_lock_uses_msvcrt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    fake = types.SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        LK_UNLCK=3,
        locking=lambda fd, mode, size: calls.append((fd, mode)),
    )
    monkeypatch.setattr(ps, "WINDOWS", True)
    monkeypatch.setattr(ps, "POSIX", False)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    lock = ps.FileLock(tmp_path / "one.lock", blocking=False)
    assert lock.acquire() is True
    lock.release()
    assert [mode for _, mode in calls] == [fake.LK_NBLCK, fake.LK_UNLCK]


def test_windows_interpreter_and_plugin_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Scripts").mkdir()
    (tmp_path / "Scripts" / "python.exe").write_text("python")
    monkeypatch.setattr(ps, "WINDOWS", True)
    monkeypatch.setattr(ps, "MACOS", False)
    assert ps.venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"
    assert ps.plugin_suffix() == ".dll"
    assert ps.plugin_glob("qm") == "qm.dll"


def test_macos_plugin_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ps, "WINDOWS", False)
    monkeypatch.setattr(ps, "MACOS", True)
    assert ps.plugin_suffix() == ".dylib"


def test_psutil_process_inspection_and_termination(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess()
    fake = FakePsutil(process)
    monkeypatch.setattr(ps, "psutil", fake)
    assert ps.process_is_alive(123) is True
    assert ps.process_command(123) == "python -m palm"
    assert ps.signal_process(123, 15) is True
    assert ps.terminate_process(123) is True
    assert ps.kill_process(123) is True
    assert process.signals == [15]
    assert process.terminated and process.killed


def test_ffmpeg_overrides_win(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PALM_FFMPEG", str(tmp_path / "ffmpeg"))
    monkeypatch.setenv("BASSEPARATE_FFPROBE", str(tmp_path / "ffprobe"))
    assert ps.ffmpeg_binary(which=lambda _name: "/bin/other") == str(tmp_path / "ffmpeg")
    assert ps.ffprobe_binary(which=lambda _name: "/bin/other") == str(tmp_path / "ffprobe")


def test_hidden_process_flags_are_windows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ps, "WINDOWS", False)
    assert ps.hidden_process_kwargs() == {}
    monkeypatch.setattr(ps, "WINDOWS", True)
    flags = ps.hidden_process_kwargs()
    assert "creationflags" in flags
    assert "startupinfo" in flags


def test_packaged_data_root_uses_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    env = tmp_path / "localappdata"
    app.mkdir()
    env.mkdir()
    monkeypatch.setattr(ps, "WINDOWS", True)
    monkeypatch.setattr(ps, "MACOS", False)
    monkeypatch.setenv("LOCALAPPDATA", str(env))
    monkeypatch.delenv("PALM_DATA_DIR", raising=False)
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app)
    assert runtime.data_root == env / "palm"


def test_packaged_data_root_uses_macos_application_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    home = tmp_path / "home"
    app.mkdir()
    home.mkdir()
    monkeypatch.setattr(ps, "WINDOWS", False)
    monkeypatch.setattr(ps, "MACOS", True)
    monkeypatch.setattr(ps.Path, "home", classmethod(lambda _cls: home))
    monkeypatch.delenv("PALM_DATA_DIR", raising=False)
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app)
    assert runtime.data_root == home / "Library" / "Application Support" / "palm"


def test_setup_checks_honour_ffmpeg_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate.setup.checks import system_checks

    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    monkeypatch.setenv("PALM_FFMPEG", str(tmp_path / "custom-ffmpeg"))
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)
    checks = system_checks(runtime, which=lambda _name: None, disk_probe=lambda _p: (0, 0, 10**12))
    assert checks["ffmpeg"]["ok"] is True
    assert checks["ffmpeg"]["path"] == str(tmp_path / "custom-ffmpeg")


def test_packaged_windows_bundled_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate import config

    app = tmp_path / "app"
    data = tmp_path / "data"
    bundled = app / "python" / "python.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("python")
    monkeypatch.setattr(config, "WINDOWS", True)
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)
    assert runtime.bundled_python == bundled


def test_packaged_windows_environment_uses_scripts_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate.setup.environments import environment_status

    app = tmp_path / "app"
    data = tmp_path / "data"
    python = data / "environments" / "cpu" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("python")
    app.mkdir()
    monkeypatch.setattr(ps, "WINDOWS", True)
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)
    status = environment_status("cpu", runtime)
    assert status["installed"] is True
    assert status["python"] == str(python)


def test_psutil_is_a_required_pinned_dependency() -> None:
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    root_project = tomllib.loads((root / "pyproject.toml").read_text())
    runtime_project = tomllib.loads(
        (root / "packaging" / "app-runtime" / "pyproject.toml").read_text()
    )
    assert "psutil==7.2.2" in root_project["project"]["dependencies"]
    assert "psutil==7.2.2" in runtime_project["project"]["dependencies"]
    for lock in (root / "uv.lock", root / "packaging/app-runtime/uv.lock"):
        text = lock.read_text()
        assert 'name = "psutil"' in text
        assert 'version = "7.2.2"' in text


def test_missing_psutil_fails_with_a_clear_message() -> None:
    import subprocess

    result = subprocess.run(
        [
            str(Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"),
            "-c",
            "import sys; sys.modules['psutil'] = None; import basseparate.platform_support",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")},
    )
    assert result.returncode != 0
    assert "requires psutil" in result.stderr


def test_psutil_stop_validation_checks_recorded_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from basseparate import launcher

    commands = {
        111: "python -m basseparate.cli serve --data-root /data",
        222: "python -m basseparate.launcher --data-root /data",
    }
    process = FakeProcess()
    fake = FakePsutil(process)
    fake.Process = lambda pid: FakeBoundProcess(commands[pid])
    monkeypatch.setattr(ps, "psutil", fake)
    state = launcher.RunState(
        url="http://127.0.0.1:1/",
        port=1,
        pid=111,
        launcher_pid=222,
        started_at="2026-01-01T00:00:00Z",
        mode="packaged",
        app_root="/app",
        data_root="/data",
    )
    health = launcher.inspect_run_state(state)
    assert health.server_alive is True
    assert health.launcher_alive is True
    assert health.server_valid is True
    assert health.launcher_valid is True


class FakeBoundProcess:
    def __init__(self, command: str) -> None:
        self.command = command

    def is_running(self) -> bool:
        return True

    def status(self) -> str:
        return "running"

    def cmdline(self) -> list[str]:
        return self.command.split()
