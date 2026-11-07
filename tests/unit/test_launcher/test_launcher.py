"""PALM launcher: roots, single instance, URL, signals and CLI options."""

from __future__ import annotations

import io
import json
import signal
from pathlib import Path
from typing import Any

import pytest

from basseparate import launcher
from basseparate.config import RuntimePaths, runtime_paths
from basseparate.doctor import DoctorCheck, DoctorReport
from basseparate.launcher import (
    InstanceLock,
    Launcher,
    LauncherPaths,
    RunState,
    build_parser,
    build_server_command,
    launcher_environment,
    main,
    open_terminal,
    parse_bootstrap_url,
    read_run_state,
    run_doctor,
    run_setup,
    run_status,
    run_stop,
    terminal_active,
    terminal_command,
    wait_for_run_state,
    write_run_state,
)


@pytest.fixture(autouse=True)
def clear_palm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PALM_MODE",
        "PALM_APP_ROOT",
        "PALM_DATA_DIR",
        "BASSEPARATE_DATA_DIR",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def runtime(tmp_path: Path) -> RuntimePaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    return runtime_paths(mode="packaged", app_root=app, data_root=data)


def make_state(url: str = "http://127.0.0.1:4123/") -> RunState:
    return RunState(
        url=url,
        port=4123,
        pid=111,
        launcher_pid=222,
        started_at="2026-01-01T00:00:00+00:00",
        mode="packaged",
        app_root="/app",
        data_root="/data",
    )


def test_paths_and_environment_stay_under_data_root(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    (runtime.app_root / "src").mkdir()
    paths = LauncherPaths.from_runtime(runtime)
    assert paths.run_dir == runtime.data_root / "run"
    assert paths.logs_root == runtime.data_root / "logs"
    assert paths.state_file == paths.run_dir / "server.json"
    paths.ensure()
    assert paths.run_dir.is_dir()
    assert paths.logs_root.is_dir()
    assert not (runtime.app_root / "logs").exists()

    env = launcher_environment(runtime, base={"PATH": "/bin"})
    assert env["PALM_MODE"] == "packaged"
    assert env["PALM_APP_ROOT"] == str(runtime.app_root)
    assert env["PALM_DATA_DIR"] == str(runtime.data_root)
    assert env["BASSEPARATE_DATA_DIR"] == str(runtime.data_root)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONPATH"].split(":")[0] == str(runtime.app_root / "src")

    command = build_server_command(runtime, port=0, python=Path("/app/bin/python"))
    assert command[:4] == ["/app/bin/python", "-m", "basseparate.cli", "serve"]
    assert "--no-browser" in command
    assert command[command.index("--data-root") + 1] == str(runtime.data_root)
    assert command[command.index("--web-dir") + 1] == str(runtime.web_dir)


def test_source_mode_resolves_app_root() -> None:
    source = runtime_paths()
    assert source.mode == "source"
    assert launcher_environment(source, base={})["PALM_MODE"] == "source"
    paths = LauncherPaths.from_runtime(source)
    assert paths.run_dir.is_relative_to(source.data_root)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("bootstrap: http://127.0.0.1:4123/\n", "http://127.0.0.1:4123/"),
        ("bootstrap: http://localhost:9\n", "http://localhost:9/"),
        ("bootstrap: http://[::1]:8000/\n", "http://[::1]:8000/"),
        ("basseparate studio: http://127.0.0.1:1/", None),
        ("bootstrap: https://127.0.0.1:1/", None),
        ("bootstrap: http://example.com:1/", None),
        ("bootstrap: http://127.0.0.1/", None),
        ("bootstrap:", None),
    ],
)
def test_parse_bootstrap_url(line: str, expected: str | None) -> None:
    assert parse_bootstrap_url(line) == expected


def test_run_state_round_trip_and_corruption(tmp_path: Path) -> None:
    path = tmp_path / "run" / "server.json"
    state = make_state()
    write_run_state(path, state)
    assert read_run_state(path) == state
    payload = json.loads(path.read_text())
    assert payload["url"] == state.url
    assert payload["version"] == 1
    path.write_text("not json")
    assert read_run_state(path) is None
    assert wait_for_run_state(path, timeout=0, sleep=lambda _: None) is None


def test_instance_lock_is_exclusive(runtime: RuntimePaths) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    first = InstanceLock(paths)
    second = InstanceLock(paths)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_second_launch_reports_running_url(
    runtime: RuntimePaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    holder = InstanceLock(paths)
    assert holder.acquire()
    state = make_state()
    write_run_state(paths.state_file, state)
    opened: list[str] = []
    second = Launcher(
        paths,
        open_browser=True,
        browser_open=lambda url: opened.append(url) or True,
        state_timeout=0.1,
        sleep=lambda _: None,
    )
    try:
        assert second.run() == 0
    finally:
        holder.release()
    assert opened == [state.url]
    assert state.url in capsys.readouterr().out


def test_launcher_starts_existing_cli_and_records_url(
    runtime: RuntimePaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    captured: dict[str, Any] = {}

    class FakeStream:
        def __init__(self) -> None:
            self._lines = iter(
                [
                    "basseparate studio: http://127.0.0.1:4321/\n",
                    "bootstrap: http://127.0.0.1:4321/\n",
                ]
            )

        def __iter__(self) -> FakeStream:
            return self

        def __next__(self) -> str:
            return next(self._lines)

        def close(self) -> None:
            captured["closed"] = True

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            self.stdout = FakeStream()
            self.returncode = 0
            self.signals: list[int] = []

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def send_signal(self, signum: int) -> None:
            self.signals.append(signum)

        def kill(self) -> None:
            self.returncode = -9

    process = FakeProcess()

    def factory(command: list[str], **kwargs: Any) -> FakeProcess:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return process

    opened: list[str] = []
    launcher_instance = Launcher(
        paths,
        port=0,
        browser_open=lambda url: opened.append(url) or True,
        popen_factory=factory,
        startup_timeout=2,
        state_timeout=0.1,
    )
    assert launcher_instance.run() == 0
    assert captured["command"][1:4] == ["-m", "basseparate.cli", "serve"]
    assert "--data-root" in captured["command"]
    assert captured["env"]["PALM_DATA_DIR"] == str(runtime.data_root)
    assert opened == ["http://127.0.0.1:4321/"]
    assert not paths.state_file.exists()  # cleaned up after the child exits
    assert "bootstrap: http://127.0.0.1:4321/" in (paths.server_log.read_text())
    out = capsys.readouterr().out
    assert "http://127.0.0.1:4321/" in out


def test_pump_streams_live_lines_and_keeps_server_log(runtime: RuntimePaths) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    output = io.StringIO()
    instance = Launcher(paths, open_browser=False, stream=output)
    instance._server_log = paths.server_log.open("a", encoding="utf-8")
    try:
        instance._pump(
            io.StringIO(
                "basseparate studio: http://127.0.0.1:4321/\nbootstrap: http://127.0.0.1:4321/\n"
            )
        )
    finally:
        if instance._server_log is not None:
            instance._server_log.close()
    assert "bootstrap: http://127.0.0.1:4321/" in output.getvalue()
    assert "bootstrap: http://127.0.0.1:4321/" in paths.server_log.read_text()
    assert instance._url == "http://127.0.0.1:4321/"


def test_terminal_command_selects_the_first_available_emulator() -> None:
    seen: list[str] = []

    def which(name: str) -> str | None:
        seen.append(name)
        return "/usr/bin/xterm" if name == "xterm" else None

    command = terminal_command(["python", "-m", "basseparate.launcher"], which=which)
    assert command == ["/usr/bin/xterm", "-e", "python", "-m", "basseparate.launcher"]
    assert seen == ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]


def test_open_terminal_attaches_a_guarded_child_and_falls_back() -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def popen(command: list[str], **kwargs: Any) -> object:
        calls.append((command, kwargs))
        return object()

    def which(name: str) -> str | None:
        return "/usr/bin/x-terminal-emulator" if name == "x-terminal-emulator" else None

    assert open_terminal(
        ["--no-browser", "--data-dir", "/tmp/palm-data"],
        which=which,
        popen=popen,
        environment={"DISPLAY": ":0"},
    )
    command, kwargs = calls[0]
    assert command[:2] == ["/usr/bin/x-terminal-emulator", "-e"]
    assert "--no-terminal" in command
    assert command[-3:] == ["--no-browser", "--data-dir", "/tmp/palm-data"]
    assert kwargs["env"][launcher.TERMINAL_MARKER] == "1"
    assert kwargs["start_new_session"] is True

    before = len(calls)
    assert not open_terminal(
        [],
        which=which,
        popen=popen,
        environment={launcher.TERMINAL_MARKER: "1"},
    )
    assert len(calls) == before
    assert not open_terminal([], which=lambda _name: None, popen=popen)
    assert terminal_active({launcher.TERMINAL_MARKER: "1"}) is True
    assert terminal_active({}) is False


def test_forward_signal_reaches_child() -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.signals: list[int] = []

        def poll(self) -> int | None:
            return None

        def send_signal(self, signum: int) -> None:
            self.signals.append(signum)

    process = FakeProcess()
    launcher.forward_signal(process, signal.SIGTERM)  # type: ignore[arg-type]
    assert process.signals == [signal.SIGTERM]


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_handler_stops_and_cleans_up(tmp_path: Path, signum: int) -> None:
    runtime = runtime_paths(mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data")
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()

    class FakeProcess:
        pid = 7

        def __init__(self) -> None:
            self.signals: list[int] = []
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def send_signal(self, signum: int) -> None:
            self.signals.append(signum)
            self.returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    process = FakeProcess()
    launcher_instance = Launcher(paths, open_browser=False)
    assert launcher_instance._lock.acquire()
    write_run_state(paths.state_file, make_state())
    launcher_instance._server = process  # type: ignore[assignment]
    launcher_instance._handle_signal(signum, None)
    assert launcher_instance._stop.is_set()
    assert process.signals == [signum]
    launcher_instance._cleanup()
    assert not paths.state_file.exists()
    assert not launcher_instance._lock.held


def test_setup_and_doctor_do_not_write_app_root(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = sorted(str(path) for path in runtime.app_root.rglob("*"))
    assert run_setup(runtime) in {0, 1}
    assert runtime.setup_state.is_file()
    assert (runtime.data_root / "run").is_dir()
    assert sorted(str(path) for path in runtime.app_root.rglob("*")) == before

    report = DoctorReport(
        (
            DoctorCheck(
                id="python",
                label="Python",
                status="ok",
                detail="3.11",
                required=True,
            ),
        )
    )
    monkeypatch.setattr(launcher, "diagnose", lambda _layout: report)
    stream = io.StringIO()
    assert run_doctor(runtime, stream=stream) == 0
    assert "doctor: ok" in stream.getvalue()
    assert sorted(str(path) for path in runtime.app_root.rglob("*")) == before


def _write_health_state(paths: LauncherPaths, data_root: Path) -> RunState:
    state = make_state()
    state = RunState(
        url=state.url,
        port=state.port,
        pid=111,
        launcher_pid=222,
        started_at=state.started_at,
        mode="packaged",
        app_root=str(data_root.parent / "app"),
        data_root=str(data_root),
    )
    write_run_state(paths.state_file, state)
    return state


def test_status_reports_url_roots_and_pids_without_starting(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    _write_health_state(paths, runtime.data_root)
    monkeypatch.setattr(launcher, "process_is_alive", lambda pid: pid in {111, 222})
    monkeypatch.setattr(
        launcher,
        "process_command",
        lambda pid: (
            "python -m basseparate.cli serve --data-root /data"
            if pid == 111
            else "python -m basseparate.launcher"
        ),
    )
    output = io.StringIO()
    assert run_status(paths, stream=output) == 0
    text = output.getvalue()
    assert "palm: URL http://127.0.0.1:4123/" in text
    assert f"palm: data root {runtime.data_root}" in text
    assert "palm: server pid 111, launcher pid 222" in text


def test_status_reports_stale_state(runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    _write_health_state(paths, runtime.data_root)
    monkeypatch.setattr(launcher, "process_is_alive", lambda _pid: False)
    output = io.StringIO()
    assert run_status(paths, stream=output) == 1
    assert "stale run state" in output.getvalue()
    assert paths.state_file.exists()


def test_stop_validates_and_terminates_launcher_and_server(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    _write_health_state(paths, runtime.data_root)
    alive = {111, 222}
    signals: list[tuple[int, int]] = []

    def kill(pid: int, signum: int) -> bool:
        signals.append((pid, signum))
        alive.discard(pid)
        return True

    monkeypatch.setattr(launcher, "process_is_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        launcher,
        "process_command",
        lambda pid: (
            "python -m basseparate.cli serve --data-root /data"
            if pid == 111
            else "python -m basseparate.launcher"
        ),
    )
    monkeypatch.setattr(launcher, "signal_process", kill)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    output = io.StringIO()
    assert run_stop(paths, stream=output, timeout=1) == 0
    assert signals == [(222, signal.SIGTERM), (111, signal.SIGTERM)]
    assert "stopped launcher pid 222" in output.getvalue()
    assert "server pid 111" in output.getvalue()
    assert not paths.state_file.exists()


def test_stop_cleans_stale_state_and_refuses_unrelated_pids(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    _write_health_state(paths, runtime.data_root)
    monkeypatch.setattr(launcher, "process_is_alive", lambda _pid: False)
    monkeypatch.setattr(launcher, "signal_process", lambda _pid, _signum: False)
    output = io.StringIO()
    assert run_stop(paths, stream=output, sleep=lambda _seconds: None) == 0
    assert "stale launcher, server process record removed" in output.getvalue()
    assert not paths.state_file.exists()

    _write_health_state(paths, runtime.data_root)
    monkeypatch.setattr(launcher, "process_is_alive", lambda _pid: True)
    monkeypatch.setattr(launcher, "process_command", lambda _pid: "some other program")
    output = io.StringIO()
    assert run_stop(paths, stream=output, sleep=lambda _seconds: None) == 0
    assert "command does not match PALM" in output.getvalue()
    assert not paths.state_file.exists()


def test_stop_refuses_another_data_root(
    runtime: RuntimePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    state = _write_health_state(paths, runtime.data_root)
    state = RunState(
        url=state.url,
        port=state.port,
        pid=state.pid,
        launcher_pid=state.launcher_pid,
        started_at=state.started_at,
        mode=state.mode,
        app_root=state.app_root,
        data_root="/some/other/root",
    )
    write_run_state(paths.state_file, state)
    monkeypatch.setattr(launcher, "process_is_alive", lambda _pid: True)
    monkeypatch.setattr(launcher, "process_command", lambda _pid: "basseparate.launcher")
    assert run_stop(paths, stream=io.StringIO(), sleep=lambda _seconds: None) == 2
    assert paths.state_file.exists()


def test_parser_defaults_and_flags() -> None:
    args = build_parser().parse_args([])
    assert args.port == 0
    assert args.no_browser is False
    assert args.no_terminal is False
    assert args.stop is False
    assert args.status is False
    assert args.setup is False
    assert args.doctor is False
    assert args.data_dir is None
    args = build_parser().parse_args(
        ["--no-browser", "--port", "8123", "--data-dir", "data", "--setup"]
    )
    assert args.port == 8123
    assert args.no_browser is True
    assert args.data_dir == Path("data")
    assert args.setup is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--setup", "--doctor"])
    assert build_parser().parse_args(["--detach"]).no_terminal is True
    assert build_parser().parse_args(["--no-terminal"]).no_terminal is True
    assert main(["--port", "70000"]) == 2
    assert build_parser().parse_args(["--stop"]).stop is True
    assert build_parser().parse_args(["--status"]).status is True


def test_desktop_entry_is_terminal_first() -> None:
    entry = (Path(__file__).resolve().parents[3] / "packaging/launcher/palm.desktop").read_text()
    assert "Terminal=true" in entry
    assert "Exec=palm" in entry
    readme = (Path(__file__).resolve().parents[3] / "packaging/launcher/README.md").read_text()
    assert "ln -sf" in readme
    assert ".local/share/applications" in readme
