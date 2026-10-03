"""JobManager integration tests (M1.4).

Covers the durable scheduling loop end to end: probe to completion with
publishing, unimplemented job types, cancellation of queued and running
jobs, restart recovery, and the acceptance property that a completed
result survives a later failed job.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import time
import uuid
from pathlib import Path

import pytest

from basseparate.app import _decode_parameters_for
from basseparate.domain.import_record import TransferState
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.jobs import JobManager, build_import_publisher, build_publishers
from basseparate.storage import (
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
)
from basseparate.storage.db import initialize_database

SLEEP_WORKER = """
import os
import shutil
import sys
import threading
import time

from basseparate.worker.protocol import (
    decode_message,
    make_cancelled,
    make_capabilities,
    make_completed,
    make_hello,
    make_pong,
    make_progress,
    make_stopped,
)

lock = threading.Lock()
cancel = threading.Event()
active = {"thread": None, "staging": None}


def emit(msg):
    with lock:
        sys.stdout.buffer.write(msg.encode() + b"\\n")
        sys.stdout.buffer.flush()


def run_job(job_id, staging):
    os.makedirs(staging, exist_ok=True)
    with open(os.path.join(staging, "marker"), "w") as f:
        f.write("partial")
    active["staging"] = staging
    emit(make_progress(job_id, "decoding", fraction=0.5, detail="simulated"))
    deadline = time.monotonic() + 120
    while not cancel.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    if cancel.is_set():
        removed = False
        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)
            removed = not os.path.exists(staging)
        emit(make_cancelled(job_id, staging_removed=removed))
    else:
        emit(make_completed(job_id, {"ok": True}))


emit(make_hello("test-media"))
while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    msg = decode_message(line)
    if msg.type == "ping":
        emit(make_pong(msg.payload.nonce, request_id=msg.message_id))
    elif msg.type == "describe":
        emit(make_capabilities("test-media"))
    elif msg.type == "run":
        if active["thread"] is not None and active["thread"].is_alive():
            continue
        t = threading.Thread(
            target=run_job, args=(msg.payload.job_id, msg.payload.staging_dir), daemon=True
        )
        active["thread"] = t
        t.start()
    elif msg.type == "cancel":
        cancel.set()
    elif msg.type == "shutdown":
        if active["thread"] is not None and active["thread"].is_alive():
            cancel.set()
            active["thread"].join(timeout=10)
        emit(make_stopped(0))
        break
"""


def _make_wav() -> bytes:
    pcm = b"\x00\x00" * 4410
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


@pytest.fixture()
def env(tmp_path: Path):
    """DB + project + completed import + source file, ready for jobs."""
    import hashlib

    (tmp_path / "uploads").mkdir()
    db = tmp_path / "basseparate.db"
    initialize_database(db)
    projects = ProjectRepository(db)
    imports = ImportRepository(db)
    jobs = JobRepository(db)
    project = projects.create_project("manager")

    wav_bytes = _make_wav()
    import_record = imports.create_import(project.id, "tone.wav", len(wav_bytes))
    source = tmp_path / "uploads" / f"{import_record.id}.part"
    source.write_bytes(wav_bytes)
    imports.update_transfer_state(
        import_record.id,
        TransferState.COMPLETE,
        received_byte_count=len(wav_bytes),
        source_sha256=hashlib.sha256(wav_bytes).hexdigest(),
    )
    import_record = imports.get_import(import_record.id)  # refresh (frozen model)

    def source_path_for(import_id: uuid.UUID) -> Path:
        return tmp_path / "uploads" / f"{import_id}.part"

    paths = StoragePaths(
        config=tmp_path / "config",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
        runtime=tmp_path / "runtime",
    )

    return {
        "root": tmp_path,
        "db": db,
        "projects": projects,
        "imports": imports,
        "jobs": jobs,
        "representations": RepresentationRepository(db),
        "paths": paths,
        "project": project,
        "import": import_record,
        "source": source,
        "source_path_for": source_path_for,
    }


def _make_manager(
    env: dict,
    worker_command: list[str] | None = None,
    publisher: object = None,
    parameters_for: object = None,
) -> JobManager:
    return JobManager(
        repository=env["jobs"],
        staging_root=env["root"] / "jobs",
        worker_command=worker_command,
        source_path_for=env["source_path_for"],
        publisher=publisher
        if publisher is not None
        else build_import_publisher(env["imports"]),
        parameters_for=parameters_for,
    )


async def _wait_terminal(mgr: JobManager, job_id: uuid.UUID, timeout: float = 30.0) -> MediaJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = await mgr.get_job(job_id)
        assert job is not None
        if job.is_terminal:
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state in {timeout}s")


class TestProbeCompletion:
    def test_probe_job_completes_and_publishes(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.COMPLETED
                assert final.stage.value == "ready"
                assert final.progress_fraction == 1.0
                assert final.result is not None
                assert final.result["format_name"] == "wav"
                assert len(final.result["audio_streams"]) == 1

                # The publisher persisted the probe result on the import and
                # auto-selected the single stream.
                import_record = env["imports"].get_import(env["import"].id)
                assert import_record.transfer_state is TransferState.COMPLETE
                assert import_record.probe_result is not None
                assert import_record.probe_result.format_name == "wav"
                assert import_record.selected_stream_index == 0

                # Staging was cleaned up.
                staging = env["root"] / "jobs" / job.id.hex / "staging"
                assert not staging.exists()
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_unimplemented_type_fails(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.MONITORING_DOWNMIX, import_id=env["import"].id
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "JOB_TYPE_NOT_IMPLEMENTED"
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_job_without_source_fails(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                job = await mgr.create_job(env["project"].id, JobType.PROBE)  # no import
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "NO_SOURCE"
            finally:
                await mgr.stop()

        asyncio.run(scenario())


class TestCancellation:
    def test_cancel_queued_job(self, env: dict) -> None:
        async def scenario() -> None:
            script = env["root"] / "sleep_worker.py"
            script.write_text(SLEEP_WORKER)
            mgr = _make_manager(env, worker_command=[sys.executable, str(script)])
            await mgr.start()
            try:
                # Occupy the worker with a long simulated job.
                long_job = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                # The probe job queued behind it (one job at a time).
                queued = await mgr.create_job(
                    env["project"].id, JobType.WAVEFORM, import_id=env["import"].id
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (await mgr.get_job(long_job.id)).state is JobState.RUNNING:
                        break
                    await asyncio.sleep(0.05)
                assert (await mgr.get_job(queued.id)).state is JobState.QUEUED

                cancelled = await mgr.cancel_job(queued.id)
                assert cancelled.state is JobState.CANCELLED

                # The running job is untouched by the queued cancellation.
                assert (await mgr.get_job(long_job.id)).state is JobState.RUNNING
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_cancel_running_job(self, env: dict) -> None:
        async def scenario() -> None:
            script = env["root"] / "sleep_worker.py"
            script.write_text(SLEEP_WORKER)
            mgr = _make_manager(env, worker_command=[sys.executable, str(script)])
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                staging = env["root"] / "jobs" / job.id.hex / "staging"

                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (await mgr.get_job(job.id)).state is JobState.RUNNING:
                        break
                    await asyncio.sleep(0.05)

                cancelling = await mgr.cancel_job(job.id)
                assert cancelling.state is JobState.CANCELLING

                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.CANCELLED
                assert not staging.exists()
                assert mgr.active_job_id is None
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_cancel_terminal_job_is_noop(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                await _wait_terminal(mgr, job.id)
                again = await mgr.cancel_job(job.id)
                assert again.state is JobState.COMPLETED
            finally:
                await mgr.stop()

        asyncio.run(scenario())


class TestRestartRecovery:
    def test_running_jobs_become_interrupted_on_start(self, env: dict) -> None:
        job = env["jobs"].create_job(env["project"].id, JobType.PROBE, import_id=env["import"].id)
        env["jobs"].set_state(job.id, JobState.RUNNING)
        env["jobs"].set_state(job.id, JobState.CANCELLING)
        stuck = env["jobs"].create_job(env["project"].id, JobType.PROBE, import_id=env["import"].id)

        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                assert env["jobs"].get_job(job.id).state is JobState.INTERRUPTED
                # The queued job was reloaded into the scheduler; it runs to
                # completion (the source exists) or fails deterministically.
                final = await _wait_terminal(mgr, stuck.id)
                assert final.state is JobState.COMPLETED
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_stale_staging_is_cleaned_on_start(self, env: dict) -> None:
        stale = env["root"] / "jobs" / "stalejob" / "staging"
        stale.mkdir(parents=True)
        (stale / "junk").write_bytes(b"leftover")

        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                assert not stale.exists()
            finally:
                await mgr.stop()

        asyncio.run(scenario())


class TestSafety:
    def test_completed_result_survives_later_failure(self, env: dict) -> None:
        """Acceptance property: a failed job cannot corrupt a completed asset."""

        async def scenario() -> None:
            mgr = _make_manager(env)
            await mgr.start()
            try:
                first = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                first_final = await _wait_terminal(mgr, first.id)
                assert first_final.state is JobState.COMPLETED
                good_result = first_final.result
                assert good_result is not None

                # A second job that fails (its source is not a media file).
                bad_bytes = b"not a media file"
                bad_source = env["root"] / "uploads" / "bad.part"
                bad_source.write_bytes(bad_bytes)
                import_record = env["imports"].create_import(
                    env["project"].id, "bad.wav", len(bad_bytes)
                )
                env["imports"].update_transfer_state(
                    import_record.id,
                    TransferState.COMPLETE,
                    received_byte_count=len(bad_bytes),
                    source_sha256="0" * 64,
                )
                bad = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=import_record.id
                )
                bad_final = await _wait_terminal(mgr, bad.id)
                assert bad_final.state is JobState.FAILED

                # The completed job's result is intact.
                reloaded = await mgr.get_job(first.id)
                assert reloaded.state is JobState.COMPLETED
                assert reloaded.result == good_result
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_cancelled_job_publishes_nothing(self, env: dict) -> None:
        async def scenario() -> None:
            script = env["root"] / "sleep_worker.py"
            script.write_text(SLEEP_WORKER)
            mgr = _make_manager(env, worker_command=[sys.executable, str(script)])
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.PROBE, import_id=env["import"].id
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (await mgr.get_job(job.id)).state is JobState.RUNNING:
                        break
                    await asyncio.sleep(0.05)
                await mgr.cancel_job(job.id)
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.CANCELLED
                assert final.result is None

                # The import was never touched by a cancelled job.
                import_record = env["imports"].get_import(env["import"].id)
                assert import_record.probe_result is None
            finally:
                await mgr.stop()

        asyncio.run(scenario())


class TestDecodeCompletion:
    """M1.5: canonical decode end to end with the real worker + ffmpeg."""

    def _decode_manager(self, env: dict) -> JobManager:
        return _make_manager(
            env,
            publisher=build_publishers(
                env["imports"],
                env["projects"],
                env["representations"],
                env["paths"],
            ),
            parameters_for=lambda job: _decode_parameters_for(job, env["imports"]),
        )

    async def _probe_first(self, env: dict, mgr: JobManager) -> None:
        probe = await mgr.create_job(
            env["project"].id, JobType.PROBE, import_id=env["import"].id
        )
        final = await _wait_terminal(mgr, probe.id)
        assert final.state is JobState.COMPLETED
        import_record = env["imports"].get_import(env["import"].id)
        assert import_record.probe_result is not None
        assert import_record.selected_stream_index == 0

    def test_decode_completes_and_publishes(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = self._decode_manager(env)
            await mgr.start()
            try:
                await self._probe_first(env, mgr)
                job = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.COMPLETED
                result = final.result
                assert result is not None
                assert result["frame_count"] == 4410
                assert result["sample_rate"] == 44100
                assert result["channel_count"] == 1
                assert result["channel_layout"] == "mono"
                content_hash = result["content_hash"]

                # The PCM asset is content-addressed on disk.
                pcm_asset = env["projects"].get_asset_by_hash(content_hash)
                assert pcm_asset is not None
                assert pcm_asset.role.value == "source_pcm"
                assert pcm_asset.relative_path == f"data/assets/{content_hash}.pcm"
                assert pcm_asset.audio is not None
                assert pcm_asset.audio.frame_count == 4410
                on_disk = env["paths"].data / "assets" / f"{content_hash}.pcm"
                assert on_disk.is_file()
                assert on_disk.stat().st_size == 4410 * 4

                # The original upload is registered as an asset.
                original = env["projects"].get_asset_by_hash(env["import"].source_sha256)
                assert original is not None
                assert original.role.value == "source_original"
                assert original.relative_path == f"runtime/uploads/{env['import'].id}.part"

                # The project is ready with all eight source fields.
                project = env["projects"].get_project(env["project"].id)
                assert project.status.value == "ready"
                assert project.source_asset_id == original.id
                assert project.canonical_asset_id == pcm_asset.id
                assert project.source_stream_index == 0
                assert project.sample_rate == 44100
                assert project.duration_frames == 4410
                assert project.source_channel_count == 1
                assert project.source_channel_layout == "mono"
                assert project.decode_profile_version == 1

                # The canonical representation is registered (identity mapping).
                rep = env["representations"].get_representation(pcm_asset.id)
                assert rep is not None
                assert rep.role.value == "canonical"
                assert rep.is_identity

                # Staging was cleaned up.
                staging = env["root"] / "jobs" / job.id.hex / "staging"
                assert not staging.exists()
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_redecode_reuses_assets(self, env: dict) -> None:
        async def scenario() -> None:
            import sqlite3

            mgr = self._decode_manager(env)
            await mgr.start()
            try:
                await self._probe_first(env, mgr)
                first = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                first_final = await _wait_terminal(mgr, first.id)
                assert first_final.state is JobState.COMPLETED
                assert first_final.result is not None
                content_hash = first_final.result["content_hash"]

                second = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                second_final = await _wait_terminal(mgr, second.id)
                assert second_final.state is JobState.COMPLETED
                assert second_final.result is not None
                assert second_final.result["content_hash"] == content_hash

                pcm = env["projects"].get_asset_by_hash(content_hash)
                assert pcm is not None
                conn = sqlite3.connect(env["db"])
                try:
                    attach_count = conn.execute(
                        "SELECT COUNT(*) FROM project_assets WHERE project_id = ?",
                        (str(env["project"].id),),
                    ).fetchone()[0]
                    rep_count = conn.execute(
                        "SELECT COUNT(*) FROM representations WHERE asset_id = ?",
                        (str(pcm.id),),
                    ).fetchone()[0]
                finally:
                    conn.close()
                assert attach_count == 2  # original + PCM, no duplicates
                assert rep_count == 1
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_decode_without_stream_selection_fails(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(
                env,
                publisher=build_publishers(
                    env["imports"],
                    env["projects"],
                    env["representations"],
                    env["paths"],
                ),
                parameters_for=lambda job: {},
            )
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "NO_STREAM_SELECTION"
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_publisher_failure_fails_job(self, env: dict) -> None:
        probe_publisher = build_import_publisher(env["imports"])

        def broken_publisher(job: MediaJob, result: dict) -> None:
            if job.job_type is JobType.CANONICAL_DECODE:
                raise RuntimeError("publisher exploded")
            probe_publisher(job, result)

        async def scenario() -> None:
            import sqlite3

            mgr = _make_manager(
                env,
                publisher=broken_publisher,
                parameters_for=lambda job: _decode_parameters_for(job, env["imports"]),
            )
            await mgr.start()
            try:
                await self._probe_first(env, mgr)
                job = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "PUBLISH_FAILED"

                # No partial state: project untouched, no assets, staging gone.
                project = env["projects"].get_project(env["project"].id)
                assert project.status.value == "empty"
                assert project.source_asset_id is None
                conn = sqlite3.connect(env["db"])
                try:
                    asset_count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
                finally:
                    conn.close()
                assert asset_count == 0
                staging = env["root"] / "jobs" / job.id.hex / "staging"
                assert not staging.exists()
            finally:
                await mgr.stop()

        asyncio.run(scenario())
