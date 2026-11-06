"""Read-only system checks for the first-run screen."""

from __future__ import annotations

import platform
import shutil
from collections.abc import Callable
from pathlib import Path

from basseparate.config import RuntimePaths

DiskProbe = Callable[[Path], object]
Which = Callable[[str], str | None]
REQUIRED_FREE_BYTES = 5 * 1024**3


def system_checks(
    runtime: RuntimePaths,
    *,
    disk_probe: DiskProbe | None = None,
    which: Which | None = None,
) -> dict[str, dict[str, object]]:
    """Report glibc, free disk and ffmpeg without touching the network."""
    probe = disk_probe if disk_probe is not None else shutil.disk_usage
    find = which if which is not None else shutil.which
    try:
        usage = probe(runtime.data_root)
        free_value = getattr(usage, "free", None)
        if free_value is None and isinstance(usage, tuple) and len(usage) >= 3:
            free_value = usage[2]
        free = int(free_value or 0)
        disk_ok = free >= REQUIRED_FREE_BYTES
        disk_detail = f"{free // (1024**2)} MiB free; 5120 MiB required"
    except OSError as error:
        free = 0
        disk_ok = False
        disk_detail = f"cannot inspect {runtime.data_root}: {error}"
    libc_name, libc_version = platform.libc_ver()
    glibc_ok = bool(libc_version)
    version_parts = tuple(int(part) for part in libc_version.split(".") if part.isdigit())
    if len(version_parts) >= 2 and version_parts < (2, 31):
        glibc_ok = False
    ffmpeg = find("ffmpeg")
    return {
        "glibc": {
            "ok": glibc_ok,
            "status": "ok" if glibc_ok else "missing",
            "detail": f"{libc_name or 'libc'} {libc_version or 'unknown'}",
        },
        "disk": {
            "ok": disk_ok,
            "status": "ok" if disk_ok else "missing",
            "free_bytes": free,
            "required_bytes": REQUIRED_FREE_BYTES,
            "detail": disk_detail,
        },
        "ffmpeg": {
            "ok": ffmpeg is not None,
            "status": "ok" if ffmpeg is not None else "missing",
            "path": ffmpeg,
            "detail": ffmpeg or "ffmpeg is not on PATH",
        },
    }
