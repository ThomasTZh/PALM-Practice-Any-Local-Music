"""PALM desktop launcher.

The launcher is the small process the tar/AppImage starts. It owns only
process and file concerns: resolve the app/data roots, enforce one instance,
start the existing ``basseparate.cli serve`` command on loopback, record the
URL, open the browser and forward shutdown signals. It does not create the
FastAPI app or duplicate any server logic.

All writable state (lock, run state, logs, setup state) lives under the
resolved data root. In packaged mode the app root is read-only by contract.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import IO, Any
from urllib.parse import urlsplit

from basseparate.config import DataPaths, RuntimePathError, RuntimePaths, runtime_paths
from basseparate.doctor import DoctorLayout, diagnose

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 0
STARTUP_TIMEOUT_SECONDS = 30.0
SHUTDOWN_GRACE_SECONDS = 10.0
STATE_TIMEOUT_SECONDS = 5.0
RUN_DIR = "run"
LOCK_NAME = "launcher.lock"
STATE_NAME = "server.json"
LAUNCHER_LOG = "launcher.log"
SERVER_LOG = "server.log"
STATE_VERSION = 1
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
BOOTSTRAP_PREFIX = "bootstrap:"


class LauncherError(RuntimeError):
    """A launcher operation failed with a user-facing message."""


@dataclass(frozen=True)
class LauncherPaths:
    """Every writable launcher path, derived from the data root."""

    runtime: RuntimePaths

    @classmethod
    def from_runtime(cls, runtime: RuntimePaths) -> LauncherPaths:
        return cls(runtime=runtime)

    @property
    def run_dir(self) -> Path:
        return self.runtime.data_root / RUN_DIR

    @property
    def lock_file(self) -> Path:
        return self.run_dir / LOCK_NAME

    @property
    def state_file(self) -> Path:
        return self.run_dir / STATE_NAME

    @property
    def logs_root(self) -> Path:
        return self.runtime.logs_root

    @property
    def launcher_log(self) -> Path:
        return self.logs_root / LAUNCHER_LOG

    @property
    def server_log(self) -> Path:
        return self.logs_root / SERVER_LOG

    @property
    def setup_state(self) -> Path:
        return self.runtime.setup_state

    def ensure(self) -> None:
        for path in (self.run_dir, self.logs_root, self.launcher_log, self.server_log):
            self.runtime.ensure_data_path(path)


@dataclass(frozen=True)
class RunState:
    """The state a second launch reads to find the running instance."""

    url: str
    port: int
    pid: int
    launcher_pid: int
    started_at: str
    mode: str
    app_root: str
    data_root: str

    def to_dict(self) -> dict[str, object]:
        return {
            "version": STATE_VERSION,
            "url": self.url,
            "port": self.port,
            "pid": self.pid,
            "launcher_pid": self.launcher_pid,
            "started_at": self.started_at,
            "mode": self.mode,
            "app_root": self.app_root,
            "data_root": self.data_root,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RunState:
        version = payload.get("version")
        if version != STATE_VERSION:
            raise ValueError(f"unsupported run state version {version!r}")
        url = payload.get("url")
        port = payload.get("port")
        pid = payload.get("pid")
        launcher_pid = payload.get("launcher_pid")
        started_at = payload.get("started_at")
        mode = payload.get("mode")
        app_root = payload.get("app_root")
        data_root = payload.get("data_root")
        if not isinstance(url, str) or not isinstance(started_at, str):
            raise ValueError("run state has an invalid url or started_at")
        if not isinstance(mode, str) or not isinstance(app_root, str):
            raise ValueError("run state has an invalid mode or app_root")
        if not isinstance(data_root, str):
            raise ValueError("run state has an invalid data_root")
        if (
            not isinstance(port, int)
            or not isinstance(pid, int)
            or not isinstance(launcher_pid, int)
        ):
            raise ValueError("run state has an invalid port or pid")
        return cls(
            url=url,
            port=port,
            pid=pid,
            launcher_pid=launcher_pid,
            started_at=started_at,
            mode=mode,
            app_root=app_root,
            data_root=data_root,
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_bootstrap_url(line: str) -> str | None:
    """Return the loopback URL from a CLI ``bootstrap:`` line, if valid."""
    text = line.strip()
    if not text.startswith(BOOTSTRAP_PREFIX):
        return None
    raw = text[len(BOOTSTRAP_PREFIX) :].strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK_NAMES:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        return None
    return raw.rstrip("/") + "/"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_run_state(path: Path, state: RunState) -> None:
    _atomic_json(path, state.to_dict())


def read_run_state(path: Path) -> RunState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return RunState.from_dict(payload)
    except ValueError:
        return None


def wait_for_run_state(
    path: Path,
    *,
    timeout: float = STATE_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> RunState | None:
    """Wait for a starting instance to publish its URL, or return None."""
    deadline = time.monotonic() + timeout
    while True:
        state = read_run_state(path)
        if state is not None:
            return state
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        sleep(min(0.05, remaining))


class InstanceLock:
    """A non-blocking advisory lock under the data root."""

    def __init__(self, paths: LauncherPaths) -> None:
        self.paths = paths
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        self.paths.runtime.ensure_data_path(self.paths.lock_file)
        descriptor = os.open(self.paths.lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return False
        except OSError:
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
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> InstanceLock:
        if not self.acquire():
            raise LauncherError("another PALM instance holds the launcher lock")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def launcher_environment(
    runtime: RuntimePaths,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment the server child must inherit, including packaged roots."""
    environment = dict(os.environ if base is None else base)
    environment["PALM_MODE"] = runtime.mode
    environment["PALM_APP_ROOT"] = str(runtime.app_root)
    environment["PALM_DATA_DIR"] = str(runtime.data_root)
    environment["BASSEPARATE_DATA_DIR"] = str(runtime.data_root)
    # Packaged app roots are read-only; never let imports create __pycache__.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if runtime.packaged:
        source = runtime.app_root / "src"
        if source.is_dir():
            existing = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                str(source) if not existing else f"{source}{os.pathsep}{existing}"
            )
    return environment


def build_server_command(
    runtime: RuntimePaths,
    *,
    port: int = DEFAULT_PORT,
    python: Path | None = None,
) -> list[str]:
    """The existing CLI server command; no server logic is reimplemented here."""
    executable = Path(python) if python is not None else Path(sys.executable)
    return [
        str(executable),
        "-m",
        "basseparate.cli",
        "serve",
        "--host",
        LOOPBACK_HOST,
        "--no-browser",
        "--port",
        str(port),
        "--data-root",
        str(runtime.data_root),
        "--web-dir",
        str(runtime.web_dir),
    ]


def forward_signal(process: subprocess.Popen[str] | None, signum: int) -> None:
    """Forward a shutdown signal to the child if it is still running."""
    if process is None or process.poll() is not None:
        return
    with contextlib.suppress(OSError, ValueError):
        process.send_signal(signum)


def run_setup(runtime: RuntimePaths) -> int:
    """Create the writable data layout and record setup state; no downloads."""
    paths = LauncherPaths.from_runtime(runtime)
    try:
        DataPaths.from_root(runtime.data_root).ensure()
        paths.ensure()
        runtime.ensure_data_path(runtime.caches_root)
    except (OSError, RuntimePathError) as error:
        print(f"palm setup: cannot prepare {runtime.data_root}: {error}", file=sys.stderr)
        return 1
    web_ready = (runtime.web_dir / "index.html").is_file()
    registry_ready = runtime.registry_path.is_file()
    payload = {
        "version": 1,
        "mode": runtime.mode,
        "app_root": str(runtime.app_root),
        "data_root": str(runtime.data_root),
        "created_at": utc_now(),
        "web_ready": web_ready,
        "registry_ready": registry_ready,
        "models_root": str(runtime.models_root),
        "tools_root": str(runtime.tools_root),
        "environments_root": str(runtime.environments_root),
    }
    try:
        _atomic_json(paths.setup_state, payload)
    except OSError as error:
        print(f"palm setup: cannot write {paths.setup_state}: {error}", file=sys.stderr)
        return 1
    print(f"palm setup: data root {runtime.data_root}")
    print(f"palm setup: app root {runtime.app_root} ({runtime.mode})")
    print(
        f"palm setup: UI {'ready' if web_ready else 'missing'} · model registry "
        f"{'ready' if registry_ready else 'missing'}"
    )
    return 0 if web_ready and registry_ready else 1


def run_doctor(runtime: RuntimePaths, *, stream: IO[str] | None = None) -> int:
    """Print the existing doctor report without writing anything."""
    output = sys.stdout if stream is None else stream
    report = diagnose(DoctorLayout.from_runtime(runtime))
    for check in report.checks:
        marker = "ok" if check.status == "ok" else check.status
        print(f"[{marker:12}] {check.label}: {check.detail}", file=output)
    print(f"doctor: {report.status}", file=output)
    return 0 if report.ok else 1


class Launcher:
    """Start and supervise the existing local server."""

    def __init__(
        self,
        paths: LauncherPaths,
        *,
        port: int = DEFAULT_PORT,
        open_browser: bool = True,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
        state_timeout: float = STATE_TIMEOUT_SECONDS,
        browser_open: Callable[[str], bool] | None = None,
        popen_factory: Callable[..., subprocess.Popen[str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = paths
        self.port = port
        self.open_browser = open_browser
        self.startup_timeout = startup_timeout
        self.state_timeout = state_timeout
        self._browser_open = browser_open if browser_open is not None else webbrowser.open
        self._popen_factory = popen_factory if popen_factory is not None else subprocess.Popen
        self._sleep = sleep
        self._lock = InstanceLock(paths)
        self._server: subprocess.Popen[str] | None = None
        self._server_log: IO[str] | None = None
        self._stop = threading.Event()
        self._url_event = threading.Event()
        self._url: str | None = None
        self._signum: int | None = None
        self._previous_handlers: dict[int, Any] = {}

    def _open_browser(self, url: str) -> None:
        if self.open_browser:
            self._browser_open(url)

    def _write_log(self, line: str) -> None:
        if self._server_log is not None:
            self._server_log.write(line)
            self._server_log.flush()

    def _pump(self, stream: IO[str]) -> None:
        try:
            for line in stream:
                self._write_log(line)
                url = parse_bootstrap_url(line)
                if url is not None and not self._url_event.is_set():
                    self._url = url
                    self._url_event.set()
        finally:
            stream.close()

    def _start_server(self) -> subprocess.Popen[str]:
        command = build_server_command(self.paths.runtime, port=self.port)
        environment = launcher_environment(self.paths.runtime)
        self._server_log = self.paths.server_log.open("a", encoding="utf-8")
        try:
            process = self._popen_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
                cwd=str(self.paths.runtime.app_root),
            )
        except OSError as error:
            self._server_log.close()
            self._server_log = None
            raise LauncherError(f"cannot start the server: {error}") from error
        self._server = process
        if process.stdout is None:
            raise LauncherError("the server child exposed no stdout")
        threading.Thread(
            target=self._pump, args=(process.stdout,), name="palm-server-log", daemon=True
        ).start()
        return process

    def _wait_for_url(self) -> str:
        if not self._url_event.wait(self.startup_timeout):
            raise LauncherError(
                f"the server did not print a bootstrap URL within {self.startup_timeout:.0f}s; "
                f"see {self.paths.server_log}"
            )
        if self._url is None:  # pragma: no cover - event implies URL
            raise LauncherError("the server URL was not recorded")
        return self._url

    def _write_running_state(self, url: str) -> RunState:
        parts = urlsplit(url)
        port = parts.port
        if port is None:
            raise LauncherError(f"the server URL has no port: {url}")
        process = self._server
        if process is None:
            raise LauncherError("the server process is not running")
        state = RunState(
            url=url,
            port=port,
            pid=process.pid,
            launcher_pid=os.getpid(),
            started_at=utc_now(),
            mode=self.paths.runtime.mode,
            app_root=str(self.paths.runtime.app_root),
            data_root=str(self.paths.runtime.data_root),
        )
        write_run_state(self.paths.state_file, state)
        return state

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        self._signum = signum
        self._stop.set()
        forward_signal(self._server, signum)

    def _install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.signal(signum, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        for signum, handler in self._previous_handlers.items():
            if handler is not None:
                signal.signal(signum, handler)
        self._previous_handlers.clear()

    def _wait_for_exit(self) -> int:
        process = self._server
        if process is None:
            return 0
        while process.poll() is None:
            if self._stop.wait(0.1):
                break
        if self._stop.is_set() and process.poll() is None:
            try:
                process.wait(timeout=SHUTDOWN_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return process.returncode if process.returncode is not None else 0

    def _cleanup(self) -> None:
        process = self._server
        if process is not None and process.poll() is None:
            forward_signal(process, signal.SIGTERM)
            try:
                process.wait(timeout=SHUTDOWN_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self.paths.state_file.unlink(missing_ok=True)
        if self._server_log is not None:
            self._server_log.close()
            self._server_log = None
        self._lock.release()
        self._restore_signal_handlers()

    def _report_running(self) -> int:
        state = wait_for_run_state(
            self.paths.state_file, timeout=self.state_timeout, sleep=self._sleep
        )
        if state is None:
            print("palm: another instance is starting; retry in a moment", file=sys.stderr)
            return 0
        print(f"palm: already running at {state.url}")
        self._open_browser(state.url)
        return 0

    def run(self) -> int:
        try:
            self.paths.ensure()
        except (OSError, RuntimePathError) as error:
            print(f"palm: cannot prepare data root: {error}", file=sys.stderr)
            return 1
        if not self._lock.acquire():
            return self._report_running()
        try:
            self._install_signal_handlers()
            with self.paths.launcher_log.open("a", encoding="utf-8") as log:
                log.write(
                    f"{utc_now()} starting mode={self.paths.runtime.mode} "
                    f"app={self.paths.runtime.app_root} data={self.paths.runtime.data_root}\n"
                )
                log.flush()
                self._start_server()
                url = self._wait_for_url()
                self._write_running_state(url)
                print(f"palm: running at {url}")
                print(f"palm: logs in {self.paths.logs_root}")
                self._open_browser(url)
                return self._wait_for_exit()
        except LauncherError as error:
            print(f"palm: {error}", file=sys.stderr)
            return 1
        except (OSError, RuntimePathError) as error:
            print(f"palm: {error}", file=sys.stderr)
            return 1
        finally:
            self._cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="palm",
        description="PALM (Practice Any Local Music) desktop launcher.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        dest="no_browser",
        help="do not open the studio URL in the browser",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="server port; 0 asks the kernel for a free loopback port (default: 0)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="writable data root (default: PALM_DATA_DIR or the per-user data dir)",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--setup",
        action="store_true",
        help="create the data layout and record setup state, then exit",
    )
    actions.add_argument(
        "--doctor",
        action="store_true",
        help="print the read-only dependency report, then exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65_535:
        print(f"palm: invalid port {args.port}", file=sys.stderr)
        return 2
    try:
        runtime = runtime_paths(data_root=args.data_dir)
    except RuntimePathError as error:
        print(f"palm: {error}", file=sys.stderr)
        return 2
    if args.doctor:
        return run_doctor(runtime)
    if args.setup:
        return run_setup(runtime)
    launcher = Launcher(
        LauncherPaths.from_runtime(runtime),
        port=args.port,
        open_browser=not args.no_browser,
    )
    return launcher.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
