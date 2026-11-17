#!/usr/bin/env python3
"""External update helper: wait, swap with rollback, restart.

This script is copied/launched outside the app folder before an update. It uses
only the standard library so replacing the app cannot remove its imports. It
never modifies the data root.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


class HelperError(RuntimeError):
    pass


def _log(data_root: Path, message: str) -> None:
    path = data_root / "logs" / "updater.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n")


def _alive(pid: int) -> bool:
    """Non-destructive liveness check; os.kill(pid, 0) is not safe on Windows."""
    if os.name == "nt":
        synchronize = 0x00100000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_exit(
    pid: int, timeout: float = 60.0, *, sleep: Callable[[float], None] = time.sleep
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid <= 0 or not _alive(pid):
            return
        sleep(0.1)
    raise HelperError(f"application pid {pid} did not exit within {timeout:.0f}s")


def _extract(asset: Path, kind: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    if kind in {"zip", "macos-app"}:
        with zipfile.ZipFile(asset) as archive:
            archive.extractall(destination)
            for info in archive.infolist():
                mode = (info.external_attr >> 16) & 0o777
                if not mode or info.is_dir():
                    continue
                target = destination / info.filename
                if target.exists():
                    target.chmod(mode)
        if kind == "macos-app":
            for path in destination.iterdir():
                if path.suffix == ".app":
                    return path
    elif kind in {"tar.gz", "tgz", "tar"}:
        with tarfile.open(asset, "r:gz" if kind != "tar" else "r:") as archive:
            archive.extractall(destination, filter="data")
    else:
        raise HelperError(f"unsupported update kind {kind!r}")
    children = [path for path in destination.iterdir() if path.is_dir()]
    if len(children) == 1:
        return children[0]
    return destination


def _clear_plan(plan_path: Path | None, asset: Path) -> None:
    if plan_path is not None:
        plan_path.unlink(missing_ok=True)
        plan_path.with_name(plan_path.name + ".launched").unlink(missing_ok=True)
        plan_path.with_name(plan_path.name + ".failed").unlink(missing_ok=True)
    asset.unlink(missing_ok=True)


def _mark_failed(plan_path: Path | None, error: Exception) -> None:
    if plan_path is None:
        return
    plan_path.with_name(plan_path.name + ".launched").unlink(missing_ok=True)
    plan_path.with_name(plan_path.name + ".failed").write_text(f"{error}\n", encoding="utf-8")


def swap_app(
    plan: dict[str, Any],
    *,
    wait: Callable[..., None] = wait_for_exit,
    extract: Callable[[Path, str, Path], Path] = _extract,
    restart: Callable[[list[str]], Any] | None = None,
    plan_path: Path | None = None,
) -> bool:
    """Swap app_root after the app exits; restore the backup on any failure."""
    app_root = Path(plan["app_root"])
    asset = Path(plan["asset"])
    data_root = Path(plan["data_root"])
    if app_root.resolve() == data_root.resolve():
        raise HelperError("refusing to replace the data root")
    if not app_root.is_dir():
        raise HelperError(f"app root is missing: {app_root}")
    if not asset.is_file():
        raise HelperError(f"staged asset is missing: {asset}")
    wait(int(plan.get("pid", 0)))
    backup = app_root.with_name(app_root.name + ".palm-backup")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    app_root.rename(backup)
    temp = Path(tempfile.mkdtemp(prefix=".palm-update-", dir=app_root.parent))
    try:
        replacement = extract(asset, str(plan.get("kind", "tar.gz")), temp)
        if replacement != app_root:
            # Move the whole extracted bundle/folder, not just its children.
            # This is required for macOS PALM.app swaps and keeps the shell.
            shutil.move(str(replacement), str(app_root))
    except Exception as error:
        _mark_failed(plan_path, error)
        _log(data_root, f"swap failed for {asset}: {error}; rolling back")
        shutil.rmtree(app_root, ignore_errors=True)
        if backup.exists():
            backup.rename(app_root)
        shutil.rmtree(temp, ignore_errors=True)
        return False
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(temp, ignore_errors=True)
    _clear_plan(plan_path, asset)
    if restart is not None and plan.get("restart"):
        try:
            restart(list(plan["restart"]))
        except Exception as error:
            _log(data_root, f"restart failed after swap: {error}")
    return True


def uninstall(
    plan: dict[str, Any],
    *,
    wait: Callable[..., None] = wait_for_exit,
    plan_path: Path | None = None,
) -> bool:
    app_root = Path(plan["app_root"])
    data_root = Path(plan["data_root"])
    if app_root.resolve() == data_root.resolve():
        raise HelperError("refusing to delete the data root as the app")
    wait(int(plan.get("pid", 0)))
    if app_root.exists():
        shutil.rmtree(app_root)
    for shortcut in plan.get("shortcuts", []):
        path = Path(shortcut)
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    _log(data_root, "uninstall removed the application and shortcuts; data kept")
    if plan_path is not None:
        plan_path.unlink(missing_ok=True)
    if plan.get("delete_data") is True:
        runtime = data_root.parent / ".palm-helper-runtime"
        shutil.rmtree(runtime, ignore_errors=True)
        if data_root.exists():
            shutil.rmtree(data_root)
    return True


def _restart(command: list[str], data_root: Path) -> None:
    log_path = data_root / "logs" / "updater.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except OSError as error:
        _log(data_root, f"restart failed after swap: {error}")
        raise
    finally:
        log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    data_root = Path(payload["data_root"])
    if "delete_data" in payload:
        return 0 if uninstall(payload, plan_path=args.plan) else 1
    return (
        0
        if swap_app(
            payload,
            plan_path=args.plan,
            restart=lambda command: _restart(command, data_root),
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
