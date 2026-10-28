"""Fast native Vamp host adapter.

The C++ host consumes interleaved float32 PCM directly and writes only the
selected beat/bar outputs. It avoids the per-block JSON round trips of the
Piper host and is the preferred personal-use path when configured.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from basseparate.vamp.features import VampAnalysis


class NativeVampUnavailable(RuntimeError):
    """The native host binary is missing or not executable."""


class NativeVampError(RuntimeError):
    """The native host failed or returned malformed output."""


def analyze_pcm_native(
    pcm_path: Path,
    *,
    sample_rate: int,
    channels: int,
    host_path: Path,
    plugin_path: Path,
    plugin_key: str,
    bpb: int,
    timeout_seconds: float,
) -> VampAnalysis:
    if not host_path.is_file() or not os.access(host_path, os.X_OK):
        raise NativeVampUnavailable(f"native Vamp host not found or not executable: {host_path}")
    if not plugin_path.is_dir():
        raise NativeVampUnavailable(f"Vamp plugin directory not found: {plugin_path}")
    env = dict(os.environ)
    env["VAMP_PATH"] = str(plugin_path)
    output_fd, output_name = tempfile.mkstemp(prefix="basseparate-vamp-", suffix=".json")
    os.close(output_fd)
    output_path = Path(output_name)
    try:
        completed = subprocess.run(
            [
                str(host_path),
                plugin_key,
                str(pcm_path),
                str(sample_rate),
                str(channels),
                str(bpb),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NativeVampError(detail or f"native Vamp host exited {completed.returncode}")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeVampError("native Vamp host wrote no valid JSON") from exc
        return VampAnalysis.from_payload(payload)
    finally:
        output_path.unlink(missing_ok=True)
