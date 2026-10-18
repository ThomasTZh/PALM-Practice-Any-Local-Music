"""Durable media job records (M1.4).

A media job is one unit of media processing (probe, canonical decode,
monitoring downmix, playback-rate conversion, waveform generation) tracked
durably in SQLite. The backend owns every state write; a worker process only
reports progress and result metadata.

State machine (enforced by the repository layer):

    queued → running → completed
                     → failed
                     → cancelling → cancelled
    queued → cancelled            (cancelled before it started)
    queued → failed               (failed before it started, e.g. no source)
    running / cancelling → interrupted   (on application restart)
    interrupted → queued / running / cancelling  (restart from a safe boundary)

Terminal states (completed, failed, cancelled) accept no transitions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import UtcTimestamp, Uuid


class JobType(StrEnum):
    PROBE = "probe"
    CANONICAL_DECODE = "canonical_decode"
    MONITORING_DOWNMIX = "monitoring_downmix"
    PLAYBACK_RATE = "playback_rate"
    WAVEFORM = "waveform"
    EXPORT = "export"
    SEPARATION = "separation"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobStage(StrEnum):
    """Progress stages reported by workers (milestone1.md §6.6)."""

    TRANSFERRING = "transferring"
    VERIFYING = "verifying"
    INSPECTING = "inspecting"
    DECODING = "decoding"
    PREPARING_PLAYBACK = "preparing_playback"
    PREPARING_INPUT = "preparing_input"
    SEPARATING = "separating"
    BUILDING_WAVEFORM = "building_waveform"
    VERIFYING_STEMS = "verifying_stems"
    ENCODING = "encoding"
    VERIFYING_EXPORT = "verifying_export"
    READY = "ready"


#: The only legal state transitions. Anything else is rejected.
ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset(
        {JobState.RUNNING, JobState.FAILED, JobState.CANCELLING, JobState.CANCELLED}
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLING,
            JobState.INTERRUPTED,
        }
    ),
    JobState.CANCELLING: frozenset({JobState.CANCELLED, JobState.INTERRUPTED}),
    JobState.INTERRUPTED: frozenset({JobState.QUEUED, JobState.RUNNING, JobState.CANCELLING}),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})

MAX_JOB_ERROR_LENGTH = 2000
MAX_JOB_PROGRESS_DETAIL_LENGTH = 512


class InvalidJobTransition(Exception):
    """Raised when a state transition is not allowed by the job state machine."""

    def __init__(self, current: JobState, requested: JobState) -> None:
        super().__init__(f"invalid job transition: {current.value} → {requested.value}")
        self.current = current
        self.requested = requested


def assert_transition(current: JobState, requested: JobState) -> None:
    """Raise InvalidJobTransition if ``current → requested`` is not allowed."""
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise InvalidJobTransition(current, requested)


class MediaJob(BaseModel):
    """One durable media-processing job."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    import_id: Uuid | None = None
    job_type: JobType
    state: JobState = JobState.QUEUED
    stage: JobStage | None = None
    #: Determinate progress in [0, 1]. Present only when a reliable
    #: denominator exists; otherwise the progress is indeterminate and
    #: ``progress_detail`` carries what is known.
    progress_fraction: float | None = Field(default=None, ge=0, le=1)
    progress_detail: str | None = Field(default=None, max_length=MAX_JOB_PROGRESS_DETAIL_LENGTH)
    #: Per-type result payload, set on completion (e.g. a ProbeResult dict).
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, max_length=MAX_JOB_ERROR_LENGTH)
    max_threads: int = Field(default=4, ge=1, le=32)
    #: Creation-time parameters persisted with the job (M1.7), e.g.
    #: ``{"target_sample_rate": 48000}`` for ``playback_rate`` jobs.
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
