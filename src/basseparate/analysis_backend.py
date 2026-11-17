"""Internal analysis backend seam.

The feature parser, cache and HTTP result are backend-neutral. A backend turns
a mono signal into the raw Chordino/Key Detector/Bar and Beat Tracker feature
maps. Linux defaults to the preserved Piper host; Windows and macOS default to
the installed Sonic Annotator backend. The backend id and version are part of
the feature cache identity, so Piper and Sonic entries cannot collide.
"""

from __future__ import annotations

import concurrent.futures
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from basseparate.piper import (
    CancelCheck,
    FeatureMap,
    LoadedPlugin,
    PiperPaths,
    PiperSession,
)

PIPER_BACKEND_ID = "piper"
PIPER_BACKEND_VERSION = "1"
TAIL_PADDING_SECONDS = 2.0

ProgressReporter = Callable[[float, str], None]


class AnalysisBackendError(RuntimeError):
    """The selected analysis backend cannot be used."""


class AnalysisBackendUnavailable(AnalysisBackendError):
    """No backend is implemented for this platform."""


@dataclass(frozen=True)
class BackendPlugin:
    """Raw plugin identity and framing returned by a backend."""

    role: str
    display_name: str
    key: str
    version: str
    parameters: Mapping[str, float]
    block_size: int
    step_size: int


@dataclass(frozen=True)
class BackendResult:
    """Raw feature maps and plugin metadata; parsing stays in features.py."""

    features: Mapping[str, FeatureMap]
    plugins: tuple[BackendPlugin, ...]
    elapsed_seconds: float


@runtime_checkable
class AnalysisBackend(Protocol):
    """A source of the raw features the analysis parser consumes."""

    id: str
    version: str

    def analyze(
        self,
        signal: NDArray[np.float32],
        *,
        sample_rate: int,
        bpb: int,
        lead_in_seconds: float,
        specs: Sequence[tuple[str, Mapping[str, float]]],
        is_cancelled: CancelCheck | None = None,
        on_progress: ProgressReporter | None = None,
    ) -> BackendResult:
        """Return raw features keyed by plugin display name."""
        ...


class PiperBackend:
    """The existing Pyin/Piper pipeline behind the backend protocol."""

    id = PIPER_BACKEND_ID
    version = PIPER_BACKEND_VERSION

    def __init__(
        self,
        paths: PiperPaths | None = None,
        *,
        timeout_seconds: float = 600.0,
    ) -> None:
        self.paths = paths
        self.timeout_seconds = timeout_seconds

    @property
    def cache_identity(self) -> str:
        return f"{self.id}:{self.version}"

    def analyze(
        self,
        signal: NDArray[np.float32],
        *,
        sample_rate: int,
        bpb: int,
        lead_in_seconds: float,
        specs: Sequence[tuple[str, Mapping[str, float]]],
        is_cancelled: CancelCheck | None = None,
        on_progress: ProgressReporter | None = None,
    ) -> BackendResult:
        paths = self.paths or PiperPaths.for_project()
        names = [name for name, _ in specs]
        warm_up_frames = int(round(lead_in_seconds * sample_rate))
        beat_signal = signal
        if warm_up_frames > 0:
            lead = np.zeros(warm_up_frames, dtype=np.float32)
            tail = np.zeros(int(round(TAIL_PADDING_SECONDS * sample_rate)), dtype=np.float32)
            beat_signal = np.concatenate((lead, signal, tail))
        signals = dict.fromkeys(names, signal)
        if "Bar and Beat Tracker" in signals:
            signals["Bar and Beat Tracker"] = beat_signal

        fractions: dict[str, float] = dict.fromkeys(names, 0.0)
        progress_lock = threading.Lock()
        internal_cancel = threading.Event()

        def cancelled() -> bool:
            if internal_cancel.is_set():
                return True
            return is_cancelled is not None and is_cancelled()

        def report(display_name: str, processed: int, total: int) -> None:
            if on_progress is None:
                return
            fraction = (processed / total) if total > 0 else 1.0
            with progress_lock:
                fractions[display_name] = min(1.0, max(0.0, fraction))
                overall = sum(fractions.values()) / len(names)
            on_progress(min(1.0, max(0.0, overall)), display_name)

        def run_one(
            display_name: str, parameters: Mapping[str, float]
        ) -> tuple[str, LoadedPlugin, FeatureMap]:
            with PiperSession(
                paths,
                timeout_seconds=self.timeout_seconds,
                is_cancelled=cancelled,
                on_progress=report,
            ) as session:
                plugin, features = session.analyze(
                    display_name,
                    signals[display_name],
                    sample_rate=sample_rate,
                    parameters=parameters,
                )
            return display_name, plugin, features

        started = time.perf_counter()
        runs: list[tuple[str, LoadedPlugin, FeatureMap]] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(specs), thread_name_prefix="piper-analysis"
        ) as pool:
            futures = {name: pool.submit(run_one, name, parameters) for name, parameters in specs}
            try:
                for name, _ in specs:
                    runs.append(futures[name].result())
            except BaseException:
                internal_cancel.set()
                for future in futures.values():
                    future.cancel()
                raise
        elapsed = time.perf_counter() - started
        return BackendResult(
            features={name: features for name, _, features in runs},
            plugins=tuple(
                BackendPlugin(
                    role=name,
                    display_name=plugin.display_name,
                    key=plugin.key,
                    version=plugin.version,
                    parameters=plugin.parameters,
                    block_size=plugin.block_size,
                    step_size=plugin.step_size,
                )
                for name, plugin, _ in runs
            ),
            elapsed_seconds=elapsed,
        )


def default_backend() -> AnalysisBackend:
    """Return the installed backend for this platform.

    Linux uses the preserved Piper pipeline. Windows and macOS use Sonic
    Annotator plus the Vamp Plugin Pack installed by PALM Setup; a missing
    installation is reported when the backend first checks its tools.
    """
    platform = f"{sys.platform}"
    if platform.startswith("linux"):
        return PiperBackend()
    if platform.startswith(("win", "darwin")):
        # Lazy import: sonic_annotator imports the result types from this module.
        from basseparate.sonic_annotator import SonicAnnotatorBackend

        return SonicAnnotatorBackend()
    raise AnalysisBackendUnavailable(
        f"no analysis backend is implemented for {platform}; "
        "install the Linux Piper host or use Windows/macOS Sonic Annotator"
    )


def resolve_backend(
    backend: AnalysisBackend | None = None,
    *,
    piper_paths: PiperPaths | None = None,
    timeout_seconds: float = 600.0,
) -> AnalysisBackend:
    """Select an explicit backend, a PiperPaths-compatible Piper backend, or default."""
    if backend is not None:
        return backend
    if piper_paths is not None:
        # Preserve the old explicit-PiperPaths calling convention on any host.
        return PiperBackend(paths=piper_paths, timeout_seconds=timeout_seconds)
    return default_backend()


__all__ = [
    "AnalysisBackend",
    "AnalysisBackendError",
    "AnalysisBackendUnavailable",
    "BackendPlugin",
    "BackendResult",
    "PIPER_BACKEND_ID",
    "PIPER_BACKEND_VERSION",
    "PiperBackend",
    "ProgressReporter",
    "default_backend",
    "resolve_backend",
]
