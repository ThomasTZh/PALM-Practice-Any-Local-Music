"""Command-line interface for basseparate."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        return _cmd_version()
    if args.command == "doctor":
        return _cmd_doctor(args)
    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
