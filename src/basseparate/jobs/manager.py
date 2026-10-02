"""Async job manager: schedules durable media jobs on one worker (M1.4).

Scheduling rules (milestone1.md §6.5):
- One media-processing job at a time.
- The API stays responsive: all blocking work (database, worker I/O) runs
  in threads; the scheduler is a single asyncio task.
- Numerical/FFmpeg thread use is bounded per job via ``max_threads``.

Ownership (milestone1.md §6.4): the backend owns every SQLite write. The
worker reports progress and result metadata; the backend verifies the
result and publishes it (via an injected publisher) only after the job
state is durably ``completed``. A failed or cancelled job never publishes
and never touches previously completed assets.
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
from basseparate.storage import ImportRepository, JobRepository
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


class JobManager:
    """Owns the media worker subprocess and the durable job queue."""

    def __init__(
        self,
        repository: JobRepository,
        staging_root: Path,
        worker_command: Sequence[str] | None = None,
        source_path_for: Callable[[uuid.UUID], Path] | None = None,
        publisher: Callable[[MediaJob], None] | None = None,
    ) -> None:
        self._repo = repository
        self._staging_root = Path(staging_root)
        self._worker_command = (
            list(worker_command) if worker_command is not None else media_worker_command()
        )
        self._source_path_for = source_path_for
        self._publisher = publisher
        self._supervisor: WorkerSupervisor | None = None
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._scheduler_task: asyncio.Task[None] | None = None
        self._active_job_id: uuid.UUID | None = None

    @property
    def active_job_id(self) -> uuid.UUID | None:
        """The job currently running in the worker, if any."""
        return self._active_job_id

    @property
    def is_started(self) -> bool:
        return self._supervisor is not None

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
            await self._queue.put(job.id)
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
    ) -> MediaJob:
        if self._supervisor is None:
            raise RuntimeError("job manager is not started")
        job = await asyncio.to_thread(
            self._repo.create_job, project_id, job_type, import_id, max_threads
        )
        await self._queue.put(job.id)
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
            job_id = await self._queue.get()
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
        """Verify the result, persist completion, then run the publisher."""
        job = await asyncio.to_thread(self._repo.get_job, job_id)
        if job is None:
            return None
        try:
            if job.job_type is JobType.PROBE:
                ProbeResult(**result)  # verify before publishing
        except (ValueError, TypeError) as exc:
            log.warning("job %s result failed verification: %s", job_id, exc)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self._repo.fail_job, job_id, "RESULT_VERIFICATION", str(exc)[:2000]
                )
            return None
        completed = await asyncio.to_thread(self._repo.complete_job, job_id, result)
        if self._publisher is not None:
            try:
                self._publisher(completed)
            except Exception:  # noqa: BLE001 - a publisher bug must not wedge jobs
                log.exception("publisher failed for job %s", job_id)
        return completed

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


def build_import_publisher(import_repository: ImportRepository) -> Callable[[MediaJob], None]:
    """Backend publisher for probe jobs (milestone1.md §6.4.5).

    Persists the verified probe result on the import and auto-selects the
    single audio stream, mirroring the M1.3 inline-probe behavior.
    """

    def publish(job: MediaJob) -> None:
        if job.job_type is not JobType.PROBE:
            return
        if job.import_id is None or job.result is None:
            return
        probe = ProbeResult(**job.result)
        import_repository.set_probe_result(job.import_id, probe)
        if len(probe.audio_streams) == 1:
            import_repository.set_selected_stream(job.import_id, probe.audio_streams[0].index)

    return publish
