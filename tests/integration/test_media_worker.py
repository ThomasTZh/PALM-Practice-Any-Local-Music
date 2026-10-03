"""Media worker subprocess tests (M1.4, extended M1.5).

Runs the real ``basseparate.worker.media_worker`` as a child process and
drives it through the v2 protocol: probe to completion, canonical decode
to completion (real ffmpeg), decode parameter validation, unimplemented
job types, and cancellation of running jobs.
"""

from __future__ import annotations

import struct
import threading
import uuid
from pathlib import Path

import pytest

from basseparate.domain.media_job import JobStage, JobType
from basseparate.worker import (
    ERR_NOT_IMPLEMENTED,
    CancelledMessage,
    CapabilitiesMessage,
    CompletedMessage,
    FailedMessage,
    HelloMessage,
    ProgressMessage,
    StoppedMessage,
    WorkerSupervisor,
    assert_no_leftover,
    assert_protocol_version,
    make_run,
    media_worker_command,
)


def _make_wav(pcm: bytes | None = None, sample_rate: int = 44100, channels: int = 1) -> bytes:
    if pcm is None:
        pcm = b"\x00\x00" * 4410
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def _install_fake_slow_ffprobe(tmp_path: Path) -> Path:
    """Install a fake ``ffprobe`` on PATH that sleeps for 30 s on any probe.

    ``exec`` replaces the shell with sleep so SIGTERM reaches the sleeper
    directly (no orphaned child). ``-version`` answers immediately so
    ``tool_versions()`` works.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ffprobe"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-version" ]; then\n'
        '  echo "ffprobe version 6.0-fake"\n'
        "  exit 0\n"
        "fi\n"
        "exec sleep 30\n"
    )
    script.chmod(0o755)
    return bin_dir


def _install_fake_slow_ffmpeg(tmp_path: Path) -> Path:
    """Install a fake ``ffmpeg`` on PATH that sleeps for 30 s on any decode.

    ``-version`` answers immediately so ``tool_versions()`` works. ``exec``
    replaces the shell with sleep so SIGTERM reaches the sleeper directly.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-version" ]; then\n'
        '  echo "ffmpeg version 6.0-fake"\n'
        "  exit 0\n"
        "fi\n"
        "exec sleep 30\n"
    )
    script.chmod(0o755)
    return bin_dir


@pytest.fixture()
def supervisor(tmp_path: Path) -> WorkerSupervisor:
    sup = WorkerSupervisor(command=media_worker_command(), cwd=tmp_path)
    sup.start()
    yield sup
    sup.stop()
    assert_no_leftover(sup.pid)


class TestHandshake:
    def test_hello_and_capabilities(self, supervisor: WorkerSupervisor) -> None:
        hello = supervisor.wait_for_handshake()
        assert isinstance(hello, HelloMessage)
        assert hello.payload.worker == "media"
        assert_protocol_version(hello)

        from basseparate.worker import make_describe

        supervisor.send(make_describe())
        caps = supervisor.receive(10.0)
        assert isinstance(caps, CapabilitiesMessage)
        ids = {c.id for c in caps.payload.capabilities}
        assert "media.probe" in ids


class TestProbeJob:
    def test_probe_completes_with_result(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        job_id = uuid.uuid4()
        staging = tmp_path / "staging"

        supervisor.send(make_run(job_id, JobType.PROBE, str(wav), str(staging)))

        messages: list[object] = []
        for _ in range(10):
            msg = supervisor.receive(15.0)
            messages.append(msg)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                break

        # progress(inspecting) then completed
        assert any(isinstance(m, ProgressMessage) for m in messages)
        final = messages[-1]
        assert isinstance(final, CompletedMessage)
        assert final.payload.job_id == job_id
        result = final.payload.result
        assert result["format_name"] == "wav"
        assert result["byte_count"] == wav.stat().st_size
        assert len(result["audio_streams"]) == 1

    def test_unimplemented_job_type_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        job_id = uuid.uuid4()
        supervisor.send(
            make_run(
                job_id, JobType.WAVEFORM, str(tmp_path / "x.part"), str(tmp_path / "s")
            )
        )
        msg = supervisor.receive(15.0)
        assert isinstance(msg, FailedMessage)
        assert msg.payload.job_id == job_id
        assert msg.payload.code == ERR_NOT_IMPLEMENTED

    def test_probe_missing_source_fails(self, supervisor: WorkerSupervisor, tmp_path: Path) -> None:
        supervisor.wait_for_handshake()
        job_id = uuid.uuid4()
        supervisor.send(
            make_run(
                job_id,
                JobType.PROBE,
                str(tmp_path / "does-not-exist.part"),
                str(tmp_path / "s"),
            )
        )
        # progress(inspecting) is emitted before the probe fails.
        final = None
        for _ in range(10):
            msg = supervisor.receive(15.0)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                final = msg
                break
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "PROBE_FAILED"


class TestDecodeJob:
    """M1.5: canonical decode jobs through the worker protocol."""

    DECODE_PARAMS = {
        "stream_index": 0,
        "sample_rate": 44100,
        "channel_count": 1,
        "channel_layout": "mono",
    }

    def test_decode_completes_with_result(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        job_id = uuid.uuid4()
        staging = tmp_path / "staging"

        supervisor.send(
            make_run(
                job_id,
                JobType.CANONICAL_DECODE,
                str(wav),
                str(staging),
                parameters=self.DECODE_PARAMS,
            )
        )

        messages: list[object] = []
        for _ in range(10):
            msg = supervisor.receive(15.0)
            messages.append(msg)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                break

        assert any(isinstance(m, ProgressMessage) for m in messages)
        final = messages[-1]
        assert isinstance(final, CompletedMessage), f"expected completed, got {type(final)}"
        assert final.payload.job_id == job_id
        result = final.payload.result
        assert result["frame_count"] == 4410
        assert result["sample_rate"] == 44100
        assert result["channel_count"] == 1
        assert result["channel_layout"] == "mono"
        assert result["profile_version"] == 1
        assert len(result["content_hash"]) == 64
        # The staged PCM is left for the backend publisher to move.
        staged = staging / "canonical.pcm"
        assert staged.is_file()
        assert staged.stat().st_size == 4410 * 4

    def test_decode_missing_parameters_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        job_id = uuid.uuid4()

        supervisor.send(make_run(job_id, JobType.CANONICAL_DECODE, str(wav), str(tmp_path / "s")))

        final = None
        for _ in range(10):
            msg = supervisor.receive(15.0)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                final = msg
                break
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DECODE_PARAMETERS"

    def test_decode_invalid_parameters_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        job_id = uuid.uuid4()
        bad_params = dict(self.DECODE_PARAMS, sample_rate=1)  # below the 8 kHz floor

        supervisor.send(
            make_run(
                job_id,
                JobType.CANONICAL_DECODE,
                str(wav),
                str(tmp_path / "s"),
                parameters=bad_params,
            )
        )

        final = None
        for _ in range(10):
            msg = supervisor.receive(15.0)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                final = msg
                break
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DECODE_PARAMETERS"

    def test_decode_missing_source_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        job_id = uuid.uuid4()

        supervisor.send(
            make_run(
                job_id,
                JobType.CANONICAL_DECODE,
                str(tmp_path / "does-not-exist.part"),
                str(tmp_path / "s"),
                parameters=self.DECODE_PARAMS,
            )
        )

        final = None
        for _ in range(10):
            msg = supervisor.receive(15.0)
            if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
                final = msg
                break
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DECODE_FAILED"

    def test_decode_cancel_running_cleans_staging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deterministic in-flight cancel: a fake ffmpeg that hangs for 30 s."""
        import os

        bin_dir = _install_fake_slow_ffmpeg(tmp_path)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

        sup = WorkerSupervisor(command=media_worker_command(), cwd=tmp_path)
        sup.start()
        try:
            sup.wait_for_handshake()
            wav = tmp_path / "tone.wav"
            wav.write_bytes(_make_wav())
            job_id = uuid.uuid4()
            staging = tmp_path / "staging"
            staging.mkdir()
            (staging / "canonical.pcm").write_bytes(b"partial work")

            sup.send(
                make_run(
                    job_id,
                    JobType.CANONICAL_DECODE,
                    str(wav),
                    str(staging),
                    parameters=self.DECODE_PARAMS,
                )
            )

            # Wait for the worker to confirm the decode started (job thread live).
            saw_progress = False
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, ProgressMessage) and msg.payload.stage is JobStage.DECODING:
                    saw_progress = True
                    break
            assert saw_progress

            from basseparate.worker import make_cancel

            sup.send(make_cancel(job_id))

            final = None
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, (CancelledMessage, CompletedMessage, FailedMessage)):
                    final = msg
                    break
            assert isinstance(final, CancelledMessage), f"expected cancelled, got {type(final)}"
            assert final.payload.job_id == job_id
            assert final.payload.staging_removed is True
            assert not staging.exists()
        finally:
            sup.stop()
        assert_no_leftover(sup.pid)


class TestCancelRunningProbe:
    def test_cancel_stops_probe_and_cleans_staging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deterministic in-flight cancel: a fake ffprobe that hangs for 30 s."""
        import os

        bin_dir = _install_fake_slow_ffprobe(tmp_path)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

        sup = WorkerSupervisor(command=media_worker_command(), cwd=tmp_path)
        sup.start()
        try:
            sup.wait_for_handshake()
            wav = tmp_path / "tone.wav"
            wav.write_bytes(_make_wav())
            job_id = uuid.uuid4()
            staging = tmp_path / "staging"
            staging.mkdir()
            (staging / "partial.bin").write_bytes(b"unfinished work")

            sup.send(make_run(job_id, JobType.PROBE, str(wav), str(staging)))

            # Wait for the worker to confirm the job is inspecting (job thread live).
            saw_progress = False
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, ProgressMessage) and msg.payload.stage is JobStage.INSPECTING:
                    saw_progress = True
                    break
            assert saw_progress

            from basseparate.worker import make_cancel

            sup.send(make_cancel(job_id))

            final = None
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, (CancelledMessage, CompletedMessage, FailedMessage)):
                    final = msg
                    break
            assert isinstance(final, CancelledMessage), f"expected cancelled, got {type(final)}"
            assert final.payload.job_id == job_id
            assert final.payload.staging_removed is True
            assert not staging.exists()
        finally:
            sup.stop()
        assert_no_leftover(sup.pid)

    def test_shutdown_cancels_running_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shutdown with a running job: the worker cancels it, joins, stops."""
        import os

        bin_dir = _install_fake_slow_ffprobe(tmp_path)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        job_id = uuid.uuid4()

        sup = WorkerSupervisor(command=media_worker_command(), cwd=tmp_path)
        sup.start()
        try:
            sup.wait_for_handshake()
            sup.send(make_run(job_id, JobType.PROBE, str(wav), str(tmp_path / "staging")))
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, ProgressMessage):
                    break

            from basseparate.worker import make_shutdown

            sup.send(make_shutdown())
            final = None
            for _ in range(20):
                msg = sup.receive(15.0)
                if isinstance(msg, StoppedMessage):
                    final = msg
                    break
            assert isinstance(final, StoppedMessage)
        finally:
            sup.stop()
        assert sup.exit_code == 0
        assert_no_leftover(sup.pid)

    def test_cancel_unknown_job_is_ignored(self, supervisor: WorkerSupervisor) -> None:
        """A cancel with no matching running job must not crash the worker."""
        from basseparate.worker import PongMessage, make_cancel, make_ping

        supervisor.wait_for_handshake()
        supervisor.send(make_cancel(uuid.uuid4()))
        supervisor.send(make_ping("after-cancel"))
        for _ in range(5):
            msg = supervisor.receive(10.0)
            if isinstance(msg, PongMessage):
                assert msg.payload.nonce == "after-cancel"
                return
        pytest.fail("worker did not answer ping after an ignored cancel")


class TestProbeCancelledBeforeStart:
    def test_pre_set_cancel_event_raises(self, tmp_path: Path) -> None:
        from basseparate.media.probe import ProbeCancelledError, probe_media

        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        event = threading.Event()
        event.set()
        with pytest.raises(ProbeCancelledError):
            import asyncio

            asyncio.run(probe_media(wav, cancel_event=event))

    def test_cancel_during_probe(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deterministic in-flight cancel against a hung fake ffprobe."""
        import asyncio
        import os

        from basseparate.media.probe import ProbeCancelledError, probe_media

        bin_dir = _install_fake_slow_ffprobe(tmp_path)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

        wav = tmp_path / "tone.wav"
        wav.write_bytes(_make_wav())
        event = threading.Event()

        def _cancel_soon() -> None:
            import time

            time.sleep(0.5)
            event.set()

        t = threading.Thread(target=_cancel_soon, daemon=True)
        t.start()
        with pytest.raises(ProbeCancelledError):
            asyncio.run(probe_media(wav, cancel_event=event))
        t.join(timeout=5)


def _make_f32le_pcm(path: Path, frames: int, channels: int, sample_rate: int) -> Path:
    """Write a raw interleaved f32le PCM file with per-channel sine tones."""
    import numpy as np

    t = np.arange(frames) / sample_rate
    chans = [0.5 * np.sin(2 * np.pi * (100.0 * (i + 1)) * t) for i in range(channels)]
    data = np.stack(chans, axis=1).astype("<f4")
    path.write_bytes(data.tobytes())
    return path


def _wait_for_terminal(supervisor: WorkerSupervisor, max_messages: int = 10) -> object:
    final = None
    for _ in range(max_messages):
        msg = supervisor.receive(30.0)
        if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
            final = msg
            break
    return final


class TestDerivedJobs:
    """M1.7: monitoring downmix and playback-rate jobs through the worker."""

    DOWNMIX_PARAMS = {
        "source_pcm_path": "source.pcm",
        "sample_rate": 44100,
        "channel_count": 4,
        "pan_spec": "pan=stereo|c0=1*c1|c1=1*c3",
        "downmix_mode": "manual",
        "left_channel": 1,
        "right_channel": 3,
    }

    PLAYBACK_PARAMS = {
        "source_pcm_path": "source.pcm",
        "sample_rate": 44100,
        "channel_count": 2,
        "target_sample_rate": 48000,
    }

    def test_downmix_completes_with_result(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        src = _make_f32le_pcm(tmp_path / "source.pcm", 44100, 4, 44100)
        job_id = uuid.uuid4()
        staging = tmp_path / "staging"

        supervisor.send(
            make_run(
                job_id,
                JobType.MONITORING_DOWNMIX,
                str(src),
                str(staging),
                parameters=dict(self.DOWNMIX_PARAMS, source_pcm_path=str(src)),
            )
        )

        final = _wait_for_terminal(supervisor)
        assert isinstance(final, CompletedMessage), f"expected completed, got {type(final)}"
        result = final.payload.result
        assert result["frame_count"] == 44100
        assert result["sample_rate"] == 44100
        assert result["channel_count"] == 2
        assert result["downmix_mode"] == "manual"
        assert result["left_channel"] == 1
        assert result["right_channel"] == 3
        assert result["source_frame_count"] == 44100
        assert result["profile_version"] == 1
        assert len(result["content_hash"]) == 64
        staged = staging / "monitoring.pcm"
        assert staged.is_file()
        assert staged.stat().st_size == 44100 * 2 * 4

    def test_playback_completes_with_result(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        src = _make_f32le_pcm(tmp_path / "source.pcm", 44100, 2, 44100)
        job_id = uuid.uuid4()
        staging = tmp_path / "staging"

        supervisor.send(
            make_run(
                job_id,
                JobType.PLAYBACK_RATE,
                str(src),
                str(staging),
                parameters=dict(self.PLAYBACK_PARAMS, source_pcm_path=str(src)),
            )
        )

        final = _wait_for_terminal(supervisor)
        assert isinstance(final, CompletedMessage), f"expected completed, got {type(final)}"
        result = final.payload.result
        assert result["source_frame_count"] == 44100
        assert result["frame_count"] == 48000
        assert result["expected_frame_count"] == 48000
        assert result["endpoint_difference_frames"] == 0
        assert result["sample_rate"] == 48000
        assert result["source_sample_rate"] == 44100
        assert result["target_sample_rate"] == 48000
        assert len(result["content_hash"]) == 64
        staged = staging / "playback.pcm"
        assert staged.is_file()
        assert staged.stat().st_size == 48000 * 2 * 4

    def test_downmix_missing_parameters_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        src = _make_f32le_pcm(tmp_path / "source.pcm", 4410, 4, 44100)
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.MONITORING_DOWNMIX,
                str(src),
                str(tmp_path / "s"),
            )
        )
        final = _wait_for_terminal(supervisor)
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DOWNMIX_PARAMETERS"

    def test_downmix_invalid_pan_spec_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        src = _make_f32le_pcm(tmp_path / "source.pcm", 4410, 4, 44100)
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.MONITORING_DOWNMIX,
                str(src),
                str(tmp_path / "s"),
                parameters=dict(self.DOWNMIX_PARAMS, source_pcm_path=str(src), pan_spec=""),
            )
        )
        final = _wait_for_terminal(supervisor)
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DOWNMIX_PARAMETERS"

    def test_playback_invalid_target_rate_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        src = _make_f32le_pcm(tmp_path / "source.pcm", 4410, 2, 44100)
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.PLAYBACK_RATE,
                str(src),
                str(tmp_path / "s"),
                parameters=dict(
                    self.PLAYBACK_PARAMS,
                    source_pcm_path=str(src),
                    target_sample_rate=1,
                ),
            )
        )
        final = _wait_for_terminal(supervisor)
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "PLAYBACK_PARAMETERS"

    def test_playback_missing_source_fails(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.PLAYBACK_RATE,
                str(tmp_path / "absent.pcm"),
                str(tmp_path / "s"),
                parameters=dict(self.PLAYBACK_PARAMS, source_pcm_path=str(tmp_path / "absent.pcm")),
            )
        )
        final = _wait_for_terminal(supervisor)
        assert isinstance(final, FailedMessage), f"expected failed, got {type(final)}"
        assert final.payload.code == "DERIVED_FAILED"
