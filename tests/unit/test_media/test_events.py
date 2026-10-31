"""SSE framing is a wire format; pin it with exact byte comparisons."""

from __future__ import annotations

from basseparate.events import SSEEvent, encode_sse, heartbeat, sse_headers


def test_encode_single_line_event() -> None:
    assert (
        encode_sse(SSEEvent(event="progress", data='{"progress":0.5}'))
        == 'event: progress\ndata: {"progress":0.5}\n\n'
    )


def test_encode_multiline_data_uses_one_data_line_per_line() -> None:
    assert (
        encode_sse(SSEEvent(event="log", data="first\nsecond"))
        == "event: log\ndata: first\ndata: second\n\n"
    )


def test_encode_id_and_retry() -> None:
    assert (
        encode_sse(SSEEvent(event="job", data="x", id="42", retry_ms=2500))
        == "retry: 2500\nid: 42\nevent: job\ndata: x\n\n"
    )


def test_heartbeat_is_a_comment_block() -> None:
    assert heartbeat() == ": keep-alive\n\n"
    assert heartbeat("still here") == ": still here\n\n"


def test_sse_headers_disable_buffering() -> None:
    headers = sse_headers()
    assert headers["content-type"] == "text/event-stream; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert headers["x-accel-buffering"] == "no"
