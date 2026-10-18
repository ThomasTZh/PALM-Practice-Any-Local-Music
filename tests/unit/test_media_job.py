"""Tests for the durable media job domain model (M1.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from basseparate.domain.media_job import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidJobTransition,
    JobStage,
    JobState,
    JobType,
    MediaJob,
    assert_transition,
)

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


def _make_job(**overrides: object) -> MediaJob:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "job_type": JobType.PROBE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return MediaJob(**base)


class TestEnums:
    def test_job_types(self) -> None:
        assert {t.value for t in JobType} == {
            "probe",
            "canonical_decode",
            "monitoring_downmix",
            "playback_rate",
            "waveform",
            "export",
            "separation",
        }

    def test_job_states(self) -> None:
        assert {s.value for s in JobState} == {
            "queued",
            "running",
            "completed",
            "failed",
            "cancelling",
            "cancelled",
            "interrupted",
        }

    def test_job_stages(self) -> None:
        assert {s.value for s in JobStage} == {
            "transferring",
            "verifying",
            "inspecting",
            "decoding",
            "preparing_playback",
            "preparing_input",
            "separating",
            "building_waveform",
            "verifying_stems",
            "encoding",
            "verifying_export",
            "ready",
        }


class TestMediaJob:
    def test_defaults(self) -> None:
        job = _make_job()
        assert job.state is JobState.QUEUED
        assert job.import_id is None
        assert job.stage is None
        assert job.progress_fraction is None
        assert job.result is None
        assert job.max_threads == 4

    def test_is_terminal(self) -> None:
        assert _make_job(state=JobState.COMPLETED).is_terminal
        assert _make_job(state=JobState.FAILED).is_terminal
        assert _make_job(state=JobState.CANCELLED).is_terminal
        assert not _make_job().is_terminal
        assert not _make_job(state=JobState.RUNNING).is_terminal
        assert not _make_job(state=JobState.INTERRUPTED).is_terminal

    def test_frozen(self) -> None:
        job = _make_job()
        with pytest.raises(ValidationError):
            job.state = JobState.RUNNING  # type: ignore[misc]

    def test_progress_fraction_bounds(self) -> None:
        _make_job(progress_fraction=0.0)
        _make_job(progress_fraction=1.0)
        with pytest.raises(ValidationError):
            _make_job(progress_fraction=-0.1)
        with pytest.raises(ValidationError):
            _make_job(progress_fraction=1.1)

    def test_max_threads_bounds(self) -> None:
        _make_job(max_threads=1)
        _make_job(max_threads=32)
        with pytest.raises(ValidationError):
            _make_job(max_threads=0)
        with pytest.raises(ValidationError):
            _make_job(max_threads=33)

    def test_error_length_bounded(self) -> None:
        _make_job(error="x" * 2000)
        with pytest.raises(ValidationError):
            _make_job(error="x" * 2001)


class TestTransitionMap:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (JobState.QUEUED, JobState.RUNNING),
            (JobState.QUEUED, JobState.FAILED),
            (JobState.QUEUED, JobState.CANCELLING),
            (JobState.QUEUED, JobState.CANCELLED),
            (JobState.RUNNING, JobState.COMPLETED),
            (JobState.RUNNING, JobState.FAILED),
            (JobState.RUNNING, JobState.CANCELLING),
            (JobState.RUNNING, JobState.INTERRUPTED),
            (JobState.CANCELLING, JobState.CANCELLED),
            (JobState.CANCELLING, JobState.INTERRUPTED),
            (JobState.INTERRUPTED, JobState.QUEUED),
            (JobState.INTERRUPTED, JobState.RUNNING),
            (JobState.INTERRUPTED, JobState.CANCELLING),
        ],
    )
    def test_allowed_transitions(self, current: JobState, target: JobState) -> None:
        assert target in ALLOWED_TRANSITIONS[current]
        assert_transition(current, target)  # must not raise

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (JobState.COMPLETED, JobState.RUNNING),
            (JobState.FAILED, JobState.QUEUED),
            (JobState.CANCELLED, JobState.RUNNING),
            (JobState.RUNNING, JobState.CANCELLED),
            (JobState.RUNNING, JobState.QUEUED),
            (JobState.QUEUED, JobState.COMPLETED),
            (JobState.CANCELLING, JobState.RUNNING),
            (JobState.CANCELLING, JobState.QUEUED),
            (JobState.INTERRUPTED, JobState.COMPLETED),
        ],
    )
    def test_rejected_transitions(self, current: JobState, target: JobState) -> None:
        assert target not in ALLOWED_TRANSITIONS[current]
        with pytest.raises(InvalidJobTransition):
            assert_transition(current, target)

    def test_terminal_states_have_no_outgoing(self) -> None:
        for state in TERMINAL_STATES:
            assert ALLOWED_TRANSITIONS[state] == frozenset()

    def test_every_state_in_map(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == set(JobState)
