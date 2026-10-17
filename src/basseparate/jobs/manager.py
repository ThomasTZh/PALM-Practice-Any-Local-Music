"""Async job manager: schedules durable media jobs on one worker (M1.4).

Scheduling rules (milestone1.md §6.5):
- One media-processing job at a time.
- The API stays responsive: all blocking work (database, worker I/O) runs
  in threads; the scheduler is a single asyncio task.
- Numerical/FFmpeg thread use is bounded per job via ``max_threads``.

Ownership (milestone1.md §6.4, §8.3.8): the backend owns every SQLite
write. The worker reports progress and result metadata; the backend
verifies the result and publishes it (via an injected publisher) while the
job is still ``running``, and only then marks it ``completed``. A failed or
cancelled job never publishes and never touches previously completed
assets.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from basseparate.domain.import_record import ProbeResult
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.domain.representation import (
    CanonicalDecodeResult,
    MonitoringDownmixResult,
    PlaybackRateResult,
)
from basseparate.domain.waveform import WaveformResult
from basseparate.storage import JobRepository
from basseparate.worker import (
    CancelledMessage,
    CompletedMessage,
    FailedMessage,
    ProgressMessage,
    WorkerExitedError,
    WorkerSupervisor,
    WorkerSupervisorError,
    assert_protocol_version,
    make_cancel,
    make_run,
    media_worker_command,
)

log = logging.getLogger(__name__)

#: Safety net: a healthy worker always answers; silence beyond this means
#: the worker is wedged and the job is failed.
_RECEIVE_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class _JobOutcome:
    kind: Literal["completed", "failed", "cancelled"]
    result: dict[str, Any] | None = None
    code: str | None = None
    message: str | None = None


class ParameterResolutionError(Exception):
    """The parameter builder cannot construct worker parameters for a job.

    The manager fails the job with the given code and message before the
    worker is involved (M1.7: monitoring downmix and playback rate).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


#: Job types whose worker parameters are built from project/import state.
_PARAMETERIZED_JOB_TYPES = frozenset(
    {
        JobType.CANONICAL_DECODE,
        JobType.MONITORING_DOWNMIX,
        JobType.PLAYBACK_RATE,
        JobType.WAVEFORM,
    }
)

#: Scheduling priority classes (M2.12, spec §14.3): playback preparation
#: runs before import-critical work, which runs before background
#: waveform generation. FIFO within one class via a monotonic sequence
#: number, so equal-priority jobs keep their arrival order.
_JOB_PRIORITY: dict[JobType, int] = {
    JobType.MONITORING_DOWNMIX: 0,
    JobType.PLAYBACK_RATE: 0,
    JobType.PROBE: 1,
    JobType.CANONICAL_DECODE: 1,
    JobType.WAVEFORM: 2,
}
_UNKNOWN_JOB_PRIORITY = 3


def _default_parameter_failure(job_type: JobType) -> tuple[str, str]:
    """Failure used when a parameter builder returns no parameters at all."""
    if job_type is JobType.CANONICAL_DECODE:
        return (
            "NO_STREAM_SELECTION",
            "no audio stream is selected for this import; select a stream before decoding",
        )
    return (
        "NO_CANONICAL",
        "the project has no canonical audio to derive this job from",
    )


class JobManager:
    """Owns the media worker subprocess and the durable job queue."""

    def __init__(
        self,
        repository: JobRepository,
        staging_root: Path,
        worker_command: Sequence[str] | None = None,
        source_path_for: Callable[[uuid.UUID], Path] | None = None,
        publisher: Callable[[MediaJob, dict[str, Any]], None] | None = None,
        parameters_for: Callable[[MediaJob], dict[str, Any]] | None = None,
        worker_memory_limit_mb: int | None = None,
    ) -> None:
        self._repo = repository
        self._staging_root = Path(staging_root)
        self._worker_command = (
            list(worker_command)
            if worker_command is not None
            else media_worker_command(worker_memory_limit_mb)
        )
        self._source_path_for = source_path_for
        self._publisher = publisher
        self._parameters_for = parameters_for
        self._supervisor: WorkerSupervisor | None = None
        #: (priority class, arrival sequence, job id) — M2.12 §14.3.
        self._queue: asyncio.PriorityQueue[tuple[int, int, uuid.UUID]] = asyncio.PriorityQueue()
        self._enqueue_sequence = 0
        self._scheduler_task: asyncio.Task[None] | None = None
        self._active_job_id: uuid.UUID | None = None
        self._known_job_ids: set[uuid.UUID] = set()

    @property
    def active_job_id(self) -> uuid.UUID | None:
        """The job currently running in the worker, if any."""
        return self._active_job_id

    @property
    def is_started(self) -> bool:
        return self._supervisor is not None

    @property
    def queue_depth(self) -> int:
        """Jobs waiting in the scheduler queue (diagnostics, M2.12 §14.4)."""
        return self._queue.qsize()

    @property
    def worker_pid(self) -> int | None:
        """PID of the media worker subprocess, if running (M2.12 §14.4)."""
        return self._supervisor.pid if self._supervisor is not None else None

    def _enqueue(self, job: MediaJob) -> None:
        """Insert a job at its class priority, FIFO within the class."""
        priority = _JOB_PRIORITY.get(job.job_type, _UNKNOWN_JOB_PRIORITY)
        self._enqueue_sequence += 1
        self._queue.put_nowait((priority, self._enqueue_sequence, job.id))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._supervisor is not None:
            raise RuntimeError("job manager already started")
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_staging()

        supervisor = WorkerSupervisor(command=self._worker_command, cwd=Path.cwd())
        supervisor.start()
        try:
            hello = await asyncio.to_thread(supervisor.wait_for_handshake)
        except BaseException:
            supervisor.stop()
            raise
        assert_protocol_version(hello)
        self._supervisor = supervisor

        interrupted = await asyncio.to_thread(self._repo.mark_interrupted)
        if interrupted:
            log.info("marked %d job(s) interrupted on startup", interrupted)

        queued = await asyncio.to_thread(self._repo.list_jobs_by_state, JobState.QUEUED)
        for job in queued:
            self._known_job_ids.add(job.id)
            self._enqueue(job)
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(), name="job-scheduler")
        log.info("job manager started (%d queued job(s) reloaded)", len(queued))

    async def stop(self) -> None:
        task = self._scheduler_task
        self._scheduler_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        supervisor = self._supervisor
        self._supervisor = None
        if supervisor is not None:
            await asyncio.to_thread(supervisor.stop)
        log.info("job manager stopped")

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def create_job(
        self,
        project_id: uuid.UUID,
        job_type: JobType,
        import_id: uuid.UUID | None = None,
        max_threads: int = 4,
        parameters: dict[str, Any] | None = None,
    ) -> MediaJob:
        if self._supervisor is None:
            raise RuntimeError("job manager is not started")
        job = await asyncio.to_thread(
            self._repo.create_job,
            project_id,
            job_type,
            import_id,
            max_threads,
            parameters,
        )
        self._enqueue(job)
        return job

    async def get_job(self, job_id: uuid.UUID) -> MediaJob | None:
        return await asyncio.to_thread(self._repo.get_job, job_id)

    async def list_project_jobs(self, project_id: uuid.UUID) -> list[MediaJob]:
        return await asyncio.to_thread(self._repo.list_jobs_for_project, project_id)

    async def cancel_job(self, job_id: uuid.UUID) -> MediaJob:
        """Request cancellation. Terminal jobs are returned unchanged."""
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(str(job_id))
        if job.is_terminal:
            return job
        if job.state is JobState.QUEUED:
            return await asyncio.to_thread(self._repo.set_state, job_id, JobState.CANCELLED)
        if job.state is JobState.RUNNING:
            updated = await asyncio.to_thread(self._repo.set_state, job_id, JobState.CANCELLING)
            supervisor = self._supervisor
            if supervisor is not None:
                with contextlib.suppress(WorkerSupervisorError):
                    await asyncio.to_thread(supervisor.send, make_cancel(job_id))
            return updated
        # cancelling: already in progress. interrupted: no live worker.
        return job

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        while True:
            _priority, _sequence, job_id = await self._queue.get()
            self._known_job_ids.add(job_id)
            job = await asyncio.to_thread(self._repo.get_job, job_id)
            if job is None or job.state is not JobState.QUEUED:
                continue  # cancelled while queued, or removed
            try:
                await self._run_job(job)
            except Exception as exc:  # noqa: BLE001 - never let one job kill the scheduler
                log.exception("job %s raised an unexpected error", job_id)
                if not job.is_terminal:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(
                            self._repo.fail_job,
                            job_id,
                            "INTERNAL_ERROR",
                            f"the scheduler failed while running the job: {exc!r}",
                        )

    def _resolve_source(self, job: MediaJob) -> Path | None:
        if job.import_id is None or self._source_path_for is None:
            return None
        path = self._source_path_for(job.import_id)
        return path if path.is_file() else None

    async def _run_job(self, job: MediaJob) -> None:
        supervisor = self._supervisor
        if supervisor is None:
            return
        job_id = job.id
        staging_dir = self._staging_root / job_id.hex / "staging"
        cleaned = False
        try:
            source_path = self._resolve_source(job)
            if source_path is None:
                await asyncio.to_thread(
                    self._repo.fail_job,
                    job_id,
                    "NO_SOURCE",
                    "the job has no import to read a source file from",
                )
                return
            parameters: dict[str, Any] = {}
            if job.job_type in _PARAMETERIZED_JOB_TYPES:
                if self._parameters_for is not None:
                    try:
                        parameters = self._parameters_for(job)
                    except ParameterResolutionError as exc:
                        await asyncio.to_thread(
                            self._repo.fail_job, job_id, exc.code, exc.message
                        )
                        return
                if not parameters:
                    code, message = _default_parameter_failure(job.job_type)
                    await asyncio.to_thread(self._repo.fail_job, job_id, code, message)
                    return

            try:
                staging_dir.mkdir(parents=True)
            except OSError as exc:
                await asyncio.to_thread(self._repo.fail_job, job_id, "STAGING_ERROR", str(exc))
                return

            await asyncio.to_thread(self._repo.set_state, job_id, JobState.RUNNING)
            await asyncio.to_thread(
                supervisor.send,
                make_run(
                    job_id,
                    job.job_type,
                    str(source_path),
                    str(staging_dir),
                    job.max_threads,
                    parameters,
                ),
            )
            self._active_job_id = job_id
            try:
                outcome = await self._await_job_completion(supervisor, job_id)
            finally:
                self._active_job_id = None

            if outcome.kind == "completed":
                await self._publish(job_id, outcome.result or {})
            elif outcome.kind == "failed":
                await asyncio.to_thread(
                    self._repo.fail_job,
                    job_id,
                    outcome.code or "JOB_FAILED",
                    outcome.message or "the job failed",
                )
            else:  # cancelled
                current = await asyncio.to_thread(self._repo.get_job, job_id)
                if current is not None and current.state is JobState.CANCELLING:
                    await asyncio.to_thread(self._repo.set_state, job_id, JobState.CANCELLED)
            # A publisher may have queued follow-up jobs out-of-band (M1.8
            # auto-queues a WAVEFORM job after a decode); pick them up.
            await self._enqueue_newly_queued()
            self._clean_staging(staging_dir)
            cleaned = True
        except WorkerExitedError:
            log.warning("worker exited while running job %s", job_id)
            current = await asyncio.to_thread(self._repo.get_job, job_id)
            if current is not None and current.state is JobState.RUNNING:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._repo.set_state, job_id, JobState.INTERRUPTED)
        except WorkerSupervisorError as exc:
            log.warning("worker error while running job %s: %s", job_id, exc)
            current = await asyncio.to_thread(self._repo.get_job, job_id)
            if current is not None and current.state is JobState.RUNNING:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self._repo.fail_job, job_id, "WORKER_ERROR", str(exc)[:2000]
                    )
        finally:
            self._active_job_id = None
            if not cleaned:
                self._clean_staging(staging_dir)

    async def _enqueue_newly_queued(self) -> None:
        """Queue durable jobs created outside ``create_job`` (M1.8 auto-queue).

        Publishers run synchronously in a worker thread and can only write
        the database row; the scheduler must discover and enqueue the new
        job itself.
        """
        queued = await asyncio.to_thread(self._repo.list_jobs_by_state, JobState.QUEUED)
        for job in queued:
            if job.id not in self._known_job_ids:
                self._known_job_ids.add(job.id)
                self._enqueue(job)

    async def _await_job_completion(
        self, supervisor: WorkerSupervisor, job_id: uuid.UUID
    ) -> _JobOutcome:
        while True:
            message = await asyncio.to_thread(supervisor.receive, _RECEIVE_TIMEOUT_SECONDS)
            if isinstance(message, ProgressMessage):
                if message.payload.job_id == job_id:
                    await asyncio.to_thread(
                        self._repo.set_progress,
                        job_id,
                        message.payload.stage,
                        message.payload.fraction,
                        message.payload.detail,
                    )
                continue
            if isinstance(message, CompletedMessage):
                if message.payload.job_id == job_id:
                    return _JobOutcome(kind="completed", result=message.payload.result)
                continue
            if isinstance(message, FailedMessage):
                if message.payload.job_id == job_id:
                    return _JobOutcome(
                        kind="failed",
                        code=message.payload.code,
                        message=message.payload.message,
                    )
                continue
            if isinstance(message, CancelledMessage):
                if message.payload.job_id == job_id:
                    return _JobOutcome(kind="cancelled")
                continue
            # Other messages (pong, capabilities, ...) are ignored.

    async def _publish(self, job_id: uuid.UUID, result: dict[str, Any]) -> MediaJob | None:
        """Verify the result, publish it, then persist completion.

        Ordering (milestone1.md §8.3.8): the publisher runs while the job is
        still ``running`` so a publisher failure can fail the job. A job only
        becomes ``completed`` after its references are committed, so a
        completed job always has its assets published.
        """
        job = await asyncio.to_thread(self._repo.get_job, job_id)
        if job is None:
            return None
        try:
            if job.job_type is JobType.PROBE:
                ProbeResult(**result)  # verify before publishing
            elif job.job_type is JobType.CANONICAL_DECODE:
                CanonicalDecodeResult(**result)
            elif job.job_type is JobType.MONITORING_DOWNMIX:
                MonitoringDownmixResult(**result)
            elif job.job_type is JobType.PLAYBACK_RATE:
                PlaybackRateResult(**result)
            elif job.job_type is JobType.WAVEFORM:
                WaveformResult(**result)
        except (ValueError, TypeError) as exc:
            log.warning("job %s result failed verification: %s", job_id, exc)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self._repo.fail_job, job_id, "RESULT_VERIFICATION", str(exc)[:2000]
                )
            return None
        if self._publisher is not None:
            try:
                await asyncio.to_thread(self._publisher, job, result)
            except Exception as exc:  # noqa: BLE001 - a publisher bug must not wedge jobs
                log.exception("publisher failed for job %s", job_id)
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self._repo.fail_job, job_id, "PUBLISH_FAILED", str(exc)[:2000]
                    )
                return None
        return await asyncio.to_thread(self._repo.complete_job, job_id, result)

    # ------------------------------------------------------------------
    # Staging cleanup
    # ------------------------------------------------------------------

    def _clean_staging(self, staging_dir: Path) -> None:
        if staging_dir.is_dir():
            shutil.rmtree(staging_dir, ignore_errors=True)
        parent = staging_dir.parent
        with contextlib.suppress(OSError):
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()

    def _cleanup_stale_staging(self) -> None:
        """Remove leftover staging from a previous run.

        At startup no worker is alive, so any staging content is incomplete
        and safe to remove. Committed sources are never touched.
        """
        if not self._staging_root.is_dir():
            return
        for entry in self._staging_root.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
