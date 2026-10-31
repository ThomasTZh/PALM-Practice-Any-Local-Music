"""Read-only environment diagnosis for the local studio.

Doctor never writes, creates directories, starts long-lived processes or touches
the network. It answers one question per dependency with ``ok`` or ``missing``
plus a short detail, so the UI can show why a feature is unavailable without
making the server fail.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate.config import REPO_ROOT

DoctorStatus = Literal["ok", "missing"]
ToolProbe = Callable[[str, Sequence[str], float], tuple[int, str]]
GpuProbe = Callable[[], tuple[bool, str]]


@dataclass(frozen=True)
class DoctorLayout:
    """Where each dependency is expected to live."""

    root: Path
    data_root: Path

    @classmethod
    def default(cls, data_root: Path) -> DoctorLayout:
        return cls(root=REPO_ROOT, data_root=Path(data_root))

    @property
    def model_dir(self) -> Path:
        return self.root / "models" / "htdemucs_ft"

    @property
    def emsdk(self) -> Path:
        return self.root / "third_party" / "emsdk"

    @property
    def signalsmith(self) -> Path:
        return self.root / "third_party" / "signalsmith-stretch"

    @property
    def vamp_sdk(self) -> Path:
        return self.root / "storage" / "tools" / "vamp-sdk"

    @property
    def vamp_plugins(self) -> Path:
        return self.root / "storage" / "tools" / "vamp-plugins"

    @property
    def native_host(self) -> Path:
        return self.root / "storage" / "tools" / "vamp-host"

    @property
    def piper(self) -> Path:
        return (
            self.root
            / "storage"
            / "tools"
            / "sv"
            / "squashfs-root"
            / "usr"
            / "bin"
            / "piper-vamp-simple-server"
        )

    @property
    def analysis_python(self) -> Path:
        return self.root / "analysis" / ".venv" / "bin" / "python"

    @property
    def recordings(self) -> Path:
        return self.root / "audio2test"

    @property
    def exports(self) -> Path:
        return self.data_root / "exports"


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    label: str
    status: DoctorStatus
    detail: str
    required: bool = True
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
            "path": self.path,
        }


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status == "ok" for check in self.checks if check.required)

    @property
    def status(self) -> str:
        return "ok" if self.ok else "degraded"

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(check.id for check in self.checks if check.status == "missing")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ok": self.ok,
            "missing": list(self.missing),
            "checks": [check.to_dict() for check in self.checks],
        }


def default_tool_probe(command: str, args: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
        return 1, str(error)
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return result.returncode, output[0] if output else ""


def default_gpu_probe() -> tuple[bool, str]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return False, "nvidia-smi is not on PATH"
    code, detail = default_tool_probe(
        executable,
        ("--query-gpu=name,driver_version", "--format=csv,noheader"),
        10,
    )
    if code != 0:
        return False, detail or "nvidia-smi failed"
    return True, detail


def _check(
    check_id: str,
    label: str,
    ok: bool,
    detail: str,
    *,
    required: bool = True,
    path: Path | None = None,
) -> DoctorCheck:
    return DoctorCheck(
        id=check_id,
        label=label,
        status="ok" if ok else "missing",
        detail=detail,
        required=required,
        path=str(path) if path is not None else None,
    )


def _directory_check(
    layout: DoctorLayout,
    check_id: str,
    label: str,
    path: Path,
    *,
    required: bool = True,
) -> DoctorCheck:
    if not path.is_dir():
        return _check(check_id, label, False, f"missing {path}", required=required, path=path)
    count = sum(1 for _ in path.iterdir())
    return _check(
        check_id,
        label,
        True,
        f"{path} ({count} entries)",
        required=required,
        path=path,
    )


def _tool_check(
    *,
    check_id: str,
    label: str,
    command: str,
    args: Sequence[str] = ("--version",),
    required: bool = True,
    tool_probe: ToolProbe,
) -> DoctorCheck:
    executable = shutil.which(command)
    if executable is None:
        return _check(check_id, label, False, f"{command} is not on PATH", required=required)
    code, detail = tool_probe(executable, args, 20.0)
    return _check(
        check_id,
        label,
        code == 0,
        detail or executable,
        required=required,
        path=Path(executable),
    )


def _check_python() -> DoctorCheck:
    modules = ("fastapi", "uvicorn", "pydantic", "numpy")
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    version = ".".join(str(part) for part in sys.version_info[:3])
    if missing:
        return _check("python", "Python", False, f"Python {version}; missing {', '.join(missing)}")
    return _check("python", "Python", True, f"Python {version}; {', '.join(modules)} importable")


def _check_model_bundle(layout: DoctorLayout) -> DoctorCheck:
    if not layout.model_dir.is_dir():
        return _check(
            "model_bundle",
            "Demucs model bundle",
            False,
            f"missing {layout.model_dir}",
            path=layout.model_dir,
        )
    checkpoints = sorted(layout.model_dir.glob("*.th"))
    preset = layout.model_dir / "htdemucs_ft.yaml"
    ok = len(checkpoints) == 4 and preset.is_file()
    preset_state = "present" if preset.is_file() else "missing"
    detail = f"{len(checkpoints)} checkpoints; preset {preset_state}"
    return _check("model_bundle", "Demucs model bundle", ok, detail, path=layout.model_dir)


def _check_plugin_pack(layout: DoctorLayout) -> DoctorCheck:
    plugin = layout.vamp_plugins / "qm-vamp-plugins.so"
    if not layout.vamp_plugins.is_dir():
        return _check(
            "vamp_plugins",
            "Vamp plugin pack",
            False,
            f"missing {layout.vamp_plugins}",
            path=layout.vamp_plugins,
        )
    plugins = sorted(layout.vamp_plugins.glob("*.so"))
    plugin_state = "present" if plugin.is_file() else "missing"
    return _check(
        "vamp_plugins",
        "Vamp plugin pack",
        plugin.is_file(),
        f"{len(plugins)} plugin libraries; qm-vamp-plugins.so {plugin_state}",
        path=layout.vamp_plugins,
    )


def _check_native_host(layout: DoctorLayout) -> DoctorCheck:
    path = layout.native_host
    if path.is_file():
        executable = " executable" if os.access(path, os.X_OK) else " not executable"
        return _check(
            "native_host",
            "Native Vamp host",
            os.access(path, os.X_OK),
            f"{path}{executable}",
            required=False,
            path=path,
        )
    if path.is_dir():
        return _check(
            "native_host",
            "Native Vamp host",
            True,
            f"{path} (directory)",
            required=False,
            path=path,
        )
    return _check(
        "native_host", "Native Vamp host", False, f"missing {path}", required=False, path=path
    )


def _check_piper(layout: DoctorLayout) -> DoctorCheck:
    if not layout.piper.is_file():
        return _check(
            "piper", "Piper Vamp server", False, f"missing {layout.piper}", path=layout.piper
        )
    executable = os.access(layout.piper, os.X_OK)
    return _check(
        "piper",
        "Piper Vamp server",
        executable,
        f"{layout.piper}{' executable' if executable else ' not executable'}",
        path=layout.piper,
    )


def _check_analysis(layout: DoctorLayout) -> DoctorCheck:
    if not layout.analysis_python.is_file():
        return _check(
            "analysis_venv",
            "Analysis virtualenv",
            False,
            f"missing {layout.analysis_python}",
            path=layout.analysis_python,
        )
    return _check(
        "analysis_venv",
        "Analysis virtualenv",
        True,
        str(layout.analysis_python),
        path=layout.analysis_python,
    )


def _check_recordings(layout: DoctorLayout) -> DoctorCheck:
    if not layout.recordings.is_dir():
        return _check(
            "recordings",
            "Test recordings",
            False,
            f"missing {layout.recordings}",
            required=False,
            path=layout.recordings,
        )
    recordings = sorted(layout.recordings.glob("*.wav"))
    return _check(
        "recordings",
        "Test recordings",
        True,
        f"{len(recordings)} WAV files",
        required=False,
        path=layout.recordings,
    )


def diagnose(
    layout: DoctorLayout | None = None,
    *,
    data_root: Path | None = None,
    tool_probe: ToolProbe | None = None,
    gpu_probe: GpuProbe | None = None,
) -> DoctorReport:
    """Build a read-only report; no writes, spawns are version probes only."""
    if layout is None:
        layout = DoctorLayout.default(data_root if data_root is not None else REPO_ROOT)
    probe = tool_probe if tool_probe is not None else default_tool_probe
    gpu = gpu_probe if gpu_probe is not None else default_gpu_probe
    checks: list[DoctorCheck] = [
        _check_python(),
        _tool_check(
            check_id="ffmpeg",
            label="ffmpeg",
            command="ffmpeg",
            args=("-version",),
            tool_probe=probe,
        ),
        _tool_check(
            check_id="ffprobe",
            label="ffprobe",
            command="ffprobe",
            args=("-version",),
            tool_probe=probe,
        ),
        _tool_check(
            check_id="node",
            label="Node.js",
            command="node",
            args=("--version",),
            required=False,
            tool_probe=probe,
        ),
        _directory_check(layout, "data_root", "Data directory", layout.data_root, required=True),
        _check_model_bundle(layout),
        _check_plugin_pack(layout),
        _check_piper(layout),
        _check_analysis(layout),
        _directory_check(layout, "vamp_sdk", "Vamp SDK", layout.vamp_sdk, required=False),
        _check_native_host(layout),
        _directory_check(layout, "emsdk", "Emscripten SDK", layout.emsdk, required=False),
        _directory_check(
            layout,
            "signalsmith",
            "Signalsmith Stretch",
            layout.signalsmith,
            required=False,
        ),
        _check_recordings(layout),
    ]
    gpu_ok, gpu_detail = gpu()
    checks.append(
        _check(
            "gpu",
            "GPU (nvidia-smi)",
            gpu_ok,
            gpu_detail,
            required=False,
            path=Path(gpu_detail) if gpu_detail and Path(gpu_detail).exists() else None,
        )
    )
    return DoctorReport(tuple(checks))


__all__ = [
    "DoctorCheck",
    "DoctorLayout",
    "DoctorReport",
    "default_gpu_probe",
    "default_tool_probe",
    "diagnose",
]
