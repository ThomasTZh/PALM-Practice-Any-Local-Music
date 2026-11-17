"""Portable operating-system boundary for PALM.

This module is the only place that knows whether the process is POSIX or
Windows: advisory locks, process inspection/termination, virtual-environment
interpreter names, plugin suffixes, FFmpeg discovery and hidden child-process
flags. Callers keep platform-independent policy.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
POSIX = os.name == "posix"

PSUTIL_REQUIRED_MESSAGE = (
    "PALM requires psutil 7.2.2 for portable process inspection. "
    "Install the pinned application dependencies (uv sync --locked) and retry."
)
try:
    import psutil  # type: ignore[import-untyped]
except ImportError as error:  # pragma: no cover - exercised by the missing-import test
    raise ImportError(PSUTIL_REQUIRED_MESSAGE) from error


class PlatformError(RuntimeError):
    """A platform operation failed with a user-facing message."""


def process_supported() -> bool:
    return True


def _process(pid: int) -> Any | None:
    try:
        return psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        if isinstance(error, psutil.AccessDenied):
            raise PlatformError(f"cannot inspect process {pid}: access denied") from error
        return None


def process_is_alive(pid: int) -> bool:
    """Whether pid exists and is not a zombie; never changes the process."""
    if pid <= 1:
        return False
    process = _process(pid)
    if process is None:
        return False
    try:
        return bool(process.is_running()) and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def process_command(pid: int) -> str | None:
    """Return a printable process command line, or None when unavailable."""
    if pid <= 1:
        return None
    process = _process(pid)
    if process is None:
        return None
    try:
        return " ".join(process.cmdline()).strip() or None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def signal_process(pid: int, signum: int) -> bool:
    """Send a signal/termination request; return whether it was delivered."""
    if pid <= 1:
        return False
    process = _process(pid)
    if process is None:
        return False
    try:
        process.send_signal(signum)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    return True


def terminate_process(pid: int) -> bool:
    """Ask a process to stop (SIGTERM/terminate)."""
    if pid <= 1:
        return False
    process = _process(pid)
    if process is None:
        return False
    try:
        process.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    return True


def kill_process(pid: int) -> bool:
    """Force-stop a process (SIGKILL/kill)."""
    if pid <= 1:
        return False
    process = _process(pid)
    if process is None:
        return False
    try:
        process.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    return True


def wait_process(pid: int, timeout: float) -> bool:
    """Wait up to timeout for pid to exit; returns True when it is gone."""
    import time

    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        if not process_is_alive(pid):
            return True
        time.sleep(0.05)
    return not process_is_alive(pid)


class FileLock:
    """Cross-platform advisory exclusive lock for one lock file."""

    def __init__(self, path: Path, *, blocking: bool = True) -> None:
        self.path = Path(path)
        self.blocking = blocking
        self._fd: int | None = None
        self._windows_locked = False

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if POSIX:
                import fcntl

                flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
                try:
                    fcntl.flock(descriptor, flags)
                except BlockingIOError:
                    os.close(descriptor)
                    return False
            elif WINDOWS:
                msvcrt = cast(Any, importlib.import_module("msvcrt"))
                if self.path.stat().st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                mode = msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK
                try:
                    msvcrt.locking(descriptor, mode, 1)
                except OSError:
                    os.close(descriptor)
                    return False
                self._windows_locked = True
            else:
                raise PlatformError(f"file locking is not supported on {sys.platform}")
        except BaseException:
            if self._fd is None:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            raise
        self._fd = descriptor
        return True

    def release(self) -> None:
        descriptor = self._fd
        if descriptor is None:
            return
        self._fd = None
        try:
            if POSIX:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif WINDOWS and self._windows_locked:
                msvcrt = cast(Any, importlib.import_module("msvcrt"))
                os.lseek(descriptor, 0, os.SEEK_SET)
                with contextlib.suppress(OSError):
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            self._windows_locked = False
            os.close(descriptor)

    def __enter__(self) -> FileLock:
        if not self.acquire():
            raise PlatformError(f"cannot acquire lock {self.path}")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def fsync_directory(directory: Path) -> None:
    """Durably persist a directory entry; Windows has no directory fsync."""
    if not POSIX:
        return
    descriptor = os.open(Path(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    lock = FileLock(path, blocking=True)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def venv_python(root: Path) -> Path:
    """The interpreter path for a virtual environment on this platform."""
    root = Path(root)
    candidates = (
        root / "Scripts" / "python.exe",
        root / "Scripts" / "python",
        root / "bin" / "python",
        root / "bin" / "python3",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0] if WINDOWS else candidates[2]


def python_executable(root: Path, name: str = "python") -> Path:
    """Resolve a named interpreter in a venv-like root."""
    candidate = venv_python(root)
    if name == "python":
        return candidate
    return candidate.with_name(name + (".exe" if WINDOWS else ""))


def plugin_suffix() -> str:
    if WINDOWS:
        return ".dll"
    if MACOS:
        return ".dylib"
    return ".so"


def plugin_glob(stem: str = "*") -> str:
    return f"{stem}{plugin_suffix()}"


def managed_media_binary(name: str) -> Path | None:
    """The setup-managed FFmpeg/FFprobe under the runtime data root."""
    from basseparate.config import runtime_paths

    candidate = (
        runtime_paths().data_root / "tools" / "ffmpeg" / f"{name}{'.exe' if WINDOWS else ''}"
    )
    return candidate if candidate.is_file() else None


def ffmpeg_binary(*, which: Any = None) -> str:
    for key in ("PALM_FFMPEG", "BASSEPARATE_FFMPEG"):
        override = os.environ.get(key)
        if override:
            return override
    managed = managed_media_binary("ffmpeg")
    if managed is not None:
        return str(managed)
    find = which or shutil.which
    return find("ffmpeg") or "ffmpeg"


def ffprobe_binary(*, which: Any = None) -> str:
    for key in ("PALM_FFPROBE", "BASSEPARATE_FFPROBE"):
        override = os.environ.get(key)
        if override:
            return override
    managed = managed_media_binary("ffprobe")
    if managed is not None:
        return str(managed)
    find = which or shutil.which
    return find("ffprobe") or "ffprobe"


def hidden_process_kwargs() -> dict[str, Any]:
    """Creation flags for child processes that should not flash a console."""
    if not WINDOWS:
        return {}
    startup_class = getattr(subprocess, "STARTUPINFO", None)
    startupinfo = startup_class() if startup_class is not None else None
    if startupinfo is not None:
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def native_data_root(app_name: str = "palm") -> Path | None:
    """Platform-native per-user data directory, or None for platformdirs."""
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) / app_name) if base else None
    if MACOS:
        return Path.home() / "Library" / "Application Support" / app_name
    return None


__all__ = [
    "FileLock",
    "MACOS",
    "POSIX",
    "WINDOWS",
    "PlatformError",
    "ffmpeg_binary",
    "ffprobe_binary",
    "file_lock",
    "fsync_directory",
    "hidden_process_kwargs",
    "kill_process",
    "managed_media_binary",
    "native_data_root",
    "plugin_glob",
    "plugin_suffix",
    "process_command",
    "process_is_alive",
    "process_supported",
    "python_executable",
    "signal_process",
    "terminate_process",
    "venv_python",
    "wait_process",
]
