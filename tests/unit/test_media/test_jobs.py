"""Background jobs: progress, terminal states and cancellation timing."""

from __future__ import annotations

import asyncio
import time

import pytest

from basseparate.jobs import JobContext, JobManager, JobNotFound


def wait_terminal(manager: JobManager, job_id: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.get(job_id).state
        if state in {"succeeded", "failed", "cancelled"}:
            return state
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish: {manager.get(job_id)}")


def wait_progress(manager: JobManager, job_id: str, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.get(job_id).progress > 0:
            return
        time.sleep(0.01)
    raise AssertionError("job never reported progress")


def test_job_reports_progress_and_result() -> None:
    manager = JobManager(poll_seconds=0.01)
    seen: list[float] = []

    def runner(ctx: JobContext, params: dict) -> dict:
        for step in range(4):
            seen.append(ctx.progress_value)
            ctx.progress((step + 1) / 4, f"step {step}")
        return {"ok": True, **params}

    manager.register("steps", runner)
    job = manager.submit("steps", {"value": 7})
    assert job.state in {"queued", "running", "succeeded"}
    assert wait_terminal(manager, job.id) == "succeeded"
    done = manager.get(job.id)
    assert done.progress == 1.0
    assert done.result == {"ok": True, "value": 7}
    assert len(seen) == 4


def test_job_failure_is_captured() -> None:
    manager = JobManager(poll_seconds=0.01)

    def runner(ctx: JobContext, params: dict) -> None:
        ctx.progress(0.5, "about to fail")
        raise RuntimeError("decoder exploded")

    manager.register("boom", runner)
    job = manager.submit("boom")
    assert wait_terminal(manager, job.id) == "failed"
    done = manager.get(job.id)
    assert done.error is not None and "decoder exploded" in done.error
    assert done.state == "failed"


def test_cancel_stops_a_cooperative_job_within_two_seconds() -> None:
    manager = JobManager(poll_seconds=0.01)
    started = time.monotonic()

    def runner(ctx: JobContext, params: dict) -> None:
        while True:
            ctx.check_cancelled()
            ctx.progress(0.4, "waiting")
            time.sleep(0.02)

    manager.register("cooperative", runner)
    job = manager.submit("cooperative")
    wait_progress(manager, job.id)
    manager.cancel(job.id)
    state = wait_terminal(manager, job.id)
    elapsed = time.monotonic() - started
    assert state == "cancelled"
    assert elapsed < 2.0
    assert manager.get(job.id).error is None


def test_cancel_before_worker_starts_still_ends_cancelled() -> None:
    manager = JobManager(poll_seconds=0.01)
    manager.register("slow", lambda ctx, params: time.sleep(1))
    job = manager.submit("slow")
    manager.cancel(job.id)
    assert wait_terminal(manager, job.id) == "cancelled"


def test_unknown_kind_and_job_are_reported() -> None:
    manager = JobManager()
    with pytest.raises(KeyError, match="unknown job kind"):
        manager.submit("nope")
    with pytest.raises(JobNotFound):
        manager.get("missing")
    with pytest.raises(JobNotFound):
        manager.cancel("missing")


def test_cancel_after_terminal_state_is_idempotent() -> None:
    manager = JobManager(poll_seconds=0.01)
    manager.register("quick", lambda ctx, params: "done")
    job = manager.submit("quick")
    assert wait_terminal(manager, job.id) == "succeeded"
    snapshot = manager.cancel(job.id)
    assert snapshot.state == "succeeded"


def test_stream_events_yields_progress_and_done_frames() -> None:
    manager = JobManager(poll_seconds=0.005)

    def runner(ctx: JobContext, params: dict) -> str:
        ctx.progress(0.5, "half")
        time.sleep(0.1)
        return "finished"

    manager.register("streamed", runner)
    job = manager.submit("streamed")

    async def collect() -> list[str]:
        return [frame async for frame in manager.stream_events(job.id)]

    frames = asyncio.run(collect())
    assert frames
    joined = "".join(frames)
    assert "event: progress" in joined
    assert "event: done" in joined
    assert '"state": "succeeded"' in joined
    assert joined.endswith("\n\n")


def test_jobs_are_addressable_and_listed() -> None:
    manager = JobManager(poll_seconds=0.01)
    manager.register("noop", lambda ctx, params: None)
    first = manager.submit("noop")
    second = manager.submit("noop")
    wait_terminal(manager, first.id)
    wait_terminal(manager, second.id)
    assert {job.id for job in manager.list()} == {first.id, second.id}
    assert manager.get(first.id).state == "succeeded"
