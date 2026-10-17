"""Integration tests for the M2.13 WAV stem export worker (real ffmpeg).

Covers the DSP engine (``basseparate.media.export``) and the worker
protocol path (``basseparate.worker.media_worker``):

- Same-rate 24-bit export: exact frame count, verified hash and size.
- Float32 same-rate export: bit-exact passthrough (no dither).
- 44.1k → 48k resampled 16-bit export: endpoint tolerance, bounded peak.
- Linked peak normalization: the joint peak lands at −1 dBFS, gain
  reported.
- Clipping refusal on integer output; float32 never refuses.
- Stem source verification failures (missing, mis-sized, hash mismatch).
- Pre-start cancellation, progress stage order, disk budget.
- Worker protocol: completed export with artifacts, ``EXPORT_PARAMETERS``,
  ``EXPORT_CLIPPING``, ``EXPORT_STEM_MISSING``.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import threading
import uuid
from collections import namedtuple
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.export import ExportFormat, ExportNormalization
from basseparate.domain.media_job import JobType
from basseparate.media.export import (
    ExportCancelledError,
    ExportClippingError,
    ExportDiskSpaceError,
    ExportStemInput,
    ExportStemVerificationError,
    export_stems,
)
from basseparate.worker import (
    CancelledMessage,
    CompletedMessage,
    FailedMessage,
    ProgressMessage,
    WorkerSupervisor,
    assert_no_leftover,
    make_run,
    media_worker_command,
)

FFMPEG = "ffmpeg"


def _write_f32le_pcm(path: Path, data: np.ndarray) -> None:
    """Write an (N, C) float array as raw interleaved f32le."""
    path.write_bytes(np.ascontiguousarray(data, dtype="<f4").tobytes())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sine(seconds: float, sample_rate: int, frequency: float, amplitude: float = 1.0) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return amplitude * np.sin(2 * np.pi * frequency * t)


def _make_stem(
    tmp_path: Path, name: str, *, amplitude: float, sample_rate: int = 44100, seconds: float = 0.25
) -> tuple[Path, int]:
    """One stereo stem: identical left/right sine. Returns (path, frames)."""
    sig = _sine(seconds, sample_rate, 440.0, amplitude)
    data = np.stack([sig, sig], axis=1)
    path = tmp_path / f"{name}.pcm"
    _write_f32le_pcm(path, data)
    return path, len(sig)


def _stem_input(
    path: Path, frames: int, *, sample_rate: int = 44100, role: str = "bass"
) -> ExportStemInput:
    return ExportStemInput(
        stem_id=str(uuid.uuid4()),
        asset_id=str(uuid.uuid4()),
        role=role,
        source_path=path,
        source_hash=_sha256_file(path),
        sample_rate=sample_rate,
        channel_count=2,
        frame_count=frames,
        download_filename=f"{role}-test-{sample_rate // 1000}k-24bit.wav",
    )


def _decode_wav(wav_path: Path, pcm_path: Path, channels: int) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(wav_path),
            "-f",
            "f32le",
            "-ac",
            str(channels),
            "-y",
            str(pcm_path),
        ],
        check=True,
        capture_output=True,
    )


def _probe_stream(wav_path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration",
            "-of",
            "json",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)["streams"][0]


class TestExportStemsDsp:
    @pytest.mark.asyncio
    async def test_same_rate_wav24_exact(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        outcome = await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV24,
            target_sample_rate=None,
            normalize=ExportNormalization.OFF,
        )
        assert outcome.joint_peak == pytest.approx(0.5, abs=1e-6)
        assert outcome.gain_db is None
        assert len(outcome.stems) == 1
        out = outcome.stems[0]
        assert out.output_rate == 44100
        assert out.frame_count == frames
        assert out.staging_path.is_file()
        assert out.byte_size == out.staging_path.stat().st_size
        assert out.byte_size >= 44
        assert out.sha256 == _sha256_file(out.staging_path)
        stream = _probe_stream(out.staging_path)
        assert stream["codec_name"] == "pcm_s24le"
        assert int(stream["sample_rate"]) == 44100
        assert int(stream["channels"]) == 2

    @pytest.mark.asyncio
    async def test_float32_same_rate_bit_exact(self, tmp_path: Path) -> None:
        sig = _sine(0.25, 44100, 440.0, 0.7)
        data = np.stack([sig, sig], axis=1)
        path = tmp_path / "bass.pcm"
        _write_f32le_pcm(path, data)
        stem = _stem_input(path, len(sig))
        outcome = await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV32F,
            target_sample_rate=None,
            normalize=ExportNormalization.OFF,
        )
        pcm_out = tmp_path / "out.pcm"
        _decode_wav(outcome.stems[0].staging_path, pcm_out, 2)
        decoded = np.fromfile(pcm_out, dtype="<f4").reshape(-1, 2)
        assert decoded.shape == data.shape
        # Within 1 ULP of the source: no dither, no quantization (spec §15.3.11).
        assert float(np.abs(decoded - data).max()) <= 1e-7

    @pytest.mark.asyncio
    async def test_resample_48k_wav16(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        expected = (frames * 48000 + 44100 // 2) // 44100
        outcome = await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV16,
            target_sample_rate=48000,
            normalize=ExportNormalization.OFF,
        )
        out = outcome.stems[0]
        assert out.output_rate == 48000
        assert abs(out.frame_count - expected) <= 2
        stream = _probe_stream(out.staging_path)
        assert stream["codec_name"] == "pcm_s16le"
        assert int(stream["sample_rate"]) == 48000
        pcm_out = tmp_path / "out.pcm"
        _decode_wav(out.staging_path, pcm_out, 2)
        decoded = np.fromfile(pcm_out, dtype="<f4").reshape(-1, 2)
        assert float(decoded.max()) == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_linked_normalization_lands_at_minus_1_dbfs(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.25)
        stem = _stem_input(path, frames)
        target = 10 ** (-1 / 20)
        outcome = await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV16,
            target_sample_rate=None,
            normalize=ExportNormalization.LINKED_PEAK,
        )
        expected_gain = 20.0 * math.log10(target / outcome.joint_peak)
        assert outcome.gain_db == pytest.approx(expected_gain, abs=1e-9)
        assert outcome.joint_peak == pytest.approx(0.25, abs=1e-6)
        pcm_out = tmp_path / "out.pcm"
        _decode_wav(outcome.stems[0].staging_path, pcm_out, 2)
        decoded = np.fromfile(pcm_out, dtype="<f4").reshape(-1, 2)
        assert float(decoded.max()) == pytest.approx(target, abs=0.005)

    @pytest.mark.asyncio
    async def test_integer_clipping_refused(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=1.0)
        stem = _stem_input(path, frames)
        with pytest.raises(ExportClippingError) as excinfo:
            await export_stems(
                stems=[stem],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV16,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
            )
        assert "float32" in str(excinfo.value)
        assert "linked" in str(excinfo.value)
        staging = tmp_path / "staging"
        assert not (staging.exists() and list(staging.glob("*.wav")))

    @pytest.mark.asyncio
    async def test_float32_never_refuses(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=1.0)
        stem = _stem_input(path, frames)
        outcome = await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV32F,
            target_sample_rate=None,
            normalize=ExportNormalization.OFF,
        )
        assert outcome.joint_peak == pytest.approx(1.0, abs=1e-6)
        assert outcome.stems[0].staging_path.is_file()

    @pytest.mark.asyncio
    async def test_missing_source(self, tmp_path: Path) -> None:
        stem = ExportStemInput(
            stem_id=str(uuid.uuid4()),
            asset_id=str(uuid.uuid4()),
            role="bass",
            source_path=tmp_path / "missing.pcm",
            source_hash="0" * 64,
            sample_rate=44100,
            channel_count=2,
            frame_count=100,
            download_filename="bass.wav",
        )
        with pytest.raises(ExportStemVerificationError):
            await export_stems(
                stems=[stem],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV24,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
            )

    @pytest.mark.asyncio
    async def test_size_mismatch(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        mis_sized = ExportStemInput(
            stem_id=stem.stem_id,
            asset_id=stem.asset_id,
            role=stem.role,
            source_path=path,
            source_hash=stem.source_hash,
            sample_rate=stem.sample_rate,
            channel_count=stem.channel_count,
            frame_count=frames + 1,
            download_filename=stem.download_filename,
        )
        with pytest.raises(ExportStemVerificationError):
            await export_stems(
                stems=[mis_sized],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV24,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
            )

    @pytest.mark.asyncio
    async def test_hash_mismatch(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        wrong = ExportStemInput(
            stem_id=stem.stem_id,
            asset_id=stem.asset_id,
            role=stem.role,
            source_path=path,
            source_hash="0" * 64,
            sample_rate=stem.sample_rate,
            channel_count=stem.channel_count,
            frame_count=frames,
            download_filename=stem.download_filename,
        )
        with pytest.raises(ExportStemVerificationError):
            await export_stems(
                stems=[wrong],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV24,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
            )

    @pytest.mark.asyncio
    async def test_cancelled_before_start(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(ExportCancelledError):
            await export_stems(
                stems=[stem],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV24,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
                cancel_event=cancel,
            )

    @pytest.mark.asyncio
    async def test_progress_stages(self, tmp_path: Path) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        stages: list[str] = []
        await export_stems(
            stems=[stem],
            staging_dir=tmp_path / "staging",
            format=ExportFormat.WAV24,
            target_sample_rate=None,
            normalize=ExportNormalization.OFF,
            on_progress=lambda stage, _fraction, _detail: stages.append(stage),
        )
        assert stages[0] == "verifying_stems"
        assert "encoding" in stages
        assert stages[-1] == "verifying_export"

    @pytest.mark.asyncio
    async def test_disk_budget_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, frames = _make_stem(tmp_path, "bass", amplitude=0.5)
        stem = _stem_input(path, frames)
        usage = namedtuple("Usage", "total used free")(10**9, 10**9, 0)
        monkeypatch.setattr("basseparate.media.export.shutil.disk_usage", lambda p: usage)
        with pytest.raises(ExportDiskSpaceError):
            await export_stems(
                stems=[stem],
                staging_dir=tmp_path / "staging",
                format=ExportFormat.WAV24,
                target_sample_rate=None,
                normalize=ExportNormalization.OFF,
            )


@pytest.fixture()
def supervisor(tmp_path: Path) -> WorkerSupervisor:
    sup = WorkerSupervisor(command=media_worker_command(), cwd=tmp_path)
    sup.start()
    yield sup
    sup.stop()
    assert_no_leftover(sup.pid)


def _export_params(tmp_path: Path, *, amplitude: float, format: str = "wav24") -> dict:
    """Two aligned stereo stems plus the full export parameter set."""
    stems: list[dict] = []
    first_path: Path | None = None
    for i in range(2):
        sig = _sine(0.25, 44100, 440.0, amplitude)
        data = np.stack([sig, sig], axis=1)
        path = tmp_path / f"stem{i}.pcm"
        _write_f32le_pcm(path, data)
        if i == 0:
            first_path = path
        stems.append(
            {
                "stem_id": str(uuid.uuid4()),
                "asset_id": str(uuid.uuid4()),
                "role": "bass" if i == 0 else "others",
                "source_path": str(path),
                "source_hash": _sha256_file(path),
                "sample_rate": 44100,
                "channel_count": 2,
                "frame_count": len(sig),
                "download_filename": f"Stem{i}-abc123-44k-24bit.wav",
            }
        )
    return {
        "result_set_id": str(uuid.uuid4()),
        "format": format,
        "normalize": "off",
        "source_sample_rate": 44100,
        "stems": stems,
        "_first_path": first_path,
    }


def _wait_for_terminal(supervisor: WorkerSupervisor, timeout: float = 30.0) -> list:
    messages: list = []
    for _ in range(60):
        msg = supervisor.receive(timeout)
        messages.append(msg)
        if isinstance(msg, (CompletedMessage, FailedMessage, CancelledMessage)):
            break
    return messages


class TestExportWorkerProtocol:
    def test_export_completes_with_artifacts(
        self, supervisor: WorkerSupervisor, tmp_path: Path
    ) -> None:
        supervisor.wait_for_handshake()
        params = _export_params(tmp_path, amplitude=0.4)
        first_path = params.pop("_first_path")
        result_set_id = uuid.UUID(params["result_set_id"])
        staging = tmp_path / "staging"
        staging.mkdir()
        job_id = uuid.uuid4()
        supervisor.send(
            make_run(job_id, JobType.EXPORT, str(first_path), str(staging), parameters=params)
        )
        messages = _wait_for_terminal(supervisor)
        final = messages[-1]
        assert isinstance(final, CompletedMessage), [
            (type(m).__name__, getattr(m.payload, "code", None)) for m in messages
        ]
        result = final.payload.result
        assert result["result_set_id"] == str(result_set_id)
        assert result["joint_peak"] == pytest.approx(0.4, abs=1e-6)
        assert len(result["artifacts"]) == 2
        for artifact in result["artifacts"]:
            staged = Path(artifact["staging_path"])
            assert staged.is_file()
            assert artifact["sha256"] == _sha256_file(staged)
            assert artifact["byte_size"] == staged.stat().st_size
            assert artifact["byte_size"] >= 44
            assert artifact["sample_rate"] == 44100
            assert artifact["frame_count"] == 11025
            assert artifact["source_frame_count"] == 11025
            assert artifact["normalized"] is False
            assert artifact["gain_db"] is None
            assert artifact["dither"] == "triangular"
            assert artifact["format"] == "wav24"
        stages = [m.payload.stage.value for m in messages if isinstance(m, ProgressMessage)]
        assert "verifying_stems" in stages
        assert "encoding" in stages
        assert "verifying_export" in stages

    def test_invalid_format_fails(self, supervisor: WorkerSupervisor, tmp_path: Path) -> None:
        supervisor.wait_for_handshake()
        params = _export_params(tmp_path, amplitude=0.4, format="flac")
        first_path = params.pop("_first_path")
        staging = tmp_path / "staging"
        staging.mkdir()
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.EXPORT,
                str(first_path),
                str(staging),
                parameters=params,
            )
        )
        messages = _wait_for_terminal(supervisor)
        final = messages[-1]
        assert isinstance(final, FailedMessage)
        assert final.payload.code == "EXPORT_PARAMETERS"

    def test_clipping_fails(self, supervisor: WorkerSupervisor, tmp_path: Path) -> None:
        supervisor.wait_for_handshake()
        params = _export_params(tmp_path, amplitude=1.0, format="wav16")
        first_path = params.pop("_first_path")
        staging = tmp_path / "staging"
        staging.mkdir()
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.EXPORT,
                str(first_path),
                str(staging),
                parameters=params,
            )
        )
        messages = _wait_for_terminal(supervisor)
        final = messages[-1]
        assert isinstance(final, FailedMessage)
        assert final.payload.code == "EXPORT_CLIPPING"

    def test_missing_stem_fails(self, supervisor: WorkerSupervisor, tmp_path: Path) -> None:
        supervisor.wait_for_handshake()
        params = _export_params(tmp_path, amplitude=0.4)
        first_path = params.pop("_first_path")
        params["stems"][0]["source_path"] = str(tmp_path / "missing.pcm")
        staging = tmp_path / "staging"
        staging.mkdir()
        supervisor.send(
            make_run(
                uuid.uuid4(),
                JobType.EXPORT,
                str(first_path),
                str(staging),
                parameters=params,
            )
        )
        messages = _wait_for_terminal(supervisor)
        final = messages[-1]
        assert isinstance(final, FailedMessage)
        assert final.payload.code == "EXPORT_STEM_MISSING"
