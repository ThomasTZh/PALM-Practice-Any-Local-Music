"""Shared SHA256SUMS writer for release builders.

Builders run independently and all target ``dist/SHA256SUMS``. Merge rather than
overwrite so a Linux host that already contains Windows/macOS artifacts keeps a
single manifest covering every asset. Missing or replaced files are pruned;
the result is sorted by basename.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def update_checksums(dist: Path, assets: Iterable[Path]) -> Path:
    """Merge current release assets into ``dist/SHA256SUMS``."""
    checksums = dist / "SHA256SUMS"
    entries: dict[str, str] = {}
    if checksums.is_file():
        for line in checksums.read_text(encoding="utf-8").splitlines():
            digest, separator, name = line.partition("  ")
            if separator and name and (dist / name).is_file():
                entries[name] = digest
    for asset in assets:
        if asset.is_file():
            entries[asset.name] = sha256(asset)
    for name in list(entries):
        if not (dist / name).is_file():
            del entries[name]
    checksums.write_text(
        "".join(f"{entries[name]}  {name}\n" for name in sorted(entries)),
        encoding="ascii",
    )
    return checksums
