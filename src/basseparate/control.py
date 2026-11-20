"""Small Tk control window for the packaged PALM launcher.

The window is a thin client over ``LauncherController``: process, health, state
and logging behavior is shared with the native Windows/macOS wrappers. It keeps
Open browser, View logs and Quit, and Check for updates opens the matching
release/download page with manual replacement instructions. PALM does not
replace itself and has no custom uninstaller; remove the app with the OS tools
and keep the data root.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from collections.abc import Callable
from typing import Any

from basseparate.launcher import LauncherController, LauncherError, LauncherPaths


def _load_tk() -> Any:
    import tkinter as tk
    from tkinter import ttk

    return tk, ttk


class ControlWindow:
    """Status window with Open browser, View logs, Quit and Check for updates.

    Check for updates reads ``install.json`` and opens the release/download page
    in a browser with manual instructions. It never downloads, swaps or restarts
    anything. Uninstall is an OS-level action: remove the app bundle/folder or
    use the OS uninstaller; projects, models and tools live below the data root
    and are preserved unless the user removes that directory explicitly.
    """

    def __init__(
        self,
        root: Any,
        controller: LauncherController,
        *,
        ttk: Any,
        tk: Any,
        update_action: Callable[[], str] | None = None,
    ) -> None:
        self.root = root
        self.controller = controller
        self._ttk = ttk
        self._tk = tk
        self._started = False
        self._log_window: Any | None = None
        self._update_action = update_action
        root.title("PALM — Practice Any Local Music")
        root.minsize(520, 340)
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
        for column in range(3):
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
            self.detail.set("Update information is unavailable for this install.")
            return
        try:
            self.detail.set(self._update_action())
        except Exception as error:  # user-facing helper errors must not crash Tk
            self.detail.set(f"Update check failed: {error}")

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
        try:
            self.controller.stop()
        finally:
            self.root.destroy()


def release_page(paths: LauncherPaths) -> tuple[str, str, str]:
    """Return (page_url, channel, version) from install.json."""
    path = paths.runtime.app_root / "install.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read install metadata {path}: {error}") from error
    channel = payload.get("channel")
    version = payload.get("version")
    assets = payload.get("assets")
    if not isinstance(channel, str) or not channel or not isinstance(version, str):
        raise ValueError("install metadata needs channel and version")
    raw = assets.get(channel, {}) if isinstance(assets, dict) else {}
    asset_url = str(raw.get("url", "")) if isinstance(raw, dict) else ""
    marker = "/releases/download/"
    if marker in asset_url:
        page = asset_url.split(marker, 1)[0] + f"/releases/tag/v{version}"
    elif asset_url:
        page = asset_url
    else:
        page = f"https://github.com/ThomasTZh/PALM-Practice-Any-Local-Music/releases/tag/v{version}"
    return page, channel, version


def check_for_updates(
    paths: LauncherPaths,
    *,
    open_url: Callable[[str], Any] = webbrowser.open,
) -> str:
    """Open the matching release page; never download or replace the app."""
    try:
        page, channel, version = release_page(paths)
        open_url(page)
    except (ValueError, OSError) as error:
        return f"Update check failed: {error}"
    return (
        f"Opened the {channel} {version} release page. Download the matching "
        "asset and SHA256SUMS, quit PALM, then replace the app folder. Your "
        "data root (projects, models and tools) is preserved."
    )


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

        ControlWindow(
            root,
            controller,
            ttk=ttk,
            tk=tk,
            update_action=update_action,
        )
        root.mainloop()
        return 0
    except Exception as error:
        print(f"palm: control window failed: {error}; Logs: {paths.server_log}", file=sys.stderr)
        return None
