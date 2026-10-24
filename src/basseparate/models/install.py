"""Explicit model-install boundary for separately installed models (M3.2 §4.3).

The network-facing install service is deliberately separate from the
inference workers. It performs one explicit, cancellable, hash-verifying
installation into a managed model store:

1. Refuse online installation while offline mode is active.
2. Stream to a staging file, hashing while downloading.
3. Verify the exact size and SHA-256 against the checked-in registry.
4. Publish atomically into the managed store and record provenance.

Offline bundle import (§4.4) uses the same verification and publication
path without any network access. The service contains no torch or
beat_this imports; qualification and inference run in the isolated
rhythm environment.

Durable job/worker wiring, API routes, and the settings UI are added by
later milestones (M3.17); this module is the reusable boundary they call.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from basseparate.models.rhythm_registry import RhythmModelManifest

#: Download/read chunk size (1 MiB).
CHUNK_BYTES = 1 << 20

#: Free-space margin required beyond the checkpoint size.
SPACE_MARGIN_BYTES = 64 << 20

_STAGING_DIR = ".staging"
_RECORD_NAME = "installed.json"

#: ``(downloaded_bytes, total_bytes_or_none)``.
ProgressCallback = Callable[[int, int | None], None]
#: Return True when the caller wants the operation cancelled.
CancelCheck = Callable[[], bool]
#: Injectable URL opener for tests; must return a response with read/close.
UrlOpener = Callable[[str], Any]


class ModelInstallError(RuntimeError):
    """Base class for explicit model-install failures."""


class OfflineModeError(ModelInstallError):
    """Online model installation was requested while offline mode is active."""


class DownloadCancelledError(ModelInstallError):
    """The user cancelled an in-progress model download."""


class ModelDownloadError(ModelInstallError):
    """The download failed or delivered an unexpected number of bytes."""


class HashMismatchError(ModelInstallError):
    """The downloaded or imported artifact does not match the registry hash."""


class ModelNotInstalledError(ModelInstallError):
    """The requested model is not present in the managed store."""


class OfflineBundleError(ModelInstallError):
    """An offline model bundle is missing or its identity does not match."""


@dataclass(frozen=True, slots=True)
class InstalledModel:
    """A verified model checkpoint in the managed store."""

    model_id: str
    checkpoint_path: Path
    size_bytes: int
    sha256: str
    installed_at: str
    source: str
    adapter_version: str
    license_notice: str


def sha256_file(path: Path) -> str:
    """Compute a file's SHA-256 with bounded memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _urlopen(url: str) -> Any:
    return urllib.request.urlopen(url, timeout=60)  # noqa: S310 - registry-pinned HTTPS URL


class ModelStore:
    """Managed on-disk store for separately installed model checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def staging_dir(self) -> Path:
        return self.root / _STAGING_DIR

    def model_dir(self, manifest: RhythmModelManifest) -> Path:
        return self.root / manifest.model_id

    def checkpoint_path(self, manifest: RhythmModelManifest) -> Path:
        return self.model_dir(manifest) / manifest.checkpoint.filename

    def record_path(self, manifest: RhythmModelManifest) -> Path:
        return self.model_dir(manifest) / _RECORD_NAME

    def installed_record(self, manifest: RhythmModelManifest) -> dict[str, Any] | None:
        path = self.record_path(manifest)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def is_installed(self, manifest: RhythmModelManifest, *, verify_hash: bool = False) -> bool:
        """Whether the checkpoint is present (optionally hash-verified)."""
        path = self.checkpoint_path(manifest)
        if not path.is_file():
            return False
        if path.stat().st_size != manifest.checkpoint.size_bytes:
            return False
        if not verify_hash:
            return True
        return sha256_file(path) == manifest.checkpoint.sha256

    def resolve_checkpoint(self, manifest: RhythmModelManifest) -> Path:
        """Return the verified checkpoint path or raise ModelNotInstalledError."""
        path = self.checkpoint_path(manifest)
        if not path.is_file():
            raise ModelNotInstalledError(
                f"{manifest.model_id} is not installed; install it explicitly or "
                "import a verified offline bundle"
            )
        size = path.stat().st_size
        if size != manifest.checkpoint.size_bytes:
            raise HashMismatchError(
                f"{manifest.model_id} checkpoint size mismatch: expected "
                f"{manifest.checkpoint.size_bytes}, found {size}"
            )
        digest = sha256_file(path)
        if digest != manifest.checkpoint.sha256:
            raise HashMismatchError(
                f"{manifest.model_id} checkpoint hash mismatch: expected "
                f"{manifest.checkpoint.sha256}, found {digest}"
            )
        return path

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        with _suppress_oserror():
            self.root.chmod(0o700)
        with _suppress_oserror():
            self.staging_dir.chmod(0o700)

    def _publish(
        self,
        manifest: RhythmModelManifest,
        staged: Path,
        *,
        source: str,
        bundle_manifest: dict[str, Any] | None = None,
    ) -> InstalledModel:
        model_dir = self.model_dir(manifest)
        model_dir.mkdir(parents=True, exist_ok=True)
        with _suppress_oserror():
            model_dir.chmod(0o700)
        destination = self.checkpoint_path(manifest)
        staged.replace(destination)
        with _suppress_oserror():
            destination.chmod(0o600)

        installed_at = _now_z()
        record: dict[str, Any] = {
            "model_id": manifest.model_id,
            "display_name": manifest.display_name,
            "preset": manifest.preset,
            "upstream_repository": manifest.upstream_repository,
            "upstream_revision": manifest.upstream_revision,
            "package_name": manifest.package_name,
            "package_version": manifest.package_version,
            "adapter_version": manifest.adapter_version,
            "preprocessing_profile": manifest.preprocessing_profile,
            "preprocessing_version": manifest.preprocessing_version,
            "checkpoint": {
                "filename": manifest.checkpoint.filename,
                "size_bytes": manifest.checkpoint.size_bytes,
                "sha256": manifest.checkpoint.sha256,
                "upstream_url": manifest.checkpoint.upstream_url,
            },
            "installed_at": installed_at,
            "source": source,
            "license_notice": manifest.license_notice,
            "notices": list(manifest.notices),
        }
        if bundle_manifest is not None:
            record["bundle_manifest"] = bundle_manifest
        tmp = self.record_path(manifest).with_name(_RECORD_NAME + ".tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with _suppress_oserror():
            tmp.chmod(0o600)
        tmp.replace(self.record_path(manifest))
        return InstalledModel(
            model_id=manifest.model_id,
            checkpoint_path=destination,
            size_bytes=manifest.checkpoint.size_bytes,
            sha256=manifest.checkpoint.sha256,
            installed_at=installed_at,
            source=source,
            adapter_version=manifest.adapter_version,
            license_notice=manifest.license_notice,
        )


class _suppress_oserror:
    """Tiny context manager: ignore chmod failures on unusual filesystems."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return isinstance(exc, OSError)


def _check_space(root: Path, required: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if free < required + SPACE_MARGIN_BYTES:
        raise ModelInstallError(
            f"insufficient free space: need {required + SPACE_MARGIN_BYTES} bytes, have {free}"
        )


def _stream_to_staging(
    response: Any,
    staged: Path,
    manifest: RhythmModelManifest,
    progress: ProgressCallback | None,
    cancel: CancelCheck | None,
) -> None:
    total = manifest.checkpoint.size_bytes
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with open(staged, "wb") as handle:
            while True:
                if cancel is not None and cancel():
                    raise DownloadCancelledError("model download cancelled")
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > total:
                    raise ModelDownloadError(f"download exceeded the expected {total} bytes")
                handle.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(downloaded, total)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    if downloaded != total:
        raise ModelDownloadError(
            f"download size mismatch: expected {total} bytes, received {downloaded}"
        )
    actual = digest.hexdigest()
    if actual != manifest.checkpoint.sha256:
        raise HashMismatchError(
            f"{manifest.model_id} download hash mismatch: expected "
            f"{manifest.checkpoint.sha256}, received {actual}"
        )
    with _suppress_oserror():
        staged.chmod(0o600)


def install_from_download(
    manifest: RhythmModelManifest,
    store: ModelStore,
    *,
    offline_mode: bool,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    opener: UrlOpener | None = None,
) -> InstalledModel:
    """Download, verify, and atomically publish one model checkpoint.

    Raises OfflineModeError before any network access when offline mode is
    active. The staged file is removed on every failure path.
    """
    if offline_mode:
        raise OfflineModeError(
            "model installation is disabled while offline mode is active; "
            "disable offline mode explicitly to install"
        )
    store._prepare()
    _check_space(store.root, manifest.checkpoint.size_bytes)
    staged = store.staging_dir / f"{manifest.model_id}-{uuid.uuid4().hex}.part"
    open_url = opener or _urlopen
    try:
        try:
            response = open_url(manifest.checkpoint.upstream_url)
        except Exception as exc:
            raise ModelDownloadError(
                f"cannot download {manifest.checkpoint.filename}: {exc}"
            ) from exc
        _stream_to_staging(response, staged, manifest, progress, cancel)
        return store._publish(manifest, staged, source="download")
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _read_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / "manifest.json"
    if not path.is_file():
        raise OfflineBundleError(f"offline bundle manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OfflineBundleError(f"cannot read offline bundle manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise OfflineBundleError("offline bundle manifest must be a JSON object")
    return data


def install_from_bundle(
    manifest: RhythmModelManifest,
    store: ModelStore,
    bundle_dir: Path,
    *,
    progress: ProgressCallback | None = None,
) -> InstalledModel:
    """Install a verified offline bundle (§4.4).

    The bundle manifest must identify the same registered model, checkpoint
    file, size, and SHA-256. The checkpoint is hashed again while copying;
    the bundle manifest alone is never trusted as proof of integrity.
    """
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise OfflineBundleError(f"offline bundle directory not found: {bundle_dir}")
    bundle = _read_bundle_manifest(bundle_dir)
    if bundle.get("model_id") != manifest.model_id:
        raise OfflineBundleError(
            f"bundle model_id {bundle.get('model_id')!r} does not match {manifest.model_id!r}"
        )
    filename = bundle.get("checkpoint_filename")
    if filename != manifest.checkpoint.filename:
        raise OfflineBundleError(
            f"bundle checkpoint filename {filename!r} does not match the registry"
        )
    if bundle.get("size_bytes") != manifest.checkpoint.size_bytes:
        raise OfflineBundleError("bundle checkpoint size does not match the registry")
    if bundle.get("sha256") != manifest.checkpoint.sha256:
        raise OfflineBundleError("bundle checkpoint hash does not match the registry")

    source = bundle_dir / manifest.checkpoint.filename
    if not source.is_file():
        raise OfflineBundleError(f"bundle checkpoint not found: {source}")
    store._prepare()
    staged = store.staging_dir / f"{manifest.model_id}-{uuid.uuid4().hex}.part"
    total = manifest.checkpoint.size_bytes
    digest = hashlib.sha256()
    copied = 0
    try:
        with open(source, "rb") as reader, open(staged, "wb") as writer:
            while chunk := reader.read(CHUNK_BYTES):
                copied += len(chunk)
                if copied > total:
                    raise OfflineBundleError("bundle checkpoint exceeds its registered size")
                writer.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(copied, total)
            writer.flush()
            os.fsync(writer.fileno())
        if copied != total:
            raise OfflineBundleError(
                f"bundle checkpoint size mismatch: expected {total}, found {copied}"
            )
        actual = digest.hexdigest()
        if actual != manifest.checkpoint.sha256:
            raise OfflineBundleError(
                f"bundle checkpoint hash mismatch: expected "
                f"{manifest.checkpoint.sha256}, found {actual}"
            )
        with _suppress_oserror():
            staged.chmod(0o600)
        return store._publish(manifest, staged, source="bundle", bundle_manifest=bundle)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
