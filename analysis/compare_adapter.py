"""Adapter-vs-reference comparison gate (M2.5, spec §7.3).

Two modes:

**single** (the literal §7.3 short-input gate): the adapter output is
compared against one whole-track upstream reference. For a single-window
track the adapter must reproduce the reference exactly (verified:
bit-exact on a 30 s track).

**windows** (the multi-window gate): a whole-track reference is *not*
the correct baseline for a windowed run — the pinned upstream code
draws its shift offsets and pos-embedding shifts from one global Python
``random`` stream, interleaved with one ``random.randrange`` call per
internal segment (``demucs/transformer.py``, ``_get_pos_embedding``).
The shift offsets therefore depend on total track length: two
whole-track runs of the same content with the same seed (120 s vs 480 s)
diverge everywhere (evidence in ``docs/evidence/m2.5-bounded-separation.md``).
The upstream-equivalent baseline for each outer window is a whole-track
reference of *just that window's slice*, seeded with the same per-window
seed (run seed + window index) the adapter used. Windows mode verifies:

- labels/shape: strict;
- identity regions (outside the 8 s blend bands): the adapter equals
  the per-window reference — gate max abs diff < 1e-6 (expect 0.0);
- blend regions (each 8 s overlap band): the adapter equals the exact
  weighted combination ``w_prev·ref_prev + w_cur·ref_cur`` divided by
  the accumulated weight, with the complementary raised-cosine weights
  from the main-env windowing module — gate max abs diff < 1e-6
  (expect ≤ one float32 ulp, the staged writes round to float32);
- scale ratio per stem 0.9–1.1, alignment lag ≤ 1 sample (vs the
  per-window references, interior region);
- boundary artifacts: diff energy in the blend bands vs the interior,
  per-sample ratio < 3.0;
- bass continuity: RMS level 1 s before/after each boundary 0.8–1.25.

Thresholds are the M2.5 gate baseline, documented here (spec §7.3: if
boundary defects appear, derive a new profile with more context/overlap
and re-run before release).

    # single mode (short input)
    analysis/.venv/bin/python analysis/compare_adapter.py \
        --adapter staged/attempt-1 --reference ref-staged \
        --report compare-report.json

    # windows mode (multi-window run)
    analysis/.venv/bin/python analysis/compare_adapter.py \
        --adapter staged/attempt-1 --refs ref-w0 ref-w1 ref-w2 ref-w3 ref-w4 \
        --window-seconds 120 --overlap-seconds 8 --report compare-report.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

SCALE_LO, SCALE_HI = 0.9, 1.1
MAX_LAG_SAMPLES = 1
NUMERICAL_REL_MAX = 0.05
BOUNDARY_RATIO_MAX = 3.0
CONTINUITY_LO, CONTINUITY_HI = 0.8, 1.25
IDENTITY_MAX_DIFF = 1e-6
BLEND_MAX_DIFF = 1e-6

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWING_PATH = REPO_ROOT / "src" / "basseparate" / "media" / "windowing.py"


def _load_windowing():
    spec = importlib.util.spec_from_file_location("basseparate_media_windowing", WINDOWING_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {WINDOWING_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windowing = _load_windowing()


def load_stems(out_dir: Path) -> dict[str, np.ndarray]:
    """Load stem PCM files as ``(frames, 2)`` arrays.

    Stem files follow the prepared-input PCM convention: interleaved
    float32 little-endian, ``(frames, channels)``.
    """
    stems = {}
    for path in sorted(out_dir.glob("*.pcm")):
        stems[path.stem] = np.fromfile(path, dtype="<f4").reshape(-1, 2)
    return stems


def head_lag(a: np.ndarray, b: np.ndarray, rate: int) -> int:
    """Lag (samples) of b relative to a, from a 2 s head cross-correlation."""
    n = min(len(a), len(b), 2 * rate)
    a_head = a[:n, 0].astype(np.float64)
    b_head = b[: n + 2 * MAX_LAG_SAMPLES, 0].astype(np.float64)
    best_lag, best_score = 0, -1.0
    for lag in range(-MAX_LAG_SAMPLES, MAX_LAG_SAMPLES + 1):
        if lag >= 0:
            score = float(np.dot(a_head[lag:], b_head[lag : lag + n - lag]))
        else:
            score = float(np.dot(a_head[:lag], b_head[-lag : -lag + n + lag]))
        score /= np.linalg.norm(a_head) * np.linalg.norm(b_head) + 1e-30
        if score > best_score:
            best_lag, best_score = lag, score
    return best_lag


def single_mode(adapter: dict[str, np.ndarray], reference: dict[str, np.ndarray], rate: int) -> dict:
    checks: dict = {}
    report_pass = True

    labels_ok = list(adapter) == list(reference)
    checks["labels"] = {"pass": labels_ok, "adapter": list(adapter), "reference": list(reference)}
    if not labels_ok:
        report_pass = False

    per_stem = {}
    for label, a in adapter.items():
        b = reference.get(label)
        entry: dict = {"label": label}
        if b is None or a.shape != b.shape:
            entry.update(
                {
                    "pass": False,
                    "error": "shape mismatch",
                    "adapter": list(a.shape),
                    "reference": None if b is None else list(b.shape),
                }
            )
            per_stem[label] = entry
            report_pass = False
            continue
        a_rms = float(np.sqrt((a.astype(np.float64) ** 2).mean()))
        b_rms = float(np.sqrt((b.astype(np.float64) ** 2).mean()))
        scale_ratio = a_rms / b_rms if b_rms > 0 else float("inf")
        diff = a.astype(np.float64) - b.astype(np.float64)
        max_abs = float(np.abs(diff).max()) if diff.size else 0.0
        lag = head_lag(a, b, rate)
        scale_ok = SCALE_LO <= scale_ratio <= SCALE_HI
        lag_ok = abs(lag) <= MAX_LAG_SAMPLES
        numerical_ok = max_abs < NUMERICAL_REL_MAX * b_rms
        entry.update(
            {
                "pass": scale_ok and lag_ok and numerical_ok,
                "frames": a.shape[0],
                "scale_ratio": round(scale_ratio, 6),
                "alignment_lag_samples": lag,
                "max_abs_diff": max_abs,
                "reference_rms": b_rms,
            }
        )
        if not entry["pass"]:
            report_pass = False
        per_stem[label] = entry
    checks["stems"] = per_stem
    checks["_pass"] = report_pass
    return checks


def windows_mode(
    adapter: dict[str, np.ndarray],
    ref_dirs: list[Path],
    window_seconds: float,
    overlap_seconds: float,
    rate: int,
) -> dict:
    checks: dict = {}
    report_pass = True

    frames = next(iter(adapter.values())).shape[0]
    window_frames = int(window_seconds * rate)
    overlap_frames = int(overlap_seconds * rate)
    schedule = windowing.window_schedule(frames, window_frames, overlap_frames)
    if len(schedule) != len(ref_dirs):
        checks["schedule"] = {
            "pass": False,
            "error": f"{len(schedule)} windows but {len(ref_dirs)} reference dirs",
        }
        checks["_pass"] = False
        return checks

    refs = [load_stems(d) for d in ref_dirs]
    labels_ok = all(list(r) == list(adapter) for r in refs)
    checks["labels"] = {"pass": labels_ok, "adapter": list(adapter)}
    if not labels_ok:
        report_pass = False

    stride = window_frames - overlap_frames
    identity_max = 0.0
    blend_max = 0.0
    boundaries = []
    diff2 = np.zeros(frames)  # per-frame diff energy vs the per-window baseline
    label = "bass" if "bass" in adapter else next(iter(adapter))

    for idx, (off, length) in enumerate(schedule):
        ref = refs[idx]
        is_first = idx == 0
        is_last = idx == len(schedule) - 1
        # Identity region of this window in the final track.
        ident_start = off + (0 if is_first else overlap_frames)
        ident_end = off + length - (0 if is_last else overlap_frames)
        if ident_end > ident_start:
            for stem, a in adapter.items():
                b = ref[stem]
                seg_a = a[ident_start:ident_end].astype(np.float64)
                seg_b = b[ident_start - off : ident_end - off].astype(np.float64)
                identity_max = max(identity_max, float(np.abs(seg_a - seg_b).max()))
                if idx == 0:
                    diff2[ident_start:ident_end] = ((seg_a - seg_b) ** 2).sum(axis=1)
        # Blend region: leading overlap band of non-first windows.
        if not is_first:
            band = overlap_frames
            boundaries.append(off)
            w_prev = windowing.outer_window_weight(
                schedule[idx - 1][1], overlap_frames, is_first=False, is_last=False
            )[-band:]
            w_cur = windowing.outer_window_weight(
                length, overlap_frames, is_first=False, is_last=is_last
            )[:band]
            prev_ref = refs[idx - 1]
            acc_w = w_prev.astype(np.float64) + w_cur.astype(np.float64)
            for stem, a in adapter.items():
                cur = a[off : off + band].astype(np.float64)
                c_ref = ref[stem][:band].astype(np.float64)
                p_ref = prev_ref[stem][schedule[idx - 1][1] - band :].astype(np.float64)
                # The exact weighted combination the adapter must produce
                # (float64 accumulate + divide, spec §7.2.7).
                expected = (
                    w_prev[:, None] * p_ref + w_cur[:, None] * c_ref
                ) / acc_w[:, None]
                blend_max = max(blend_max, float(np.abs(cur - expected).max()))
                diff2[off : off + band] = np.maximum(
                    diff2[off : off + band], ((cur - expected) ** 2).sum(axis=1)
                )

    checks["identity"] = {
        "pass": identity_max < IDENTITY_MAX_DIFF,
        "max_abs_diff": identity_max,
    }
    checks["blend"] = {"pass": blend_max < BLEND_MAX_DIFF, "max_abs_diff": blend_max}
    if not (checks["identity"]["pass"] and checks["blend"]["pass"]):
        report_pass = False

    # Scale / alignment vs the first window's reference (interior region).
    if schedule:
        off0, len0 = schedule[0]
        i0_start = off0
        i0_end = off0 + len0 - (0 if len(schedule) == 1 else overlap_frames)
        per_stem = {}
        for stem, a in adapter.items():
            b = refs[0][stem]
            a_rms = float(np.sqrt((a[i0_start:i0_end].astype(np.float64) ** 2).mean()))
            b_rms = float(np.sqrt((b[: i0_end - off0].astype(np.float64) ** 2).mean()))
            scale_ratio = a_rms / b_rms if b_rms > 0 else float("inf")
            lag = head_lag(a[i0_start:i0_end], b[: i0_end - off0], rate)
            ok = SCALE_LO <= scale_ratio <= SCALE_HI and abs(lag) <= MAX_LAG_SAMPLES
            per_stem[stem] = {
                "pass": ok,
                "scale_ratio": round(scale_ratio, 6),
                "alignment_lag_samples": lag,
            }
            if not ok:
                report_pass = False
        checks["stems"] = per_stem

    # Boundary artifacts: blend-band diff energy vs the interior,
    # per sample. The interior floor is the identity tolerance: a run
    # that is bit-exact outside the bands (interior energy exactly 0)
    # must not divide by zero, and a boundary band whose per-sample
    # error is below the numerical tolerance is not a boundary defect.
    if boundaries:
        band = overlap_frames
        mask = np.zeros(frames, dtype=bool)
        for off in boundaries:
            mask[off : off + band] = True
        channels = next(iter(adapter.values())).shape[1]
        boundary_mse = float(diff2[mask].sum()) / max(int(mask.sum()) * channels, 1)
        interior_mse = float(diff2[~mask].sum()) / max(int((~mask).sum()) * channels, 1)
        ratio = boundary_mse / max(interior_mse, IDENTITY_MAX_DIFF**2)
        checks["boundary_artifacts"] = {
            "pass": ratio < BOUNDARY_RATIO_MAX,
            "boundaries_samples": boundaries,
            "per_sample_ratio": ratio,
        }
        if not checks["boundary_artifacts"]["pass"]:
            report_pass = False
    else:
        checks["boundary_artifacts"] = {"pass": True, "skipped": "single-window run"}

    # Bass continuity around the boundaries (1 s before/after, per the
    # gate baseline above — 8 s bands would track the test content's
    # 20 s AM envelope, not the boundary).
    if boundaries and label in adapter:
        a = adapter[label].astype(np.float64)
        cont_band = rate
        ratios = []
        for off in boundaries:
            before = float(np.sqrt((a[off - cont_band : off, :] ** 2).mean()))
            after = float(np.sqrt((a[off : off + cont_band, :] ** 2).mean()))
            ratios.append(after / before if before > 0 else float("inf"))
        cont_ok = all(CONTINUITY_LO <= r <= CONTINUITY_HI for r in ratios)
        checks["bass_continuity"] = {
            "pass": cont_ok,
            "ratios": [round(r, 4) for r in ratios],
        }
        if not cont_ok:
            report_pass = False
    else:
        checks["bass_continuity"] = {"pass": True, "skipped": "no boundaries"}

    checks["_pass"] = report_pass
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Adapter-vs-reference comparison gate")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=None, help="whole-track reference (single mode)")
    parser.add_argument("--refs", nargs="+", type=Path, default=None, help="per-window reference dirs (windows mode)")
    parser.add_argument("--window-seconds", type=float, default=120.0)
    parser.add_argument("--overlap-seconds", type=float, default=8.0)
    parser.add_argument("--rate", type=int, default=44100)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if (args.reference is None) == (args.refs is None):
        print("exactly one of --reference (single) or --refs (windows) is required", file=sys.stderr)
        return 1

    adapter = load_stems(args.adapter)
    if args.reference is not None:
        reference = load_stems(args.reference)
        checks = single_mode(adapter, reference, args.rate)
    else:
        checks = windows_mode(adapter, args.refs, args.window_seconds, args.overlap_seconds, args.rate)

    report_pass = checks.pop("_pass")
    report = {"mode": "single" if args.reference is not None else "windows", "pass": report_pass, "checks": checks}
    if args.report is not None:
        args.report.write_text(json.dumps(report, indent=2))
    summary = {}
    for key, value in checks.items():
        if key == "stems":
            summary[key] = {stem: entry.get("pass") for stem, entry in value.items()}
        else:
            summary[key] = value.get("pass")
    print(json.dumps({"pass": report_pass, "checks": summary}))
    return 0 if report_pass else 1


if __name__ == "__main__":
    sys.exit(main())
