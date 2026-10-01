"""Bounded-memory local file transfer sessions (M1.2).

Each import owns one temporary media file and one JSON manifest. The
manifest is the durable record of the acknowledged byte offset and the
SHA-256 hash of every acknowledged chunk. Media bytes and manifest never
share a file.

Invariants maintained after every acknowledged chunk:

- ``temp file size == manifest expected_offset``
- the manifest is written atomically (tmp + rename) after the media file
  is fsynced
- on session load, any media bytes beyond the manifest offset (crash
  residue) are truncated away

The complete media file is never held in server memory: request bodies
are streamed in bounded reads, hashed incrementally, and written to disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_SUFFIX = ".manifest.json"
PART_SUFFIX = ".part"
_STREAM_READ_SIZE = 256 * 1024


class UploadError(Exception):
    """Base class for upload session failures."""


class ImportSessionNotFoundError(UploadError):
    def __init__(self, import_id: str) -> None:
        super().__init__(f"import session not found: {import_id}")
        self.import_id = import_id


class OffsetMismatchError(UploadError):
    """Chunk offset is beyond the next expected position."""

    def __init__(self, expected: int, requested: int) -> None:
        super().__init__(f"expected offset {expected}, got {requested}")
        self.expected = expected
        self.requested = requested


class ChunkConflictError(UploadError):
    """A repeated offset carries different bytes than the acknowledged one."""

    def __init__(self, offset: int) -> None:
        super().__init__(f"chunk at offset {offset} does not match the acknowledged bytes")
        self.offset = offset


class ChunkSizeError(UploadError):
    """The request body exceeds the maximum chunk size."""

    def __init__(self, maximum: int, received: int) -> None:
        super().__init__(f"chunk of {received} bytes exceeds the {maximum} byte limit")
        self.maximum = maximum
        self.received = received


class SessionNotActiveError(UploadError):
    """The import is not in a state that accepts chunks."""

    def __init__(self, state: str) -> None:
        super().__init__(f"import is not accepting uploads (state: {state})")
        self.state = state


@dataclass(frozen=True)
class ChunkAck:
    """Durable acknowledgment for an uploaded chunk."""

    offset: int
    chunk_bytes: int
    idempotent_replay: bool = False


@dataclass
class _Manifest:
    import_id: str
    expected_offset: int
    chunk_hashes: dict[int, str] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(f"{self.import_id}{MANIFEST_SUFFIX}")

    def to_json(self) -> str:
        return json.dumps(
            {
                "import_id": self.import_id,
                "expected_offset": self.expected_offset,
                "chunk_hashes": {str(k): v for k, v in sorted(self.chunk_hashes.items())},
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> _Manifest:
        data = json.loads(raw)
        return cls(
            import_id=data["import_id"],
            expected_offset=int(data["expected_offset"]),
            chunk_hashes={int(k): v for k, v in data.get("chunk_hashes", {}).items()},
        )


@dataclass
class _Session:
    import_id: str
    part_path: Path
    manifest_path: Path
    lock: asyncio.Lock
    manifest: _Manifest | None = None


class UploadManager:
    """Owns per-import upload sessions, locks, and manifest durability.

    One instance per server process. Sessions are created on demand from
    an import id and survive restarts via their on-disk manifest; the
    in-process lock map is rebuilt lazily.
    """

    def __init__(self, uploads_dir: Path, chunk_size: int, max_import_bytes: int) -> None:
        self._uploads_dir = uploads_dir
        self._chunk_size = chunk_size
        self._max_import_bytes = max_import_bytes
        self._sessions: dict[str, _Session] = {}

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def max_import_bytes(self) -> int:
        return self._max_import_bytes

    def part_path_for(self, import_id: uuid.UUID) -> Path:
        return self._uploads_dir / f"{import_id}{PART_SUFFIX}"

    def manifest_path_for(self, import_id: uuid.UUID) -> Path:
        return self._uploads_dir / f"{import_id}{MANIFEST_SUFFIX}"

    def free_bytes(self) -> int:
        usage = shutil.disk_usage(self._uploads_dir)
        return usage.free

    def reserve(self, import_id: uuid.UUID, declared_byte_count: int) -> Path:
        """Reserve the temporary media path and check available disk space.

        Raises UploadError (insufficient space) before any bytes are
        written. The returned path is owned by the import.
        """
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        part = self.part_path_for(import_id)
        free = self.free_bytes()
        # Reserve the declared media size plus a 2 GiB headroom for
        # decode/waveform staging that follows the transfer.
        reserve = declared_byte_count + 2 * 1024**3
        if free < reserve:
            raise UploadError(f"insufficient disk space: need {reserve} bytes, {free} free")
        # Start from a clean file so a stale .part from a crashed session
        # cannot mix bytes with the new transfer.
        with part.open("wb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        self._write_manifest(
            str(import_id),
            _Manifest(import_id=str(import_id), expected_offset=0),
        )
        return part

    def _session(self, import_id: str) -> _Session:
        session = self._sessions.get(import_id)
        if session is not None:
            return session
        part = self._uploads_dir / f"{import_id}{PART_SUFFIX}"
        manifest_path = self._uploads_dir / f"{import_id}{MANIFEST_SUFFIX}"
        if not manifest_path.is_file():
            raise ImportSessionNotFoundError(import_id)
        manifest = _Manifest.from_json(manifest_path.read_text())
        # Reconcile crash residue: media bytes past the durable offset are
        # unacknowledged and must not shift later chunks.
        if part.exists() and part.stat().st_size > manifest.expected_offset:
            with part.open("r+b") as handle:
                handle.truncate(manifest.expected_offset)
        session = _Session(
            import_id=import_id,
            part_path=part,
            manifest_path=manifest_path,
            lock=asyncio.Lock(),
            manifest=manifest,
        )
        self._sessions[import_id] = session
        return session

    def _write_manifest(self, import_id: str, manifest: _Manifest) -> None:
        tmp = self._uploads_dir / f"{import_id}.manifest.tmp"
        tmp.write_text(manifest.to_json())
        tmp.replace(self._uploads_dir / f"{import_id}{MANIFEST_SUFFIX}")

    def acknowledged_offset(self, import_id: uuid.UUID) -> int:
        return self._session(str(import_id)).manifest.expected_offset  # type: ignore[union-attr]

    async def append_chunk(
        self,
        import_id: uuid.UUID,
        body: AsyncIterator[bytes],
        requested_offset: int,
        chunk_sha256: str,
    ) -> ChunkAck:
        """Stream one chunk from an async byte iterator to disk.

        ``body`` is ``request.stream()``: an async iterator of bytes.
        Returns the durable acknowledged offset.
        """
        import_id_str = str(import_id)
        session = self._session(import_id_str)
        async with session.lock:
            manifest = session.manifest
            assert manifest is not None
            durable = manifest.expected_offset

            if requested_offset > durable:
                raise OffsetMismatchError(durable, requested_offset)

            if requested_offset < durable:
                # Replay of an already-acknowledged chunk.
                stored = manifest.chunk_hashes.get(requested_offset)
                if stored != chunk_sha256:
                    raise ChunkConflictError(requested_offset)
                return ChunkAck(
                    offset=durable, chunk_bytes=durable - requested_offset, idempotent_replay=True
                )

            hasher = hashlib.sha256()
            received = 0
            with session.part_path.open("r+b") as handle:
                handle.seek(durable)
                async for block in body:
                    if not block:
                        continue
                    received += len(block)
                    if received > self._chunk_size:
                        raise ChunkSizeError(self._chunk_size, received)
                    hasher.update(block)
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())

            if received == 0:
                raise ChunkSizeError(self._chunk_size, 0)

            actual = hasher.hexdigest()
            if actual != chunk_sha256:
                # The bytes are on disk but unacknowledged; roll the file
                # back so the offset invariant holds and the client can
                # retry cleanly.
                with session.part_path.open("r+b") as handle:
                    handle.truncate(durable)
                raise ChunkConflictError(requested_offset)

            manifest.expected_offset = durable + received
            manifest.chunk_hashes[requested_offset] = actual
            self._write_manifest(import_id_str, manifest)
            session.manifest = manifest
            return ChunkAck(offset=manifest.expected_offset, chunk_bytes=received)

    async def hash_completed_file(self, import_id: uuid.UUID) -> str:
        """Stream the full temporary file through SHA-256 (bounded memory)."""
        session = self._session(str(import_id))
        hasher = hashlib.sha256()
        with session.part_path.open("rb") as handle:
            while block := handle.read(_STREAM_READ_SIZE):
                hasher.update(block)
        return hasher.hexdigest()

    def file_size(self, import_id: uuid.UUID) -> int:
        session = self._session(str(import_id))
        return session.part_path.stat().st_size if session.part_path.exists() else 0

    async def cancel_and_remove(self, import_id: uuid.UUID) -> None:
        """Remove the uncommitted temporary bytes and manifest for an import.

        Only this import's files are touched. Published shared assets are
        owned elsewhere and are never removed here. The per-import lock is
        held so an in-flight chunk write cannot race the removal.
        """
        import_id_str = str(import_id)
        session = self._sessions.get(import_id_str)
        if session is not None:
            async with session.lock:
                self._unlink_files(import_id_str)
            self._sessions.pop(import_id_str, None)
        else:
            self._unlink_files(import_id_str)

    def _unlink_files(self, import_id_str: str) -> None:
        part = self._uploads_dir / f"{import_id_str}{PART_SUFFIX}"
        manifest = self._uploads_dir / f"{import_id_str}{MANIFEST_SUFFIX}"
        tmp = self._uploads_dir / f"{import_id_str}.manifest.tmp"
        for path in (part, manifest, tmp):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
