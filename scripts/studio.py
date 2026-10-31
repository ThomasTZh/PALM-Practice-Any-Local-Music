#!/usr/bin/env python3
"""Offline development harness for the basseparate practice studio.

One entry point for the whole local loop: doctor, bootstrap, fixtures, gate,
dev, build, test, e2e, fix and demo. Standard library only, no network access,
no downloads. Make targets are thin wrappers around these subcommands.

Design rules:
* One decision lives in one place: paths, fixture definitions and the web
  dependency versions are defined once here or in the manifests it reads.
* Idempotent: running a command twice ends in the same state and reports
  skipped work instead of redoing it.
* Empty is not failure: the skeleton has no application tests yet, so gate
  explicitly reports SKIP for an empty test set and fails only on real errors.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "basseparate"
WEB = ROOT / "web"
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"
AUDIO = FIXTURES / "audio"
MANIFEST = FIXTURES / "manifest.json"
SUMS = FIXTURES / "SHA256SUMS"

PY = ROOT / ".venv" / "bin" / "python"
ANALYSIS_PY = ROOT / "analysis" / ".venv" / "bin" / "python"
PNPM_STORE = ROOT / "node_modules" / ".pnpm"
WEB_MODULES = WEB / "node_modules"

MODEL_DIR = ROOT / "models" / "htdemucs_ft"
TOOLS = ROOT / "storage" / "tools"
PIPER = TOOLS / "sv" / "squashfs-root" / "usr" / "bin" / "piper-vamp-simple-server"
NATIVE_HOST = TOOLS / "vamp-host"
PLUGIN_PACK = TOOLS / "vamp-plugins"
RECORDINGS = ROOT / "audio2test"

# Python packages the harness itself depends on; used to decide whether the
# preserved virtual environment is usable.
APP_IMPORTS = "fastapi,uvicorn,pydantic,numpy,pytest"


# ---------------------------------------------------------------------------
# process helpers


def python_bin() -> str:
    """The project interpreter when present, otherwise the running one."""
    return str(PY) if PY.exists() else sys.executable


def run(
    cmd: list[object],
    *,
    cwd: Path = ROOT,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command offline and capture its output."""
    return subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd),
        timeout=timeout,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0] if lines else ""


def tail(text: str, limit: int = 4000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "...\n" + text[-limit:]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# fixtures
#
# Deterministic synthesis: fixed note lists, fixed envelopes, no randomness and
# no timestamps in the WAV headers, so a rerun produces identical bytes.

SAMPLE_RATE = 44_100


def _sine(phase_hz: float, index: int, rate: int) -> float:
    return math.sin(2.0 * math.pi * phase_hz * (index / rate))


def _envelope(position: int, total: int, rate: int, attack: float, release: float) -> float:
    """Linear attack/release envelope in seconds over a finite region."""
    attack_frames = int(attack * rate)
    release_frames = int(release * rate)
    if position < attack_frames and attack_frames > 0:
        return position / attack_frames
    if position >= total - release_frames and release_frames > 0:
        return max(0.0, (total - position - 1) / release_frames)
    return 1.0


def _to_pcm(samples: list[float]) -> array:
    pcm = array("h")
    for value in samples:
        clipped = max(-1.0, min(1.0, value))
        pcm.append(int(round(clipped * 32767.0)))
    return pcm


def _wav_bytes(rate: int, channels: int, samples: array) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def synth_click(
    bpm: float, bars: int, meter: int = 4, rate: int = SAMPLE_RATE
) -> tuple[bytes, dict]:
    """Metronome click track with accents on every bar start."""
    beat_seconds = 60.0 / bpm
    beats = bars * meter
    total = int(round(beats * beat_seconds * rate))
    samples = [0.0] * total
    click_frames = int(0.04 * rate)
    accent_beats = list(range(0, beats, meter))
    for beat in range(beats):
        start = int(round(beat * beat_seconds * rate))
        amplitude = 0.8 if beat in accent_beats else 0.45
        for offset in range(min(click_frames, total - start)):
            decay = math.exp(-6.0 * offset / click_frames)
            samples[start + offset] += amplitude * decay * _sine(1000.0, offset, rate)
    meta = {
        "kind": "click",
        "bpm": bpm,
        "meter": f"{meter}/4",
        "bars": bars,
        "beats": beats,
        "accent_beats": [beat + 1 for beat in accent_beats],
        "seconds": round(total / rate, 6),
    }
    return _wav_bytes(rate, 1, _to_pcm(samples)), meta


CHORD_PROGRESSION: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("C:maj", (261.63, 329.63, 392.00)),
    ("A:min", (220.00, 261.63, 329.63)),
    ("F:maj", (174.61, 220.00, 261.63)),
    ("G:maj", (196.00, 246.94, 293.66)),
)


def synth_chords(
    chord_seconds: float = 2.0,
    rate: int = SAMPLE_RATE,
) -> tuple[bytes, dict]:
    """C-Am-F-G triads, one chord per 4/4 bar at 120 BPM."""
    per_chord = int(round(chord_seconds * rate))
    samples = [0.0] * (per_chord * len(CHORD_PROGRESSION))
    for chord_index, (_, frequencies) in enumerate(CHORD_PROGRESSION):
        start = chord_index * per_chord
        for offset in range(per_chord):
            gain = 0.2 * _envelope(offset, per_chord, rate, 0.02, 0.05)
            value = sum(_sine(freq, offset, rate) for freq in frequencies) / len(frequencies)
            samples[start + offset] = gain * value
    meta = {
        "kind": "chords",
        "bpm": 120.0,
        "meter": "4/4",
        "key": "C major",
        "chords": [name for name, _ in CHORD_PROGRESSION],
        "chord_seconds": chord_seconds,
        "seconds": round(len(samples) / rate, 6),
    }
    return _wav_bytes(rate, 1, _to_pcm(samples)), meta


def synth_tone(
    frequency_hz: float = 440.0,
    seconds: float = 2.0,
    rate: int = SAMPLE_RATE,
    channels: int = 1,
) -> tuple[bytes, dict]:
    """Pure sine tone; used for pitch and rate checks."""
    total = int(round(seconds * rate))
    samples = [0.5 * _sine(frequency_hz, index, rate) for index in range(total)]
    pcm = array("h")
    for value in _to_pcm(samples):
        for _ in range(channels):
            pcm.append(value)
    meta = {
        "kind": "tone",
        "frequency_hz": frequency_hz,
        "seconds": round(total / rate, 6),
        "channels": channels,
    }
    return _wav_bytes(rate, channels, pcm), meta


def synth_silence(seconds: float = 1.0, rate: int = SAMPLE_RATE) -> tuple[bytes, dict]:
    total = int(round(seconds * rate))
    meta = {"kind": "silence", "seconds": round(total / rate, 6)}
    return _wav_bytes(rate, 1, _to_pcm([0.0] * total)), meta


FIXTURE_BUILDERS: tuple[tuple[str, object], ...] = (
    ("audio/click_120bpm.wav", lambda: synth_click(bpm=120.0, bars=2)),
    ("audio/chords_c_am_f_g.wav", synth_chords),
    ("audio/tone_440hz.wav", synth_tone),
    ("audio/silence.wav", synth_silence),
    (
        "audio/tone_48k_stereo.wav",
        lambda: synth_tone(frequency_hz=440.0, seconds=1.0, rate=48_000, channels=2),
    ),
)


def build_fixtures() -> tuple[dict[str, bytes], dict]:
    """Return fixture bytes plus a manifest describing their musical content."""
    files: dict[str, bytes] = {}
    entries: list[dict] = []
    for name, builder in FIXTURE_BUILDERS:
        data, meta = builder()  # type: ignore[operator]
        files[name] = data
        display = Path(name).name
        with wave.open(io.BytesIO(data), "rb") as handle:
            meta = {
                "file": name,
                "sample_rate": handle.getframerate(),
                "channels": handle.getnchannels(),
                "frames": handle.getnframes(),
                **meta,
            }
        entries.append({"name": display, **meta})
    manifest = {
        "version": 1,
        "description": "Deterministic audio fixtures synthesised by scripts/studio.py fixtures.",
        "fixtures": entries,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return files, manifest


def checksums(files: dict[str, bytes]) -> bytes:
    lines = [f"{hashlib.sha256(data).hexdigest()}  {name}" for name, data in sorted(files.items())]
    return ("\n".join(lines) + "\n").encode()


def write_fixtures() -> int:
    files, manifest = build_fixtures()
    AUDIO.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = FIXTURES / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"  wrote {rel(target)} ({len(data)} bytes)")
    SUMS.write_bytes(checksums(files))
    print(f"  wrote {rel(SUMS)} ({len(manifest['fixtures'])} fixtures)")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def check_fixtures() -> tuple[bool, str]:
    """Regenerate in memory and compare bytes; proves determinism cheaply."""
    files, _ = build_fixtures()
    problems: list[str] = []
    for name, data in files.items():
        target = FIXTURES / name
        if not target.is_file():
            problems.append(f"missing {rel(target)}")
        elif target.read_bytes() != data:
            problems.append(f"content differs from the generator: {rel(target)}")
    expected_sums = checksums(files)
    if not SUMS.is_file() or SUMS.read_bytes() != expected_sums:
        problems.append(f"{rel(SUMS)} does not match the generated fixtures")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(files) - 1} fixtures match the generator byte for byte"


# ---------------------------------------------------------------------------
# doctor


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass
class DoctorReport:
    sections: list[tuple[str, list[Check]]] = field(default_factory=list)

    def add(self, title: str, check: Check) -> None:
        for existing_title, checks in self.sections:
            if existing_title == title:
                checks.append(check)
                return
        self.sections.append((title, [check]))

    @property
    def failures(self) -> list[Check]:
        return [
            check
            for _, checks in self.sections
            for check in checks
            if check.required and not check.ok
        ]


TOOL_VERSION_ARGS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
}


def tool_check(name: str, cwd: Path = ROOT) -> Check:
    path = shutil.which(name)
    if path is None:
        return Check(name, False, "not on PATH", required=True)
    version_args = TOOL_VERSION_ARGS.get(name, ("--version",))
    result = run([path, *version_args], cwd=cwd, timeout=20)
    if result.returncode != 0:
        return Check(name, False, f"{path} (version probe failed)", required=True)
    first = (result.stdout or result.stderr).strip().splitlines()
    return Check(name, True, first[0] if first else path, required=True)


def path_check(name: str, path: Path, required: bool = False) -> Check:
    if not path.exists():
        return Check(name, False, f"missing {rel(path)}", required=required)
    if path.is_dir():
        count = sum(1 for _ in path.iterdir())
        return Check(name, True, f"{rel(path)} ({count} entries)", required=required)
    size = path.stat().st_size
    executable = " executable" if os.access(path, os.X_OK) else ""
    return Check(name, True, f"{rel(path)} ({size} bytes{executable})", required=required)


def doctor() -> int:
    report = DoctorReport()
    for name in ("make", "git", "ffmpeg", "ffprobe", "node"):
        report.add("Toolchain", tool_check(name))
    report.add("Toolchain", tool_check("uv"))
    # pnpm 12 rewrites a lockfile for the `packageManager` pin on any
    # invocation, so probe it outside the repository to keep doctor read-only.
    with tempfile.TemporaryDirectory(prefix="basseparate-doctor-") as scratch:
        report.add("Toolchain", tool_check("pnpm", Path(scratch)))

    if PY.exists():
        probe = run([PY, "-c", f"import {APP_IMPORTS}; print('python deps ok')"], timeout=60)
        ok = probe.returncode == 0
        report.add("Python environment", Check(".venv", True, rel(PY), required=True))
        report.add(
            "Python environment",
            Check("app imports", ok, (probe.stdout or probe.stderr).strip(), required=True),
        )
    else:
        report.add(
            "Python environment",
            Check(
                ".venv",
                False,
                f"missing {rel(PY)} (offline bootstrap cannot recreate it)",
                required=True,
            ),
        )

    if ANALYSIS_PY.exists():
        probe = run(
            [
                ANALYSIS_PY,
                "-c",
                "import torch, demucs; print(torch.__version__, demucs.__version__)",
            ],
            timeout=120,
        )
        report.add(
            "Analysis environment", Check("analysis/.venv", True, rel(ANALYSIS_PY), required=False)
        )
        report.add(
            "Analysis environment",
            Check(
                "torch + demucs",
                probe.returncode == 0,
                (probe.stdout or probe.stderr).strip(),
                required=False,
            ),
        )
    else:
        report.add(
            "Analysis environment",
            Check("analysis/.venv", False, f"missing {rel(ANALYSIS_PY)}", required=False),
        )

    missing_links = missing_web_links()
    report.add(
        "Web environment",
        Check(
            "web/node_modules",
            not missing_links,
            "all direct dependencies linked"
            if not missing_links
            else f"missing {', '.join(missing_links)}",
            required=False,
        ),
    )
    for tool in ("vite", "vitest", "tsc", "playwright"):
        binary = WEB_MODULES / ".bin" / tool
        report.add("Web environment", Check(tool, binary.exists(), rel(binary), required=False))

    report.add("Assets", path_check("model bundle", MODEL_DIR))
    report.add("Assets", path_check("third_party/emsdk", ROOT / "third_party" / "emsdk"))
    report.add(
        "Assets", path_check("signalsmith-stretch", ROOT / "third_party" / "signalsmith-stretch")
    )
    report.add("Assets", path_check("Vamp SDK", TOOLS / "vamp-sdk"))
    report.add("Assets", path_check("Vamp plugins", PLUGIN_PACK))
    report.add("Assets", path_check("native Vamp host", NATIVE_HOST))
    report.add("Assets", path_check("Piper server", PIPER))
    report.add("Assets", path_check("recordings", RECORDINGS))

    checkpoints = sorted(MODEL_DIR.glob("*.th")) if MODEL_DIR.is_dir() else []
    report.add(
        "Model bundle",
        Check(
            "htdemucs_ft checkpoints",
            len(checkpoints) == 4,
            f"{len(checkpoints)} .th files"
            + (f" in {rel(MODEL_DIR)}" if MODEL_DIR.exists() else ""),
            required=False,
        ),
    )
    report.add(
        "Model bundle",
        Check(
            "htdemucs_ft preset",
            (MODEL_DIR / "htdemucs_ft.yaml").is_file(),
            rel(MODEL_DIR / "htdemucs_ft.yaml"),
            required=False,
        ),
    )

    gpu_name = "unavailable"
    smi = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=20)
    if smi.returncode == 0 and smi.stdout.strip():
        gpu_name = smi.stdout.strip().splitlines()[0]
    report.add("GPU", Check("nvidia-smi", smi.returncode == 0, gpu_name, required=False))
    if ANALYSIS_PY.exists():
        cuda = run(
            [ANALYSIS_PY, "-c", "import torch; print('cuda', torch.cuda.is_available())"],
            timeout=120,
        )
        detail = (cuda.stdout or cuda.stderr).strip().splitlines()
        report.add(
            "GPU",
            Check(
                "torch cuda",
                cuda.returncode == 0 and "cuda True" in (cuda.stdout or ""),
                detail[-1] if detail else "torch probe failed",
                required=False,
            ),
        )
    else:
        report.add("GPU", Check("torch cuda", False, "analysis/.venv missing", required=False))

    for title, checks in report.sections:
        print(title)
        for check in checks:
            flag = "ok     " if check.ok else ("MISSING" if check.required else "missing")
            print(f"  [{flag}] {check.name:24} {check.detail}")
        print()
    failures = report.failures
    if failures:
        names = ", ".join(check.name for check in failures)
        print(f"doctor: {len(failures)} required item(s) missing: {names}")
        return 1
    print("doctor: required toolchain and environment present; no network access was used")
    return 0


# ---------------------------------------------------------------------------
# web dependency linking
#
# `pnpm install` is unavailable offline in this environment (the sandbox makes
# the package manager's store unusable), while the pnpm virtual store is
# preserved in node_modules/.pnpm. Bootstrap therefore links web/node_modules
# from that store using the exact versions pinned in web/package.json. No
# network, no re-download, and the result is a normal pnpm-shaped tree.


def web_package_json() -> dict:
    return json.loads((WEB / "package.json").read_text())


def web_dependencies() -> dict[str, str]:
    manifest = web_package_json()
    deps: dict[str, str] = {}
    deps.update(manifest.get("dependencies", {}))
    deps.update(manifest.get("devDependencies", {}))
    return deps


def pnpm_package_dir(name: str, version: str) -> Path | None:
    encoded = name.replace("/", "+")
    prefix = f"{encoded}@{version}"
    exact = PNPM_STORE / prefix / "node_modules" / name
    if exact.is_dir():
        return exact
    matches = sorted(PNPM_STORE.glob(f"{prefix}_*"))
    for match in matches:
        candidate = match / "node_modules" / name
        if candidate.is_dir():
            return candidate
    return None


def missing_web_links() -> list[str]:
    if not (WEB_MODULES / ".basseparate-links.json").is_file():
        return list(web_dependencies())
    try:
        state = json.loads((WEB_MODULES / ".basseparate-links.json").read_text())
    except json.JSONDecodeError:
        return list(web_dependencies())
    missing = []
    for name, version in web_dependencies().items():
        link = WEB_MODULES / name
        if not link.exists() or state.get("dependencies", {}).get(name) != version:
            missing.append(f"{name}@{version}")
    return missing


def link_web_modules(force: bool = False) -> str:
    deps = web_dependencies()
    if not PNPM_STORE.is_dir():
        msg = (
            f"{rel(PNPM_STORE)} is missing: the preserved pnpm virtual store is required "
            "for the offline web environment"
        )
        raise SystemExit(msg)
    if not force and not missing_web_links():
        return f"web/node_modules already linked ({len(deps)} direct dependencies)"

    if WEB_MODULES.exists():
        shutil.rmtree(WEB_MODULES)
    WEB_MODULES.mkdir(parents=True)
    linked: dict[str, str] = {}
    unresolved: list[str] = []
    for name, version in sorted(deps.items()):
        target = pnpm_package_dir(name, version)
        if target is None:
            unresolved.append(f"{name}@{version}")
            continue
        link = WEB_MODULES / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(target, link.parent))
        linked[name] = version
        bins = json.loads((target / "package.json").read_text()).get("bin")
        if isinstance(bins, str):
            bins = {name.split("/")[-1]: bins}
        for bin_name, rel_path in (bins or {}).items():
            bin_link = WEB_MODULES / ".bin" / bin_name
            bin_link.parent.mkdir(parents=True, exist_ok=True)
            bin_link.unlink(missing_ok=True)
            bin_link.symlink_to(os.path.relpath(target / rel_path, bin_link.parent))
            bin_link.chmod(0o755)
    if unresolved:
        raise SystemExit(
            "cannot link offline web dependencies, missing from "
            f"{rel(PNPM_STORE)}: {', '.join(unresolved)}"
        )
    state = {"dependencies": linked}
    (WEB_MODULES / ".basseparate-links.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n"
    )
    return f"linked {len(linked)} direct dependencies from {rel(PNPM_STORE)}"


# ---------------------------------------------------------------------------
# bootstrap


def bootstrap() -> int:
    steps: list[tuple[str, str, str]] = []
    started = time.time()

    if PY.exists():
        probe = run([PY, "-c", f"import {APP_IMPORTS}"], timeout=60)
        if probe.returncode == 0:
            steps.append(
                ("python", "skip", f"{rel(PY)} already satisfies the app and dev dependencies")
            )
        else:
            repaired = repair_python()
            steps.append(
                (
                    "python",
                    "done" if repaired else "fail",
                    "reinstalled offline"
                    if repaired
                    else (probe.stderr.strip() or "python environment is not usable"),
                )
            )
    else:
        repaired = repair_python()
        steps.append(
            (
                "python",
                "done" if repaired else "fail",
                "created .venv offline"
                if repaired
                else "no .venv and no cached wheels for offline repair",
            )
        )

    try:
        message = link_web_modules()
        steps.append(
            ("web", "skip" if message.startswith("web/node_modules already") else "done", message)
        )
    except SystemExit as error:
        steps.append(("web", "fail", str(error)))

    ok, detail = check_fixtures()
    if ok:
        steps.append(("fixtures", "skip", detail))
    else:
        code = write_fixtures()
        ok_after, detail_after = check_fixtures()
        steps.append(("fixtures", "done" if code == 0 and ok_after else "fail", detail_after))

    elapsed = time.time() - started
    print("bootstrap (offline)")
    for name, status, message in steps:
        print(f"  [{status:4}] {name:8} {message}")
    failed = [name for name, status, _ in steps if status == "fail"]
    if failed:
        print(f"bootstrap: failed steps: {', '.join(failed)}")
        return 1
    skipped = sum(1 for _, status, _ in steps if status == "skip")
    summary = f"bootstrap: ok in {elapsed:.1f}s ({skipped} step(s) skipped)"
    print(f"{summary}; no network used")
    return 0


def repair_python() -> bool:
    """Best-effort offline provision of the app virtual environment."""
    uv = shutil.which("uv")
    if uv is None:
        return False
    if not PY.exists():
        result = run([uv, "venv", "--python", "3.11", str(ROOT / ".venv")], timeout=180)
        if result.returncode != 0:
            return False
    result = run([uv, "sync", "--offline", "--no-dev"], timeout=900)
    if result.returncode != 0:
        return False
    probe = run([PY, "-c", f"import {APP_IMPORTS}"], timeout=60)
    return probe.returncode == 0


# ---------------------------------------------------------------------------
# gate


@dataclass
class GateResult:
    status: str  # pass | skip | fail
    detail: str = ""


def gate_ruff() -> GateResult:
    targets = [path for path in (SRC, ROOT / "scripts", TESTS) if path.exists()]
    result = run([python_bin(), "-m", "ruff", "check", *targets], timeout=180)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", f"ruff check {len(targets)} path(s)")


def gate_format() -> GateResult:
    targets = [path for path in (SRC, ROOT / "scripts", TESTS) if path.exists()]
    result = run([python_bin(), "-m", "ruff", "format", "--check", *targets], timeout=180)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", "ruff format --check")


def gate_mypy() -> GateResult:
    if not (PACKAGE / "__init__.py").exists():
        return GateResult("skip", "no src/basseparate/__init__.py")
    result = run([python_bin(), "-m", "mypy", str(PACKAGE)], timeout=600)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", "mypy strict")


def pytest_target() -> Path | None:
    for directory in TESTS.glob("**/test_*.py"):
        if "__pycache__" not in directory.parts:
            return TESTS
    return None


def gate_pytest(lite: bool = False) -> GateResult:
    target = pytest_target()
    if target is None:
        return GateResult("skip", "no tests yet (empty skeleton)")
    args = [python_bin(), "-m", "pytest", "-q"]
    if lite:
        args += ["-m", "not integration and not browser", "-x"]
    result = run(args, timeout=900)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    summary = (result.stdout.strip().splitlines() or ["tests passed"])[-1]
    return GateResult("pass", summary)


def web_sources_exist() -> bool:
    if not (WEB / "src").is_dir():
        return False
    return any((WEB / "src").glob("**/*.ts")) or any((WEB / "src").glob("**/*.tsx"))


def gate_web_typecheck() -> GateResult:
    tsc = WEB_MODULES / ".bin" / "tsc"
    if not web_sources_exist():
        return GateResult("skip", "web/src is empty (UI tasks not landed yet)")
    if not tsc.exists():
        return GateResult("fail", "web/node_modules is not linked; run make bootstrap")
    result = run([tsc, "--noEmit", "-p", "tsconfig.json"], cwd=WEB, timeout=600)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", "tsc --noEmit")


def gate_web_tests() -> GateResult:
    vitest = WEB_MODULES / ".bin" / "vitest"
    if not vitest.exists():
        return GateResult("fail", "web/node_modules is not linked; run make bootstrap")
    result = run([vitest, "run", "--passWithNoTests"], cwd=WEB, timeout=900)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    output = result.stdout.strip().splitlines()
    summary = output[-1] if output else "vitest: no test files yet"
    return GateResult("pass", summary)


def gate_web_build() -> GateResult:
    vite = WEB_MODULES / ".bin" / "vite"
    if not web_sources_exist():
        return GateResult("skip", "web/src is empty (UI tasks not landed yet)")
    if not vite.exists():
        return GateResult("fail", "web/node_modules is not linked; run make bootstrap")
    result = run([vite, "build"], cwd=WEB, timeout=900)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", "vite build")


def e2e_specs() -> list[Path]:
    directory = WEB / "e2e"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.spec.ts"))


def e2e_config() -> Path | None:
    """Config owned by the e2e task, at the package root or inside web/e2e."""
    for candidate in (WEB / "playwright.config.ts", WEB / "e2e" / "playwright.config.ts"):
        if candidate.is_file():
            return candidate
    return None


def gate_e2e() -> GateResult:
    specs = e2e_specs()
    if not specs:
        return GateResult("skip", "no web/e2e specs yet")
    playwright = WEB_MODULES / ".bin" / "playwright"
    if not playwright.exists():
        return GateResult("fail", "web/node_modules is not linked; run make bootstrap")
    config = e2e_config()
    if config is not None:
        args = [playwright, "test", "--config", str(config.relative_to(WEB))]
    else:
        # No config yet: run the specs in web/e2e on the installed browser.
        args = [playwright, "test", "e2e", "--browser", "firefox"]
    result = run(args, cwd=WEB, timeout=1800)
    if result.returncode != 0:
        return GateResult("fail", tail(result.stdout + result.stderr))
    return GateResult("pass", f"{len(specs)} spec file(s)")


def gate_fixtures() -> GateResult:
    ok, detail = check_fixtures()
    return GateResult("pass" if ok else "fail", detail)


def run_gate(steps: list[tuple[str, object]], title: str) -> int:
    print(f"{title} (offline)")
    failures = 0
    for name, step in steps:
        started = time.time()
        result = step()  # type: ignore[operator]
        elapsed = time.time() - started
        summary = first_line(result.detail)
        print(f"  [{result.status.upper():4}] {name:14} {summary} ({elapsed:.1f}s)")
        if result.status == "fail":
            failures += 1
            print()
            print(result.detail)
            print()
    if failures:
        print(f"{title}: {failures} step(s) failed")
        return 1
    print(f"{title}: ok")
    return 0


def gate(lite: bool = False) -> int:
    steps: list[tuple[str, object]] = [
        ("ruff check", gate_ruff),
        ("ruff format", gate_format),
        ("fixtures", gate_fixtures),
        ("mypy", gate_mypy),
        ("pytest", lambda: gate_pytest(lite)),
    ]
    if not lite:
        steps += [
            ("web typecheck", gate_web_typecheck),
            ("web tests", gate_web_tests),
            ("web build", gate_web_build),
            ("e2e", gate_e2e),
        ]
    else:
        steps += [("web tests", gate_web_tests)]
    return run_gate(steps, "gate-lite" if lite else "gate")


# ---------------------------------------------------------------------------
# dev / build / test / e2e / fix / demo


def server_ready() -> bool:
    if not (PACKAGE / "cli.py").exists():
        return False
    probe = run(
        [python_bin(), "-c", "import basseparate.cli"],
        env={**os.environ, "PYTHONPATH": str(SRC)},
        timeout=60,
    )
    return probe.returncode == 0


def web_ready() -> bool:
    return (WEB / "src" / "main.tsx").exists()


def dev() -> int:
    ensure_fixtures()
    parts: list[tuple[str, list[str], Path, dict[str, str]]] = []
    if web_ready():
        vite = WEB_MODULES / ".bin" / "vite"
        if not vite.exists():
            print("dev: web/node_modules missing; run make bootstrap")
            return 1
        parts.append(("vite", [str(vite)], WEB, dict(os.environ)))
    if server_ready():
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        parts.append(
            (
                "server",
                [
                    python_bin(),
                    "-c",
                    "import sys; from basseparate.cli import main; sys.exit(main())",
                    "serve",
                    "--no-browser",
                    "--port",
                    "0",
                ],
                ROOT,
                env,
            )
        )
    if not parts:
        print("dev: nothing to run yet")
        print("  server: src/basseparate/cli.py (backend task)")
        print("  UI:     web/src/main.tsx (UI task)")
        print("  fixtures are ready; `make demo` lists them")
        return 0
    processes: list[subprocess.Popen[str]] = []
    try:
        for name, cmd, cwd, env in parts:
            print(f"dev: starting {name}")
            processes.append(subprocess.Popen(cmd, cwd=str(cwd), env=env, text=True))
        print("dev: press Ctrl+C to stop")
        while True:
            for (name, _, _, _), process in zip(parts, processes, strict=True):
                if process.poll() is not None:
                    print(f"dev: {name} exited with {process.returncode}")
                    return process.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("dev: stopping")
        return 0
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def ensure_fixtures() -> None:
    ok, detail = check_fixtures()
    if not ok:
        write_fixtures()


def build() -> int:
    failures = 0
    compile_result = run([python_bin(), "-m", "compileall", "-q", str(SRC)], timeout=300)
    print(f"  [{'PASS' if compile_result.returncode == 0 else 'FAIL'}] python compile")
    failures += compile_result.returncode != 0
    if compile_result.returncode != 0:
        print(tail(compile_result.stdout + compile_result.stderr))
    if web_sources_exist():
        for name, step in (("web typecheck", gate_web_typecheck), ("web build", gate_web_build)):
            result = step()
            print(f"  [{result.status.upper()}] {name}: {first_line(result.detail)}")
            failures += result.status == "fail"
    else:
        print("  [SKIP] web build: web/src is empty")
    return 1 if failures else 0


def test() -> int:
    return run_gate(
        [
            ("fixtures", gate_fixtures),
            ("pytest", lambda: gate_pytest(False)),
            ("web tests", gate_web_tests),
        ],
        "test",
    )


def e2e() -> int:
    result = gate_e2e()
    print(f"e2e: {result.status.upper()} {result.detail.splitlines()[0] if result.detail else ''}")
    if result.status == "fail":
        print(result.detail)
        return 1
    return 0


def fix() -> int:
    failures = 0
    ruff = run([python_bin(), "-m", "ruff", "check", "--fix", SRC, ROOT / "scripts"], timeout=300)
    print(f"  [{'PASS' if ruff.returncode == 0 else 'FAIL'}] ruff check --fix")
    if ruff.returncode != 0:
        print(tail(ruff.stdout + ruff.stderr))
        failures += 1
    fmt = run([python_bin(), "-m", "ruff", "format", SRC, ROOT / "scripts"], timeout=300)
    print(f"  [{'PASS' if fmt.returncode == 0 else 'FAIL'}] ruff format")
    failures += fmt.returncode != 0
    prettier = WEB_MODULES / ".bin" / "prettier"
    if prettier.exists() and web_sources_exist():
        result = run([prettier, "--write", "."], cwd=WEB, timeout=600)
        print(f"  [{'PASS' if result.returncode == 0 else 'FAIL'}] prettier --write")
        if result.returncode != 0:
            print(tail(result.stdout + result.stderr))
            failures += 1
    else:
        print("  [SKIP] prettier: no web sources yet")
    return 1 if failures else 0


def demo() -> int:
    ensure_fixtures()
    files, manifest = build_fixtures()
    print("demo fixtures (44.1 kHz mono unless noted)")
    for entry in manifest["fixtures"]:
        path = FIXTURES / entry["file"]
        detail = ", ".join(
            f"{key}={value}" for key, value in entry.items() if key not in {"file", "name"}
        )
        print(f"  {rel(path):44} {detail}")
    print()
    print("Next: `make bootstrap` links the web dependencies, `make dev` starts")
    print("the UI and server once the backend and UI tasks have landed.")
    return 0 if all((FIXTURES / entry["file"]).is_file() for entry in manifest["fixtures"]) else 1


# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="report toolchain, assets, plugins, Piper, model bundle and GPU")
    bootstrap_parser = sub.add_parser("bootstrap", help="offline, idempotent environment setup")
    bootstrap_parser.add_argument("--force", action="store_true", help="relink the web environment")
    sub.add_parser("fixtures", help="write the deterministic audio fixtures")
    check_parser = sub.add_parser(
        "fixtures-check", help="verify the fixtures rerun byte-identically"
    )
    check_parser.add_argument("--quiet", action="store_true")
    gate_parser = sub.add_parser("gate", help="run the full local gate")
    gate_parser.add_argument("--lite", action="store_true", help="skip build and end-to-end steps")
    sub.add_parser("dev", help="run the dev servers")
    sub.add_parser("build", help="compile Python and build the UI")
    sub.add_parser("test", help="run the test suites")
    sub.add_parser("e2e", help="run the browser end-to-end tests")
    sub.add_parser("fix", help="apply automatic formatting and lint fixes")
    sub.add_parser("demo", help="list the demo fixtures and next steps")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "bootstrap":
        if args.force:
            message = link_web_modules(force=True)
            print(f"bootstrap: {message}")
        return bootstrap()
    if args.command == "fixtures":
        return write_fixtures()
    if args.command == "fixtures-check":
        ok, detail = check_fixtures()
        if not args.quiet or not ok:
            print(("fixtures: ok " if ok else "fixtures: FAIL ") + detail)
        return 0 if ok else 1
    if args.command == "gate":
        return gate(lite=args.lite)
    if args.command == "dev":
        return dev()
    if args.command == "build":
        return build()
    if args.command == "test":
        return test()
    if args.command == "e2e":
        return e2e()
    if args.command == "fix":
        return fix()
    if args.command == "demo":
        return demo()
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
