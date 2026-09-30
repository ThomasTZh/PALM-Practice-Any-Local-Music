"""Server launch, instance locking, and lifecycle management (M0.10).

``run_server`` executes the full launch sequence:
1. Verify static frontend assets exist.
2. Acquire an OS-backed advisory lock for the storage root.
3. Bind the loopback socket via uvicorn.
4. Wait for readiness.
5. Open one browser tab with the bootstrap fragment (optional).
6. Print a concise ready message without the token.
7. Continue serving until SIGINT/SIGTERM.
8. Release the lock and exit.
"""

from __future__ import annotations

import fcntl
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from basseparate.app import _static_dir, create_app
from basseparate.config import AppConfig
from basseparate.storage import (
    StorageError,
    initialize_storage_paths,
    resolve_storage_paths,
)

LOCK_FILENAME = ".basseparate.lock"


class InstanceLockError(RuntimeError):
    """Another instance already owns this storage root."""


class ServeError(RuntimeError):
    """Generic serve-launch failure."""


def acquire_instance_lock(runtime_dir: Path) -> int:
    """Acquire an exclusive advisory lock on the storage root.

    Returns the open file descriptor. The OS releases the lock
    automatically when the process exits (crash or clean shutdown).

    Raises InstanceLockError if the lock is already held.
    """
    lock_path = runtime_dir / LOCK_FILENAME
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise InstanceLockError(
            f"basseparate is already running for this storage root (lock file: {lock_path})"
        ) from None
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.fsync(fd)
    return fd


def release_instance_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def run_server(config: AppConfig) -> int:
    """Execute the full serve lifecycle. Returns a process exit code."""

    # 1. Verify static frontend assets exist.
    static_dir = _static_dir()
    if static_dir is None:
        print(
            "error: frontend build not found. Run 'python scripts/dev.py build' first.",
            file=sys.stderr,
        )
        return 1

    # 2. Resolve and initialize storage paths, then acquire the lock.
    try:
        paths = resolve_storage_paths(config.storage_root)
        initialize_storage_paths(paths)
    except StorageError as exc:
        print(f"storage error: {exc}", file=sys.stderr)
        return 1

    try:
        lock_fd = acquire_instance_lock(paths.runtime)
    except InstanceLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        return _serve_locked(config)
    finally:
        release_instance_lock(lock_fd)


def _serve_locked(config: AppConfig) -> int:
    """Bind, serve, and manage the browser. Lock is already held."""

    app = create_app(config)
    token: str = app.state.session_token

    uv_config = uvicorn.Config(
        app=app,
        host=config.bind_address,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(uv_config)

    stop_event = threading.Event()

    def _signal_handler(signum: int, _frame: object) -> None:
        stop_event.set()
        server.should_exit = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for the server to begin accepting connections.
    deadline = time.monotonic() + config.startup_timeout_seconds
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            server_thread.join(timeout=5.0)
            print("error: server did not start within the configured timeout", file=sys.stderr)
            return 1
        if stop_event.is_set():
            server.should_exit = True
            server_thread.join(timeout=5.0)
            return 0
        time.sleep(0.05)

    # Server is ready. Open the browser or print the URL.
    bootstrap_url = f"http://{config.bind_address}:{config.port}/#token={token}"
    if config.open_browser:
        if not webbrowser.open(bootstrap_url):
            print(
                f"warning: could not open a browser automatically.\n"
                f"open this URL manually: {bootstrap_url}",
                file=sys.stderr,
            )
    else:
        print(bootstrap_url)

    print(f"basseparate ready at http://{config.bind_address}:{config.port}")

    # Block until the server stops (SIGINT/SIGTERM or internal error).
    server_thread.join()

    return 0
