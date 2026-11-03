"""Demucs stem separation orchestration, cache and HTTP surface.

This module is deliberately dependency-light: the application environment must
never import torch or demucs. Separation runs in the preserved analysis
environment (``analysis/.venv/bin/python analysis/separate_track.py``) with
offline flags; this module only hashes the prepared PCM, spawns that child,
streams its progress, enforces cancellation and publishes the four stems.

Cache identity is content addressed: prepared PCM SHA-256, project rate,
channel layout, window/overlap/shifts and the SHA-256 of the checkpoint
manifest. A cache entry is one directory with ``drums.f32``, ``bass.f32``,
``other.f32``, ``vocals.f32`` plus ``stems.json``; publication renames a fully
written staging directory into place, so a cancelled or failed run leaves no
partial stem set.

The UI-facing routes live on :data:`router`; :func:`install` registers the
``separate`` job kind and includes that router in an application. The app
factory only needs ``stems.install(app)`` after its state is populated.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from basseparate.api.deps import JobsDep, PathsDep, StoreDep
from basseparate.config import DataPaths
from basseparate.jobs import JobCancelled, JobContext, JobManager
from basseparate.media import (
    RangeError,
    atomic_write_bytes,
    pcm_response_headers,
    read_pcm_slice,
    unsatisfiable_range_headers,
)
from basseparate.model_registry import (
    ModelEntry,
    ModelRegistryError,
    ModelState,
    Registry,
    load_registry,
    verify_model,
    verify_registry,
)
from basseparate.peaks import (
    PEAK_BUCKET_SIZES,
    bucket_count,
    compute_peaks_from_file,
    decode_peaks,
    encode_peaks,
)
from basseparate.projects import Project, ProjectStore, RevisionConflict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYSIS_PYTHON = REPO_ROOT / "analysis" / ".venv" / "bin" / "python"
WORKER_SCRIPT = REPO_ROOT / "analysis" / "separate_track.py"
CHECKPOINT_MANIFEST = REPO_ROOT / "analysis" / "checkpoints.json"
DEFAULT_BUNDLE = REPO_ROOT / "models" / "htdemucs_ft"
MODELS_ROOT = REPO_ROOT
MODEL_REGISTRY_PATH = REPO_ROOT / "analysis" / "models.json"
ANALYSIS_MODELS_PYTHON = REPO_ROOT / "analysis-models" / ".venv" / "bin" / "python"
MSST_WORKER_SCRIPT = REPO_ROOT / "analysis" / "separate_msst.py"

DEFAULT_MODEL_ID = "htdemucs_ft"
STEM_LABELS: tuple[str, ...] = ("drums", "bass", "other", "vocals")
STEM_CHANNELS = 2
CACHE_VERSION = 2
SUPPORTED_CACHE_VERSIONS: tuple[int, ...] = (1, 2)
CACHE_DIR_NAME = "stems"

# Measured locally in the dependency tasks (8 s fixture, CPU); kept here so the
# model picker can show a realistic cost without importing torch or running a
# model. These are measurements, not registry identity.
MODEL_METRICS: dict[str, dict[str, object]] = {
    "htdemucs_ft": {
        "device": "cpu",
        "fixture_seconds": 8.0,
        "wall_seconds": 19.24,
        "child_seconds": 18.85,
        "source": "t8 measured run",
    },
    "scnet-xl-ihf": {
        "device": "cpu",
        "fixture_seconds": 8.0,
        "wall_seconds": 58.20,
        "child_seconds": 55.32,
        "peak_rss_mib": 3965.4,
        "source": "t49 measured run",
    },
    "bs-roformer-sw": {
        "device": "cpu",
        "fixture_seconds": 8.0,
        "wall_seconds": 67.35,
        "child_seconds": 65.97,
        "peak_rss_mib": 3006.4,
        "source": "t49 measured run",
    },
}
DEFAULT_WINDOW_SECONDS = 120.0
DEFAULT_OVERLAP_SECONDS = 8.0
DEFAULT_SHIFTS = 0
CANCEL_GRACE_SECONDS = 10.0
STDERR_TAIL_LIMIT = 4096
READ_POLL_SECONDS = 0.1
BINARY_MEDIA_TYPE = "application/octet-stream"

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


class StemError(RuntimeError):
    """Stem separation failed; the message is safe for the UI."""


class StemsCancelled(StemError):
    """The caller cancelled; the child is gone and no cache entry was published."""


@dataclass(frozen=True)
class StemFile:
    label: str
    path: Path
    frames: int
    channels: int


@dataclass(frozen=True)
class StemSet:
    key: str
    directory: Path
    sample_rate: int
    channels: int
    frames: int
    stems: tuple[StemFile, ...]
    device: str
    elapsed_seconds: float
    cached: bool
    metadata: Mapping[str, Any]
    model_id: str = DEFAULT_MODEL_ID

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(stem.label for stem in self.stems)

    def file(self, label: str) -> StemFile:
        for stem in self.stems:
            if stem.label == label:
                return stem
        raise StemError(f"stem set has no {label!r} stem")

    def payload(self, project_id: str | None = None) -> dict[str, Any]:
        stems: list[dict[str, Any]] = []
        for stem in self.stems:
            entry: dict[str, Any] = {
                "label": stem.label,
                "frames": stem.frames,
                "channels": stem.channels,
                "sampleRate": self.sample_rate,
                "sample_rate": self.sample_rate,
                "key": self.key,
                "model": self.model_id,
                "model_id": self.model_id,
                "path": f"{CACHE_DIR_NAME}/{self.key}/{stem.label}.f32",
                "cache_key": self.key,
            }
            if project_id is not None:
                entry["url"] = stem_url(project_id, stem.label)
            stems.append(entry)
        return {
            "key": self.key,
            "cached": self.cached,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "frames": self.frames,
            "device": self.device,
            "elapsed_seconds": self.elapsed_seconds,
            "model": self.model_id,
            "model_id": self.model_id,
            "labels": list(self.labels),
            "stems": stems,
        }


class SeparateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    model_id: str = Field(default=DEFAULT_MODEL_ID, min_length=1, max_length=64)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    force: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_sha256() -> str:
    if not CHECKPOINT_MANIFEST.is_file():
        raise StemError(
            f"checkpoint manifest is missing: {CHECKPOINT_MANIFEST}. Restore the preserved "
            "analysis/checkpoints.json before separating."
        )
    return sha256_file(CHECKPOINT_MANIFEST)


def model_cache_hashes(entry: ModelEntry, *, root: Path = MODELS_ROOT) -> dict[str, str]:
    """Weights/config identity for the cache key; declared hashes, no model load."""
    if entry.bundled:
        if entry.checkpoint_manifest is None:
            raise StemError(f"bundled model {entry.id} has no checkpoint manifest")
        manifest = Path(root) / entry.checkpoint_manifest
        if not manifest.is_file():
            raise StemError(f"checkpoint manifest is missing: {manifest}")
        hashes = {"checkpoints_manifest": sha256_file(manifest)}
        if entry.config_name:
            config = Path(root) / entry.install_dir / entry.config_name
            if config.is_file():
                hashes["config"] = sha256_file(config)
        return hashes
    if not entry.files:
        raise StemError(f"model {entry.id} declares no weights or config files")
    return {
        f"{item.role}:{item.name}": item.sha256
        for item in sorted(entry.files, key=lambda item: (item.role, item.name))
    }


def stem_cache_key(
    pcm_sha256: str,
    *,
    sample_rate: int,
    channels: int,
    model_id: str = DEFAULT_MODEL_ID,
    model_hashes: Mapping[str, str] | None = None,
    labels: tuple[str, ...] | None = None,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    shifts: int = DEFAULT_SHIFTS,
) -> str:
    """Content address for a stem set; includes model id and weight/config hashes.

    Version 1 keys were the Demucs-only shape; version 2 identity keeps old
    entries readable by key while ensuring a different model or checkpoint set
    can never collide with the current one.
    """
    identity = {
        "schema": CACHE_VERSION,
        "pcm_sha256": pcm_sha256,
        "sample_rate": sample_rate,
        "channels": channels,
        "model_id": model_id,
        "labels": list(labels) if labels is not None else list(STEM_LABELS),
        "model_hashes": dict(sorted((model_hashes or {}).items())),
        "window_seconds": round(window_seconds, 6),
        "overlap_seconds": round(overlap_seconds, 6),
        "shifts": shifts,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_root(paths: DataPaths) -> Path:
    return paths.root / CACHE_DIR_NAME


def cache_entry(paths: DataPaths, key: str) -> Path:
    return cache_root(paths) / key


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StemError(f"{label} is not a JSON object")
    return value


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StemError(f"{label} is not an integer")
    return value


def _as_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StemError(f"{label} is not a number")
    return float(value)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StemError(f"cannot read {path}: {error}") from error
    return _as_mapping(payload, str(path))


def read_stem_cache(paths: DataPaths, key: str) -> StemSet | None:
    """Read a complete cache entry; any missing or corrupt part is a miss."""
    directory = cache_entry(paths, key)
    try:
        payload = _read_json(directory / "stems.json")
        version = _as_int(payload.get("version"), "cache version")
        if version not in SUPPORTED_CACHE_VERSIONS:
            return None
        if payload.get("key") != key:
            return None
        sample_rate = _as_int(payload.get("sample_rate"), "sample rate")
        channels = _as_int(payload.get("channels"), "channels")
        frames = _as_int(payload.get("frames"), "frames")
        if version == 1:
            model_id = DEFAULT_MODEL_ID
            expected_labels = STEM_LABELS
        else:
            raw_model = payload.get("model_id")
            if not isinstance(raw_model, str) or not raw_model:
                return None
            model_id = raw_model
            raw_labels = payload.get("labels")
            if not isinstance(raw_labels, list) or not raw_labels:
                return None
            if any(not isinstance(label, str) or not label for label in raw_labels):
                return None
            if len(set(raw_labels)) != len(raw_labels):
                return None
            expected_labels = tuple(raw_labels)
            reported_labels = payload.get("model_labels")
            if reported_labels is not None and list(reported_labels) != list(raw_labels):
                return None
            try:
                model_entry = load_registry(MODEL_REGISTRY_PATH).get(model_id)
            except ModelRegistryError:
                model_entry = None
            if model_entry is not None and tuple(model_entry.labels) != expected_labels:
                return None
        rows = payload.get("stems")
        if not isinstance(rows, list):
            return None
        stems: list[StemFile] = []
        for row in rows:
            entry = _as_mapping(row, "stem")
            label = entry.get("label")
            file_name = entry.get("file")
            if not isinstance(label, str) or not isinstance(file_name, str):
                return None
            stem_frames = _as_int(entry.get("frames"), "stem frames")
            stem_channels = _as_int(entry.get("channels"), "stem channels")
            path = directory / file_name
            if not path.is_file():
                return None
            if path.stat().st_size != stem_frames * stem_channels * 4:
                return None
            stems.append(
                StemFile(
                    label=label,
                    path=path,
                    frames=stem_frames,
                    channels=stem_channels,
                )
            )
        if tuple(stem.label for stem in stems) != expected_labels:
            return None
        if any(stem.frames != frames or stem.channels != channels for stem in stems):
            return None
        device = str(payload.get("device", "unknown"))
        elapsed = _as_float(payload.get("elapsed_seconds", 0.0), "elapsed")
        return StemSet(
            key=key,
            directory=directory,
            sample_rate=sample_rate,
            channels=channels,
            frames=frames,
            stems=tuple(stems),
            device=device,
            elapsed_seconds=elapsed,
            cached=True,
            metadata=payload,
            model_id=model_id,
        )
    except (OSError, StemError, KeyError, ValueError):
        return None


def _write_cache_meta(
    stage: Path,
    *,
    key: str,
    pcm_sha256: str,
    sample_rate: int,
    channels: int,
    frames: int,
    worker_meta: Mapping[str, Any],
    model: ModelEntry,
    model_hashes: Mapping[str, str],
) -> None:
    stems = [
        {
            "label": label,
            "file": f"{label}.f32",
            "frames": frames,
            "channels": channels,
        }
        for label in model.labels
    ]
    payload = {
        "version": CACHE_VERSION,
        "key": key,
        "model_id": model.id,
        "model_name": model.name,
        "model_engine": model.engine,
        "model_labels": list(model.labels),
        "model_hashes": dict(sorted(model_hashes.items())),
        "labels": list(model.labels),
        "source_pcm_sha256": pcm_sha256,
        "sample_rate": sample_rate,
        "channels": channels,
        "frames": frames,
        "stems": stems,
        "device": str(worker_meta.get("device", "unknown")),
        "elapsed_seconds": float(worker_meta.get("elapsed_seconds", 0.0)),
        "quality": worker_meta.get("quality", {}),
        "checkpoints": worker_meta.get("checkpoints", {}),
        "worker": dict(worker_meta),
    }
    atomic_write_bytes(
        stage / "stems.json",
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _publish(paths: DataPaths, key: str, stage: Path, *, force: bool) -> StemsSetOrNone:
    final = cache_entry(paths, key)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.is_dir():
        if not force:
            cached = read_stem_cache(paths, key)
            if cached is not None:
                shutil.rmtree(stage, ignore_errors=True)
                return cached
        shutil.rmtree(final, ignore_errors=True)
    stage.rename(final)
    _fsync_directory(final.parent)
    return None


StemsSetOrNone = StemSet | None


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stderr_tail(stream: IO[bytes] | None) -> str:
    if stream is None:
        return ""
    try:
        stream.flush()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - STDERR_TAIL_LIMIT))
        text = stream.read().decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""
    if not text:
        return ""
    return "\nworker stderr tail:\n" + text


def _validate_worker_output(
    stage: Path,
    *,
    frames: int,
    sample_rate: int,
    labels: tuple[str, ...],
    model_id: str,
) -> Mapping[str, Any]:
    meta_path = stage / "meta.json"
    if not meta_path.is_file():
        raise StemError(f"separation produced no metadata ({meta_path.name})")
    meta = _read_json(meta_path)
    if meta.get("status") != "complete":
        raise StemError(f"separation did not complete: {meta.get('status')!r}")
    if tuple(meta.get("labels", ())) != labels:
        raise StemError(f"separation produced labels {meta.get('labels')!r}, expected {labels}")
    reported_model = meta.get("model_id")
    if reported_model is not None and str(reported_model) != model_id:
        raise StemError(
            f"separation worker reported model {reported_model!r}, expected {model_id!r}"
        )
    if _as_int(meta.get("frames"), "worker frames") != frames:
        raise StemError(
            f"separation produced {meta.get('frames')} frames, expected "
            f"{frames} at the project rate"
        )
    if _as_int(meta.get("sample_rate"), "worker sample rate") != sample_rate:
        raise StemError(f"separation wrote {meta.get('sample_rate')} Hz, expected {sample_rate} Hz")
    for label in labels:
        path = stage / f"{label}.f32"
        if not path.is_file():
            raise StemError(f"separation is missing the {label} stem")
        expected = frames * STEM_CHANNELS * 4
        if path.stat().st_size != expected:
            raise StemError(
                f"{label} stem has {path.stat().st_size} bytes, expected {expected} "
                f"({frames} frames × {STEM_CHANNELS} channels)"
            )
    return meta


def resolve_model(model_id: str, *, registry: Registry | None = None) -> ModelEntry:
    """Look up a model id in the registry with a user-facing error."""
    try:
        active = registry if registry is not None else load_registry(MODEL_REGISTRY_PATH)
        return active.get(model_id)
    except ModelRegistryError as error:
        raise StemError(str(error)) from error


def require_model_installed(entry: ModelEntry) -> ModelState:
    state = verify_model(entry)
    if not state.installed:
        raise StemError(
            f"model {entry.id} is not installed ({state.status}: {state.detail}); "
            f"install it with: {entry.install_command}"
        )
    return state


def worker_command(
    model: ModelEntry,
    *,
    pcm_path: Path,
    stage: Path,
    sample_rate: int,
    channels: int,
    device: str,
    cancel_path: Path,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    shifts: int = DEFAULT_SHIFTS,
    analysis_python: Path | None = None,
    worker_script: Path | None = None,
    bundle_dir: Path | None = None,
) -> list[str]:
    """Build the engine-specific child command for the selected model."""
    if model.engine == "demucs":
        interpreter = Path(analysis_python) if analysis_python is not None else ANALYSIS_PYTHON
        worker = Path(worker_script) if worker_script is not None else WORKER_SCRIPT
        bundle = Path(bundle_dir) if bundle_dir is not None else MODELS_ROOT / model.install_dir
        return [
            str(interpreter),
            str(worker),
            "--input",
            str(pcm_path),
            "--out",
            str(stage),
            "--bundle-dir",
            str(bundle),
            "--manifest",
            str(CHECKPOINT_MANIFEST),
            "--device",
            device,
            "--sample-rate",
            str(sample_rate),
            "--channels",
            str(channels),
            "--window-seconds",
            str(window_seconds),
            "--overlap-seconds",
            str(overlap_seconds),
            "--shifts",
            str(shifts),
            "--cancel",
            str(cancel_path),
        ]
    if model.engine == "msst":
        interpreter = (
            Path(analysis_python) if analysis_python is not None else ANALYSIS_MODELS_PYTHON
        )
        worker = Path(worker_script) if worker_script is not None else MSST_WORKER_SCRIPT
        return [
            str(interpreter),
            str(worker),
            "--input",
            str(pcm_path),
            "--out",
            str(stage),
            "--model-id",
            model.id,
            "--sample-rate",
            str(sample_rate),
            "--channels",
            str(channels),
            "--models-root",
            str(MODELS_ROOT),
            "--registry",
            str(MODEL_REGISTRY_PATH),
            "--device",
            device,
        ]
    raise StemError(f"model {model.id} uses unsupported engine {model.engine!r}")


def _read_worker_line(
    process: subprocess.Popen[bytes], deadline: float
) -> tuple[dict[str, Any] | None, bool]:
    """Read one JSON line, returning (event, eof) without blocking forever."""
    stdout = process.stdout
    if stdout is None:
        return None, True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StemError("separation timed out")
    ready, _, _ = select.select([stdout], [], [], min(READ_POLL_SECONDS, remaining))
    if not ready:
        return None, False
    line = stdout.readline()
    if not line:
        return None, True
    text = line.decode("utf-8", "replace").strip()
    if not text:
        return None, False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, False
    if not isinstance(payload, Mapping):
        return None, False
    return dict(payload), False


def separate_asset(
    pcm_path: Path,
    *,
    sample_rate: int,
    channels: int,
    paths: DataPaths,
    model_id: str = DEFAULT_MODEL_ID,
    model: ModelEntry | None = None,
    registry: Registry | None = None,
    bundle_dir: Path | None = None,
    device: str = "auto",
    force: bool = False,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    shifts: int = DEFAULT_SHIFTS,
    timeout_seconds: float = 3600.0,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    analysis_python: Path | None = None,
    worker_script: Path | None = None,
) -> StemSet:
    """Separate one prepared PCM into the selected model's cached f32 stems."""
    entry = model if model is not None else resolve_model(model_id, registry=registry)
    if model is None:
        require_model_installed(entry)
    labels = entry.labels
    model_hashes = model_cache_hashes(entry)
    pcm = Path(pcm_path)
    if not pcm.is_file():
        raise StemError(f"prepared PCM is missing: {pcm}")
    if sample_rate <= 0 or channels not in (1, 2):
        raise StemError(f"invalid PCM layout: {sample_rate} Hz, {channels} channels")
    if pcm.stat().st_size % (channels * 4):
        raise StemError(f"prepared PCM is not aligned to {channels} channels")
    frames = pcm.stat().st_size // (channels * 4)
    if frames <= 0:
        raise StemError("prepared PCM is empty")
    pcm_sha = sha256_file(pcm)
    key = stem_cache_key(
        pcm_sha,
        sample_rate=sample_rate,
        channels=channels,
        model_id=entry.id,
        model_hashes=model_hashes,
        labels=labels,
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
        shifts=shifts,
    )
    if not force:
        cached = read_stem_cache(paths, key)
        if cached is not None and cached.model_id == entry.id and cached.labels == labels:
            if progress is not None:
                progress(1.0, "stems already cached")
            return cached

    analysis = (
        Path(analysis_python)
        if analysis_python is not None
        else (ANALYSIS_PYTHON if entry.engine == "demucs" else ANALYSIS_MODELS_PYTHON)
    )
    worker = (
        Path(worker_script)
        if worker_script is not None
        else (WORKER_SCRIPT if entry.engine == "demucs" else MSST_WORKER_SCRIPT)
    )
    bundle = Path(bundle_dir) if bundle_dir is not None else MODELS_ROOT / entry.install_dir
    if not analysis.is_file() or not os.access(analysis, os.X_OK):
        raise StemError(
            f"separation interpreter is missing or not executable: {analysis}. "
            f"Run {entry.install_command}."
        )
    if not worker.is_file():
        raise StemError(f"separation worker is missing: {worker}")
    if entry.engine == "demucs" and not bundle.is_dir():
        raise StemError(f"model bundle is missing: {bundle}")

    root = cache_root(paths)
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=root))
    cancel_path = stage / "cancel.flag"
    command = worker_command(
        entry,
        analysis_python=analysis,
        worker_script=worker,
        pcm_path=pcm,
        stage=stage,
        sample_rate=sample_rate,
        channels=channels,
        bundle_dir=bundle,
        device=device,
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
        shifts=shifts,
        cancel_path=cancel_path,
    )
    environment = dict(os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    stderr_stream = tempfile.TemporaryFile()  # noqa: SIM115 - spans the child
    process: subprocess.Popen[bytes] | None = None
    published = False
    started = time.monotonic()
    deadline = started + timeout_seconds
    child_error: str | None = None
    cancelled = False
    try:
        if is_cancelled is not None and is_cancelled():
            raise StemsCancelled("separation cancelled before start")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr_stream,
            env=environment,
            bufsize=0,
        )
        if process.stdout is None:
            raise StemError("separation worker exposed no stdout")
        eof = False
        while not eof:
            if is_cancelled is not None and is_cancelled():
                cancelled = True
                break
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise StemError("separation timed out" + _stderr_tail(stderr_stream))
            event, eof = _read_worker_line(process, deadline)
            if event is None:
                if process.poll() is not None and eof:
                    break
                continue
            kind = event.get("type")
            if kind == "progress":
                fraction = event.get("fraction")
                if isinstance(fraction, (int, float)) and progress is not None:
                    detail = str(event.get("stage", "separating"))
                    if event.get("window") is not None:
                        detail += f" · window {event['window']}/{event.get('windows', '?')}"
                    progress(min(0.99, max(0.0, float(fraction))), detail)
            elif kind == "attempt":
                if progress is not None:
                    progress(
                        min(0.99, max(0.0, float(event.get("fraction", 0.0)))),
                        f"attempt {event.get('attempt')}/"
                        f"{event.get('attempts', event.get('segments', '?'))} · "
                        f"segment {event.get('segment_seconds')}s",
                    )
            elif kind == "failed":
                child_error = str(event.get("error", "unknown separation error"))
            elif kind == "cancelled":
                cancelled = True
        if cancelled:
            with contextlib.suppress(OSError):
                cancel_path.write_text("cancel\n", encoding="utf-8")
            try:
                process.wait(timeout=CANCEL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise StemsCancelled("separation cancelled")
        try:
            code = process.wait(timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise StemError("separation timed out" + _stderr_tail(stderr_stream)) from error
        tail = _stderr_tail(stderr_stream)
        if code == 2:
            raise StemsCancelled("separation cancelled")
        if code != 0:
            detail = child_error or f"exit status {code}"
            raise StemError(f"separation failed ({detail}){tail}")
        worker_meta = _validate_worker_output(
            stage,
            frames=frames,
            sample_rate=sample_rate,
            labels=labels,
            model_id=entry.id,
        )
        _write_cache_meta(
            stage,
            key=key,
            pcm_sha256=pcm_sha,
            sample_rate=sample_rate,
            channels=STEM_CHANNELS,
            frames=frames,
            worker_meta=worker_meta,
            model=entry,
            model_hashes=model_hashes,
        )
        existing = _publish(paths, key, stage, force=force)
        if existing is not None:
            published = True
            return existing
        published = True
        result = read_stem_cache(paths, key)
        if result is None:
            raise StemError("published stems could not be read back")
        if progress is not None:
            progress(1.0, "stems ready")
        return replace(result, cached=False)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if not published:
            shutil.rmtree(stage, ignore_errors=True)
        stderr_stream.close()


def separate_project(
    project: Project,
    *,
    paths: DataPaths,
    model_id: str = DEFAULT_MODEL_ID,
    model: ModelEntry | None = None,
    registry: Registry | None = None,
    bundle_dir: Path | None = None,
    device: str = "auto",
    force: bool = False,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    shifts: int = DEFAULT_SHIFTS,
    timeout_seconds: float = 3600.0,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    analysis_python: Path | None = None,
    worker_script: Path | None = None,
) -> StemSet:
    pcm = paths.asset_dir(project.audio.asset_id) / "pcm.f32"
    if not pcm.is_file():
        raise StemError(f"decoded PCM for project {project.id} is missing")
    expected_bytes = project.audio.frames * project.audio.channels * 4
    if pcm.stat().st_size != expected_bytes:
        raise StemError(
            f"decoded PCM for project {project.id} is {pcm.stat().st_size} bytes, "
            f"expected {expected_bytes}"
        )
    if model is not None:
        entry = model
    else:
        entry = resolve_model(model_id, registry=registry)
        require_model_installed(entry)
    return separate_asset(
        pcm,
        sample_rate=project.audio.sample_rate,
        channels=project.audio.channels,
        paths=paths,
        model=entry,
        bundle_dir=bundle_dir,
        device=device,
        force=force,
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
        shifts=shifts,
        timeout_seconds=timeout_seconds,
        progress=progress,
        is_cancelled=is_cancelled,
        analysis_python=analysis_python,
        worker_script=worker_script,
    )


def stem_url(project_id: str, label: str) -> str:
    return f"/api/projects/{project_id}/stems/{label}/pcm"


def publish_project_stems(store: ProjectStore, project_id: str, stem_set: StemSet) -> Project:
    """Merge stem descriptors into the project document, retrying a save race."""
    for _ in range(4):
        current = store.get(project_id)
        document = dict(current.document)
        document["stems"] = stem_set.payload(project_id)["stems"]
        document["stemCacheKey"] = stem_set.key
        document["stemModel"] = stem_set.model_id
        try:
            return store.update(project_id, document=document, expected_revision=current.revision)
        except RevisionConflict:
            time.sleep(0.02)
    raise StemError(f"could not save stem metadata into project {project_id}")


def _runner(
    store: ProjectStore, paths: DataPaths
) -> Callable[[JobContext, Mapping[str, Any]], object]:
    def run(context: JobContext, params: Mapping[str, Any]) -> object:
        request = SeparateRequest.model_validate(dict(params))
        entry = resolve_model(request.model_id)
        require_model_installed(entry)
        project = store.get(request.project_id)
        try:
            stem_set = separate_project(
                project,
                paths=paths,
                model=entry,
                device=request.device,
                force=request.force,
                progress=lambda fraction, message: context.progress(fraction, message),
                is_cancelled=lambda: context.cancelled,
            )
        except StemsCancelled as error:
            raise JobCancelled(str(error)) from error
        context.check_cancelled()
        publish_project_stems(store, request.project_id, stem_set)
        return stem_set.payload(request.project_id)

    return run


def register_stems_job(manager: JobManager, *, paths: DataPaths, store: ProjectStore) -> None:
    manager.register("separate", _runner(store, paths))


def stem_peaks_path(stem_set: StemSet, label: str, buckets: int) -> Path:
    """Where a stem's waveform peaks live inside its content-addressed entry."""
    return stem_set.directory / f"peaks-{label}-{buckets}.bin"


def _cached_stem_peaks(
    path: Path,
    *,
    buckets: int,
    channels: int,
    sample_rate: int,
    frames: int,
) -> bytes | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    try:
        decoded = decode_peaks(payload)
    except ValueError:
        return None
    if (
        decoded.bucket_size == buckets
        and decoded.channels == channels
        and decoded.sample_rate == sample_rate
        and decoded.bucket_count == bucket_count(frames, buckets)
    ):
        return payload
    return None


def ensure_stem_peaks(stem_set: StemSet, stem: StemFile, buckets: int) -> bytes:
    """Return the BSPK bytes for one stem, computing and atomically caching once."""
    if buckets not in PEAK_BUCKET_SIZES:
        choices = ", ".join(str(size) for size in PEAK_BUCKET_SIZES)
        raise StemError(f"unsupported bucket size {buckets}; choose one of {choices}")
    path = stem_peaks_path(stem_set, stem.label, buckets)
    cached = _cached_stem_peaks(
        path,
        buckets=buckets,
        channels=stem.channels,
        sample_rate=stem_set.sample_rate,
        frames=stem.frames,
    )
    if cached is not None:
        return cached
    path.unlink(missing_ok=True)
    try:
        peaks = compute_peaks_from_file(
            stem.path,
            channels=stem.channels,
            frames=stem.frames,
            bucket_size=buckets,
        )
        payload = encode_peaks(peaks, sample_rate=stem_set.sample_rate)
        atomic_write_bytes(path, payload)
    except OSError as error:
        raise StemError(f"cannot cache waveform peaks for stem {stem.label}: {error}") from error
    return payload


router = APIRouter(tags=["stems"])


@router.get("/separation/models")
def separation_models() -> dict[str, Any]:
    registry = load_registry(MODEL_REGISTRY_PATH)
    states = verify_registry(registry)
    models = []
    for state in states:
        payload = state.to_dict()
        payload["metrics"] = dict(MODEL_METRICS.get(state.entry.id, {}))
        payload["default"] = state.entry.id == DEFAULT_MODEL_ID
        payload["install_command"] = state.entry.install_command
        payload["size"] = state.entry.size_bytes
        payload["stem_labels"] = list(state.entry.labels)
        models.append(payload)
    return {"default": DEFAULT_MODEL_ID, "models": models}


@router.post("/separate", status_code=status.HTTP_202_ACCEPTED)
def start_separation(
    body: SeparateRequest,
    jobs: JobsDep,
    store: StoreDep,
) -> dict[str, Any]:
    try:
        entry = resolve_model(body.model_id)
        require_model_installed(entry)
    except StemError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    store.get(body.project_id)  # 404 before the job is queued
    try:
        job = jobs.submit("separate", body.model_dump())
    except KeyError as error:
        raise HTTPException(
            status_code=400,
            detail="the separate job is not installed; call stems.install(app) first",
        ) from error
    payload = job.to_dict()
    payload["params"] = body.model_dump()
    payload["model_id"] = entry.id
    payload["model"] = entry.to_dict()
    return payload


@router.get("/projects/{project_id}/stems")
def project_stems(project_id: str, store: StoreDep, paths: PathsDep) -> dict[str, Any]:
    project = store.get(project_id)
    stems = project.document.get("stems", [])
    if not isinstance(stems, list):
        stems = []
    model = project.document.get("stemModel")
    if not isinstance(model, str):
        key = project.document.get("stemCacheKey")
        if isinstance(key, str):
            cached = read_stem_cache(paths, key)
            if cached is not None:
                model = cached.model_id
    return {
        "project_id": project_id,
        "key": project.document.get("stemCacheKey"),
        "model": model,
        "model_id": model,
        "active_model": model,
        "stems": stems,
    }


def _stem_range_error(error: RangeError, total_bytes: int) -> Response:
    return Response(
        content=json.dumps({"detail": str(error)}).encode(),
        status_code=416,
        media_type="application/json",
        headers=unsatisfiable_range_headers(total_bytes),
    )


@router.get("/projects/{project_id}/stems/{label}/peaks")
def project_stem_peaks(
    project_id: str,
    label: str,
    paths: PathsDep,
    store: StoreDep,
    buckets: int = Query(default=1024),
) -> Response:
    if buckets not in PEAK_BUCKET_SIZES:
        choices = ", ".join(str(size) for size in PEAK_BUCKET_SIZES)
        raise HTTPException(
            status_code=400,
            detail=f"unsupported bucket size {buckets}; choose one of {choices}",
        )
    project = store.get(project_id)
    key = project.document.get("stemCacheKey")
    if not isinstance(key, str):
        raise HTTPException(status_code=404, detail=f"project {project_id} has no stem set")
    stem_set = read_stem_cache(paths, key)
    if stem_set is None:
        raise HTTPException(status_code=404, detail=f"stem set {key} is missing or incomplete")
    if label not in stem_set.labels:
        raise HTTPException(status_code=404, detail=f"unknown stem {label!r}")
    stem = stem_set.file(label)
    payload = ensure_stem_peaks(stem_set, stem, buckets)
    return Response(
        content=payload,
        media_type=BINARY_MEDIA_TYPE,
        headers={
            "x-bucket-size": str(buckets),
            "x-channels": str(stem.channels),
            "x-sample-rate": str(stem_set.sample_rate),
            "x-stem-label": label,
            "cache-control": "private, max-age=3600",
        },
    )


@router.get("/projects/{project_id}/stems/{label}/pcm")
def project_stem_pcm(
    project_id: str,
    label: str,
    request: Request,
    paths: PathsDep,
    store: StoreDep,
    start: int = Query(default=0),
    end: int | None = Query(default=None),
) -> Response:
    project = store.get(project_id)
    key = project.document.get("stemCacheKey")
    if not isinstance(key, str):
        raise HTTPException(status_code=404, detail=f"project {project_id} has no stem set")
    stem_set = read_stem_cache(paths, key)
    if stem_set is None:
        raise HTTPException(status_code=404, detail=f"stem set {key} is missing or incomplete")
    if label not in stem_set.labels:
        raise HTTPException(status_code=404, detail=f"unknown stem {label!r}")
    stem = stem_set.file(label)
    total_bytes = stem.path.stat().st_size
    try:
        sliced = read_pcm_slice(
            stem.path,
            channels=stem.channels,
            total_frames=stem_set.frames,
            range_header=request.headers.get("range"),
            start=start,
            end=end,
        )
    except RangeError as error:
        return _stem_range_error(error, total_bytes)
    return Response(
        content=sliced.payload,
        status_code=sliced.status_code,
        media_type=BINARY_MEDIA_TYPE,
        headers=pcm_response_headers(
            start_frame=sliced.start_frame,
            end_frame=sliced.end_frame,
            total_frames=sliced.total_frames,
            sample_rate=stem_set.sample_rate,
            channels=stem.channels,
            content_range=sliced.content_range,
            extra={"x-stem-label": label},
        ),
    )


def install(app: Any) -> None:
    """Register the separate job and include the stem routes once."""
    if getattr(app.state, "stems_installed", False):
        return
    paths: DataPaths = app.state.paths
    store: ProjectStore = app.state.projects
    jobs: JobManager = app.state.jobs
    register_stems_job(jobs, paths=paths, store=store)
    app.include_router(router, prefix="/api")
    app.state.stems_installed = True


__all__ = [
    "CACHE_VERSION",
    "DEFAULT_MODEL_ID",
    "MODEL_METRICS",
    "STEM_LABELS",
    "SUPPORTED_CACHE_VERSIONS",
    "SeparateRequest",
    "StemError",
    "StemFile",
    "StemSet",
    "StemsCancelled",
    "cache_entry",
    "cache_root",
    "ensure_stem_peaks",
    "install",
    "model_cache_hashes",
    "publish_project_stems",
    "read_stem_cache",
    "register_stems_job",
    "require_model_installed",
    "resolve_model",
    "router",
    "separate_asset",
    "separate_project",
    "sha256_file",
    "stem_cache_key",
    "stem_peaks_path",
    "stem_url",
    "worker_command",
]
