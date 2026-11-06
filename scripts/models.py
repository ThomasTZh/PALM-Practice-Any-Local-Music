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
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basseparate.config import RuntimePaths  # noqa: E402
from basseparate.model_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    ModelEntry,
    ModelRegistryError,
    ModelState,
    format_size,
    load_registry,
    verify_registry,
)
from basseparate.setup.download import download_file  # noqa: E402
from basseparate.setup.errors import SetupError  # noqa: E402
from basseparate.setup.models import install_model as _install_model  # noqa: E402

Downloader = Callable[[str, Path], None]
CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 120


InstallError = SetupError


def install_model(
    entry: ModelEntry,
    *,
    root: Path = ROOT,
    fetch: Downloader | None = None,
    progress: Callable[[str], None] | None = None,
) -> ModelState:
    """Compatibility wrapper around the shared setup model installer."""
    runtime = RuntimePaths.from_environment(mode="source", app_root=root, data_root=root)

    def report(fraction: float, message: str) -> None:
        if progress is not None:
            progress(message)

    return _install_model(
        entry,
        runtime=runtime,
        fetch=fetch if fetch is not None else download_file,
        progress=report if progress is not None else None,
    )


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
