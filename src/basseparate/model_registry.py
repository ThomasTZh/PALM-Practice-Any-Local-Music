"""Separation model registry: parse, verify and describe local models.

The studio can run Demucs htdemucs_ft, MSST SCNet XL IHF and MSST
BS-RoFormer-SW. This module is the single source of truth for their ids,
engines, stems, sample rate, sizes, hashes, licences and pinned source URLs. It
uses only the standard library and never imports torch or another inference
package; the server can report model state without touching the analysis
environments.

``analysis/models.json`` schema 2 gives every model the same shape: a complete
list of file pins with byte size, SHA-256 and HTTPS URL. There is no bundled or
default special case. A source checkout still reports htdemucs_ft as installed
because its five files are present under ``models/htdemucs_ft``.

Verification is read-only: files are stat'ed and hashed, and the result is one
of ``installed``, ``missing`` or ``hash-mismatch``. The installer lives in
``scripts/models.py`` so the registry itself stays free of network code.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from basseparate.config import runtime_paths

# Kept for the maintainer CLI, which defaults to the source checkout. Runtime
# code resolves the registry and model roots through ``runtime_paths``.
DEFAULT_REGISTRY_PATH = runtime_paths().registry_path
MODELS_DIR_NAME = "models"

SCHEMA_VERSION = 2
ModelStatus = Literal["installed", "missing", "hash-mismatch"]
FileStatus = Literal["ok", "missing", "size-mismatch", "hash-mismatch", "extra"]
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_ENGINE_COMMANDS = {
    "demucs": "analysis/.venv/bin/python analysis/separate_track.py",
    "msst": "analysis-models/.venv/bin/python analysis/separate_msst.py",
}


class ModelRegistryError(ValueError):
    """The registry is missing, malformed or internally inconsistent."""


@dataclass(frozen=True)
class ModelFile:
    role: str
    name: str
    url: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ModelEntry:
    id: str
    name: str
    engine: str
    engine_command: str
    labels: tuple[str, ...]
    sample_rate: int
    size_bytes: int
    source_url: str
    license: str
    install_dir: str
    files: tuple[ModelFile, ...]
    # Compatibility aliases for callers written before schema 2. They are not
    # parsed from JSON and never serialized: every model is file-based now.
    bundled: bool = False
    checkpoint_manifest: str | None = None
    config_name: str | None = None

    @property
    def install_command(self) -> str:
        return f"make models-install ID={self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "engine": self.engine,
            "engine_command": self.engine_command,
            "labels": list(self.labels),
            "sample_rate": self.sample_rate,
            "size_bytes": self.size_bytes,
            "source_url": self.source_url,
            "license": self.license,
            "install_dir": self.install_dir,
            "install_command": self.install_command,
            "files": [
                {
                    "role": item.role,
                    "name": item.name,
                    "url": item.url,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in self.files
            ],
        }


@dataclass(frozen=True)
class Registry:
    schema_version: int
    models: tuple[ModelEntry, ...]

    def by_id(self) -> dict[str, ModelEntry]:
        return {entry.id: entry for entry in self.models}

    def get(self, model_id: str) -> ModelEntry:
        for entry in self.models:
            if entry.id == model_id:
                return entry
        raise ModelRegistryError(
            f"unknown model id {model_id!r}; known: {', '.join(entry.id for entry in self.models)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "models": [entry.to_dict() for entry in self.models],
        }


@dataclass(frozen=True)
class FileState:
    role: str
    name: str
    path: str
    status: FileStatus
    expected_size: int | None = None
    actual_size: int | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "expected_size": self.expected_size,
            "actual_size": self.actual_size,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelState:
    entry: ModelEntry
    status: ModelStatus
    model_dir: str
    files: tuple[FileState, ...] = ()
    detail: str = ""

    @property
    def installed(self) -> bool:
        return self.status == "installed"

    @property
    def labels(self) -> tuple[str, ...]:
        return self.entry.labels

    def to_dict(self) -> dict[str, Any]:
        payload = self.entry.to_dict()
        payload.update(
            {
                "status": self.status,
                "installed": self.installed,
                "model_dir": self.model_dir,
                "detail": self.detail,
                "file_states": [state.to_dict() for state in self.files],
            }
        )
        return payload


# Hashes of large checkpoint files are cached by path, size and mtime so a
# doctor call and an immediate verify/list do not read hundreds of MB twice.
_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cached_sha256(path: Path) -> str:
    resolved = Path(path)
    stat = resolved.stat()
    key = (str(resolved), stat.st_size, stat.st_mtime_ns)
    cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return cached
    digest = sha256_file(resolved)
    _DIGEST_CACHE[key] = digest
    return digest


def clear_digest_cache() -> None:
    _DIGEST_CACHE.clear()


# ---------------------------------------------------------------------------
# parsing


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelRegistryError(f"{label} must be a JSON object")
    return value


def _string(mapping: Mapping[str, Any], key: str, label: str, *, allow_empty: bool = False) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ModelRegistryError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModelRegistryError(f"{key} must be a non-empty string when present")
    return value.strip()


def _integer(mapping: Mapping[str, Any], key: str, label: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelRegistryError(f"{label}.{key} must be an integer")
    return value


def _https_url(value: str, label: str) -> str:
    if not value.startswith("https://"):
        raise ModelRegistryError(f"{label} must be an https URL, got {value!r}")
    return value


def _relative_parts(value: str, label: str) -> tuple[str, ...]:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelRegistryError(f"{label} must be a safe relative path, got {value!r}")
    return tuple(path.parts)


def _safe_name(value: str, label: str) -> str:
    name = Path(value).name
    if name != value or name in {"", ".", ".."}:
        raise ModelRegistryError(f"{label} must be a plain file name, got {value!r}")
    return value


def _parse_file(raw: object, index: int) -> ModelFile:
    label = f"models[{index}].files[{index}]"
    data = _mapping(raw, label)
    role = _string(data, "role", label)
    name = _safe_name(_string(data, "name", label), f"{label}.name")
    url = _https_url(_string(data, "url", label), f"{label}.url")
    size = _integer(data, "size_bytes", label)
    if size <= 0:
        raise ModelRegistryError(f"{label}.size_bytes must be positive")
    sha = _string(data, "sha256", label).lower()
    if not SHA256_PATTERN.fullmatch(sha):
        raise ModelRegistryError(f"{label}.sha256 must be a lowercase 64-character digest")
    return ModelFile(role=role, name=name, url=url, size_bytes=size, sha256=sha)


def _parse_entry(raw: object, index: int) -> ModelEntry:
    label = f"models[{index}]"
    data = _mapping(raw, label)
    model_id = _string(data, "id", label)
    if not ID_PATTERN.fullmatch(model_id):
        raise ModelRegistryError(f"{label}.id is not a safe model id: {model_id!r}")
    name = _string(data, "name", label)
    engine = _string(data, "engine", label)
    if engine not in DEFAULT_ENGINE_COMMANDS:
        raise ModelRegistryError(
            f"{label}.engine must be one of {', '.join(sorted(DEFAULT_ENGINE_COMMANDS))}"
        )
    command = data.get("engine_command", DEFAULT_ENGINE_COMMANDS[engine])
    if not isinstance(command, str) or not command.strip():
        raise ModelRegistryError(f"{label}.engine_command must be a non-empty string")
    labels_raw = data.get("labels")
    if not isinstance(labels_raw, list) or not labels_raw:
        raise ModelRegistryError(f"{label}.labels must be a non-empty list")
    labels: list[str] = []
    for item in labels_raw:
        if not isinstance(item, str) or not item.strip():
            raise ModelRegistryError(f"{label}.labels contains a non-string or empty label")
        labels.append(item.strip())
    if len(set(labels)) != len(labels):
        raise ModelRegistryError(f"{label}.labels contains duplicate stems")
    sample_rate = _integer(data, "sample_rate", label)
    if not 8_000 <= sample_rate <= 384_000:
        raise ModelRegistryError(f"{label}.sample_rate is outside the supported range")
    size_bytes = _integer(data, "size_bytes", label)
    if size_bytes <= 0:
        raise ModelRegistryError(f"{label}.size_bytes must be positive")
    source_url = _https_url(_string(data, "source_url", label), f"{label}.source_url")
    license_text = _string(data, "license", label)
    for retired in ("bundled", "default", "checkpoint_manifest", "config_name"):
        if retired in data:
            raise ModelRegistryError(
                f"{label}.{retired} is retired by model registry schema {SCHEMA_VERSION}. "
                "Every model now declares complete file pins; migrate the registry "
                "rather than relying on a bundled/default entry."
            )
    install_dir = _optional_string(data, "install_dir") or f"{MODELS_DIR_NAME}/{model_id}"
    parts = _relative_parts(install_dir, f"{label}.install_dir")
    if parts[0] != MODELS_DIR_NAME:
        raise ModelRegistryError(f"{label}.install_dir must live under {MODELS_DIR_NAME}/")
    files_raw = data.get("files", [])
    if not isinstance(files_raw, list) or not files_raw:
        raise ModelRegistryError(f"{label}.files must be a non-empty list")
    files = tuple(_parse_file(item, index) for item in files_raw)
    names = [item.name for item in files]
    if len(set(names)) != len(names):
        raise ModelRegistryError(f"{label}.files contains duplicate file names")
    if size_bytes != sum(item.size_bytes for item in files):
        raise ModelRegistryError(
            f"{label}.size_bytes {size_bytes} does not equal its file sizes "
            f"{sum(item.size_bytes for item in files)}"
        )
    return ModelEntry(
        id=model_id,
        name=name,
        engine=engine,
        engine_command=command,
        labels=tuple(labels),
        sample_rate=sample_rate,
        size_bytes=size_bytes,
        source_url=source_url,
        license=license_text,
        install_dir=install_dir,
        files=files,
    )


def load_registry(path: Path | None = None) -> Registry:
    """Parse and validate the registry; no files are hashed and no network is used."""
    registry_path = Path(path) if path is not None else runtime_paths().registry_path
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelRegistryError(f"cannot read model registry {registry_path}: {error}") from error
    data = _mapping(payload, "registry")
    version = _integer(data, "schema_version", "registry")
    if version == 1:
        raise ModelRegistryError(
            "model registry schema_version 1 is retired: it assumed a bundled/default "
            f"Demucs entry. Migrate to schema_version {SCHEMA_VERSION} where every model "
            "declares complete file pins (checkpoints and config) and carries no "
            "bundled/default/checkpoint_manifest fields; see analysis/models.json."
        )
    if version != SCHEMA_VERSION:
        raise ModelRegistryError(
            f"unsupported model registry schema_version {version}; expected {SCHEMA_VERSION}"
        )
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ModelRegistryError("registry.models must be a non-empty list")
    entries = tuple(_parse_entry(item, index) for index, item in enumerate(raw_models))
    ids = [entry.id for entry in entries]
    if len(set(ids)) != len(ids):
        raise ModelRegistryError("registry contains duplicate model ids")
    return Registry(schema_version=version, models=entries)


# ---------------------------------------------------------------------------
# verification


def model_directory(entry: ModelEntry, root: Path | None = None) -> Path:
    return (Path(root) if root is not None else runtime_paths().models_root) / entry.install_dir


def _state_for_file(
    *,
    role: str,
    name: str,
    path: Path,
    size: int,
    sha256: str | None,
) -> FileState:
    display = str(path)
    if not path.is_file():
        return FileState(
            role=role,
            name=name,
            path=display,
            status="missing",
            expected_size=size,
            expected_sha256=sha256,
            detail="file is absent",
        )
    actual_size = path.stat().st_size
    if actual_size != size:
        return FileState(
            role=role,
            name=name,
            path=display,
            status="size-mismatch",
            expected_size=size,
            actual_size=actual_size,
            expected_sha256=sha256,
            detail=f"expected {size} bytes, got {actual_size}",
        )
    if sha256 is None:
        return FileState(
            role=role,
            name=name,
            path=display,
            status="ok",
            expected_size=size,
            actual_size=actual_size,
        )
    actual_sha = cached_sha256(path)
    if actual_sha != sha256:
        return FileState(
            role=role,
            name=name,
            path=display,
            status="hash-mismatch",
            expected_size=size,
            actual_size=actual_size,
            expected_sha256=sha256,
            actual_sha256=actual_sha,
            detail="sha256 does not match the registry",
        )
    return FileState(
        role=role,
        name=name,
        path=display,
        status="ok",
        expected_size=size,
        actual_size=actual_size,
        expected_sha256=sha256,
        actual_sha256=actual_sha,
    )


def _downloadable_states(
    entry: ModelEntry, root: Path
) -> tuple[tuple[FileState, ...], tuple[str, ...], list[FileState]]:
    model_dir = model_directory(entry, root)
    expected = {item.name for item in entry.files}
    states = tuple(
        _state_for_file(
            role=item.role,
            name=item.name,
            path=model_dir / item.name,
            size=item.size_bytes,
            sha256=item.sha256,
        )
        for item in entry.files
    )
    extras: list[FileState] = []
    if model_dir.is_dir():
        for child in sorted(model_dir.iterdir()):
            if child.is_file() and child.name not in expected:
                extras.append(
                    FileState(
                        role="extra",
                        name=child.name,
                        path=str(child),
                        status="extra",
                        detail="not declared by the model registry",
                    )
                )
    return states, tuple(sorted(expected)), extras


def verify_model(
    entry: ModelEntry,
    root: Path | None = None,
    *,
    app_root: Path | None = None,
) -> ModelState:
    """Report installed/missing/hash-mismatch for one model without network."""
    runtime = runtime_paths()
    models_root = Path(root) if root is not None else runtime.models_root
    # ``app_root`` is kept for callers from the schema-1 era; weights now always
    # live under models_root and every entry is verified by the same file path.
    _ = app_root
    model_dir = model_directory(entry, models_root)
    try:
        states, expected_names, extras = _downloadable_states(entry, models_root)
    except ModelRegistryError as error:
        return ModelState(
            entry=entry,
            status="missing",
            model_dir=str(model_dir),
            detail=str(error),
        )
    all_states = (*states, *extras)
    missing = [state for state in states if state.status == "missing"]
    broken = [state for state in all_states if state.status not in {"ok", "missing"}]
    if broken:
        status: ModelStatus = "hash-mismatch"
        detail = "; ".join(f"{state.name}: {state.status}" for state in broken[:4])
        if len(broken) > 4:
            detail += f"; +{len(broken) - 4} more"
    elif missing:
        status = "missing"
        detail = (
            "no declared files are present"
            if len(missing) == len(states)
            else "missing " + ", ".join(state.name for state in missing[:4])
        )
    else:
        status = "installed"
        detail = f"{len(expected_names)} files verified"
    return ModelState(
        entry=entry,
        status=status,
        model_dir=str(model_dir),
        files=tuple(all_states),
        detail=detail,
    )


def verify_registry(
    registry: Registry,
    root: Path | None = None,
    *,
    app_root: Path | None = None,
) -> tuple[ModelState, ...]:
    return tuple(verify_model(entry, root, app_root=app_root) for entry in registry.models)


def model_install_command(entry: ModelEntry) -> str:
    return entry.install_command


def expected_labels(entry: ModelEntry) -> tuple[str, ...]:
    """The stem labels the engine must emit, in engine order."""
    return entry.labels


def engine_command(entry: ModelEntry) -> str:
    """The pinned command description for the entry's engine."""
    return entry.engine_command


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ("KiB", "MiB", "GiB", "TiB")
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{size_bytes} B"


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "FileState",
    "MODELS_DIR_NAME",
    "ModelEntry",
    "ModelFile",
    "ModelRegistryError",
    "ModelState",
    "Registry",
    "cached_sha256",
    "clear_digest_cache",
    "engine_command",
    "expected_labels",
    "format_size",
    "load_registry",
    "model_directory",
    "model_install_command",
    "sha256_file",
    "verify_model",
    "verify_registry",
]
