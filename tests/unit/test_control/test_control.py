"""Control-window controller and fallback behavior."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pytest

from basseparate import control
from basseparate.config import runtime_paths
from basseparate.launcher import LauncherController, LauncherError, LauncherPaths


@pytest.fixture
def paths(tmp_path: Path) -> LauncherPaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    runtime = runtime_paths(mode="packaged", app_root=app, data_root=data)
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    return paths


class FakeLauncher:
    def __init__(self, paths: LauncherPaths, **_: Any) -> None:
        self.paths = paths
        self.owns_instance = True
        self.stopped = 0
        self.started = 0

    def start(self) -> str:
        self.started += 1
        return "http://127.0.0.1:4321/"

    def stop(self) -> None:
        self.stopped += 1


def test_controller_starts_waits_health_opens_once_and_stops(paths: LauncherPaths) -> None:
    fake = FakeLauncher(paths)
    opened: list[str] = []
    checks: list[str] = []
    controller = LauncherController(
        paths,
        launcher_factory=lambda p, **kw: fake,
        health_check=lambda url: checks.append(url) or True,
        browser_open=lambda url: opened.append(url) or True,
        health_timeout=1,
        sleep=lambda _: None,
    )
    assert controller.start() == "http://127.0.0.1:4321/"
    assert checks == ["http://127.0.0.1:4321/"]
    assert opened == ["http://127.0.0.1:4321/"]
    assert controller.start() == "http://127.0.0.1:4321/"
    assert fake.started == 1
    assert opened == ["http://127.0.0.1:4321/"]
    paths.server_log.write_text("line one\nline two\n")
    assert "line two" in controller.log_tail()
    assert "not running" in controller.status()
    controller.stop()
    assert fake.stopped == 1


def test_controller_fails_when_health_never_arrives(paths: LauncherPaths) -> None:
    fake = FakeLauncher(paths)
    controller = LauncherController(
        paths,
        launcher_factory=lambda p, **kw: fake,
        health_check=lambda _: False,
        browser_open=lambda _: True,
        health_timeout=0.01,
        sleep=lambda _: None,
    )
    with pytest.raises(LauncherError, match="did not become healthy"):
        controller.start()
    assert fake.stopped == 1


def test_control_falls_back_without_tk_or_display(
    paths: LauncherPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> Any:
        raise ImportError("Tk is not installed")

    monkeypatch.setattr(control, "_load_tk", unavailable)
    assert control.run_control(paths) is None
    error = capsys.readouterr().err
    assert "control window unavailable" in error
    assert str(paths.server_log) in error


def test_control_falls_back_without_display(
    paths: LauncherPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class TclError(Exception):
        pass

    def unavailable() -> Any:
        raise TclError("no display name")

    monkeypatch.setattr(control, "_load_tk", unavailable)
    assert control.run_control(paths) is None
    error = capsys.readouterr().err
    assert "no graphical display" in error
    assert str(paths.server_log) in error


def test_native_wrapper_sources_and_desktop_entry() -> None:
    root = Path(__file__).resolve().parents[3]
    c_source = (root / "packaging/windows/palm_launcher.c").read_text()
    native = root / "packaging/windows/PALM.exe"
    assert native.read_bytes()[:2] == b"MZ"
    assert native.stat().st_size > 4096
    assert "wWinMain" in c_source
    assert "pythonw.exe" in c_source
    assert "CreateProcessW" in c_source
    assert "CREATE_NO_WINDOW" in c_source
    assert "--window" in c_source
    assert "GetModuleFileNameW" in c_source
    assert "GetModuleFileNameW" in c_source
    desktop = (root / "packaging/launcher/palm.desktop").read_text()
    assert "Terminal=false" in desktop
    assert "Exec=palm --window" in desktop
    command = (root / "palm.cmd").read_bytes().decode()
    assert "--console" in command
    assert "%*" in command
    mac = (root / "packaging/macos/PALM.app/Contents/MacOS/palm").read_text()
    assert "set -- --window" in mac
    assert 'exec "$APP_ROOT/bin/palm" "$@"' in mac


def test_control_window_starts_and_quits_with_shared_controller() -> None:
    from types import SimpleNamespace

    class Var:
        def __init__(self, _root: Any, value: str = "") -> None:
            self.value = value

        def set(self, value: str) -> None:
            self.value = value

    class Widget:
        def grid(self, **_kwargs: Any) -> None:
            pass

        def pack(self, **_kwargs: Any) -> None:
            pass

        def configure(self, **_kwargs: Any) -> None:
            pass

        def insert(self, *_args: Any) -> None:
            pass

        def delete(self, *_args: Any) -> None:
            pass

        def columnconfigure(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def rowconfigure(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def winfo_exists(self) -> bool:
            return True

        def lift(self) -> None:
            pass

    class FakeFrame(Widget):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class FakeLabel(Widget):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class FakeButton(Widget):
        def __init__(self, *_args: Any, command: Any = None, **_kwargs: Any) -> None:
            self.command = command

    class FakeText(Widget):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.value = ""

    class Root:
        def __init__(self) -> None:
            self.destroyed = False
            self.callback: Any = None

        def title(self, _value: str) -> None:
            pass

        def minsize(self, *_args: Any) -> None:
            pass

        def protocol(self, *_args: Any) -> None:
            pass

        def after(self, _delay: int, callback: Any) -> None:
            self.callback = callback

        def columnconfigure(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def rowconfigure(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def destroy(self) -> None:
            self.destroyed = True

    class Ttk:
        Frame = FakeFrame
        Label = FakeLabel
        Button = FakeButton

    class Tk:
        StringVar = Var
        Toplevel = FakeFrame
        Text = FakeText

    class Controller:
        paths = SimpleNamespace(runtime=SimpleNamespace(data_root=Path("/data")))

        def __init__(self) -> None:
            self.stopped = 0

        def start(self) -> str:
            return "http://127.0.0.1:4321/"

        def open_browser(self) -> bool:
            return True

        def log_tail(self, _lines: int = 40) -> str:
            return "log"

        def stop(self) -> None:
            self.stopped += 1

    root = Root()
    controller = Controller()
    actions: list[str] = []
    cancelled: list[bool] = []
    window = control.ControlWindow(  # type: ignore[arg-type]
        root,
        controller,
        ttk=Ttk,
        tk=Tk,
        update_action=lambda: "checked",
        uninstall_action=lambda: actions.append("uninstall") or "launched",
        confirm_uninstall=lambda: cancelled.append(True) or False,
        quit_action=lambda: actions.append("quit") or "launched",
    )
    window.start()
    assert "Running at" in window.status.value
    window.check_update()
    assert window.detail.value == "checked"
    window.uninstall()
    assert actions == []
    window._confirm_uninstall = lambda: True
    window.uninstall()
    assert actions == ["uninstall"]
    assert root.callback is not None
    window.quit()
    assert actions == ["uninstall", "quit"]
    assert controller.stopped == 1
    assert root.destroyed


def test_window_and_console_are_explicit_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate import launcher as launcher_module

    parser = launcher_module.build_parser()
    assert parser.parse_args(["--window"]).window is True
    assert parser.parse_args(["--console"]).console is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--window", "--console"])

    called: list[Any] = []

    def fake_control(paths: LauncherPaths) -> int:
        called.append(paths)
        return 0

    monkeypatch.setattr(control, "run_control", fake_control)
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setenv("DISPLAY", ":0")
    assert launcher_module.main(["--window", "--data-dir", str(tmp_path)]) == 0
    assert len(called) == 1


def test_check_for_updates_reports_no_update_and_network_error(
    paths: LauncherPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from basseparate.updater import UpdateError

    metadata = SimpleNamespace(
        channel="linux-x86_64",
        version="0.1.0",
        app_root=paths.runtime.app_root,
        data_root=paths.runtime.data_root,
    )
    monkeypatch.setattr(control, "load_metadata", lambda *_a, **_k: metadata)
    monkeypatch.setattr(control, "check_for_update", lambda *_a, **_k: None)
    assert "No update available" in control.check_for_updates(paths)

    def network_error(*_a: Any, **_k: Any) -> Any:
        raise UpdateError("network unavailable")

    monkeypatch.setattr(control, "check_for_update", network_error)
    message = control.check_for_updates(paths)
    assert message.startswith("Update check failed")
    assert "network unavailable" in message


def test_check_for_updates_stages_verified_asset(
    paths: LauncherPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from basseparate.updater import UpdateAsset

    metadata = SimpleNamespace(
        channel="linux-x86_64",
        version="0.1.0",
        app_root=paths.runtime.app_root,
        data_root=paths.runtime.data_root,
    )
    candidate = UpdateAsset(
        channel="linux-x86_64",
        version="0.2.0",
        name="PALM-0.2.0-linux-x86_64.tar.gz",
        url="https://example.invalid/new.tar.gz",
        sha256="a" * 64,
        kind="tar.gz",
    )
    staged = paths.runtime.data_root / "updates/0.2.0/new.tar.gz"
    helper = paths.runtime.app_root / "updaters/update_helper.py"
    helper.parent.mkdir()
    helper.write_text("# helper")
    monkeypatch.setattr(control, "load_metadata", lambda *_a, **_k: metadata)
    monkeypatch.setattr(control, "check_for_update", lambda *_a, **_k: candidate)
    monkeypatch.setattr(control, "stage_update", lambda *_a, **_k: staged)
    message = control.check_for_updates(paths)
    assert "staged" in message
    assert (paths.runtime.data_root / "updates/helpers/update_helper.py").is_file()
    assert (paths.runtime.data_root / "updates/pending.json").is_file()


def test_macos_helper_layout_and_install_root(tmp_path: Path) -> None:
    bundle = tmp_path / "PALM.app"
    app = bundle / "Contents" / "Resources" / "app"
    data = tmp_path / "data"
    app.mkdir(parents=True)
    data.mkdir()
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    (bundle / "Contents" / "MacOS" / "palm").write_text("#!/bin/sh\n")
    (bundle / "Contents" / "Resources" / "updaters").mkdir()
    helper = bundle / "Contents" / "Resources" / "updaters" / "uninstall_helper.py"
    helper.write_text("# helper")
    runtime = runtime_paths(mode="packaged", app_root=app, data_root=data)
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    copied = control._external_helper(paths, "uninstall_helper.py")
    assert copied == data / "updates/helpers/uninstall_helper.py"
    assert copied.read_text() == "# helper"
    assert control._install_root(app) == bundle
    assert control._restart_command(bundle) == [str(bundle / "Contents/MacOS/palm"), "--window"]


def test_launch_pending_update_and_no_pending(paths: LauncherPaths) -> None:
    assert control.launch_pending_update(paths) == "No pending update."
    helper = paths.runtime.data_root / "updates/helpers/update_helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# helper")
    (paths.runtime.app_root / "install.json").write_text(
        '{"channel": "linux-x86_64", "version": "0.1.0", "assets": {}}'
    )
    plan = paths.runtime.data_root / "updates/pending.json"
    plan.write_text(
        '{"version": "0.2.0", "app_root": "'
        + str(paths.runtime.app_root)
        + '", "data_root": "'
        + str(paths.runtime.data_root)
        + '", "helper": "'
        + str(helper)
        + '"}'
    )
    calls: list[list[str]] = []
    message = control.launch_pending_update(
        paths, popen=lambda command, **kw: calls.append(command)
    )
    assert "launched" in message
    assert calls and "--plan" in calls[0]


def test_windows_helper_layout_copies_outside_app(tmp_path: Path) -> None:
    app = tmp_path / "PALM app ü"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    (app / "updaters").mkdir()
    (app / "updaters" / "update_helper.py").write_text("# update")
    (app / "updaters" / "uninstall_helper.py").write_text("# uninstall")
    runtime = runtime_paths(mode="packaged", app_root=app, data_root=data)
    paths = LauncherPaths.from_runtime(runtime)
    paths.ensure()
    for name in ("update_helper.py", "uninstall_helper.py"):
        copied = control._external_helper(paths, name)
        assert copied == data / "updates/helpers" / name
        assert copied.is_file()
        assert not copied.resolve().is_relative_to(app.resolve())
    assert control._install_root(app) == app


def test_copied_uninstall_helper_runs_with_real_plan(paths: LauncherPaths) -> None:
    import subprocess
    import sys as _sys

    from basseparate.updater import UninstallPlan, write_uninstall_plan

    app = paths.runtime.app_root
    helper = app / "updaters" / "uninstall_helper.py"
    helper.parent.mkdir()
    source_root = Path(__file__).resolve().parents[3] / "packaging/updaters"
    for name in ("update_helper.py", "uninstall_helper.py"):
        (app / "updaters" / name).write_text((source_root / name).read_text())
    copied = control._external_helper(paths, "uninstall_helper.py")
    assert (copied.parent / "update_helper.py").is_file()
    plan = write_uninstall_plan(UninstallPlan(app, paths.runtime.data_root, False, 0, ()), copied)
    result = subprocess.run([_sys.executable, str(copied), "--plan", str(plan)], check=False)
    assert result.returncode == 0
    assert not app.exists()
    assert paths.runtime.data_root.is_dir()


def test_stale_and_second_quit_do_not_relaunch(paths: LauncherPaths) -> None:
    helper = paths.runtime.data_root / "updates/helpers/update_helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# helper")
    (paths.runtime.app_root / "install.json").write_text(
        '{"channel": "linux-x86_64", "version": "0.2.0", "assets": {}}'
    )
    plan = paths.runtime.data_root / "updates/pending.json"
    plan.write_text(
        '{"version": "0.1.0", "app_root": "'
        + str(paths.runtime.app_root)
        + '", "data_root": "'
        + str(paths.runtime.data_root)
        + '", "asset": "'
        + str(paths.runtime.data_root / "updates/old.tar.gz")
        + '", "helper": "'
        + str(helper)
        + '"}'
    )
    assert "No newer" in control.launch_pending_update(paths)
    assert not plan.exists()
    plan.write_text(
        '{"version": "0.3.0", "app_root": "'
        + str(paths.runtime.app_root)
        + '", "data_root": "'
        + str(paths.runtime.data_root)
        + '", "helper": "'
        + str(helper)
        + '"}'
    )
    calls: list[list[str]] = []
    assert "launched" in control.launch_pending_update(
        paths, popen=lambda command, **kw: calls.append(command)
    )
    assert "already been launched" in control.launch_pending_update(
        paths, popen=lambda command, **kw: calls.append(command)
    )
    assert len(calls) == 1


def test_uninstall_action_auto_closes_window(paths: LauncherPaths) -> None:
    # The existing fake-window test covers confirmation; this checks the
    # scheduled quit callback is installed after a successful action.
    from types import SimpleNamespace

    class Root:
        destroyed = False
        callback: Any = None

        def after(self, _delay: int, callback: Any) -> None:
            self.callback = callback

        def destroy(self) -> None:
            self.destroyed = True

    window = control.ControlWindow.__new__(control.ControlWindow)
    window.root = Root()
    window.controller = SimpleNamespace(stop=lambda: None)
    window.detail = SimpleNamespace(set=lambda _value: None)
    window._confirm_uninstall = lambda: True
    window._uninstall_action = lambda: "launched"
    window._quitting = False
    window._quit_action = None
    window.uninstall()
    assert window.root.callback is not None


def test_external_python_copies_minimal_runtime_for_all_layouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = {
        "windows": ("app", "python/python.exe", ["python311.dll", "python311.zip"]),
        "linux": ("app", "python/bin/python3.11", ["python/lib/libpython3.11.so"]),
        "macos": (
            "PALM.app/Contents/Resources/app",
            "python/bin/python3.11",
            ["python/lib/libpython3.11.dylib"],
        ),
    }
    for name, (app_rel, exe_rel, extras) in cases.items():
        root = tmp_path / name
        app = root / app_rel
        data = root / "data"
        exe = root / app_rel / exe_rel
        exe.parent.mkdir(parents=True)
        exe.write_text("exe")
        for extra in extras:
            target = root / app_rel / extra
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lib")
        if name == "windows":
            (root / app_rel / "python311.zip").write_text("stdlib")
        runtime = runtime_paths(mode="packaged", app_root=app, data_root=data)
        paths = LauncherPaths.from_runtime(runtime)
        paths.ensure()
        monkeypatch.setattr(control.sys, "executable", str(exe))
        copied = control._external_python(paths)
        assert copied.is_file()
        assert not copied.resolve().is_relative_to(data.resolve())
        assert not copied.resolve().is_relative_to(app.resolve())
