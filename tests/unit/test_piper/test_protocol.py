"""Unit tests for the Piper client: protocol, discovery, errors, cancellation.

A small fake server exercises the JSON-lines contract without depending on the
real plugin pack, so every error path is deterministic. The real plugins are
covered by ``tests/integration/test_analysis.py``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from basseparate.piper import (
    AnalysisCancelled,
    PiperPaths,
    PiperProcessError,
    PiperSession,
    PiperTimeout,
    PiperUnavailable,
    feature_label,
    feature_time,
    feature_values,
)

FAKE_SERVER = r"""#!/usr/bin/env python3
import json
import os
import sys
import time

mode = os.environ.get("FAKE_PIPER_MODE", "ok")
print(f"fake piper stderr: {mode}", file=sys.stderr, flush=True)
if mode == "crash":
    sys.exit(3)
if mode == "hang":
    time.sleep(30)

PLUGINS = [
    ("Chordino", "fake:chordino", "simplechord"),
    ("Key Detector", "fake:key", "key"),
    ("Bar and Beat Tracker", "fake:beats", "beats"),
]
if mode == "fallback":
    PLUGINS = [
        ("Mystery Chords", "embed-07-8888130:chordino", "simplechord"),
        ("Mystery Key", "embed-12-10378903:qm-keydetector", "key"),
        ("Mystery Beats", "embed-12-10378903:qm-barbeattracker", "beats"),
    ]
LATIN1 = "Caf\u00e9 Tuner"

state = {"handle": 0, "key": "", "emitted": set()}


def emit(payload):
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("latin-1") + b"\n")
    sys.stdout.buffer.flush()


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    params = request.get("params", {})
    identifier = request.get("id")
    if method == "list":
        available = []
        for index, (name, key, output) in enumerate(PLUGINS):
            available.append({
                "basic": {"name": name, "identifier": f"fake-{index}"},
                "key": key,
                "version": 1,
                "basicOutputInfo": [{"identifier": output}],
            })
        available.append({
            "basic": {"name": LATIN1, "identifier": "cafe"},
            "key": "fake:cafe",
            "version": 1,
            "basicOutputInfo": [{"identifier": "out"}],
        })
        emit({"jsonrpc": "2.0", "id": identifier, "method": method,
              "result": {"available": available}})
    elif method == "load":
        state["handle"] += 1
        state["key"] = params["key"]
        values = {"bpb": 4} if "beat" in state["key"] else {}
        emit({"jsonrpc": "2.0", "id": identifier, "method": method, "result": {
            "handle": state["handle"],
            "defaultConfiguration": {
                "channelCount": 1,
                "framing": {"blockSize": 8, "stepSize": 4},
                "parameterValues": values,
            },
            "staticData": {"version": 7},
            "programParameters": {},
        }})
    elif method == "configure":
        handle = params["handle"]
        emit({"jsonrpc": "2.0", "id": identifier, "method": method, "result": {
            "handle": handle,
            "framing": {"blockSize": 8, "stepSize": 4},
            "outputList": [],
        }})
    elif method == "process":
        handle = params["handle"]
        stamp = params["processInput"]["timestamp"]
        features = {}
        if handle == 1 and "chord" not in state["emitted"]:
            features["simplechord"] = [{"timestamp": stamp, "label": "C:maj"}]
            state["emitted"].add("chord")
        elif handle == 2 and "key" not in state["emitted"]:
            features["key"] = [{"timestamp": stamp, "label": "C major", "featureValues": [1]}]
            features["tonic"] = [{"timestamp": stamp, "label": None, "featureValues": [1]}]
            features["mode"] = [{"timestamp": stamp, "label": None, "featureValues": [0]}]
            state["emitted"].add("key")
        elif handle == 3:
            features["beats"] = [{"timestamp": stamp, "label": "1", "featureValues": []}]
            features["bars"] = [{"timestamp": stamp, "label": "1", "featureValues": []}]
        emit({"jsonrpc": "2.0", "id": identifier, "method": method,
              "result": {"handle": handle, "features": features}})
    elif method == "finish":
        emit({"jsonrpc": "2.0", "id": identifier, "method": method,
              "result": {"handle": params["handle"], "features": {}}})
    else:
        emit({"jsonrpc": "2.0", "id": identifier,
              "error": {"code": 0, "message": f"unknown method {method}"}})
"""


@pytest.fixture
def fake_paths(tmp_path: Path) -> PiperPaths:
    server = tmp_path / "fake-piper"
    server.write_text(FAKE_SERVER)
    server.chmod(0o755)
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "fake.so").write_bytes(b"")
    libraries = tmp_path / "lib"
    libraries.mkdir()
    return PiperPaths(server=server, plugin_path=plugins, library_path=libraries)


def test_missing_server_names_the_asset_and_bootstrap(tmp_path: Path) -> None:
    paths = PiperPaths.for_project(tmp_path)
    with pytest.raises(PiperUnavailable) as error:
        paths.validate()
    message = str(error.value)
    assert "storage/tools/sv" in message
    assert "make bootstrap" in message


def test_missing_plugin_pack_names_the_preserved_pack(fake_paths: PiperPaths) -> None:
    missing = PiperPaths(
        server=fake_paths.server,
        plugin_path=fake_paths.plugin_path / "absent",
        library_path=fake_paths.library_path,
    )
    with pytest.raises(PiperUnavailable) as error:
        missing.validate()
    message = str(error.value)
    assert "Vamp plugin pack not found" in message
    assert "storage/tools/plugins" in message


def test_empty_plugin_pack_is_rejected(tmp_path: Path, fake_paths: PiperPaths) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    paths = PiperPaths(
        server=fake_paths.server, plugin_path=empty, library_path=fake_paths.library_path
    )
    with pytest.raises(PiperUnavailable, match=r"contains no \*\.so"):
        paths.validate()


def test_resolution_is_by_display_name(fake_paths: PiperPaths) -> None:
    with PiperSession(fake_paths) as session:
        plugins = session.list_plugins()
        assert any(plugin.display_name == "Caf\u00e9 Tuner" for plugin in plugins)
        chordino = session.resolve("Chordino")
        assert chordino.display_name == "Chordino"
        assert chordino.key == "fake:chordino"


def test_resolution_falls_back_to_known_embed_keys(
    fake_paths: PiperPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PIPER_MODE", "fallback")
    with PiperSession(fake_paths) as session:
        chordino = session.resolve("Chordino")
        assert chordino.key == "embed-07-8888130:chordino"
        assert chordino.display_name == "Mystery Chords"


def test_unknown_display_name_is_actionable(fake_paths: PiperPaths) -> None:
    with PiperSession(fake_paths) as session, pytest.raises(PiperUnavailable) as error:
        session.resolve("No Such Plugin")
    assert "No Such Plugin" in str(error.value)
    assert "display" in str(error.value)


def test_full_protocol_run(fake_paths: PiperPaths) -> None:
    signal = np.zeros(12, dtype=np.float32)
    with PiperSession(fake_paths) as session:
        chord_plugin, chord_features = session.analyze("Chordino", signal, sample_rate=8)
        assert chord_plugin.key == "fake:chordino"
        assert chord_plugin.block_size == 8
        assert chord_plugin.step_size == 4
        assert chord_plugin.version == "7"
        rows = chord_features["simplechord"]
        assert [feature_label(row) for row in rows] == ["C:maj"]
        assert feature_time(rows[0]) == 0.0
        key_plugin, key_features = session.analyze("Key Detector", signal, sample_rate=8)
        assert key_plugin.display_name == "Key Detector"
        assert [feature_label(row) for row in key_features["key"]] == ["C major"]
        assert feature_values(key_features["key"][0]) == (1.0,)
        beat_plugin, beat_features = session.analyze(
            "Bar and Beat Tracker", signal, sample_rate=8, parameters={"bpb": 4}
        )
        assert beat_plugin.parameters["bpb"] == 4.0
        assert len(beat_features["beats"]) == 3


def test_unknown_parameter_is_rejected(fake_paths: PiperPaths) -> None:
    with PiperSession(fake_paths) as session, pytest.raises(PiperProcessError) as error:
        session.load("Bar and Beat Tracker", sample_rate=8, parameters={"nope": 1.0})
    assert "has no parameter" in str(error.value)


def test_timeout_kills_the_child_and_reports_stderr(
    fake_paths: PiperPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PIPER_MODE", "hang")
    started = time.monotonic()
    with (
        pytest.raises(PiperTimeout) as error,
        PiperSession(fake_paths, timeout_seconds=0.3) as session,
    ):
        session.list_plugins()
    assert time.monotonic() - started < 10
    message = str(error.value)
    assert "timed out" in message
    assert "fake piper stderr: hang" in message


def test_non_zero_exit_reports_stderr_tail(
    fake_paths: PiperPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PIPER_MODE", "crash")
    with (
        pytest.raises(PiperProcessError) as error,
        PiperSession(fake_paths, timeout_seconds=5) as session,
    ):
        session.list_plugins()
    message = str(error.value)
    assert "fake piper stderr: crash" in message
    assert "exit status 3" in message or "closed stdout" in message


def test_cancellation_before_a_request_kills_the_child(fake_paths: PiperPaths) -> None:
    cancelled = False
    session_ref: list[PiperSession] = []
    with (
        pytest.raises(AnalysisCancelled),
        PiperSession(fake_paths, is_cancelled=lambda: cancelled) as session,
    ):
        session_ref.append(session)
        session.analyze("Chordino", np.zeros(64, dtype=np.float32), sample_rate=8)
        cancelled = True
        session.request("list", {})
    assert session_ref[0].pid is None


def test_cancellation_during_feed_kills_the_child(fake_paths: PiperPaths) -> None:
    cancelled = False
    pid_holder: list[int] = []
    session_ref: list[PiperSession] = []

    def on_progress(display_name: str, processed: int, total: int) -> None:
        nonlocal cancelled
        if not cancelled:
            pid = session_ref[0].pid
            assert pid is not None
            pid_holder.append(pid)
            cancelled = True

    with (
        pytest.raises(AnalysisCancelled),
        PiperSession(
            fake_paths,
            is_cancelled=lambda: cancelled,
            on_progress=on_progress,
        ) as session,
    ):
        session_ref.append(session)
        session.analyze("Chordino", np.zeros(64, dtype=np.float32), sample_rate=8)
    assert pid_holder
    assert session_ref[0].pid is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid_holder[0], 0)
