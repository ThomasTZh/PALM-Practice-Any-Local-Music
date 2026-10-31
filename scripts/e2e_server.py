#!/usr/bin/env python3
"""Start the real studio server for Playwright with an isolated data root.

The Playwright config launches this script as its ``webServer``. Every run gets
a fresh data directory under the system temp area, so imports, projects,
analysis caches and exports cannot leak between runs or touch the user's real
studio data. The built UI is served from ``web/dist``; run ``make build-web``
first (``make e2e`` does it for you).
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.environ.get("BASSEPARATE_E2E_HOST", DEFAULT_HOST),
        help=f"loopback host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BASSEPARATE_E2E_PORT", DEFAULT_PORT)),
        help=f"port to bind, 0 picks a free port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="explicit data root; default: a fresh temp directory per run",
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=ROOT / "web" / "dist",
        help="built UI directory (default: web/dist)",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="keep the generated data root (debugging); implies no cleanup",
    )
    return parser.parse_args(argv)


def bound_port(host: str, port: int) -> int:
    """Return a concrete free port for ``port`` (0 asks the kernel)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as error:
            raise SystemExit(f"e2e-server: cannot bind {host}:{port}: {error}") from error
        return int(probe.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    web_dir = Path(args.web_dir).resolve()
    if not (web_dir / "index.html").is_file():
        print(
            f"e2e-server: no built UI at {web_dir}; run `make build-web` first",
            file=sys.stderr,
            flush=True,
        )
        return 1

    generated = args.data_root is None
    data_root = (
        Path(tempfile.mkdtemp(prefix="basseparate-e2e-")).resolve()
        if generated
        else Path(args.data_root).resolve()
    )
    data_root.mkdir(parents=True, exist_ok=True)
    port = bound_port(str(args.host), int(args.port))

    sys.path.insert(0, str(SRC))
    import uvicorn

    from basseparate.app import create_app
    from basseparate.config import Settings

    settings = Settings(data_dir=data_root, web_dir=web_dir)
    application = create_app(settings)
    print(f"e2e-server: data root {data_root}", flush=True)
    print(f"e2e-server: listening on http://{args.host}:{port}/", flush=True)

    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host=str(args.host),
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    try:
        server.run()
    finally:
        if generated and not args.keep_data:
            shutil.rmtree(data_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
