#!/usr/bin/env python3
"""List, verify and install separation models from the pinned registry.

Only ``install`` touches the network. It downloads each file to a ``.part``
file in a private staging directory, checks the declared size and SHA-256,
publishes it atomically inside the staging model directory, then swaps the
whole model directory into place and re-verifies. A failure leaves the previous
model directory (or nothing) instead of a half-installed model.

Examples:
    python scripts/models.py list
    python scripts/models.py verify
    python scripts/models.py verify --require-all
    python scripts/models.py install scnet-xl-ihf
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basseparate.model_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    ModelEntry,
    ModelRegistryError,
    ModelState,
    format_size,
    load_registry,
    model_directory,
    verify_model,
    verify_registry,
)

Downloader = Callable[[str, Path], None]
CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 120


class InstallError(RuntimeError):
    """A model could not be downloaded, verified or published."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, destination: Path) -> None:
    """Stream an HTTPS URL into ``destination`` (normally a .part file)."""
    if not url.startswith("https://"):
        raise InstallError(f"refusing non-HTTPS download: {url}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "basseparate-models/1"})
    try:
        with (
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
            destination.open("wb") as handle,
        ):
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise InstallError(f"download failed for {url}: {error}") from error


def _verify_part(part: Path, *, expected_size: int, expected_sha256: str, name: str) -> None:
    actual_size = part.stat().st_size
    if actual_size != expected_size:
        raise InstallError(f"{name}: expected {expected_size} bytes, downloaded {actual_size}")
    actual_sha = sha256_file(part)
    if actual_sha != expected_sha256:
        raise InstallError(
            f"{name}: sha256 mismatch (expected {expected_sha256}, got {actual_sha})"
        )


def install_model(
    entry: ModelEntry,
    *,
    root: Path = ROOT,
    fetch: Downloader | None = None,
    progress: Callable[[str], None] | None = None,
) -> ModelState:
    """Install one downloadable model with .part files and an atomic directory swap."""
    if entry.bundled:
        raise InstallError(f"{entry.id} is bundled with the checkout; it cannot be downloaded")
    verify = verify_model(entry, root)
    if verify.installed:
        if progress is not None:
            progress(f"{entry.id}: already installed ({verify.detail})")
        return verify
    fetch = fetch if fetch is not None else download_file
    models_root = Path(root) / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{entry.id}.install-", dir=models_root))
    target = model_directory(entry, root)
    backup: Path | None = None
    published = False
    try:
        for model_file in entry.files:
            if progress is not None:
                progress(
                    f"{entry.id}: downloading {model_file.name} "
                    f"({format_size(model_file.size_bytes)})"
                )
            part = staging / f"{model_file.name}.part"
            fetch(model_file.url, part)
            if not part.is_file():
                raise InstallError(f"{model_file.name}: download produced no file")
            _verify_part(
                part,
                expected_size=model_file.size_bytes,
                expected_sha256=model_file.sha256,
                name=model_file.name,
            )
            part.replace(staging / model_file.name)
        if progress is not None:
            progress(f"{entry.id}: published files verified; swapping into place")
        if target.exists():
            backup = models_root / f".{entry.id}.backup-{os.getpid()}"
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            target.replace(backup)
        staging.replace(target)
        published = True
        state = verify_model(entry, root)
        if not state.installed:
            raise InstallError(f"{entry.id}: post-install verification failed: {state.detail}")
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
        if progress is not None:
            progress(f"{entry.id}: installed and verified")
        return state
    except BaseException:
        if published and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup is not None and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _status(label: str, state: ModelState) -> str:
    marker = "ok     " if state.installed else state.status
    return f"  [{marker:12}] {label:22} {state.detail}"


def list_models(states: tuple[ModelState, ...], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps([state.to_dict() for state in states], indent=2, sort_keys=True))
        return 0
    print("separation models (offline status; no network used)")
    for state in states:
        entry = state.entry
        stems = ", ".join(entry.labels)
        install = entry.install_command
        print(
            f"  {entry.id:20} {state.status:13} {len(entry.labels)} stems  "
            f"{entry.engine:7} {format_size(entry.size_bytes):>10}  "
            f"[{stems}]"
        )
        print(f"  {'':20} {entry.name} · {entry.sample_rate} Hz · {install}")
    print("status legend: installed / missing / hash-mismatch")
    return 0


def verify_models(
    states: tuple[ModelState, ...], *, require_all: bool, as_json: bool = False
) -> int:
    if as_json:
        print(json.dumps([state.to_dict() for state in states], indent=2, sort_keys=True))
    else:
        print("separation models (offline verification; no network used)")
        for state in states:
            print(_status(state.entry.id, state))
            for file_state in state.files:
                if not file_state.ok:
                    print(f"      {file_state.role:10} {file_state.name}: {file_state.status}")
    broken = [state for state in states if state.status == "hash-mismatch"]
    missing = [state for state in states if state.status == "missing"]
    if broken:
        print(
            "models-verify: hash mismatch: " + ", ".join(state.entry.id for state in broken),
            file=sys.stderr,
        )
        return 1
    if require_all and missing:
        print(
            "models-verify: missing: " + ", ".join(state.entry.id for state in missing),
            file=sys.stderr,
        )
        return 1
    print("models-verify: installed models are intact")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="print model status without network")
    listing.add_argument("--json", action="store_true")
    verify = sub.add_parser("verify", help="verify installed files without network")
    verify.add_argument("--json", action="store_true")
    verify.add_argument(
        "--require-all",
        action="store_true",
        help="fail when a registry model is not installed",
    )
    install = sub.add_parser("install", help="download, verify and publish a model")
    install.add_argument("model_ids", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        registry = load_registry(args.registry)
    except ModelRegistryError as error:
        print(f"models: {error}", file=sys.stderr)
        return 2
    if args.command == "list":
        return list_models(verify_registry(registry, args.root), as_json=args.json)
    if args.command == "verify":
        return verify_models(
            verify_registry(registry, args.root),
            require_all=args.require_all,
            as_json=args.json,
        )
    if args.command == "install":
        failures = 0
        for model_id in args.model_ids:
            try:
                entry = registry.get(model_id)
                install_model(entry, root=args.root, progress=print)
            except (ModelRegistryError, InstallError) as error:
                print(f"models-install: {model_id}: {error}", file=sys.stderr)
                failures += 1
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
