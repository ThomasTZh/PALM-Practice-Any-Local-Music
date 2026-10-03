"""M1.7 acceptance: 44.1 kHz and 48 kHz sources play with correct pitch and
duration at any browser output rate (milestone1.md §9).

Matrix (real ffmpeg, via the production ``resample_playback`` transform):

- For each source rate in {44100, 48000} x target rate in {44100, 48000}, a
  one-second 440 Hz stereo sine is resampled and verified for:

  - Duration: the output is one second long at the target rate (frame count
    within +/-2 frames of the exact rational conversion).
  - Pitch: the output zero-crossing frequency is still 440 Hz (within 2 %).
  - Determinism: two runs are byte-identical (stable SHA-256).

Pipeline: a ready project seeded with real 44.1 kHz sine PCM is resampled to
48 kHz, published through the real publisher, and the representation resolves
via ``find_playback`` with the resampled bytes on disk. Same-rate playback
needs no representation at all (the source asset plays directly).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.media_job import JobType
from basseparate.domain.representation import (
    AudioRepresentation,
    PlaybackRateResult,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_transform_key,
)
from basseparate.jobs import build_publishers
from basseparate.media.derived import resample_playback
from basseparate.storage import (
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
    WaveformCacheRepository,
)
from basseparate.storage.db import initialize_database

RATES = (44100, 48000)
FREQUENCY = 440.0
DURATION_SECONDS = 1.0


def _sine_pcm(rate: int, channels: int = 2) -> bytes:
    """One second of a 440 Hz sine as interleaved f32le PCM."""
    t = np.arange(int(DURATION_SECONDS * rate), dtype="<f8") / rate
    mono = (0.5 * np.sin(2.0 * np.pi * FREQUENCY * t)).astype("<f4")
    interleaved = np.repeat(mono[:, None], channels, axis=1).ravel()
    return interleaved.tobytes()


def _zero_crossing_frequency(pcm: bytes, rate: int, channel: int = 0) -> float:
    """Estimated tone frequency from upward zero crossings (1 per cycle).

    ``pcm`` is interleaved stereo f32le; one channel is analyzed.
    """
    samples = np.frombuffer(pcm, dtype="<f4")[channel::2]
    crossings = int(np.count_nonzero((samples[:-1] < 0) & (samples[1:] >= 0)))
    duration = len(samples) / rate
    return crossings / duration


def _resample(tmp_path: Path, source_rate: int, target_rate: int, name: str = "out") -> Path:
    src = tmp_path / f"src-{source_rate}.pcm"
    src.write_bytes(_sine_pcm(source_rate))
    out = tmp_path / f"{name}-{source_rate}-{target_rate}.pcm"
    asyncio.run(
        resample_playback(
            source_path=src,
            output_path=out,
            source_rate=source_rate,
            target_rate=target_rate,
            channel_count=2,
        )
    )
    return out


@pytest.mark.parametrize("source_rate", RATES)
@pytest.mark.parametrize("target_rate", RATES)
class TestResampleMatrix:
    def test_duration_preserved(
        self, tmp_path: Path, source_rate: int, target_rate: int
    ) -> None:
        out = _resample(tmp_path, source_rate, target_rate)
        frames = out.stat().st_size // 8  # stereo f32le
        # One second at the target rate, within the resampler endpoint bound.
        assert abs(frames - target_rate) <= 2

    def test_pitch_preserved(self, tmp_path: Path, source_rate: int, target_rate: int) -> None:
        out = _resample(tmp_path, source_rate, target_rate)
        frequency = _zero_crossing_frequency(out.read_bytes(), target_rate)
        assert frequency == pytest.approx(FREQUENCY, rel=0.02)

    def test_deterministic_two_runs(
        self, tmp_path: Path, source_rate: int, target_rate: int
    ) -> None:
        out1 = _resample(tmp_path, source_rate, target_rate, name="r1")
        out2 = _resample(tmp_path, source_rate, target_rate, name="r2")
        assert hashlib.sha256(out1.read_bytes()).hexdigest() == (
            hashlib.sha256(out2.read_bytes()).hexdigest()
        )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    db = tmp_path / "basseparate.db"
    initialize_database(db)
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
        "paths": paths,
        "projects": ProjectRepository(db),
        "imports": ImportRepository(db),
        "jobs": JobRepository(db),
        "representations": RepresentationRepository(db),
        "waveform_caches": WaveformCacheRepository(db, paths.cache),
    }


def _seed_ready_project(env: dict, sample_rate: int) -> tuple[uuid.UUID, AssetRecord]:
    """A ready project whose canonical asset is a real one-second sine."""
    projects = env["projects"]
    project = projects.create_project("acceptance")
    frames = int(DURATION_SECONDS * sample_rate)
    pcm_bytes = _sine_pcm(sample_rate)
    pcm_hash = _hash(pcm_bytes)
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
            sample_rate=sample_rate,
            channel_count=2,
            frame_count=frames,
            sample_format="f32le",
        ),
    )
    representation = AudioRepresentation(
        asset_id=pcm.id,
        parent_asset_id=original.id,
        role=RepresentationRole.CANONICAL,
        sample_rate=sample_rate,
        channel_count=2,
        channel_layout="stereo",
        frame_count=frames,
        content_hash=pcm_hash,
        transform_key=compute_transform_key("ab" * 32, 0, 1, "ffmpeg 8.1.2"),
        time_mapping=TimeMapping(project_rate=sample_rate, representation_rate=sample_rate),
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
        representation=representation,
        source_stream_index=0,
        sample_rate=sample_rate,
        duration_frames=frames,
        channel_count=2,
        channel_layout="stereo",
        decode_profile_version=1,
        source_metadata={"format": "wav"},
    )
    asset_dir = env["paths"].data / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / f"{pcm_hash}.pcm").write_bytes(pcm_bytes)
    return project.id, pcm


class TestPipeline:
    def test_441k_source_publishes_48k_playback(self, env: dict, tmp_path: Path) -> None:
        project_id, canonical = _seed_ready_project(env, 44100)
        job_id = uuid.uuid4()

        # The production transform, staged where the worker would stage it.
        staging = env["root"] / "jobs" / job_id.hex / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        staged = staging / "playback.pcm"
        asyncio.run(
            resample_playback(
                source_path=env["paths"].data / "assets" / f"{canonical.content_hash}.pcm",
                output_path=staged,
                source_rate=44100,
                target_rate=48000,
                channel_count=2,
            )
        )
        # The worker's exact result construction, then the real publisher.
        data = staged.read_bytes()
        frames = len(data) // 8
        result = PlaybackRateResult(
            frame_count=frames,
            sample_rate=48000,
            channel_count=2,
            content_hash=_hash(data),
            max_amplitude=0.5,
            pcm_byte_count=len(data),
            source_frame_count=44100,
            source_sample_rate=44100,
            target_sample_rate=48000,
            expected_frame_count=frames,
            endpoint_difference_frames=0,
            ffmpeg_version="ffmpeg 8.1.2",
            profile_version=1,
            staging_pcm_path=str(staged),
        )
        job = env["jobs"].create_job(project_id, JobType.PLAYBACK_RATE)
        build_publishers(
            env["imports"],
            env["projects"],
            env["representations"],
            env["paths"],
            env["jobs"],
            env["waveform_caches"],
        )(job, result.model_dump(mode="json"))

        # The representation resolves under the canonical parent at 48 kHz.
        rep = env["representations"].find_playback(canonical.id, 48000)
        assert rep is not None
        assert rep.sample_rate == 48000
        assert rep.frame_count == frames
        assert abs(frames - 48000) <= 2  # one second at 48 kHz
        assert rep.parent_asset_id == canonical.id
        assert rep.time_mapping.project_rate == 44100
        assert rep.time_mapping.representation_rate == 48000

        # The published bytes on disk are the resampled audio.
        asset = env["projects"].get_asset_by_hash(_hash(data))
        assert asset is not None
        on_disk = env["paths"].data / "assets" / f"{_hash(data)}.pcm"
        assert on_disk.read_bytes() == data
        assert not staged.exists()  # staging moved into the asset store

        # The resampled tone is still 440 Hz.
        assert _zero_crossing_frequency(data, 48000) == pytest.approx(FREQUENCY, rel=0.02)

    def test_same_rate_needs_no_representation(self, env: dict) -> None:
        _project_id, canonical = _seed_ready_project(env, 48000)
        # The route logic: a request at the source's own rate plays the
        # source asset directly; no playback representation is required.
        assert env["representations"].find_playback(canonical.id, 48000) is None
        assert canonical.audio is not None
        assert canonical.audio.sample_rate == 48000
