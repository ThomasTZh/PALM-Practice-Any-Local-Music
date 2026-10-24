"""Command-line interface for basseparate."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from basseparate import (
    API_VERSION,
    APP_VERSION,
    DATABASE_SCHEMA_VERSION,
    PROJECT_SCHEMA_VERSION,
    WORKER_PROTOCOL_VERSION,
)
from basseparate.config import ConfigError, resolve_config
from basseparate.diagnostics import exit_code_for, format_report, run_diagnostics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="basseparate",
        description="Local music-analysis and bass practice application.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="print application and contract versions")

    doctor = subparsers.add_parser("doctor", help="report environment readiness")
    doctor.add_argument(
        "--storage-root",
        default=None,
        help="explicit storage root (all categories placed beneath it)",
    )

    subparsers.add_parser(
        "worker-probe",
        help="run the model-free worker probe (handshake, ping, shutdown)",
    )

    serve = subparsers.add_parser("serve", help="start the local backend and open the browser")
    serve.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab; print the bootstrap URL instead",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="loopback port to bind (default 8765)",
    )
    serve.add_argument(
        "--storage-root",
        default=None,
        help="explicit storage root (all categories placed beneath it)",
    )
    serve.add_argument(
        "--media-worker-memory-limit-mb",
        type=int,
        default=None,
        help="address-space limit for the media worker subprocess (default 4096)",
    )

    models = subparsers.add_parser(
        "models", help="manage separately installed rhythm models"
    )
    model_sub = models.add_subparsers(dest="models_command", required=True)
    list_models = model_sub.add_parser("list", help="list registered rhythm models")
    install = model_sub.add_parser(
        "install",
        help="explicitly download and install a model (requires offline mode off)",
    )
    install.add_argument("model_id", help="registered model ID")
    install.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation prompt",
    )
    verify = model_sub.add_parser("verify", help="verify an installed checkpoint")
    verify.add_argument("model_id", help="registered model ID")
    import_bundle = model_sub.add_parser(
        "import-bundle", help="install a verified offline model bundle"
    )
    import_bundle.add_argument("model_id", help="registered model ID")
    import_bundle.add_argument("bundle_dir", help="directory with manifest.json + checkpoint")
    for sub in (list_models, install, verify, import_bundle):
        sub.add_argument(
            "--storage-root",
            default=None,
            help="explicit storage root (all categories placed beneath it)",
        )
    return parser


def _cmd_version() -> int:
    print(f"basseparate {APP_VERSION}")
    print(
        f"api v{API_VERSION} | database schema v{DATABASE_SCHEMA_VERSION} | "
        f"project schema v{PROJECT_SCHEMA_VERSION} | "
        f"worker protocol v{WORKER_PROTOCOL_VERSION}"
    )
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    try:
        config = resolve_config(cli={"storage_root": args.storage_root})
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    checks = run_diagnostics(config)
    print(format_report(checks))
    return exit_code_for(checks)


def _cmd_worker_probe() -> int:
    from basseparate.worker import (
        CapabilitiesMessage,
        WorkerSupervisor,
        WorkerSupervisorError,
        make_describe,
    )

    try:
        with WorkerSupervisor(cwd=Path.cwd()) as sup:
            hello = sup.wait_for_handshake()
            print(
                f"handshake ok: worker={hello.payload.worker} "
                f"protocol v{hello.payload.protocol_version}"
            )
            sup.send(make_describe())
            caps = sup.receive(timeout=5.0)
            if not isinstance(caps, CapabilitiesMessage):
                raise WorkerSupervisorError(f"expected capabilities, got {caps.type!r}")
            for cap in caps.payload.capabilities:
                print(f"capability: {cap.id} — {cap.description}")
            sup.ping()
            print("ping ok")
            sup.shutdown()
            print("shutdown ok")
    except WorkerSupervisorError as exc:
        print(f"worker probe failed: {exc}", file=sys.stderr)
        return 1
    print("worker probe passed")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from basseparate.serve import ServeError, run_server

    try:
        config = resolve_config(
            cli={
                "port": args.port,
                "storage_root": args.storage_root,
                "open_browser": not args.no_browser,
                "media_worker_memory_limit_mb": args.media_worker_memory_limit_mb,
            }
        )
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        return run_server(config)
    except ServeError as exc:
        print(f"serve error: {exc}", file=sys.stderr)
        return 1


def _cmd_models(args: argparse.Namespace) -> int:
    from basseparate.models import (
        ModelInstallError,
        ModelStore,
        get_rhythm_model,
        install_from_bundle,
        install_from_download,
        list_rhythm_models,
    )
    from basseparate.storage.paths import resolve_storage_paths

    try:
        config = resolve_config(cli={"storage_root": args.storage_root})
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    store = ModelStore(resolve_storage_paths(config.storage_root).data / "models")

    if args.models_command == "list":
        for manifest in list_rhythm_models():
            install_state = (
                "installed" if store.is_installed(manifest) else "not installed"
            )
            size_mb = manifest.checkpoint.size_bytes / (1024 * 1024)
            print(
                f"{manifest.model_id}  {size_mb:.1f} MiB  {install_state}  "
                f"({manifest.display_name})"
            )
        return 0

    try:
        manifest = get_rhythm_model(args.model_id)
    except KeyError as exc:
        print(f"unknown model: {exc.args[0]}", file=sys.stderr)
        return 2

    if args.models_command == "verify":
        try:
            path = store.resolve_checkpoint(manifest)
        except ModelInstallError as exc:
            print(f"verify failed: {exc}", file=sys.stderr)
            return 1
        print(f"ok: {manifest.model_id} {manifest.checkpoint.sha256} ({path})")
        return 0

    if args.models_command == "import-bundle":
        try:
            installed_model = install_from_bundle(
                manifest, store, Path(args.bundle_dir)
            )
        except ModelInstallError as exc:
            print(f"import failed: {exc}", file=sys.stderr)
            return 1
        print(f"installed offline bundle: {installed_model.checkpoint_path}")
        print(f"source: {installed_model.source}; verified sha256: {installed_model.sha256}")
        return 0

    # install
    if store.is_installed(manifest, verify_hash=True):
        print(f"{manifest.model_id} is already installed and hash-verified")
        return 0
    print(f"Model: {manifest.display_name}")
    print(f"Download: {manifest.checkpoint.size_bytes} bytes from the official source")
    print(f"License: {manifest.license_notice}")
    if config.offline_mode:
        print(
            "offline mode is active; disable it explicitly (for example "
            "BASSEPARATE_OFFLINE_MODE=false) before installing",
            file=sys.stderr,
        )
        return 1
    if not args.yes:
        answer = input("Type 'install' to confirm the download: ").strip()
        if answer != "install":
            print("aborted")
            return 1

    last_percent = -10

    def progress(downloaded: int, total: int | None) -> None:
        nonlocal last_percent
        if not total:
            return
        percent = downloaded * 100 // total
        if percent >= last_percent + 10:
            print(f"  {percent}% ({downloaded}/{total} bytes)")
            last_percent = percent

    try:
        installed_model = install_from_download(
            manifest, store, offline_mode=False, progress=progress
        )
    except ModelInstallError as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed: {installed_model.checkpoint_path}")
    print(f"sha256: {installed_model.sha256}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        return _cmd_version()
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "worker-probe":
        return _cmd_worker_probe()
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "models":
        return _cmd_models(args)
    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
