"""Shared subprocess helpers for FFmpeg/ffprobe tools (M1.3, extended M1.5).

Used by ``probe.py`` and ``decode.py``: graceful termination with escalation,
cancellation polling, and bounded stream reads. The helpers work on
``asyncio.subprocess.Process`` objects and are transport-agnostic.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading

#: How long to wait after ``terminate()`` before escalating to ``kill()``.
TERMINATE_GRACE_SECONDS = 5.0
#: Poll interval for threading.Event based cancellation.
CANCEL_POLL_SECONDS = 0.1


class SubprocessOutputError(Exception):
    """A subprocess stream exceeded its byte bound."""


def kill(proc: asyncio.subprocess.Process) -> None:
    """Send SIGKILL if the process is still running."""
    if proc.returncode is None:
        proc.kill()


async def wait_for_cancel(cancel_event: threading.Event) -> None:
    """Poll a ``threading.Event`` until cancellation is requested."""
    while not cancel_event.is_set():
        await asyncio.sleep(CANCEL_POLL_SECONDS)


async def terminate_gracefully(
    proc: asyncio.subprocess.Process,
    timeout: float = TERMINATE_GRACE_SECONDS,
) -> None:
    """Terminate gracefully, escalating to kill. Always reaps (milestone1.md §6.7)."""
    if proc.returncode is None:
        proc.terminate()
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=timeout)
    if proc.returncode is None:
        proc.kill()
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=timeout)


async def read_stream_bounded(
    stream: asyncio.StreamReader,
    limit: int,
    what: str,
) -> bytes:
    """Read a subprocess stream, refusing output beyond ``limit`` bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise SubprocessOutputError(f"{what} exceeds {limit} bytes")
        chunks.append(chunk)
