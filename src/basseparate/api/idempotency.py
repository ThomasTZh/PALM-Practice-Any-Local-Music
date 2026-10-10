"""In-memory idempotency key store (M0.6, generalized M1.15).

Maps idempotency keys to (body_hash, payload) pairs. The payload is the
cached response value (a project record for project creation, a command
result for project commands). Persists for the lifetime of the
application instance. Not thread-safe; intended for use within a single
async event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IdempotencyEntry:
    body_hash: str
    payload: Any


class IdempotencyStore:
    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyEntry] = {}

    def get(self, key: str) -> IdempotencyEntry | None:
        return self._entries.get(key)

    def set(self, key: str, body_hash: str, payload: Any) -> None:
        self._entries[key] = IdempotencyEntry(body_hash=body_hash, payload=payload)

    def clear(self) -> None:
        self._entries.clear()
