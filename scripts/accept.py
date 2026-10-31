#!/usr/bin/env python3
"""Headless five-recording acceptance run for the analysis pipeline.

Runs the real offline Vamp pipeline (Piper + Chordino/Key Detector/Bar and Beat
Tracker) over every recording in ``audio2test``, measures each cold run, and
writes ``docs/acceptance/report.json`` and ``docs/acceptance/report.md``.

No browser, no network, no new dependencies. Missing recordings are reported
as ``missing`` and never replaced with invented values; the exit status is 0
only when every expected recording was analysed successfully.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DEFAULT_RECORDINGS = ROOT / "audio2test"
DEFAULT_REPORT = ROOT / "docs" / "acceptance"
DEFAULT_SAMPLE_RATE = 48_000
EXPECTED_RECORDINGS = (
    "46.GIBBS - Simplicity.wav",
    "Carousel Theory Full Mix V1 (With Limiter).wav",
    "Summer By The Sea Instrumental Demo.wav",
    "Sweet Demo.wav",
    "Videoslave Instrumental Demo.wav",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recordings-dir",
        type=Path,
        default=DEFAULT_RECORDINGS,
        help=f"folder with the acceptance recordings (default: {DEFAULT_RECORDINGS})",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"where report.json/report.md are written (default: {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help=f"project rate for analysis (default: {DEFAULT_SAMPLE_RATE})",
    )
    return parser.parse_args(argv)


def discover(directory: Path) -> tuple[list[Path], list[str]]:
    """Return recordings in a stable order plus any expected-but-missing names."""
    present = sorted(path for path in directory.glob("*.wav") if path.is_file())
    missing = [name for name in EXPECTED_RECORDINGS if not (directory / name).is_file()]
    extras = sorted(path.name for path in present if path.name not in EXPECTED_RECORDINGS)
    return present, missing + [f"extra:{name}" for name in extras]


def analyse(path: Path, sample_rate: int) -> dict[str, object]:
    """One cold analysis run; returns the report row or a failure row."""
    from basseparate.features import analyze_file

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="basseparate-accept-") as scratch:
            result = analyze_file(
                path,
                cache_dir=Path(scratch) / "cache",
                sample_rate=sample_rate,
                timeout_seconds=1800.0,
            )
        elapsed = time.perf_counter() - started
        raw_labels = [chord.label for chord in result.chords]
        filtered = [label for label in raw_labels if label not in {"N", "N.C.", ""}]
        return {
            "file": path.name,
            "status": "analyzed",
            "duration_seconds": round(result.meta.duration_seconds, 3),
            "analysis_seconds": round(elapsed, 3),
            "sample_rate": result.meta.sample_rate,
            "bpm": result.bpm,
            "key": result.key_label,
            "bars": result.grid.bar_count,
            "beats": len(result.grid.beats),
            "first_beat_seconds": result.grid.first_beat,
            "chords_count": len(result.chords),
            "chords": filtered,
            "chords_raw": raw_labels,
            "cached": result.cached,
        }
    except Exception as error:  # noqa: BLE001 - reported per recording, never hidden
        return {
            "file": path.name,
            "status": "failed",
            "duration_seconds": None,
            "analysis_seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(error).__name__}: {error}",
        }


def render_markdown(
    rows: list[dict[str, object]],
    *,
    sample_rate: int,
    generated_at: str,
    recording_dir: Path,
) -> str:
    lines = [
        "# Five-recording acceptance report",
        "",
        f"- Generated: {generated_at}",
        "- Mode: offline headless analysis pipeline (no browser, no network)",
        f"- Project sample rate: {sample_rate} Hz",
        f"- Recordings: `{recording_dir}`",
        "- Command: `.venv/bin/python scripts/accept.py`",
        "",
        "| Recording | Duration (s) | Analysis (s) | BPM | Key | Bars | Beats "
        "| Chords (N filtered) | Status |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        chords = row.get("chords") or []
        chord_text = ", ".join(str(label) for label in chords[:8])
        if len(chords) > 8:
            chord_text += f", … (+{len(chords) - 8})"
        lines.append(
            "| {file} | {duration} | {elapsed} | {bpm} | {key} | {bars} "
            "| {beats} | {chords} | {status}{error} |".format(
                file=row["file"],
                duration=_number(row.get("duration_seconds")),
                elapsed=_number(row.get("analysis_seconds")),
                bpm=_number(row.get("bpm")),
                key=row.get("key") or "—",
                bars=row.get("bars", "—"),
                beats=row.get("beats", "—"),
                chords=chord_text or "—",
                status=row["status"],
                error=f" ({row['error']})" if row.get("error") else "",
            )
        )
    analysed = [row for row in rows if row["status"] == "analyzed"]
    total_audio = sum(float(row["duration_seconds"] or 0) for row in analysed)
    total_time = sum(float(row["analysis_seconds"] or 0) for row in rows)
    lines += [
        "",
        "## Summary",
        "",
        f"- Analysed: {len(analysed)} / {len(rows)} recordings",
        f"- Audio measured: {total_audio:.2f} s",
        f"- Analysis wall time: {total_time:.2f} s",
        f"- Missing or extra recordings: {sum(1 for row in rows if row['status'] != 'analyzed')}",
        "",
        "Average values are not reported: the goal is per-recording evidence, "
        "not a smoothed number. Values are exactly what the offline pipeline "
        "returned on this machine; nothing was estimated or replaced.",
        "",
    ]
    return "\n".join(lines)


def _number(value: object) -> str:
    if isinstance(value, (int, float)) and value is not None:
        return f"{float(value):.3f}"
    return "—"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    recording_dir = Path(args.recordings_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if not recording_dir.is_dir():
        print(f"accept: recording directory not found: {recording_dir}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(SRC))
    present, missing = discover(recording_dir)
    rows: list[dict[str, object]] = []
    for name in EXPECTED_RECORDINGS:
        path = recording_dir / name
        if path.is_file():
            rows.append(analyse(path, args.sample_rate))
        else:
            rows.append(
                {
                    "file": name,
                    "status": "missing",
                    "duration_seconds": None,
                    "analysis_seconds": None,
                    "bpm": None,
                    "key": None,
                    "bars": None,
                    "beats": None,
                    "chords": [],
                }
            )
    for path in present:
        if path.name not in EXPECTED_RECORDINGS:
            rows.append(analyse(path, args.sample_rate))

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {
        "generated_at": generated_at,
        "mode": "offline headless analysis",
        "sample_rate": args.sample_rate,
        "recordings_dir": str(recording_dir),
        "recordings": rows,
        "missing_expected": missing,
        "analysed": sum(1 for row in rows if row["status"] == "analyzed"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "missing": sum(1 for row in rows if row["status"] == "missing"),
    }
    (report_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(
        rows,
        sample_rate=args.sample_rate,
        generated_at=generated_at,
        recording_dir=recording_dir,
    )
    (report_dir / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"accept: wrote {report_dir / 'report.md'} and {report_dir / 'report.json'}")

    failed = [row["file"] for row in rows if row["status"] == "failed"]
    absent = [row["file"] for row in rows if row["status"] == "missing"]
    if failed:
        print(f"accept: {len(failed)} recording(s) failed: {', '.join(failed)}", file=sys.stderr)
    if absent:
        print(
            f"accept: {len(absent)} expected recording(s) missing: {', '.join(absent)}",
            file=sys.stderr,
        )
    if missing:
        print(f"accept: discovery notes: {', '.join(missing)}", file=sys.stderr)
    return 0 if not failed and not absent else 1


if __name__ == "__main__":
    raise SystemExit(main())
