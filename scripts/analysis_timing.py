#!/usr/bin/env python3
"""Measure the cold analysis time of a five-minute recording.

The timing covers the whole pipeline the user waits for: decode/resample,
Chordino, Key Detector, Bar and Beat Tracker, parsing and the atomic cache
write. The cache directory is temporary, so every run is a cold run.

Exit status is 0 when the analysis completed, even if the limit was exceeded:
the contract requires an overrun to be recorded without changing the design.
Use ``--strict`` to turn an overrun into exit status 1 in a gate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basseparate.features import AnalysisError, analyze_file  # noqa: E402

RECORDINGS = ROOT / "audio2test"
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_LIMIT_SECONDS = 60.0
MINIMUM_FIVE_MINUTE_SECONDS = 240.0


def probe_duration(path: Path) -> float | None:
    """Read the container duration with the local ffprobe, or return None."""
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def choose_recording(explicit: str | None) -> Path:
    """Pick a preserved recording close to five minutes long."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise AnalysisError(f"recording not found: {path}")
        return path
    from_env = os.environ.get("BASSEPARATE_TIMING_AUDIO")
    if from_env:
        path = Path(from_env).expanduser().resolve()
        if not path.is_file():
            raise AnalysisError(f"BASSEPARATE_TIMING_AUDIO is not a file: {path}")
        return path
    candidates = sorted(RECORDINGS.glob("*.wav")) if RECORDINGS.is_dir() else []
    if not candidates:
        raise AnalysisError(
            f"no timing recording found in {RECORDINGS}; pass --audio PATH or set "
            "BASSEPARATE_TIMING_AUDIO"
        )
    durations = [(probe_duration(path), path) for path in candidates]
    usable = [(duration, path) for duration, path in durations if duration is not None]
    if not usable:
        return candidates[0]
    return min(usable, key=lambda item: abs(item[0] - 300.0))[1]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", help="recording to analyse (default: a preserved 5-minute file)")
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="project sample rate (default: 48000)",
    )
    parser.add_argument(
        "--limit",
        type=float,
        default=DEFAULT_LIMIT_SECONDS,
        help="time limit in seconds (default: 60)",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when the limit is exceeded")
    parser.add_argument(
        "--json", action="store_true", help="print one JSON object instead of lines"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        recording = choose_recording(args.audio)
    except AnalysisError as error:
        print(f"analysis-timing: {error}", file=sys.stderr)
        return 1
    duration = probe_duration(recording)
    if duration is not None and duration < MINIMUM_FIVE_MINUTE_SECONDS:
        print(
            f"analysis-timing: {recording.name} is {duration:.1f} s, shorter than the "
            f"{MINIMUM_FIVE_MINUTE_SECONDS:.0f} s required for a five-minute measurement; "
            "pass a longer --audio file",
            file=sys.stderr,
        )
        return 1
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="basseparate-timing-") as scratch:
            result = analyze_file(
                recording,
                cache_dir=Path(scratch) / "cache",
                sample_rate=args.sample_rate,
                timeout_seconds=900.0,
            )
    except AnalysisError as error:
        print(f"analysis-timing: analysis failed: {error}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started
    within_limit = elapsed <= args.limit
    payload = {
        "audio": str(recording),
        "duration_seconds": round(result.meta.duration_seconds, 3),
        "sample_rate": result.meta.sample_rate,
        "elapsed_seconds": round(elapsed, 3),
        "limit_seconds": args.limit,
        "status": "OK" if within_limit else "OVER",
        "bpm": result.bpm,
        "key": result.key_label,
        "bars": result.grid.bar_count,
        "beats": len(result.grid.beats),
        "chords": len(result.chords),
        "cached": result.cached,
        "plugins": [
            {
                "display_name": plugin.display_name,
                "key": plugin.key,
                "block_size": plugin.block_size,
                "step_size": plugin.step_size,
            }
            for plugin in result.meta.plugins
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "OK" if within_limit else "OVER LIMIT"
        print(f"analysis-timing: audio {recording.name}")
        print(
            f"analysis-timing: duration {payload['duration_seconds']:.2f} s, "
            f"project rate {payload['sample_rate']} Hz, cold cache"
        )
        print(
            "analysis-timing: plugins "
            + ", ".join(plugin["display_name"] for plugin in payload["plugins"])
        )
        print(f"analysis-timing: elapsed {elapsed:.2f} s (limit {args.limit:.2f} s) {status}")
        print(
            f"analysis-timing: bpm={payload['bpm']} key={payload['key']} "
            f"bars={payload['bars']} beats={payload['beats']} chords={payload['chords']}"
        )
    if args.strict and not within_limit:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
