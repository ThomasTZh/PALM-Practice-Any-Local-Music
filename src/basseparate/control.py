"""Small Tk control window for the packaged PALM launcher.

The window is deliberately a thin client over ``LauncherController``: process,
health, state and logging behavior is shared with the native Windows/macOS
wrappers. It also wires Check for updates to install.json-based staging and
Uninstall to an external helper that keeps user data by default. Tk is imported
lazily so a server-only environment can still use the diagnostic CLI.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from basseparate.launcher import LauncherController, LauncherError, LauncherPaths
from basseparate.updater import (
    UninstallPlan,
    UpdateError,
    check_for_update,
    launch_helper,
    launch_uninstall_helper,
    load_metadata,
    stage_update,
    write_plan,
)


def _load_tk() -> Any:
    import tkinter as tk
    from tkinter import ttk

    return tk, ttk


class ControlWindow:
    """Status/start/stop window with wired update and uninstall actions.

    Check for updates reads install.json, verifies and stages the channel asset,
    and leaves the running app untouched until Quit. Uninstall asks for
    confirmation, stops the server and launches the external helper; projects,
    models and tools are kept unless delete-data is explicitly chosen.
    """

    def __init__(
        self,
        root: Any,
        controller: LauncherController,
        *,
        ttk: Any,
        tk: Any,
        update_action: Callable[[], str] | None = None,
        uninstall_action: Callable[[], str] | None = None,
        confirm_uninstall: Callable[[], bool] | None = None,
        quit_action: Callable[[], str] | None = None,
    ) -> None:
        self.root = root
        self.controller = controller
        self._ttk = ttk
        self._tk = tk
        self._started = False
        self._log_window: Any | None = None
        self._update_action = update_action
        self._uninstall_action = uninstall_action
        self._confirm_uninstall = confirm_uninstall or self._ask_uninstall
        self._quit_action = quit_action
        self._quitting = False
        root.title("PALM — Practice Any Local Music")
        root.minsize(520, 360)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.status = tk.StringVar(root, value="Starting…")
        self.detail = tk.StringVar(root, value="Preparing the local server")
        self._build()
        root.after(50, self.start)

    def _build(self) -> None:
        ttk = self._ttk
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        ttk.Label(frame, text="PALM", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(frame, textvariable=self.status, font=("TkDefaultFont", 12)).grid(
            row=1, column=0, sticky="w", pady=(12, 2)
        )
        ttk.Label(frame, textvariable=self.detail, wraplength=470).grid(
            row=2, column=0, sticky="w", pady=(0, 12)
        )
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew")
        for column in range(4):
            buttons.columnconfigure(column, weight=1)
        ttk.Button(buttons, text="Open browser", command=self.open_browser).grid(
            row=0, column=0, padx=3, pady=3, sticky="ew"
        )
        ttk.Button(buttons, text="View logs", command=self.view_logs).grid(
            row=0, column=1, padx=3, pady=3, sticky="ew"
        )
        ttk.Button(buttons, text="Quit", command=self.quit).grid(
            row=0, column=2, padx=3, pady=3, sticky="ew"
        )
        ttk.Button(buttons, text="Check for updates", command=self.check_update).grid(
            row=1, column=0, padx=3, pady=3, sticky="ew"
        )
        ttk.Button(buttons, text="Uninstall", command=self.uninstall).grid(
            row=1, column=1, padx=3, pady=3, sticky="ew"
        )
        self.log = self._tk.Text(frame, height=8, wrap="none", state="disabled")
        self.log.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(4, weight=1)
        frame.columnconfigure(0, weight=1)

    def start(self) -> None:
        if self._started:
            return
        try:
            url = self.controller.start()
        except (LauncherError, OSError) as error:
            self.status.set("PALM could not start")
            self.detail.set(str(error))
            self._append_log(str(error))
            return
        self._started = True
        self.status.set(f"Running at {url}")
        self.detail.set(f"Data: {self.controller.paths.runtime.data_root}")
        self.refresh_logs()

    def check_update(self) -> None:
        if self._update_action is None:
            self.detail.set("Update metadata is not configured for this install.")
            return
        try:
            self.detail.set(self._update_action())
        except Exception as error:  # user-facing helper errors must not crash Tk
            self.detail.set(f"Update check failed: {error}")

    def _ask_uninstall(self) -> bool:
        try:
            from tkinter import messagebox

            return bool(
                messagebox.askyesno(
                    "Uninstall PALM?",
                    "Stop PALM and remove the application?\n\n"
                    "Your projects, models and tools are kept by default. "
                    "Delete data separately only if you intend to remove them.",
                )
            )
        except Exception:
            return False

    def uninstall(self) -> None:
        if not self._confirm_uninstall():
            self.detail.set("Uninstall cancelled; PALM is still running.")
            return
        if self._uninstall_action is None:
            self.detail.set("Uninstall helper is not configured for this install.")
            return
        try:
            self.detail.set(self._uninstall_action())
        except Exception as error:  # user-facing helper errors must not crash Tk
            self.detail.set(f"Uninstall failed: {error}")
            return
        # The helper waits for this process; close the control window now.
        self.root.after(50, self.quit)

    def open_browser(self) -> None:
        if not self.controller.open_browser():
            self.detail.set("Open the URL shown above once the server is running.")

    def view_logs(self) -> None:
        self.refresh_logs()
        if self._log_window is not None and self._log_window.winfo_exists():
            self._log_window.lift()
            return
        window = self._tk.Toplevel(self.root)
        window.title("PALM server log")
        window.geometry("760x460")
        text = self._tk.Text(window, wrap="none", state="disabled")
        text.pack(fill="both", expand=True)
        text.configure(state="normal")
        text.insert("1.0", self.controller.log_tail(120))
        text.configure(state="disabled")
        self._log_window = window

    def refresh_logs(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", self.controller.log_tail(40))
        self.log.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.configure(state="disabled")

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        try:
            self.controller.stop()
        except Exception as error:
            print(f"palm: server did not stop cleanly: {error}", file=sys.stderr)
        update_failed = False
        if self._quit_action is not None:
            try:
                result = self._quit_action()
            except Exception as error:  # keep quitting even if update launch fails
                result = f"Pending update could not be launched: {error}"
                update_failed = True
            if isinstance(result, str) and "could not be launched" in result:
                self.detail.set(result)
                update_failed = True
        if update_failed:
            self._quitting = False
            return
        self.root.destroy()


def _install_root(app_root: Path) -> Path:
    """Return the unit the updater/uninstaller must replace or delete.

    Linux/Windows use the app directory. A macOS app launches from
    PALM.app/Contents/Resources/app, but the whole PALM.app bundle must be
    swapped or removed.
    """
    if app_root.name == "app" and app_root.parent.name == "Resources":
        bundle = app_root.parents[2]
        if bundle.suffix == ".app":
            return bundle
    return app_root


def _restart_command(app_root: Path) -> list[str]:
    if app_root.suffix == ".app":
        wrapper = app_root / "Contents" / "MacOS" / "palm"
        return [str(wrapper), "--window"] if wrapper.is_file() else []
    if (app_root / "bin" / "palm").is_file():
        return [str(app_root / "bin" / "palm"), "--window"]
    if (app_root / "PALM.exe").is_file():
        return [str(app_root / "PALM.exe")]
    return []


def _external_python(paths: LauncherPaths) -> Path:
    """Return a helper interpreter outside app_root/data_root.

    The app's bundled Python is copied into a side directory outside the data
    root (so delete-data cannot remove a running helper). Only the interpreter,
    shared library/DLLs and standard-library payload are copied, not the large
    site-packages tree.
    """
    executable = Path(sys.executable).resolve()
    app_root = paths.runtime.app_root.resolve()
    try:
        executable.relative_to(app_root)
    except ValueError:
        return executable
    source = (
        executable.parent
        if executable.name.lower() in {"python.exe", "pythonw.exe"}
        else executable.parent.parent
    )
    destination = paths.runtime.data_root.parent / ".palm-helper-runtime"
    log = paths.runtime.data_root / "logs" / "updater.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not (destination / executable.relative_to(source)).is_file():
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            destination.mkdir(parents=True)
            _copy_helper_runtime(source, destination)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"helper runtime copied to {destination}\n")
        copied = destination / executable.relative_to(source)
    except (OSError, ValueError) as error:
        raise UpdateError(f"helper runtime could not be prepared: {error}") from error
    if not copied.is_file():
        raise UpdateError(f"helper runtime is incomplete: {copied}")
    return copied


def _copy_helper_runtime(source: Path, destination: Path) -> None:
    """Copy only the interpreter/shared libraries/stdlib needed by helpers."""
    for entry in source.iterdir():
        name = entry.name.lower()
        if entry.is_dir():
            if name in {"site-packages", "test", "tests", "__pycache__", "include"}:
                continue
            if name in {"dlls", "lib", "bin"}:
                shutil.copytree(
                    entry,
                    destination / entry.name,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(
                        "site-packages", "test", "tests", "__pycache__", "*.pyc"
                    ),
                )
        elif name in {"python.exe", "pythonw.exe"} or name.endswith(
            (".dll", ".dylib", ".so", ".zip", ".pyd")
        ):
            shutil.copy2(entry, destination / entry.name)


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def _clear_pending(plan: Path, payload: dict[str, Any]) -> None:
    plan.unlink(missing_ok=True)
    plan.with_name(plan.name + ".launched").unlink(missing_ok=True)
    asset = payload.get("asset")
    if isinstance(asset, str):
        Path(asset).unlink(missing_ok=True)


def launch_pending_update(
    paths: LauncherPaths,
    *,
    popen: Callable[..., Any] | None = None,
) -> str:
    """Launch the staged update helper, if any, before the app exits."""
    plan = paths.runtime.data_root / "updates" / "pending.json"
    marker = plan.with_name(plan.name + ".launched")
    if marker.is_file():
        return "Update helper has already been launched."
    if not plan.is_file():
        return "No pending update."
    try:
        payload = json.loads(plan.read_text(encoding="utf-8"))
        metadata = load_metadata(paths.runtime.app_root, paths.runtime.data_root)
        version = str(payload.get("version", ""))
        if version and _version_key(version) <= _version_key(metadata.version):
            _clear_pending(plan, payload)
            return "No newer update pending; removed stale plan."
        executable = _external_python(paths)
        launch_helper(plan, python=executable, popen=popen)
        marker.write_text("launched\n", encoding="utf-8")
    except (UpdateError, OSError, ValueError, json.JSONDecodeError) as error:
        try:
            log = paths.runtime.data_root / "logs" / "updater.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"pending update launch failed: {error}\n")
        except OSError:
            pass
        return f"Pending update could not be launched: {error}"
    return "Update helper launched; PALM will swap and restart after Quit."


def uninstall_app(
    controller: LauncherController,
    paths: LauncherPaths,
    *,
    delete_data: bool = False,
    helper: Path | None = None,
    popen: Callable[..., Any] | None = None,
) -> Path:
    """Stop the app, then launch the external uninstall helper (default keep data)."""
    controller.stop()
    executable = helper or _external_helper(paths, "uninstall_helper.py")
    shortcuts = (
        Path.home() / ".local/share/applications/palm.desktop",
        Path.home() / ".local/bin/palm",
    )
    plan = UninstallPlan(
        app_root=_install_root(paths.runtime.app_root),
        data_root=paths.runtime.data_root,
        delete_data=delete_data is True,
        pid=os.getpid(),
        shortcuts=shortcuts,
    )
    return launch_uninstall_helper(
        plan,
        executable,
        python=_external_python(paths),
        popen=popen,
        log_path=paths.runtime.data_root / "logs" / "updater.log",
    )


def _external_helper(paths: LauncherPaths, name: str) -> Path:
    """Copy a packaged updater/helper below the writable data root."""
    roots = (
        paths.runtime.app_root / "updaters",
        paths.runtime.app_root.parent / "updaters",
        paths.runtime.app_root.parents[1] / "updaters"
        if len(paths.runtime.app_root.parents) > 1
        else paths.runtime.app_root.parent / "updaters",
    )
    destination = paths.runtime.data_root / "updates" / "helpers" / name
    for root in roots:
        source = root / name
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            for helper_name in ("update_helper.py", "uninstall_helper.py"):
                sibling = root / helper_name
                if sibling.is_file():
                    copied = destination.parent / helper_name
                    shutil.copy2(sibling, copied)
                    copied.chmod(0o755)
            return destination
    return paths.runtime.app_root.parent / name


def check_for_updates(
    paths: LauncherPaths,
    *,
    fetch_release: Callable[[str], Any] | None = None,
    download: Callable[[str, Path], None] | None = None,
) -> str:
    """Read install.json, check the channel and stage a verified update."""
    try:
        metadata = load_metadata(paths.runtime.app_root, paths.runtime.data_root)
    except UpdateError as error:
        return f"Update check failed: {error}"
    release_url = os.environ.get(
        "PALM_UPDATE_MANIFEST",
        "https://github.com/ThomasTZh/PALM-Practice-Any-Local-Music/releases/latest/download/release.json",
    )
    try:
        candidate = check_for_update(metadata, fetch_release=fetch_release, release_url=release_url)
    except (UpdateError, OSError) as error:
        return f"Update check failed: {error}"
    if candidate is None:
        return f"No update available for {metadata.channel} (installed {metadata.version})."
    try:
        staged = stage_update(candidate, paths.runtime.data_root, download=download)
        helper = _external_helper(paths, "update_helper.py")
        if not helper.is_file():
            return "Update is available but the external update helper is missing."
        app_root = _install_root(paths.runtime.app_root)
        pending = write_plan(
            metadata,
            candidate,
            staged,
            helper,
            app_root=app_root,
            restart=_restart_command(app_root),
        )
        pending.with_name(pending.name + ".launched").unlink(missing_ok=True)
    except (UpdateError, OSError) as error:
        return f"Update could not be staged: {error}"
    return f"Update {candidate.version} staged; quit PALM to install and restart."


def run_control(
    paths: LauncherPaths,
    *,
    root_factory: Callable[[], Any] | None = None,
    controller_factory: Callable[[LauncherPaths], LauncherController] | None = None,
) -> int | None:
    """Open the control window; return None when Tk/display is unavailable."""
    try:
        tk, ttk = _load_tk()
        root = root_factory() if root_factory is not None else tk.Tk()
    except (ImportError, OSError) as error:
        print(
            f"palm: control window unavailable ({error}); using headless/terminal mode. "
            f"Logs: {paths.server_log}",
            file=sys.stderr,
        )
        return None
    except Exception as error:  # tkinter.TclError without a display
        print(
            f"palm: no graphical display for the control window ({error}); "
            f"using headless/terminal mode. Logs: {paths.server_log}",
            file=sys.stderr,
        )
        return None
    try:
        controller = (
            controller_factory(paths)
            if controller_factory is not None
            else LauncherController(paths)
        )

        def update_action() -> str:
            return check_for_updates(paths)

        def uninstall_action() -> str:
            helper = _external_helper(paths, "uninstall_helper.py")
            uninstall_app(controller, paths, helper=helper)
            return "Uninstall helper launched; your data is kept."

        ControlWindow(
            root,
            controller,
            ttk=ttk,
            tk=tk,
            update_action=update_action,
            uninstall_action=uninstall_action,
            quit_action=lambda: launch_pending_update(paths),
        )
        root.mainloop()
        return 0
    except Exception as error:
        print(f"palm: control window failed: {error}; Logs: {paths.server_log}", file=sys.stderr)
        return None
