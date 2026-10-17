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
    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
