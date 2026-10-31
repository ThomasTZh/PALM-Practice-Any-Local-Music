"""In-process background jobs with cooperative cancellation and SSE progress.

Jobs are daemon threads: this is a local, single-user studio, so an external
worker queue would add moving parts without adding safety. A job runner receives
a :class:`JobContext`, reports progress and calls ``check_cancelled`` at natural
boundaries. Cancellation is a ``threading.Event`` and is therefore visible to a
running worker within one polling interval, which keeps the cancel path well
under the two-second requirement.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from basseparate.events import SSEEvent, encode_sse, heartbeat
from basseparate.projects import utc_now

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_JOB_STATES: frozenset[str] = TERMINAL_STATES


class JobError(Exception):
    """Base class for job failures that map to HTTP errors."""


class JobNotFound(JobError, KeyError):
    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


class JobCancelled(Exception):
    """Raised by a runner when the job was asked to stop."""


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    state: JobState
    progress: float
    message: str
    created_at: str
    updated_at: str
    result: object | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


JobRunner = Callable[["JobContext", Mapping[str, Any]], object]


class JobContext:
    def __init__(self, manager: JobManager, job_id: str, cancel_event: threading.Event) -> None:
        self._manager = manager
        self._job_id = job_id
        self._cancel_event = cancel_event
        self._progress = 0.0

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def progress_value(self) -> float:
        return self._progress

    def progress(self, fraction: float, message: str = "") -> None:
        value = max(0.0, min(1.0, float(fraction)))
        self._progress = value
        self._manager._update(self._job_id, progress=value, message=message)

    def check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise JobCancelled(self._job_id)


class JobManager:
    def __init__(self, *, poll_seconds: float = 0.02, heartbeat_seconds: float = 10.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll seconds must be positive")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat seconds must be positive")
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._runners: dict[str, JobRunner] = {}
        self._threads: dict[str, threading.Thread] = {}

    def register(self, kind: str, runner: JobRunner) -> None:
        with self._lock:
            self._runners[kind] = runner

    def submit(self, kind: str, params: Mapping[str, Any] | None = None) -> Job:
        with self._lock:
            runner = self._runners.get(kind)
        if runner is None:
            raise KeyError(f"unknown job kind {kind!r}")
        job_id = uuid.uuid4().hex
        timestamp = utc_now()
        job = Job(
            id=job_id,
            kind=kind,
            state="queued",
            progress=0.0,
            message="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        cancel_event = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = cancel_event
        thread = threading.Thread(
            target=self._run,
            args=(job_id, kind, runner, dict(params or {}), cancel_event),
            name=f"basseparate-job-{kind}-{job_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def list(self) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda job: (job.created_at, job.id))

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state in TERMINAL_STATES:
            return job
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is not None:
            event.set()
        return self._update(job_id, message="cancellation requested")

    def _update(self, job_id: str, **changes: object) -> Job:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise JobNotFound(job_id)
            updated = replace(current, updated_at=utc_now(), **changes)  # type: ignore[arg-type]
            self._jobs[job_id] = updated
            return updated

    def _run(
        self,
        job_id: str,
        kind: str,
        runner: JobRunner,
        params: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        context = JobContext(self, job_id, cancel_event)
        if cancel_event.is_set():
            self._update(job_id, state="cancelled", message="cancelled before start")
            return
        self._update(job_id, state="running", message="running")
        try:
            result = runner(context, params)
        except JobCancelled:
            self._update(job_id, state="cancelled", message="cancelled")
        except Exception as error:  # noqa: BLE001 - job boundary must capture everything
            self._update(
                job_id,
                state="failed",
                progress=context.progress_value,
                message="failed",
                error=f"{type(error).__name__}: {error}",
            )
        else:
            if cancel_event.is_set():
                self._update(job_id, state="cancelled", message="cancelled")
            else:
                self._update(
                    job_id,
                    state="succeeded",
                    progress=1.0,
                    message="finished",
                    result=result,
                )
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    async def stream_events(self, job_id: str) -> AsyncIterator[str]:
        """SSE frames for one job, ending after the terminal state.

        Polling keeps the implementation thread-agnostic; 20 ms latency is well
        inside what a practice UI needs and avoids an extra event loop bridge.
        """
        self.get(job_id)
        last: Job | None = None
        last_change = time.monotonic()
        while True:
            job = self.get(job_id)
            if job != last:
                event_name = "done" if job.state in TERMINAL_STATES else "progress"
                yield encode_sse(
                    SSEEvent(
                        event=event_name,
                        data=json.dumps(job.to_dict(), default=str, separators=(", ", ": ")),
                        id=job.updated_at,
                    )
                )
                last = job
                last_change = time.monotonic()
                if job.state in TERMINAL_STATES:
                    return
            elif time.monotonic() - last_change >= self.heartbeat_seconds:
                yield heartbeat()
                last_change = time.monotonic()
            await asyncio.sleep(self.poll_seconds)
