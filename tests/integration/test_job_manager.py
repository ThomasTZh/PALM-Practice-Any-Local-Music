"""JobManager integration tests (M1.4).

Covers the durable scheduling loop end to end: probe to completion with
publishing, unimplemented job types, cancellation of queued and running
jobs, restart recovery, and the acceptance property that a completed
result survives a later failed job.
"""

from __future__ import annotations

import asyncio
import hashlib
import struct
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.app import _decode_parameters_for, _job_parameters_for
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
                    env["project"].id, JobType.WAVEFORM, import_id=env["import"].id
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


class TestParameterResolution:
    """M1.7: parameter-builder failures become job failures with codes."""

    def test_parameter_error_code_propagates(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        def failing(job: MediaJob) -> dict:
            raise ParameterResolutionError("NO_CANONICAL", "the project has no canonical audio")

        async def scenario() -> None:
            mgr = _make_manager(env, parameters_for=failing)
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id,
                    JobType.MONITORING_DOWNMIX,
                    import_id=env["import"].id,
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "NO_CANONICAL"
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_empty_parameters_downmix_defaults_to_no_canonical(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env, parameters_for=lambda job: {})
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id,
                    JobType.MONITORING_DOWNMIX,
                    import_id=env["import"].id,
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "NO_CANONICAL"
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_empty_parameters_playback_defaults_to_no_canonical(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env, parameters_for=lambda job: {})
            await mgr.start()
            try:
                job = await mgr.create_job(
                    env["project"].id,
                    JobType.PLAYBACK_RATE,
                    import_id=env["import"].id,
                    parameters={"target_sample_rate": 48000},
                )
                final = await _wait_terminal(mgr, job.id)
                assert final.state is JobState.FAILED
                assert final.error_code == "NO_CANONICAL"
            finally:
                await mgr.stop()

        asyncio.run(scenario())

    def test_empty_parameters_decode_still_no_stream_selection(self, env: dict) -> None:
        async def scenario() -> None:
            mgr = _make_manager(env, parameters_for=lambda job: {})
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


class TestParameterResolvers:
    """M1.7: the app's parameter builders for derived jobs (no worker)."""

    def _seed_ready(
        self, env: dict, *, channels: int, layout: str
    ) -> tuple[uuid.UUID, Path]:
        from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
        from basseparate.domain.representation import (
            AudioRepresentation,
            RepresentationProvenance,
            RepresentationRole,
            TimeMapping,
            compute_transform_key,
        )

        frames = 4410
        projects = env["projects"]
        project = projects.create_project("resolver")
        pcm_bytes = b"\x00\x00\x00\x00" * (frames * channels)
        pcm_hash = hashlib.sha256(pcm_bytes).hexdigest()
        original = AssetRecord(
            id=uuid.uuid4(),
            content_hash="ab" * 32,
            role=AssetRole.SOURCE_ORIGINAL,
            relative_path="runtime/uploads/seed.part",
            media_type="audio/wav",
            byte_count=100,
            created_at=datetime.now(UTC),
        )
        pcm = AssetRecord(
            id=uuid.uuid4(),
            content_hash=pcm_hash,
            role=AssetRole.SOURCE_PCM,
            relative_path=f"data/assets/{pcm_hash}.pcm",
            media_type="application/octet-stream",
            byte_count=len(pcm_bytes),
            created_at=datetime.now(UTC),
            audio=AudioMetadata(
                sample_rate=44100,
                channel_count=channels,
                frame_count=frames,
                sample_format="f32le",
            ),
        )
        rep = AudioRepresentation(
            asset_id=pcm.id,
            parent_asset_id=original.id,
            role=RepresentationRole.CANONICAL,
            sample_rate=44100,
            channel_count=channels,
            channel_layout=layout,
            frame_count=frames,
            content_hash=pcm_hash,
            transform_key=compute_transform_key("ab" * 32, 0, 1, "ffmpeg 8.1.2"),
            time_mapping=TimeMapping(project_rate=44100, representation_rate=44100),
            provenance=RepresentationProvenance(
                tool="ffmpeg",
                tool_version="ffmpeg 8.1.2",
                profile_version=1,
                created_at=datetime.now(UTC),
            ),
        )
        projects.publish_source(
            project_id=project.id,
            original_asset=original,
            pcm_asset=pcm,
            representation=rep,
            source_stream_index=0,
            sample_rate=44100,
            duration_frames=frames,
            channel_count=channels,
            channel_layout=layout,
            decode_profile_version=1,
            source_metadata={},
        )
        asset_dir = env["paths"].data / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        on_disk = asset_dir / f"{pcm_hash}.pcm"
        on_disk.write_bytes(pcm_bytes)
        return project.id, on_disk

    def _job(
        self,
        env: dict,
        project_id: uuid.UUID,
        job_type: JobType,
        parameters: dict | None = None,
    ) -> MediaJob:
        return env["jobs"].create_job(
            project_id, job_type, import_id=env["import"].id, parameters=parameters
        )

    def _resolvers(self, env: dict):
        return lambda job: _job_parameters_for(
            job, env["imports"], env["projects"], env["paths"]
        )

    def test_downmix_standard_51(self, env: dict) -> None:
        project_id, pcm_path = self._seed_ready(env, channels=6, layout="5.1")
        job = self._job(env, project_id, JobType.MONITORING_DOWNMIX)
        params = self._resolvers(env)(job)
        assert params["source_pcm_path"] == str(pcm_path)
        assert params["sample_rate"] == 44100
        assert params["channel_count"] == 6
        assert params["downmix_mode"] == "standard_5_1"
        assert params["left_channel"] == 0
        assert params["right_channel"] == 1
        assert params["pan_spec"].startswith("pan=stereo|c0=")
        assert params["estimated_duration_seconds"] == pytest.approx(0.1)

    def test_downmix_unknown_layout_requires_selection(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        project_id, _ = self._seed_ready(env, channels=4, layout="quad")
        job = self._job(env, project_id, JobType.MONITORING_DOWNMIX)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolvers(env)(job)
        assert excinfo.value.code == "MISSING_MONITORING_SELECTION"

    def test_downmix_manual_with_selection(self, env: dict) -> None:
        project_id, _ = self._seed_ready(env, channels=4, layout="quad")
        env["projects"].set_monitoring_channels(project_id, 1, 3)
        job = self._job(env, project_id, JobType.MONITORING_DOWNMIX)
        params = self._resolvers(env)(job)
        assert params["downmix_mode"] == "manual"
        assert params["left_channel"] == 1
        assert params["right_channel"] == 3
        assert params["pan_spec"] == "pan=stereo|c0=1*c1|c1=1*c3"

    def test_downmix_stereo_needs_nothing(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        project_id, _ = self._seed_ready(env, channels=2, layout="stereo")
        job = self._job(env, project_id, JobType.MONITORING_DOWNMIX)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolvers(env)(job)
        assert excinfo.value.code == "NO_DOWNMIX_NEEDED"

    def test_downmix_empty_project_no_canonical(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        project = env["projects"].create_project("empty")
        job = self._job(env, project.id, JobType.MONITORING_DOWNMIX)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolvers(env)(job)
        assert excinfo.value.code == "NO_CANONICAL"

    def test_playback_from_canonical(self, env: dict) -> None:
        project_id, pcm_path = self._seed_ready(env, channels=2, layout="stereo")
        job = self._job(env, project_id, JobType.PLAYBACK_RATE, {"target_sample_rate": 48000})
        params = self._resolvers(env)(job)
        assert params["source_pcm_path"] == str(pcm_path)
        assert params["sample_rate"] == 44100
        assert params["channel_count"] == 2
        assert params["target_sample_rate"] == 48000

    def test_playback_missing_target_rate(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        project_id, _ = self._seed_ready(env, channels=2, layout="stereo")
        job = self._job(env, project_id, JobType.PLAYBACK_RATE)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolvers(env)(job)
        assert excinfo.value.code == "INVALID_TARGET_RATE"

    def test_playback_out_of_range_target(self, env: dict) -> None:
        from basseparate.jobs import ParameterResolutionError

        project_id, _ = self._seed_ready(env, channels=2, layout="stereo")
        job = self._job(env, project_id, JobType.PLAYBACK_RATE, {"target_sample_rate": 7999})
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolvers(env)(job)
        assert excinfo.value.code == "INVALID_TARGET_RATE"

    def test_playback_prefers_monitoring_source(self, env: dict, tmp_path: Path) -> None:
        import hashlib as _hashlib

        from basseparate.jobs import build_publishers

        project_id, _canonical = self._seed_ready(env, channels=6, layout="5.1")
        # Publish a monitoring downmix through the real publisher.
        stereo = b"\x08\x00\x00\x00" * (4410 * 2)
        staging = tmp_path / "staging"
        staging.mkdir()
        staged = staging / "monitoring.pcm"
        staged.write_bytes(stereo)
        downmix_job = self._job(env, project_id, JobType.MONITORING_DOWNMIX)
        build_publishers(env["imports"], env["projects"], env["representations"], env["paths"])(
            downmix_job,
            {
                "frame_count": 4410,
                "sample_rate": 44100,
                "channel_count": 2,
                "content_hash": _hashlib.sha256(stereo).hexdigest(),
                "max_amplitude": 0.0,
                "pcm_byte_count": len(stereo),
                "source_frame_count": 4410,
                "downmix_mode": "standard_5_1",
                "left_channel": 0,
                "right_channel": 1,
                "ffmpeg_version": "ffmpeg 8.1.2",
                "profile_version": 1,
                "staging_pcm_path": str(staged),
            },
        )
        monitoring = env["projects"].get_project(project_id).monitoring_asset_id
        assert monitoring is not None
        monitoring_path = env["paths"].resolve_asset_path(
            env["projects"].get_asset(monitoring).relative_path  # type: ignore[union-attr]
        )

        job = self._job(env, project_id, JobType.PLAYBACK_RATE, {"target_sample_rate": 48000})
        params = self._resolvers(env)(job)
        assert params["source_pcm_path"] == str(monitoring_path)
        assert params["channel_count"] == 2


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

    def test_crash_between_publish_and_commit_recovers(self, env: dict) -> None:
        """milestone1.md §8.3: a crash after the rename but before the DB
        commit leaves an unreferenced complete asset, not a broken project.
        Re-decoding re-registers the asset and re-attaches the project,
        reusing the on-disk file."""
        async def scenario() -> None:
            import hashlib
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
                pcm = env["projects"].get_asset_by_hash(content_hash)
                assert pcm is not None
                on_disk = env["paths"].data / "assets" / f"{content_hash}.pcm"
                bytes_before = on_disk.read_bytes()

                # Simulate the crash: the asset row and its references vanish,
                # the published file remains.
                conn = sqlite3.connect(env["db"])
                try:
                    conn.execute("DELETE FROM representations WHERE asset_id = ?", (str(pcm.id),))
                    conn.execute("DELETE FROM assets WHERE id = ?", (str(pcm.id),))
                    conn.commit()
                finally:
                    conn.close()
                assert env["projects"].get_asset_by_hash(content_hash) is None
                assert on_disk.is_file()  # the complete asset survives

                # Re-decode: identical content, and the on-disk asset is
                # reused rather than re-written.
                second = await mgr.create_job(
                    env["project"].id, JobType.CANONICAL_DECODE, import_id=env["import"].id
                )
                second_final = await _wait_terminal(mgr, second.id)
                assert second_final.state is JobState.COMPLETED
                assert second_final.result is not None
                assert second_final.result["content_hash"] == content_hash

                pcm2 = env["projects"].get_asset_by_hash(content_hash)
                assert pcm2 is not None
                assert pcm2.id != pcm.id  # a fresh asset row
                assert on_disk.read_bytes() == bytes_before  # file untouched
                assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == content_hash

                project = env["projects"].get_project(env["project"].id)
                assert project.status.value == "ready"
                assert project.canonical_asset_id == pcm2.id
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
