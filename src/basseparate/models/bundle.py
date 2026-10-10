"""Verification, import, and provenance for the bundled model baseline.

Implements spec §5.3 (provisioning workflow), §5.4 (local bundle import),
and the file/hash pre-checks of §5.5 (no implicit retrieval). Pure
standard library: the main environment never imports torch or demucs.

State model (§5.3.5): a bundle directory is ``bundled_available`` when every
manifested artifact is present with the exact size and SHA-256;
``bundled_missing`` when any artifact is absent; ``bundled_corrupt`` when
everything is present but at least one size/hash mismatches. The report
carries the per-artifact detail so mixed cases lose no information.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from basseparate.models.registry import ModelManifest, get_manifest

BundleState = Literal["available", "missing", "corrupt"]

MODEL_STORE_VERSION = 1

# File extensions that must never appear in a model bundle (§5.4.6): a bundle
# is a strict set of data artifacts, and anything executable is rejected.
_EXECUTABLE_EXTENSIONS = frozenset(
    {".py", ".so", ".dylib", ".dll", ".exe", ".sh", ".bat", ".cmd", ".js", ".c", ".o"}
)

_HASH_CHUNK_SIZE = 2**20


class BundleError(RuntimeError):
    """Raised when a bundle import is refused or fails verification."""


@dataclass(frozen=True, slots=True)
class BundleReport:
    """The verification outcome for one model directory."""

    model_id: str
    state: BundleState
    missing: tuple[str, ...]
    corrupt: tuple[str, ...]

    @property
    def is_available(self) -> bool:
        return self.state == "available"

    def describe(self) -> str:
        if self.state == "available":
            return "bundled_available"
        parts = [f"bundled_{self.state}"]
        if self.missing:
            parts.append("missing: " + ", ".join(self.missing))
        if self.corrupt:
            parts.append("corrupt: " + ", ".join(self.corrupt))
        return "; ".join(parts)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(model_dir: Path, manifest: ModelManifest) -> BundleReport:
    """Check every manifested artifact against size and SHA-256.

    A missing directory counts as every artifact missing. Missing artifacts
    take precedence in the state; the report lists both missing and corrupt
    artifacts.
    """
    if not model_dir.is_dir():
        return BundleReport(
            model_id=manifest.model_id,
            state="missing",
            missing=tuple(spec.name for spec in manifest.artifacts),
            corrupt=(),
        )
    missing: list[str] = []
    corrupt: list[str] = []
    for spec in manifest.artifacts:
        path = model_dir / spec.name
        if not path.is_file():
            missing.append(spec.name)
            continue
        if path.stat().st_size != spec.size_bytes:
            corrupt.append(spec.name)
            continue
        if sha256_of(path) != spec.sha256:
            corrupt.append(spec.name)
    if missing:
        state: BundleState = "missing"
    elif corrupt:
        state = "corrupt"
    else:
        state = "available"
    return BundleReport(
        model_id=manifest.model_id,
        state=state,
        missing=tuple(missing),
        corrupt=tuple(corrupt),
    )


def default_bundle_root() -> Path:
    """The development-workspace bundle root (the repo root).

    The manifest's ``bundle_prefix`` is bundle-relative: in the development
    workspace it resolves against the repo root (whose ``models/`` directory
    is git-ignored and holds developer-provisioned artifacts); in a release
    install it resolves against the install root. Release and repair paths
    pass an explicit directory to the same functions.
    """
    return Path(__file__).resolve().parents[3]


def default_bundle_dir(manifest: ModelManifest) -> Path:
    return default_bundle_root() / manifest.bundle_prefix


def import_local_bundle(
    bundle_dir: Path,
    target_dir: Path,
    manifest: ModelManifest,
) -> BundleReport:
    """Provision/repair a model directory from a local bundle (§5.4).

    The source bundle must verify fully against the manifest. The file set
    is strict: any file not in the manifest is refused, and executable
    extensions are refused even before the manifest check. Artifacts are
    copied by name, then the *target* is verified against the same manifest
    (§5.3.4); on failure the copied files are removed and ``BundleError`` is
    raised. No network access is performed.
    """
    if not bundle_dir.is_dir():
        raise BundleError(f"source bundle {bundle_dir} is not a directory")

    names = {spec.name for spec in manifest.artifacts}
    for entry in sorted(bundle_dir.iterdir()):
        if not entry.is_file():
            continue  # nested directories are ignored; only files are vetted
        if entry.suffix.lower() in _EXECUTABLE_EXTENSIONS:
            raise BundleError(f"bundle contains an executable file: {entry.name}")
        if entry.name not in names:
            raise BundleError(f"bundle contains a file not in the manifest: {entry.name}")

    source_report = verify_bundle(bundle_dir, manifest)
    if not source_report.is_available:
        raise BundleError(f"source bundle does not verify: {source_report.describe()}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    try:
        for spec in manifest.artifacts:
            destination = target_dir / spec.name
            shutil.copy2(bundle_dir / spec.name, destination)
            copied.append(destination)
    except OSError as exc:
        _remove_all(copied)
        raise BundleError(f"copying the bundle failed: {exc}") from exc

    target_report = verify_bundle(target_dir, manifest)
    if not target_report.is_available:
        _remove_all(copied)
        raise BundleError(f"packaged copy does not verify: {target_report.describe()}")
    return target_report


def _remove_all(paths: list[Path]) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink()


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Bundled provenance + qualification status (§5.3.8).

    Written when a bundle is provisioned (developer download or local
    import) and when the offline qualification runs; Milestone 7 displays it
    in the unified model manager.
    """

    model_id: str
    provisioned_at: str
    source: str
    artifact_hashes: dict[str, str]
    qualification_status: str
    qualification_detail: str | None = None


class ProvenanceStore:
    """JSON persistence of provenance records under the data directory.

    Same pattern as ``QualificationStore``: a missing file means "nothing
    provisioned yet" and is never an error.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, ProvenanceRecord]:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BundleError(f"cannot read model store {self._path}: {exc}") from exc
        if not isinstance(document, dict) or document.get("version") != MODEL_STORE_VERSION:
            raise BundleError(
                f"model store {self._path} has unsupported version (expected {MODEL_STORE_VERSION})"
            )
        records: dict[str, ProvenanceRecord] = {}
        raw_models = document.get("models", {})
        if not isinstance(raw_models, dict):
            raise BundleError(f"model store {self._path} is malformed")
        for model_id, raw in raw_models.items():
            if not isinstance(raw, dict):
                raise BundleError(f"model store entry {model_id!r} is malformed")
            hashes = raw.get("artifact_hashes", {})
            if not isinstance(hashes, dict):
                raise BundleError(f"model store entry {model_id!r} is malformed")
            records[str(model_id)] = ProvenanceRecord(
                model_id=str(model_id),
                provisioned_at=str(raw.get("provisioned_at", "")),
                source=str(raw.get("source", "")),
                artifact_hashes={str(k): str(v) for k, v in hashes.items()},
                qualification_status=str(raw.get("qualification_status", "not-qualified")),
                qualification_detail=raw.get("qualification_detail"),
            )
        return records

    def save(self, records: dict[str, ProvenanceRecord]) -> None:
        document = {
            "version": MODEL_STORE_VERSION,
            "models": {
                model_id: {
                    "provisioned_at": record.provisioned_at,
                    "source": record.source,
                    "artifact_hashes": dict(sorted(record.artifact_hashes.items())),
                    "qualification_status": record.qualification_status,
                    "qualification_detail": record.qualification_detail,
                }
                for model_id, record in sorted(records.items())
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self._path)


def record_provisioning(
    store: ProvenanceStore,
    manifest: ModelManifest | None = None,
    *,
    model_id: str | None = None,
    source: str,
    now: datetime | None = None,
) -> ProvenanceRecord:
    """Record that a bundle was provisioned, resetting its qualification.

    The manifest (or an explicit model id) supplies the artifact hashes from
    the registry — the on-disk bytes were just verified by the caller.
    """
    if manifest is None:
        if model_id is None:
            raise BundleError("record_provisioning needs a manifest or a model_id")
        manifest = get_manifest(model_id)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    record = ProvenanceRecord(
        model_id=manifest.model_id,
        provisioned_at=timestamp,
        source=source,
        artifact_hashes={spec.name: spec.sha256 for spec in manifest.artifacts},
        qualification_status="not-qualified",
        qualification_detail=None,
    )
    records = store.load()
    records[manifest.model_id] = record
    store.save(records)
    return record


def record_qualification(
    store: ProvenanceStore,
    model_id: str,
    passed: bool,
    detail: str,
    now: datetime | None = None,
) -> ProvenanceRecord:
    """Update the qualification status of a provisioned model.

    If the model has no provenance record yet, one is created with an
    unknown source so a qualification run is never silently dropped.
    """
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    records = store.load()
    existing = records.get(model_id)
    if existing is None:
        try:
            hashes = {spec.name: spec.sha256 for spec in get_manifest(model_id).artifacts}
            proven_at = timestamp
            source = "unrecorded"
        except KeyError:
            hashes = {}
            proven_at = timestamp
            source = "unrecorded"
    else:
        hashes = dict(existing.artifact_hashes)
        proven_at = existing.provisioned_at
        source = existing.source
    record = ProvenanceRecord(
        model_id=model_id,
        provisioned_at=proven_at,
        source=source,
        artifact_hashes=hashes,
        qualification_status="qualified" if passed else "failed",
        qualification_detail=detail,
    )
    records[model_id] = record
    store.save(records)
    return record
