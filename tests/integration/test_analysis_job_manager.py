"""Two-class job scheduling (M2.17, spec §14.3, §19.5).

Separation jobs run on the isolated analysis worker (real
``analysis/worker.py`` with a fake separator, no torch); media jobs keep
the media worker. The classes have independent queues and supervisors,
so a slow separation never blocks playback preparation.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import pytest

from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.jobs import JobManager
from basseparate.storage import JobRepository, ProjectRepository
from basseparate.storage.db import initialize_database

ANALYSIS_WORKER = Path(__file__).resolve().parents[2] / "analysis" / "worker.py"

FAKE_SEPARATOR = r'''
import argparse, json, sys, time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input")
parser.add_argument("--profile")
parser.add_argument("--bundle-dir")
parser.add_argument("--device", default="cpu")
parser.add_argument("--out", required=True)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--cancel")
parser.add_argument("--segment", type=float, default=7.5)
parser.add_argument("--window-seconds", type=float, default=120.0)
parser.add_argument("--overlap-seconds", type=float, default=8.0)
args = parser.parse_args()

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)


def record(status, **extra):
    (out / "run-record.json").write_text(json.dumps({"status": status, **extra}))


mode = Path(args.input).read_text().strip()
if mode == "fail":
    record("failed", error="synthetic separation failure")
    sys.exit(1)
if mode == "cancel":
    cancel = Path(args.cancel)
    for _ in range(1000):
        if cancel.exists():
            record("cancelled")
            sys.exit(2)
        time.sleep(0.01)
    record("failed", error="cancel flag was never written")
    sys.exit(1)

attempt = out / "attempt-1"
attempt.mkdir()
(attempt / "bass.pcm").write_bytes(b"fake-stem")
print(json.dumps({
    "type": "segment", "window": 1, "window_count": 1, "fraction": 0.5,
    "completed_units": 1, "total_units": 2,
}), flush=True)
if mode == "slow":
    time.sleep(1.5)
record(
    "complete", outputs=str(attempt), labels=["bass"], frames=5,
    device=args.device, timings={"seconds": 0.01},
)
print(json.dumps({
    "type": "final", "status": "complete", "record": str(out / "run-record.json"),
}), flush=True)
sys.exit(0)
'''

MEDIA_WORKER = r'''
import sys
from basseparate.worker.protocol import (
    decode_message, make_cancelled, make_capabilities, make_completed,
    make_hello, make_pong, make_stopped,
)

RESULT = {
    "cache_version": 1,
    "source_hash": "aa" * 32,
    "sample_rate": 44100,
    "frame_count": 128,
    "channel_count": 1,
    "final_bucket_frames": 64,
    "levels": [{
        "bucket_frame_count": 64, "bucket_count": 2,
        "tile_count": 1, "final_tile_buckets": 2,
    }],
    "manifest_path": "/tmp/media-worker/manifest.json",
}


def emit(message):
    sys.stdout.buffer.write(message.encode() + b"\n")
    sys.stdout.buffer.flush()


emit(make_hello("test-media"))
while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    message = decode_message(line.strip())
    if message.type == "ping":
        emit(make_pong(message.payload.nonce, request_id=message.message_id))
    elif message.type == "describe":
        emit(make_capabilities("test-media"))
    elif message.type == "run":
        emit(make_completed(message.payload.job_id, RESULT))
    elif message.type == "cancel":
        emit(make_cancelled(message.payload.job_id, True))
    elif message.type == "shutdown":
        emit(make_stopped(0))
        break
'''


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    db = tmp_path / "data" / "basseparate.db"
    initialize_database(db)
    projects = ProjectRepository(db)
    jobs = JobRepository(db)
    project = projects.create_project("Song")
    fake_separator = tmp_path / "fake_separator.py"
    fake_separator.write_text(FAKE_SEPARATOR, encoding="utf-8")
    media_worker = tmp_path / "media_worker.py"
    media_worker.write_text(MEDIA_WORKER, encoding="utf-8")
    media_source = tmp_path / "media-source.pcm"
    media_source.write_bytes(b"\x00" * 64)
    return {
        "root": tmp_path,
        "db": db,
        "projects": projects,
        "jobs": jobs,
        "project": project,
        "fake_separator": fake_separator,
        "media_worker": media_worker,
        "media_source": media_source,
    }


async def _separation_parameters(job: MediaJob, staging_dir: Path) -> dict:
    staging_dir.mkdir(parents=True, exist_ok=True)
    mode = str(job.parameters.get("mode", "complete"))
    input_path = staging_dir / "input.pcm"
    input_path.write_text(mode, encoding="utf-8")
    profile = staging_dir / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    bundle = staging_dir / "bundle"
    bundle.mkdir(exist_ok=True)
    return {
        "input_path": str(input_path),
        "profile_path": str(profile),
        "out_dir": str(staging_dir / "out"),
        "bundle_dir": str(bundle),
        "device": "cpu",
        "seed": 0,
    }


def _make_manager(
    env: dict,
    *,
    analysis_command: list[str] | None = None,
    events: list[tuple[JobType, float]] | None = None,
) -> JobManager:
    command = analysis_command or [
        sys.executable,
        str(ANALYSIS_WORKER),
        "--separate-script",
        str(env["fake_separator"]),
        "--python",
        sys.executable,
    ]
    return JobManager(
        repository=env["jobs"],
        staging_root=env["root"] / "jobs",
        worker_command=[sys.executable, str(env["media_worker"])],
        publisher=(
            lambda job, _result: events.append((job.job_type, time.monotonic()))
            if events is not None
            else None
        ),
        parameters_for=lambda job: {"source_path": str(env["media_source"])},
        analysis_worker_command=command,
        separation_parameters_for=_separation_parameters,
    )


async def _wait_terminal(mgr: JobManager, job_id: uuid.UUID, timeout: float = 30.0) -> MediaJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = await mgr.get_job(job_id)
        assert job is not None
        if job.is_terminal:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal state in {timeout}s")


async def _wait_state(
    mgr: JobManager, job_id: uuid.UUID, state: JobState, timeout: float = 20.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = await mgr.get_job(job_id)
        if job is not None and job.state is state:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {state.value}")


class TestAnalysisJobClass:
    def test_separation_completes_on_the_analysis_worker(self, env: dict) -> None:
        async def scenario() -> None:
            events: list[tuple[JobType, float]] = []
            mgr = _make_manager(env, events=events)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.SEPARATION, parameters={"mode": "complete"}
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.COMPLETED
                assert final.result is not None
                assert final.result["status"] == "complete"
                assert final.result["stem_labels"] == ["bass"]
                assert final.progress_fraction == 1.0
                assert [kind for kind, _ in events] == [JobType.SEPARATION]
                # The torch process is stopped once the analysis queue is idle.
                assert mgr.analysis_worker_pid is None
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_missing_analysis_runtime_fails_the_job(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(
                env, analysis_command=[str(env["root"] / "missing-python"), "worker.py"]
            )
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.SEPARATION, parameters={"mode": "complete"}
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "ANALYSIS_RUNTIME_UNAVAILABLE"

                # The media class still works.
                media = await mgr.create_job(env["project"].id, JobType.WAVEFORM)
                media_final = await _wait_terminal(mgr, media.id)
                assert media_final.state is JobState.COMPLETED
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_cancel_routes_to_the_analysis_worker(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.SEPARATION, parameters={"mode": "cancel"}
                )
                await _wait_state(mgr, job.id, JobState.RUNNING)
                await mgr.cancel_job(job.id)
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.CANCELLED
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_media_jobs_run_while_separation_runs(self, env: dict) -> None:
        async def scenario() -> None:
            events: list[tuple[JobType, float]] = []
            mgr = _make_manager(env, events=events)
            await mgr.start()
            try:
                separation = await mgr.create_job(
                    env["project"].id, JobType.SEPARATION, parameters={"mode": "slow"}
                )
                await _wait_state(mgr, separation.id, JobState.RUNNING)
                media = await mgr.create_job(env["project"].id, JobType.WAVEFORM)
                media_final = await _wait_terminal(mgr, media.id)
                separation_final = await _wait_terminal(mgr, separation.id)
                assert media_final.state is JobState.COMPLETED
                assert separation_final.state is JobState.COMPLETED
                # The media job finished inside the slow separation window.
                assert [kind for kind, _ in events] == [
                    JobType.WAVEFORM,
                    JobType.SEPARATION,
                ]
            finally:
                await mgr.stop()

        asyncio.run(scenario())
