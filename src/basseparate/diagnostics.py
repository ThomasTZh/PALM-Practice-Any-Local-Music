"""Environment diagnostics for ``basseparate doctor``.

Rules: no PyTorch import, timeouts on every external command, argument arrays
(no shell interpolation), required versus optional capabilities, and no
mutation of the environment (directories are reported, not created).
"""

from __future__ import annotations

import platform
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate import APP_VERSION
from basseparate.config import AppConfig

Status = Literal["ok", "warn", "fail"]

_COMMAND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    status: Status
    detail: str
    required: bool


def _run_command(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"command failed: {exc}"
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        output = f"exit {proc.returncode}: {(proc.stderr or proc.stdout or '').strip()}"
    return proc.returncode, output


def _total_ram_bytes() -> int | None:
    try:
        with Path("/proc/meminfo").open("r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _frontend_build_available() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent / "web" / "static" / "index.html",
        Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_diagnostics(config: AppConfig) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []

    checks.append(DiagnosticCheck("application", "ok", f"basseparate {APP_VERSION}", required=True))
    checks.append(
        DiagnosticCheck(
            "python",
            "ok",
            f"{platform.python_version()} at {sys.executable}",
            required=True,
        )
    )
    checks.append(
        DiagnosticCheck(
            "platform",
            "ok",
            f"{platform.system()} {platform.release()} ({platform.machine()})",
            required=True,
        )
    )

    ram = _total_ram_bytes()
    if ram is None:
        checks.append(
            DiagnosticCheck("ram", "warn", "total RAM could not be determined", required=False)
        )
    else:
        checks.append(
            DiagnosticCheck("ram", "ok", f"{ram / (1024**3):.1f} GiB total", required=False)
        )

    for label, directory in (
        ("config", config.config_file.parent),
        ("data", _storage_dir(config, "data")),
        ("cache", _storage_dir(config, "cache")),
        ("state", _storage_dir(config, "state")),
    ):
        detail = _describe_storage_dir(label, directory)
        status: Status = "ok" if directory.is_dir() else "warn"
        checks.append(DiagnosticCheck(f"storage-{label}", status, detail, required=False))

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        checks.append(DiagnosticCheck("ffmpeg", "ok", f"{ffmpeg} + {ffprobe}", required=False))
    else:
        missing = "ffmpeg" if not ffmpeg else "ffprobe"
        checks.append(
            DiagnosticCheck(
                "ffmpeg",
                "warn",
                f"{missing} not found on PATH (required for audio import in a later milestone)",
                required=False,
            )
        )

    node = shutil.which("node")
    pnpm = shutil.which("pnpm")
    if node and pnpm:
        checks.append(DiagnosticCheck("node-pnpm", "ok", f"{node} + {pnpm}", required=False))
    else:
        checks.append(
            DiagnosticCheck(
                "node-pnpm",
                "warn",
                "node and/or pnpm not found on PATH (needed only for frontend development)",
                required=False,
            )
        )

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        checks.append(
            DiagnosticCheck(
                "gpu",
                "warn",
                "nvidia-smi not available; GPU inference is unavailable (optional in Milestone 0)",
                required=False,
            )
        )
    else:
        code, output = _run_command(
            [
                nvidia_smi,
                "--query-gpu=name,uuid,memory.total,memory.free",
                "--format=csv,noheader",
            ]
        )
        if code == 0 and output:
            checks.append(
                DiagnosticCheck(
                    "gpu",
                    "ok",
                    "GPU(s): " + " | ".join(line.strip() for line in output.splitlines()),
                    required=False,
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    "gpu",
                    "warn",
                    f"nvidia-smi present but driver query failed: {output}",
                    required=False,
                )
            )

    build = _frontend_build_available()
    if build is not None:
        checks.append(DiagnosticCheck("frontend-build", "ok", str(build), required=True))
    else:
        checks.append(
            DiagnosticCheck(
                "frontend-build",
                "fail",
                "no built frontend assets found; run the build before serving",
                required=True,
            )
        )

    checks.append(_database_check())
    return checks


def _storage_dir(config: AppConfig, category: str) -> Path:
    if config.storage_root is not None:
        return config.storage_root / category
    from basseparate.storage import default_storage_paths

    paths = default_storage_paths()
    match category:
        case "config":
            return paths.config
        case "data":
            return paths.data
        case "cache":
            return paths.cache
        case _:
            return paths.state


def _describe_storage_dir(label: str, directory: Path) -> str:
    if not directory.is_dir():
        return f"{directory} (not created yet; created at startup)"
    try:
        usage = shutil.disk_usage(directory)
        return f"{directory} ({usage.free / (1024**3):.1f} GiB free)"
    except OSError:
        return str(directory)


def _database_check() -> DiagnosticCheck:
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("SELECT 1")
            connection.execute("PRAGMA user_version")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return DiagnosticCheck("database", "fail", f"SQLite is not usable: {exc}", required=True)
    return DiagnosticCheck("database", "ok", f"sqlite3 {sqlite3.sqlite_version}", required=True)


def format_report(checks: list[DiagnosticCheck]) -> str:
    lines = ["basseparate doctor", "=" * 60]
    for check in checks:
        marker = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[check.status]
        kind = "required" if check.required else "optional"
        lines.append(f"[{marker}] {check.name} ({kind}): {check.detail}")
    lines.append("=" * 60)
    failed_required = [c.name for c in checks if c.required and c.status == "fail"]
    if failed_required:
        lines.append(f"RESULT: not ready — required checks failed: {', '.join(failed_required)}")
    else:
        lines.append("RESULT: core foundation is ready.")
    return "\n".join(lines)


def exit_code_for(checks: list[DiagnosticCheck]) -> int:
    return 1 if any(c.required and c.status == "fail" for c in checks) else 0
