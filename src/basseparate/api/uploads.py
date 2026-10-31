"""Minimal streaming multipart/form-data parser.

The pinned environment has no ``python-multipart`` and no new dependency may be
added, so uploads are parsed here: stream the file part to a temporary file and
keep small text fields in memory. The parser enforces the upload limit while
writing and never trusts the client's filename as a path.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from fastapi import Request

MAX_HEADER_LINE = 16 * 1024
MAX_FIELDS = 32
MAX_OVERHEAD = 1 * 1024 * 1024
READ_CHUNK = 256 * 1024


class UploadError(Exception):
    """The multipart upload is malformed or too large."""


@dataclass(frozen=True)
class FilePart:
    filename: str
    path: Path
    size: int
    content_type: str | None


@dataclass(frozen=True)
class ParsedForm:
    files: dict[str, FilePart] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


def parse_boundary(content_type: str) -> bytes:
    header, _, parameters = content_type.partition(";")
    if header.strip().lower() != "multipart/form-data":
        raise UploadError("expected a multipart/form-data upload")
    for parameter in parameters.split(";"):
        key, _, raw_value = parameter.strip().partition("=")
        if key.lower() != "boundary":
            continue
        value = raw_value.strip().strip('"')
        if value:
            return value.encode("latin-1")
        break
    raise UploadError("multipart boundary is missing")


def header_parameter(header_value: str, parameter: str) -> str | None:
    for segment in header_value.split(";"):
        key, _, raw_value = segment.strip().partition("=")
        if key.lower() != parameter:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"')
        return value
    return None


def safe_filename(raw: str | None) -> str:
    if not raw:
        raise UploadError("the uploaded file part has no filename")
    name = Path(raw.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise UploadError("the uploaded filename is not usable")
    return name


class _MultipartReader:
    def __init__(self, stream: AsyncIterator[bytes], *, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._buffer = bytearray()
        self._eof = False
        self.total = 0

    async def _read_chunk(self) -> bool:
        if self._eof:
            return False
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._eof = True
            return False
        if not chunk:
            return True
        self.total += len(chunk)
        if self.total > self._max_bytes + MAX_OVERHEAD:
            raise UploadError(f"upload exceeds the {self._max_bytes} byte limit")
        self._buffer.extend(chunk)
        return True

    async def read_line(self) -> bytes:
        while True:
            index = self._buffer.find(b"\r\n")
            if index >= 0:
                line = bytes(self._buffer[:index])
                del self._buffer[: index + 2]
                return line
            if len(self._buffer) > MAX_HEADER_LINE:
                raise UploadError("multipart header line is too long")
            if not await self._read_chunk():
                raise UploadError("unexpected end of multipart body while reading a header")

    async def skip_to(self, marker: bytes) -> None:
        keep = len(marker) - 1
        while True:
            index = self._buffer.find(marker)
            if index >= 0:
                del self._buffer[: index + len(marker)]
                return
            if len(self._buffer) > keep:
                del self._buffer[: len(self._buffer) - keep]
            if not await self._read_chunk():
                raise UploadError("multipart boundary not found")

    async def read_until(self, marker: bytes, sink: Callable[[bytes], None]) -> None:
        keep = len(marker) - 1
        while True:
            index = self._buffer.find(marker)
            if index >= 0:
                sink(bytes(self._buffer[:index]))
                del self._buffer[: index + len(marker)]
                return
            if len(self._buffer) > keep:
                take = len(self._buffer) - keep
                sink(bytes(self._buffer[:take]))
                del self._buffer[:take]
            if not await self._read_chunk():
                raise UploadError("unexpected end of multipart body while reading a part")

    async def read_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line = await self.read_line()
            if not line:
                return headers
            if line[:1] in {b" ", b"\t"}:
                raise UploadError("folded multipart headers are not supported")
            key, _, value = line.decode("latin-1").partition(":")
            if not key.strip():
                raise UploadError("malformed multipart header")
            headers[key.strip().lower()] = value.strip()

    def starts_with(self, prefix: bytes) -> bool:
        return self._buffer.startswith(prefix)

    def consume(self, count: int) -> None:
        del self._buffer[:count]

    def remaining(self) -> bytes:
        return bytes(self._buffer)


async def parse_multipart_upload(
    request: Request,
    *,
    target_dir: Path,
    max_bytes: int,
) -> ParsedForm:
    boundary = parse_boundary(request.headers.get("content-type", ""))
    start = b"--" + boundary
    delimiter = b"\r\n--" + boundary
    reader = _MultipartReader(request.stream(), max_bytes=max_bytes)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    files: dict[str, FilePart] = {}
    fields: dict[str, str] = {}
    try:
        await reader.skip_to(start)
        line = await reader.read_line()
        if line == b"--":
            return ParsedForm()
        if line != b"":
            raise UploadError("malformed multipart body after the first boundary")

        while True:
            headers = await reader.read_headers()
            disposition = headers.get("content-disposition", "")
            name = header_parameter(disposition, "name")
            filename = header_parameter(disposition, "filename")
            if filename is not None:
                if name is None:
                    raise UploadError("file part has no form field name")
                clean = safe_filename(filename)
                suffix = Path(clean).suffix.lower()
                if not suffix or not suffix[1:].isalnum():
                    suffix = ".bin"
                path = target_dir / f"upload-{uuid.uuid4().hex}{suffix}"
                created.append(path)
                size = 0
                handle: BinaryIO = path.open("wb")

                def sink(data: bytes, handle: BinaryIO = handle) -> None:
                    nonlocal size
                    size += len(data)
                    if size > max_bytes:
                        raise UploadError(f"upload exceeds the {max_bytes} byte limit")
                    handle.write(data)

                try:
                    await reader.read_until(delimiter, sink)
                finally:
                    handle.close()
                files[name] = FilePart(
                    filename=clean,
                    path=path,
                    size=size,
                    content_type=headers.get("content-type"),
                )
            else:
                if name is None:
                    raise UploadError("form part has no field name")
                if len(fields) >= MAX_FIELDS:
                    raise UploadError("too many multipart fields")
                chunks: list[bytes] = []
                collected = 0

                field_name = name

                def collect(
                    data: bytes, chunks: list[bytes] = chunks, label: str = field_name
                ) -> None:
                    nonlocal collected
                    collected += len(data)
                    if collected > MAX_HEADER_LINE:
                        raise UploadError(f"form field {label!r} is too large")
                    chunks.append(data)

                await reader.read_until(delimiter, collect)
                fields[name] = b"".join(chunks).decode("utf-8", "replace")

            if reader.starts_with(b"--"):
                reader.consume(2)
                if reader.starts_with(b"\r\n"):
                    reader.consume(2)
                break
            line = await reader.read_line()
            if line != b"":
                raise UploadError("malformed multipart body between parts")
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return ParsedForm(files=files, fields=fields)


__all__ = [
    "FilePart",
    "ParsedForm",
    "UploadError",
    "header_parameter",
    "parse_boundary",
    "parse_multipart_upload",
]
