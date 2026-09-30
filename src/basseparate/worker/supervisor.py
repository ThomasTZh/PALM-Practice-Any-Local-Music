"""Parent supervisor for worker subprocesses (M0.9).

Spawns a worker with the current interpreter, an argument array, and an
explicit working directory. Reads stdout and stderr concurrently,
validates every message, limits message size to 1 MiB, handles
malformed JSON, detects unexpected exits, requests graceful shutdown,
and terminates only the app-owned child after a timeout. The child is
always reaped.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path

from basseparate.worker.protocol import (
    MAX_MESSAGE_BYTES,
    HelloMessage,
    MalformedMessageError,
    PongMessage,
    StoppedMessage,
    WorkerMessage,
    decode_message,
    make_ping,
    make_shutdown,
)

HANDSHAKE_TIMEOUT_SECONDS = 5.0
_SHUTDOWN_GRACE_SECONDS = 2.0
_KILL_GRACE_SECONDS = 2.0
_READ_CHUNK = 65536
_STDERR_LINE_CAP = 1000

# Queue sentinels.
_EOF = object()
_OVERSIZED = object()


class WorkerSupervisorError(Exception):
    """Base class for supervisor failures."""


class HandshakeTimeoutError(WorkerSupervisorError):
    """The worker did not emit a valid hello within the timeout."""


class WorkerTimeoutError(WorkerSupervisorError):
    """No message arrived within the requested timeout."""


class WorkerExitedError(WorkerSupervisorError):
    """The worker process exited."""

    def __init__(self, returncode: int | None) -> None:
        super().__init__(f"worker exited with return code {returncode}")
        self.returncode = returncode


class MalformedWorkerMessage(WorkerSupervisorError):
    """The worker emitted a line that is not a valid protocol message."""


class OversizedWorkerMessage(WorkerSupervisorError):
    """The worker emitted a line larger than MAX_MESSAGE_BYTES."""


def probe_command() -> list[str]:
    """Argument array for the built-in probe worker."""
    return [sys.executable, "-m", "basseparate.worker.probe_worker"]


class WorkerSupervisor:
    """Owns one worker subprocess and its protocol exchange."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        cwd: str | Path | None = None,
        handshake_timeout: float = HANDSHAKE_TIMEOUT_SECONDS,
    ) -> None:
        self._command = list(command) if command is not None else probe_command()
        self._cwd = Path(cwd) if cwd is not None else Path.cwd()
        self._handshake_timeout = handshake_timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._out_queue: queue.Queue[object] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._last_pid: int | None = None
        self._exit_code: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def pid(self) -> int | None:
        if self._proc is not None:
            return self._proc.pid
        return self._last_pid

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def stderr_lines(self) -> list[str]:
        with self._stderr_lock:
            return list(self._stderr_lines)

    def start(self) -> None:
        if self._proc is not None:
            raise WorkerSupervisorError("supervisor already started")
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._cwd),
        )
        self._last_pid = self._proc.pid
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name="worker-stdout", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="worker-stderr", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def stop(self) -> None:
        """Gracefully stop the worker, escalating to terminate/kill. Always reaps."""
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                self.shutdown(timeout=_SHUTDOWN_GRACE_SECONDS)
            except WorkerSupervisorError:
                proc.terminate()
                try:
                    proc.wait(timeout=_KILL_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=_KILL_GRACE_SECONDS)
        proc.wait()
        self._exit_code = proc.returncode
        if self._stdout_thread is not None:
            self._stdout_thread.join(timeout=_KILL_GRACE_SECONDS)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=_KILL_GRACE_SECONDS)
        self._proc = None

    def __enter__(self) -> WorkerSupervisor:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Protocol exchange
    # ------------------------------------------------------------------

    def _require_running(self) -> subprocess.Popen[bytes]:
        proc = self._proc
        if proc is None:
            raise WorkerSupervisorError("supervisor not started")
        return proc

    def send(self, message: WorkerMessage) -> None:
        proc = self._require_running()
        if proc.poll() is not None:
            raise WorkerExitedError(proc.returncode)
        data = message.encode() + b"\n"
        if len(data) > MAX_MESSAGE_BYTES:
            raise WorkerSupervisorError("refusing to send an oversized message")
        assert proc.stdin is not None
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise WorkerExitedError(proc.poll()) from exc

    def send_raw(self, line: bytes) -> None:
        """Write a raw line to the worker's stdin (testing / diagnostics)."""
        proc = self._require_running()
        if proc.poll() is not None:
            raise WorkerExitedError(proc.returncode)
        assert proc.stdin is not None
        try:
            proc.stdin.write(line + b"\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise WorkerExitedError(proc.poll()) from exc

    def receive(self, timeout: float | None = None) -> WorkerMessage:
        self._require_running()
        while True:
            try:
                item = self._out_queue.get(timeout=timeout)
            except queue.Empty:
                proc = self._require_running()
                if proc.poll() is not None:
                    self._reap()
                    raise WorkerExitedError(self._exit_code) from None
                raise WorkerTimeoutError("timed out waiting for a worker message") from None
            if item is _EOF:
                self._reap()
                raise WorkerExitedError(self._exit_code)
            if item is _OVERSIZED:
                raise OversizedWorkerMessage(f"worker message exceeds {MAX_MESSAGE_BYTES} bytes")
            assert isinstance(item, bytes)
            try:
                return decode_message(item)
            except (MalformedMessageError, WorkerSupervisorError) as exc:
                raise MalformedWorkerMessage(str(exc)) from exc

    def _reap(self) -> None:
        proc = self._proc
        if proc is not None:
            proc.wait()
            self._exit_code = proc.returncode

    def wait_for_handshake(self) -> HelloMessage:
        """Wait up to the handshake timeout for the worker's hello."""
        try:
            message = self.receive(timeout=self._handshake_timeout)
        except WorkerTimeoutError as exc:
            self.stop()
            raise HandshakeTimeoutError(f"no hello within {self._handshake_timeout}s") from exc
        if not isinstance(message, HelloMessage):
            self.stop()
            raise WorkerSupervisorError(f"expected hello during handshake, got {message.type!r}")
        return message

    def ping(self, timeout: float = 5.0) -> PongMessage:
        nonce = uuid.uuid4().hex
        self.send(make_ping(nonce))
        message = self.receive(timeout=timeout)
        if not isinstance(message, PongMessage) or message.payload.nonce != nonce:
            raise WorkerSupervisorError(f"expected pong with nonce {nonce!r}, got {message.type!r}")
        return message

    def shutdown(self, timeout: float = 5.0) -> StoppedMessage:
        self.send(make_shutdown())
        message = self.receive(timeout=timeout)
        if not isinstance(message, StoppedMessage):
            raise WorkerSupervisorError(f"expected stopped, got {message.type!r}")
        return message

    # ------------------------------------------------------------------
    # Reader threads
    # ------------------------------------------------------------------

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        fd = proc.stdout.fileno()
        buf = b""
        while True:
            try:
                chunk = os.read(fd, _READ_CHUNK)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                if buf:
                    self._out_queue.put(buf)
                self._out_queue.put(_EOF)
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if len(line) > MAX_MESSAGE_BYTES:
                    self._out_queue.put(_OVERSIZED)
                else:
                    self._out_queue.put(line)

    def _read_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            with self._stderr_lock:
                if len(self._stderr_lines) < _STDERR_LINE_CAP:
                    self._stderr_lines.append(line)


def assert_no_leftover(pid: int | None) -> None:
    """Fail if a child process with this pid is still alive (tests)."""
    if pid is None:
        return
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    raise AssertionError(f"child process {pid} is still alive")
