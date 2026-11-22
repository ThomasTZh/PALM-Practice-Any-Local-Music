"""Command line entry point: ``basseparate serve``.

The server binds 127.0.0.1 only. ``--port 0`` asks the kernel for a free port;
the actual bootstrap URL is printed on stdout after uvicorn has started, so a
script can read the line and use it immediately without polling a guess.
"""

from __future__ import annotations

import argparse
import errno
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from basseparate.app import create_app
from basseparate.config import Settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORT = 8765
STARTUP_TIMEOUT_SECONDS = 30.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="basseparate",
        description="Local bass practice studio (offline, loopback only).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the local API and UI server")
    serve.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="port to bind; 0 asks the kernel for a free port (default: 8765)",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="loopback host to bind: 127.0.0.1, localhost or ::1",
    )
    serve.add_argument(
        "--no-browser",
        action="store_true",
        dest="no_browser",
        help="do not open the bootstrap URL in a browser",
    )
    serve.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="application data directory (default: per-user data dir)",
    )
    serve.add_argument(
        "--web-dir",
        type=Path,
        default=None,
        help="built UI directory (default: web/dist in the checkout)",
    )
    serve.add_argument(
        "--log-level",
        default="warning",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn log level (default: warning)",
    )
    return parser


def _closed_socket_error(error: OSError) -> bool:
    """WinError 10038/WSAENOTSOCK and EBADF mean the socket already closed."""
    return getattr(error, "winerror", None) == 10038 or error.errno in {
        errno.EBADF,
        10038,
    }


def _safe_close(sock: socket.socket, context: str) -> None:
    """Close a socket that uvicorn may already own/closed, without masking real errors.

    ``serve`` binds the socket, passes it to ``uvicorn.Server.run(sockets=[sock])``
    and then closes it in ``finally``. During uvicorn/asyncio shutdown the
    listening socket may already be closed; a second ``closesocket`` on Windows
    reports WSAENOTSOCK/WinError 10038. Suppress only that closed-socket case.
    """
    try:
        sock.close()
    except OSError as error:
        if not _closed_socket_error(error):
            raise
        print(
            f"basseparate: {context}: socket was already closed "
            f"(winerror={getattr(error, 'winerror', None)}, errno={error.errno}); ignoring",
            file=sys.stderr,
        )


def _close_if_owned(sock: socket.socket, owned_by_server: bool, context: str) -> None:
    """Close only sockets not already owned/closed by uvicorn."""
    if not owned_by_server:
        _safe_close(sock, context)


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except OSError as error:
        if _closed_socket_error(error):
            print(f"basseparate: browser launch socket was closed: {error}", file=sys.stderr)
            return
        raise


def _bind_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(128)
    except OSError:
        _safe_close(sock, "bind failure")
        raise
    return sock


def serve(args: argparse.Namespace) -> int:
    host = str(args.host)
    if host not in LOOPBACK_HOSTS:
        print(
            f"basseparate: refusing to bind non-loopback host {host!r}; "
            "the studio only listens on loopback",
            file=sys.stderr,
        )
        return 2
    if not 0 <= args.port <= 65_535:
        print(f"basseparate: invalid port {args.port}", file=sys.stderr)
        return 2

    defaults = Settings()
    settings = Settings(
        data_dir=args.data_root if args.data_root is not None else defaults.data_dir,
        web_dir=args.web_dir if args.web_dir is not None else defaults.web_dir,
    )

    try:
        sock = _bind_socket(host, args.port)
    except OSError as error:
        print(f"basseparate: cannot bind {host}:{args.port}: {error}", file=sys.stderr)
        return 1
    port = sock.getsockname()[1]
    display_host = f"[{host}]" if ":" in host else host
    url = f"http://{display_host}:{port}/"

    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=args.log_level,
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    failure: list[BaseException] = []

    def run_server() -> None:
        try:
            server.run(sockets=[sock])
        except OSError as error:  # uvicorn/asyncio may close the passed socket
            if _closed_socket_error(error):
                print(
                    f"basseparate: server socket was already closed during shutdown: {error}",
                    file=sys.stderr,
                )
                return
            failure.append(error)
        except BaseException as error:  # pragma: no cover - surfaced below
            failure.append(error)

    thread = threading.Thread(target=run_server, name="basseparate-server", daemon=True)
    thread.start()
    socket_owned_by_server = False
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        if failure:
            print(f"basseparate: server failed to start: {failure[0]}", file=sys.stderr)
        else:
            print("basseparate: server did not start in time", file=sys.stderr)
        server.should_exit = True
        thread.join(timeout=5)
        _safe_close(sock, "startup failure")
        return 1

    socket_owned_by_server = True
    print(f"basseparate studio: {url}", flush=True)
    print(f"bootstrap: {url}", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, _open_browser, args=[url]).start()

    try:
        while thread.is_alive():
            thread.join(timeout=0.25)
    except KeyboardInterrupt:
        print("basseparate: stopping", file=sys.stderr)
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        # Once uvicorn/asyncio has taken the listening socket, it closes it as
        # part of server.run shutdown. Closing it again here is the Windows
        # WSAENOTSOCK/WinError 10038 path; only close sockets we still own.
        _close_if_owned(sock, socket_owned_by_server, "server shutdown")
    return 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.error(f"unknown command {args.command}")
    return serve(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
