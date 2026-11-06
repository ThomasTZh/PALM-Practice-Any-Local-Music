"""Pinned, resumable downloads with .part staging and verification."""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from basseparate.setup.errors import DownloadError, SetupCancelled

CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 120
Progress = Callable[[int, int], None]
Cancel = Callable[[], bool]

# A fetch callback writes the URL into the given .part path. Tests inject one;
# the default streams HTTPS with a Range request when a partial file exists.
Fetch = Callable[[str, Path], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(
    url: str,
    destination: Path,
    *,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> None:
    """Stream an HTTPS URL into destination, resuming and checking cancel per chunk."""
    if not url.startswith("https://"):
        raise DownloadError(f"refusing non-HTTPS download: {url}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    offset = destination.stat().st_size if destination.is_file() else 0
    headers = {"User-Agent": "palm-setup/1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    mode = "ab" if offset else "wb"
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            if offset and getattr(response, "status", 200) != 206:
                # The server ignored Range; restart the part file.
                mode = "wb"
                offset = 0
            total_header = response.headers.get("Content-Length")
            total = offset + int(total_header) if total_header and total_header.isdigit() else 0
            downloaded = offset
            with destination.open(mode) as handle:
                while True:
                    if cancel is not None and cancel():
                        raise SetupCancelled("download cancelled")
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DownloadError(f"download failed for {url}: {error}") from error


def download_verified(
    url: str,
    destination: Path,
    *,
    size_bytes: int,
    sha256: str,
    fetch: Fetch | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> Path:
    """Download, verify size/hash and atomically publish destination."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        if (
            destination.is_file()
            and destination.stat().st_size == size_bytes
            and _sha256(destination) == sha256
        ):
            if progress is not None:
                progress(size_bytes, size_bytes)
            return destination
        if not (part.is_file() and part.stat().st_size == size_bytes and _sha256(part) == sha256):
            if cancel is not None and cancel():
                raise SetupCancelled("download cancelled")
            if fetch is None:
                download_file(url, part, progress=progress, cancel=cancel)
            else:
                fetch(url, part)
        if cancel is not None and cancel():
            raise SetupCancelled("download cancelled")
        if not part.is_file():
            raise DownloadError(f"{url}: download produced no file")
        actual_size = part.stat().st_size
        if actual_size != size_bytes:
            raise DownloadError(f"{url}: expected {size_bytes} bytes, downloaded {actual_size}")
        actual_sha = _sha256(part)
        if actual_sha != sha256:
            raise DownloadError(f"{url}: sha256 mismatch (expected {sha256}, got {actual_sha})")
        if progress is not None:
            progress(actual_size, size_bytes)
        part.replace(destination)
        return destination
    except SetupCancelled:
        # Keep the partial file so a later retry can resume with a Range request.
        raise
    except DownloadError:
        if not (part.is_file() and part.stat().st_size < size_bytes):
            part.unlink(missing_ok=True)
        raise
    except BaseException:
        part.unlink(missing_ok=True)
        raise
