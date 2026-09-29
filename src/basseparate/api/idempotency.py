"""In-memory idempotency key store (M0.6).

Maps idempotency keys to (body_hash, project) pairs. Persists for the
lifetime of the application instance. Not thread-safe; intended for
use within a single async event loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from basseparate.domain.project import ProjectRecord


@dataclass(frozen=True)
class IdempotencyEntry:
    body_hash: str
    project: ProjectRecord


class IdempotencyStore:
    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyEntry] = {}

    def get(self, key: str) -> IdempotencyEntry | None:
        return self._entries.get(key)

    def set(self, key: str, body_hash: str, project: ProjectRecord) -> None:
        self._entries[key] = IdempotencyEntry(body_hash=body_hash, project=project)

    def clear(self) -> None:
        self._entries.clear()
