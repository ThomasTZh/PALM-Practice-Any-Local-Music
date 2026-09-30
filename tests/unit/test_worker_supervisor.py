"""Supervisor + probe worker tests (M0.9, spec 10.6).

Covers: successful handshake, ping/pong, version mismatch, invalid
JSON, oversized message, missing handshake, worker exception,
unexpected exit, stderr without protocol corruption, graceful
shutdown, timeout cleanup, and no leftover child process.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

from basseparate.worker import (
    ERR_MALFORMED,
    ERR_OVERSIZED,
    ERR_VERSION_MISMATCH,
    MAX_MESSAGE_BYTES,
    CapabilitiesMessage,
    ErrorMessage,
    HelloMessage,
    PongMessage,
    StoppedMessage,
    WorkerExitedError,
    WorkerSupervisor,
    WorkerSupervisorError,
    WorkerTimeoutError,
    assert_no_leftover,
    make_describe,
    make_ping,
    worker_message_adapter,
)


def _write_worker_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / f"worker_{uuid.uuid4().hex[:8]}.py"
    script.write_text(body, encoding="utf-8")
    return script


_HELLO_ONLY_SCRIPT = """
import sys
from basseparate.worker.protocol import make_hello
print(make_hello("probe").model_dump_json(), flush=True)
"""

_HELLO_THEN_RAISE = (
    _HELLO_ONLY_SCRIPT
    + """
raise RuntimeError("boom")
"""
)

_HELLO_THEN_HARD_EXIT = (
    _HELLO_ONLY_SCRIPT
    + """
import os
os._exit(3)
"""
)

_HELLO_THEN_SLEEP = (
    _HELLO_ONLY_SCRIPT
    + """
import time
time.sleep(60)
"""
)


@pytest.fixture()
def sup() -> WorkerSupervisor:
    supervisor = WorkerSupervisor(cwd=Path.cwd())
    supervisor.start()
    yield supervisor
    supervisor.stop()


class TestHandshake:
    def test_successful_handshake(self, sup: WorkerSupervisor) -> None:
        hello = sup.wait_for_handshake()
        assert isinstance(hello, HelloMessage)
        assert hello.payload.worker == "probe"
        assert hello.payload.protocol_version == 1

    def test_missing_handshake_times_out_and_reaps(self, tmp_path: Path) -> None:
        script = _write_worker_script(tmp_path, "import time\ntime.sleep(30)\n")
        supervisor = WorkerSupervisor(
            command=[sys.executable, str(script)],
            cwd=tmp_path,
            handshake_timeout=0.5,
        )
        supervisor.start()
        pid = supervisor.pid
        with pytest.raises(WorkerSupervisorError):
            supervisor.wait_for_handshake()
        assert supervisor.exit_code is not None
        assert_no_leftover(pid)


class TestPingPong:
    def test_ping_pong_echoes_nonce(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        pong = sup.ping()
        assert isinstance(pong, PongMessage)
        assert pong.payload.nonce

    def test_pong_references_ping(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        ping = make_ping("custom-nonce")
        sup.send(ping)
        msg = sup.receive(timeout=5.0)
        assert isinstance(msg, PongMessage)
        assert msg.payload.nonce == "custom-nonce"
        assert msg.request_id == ping.message_id

    def test_capabilities_are_model_free(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        sup.send(make_describe())
        caps = sup.receive(timeout=5.0)
        assert isinstance(caps, CapabilitiesMessage)
        assert caps.payload.worker == "probe"
        assert caps.payload.models == []
        assert [c.id for c in caps.payload.capabilities] == ["diagnostic.ping"]


class TestMalformedInput:
    def test_version_mismatch(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        raw = {
            "protocol_version": 99,
            "message_id": str(uuid.uuid4()),
            "request_id": None,
            "type": "describe",
            "payload": {},
        }
        msg = worker_message_adapter.validate_python(raw)
        sup.send(msg)
        err = sup.receive(timeout=5.0)
        assert isinstance(err, ErrorMessage)
        assert err.payload.code == ERR_VERSION_MISMATCH

    def test_invalid_json(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        sup.send_raw(b"this is {not json")
        err = sup.receive(timeout=5.0)
        assert isinstance(err, ErrorMessage)
        assert err.payload.code == ERR_MALFORMED

    def test_oversized_message(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        sup.send_raw(b"x" * (MAX_MESSAGE_BYTES + 1))
        err = sup.receive(timeout=5.0)
        assert isinstance(err, ErrorMessage)
        assert err.payload.code == ERR_OVERSIZED
        # The protocol stream is still usable afterwards.
        pong = sup.ping(timeout=5.0)
        assert isinstance(pong, PongMessage)


class TestWorkerFailures:
    def test_worker_exception_detected(self, tmp_path: Path) -> None:
        script = _write_worker_script(tmp_path, _HELLO_THEN_RAISE)
        supervisor = WorkerSupervisor(command=[sys.executable, str(script)], cwd=tmp_path)
        supervisor.start()
        pid = supervisor.pid
        hello = supervisor.wait_for_handshake()
        assert isinstance(hello, HelloMessage)
        with pytest.raises(WorkerExitedError) as excinfo:
            supervisor.receive(timeout=5.0)
        assert excinfo.value.returncode == 1
        supervisor.stop()
        assert_no_leftover(pid)

    def test_unexpected_exit(self, tmp_path: Path) -> None:
        script = _write_worker_script(tmp_path, _HELLO_THEN_HARD_EXIT)
        supervisor = WorkerSupervisor(command=[sys.executable, str(script)], cwd=tmp_path)
        supervisor.start()
        pid = supervisor.pid
        supervisor.wait_for_handshake()
        with pytest.raises(WorkerExitedError) as excinfo:
            supervisor.receive(timeout=5.0)
        assert excinfo.value.returncode == 3
        supervisor.stop()
        assert_no_leftover(pid)

    def test_stderr_does_not_corrupt_protocol(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        sup.ping()
        sup.send(make_describe())
        caps = sup.receive(timeout=5.0)
        assert isinstance(caps, CapabilitiesMessage)
        # The worker logs to stderr; the lines are captured, not mixed
        # into the stdout protocol stream.
        lines = sup.stderr_lines
        assert any("probe-worker" in line for line in lines)

    def test_timeout_cleanup_kills_hung_worker(self, tmp_path: Path) -> None:
        script = _write_worker_script(tmp_path, _HELLO_THEN_SLEEP)
        supervisor = WorkerSupervisor(command=[sys.executable, str(script)], cwd=tmp_path)
        supervisor.start()
        pid = supervisor.pid
        supervisor.wait_for_handshake()
        with pytest.raises(WorkerTimeoutError):
            sup_ping = supervisor.ping(timeout=0.5)
            assert sup_ping is not None
        supervisor.stop()
        assert supervisor.exit_code is not None
        assert_no_leftover(pid)


class TestShutdown:
    def test_graceful_shutdown(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        stopped = sup.shutdown()
        assert isinstance(stopped, StoppedMessage)
        assert stopped.payload.exit_code == 0
        sup.stop()
        assert sup.exit_code == 0

    def test_no_leftover_child(self, sup: WorkerSupervisor) -> None:
        sup.wait_for_handshake()
        sup.ping()
        pid = sup.pid
        sup.stop()
        assert sup.exit_code == 0
        assert_no_leftover(pid)


class TestProbeCliModule:
    def test_probe_worker_stops_on_stdin_eof(self, tmp_path: Path) -> None:
        supervisor = WorkerSupervisor(cwd=tmp_path)
        supervisor.start()
        pid = supervisor.pid
        supervisor.wait_for_handshake()
        # Close stdin: the worker must stop cleanly on EOF.
        assert supervisor._proc is not None
        assert supervisor._proc.stdin is not None
        supervisor._proc.stdin.close()
        with pytest.raises(WorkerExitedError) as excinfo:
            supervisor.receive(timeout=5.0)
        assert excinfo.value.returncode == 0
        supervisor.stop()
        assert_no_leftover(pid)

    def test_json_helper_sanity(self) -> None:
        # Guard against accidental changes to the on-the-wire shape.
        msg = make_ping("n")
        payload = json.loads(msg.encode())
        assert set(payload) == {
            "protocol_version",
            "message_id",
            "request_id",
            "type",
            "payload",
        }
