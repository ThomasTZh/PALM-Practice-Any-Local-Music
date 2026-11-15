"""Sonic Annotator discovery, CSV parsing, process control and path handling."""

from __future__ import annotations

import json
import stat
import struct
import threading
from pathlib import Path

import numpy as np
import pytest

from basseparate import features
from basseparate.sonic_annotator import (
    SonicAnnotatorBackend,
    SonicAnnotatorUnavailable,
    SonicCancelled,
    SonicParseError,
    SonicPluginError,
    SonicTimeout,
    parse_csv_features,
    write_float_wav,
)

FAKE = """#!/usr/bin/env python3
import json
import os
import struct
import sys
import time

args = sys.argv[1:]
if "--list" in args:
    print("vamp:embed-07-8888130:chordino:simplechord")
    print("vamp:qm-vamp-plugins:qm-keydetector:key")
    print("vamp:qm-vamp-plugins:qm-keydetector:tonic")
    print("vamp:qm-vamp-plugins:qm-keydetector:mode")
    print("vamp:qm-vamp-plugins:qm-barbeattracker:beats")
    print("vamp:qm-vamp-plugins:qm-barbeattracker:bars")
    print("vamp:embed-12-10378903:qm-barbeattracker:beats")
    print("vamp:embed-12-10378903:qm-barbeattracker:bars")
    if os.environ.get("FAKE_MISSING"):
        sys.exit(0)
    sys.exit(0)

if "-s" in args:
    print("vamp:plugin_version " + chr(34) * 3 + "5" + chr(34) * 3)
    sys.exit(0)
output = args[args.index("--csv-one-file") + 1]
if "-t" in args:
    ttl = __import__("pathlib").Path(args[args.index("-t") + 1]).read_text(encoding="utf-8")
    transform = "custom:simplechord" if "chordino" in ttl else "custom"
else:
    transform = args[args.index("-d") + 1]
audio = args[-1]
with open(audio, "rb") as handle:
    header = handle.read(44)
wave_format, channels, rate, _, _, bits = struct.unpack("<HHIIHH", header[20:36])
frames = (os.path.getsize(audio) - 44) // max(1, channels * bits // 8)
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "args": args,
            "transform": transform,
            "audio": audio,
            "frames": frames,
            "format": wave_format,
            "bits": bits,
            "channels": channels,
        }) + "\\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_BAD"):
    Path = __import__("pathlib").Path
    Path(output).write_text("not,a,valid,row\\n", encoding="utf-8")
    sys.exit(0)
if transform.endswith(":simplechord"):
    text = '0.0,"N"\\n0.5,"C"\\n'
elif transform.endswith(":key"):
    text = '0.0,1,"C major"\\n'
elif transform.endswith(":tonic"):
    text = '0.0,1,"C"\\n'
elif transform.endswith(":mode"):
    text = '0.0,0,"Major"\\n'
elif transform.endswith(":beats"):
    text = '0.5,"1"\\n1.0,"2"\\n'
elif transform.endswith(":bars"):
    text = '0.5,"1"\\n'
else:
    text = ""
Path = __import__("pathlib").Path
Path(output).write_text(text, encoding="utf-8")
"""


def fake_binary(tmp_path: Path, name: str = "sonic") -> Path:
    binary = tmp_path / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(FAKE, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def test_float_wav_header_is_ieee_float_32_mono(tmp_path: Path) -> None:
    path = tmp_path / "x.wav"
    write_float_wav(path, np.zeros(4, dtype=np.float32), 48000)
    data = path.read_bytes()
    assert data[:4] == b"RIFF"
    assert struct.unpack("<H", data[20:22])[0] == 3
    assert struct.unpack("<H", data[22:24])[0] == 1
    assert struct.unpack("<I", data[24:28])[0] == 48000
    assert struct.unpack("<H", data[34:36])[0] == 32
    assert len(data) == 44 + 4 * 4


def test_discovery_resolves_semantic_plugins_not_library_filenames(tmp_path: Path) -> None:
    backend = SonicAnnotatorBackend(binary=fake_binary(tmp_path), plugin_paths=(tmp_path,))
    plugins = backend.discover_plugins()
    assert plugins.chord.transform == "vamp:embed-07-8888130:chordino:simplechord"
    assert plugins.key.transform == "vamp:qm-vamp-plugins:qm-keydetector:key"
    assert plugins.beats.transform == "vamp:qm-vamp-plugins:qm-barbeattracker:beats"
    assert plugins.bars.transform == "vamp:qm-vamp-plugins:qm-barbeattracker:bars"


def test_analyze_pads_only_with_lead_and_writes_csv_arguments(tmp_path: Path) -> None:
    binary = fake_binary(tmp_path)
    backend = SonicAnnotatorBackend(binary=binary, plugin_paths=(tmp_path,))
    result = backend.analyze(
        np.arange(100, dtype=np.float32),
        sample_rate=10,
        bpb=4,
        lead_in_seconds=0.5,
        specs=features.plugin_specs(4),
    )
    assert set(result.features) == {
        features.CHORD_PLUGIN,
        features.KEY_PLUGIN,
        features.BEAT_PLUGIN,
    }
    assert result.features[features.CHORD_PLUGIN][features.CHORD_OUTPUT][0]["label"] == "N"
    assert result.features[features.BEAT_PLUGIN][features.BARS_OUTPUT][0]["label"] == "1"
    # Frames and format are asserted in the logged run below.


def test_analyze_uses_lead_and_tail_padding_for_beats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    binary = fake_binary(tmp_path)
    backend = SonicAnnotatorBackend(binary=binary, plugin_paths=(tmp_path,))
    backend.analyze(
        np.zeros(100, dtype=np.float32),
        sample_rate=10,
        bpb=4,
        lead_in_seconds=0.5,
        specs=features.plugin_specs(4),
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    by_transform = {call["transform"].rsplit(":", 1)[-1]: call for call in calls}
    assert by_transform["simplechord"]["frames"] == 100
    assert by_transform["key"]["frames"] == 100
    assert by_transform["tonic"]["frames"] == 100
    assert by_transform["mode"]["frames"] == 100
    assert by_transform["beats"]["frames"] == 100 + 5 + 20
    assert by_transform["bars"]["frames"] == 100 + 5 + 20
    assert by_transform["simplechord"]["format"] == 3
    assert by_transform["simplechord"]["bits"] == 32
    assert by_transform["simplechord"]["channels"] == 1


def test_no_lead_means_no_tail_padding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    backend = SonicAnnotatorBackend(binary=fake_binary(tmp_path), plugin_paths=(tmp_path,))
    backend.analyze(
        np.zeros(100, dtype=np.float32),
        sample_rate=10,
        bpb=4,
        lead_in_seconds=0.0,
        specs=features.plugin_specs(4),
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert next(call for call in calls if call["transform"].endswith(":beats"))["frames"] == 100


def test_header_and_headerless_csv_parsing(tmp_path: Path) -> None:
    header = tmp_path / "header.csv"
    header.write_text("time,values,label\n1.25,1,C major\n", encoding="utf-8")
    rows = parse_csv_features(header, default_columns=("time", "values", "label"))
    assert rows[0].time_seconds == 1.25
    assert rows[0].values == (1.0,)
    assert rows[0].label == "C major"
    headerless = tmp_path / "plain.csv"
    headerless.write_text('2.0,"C"\n', encoding="utf-8")
    rows = parse_csv_features(headerless, default_columns=("time", "label"))
    assert rows[0].label == "C"
    with pytest.raises(SonicParseError, match="expected 2 columns"):
        bad = tmp_path / "bad.csv"
        bad.write_text("1.0,2.0,3.0,4.0\n", encoding="utf-8")
        parse_csv_features(bad, default_columns=("time", "label"))


def test_missing_plugins_and_binary_are_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = SonicAnnotatorBackend(binary=fake_binary(tmp_path), plugin_paths=(tmp_path,))
    monkeypatch.setenv("FAKE_MISSING", "1")
    # The fake list still has all plugins; this test verifies the missing binary path.
    backend.binary = tmp_path / "does-not-exist"
    with pytest.raises(SonicAnnotatorUnavailable, match="not found"):
        backend.discover_plugins()
    binary = fake_binary(tmp_path / "other")
    missing = SonicAnnotatorBackend(binary=binary, plugin_paths=(tmp_path,))
    missing._resolved = None
    # Replace the list output by running a small wrapper is overkill; use a
    # backend whose binary is a shell script printing only one plugin.
    only = tmp_path / "only.sh"
    only.write_text(
        '#!/bin/sh\nprintf "vamp:qm-vamp-plugins:qm-keydetector:key\\n"\n', encoding="utf-8"
    )
    only.chmod(0o755)
    with pytest.raises(SonicPluginError, match="required Vamp plugins are missing"):
        SonicAnnotatorBackend(binary=only, plugin_paths=(tmp_path,)).discover_plugins()


def test_malformed_csv_raises_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BAD", "1")
    backend = SonicAnnotatorBackend(binary=fake_binary(tmp_path), plugin_paths=(tmp_path,))
    with pytest.raises(SonicParseError, match="unrecognized header|expected"):
        backend.analyze(
            np.zeros(100, dtype=np.float32),
            sample_rate=10,
            bpb=4,
            lead_in_seconds=0.0,
            specs=features.plugin_specs(4),
        )


def test_timeout_terminates_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SLEEP", "5")
    backend = SonicAnnotatorBackend(
        binary=fake_binary(tmp_path), plugin_paths=(tmp_path,), timeout_seconds=0.1
    )
    with pytest.raises(SonicTimeout, match="timed out"):
        backend.analyze(
            np.zeros(100, dtype=np.float32),
            sample_rate=10,
            bpb=4,
            lead_in_seconds=0.0,
            specs=features.plugin_specs(4),
        )


def test_cancellation_terminates_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SLEEP", "5")
    cancelled = threading.Event()
    backend = SonicAnnotatorBackend(binary=fake_binary(tmp_path), plugin_paths=(tmp_path,))

    def progress(fraction: float, message: str) -> None:
        if fraction >= 0.2:
            cancelled.set()

    with pytest.raises(SonicCancelled, match="cancelled"):
        backend.analyze(
            np.zeros(100, dtype=np.float32),
            sample_rate=10,
            bpb=4,
            lead_in_seconds=0.0,
            specs=features.plugin_specs(4),
            is_cancelled=cancelled.is_set,
            on_progress=progress,
        )


def test_paths_with_spaces_and_non_ascii_are_argument_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "with space" / "café"
    root.mkdir(parents=True)
    binary = fake_binary(root, "sonic annotator")
    log = root / "log.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    backend = SonicAnnotatorBackend(binary=binary, plugin_paths=(root,), tmp_root=root)
    result = backend.analyze(
        np.zeros(12, dtype=np.float32),
        sample_rate=12,
        bpb=4,
        lead_in_seconds=0.0,
        specs=features.plugin_specs(4),
    )
    assert result.features[features.KEY_PLUGIN][features.KEY_OUTPUT][0]["label"] == "C major"
    assert log.read_text(encoding="utf-8").count("audio") == 6
