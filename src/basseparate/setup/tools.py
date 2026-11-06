"""Pinned external tool installation and status.

The source-checkout installer remains the implementation of the download and
AppImage extraction details; this module owns the data-root locations, status
and the setup-job boundary so the service and CLI share one API.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Any, cast

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.setup.errors import SetupCancelled, SetupInstallError

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]
ToolInstaller = Callable[[RuntimePaths, Progress | None, Cancel | None], None]


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    license: str
    target: str


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        id="sonic_visualiser",
        name="Sonic Visualiser / Piper",
        license="GPL-2.0-or-later",
        target="sv/squashfs-root/usr/bin/piper-vamp-simple-server",
    ),
    ToolSpec(
        id="vamp_plugin_pack",
        name="Vamp Plugin Pack",
        license="AGPL-3.0 (pack); individual plugins GPL/AGPL",
        target="vamp-plugins/qm-vamp-plugins.so",
    ),
)


def tools_status(runtime: RuntimePaths | None = None) -> dict[str, dict[str, object]]:
    active = runtime or runtime_paths()
    piper = active.tools_root / "sv" / "squashfs-root" / "usr" / "bin" / "piper-vamp-simple-server"
    plugin = active.tools_root / "vamp-plugins" / "qm-vamp-plugins.so"
    return {
        "sonic_visualiser": {
            "installed": piper.is_file(),
            "path": str(piper),
            "license": "GPL-2.0-or-later",
        },
        "vamp_plugin_pack": {
            "installed": plugin.is_file(),
            "path": str(plugin),
            "license": "AGPL-3.0 (pack); individual plugins GPL/AGPL",
        },
    }


def _load_legacy_installer(runtime: RuntimePaths) -> ModuleType:
    path = runtime.app_root / "scripts" / "install_tools.py"
    if not path.is_file():
        raise SetupInstallError(f"tool installer is missing: {path}")
    spec = importlib.util.spec_from_file_location("palm_legacy_install_tools", path)
    if spec is None or spec.loader is None:
        raise SetupInstallError(f"cannot load tool installer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    legacy = cast(Any, module)
    legacy.TOOLS = runtime.tools_root
    legacy.SV_DIR = runtime.tools_root / "sv"
    legacy.PLUGIN_DIR = runtime.tools_root / "plugins"
    legacy.NATIVE_PLUGIN_DIR = runtime.tools_root / "vamp-plugins"
    return module


def install_tools(
    runtime: RuntimePaths | None = None,
    *,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    installer: ToolInstaller | None = None,
) -> dict[str, dict[str, object]]:
    """Install the optional GPL tools below the writable tools root."""
    active = runtime or runtime_paths()
    active.ensure_data_path(active.tools_root)
    if installer is not None:
        if cancel is not None and cancel():
            raise SetupCancelled("tool installation cancelled")
        installer(active, progress, cancel)
        return tools_status(active)
    if all(item["installed"] for item in tools_status(active).values()):
        if progress is not None:
            progress(1.0, "tools already installed")
        return tools_status(active)
    module = _load_legacy_installer(active)
    try:
        if progress is not None:
            progress(0.05, "installing Sonic Visualiser")
        module.install_sonic_visualiser(force=False)
        if cancel is not None and cancel():
            raise SetupCancelled("tool installation cancelled")
        if progress is not None:
            progress(0.6, "installing Vamp plugin pack")
        module.install_plugin_pack(force=False)
    except SetupCancelled:
        raise
    except Exception as error:  # noqa: BLE001 - legacy installer error boundary
        raise SetupInstallError(f"tool installation failed: {error}") from error
    if progress is not None:
        progress(1.0, "tools installed")
    return tools_status(active)
