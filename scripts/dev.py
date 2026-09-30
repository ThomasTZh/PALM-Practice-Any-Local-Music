#!/usr/bin/env python3
"""Development wrapper for basseparate (M0.10).

Exposes:
    dev.py setup            install locked dependencies (network-capable)
    dev.py dev              start backend and Vite, stop both together
    dev.py build            build frontend and Python distribution
    dev.py check            non-mutating formatting, lint, typing, contracts
    dev.py test             Python and frontend unit/integration tests
    dev.py test-browser     Playwright browser tests
    dev.py contracts        regenerate contract artifacts
    dev.py contracts --check  check contracts without regenerating
    dev.py licenses         regenerate dependency inventory
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def _pnpm() -> str:
    pnpm = os.environ.get("PNPM_BIN", "pnpm")
    return pnpm


def _run(cmd: Sequence[str], *, check: bool = True, **kwargs: object) -> int:
    printable = " ".join(str(c) for c in cmd)
    print(f"$ {printable}", file=sys.stderr)
    result = subprocess.run([str(c) for c in cmd], cwd=str(ROOT), **kwargs)  # type: ignore[arg-type]
    if check and result.returncode != 0:
        print(f"command failed ({result.returncode}): {printable}", file=sys.stderr)
    return result.returncode


def cmd_setup(_args: argparse.Namespace) -> int:
    rc = _run(["uv", "sync", "--locked"])
    if rc != 0:
        return rc
    rc = _run([_pnpm(), "install", "--frozen-lockfile"])
    if rc != 0:
        return rc
    print("setup complete", file=sys.stderr)
    return 0


def cmd_dev(_args: argparse.Namespace) -> int:
    vite = subprocess.Popen(
        [_pnpm(), "--dir", str(FRONTEND), "run", "dev"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    backend = subprocess.Popen(
        [sys.executable, "-m", "basseparate.cli", "serve", "--no-browser"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def _shutdown(signum: int, _frame: object) -> None:
        for proc in (vite, backend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (vite, backend):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while vite.poll() is None and backend.poll() is None:
            time.sleep(0.5)
        for proc in (vite, backend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (vite, backend):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if vite.returncode is not None and vite.returncode != 0:
            return vite.returncode
        if backend.returncode is not None and backend.returncode != 0:
            return backend.returncode
        return 0
    except KeyboardInterrupt:
        for proc in (vite, backend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (vite, backend):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        return 0


def cmd_build(_args: argparse.Namespace) -> int:
    rc = _run([_pnpm(), "--dir", str(FRONTEND), "run", "build"])
    if rc != 0:
        return rc
    rc = _run(["uv", "build"])
    if rc != 0:
        return rc
    print("build complete", file=sys.stderr)
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    rc = _run(["uv", "run", "--locked", "ruff", "check", "src", "tests"])
    if rc != 0:
        return rc
    rc = _run(["uv", "run", "--locked", "ruff", "format", "--check", "src", "tests"])
    if rc != 0:
        return rc
    rc = _run(["uv", "run", "--locked", "mypy"])
    if rc != 0:
        return rc
    rc = _run(["uv", "run", "--locked", "python", "scripts/check_contract.py"])
    if rc != 0:
        return rc
    rc = _run([_pnpm(), "--dir", str(FRONTEND), "run", "typecheck"])
    if rc != 0:
        return rc
    rc = _run([_pnpm(), "--dir", str(FRONTEND), "run", "lint"])
    if rc != 0:
        return rc
    print("all checks passed", file=sys.stderr)
    return 0


def cmd_test(_args: argparse.Namespace) -> int:
    rc = _run(["uv", "run", "--locked", "pytest", "tests/unit", "-q"])
    if rc != 0:
        return rc
    rc = _run([_pnpm(), "--dir", str(FRONTEND), "run", "test"])
    if rc != 0:
        return rc
    print("all tests passed", file=sys.stderr)
    return 0


def cmd_test_browser(_args: argparse.Namespace) -> int:
    return _run([_pnpm(), "--dir", str(FRONTEND), "exec", "playwright", "test"])


def cmd_contracts(args: argparse.Namespace) -> int:
    if args.check:
        return _run(["uv", "run", "--locked", "python", "scripts/check_contract.py"])
    rc = _run(["uv", "run", "--locked", "python", "scripts/export_openapi.py"])
    if rc != 0:
        return rc
    rc = _run([_pnpm(), "--dir", str(FRONTEND), "run", "contracts"])
    if rc != 0:
        return rc
    print("contracts regenerated", file=sys.stderr)
    return 0


def cmd_licenses(_args: argparse.Namespace) -> int:
    return _run(["uv", "run", "--locked", "python", "scripts/generate_licenses.py"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev.py",
        description="basseparate development wrapper",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="install locked dependencies")
    subparsers.add_parser("dev", help="start backend and Vite, stop both together")
    subparsers.add_parser("build", help="build frontend and Python distribution")
    subparsers.add_parser("check", help="run formatting, lint, typing, contract checks")
    subparsers.add_parser("test", help="run Python and frontend unit tests")
    subparsers.add_parser("test-browser", help="run Playwright browser tests")

    contracts = subparsers.add_parser("contracts", help="regenerate contract artifacts")
    contracts.add_argument(
        "--check",
        action="store_true",
        help="check contracts without regenerating",
    )

    subparsers.add_parser("licenses", help="regenerate dependency inventory")

    args = parser.parse_args(argv)

    handlers = {
        "setup": cmd_setup,
        "dev": cmd_dev,
        "build": cmd_build,
        "check": cmd_check,
        "test": cmd_test,
        "test-browser": cmd_test_browser,
        "contracts": cmd_contracts,
        "licenses": cmd_licenses,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
