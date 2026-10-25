#!/usr/bin/env python3
"""Run a Vamp plugin through Sonic Visualiser's Piper host.

Evaluation only. This is not imported by the application and must not become a
runtime dependency: the Vamp plugin pack and Sonic Visualiser are distributed
under GPL/AGPL-compatible licences. Use the output as a reference oracle when
comparing basseparate's rhythm postprocessing with established trackers.

The host and plugin directory are supplied explicitly so the repository does
not assume a system installation:

    python scripts/vamp_reference.py \
        --server /path/to/piper-vamp-simple-server \
        --vamp-path /path/to/vamp-plugins \
        --plugin qm-vamp-plugins:qm-barbeattracker \
        --audio excerpt.wav \
        --output beats.json

The WAV is decoded to mono float samples at its native rate. The script
supports the load/configure/process/finish JSON protocol used by Piper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave
from pathlib import Path


def _read_mono(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        if width != 2:
            raise ValueError("only 16-bit PCM WAV excerpts are supported")
        raw = handle.readframes(handle.getnframes())
    count = len(raw) // 2
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) / 32768.0
        for i in range(0, count * 2, 2)
    ]
    if channels > 1:
        samples = [
            sum(samples[index : index + channels]) / channels
            for index in range(0, len(samples), channels)
        ]
    return samples, rate


def _send(process: subprocess.Popen[str], payload: dict[str, object]) -> dict[str, object]:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("Piper host closed its output")
    response = json.loads(line)
    if "error" in response:
        raise RuntimeError(f"Piper error: {response['error'].get('message')}")
    return response


def _timestamp_seconds(timestamp: dict[str, int] | None) -> float | None:
    if timestamp is None:
        return None
    return float(timestamp.get("s", 0)) + float(timestamp.get("n", 0)) / 1e9


def run(
    *,
    server: Path,
    vamp_path: Path,
    plugin: str,
    audio: Path,
    output: Path,
    bpb: int,
) -> dict[str, object]:
    samples, rate = _read_mono(audio)
    env = dict(os.environ)
    env["VAMP_PATH"] = str(vamp_path)
    process = subprocess.Popen(
        [str(server), "json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        loaded = _send(
            process,
            {
                "method": "load",
                "params": {"key": plugin, "inputSampleRate": rate},
            },
        )["result"]
        configuration = loaded["defaultConfiguration"]
        configuration["parameterValues"]["bpb"] = bpb
        configured = _send(
            process,
            {
                "method": "configure",
                "params": {"handle": loaded["handle"], "configuration": configuration},
            },
        )["result"]
        block = int(configured["framing"]["blockSize"])
        step = int(configured["framing"]["stepSize"])

        features: dict[str, list[dict[str, object]]] = {}
        for start in range(0, max(0, len(samples) - block + 1), step):
            response = _send(
                process,
                {
                    "method": "process",
                    "params": {
                        "handle": loaded["handle"],
                        "processInput": {
                            "inputBuffers": [samples[start : start + block]],
                            "timestamp": {
                                "s": start // rate,
                                "n": (start % rate) * 1_000_000_000 // rate,
                            },
                        },
                    },
                },
            )
            for key, values in (response.get("result", {}).get("features", {}) or {}).items():
                features.setdefault(key, []).extend(values)

        finished = _send(
            process,
            {"method": "finish", "params": {"handle": loaded["handle"]}},
        )
        for key, values in (finished.get("result", {}).get("features", {}) or {}).items():
            features.setdefault(key, []).extend(values)
    finally:
        process.kill()
        process.wait()

    serialised: dict[str, list[dict[str, object]]] = {}
    for key, values in features.items():
        rows = []
        for value in values:
            row: dict[str, object] = {
                "time_seconds": _timestamp_seconds(value.get("timestamp")),
                "label": value.get("label"),
            }
            if "featureValues" in value:
                row["values"] = value["featureValues"]
            rows.append(row)
        serialised[key] = rows
    result = {
        "plugin": plugin,
        "sample_rate": rate,
        "duration_seconds": len(samples) / rate,
        "bpb": bpb,
        "features": serialised,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--vamp-path", required=True, type=Path)
    parser.add_argument("--plugin", default="qm-vamp-plugins:qm-barbeattracker")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--bpb", type=int, default=4, help="Beats per bar hint for bar/beat plugins"
    )
    args = parser.parse_args()
    result = run(
        server=args.server,
        vamp_path=args.vamp_path,
        plugin=args.plugin,
        audio=args.audio,
        output=args.output,
        bpb=args.bpb,
    )
    counts = {key: len(value) for key, value in result["features"].items()}
    print(f"plugin={result['plugin']} rate={result['sample_rate']} features={counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
