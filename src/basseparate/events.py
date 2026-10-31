"""Server-sent event framing.

The wire format is fixed server-side so browser tests can assert exact frames.
SSE is written as UTF-8 text with one blank line between events; data lines are
split so embedded newlines cannot terminate the event early.
"""

from __future__ import annotations

from dataclasses import dataclass

SSE_CONTENT_TYPE = "text/event-stream; charset=utf-8"


@dataclass(frozen=True)
class SSEEvent:
    event: str
    data: str
    id: str | None = None
    retry_ms: int | None = None


def encode_sse(event: SSEEvent) -> str:
    lines: list[str] = []
    if event.retry_ms is not None:
        lines.append(f"retry: {event.retry_ms}")
    if event.id is not None:
        lines.append(f"id: {event.id}")
    lines.append(f"event: {event.event}")
    lines.extend(f"data: {line}" for line in event.data.split("\n"))
    return "\n".join(lines) + "\n\n"


def heartbeat(comment: str = "keep-alive") -> str:
    return f": {comment}\n\n"


def sse_headers() -> dict[str, str]:
    return {
        "content-type": SSE_CONTENT_TYPE,
        "cache-control": "no-store",
        "connection": "keep-alive",
        "x-accel-buffering": "no",
    }
