"""Local runtime diagnostics for the API process (M2.12, spec §14.4).

Everything here is local-only: procfs, a bounded ``nvidia-smi`` query,
and the job/separation repositories. Nothing is ever sent off the
machine, and nothing here mutates application state.

The collector is intentionally small and synchronous on the request
path (reading two procfs files and one SQLite row); the only timed
work — the GPU peak sampler — runs as a background task that samples
while a job is active.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from basseparate.jobs import JobManager
from basseparate.storage import SeparationRepository

#: GPU sampling cadence while a job is active (seconds).
_GPU_SAMPLE_SECONDS = 5.0
_GPU_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ProcessStats:
    """Resident memory and cumulative CPU time of one process."""

    rss_bytes: int | None
    cpu_seconds: float | None


@dataclass(frozen=True, slots=True)
class GpuMemory:
    total_bytes: int
    free_bytes: int


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


def _clock_ticks() -> float | None:
    try:
        value = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):  # pragma: no cover - non-POSIX
        return None
    if not isinstance(value, int) or value <= 0:
        return None
    return float(value)


def parse_statm(text: str) -> int | None:
    """Resident bytes from one ``/proc/<pid>/statm`` line."""

    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        pages = int(parts[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None
    if not isinstance(page_size, int) or page_size <= 0:
        return None
    return pages * page_size


def parse_stat_cpu(text: str, clock_ticks: float) -> float | None:
    """``utime + stime`` in seconds from one ``/proc/<pid>/stat`` line.

    The stat format puts the command in parentheses (which may itself
    contain spaces and parentheses), so parsing starts after the last
    ``)``: the next field is the state, then utime (field 14) and stime
    (field 15).
    """

    try:
        closing = text.rindex(")")
        fields = text[closing + 2 :].split()
        utime = int(fields[11])
        stime = int(fields[12])
    except (ValueError, IndexError):
        return None
    return (utime + stime) / clock_ticks


def read_process_stats(pid: int) -> ProcessStats:
    """Sample RSS/CPU for one process; missing files become ``None``s."""

    rss: int | None = None
    statm = _read_text(Path("/proc") / str(pid) / "statm")
    if statm is not None:
        rss = parse_statm(statm)
    cpu: float | None = None
    ticks = _clock_ticks()
    stat = _read_text(Path("/proc") / str(pid) / "stat")
    if ticks is not None and stat is not None:
        cpu = parse_stat_cpu(stat, ticks)
    return ProcessStats(rss_bytes=rss, cpu_seconds=cpu)


def parse_gpu_memory(text: str) -> GpuMemory | None:
    """First GPU line of ``nvidia-smi --format=csv,noheader,nounits`` output."""

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    parts = [part.strip() for part in lines[0].split(",")]
    if len(parts) != 2:
        return None
    try:
        total_mib = int(parts[0])
        free_mib = int(parts[1])
    except ValueError:
        return None
    return GpuMemory(total_bytes=total_mib * 1024 * 1024, free_bytes=free_mib * 1024 * 1024)


def query_gpu_memory() -> GpuMemory | None:
    """Total/free GPU memory via ``nvidia-smi`` (first GPU), or ``None``."""

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None
    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=_GPU_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_gpu_memory(proc.stdout or "")


class GpuPeakTracker:
    """Tracks the peak observed GPU memory use while a job is active."""

    def __init__(
        self,
        query: Callable[[], GpuMemory | None] = query_gpu_memory,
        should_sample: Callable[[], bool] = lambda: True,
    ) -> None:
        self._query = query
        self._should_sample = should_sample
        self._latest: GpuMemory | None = None
        self._peak_used_bytes: int | None = None
        self._stop = asyncio.Event()

    def sample(self) -> None:
        memory = self._query()
        if memory is None:
            return
        self._latest = memory
        used = max(0, memory.total_bytes - memory.free_bytes)
        if self._peak_used_bytes is None or used > self._peak_used_bytes:
            self._peak_used_bytes = used

    async def run(self, interval_seconds: float = _GPU_SAMPLE_SECONDS) -> None:
        """Sample on a timer while ``should_sample`` says the app is busy."""

        while not self._stop.is_set():
            if self._should_sample():
                self.sample()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval_seconds)

    def stop(self) -> None:
        self._stop.set()

    @property
    def latest(self) -> GpuMemory | None:
        return self._latest

    @property
    def peak_used_bytes(self) -> int | None:
        return self._peak_used_bytes


class RuntimeDiagnostics:
    """Composes one local diagnostics snapshot (spec §14.4)."""

    def __init__(
        self,
        job_manager: JobManager,
        separation_repository: SeparationRepository,
        gpu_tracker: GpuPeakTracker,
    ) -> None:
        self._jobs = job_manager
        self._separation = separation_repository
        self._gpu = gpu_tracker

    async def collect(self) -> dict[str, Any]:
        api = read_process_stats(os.getpid())
        worker_pid = self._jobs.worker_pid
        worker = read_process_stats(worker_pid) if worker_pid is not None else None
        job: dict[str, Any] | None = None
        active = self._jobs.active_job_id
        if active is not None:
            record = await self._jobs.get_job(active)
            if record is not None:
                job = {
                    "job_id": str(record.id),
                    "job_type": record.job_type.value,
                    "stage": record.stage.value if record.stage is not None else None,
                    "progress_fraction": record.progress_fraction,
                    "queued": self._jobs.queue_depth,
                }
        if job is None and self._jobs.queue_depth > 0:
            job = {"queued": self._jobs.queue_depth}
        gpu: dict[str, Any] | None = None
        memory = self._gpu.latest
        if memory is not None:
            gpu = {
                "total_bytes": memory.total_bytes,
                "free_bytes": memory.free_bytes,
                "peak_used_bytes": self._gpu.peak_used_bytes,
            }
        return {
            "api": {"rss_bytes": api.rss_bytes, "cpu_seconds": api.cpu_seconds},
            "media_worker": (
                None
                if worker is None
                else {"rss_bytes": worker.rss_bytes, "cpu_seconds": worker.cpu_seconds}
            ),
            "job": job,
            "gpu": gpu,
            "separation_elapsed_seconds": self._separation.latest_run_elapsed_seconds(),
        }
