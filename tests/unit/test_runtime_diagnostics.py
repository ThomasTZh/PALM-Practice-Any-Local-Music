"""Unit tests for local runtime diagnostics (M2.12, spec §14.4)."""

from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from basseparate import runtime_diagnostics
from basseparate.runtime_diagnostics import (
    GpuMemory,
    GpuPeakTracker,
    RuntimeDiagnostics,
    parse_gpu_memory,
    parse_stat_cpu,
    parse_statm,
    query_gpu_memory,
    read_process_stats,
)


class TestProcParsing:
    def test_parse_statm_returns_resident_bytes(self) -> None:
        page = os.sysconf("SC_PAGE_SIZE")
        assert isinstance(page, int)
        assert parse_statm("1000 250 40 0 0 0 0") == 250 * page

    @pytest.mark.parametrize("text", ["", "1000", "1000 notanumber 0 0 0 0 0"])
    def test_parse_statm_rejects_bad_input(self, text: str) -> None:
        assert parse_statm(text) is None

    def test_parse_stat_cpu_handles_parentheses_in_command(self) -> None:
        # Fields after the comm: state, ppid..cmajflt (10 values),
        # utime, stime.
        text = "42 (weird ) name) S " + " ".join(["1"] * 10) + " 500 250 0 0"
        assert parse_stat_cpu(text, 100.0) == 7.5

    @pytest.mark.parametrize("text", ["", "no closing paren", "42 (x) S 1 2"])
    def test_parse_stat_cpu_rejects_bad_input(self, text: str) -> None:
        assert parse_stat_cpu(text, 100.0) is None

    def test_read_process_stats_for_self(self) -> None:
        stats = read_process_stats(os.getpid())
        assert stats.rss_bytes is not None and stats.rss_bytes > 0
        assert stats.cpu_seconds is not None and stats.cpu_seconds >= 0.0

    def test_read_process_stats_for_missing_pid(self) -> None:
        stats = read_process_stats(2**30)
        assert stats.rss_bytes is None
        assert stats.cpu_seconds is None


class TestGpu:
    def test_parse_gpu_memory(self) -> None:
        memory = parse_gpu_memory("24564, 20000\n")
        assert memory is not None
        assert memory.total_bytes == 24564 * 1024 * 1024
        assert memory.free_bytes == 20000 * 1024 * 1024

    @pytest.mark.parametrize("text", ["", "garbage", "1, 2, 3", "a, b"])
    def test_parse_gpu_memory_rejects_bad_input(self, text: str) -> None:
        assert parse_gpu_memory(text) is None

    def test_query_gpu_memory_without_nvidia_smi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime_diagnostics.shutil, "which", lambda name: None)
        assert query_gpu_memory() is None

    def test_tracker_remembers_peak(self) -> None:
        samples = iter(
            [GpuMemory(1000, 400), GpuMemory(1000, 100), GpuMemory(1000, 500)]
        )
        tracker = GpuPeakTracker(query=lambda: next(samples))
        tracker.sample()
        tracker.sample()
        assert tracker.peak_used_bytes == 900
        assert tracker.latest is not None and tracker.latest.free_bytes == 100
        tracker.sample()
        assert tracker.peak_used_bytes == 900
        assert tracker.latest.free_bytes == 500

    def test_tracker_ignores_unavailable_gpu(self) -> None:
        tracker = GpuPeakTracker(query=lambda: None)
        tracker.sample()
        assert tracker.latest is None
        assert tracker.peak_used_bytes is None

    def test_run_samples_only_while_busy(self) -> None:
        calls: list[int] = []
        busy = {"value": False}
        tracker = GpuPeakTracker(
            query=lambda: calls.append(1) or GpuMemory(1000, 500),
            should_sample=lambda: busy["value"],
        )

        async def scenario() -> None:
            task = asyncio.create_task(tracker.run(interval_seconds=0.005))
            await asyncio.sleep(0.03)
            assert calls == []
            busy["value"] = True
            await asyncio.sleep(0.05)
            tracker.stop()
            await task

        asyncio.run(scenario())
        assert calls
        assert tracker.peak_used_bytes == 500


class _StubJobManager:
    def __init__(
        self,
        *,
        active: uuid.UUID | None = None,
        queued: int = 0,
        worker_pid: int | None = None,
        record: Any = None,
    ) -> None:
        self.active_job_id = active
        self.queue_depth = queued
        self.worker_pid = worker_pid
        self._record = record

    async def get_job(self, job_id: uuid.UUID) -> Any:
        return self._record


class _StubSeparationRepository:
    def __init__(self, elapsed: float | None) -> None:
        self._elapsed = elapsed

    def latest_run_elapsed_seconds(self) -> float | None:
        return self._elapsed


class TestCollect:
    def test_shape_with_active_job(self) -> None:
        job_id = uuid.uuid4()
        record = SimpleNamespace(
            id=job_id,
            job_type=SimpleNamespace(value="waveform"),
            stage=SimpleNamespace(value="peaks"),
            progress_fraction=0.5,
        )
        manager = _StubJobManager(active=job_id, queued=2, worker_pid=os.getpid(), record=record)
        separation = _StubSeparationRepository(12.5)
        memory = GpuMemory(total_bytes=1000, free_bytes=600)
        tracker = GpuPeakTracker(query=lambda: memory)
        tracker.sample()
        diagnostics = RuntimeDiagnostics(
            job_manager=manager,  # type: ignore[arg-type]
            separation_repository=separation,  # type: ignore[arg-type]
            gpu_tracker=tracker,
        )

        data = asyncio.run(diagnostics.collect())

        assert data["api"]["rss_bytes"] is not None
        assert data["media_worker"]["rss_bytes"] is not None
        assert data["job"]["job_id"] == str(job_id)
        assert data["job"]["job_type"] == "waveform"
        assert data["job"]["stage"] == "peaks"
        assert data["job"]["progress_fraction"] == 0.5
        assert data["job"]["queued"] == 2
        assert data["gpu"]["total_bytes"] == 1000
        assert data["gpu"]["peak_used_bytes"] == 400
        assert data["separation_elapsed_seconds"] == 12.5

    def test_shape_without_jobs(self) -> None:
        manager = _StubJobManager()
        tracker = GpuPeakTracker(query=lambda: None)
        diagnostics = RuntimeDiagnostics(
            job_manager=manager,  # type: ignore[arg-type]
            separation_repository=_StubSeparationRepository(None),  # type: ignore[arg-type]
            gpu_tracker=tracker,
        )

        data = asyncio.run(diagnostics.collect())

        assert data["media_worker"] is None
        assert data["job"] is None
        assert data["gpu"] is None
        assert data["separation_elapsed_seconds"] is None
