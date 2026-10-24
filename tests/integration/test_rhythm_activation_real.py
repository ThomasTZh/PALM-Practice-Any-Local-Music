"""Real Beat This! activation run and publication (M3.4).

Skipped unless BASSEPARATE_RHYTHM_TEST_CHECKPOINT points at a verified
installed checkpoint. The manual acceptance run sets it to the managed
`final0.ckpt`; automated environments without the model remain green.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.rhythm import RhythmAnalysisRun, RhythmAnalysisStatus
from basseparate.domain.rhythm_input import RhythmInputPlan
from basseparate.media.rhythm_input import prepare_rhythm_input
from basseparate.rhythm import (
    ActivationRequest,
    RhythmActivationStore,
    run_and_publish,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ProjectRepository, RhythmRepository

CHECKPOINT = os.environ.get("BASSEPARATE_RHYTHM_TEST_CHECKPOINT")
pytestmark = pytest.mark.skipif(
    not CHECKPOINT or not Path(CHECKPOINT).is_file(),
    reason="BASSEPARATE_RHYTHM_TEST_CHECKPOINT is not set to a verified checkpoint",
)
MODEL_HASH = "cd" * 32


def _fixture(sample_rate: int = 48_000, seconds: float = 5.0) -> np.ndarray:
    times = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
    signal = 0.05 * np.sin(2.0 * np.pi * 220.0 * times)
    for beat in range(int(seconds / 0.5)):
        start = int(round(beat * 0.5 * sample_rate))
        length = min(int(0.02 * sample_rate), len(signal) - start)
        envelope = np.exp(-np.arange(length) / (0.004 * sample_rate))
        signal[start : start + length] += (0.8 if beat % 4 == 0 else 0.4) * envelope
    stereo = np.stack([signal, signal], axis=1)
    return np.ascontiguousarray(stereo, dtype="<f4")


def _prepare(tmp_path: Path) -> tuple[Path, str, int]:
    source = tmp_path / "source.pcm"
    data = _fixture()
    source.write_bytes(data.tobytes())
    import hashlib

    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    plan = RhythmInputPlan(
        input_role="original_mix",
        asset_id=uuid.uuid4(),
        source_hash=source_hash,
        sample_rate=48_000,
        channel_count=2,
        model_id="beat_this_final0",
        model_manifest_hash=MODEL_HASH,
        adapter_version="beat-this-adapter-v1",
    )
    outcome = asyncio.run(
        prepare_rhythm_input(
            plan=plan, source_path=source, work_dir=tmp_path / "prep", max_threads=2
        )
    )
    return outcome.final_path, outcome.content_hash, plan.sample_rate


def _run(
    tmp_path: Path,
    db_path: Path,
    prepared: Path,
    input_hash: str,
    sample_rate: int,
    index: int,
) -> tuple[RhythmAnalysisRun, object]:
    projects = ProjectRepository(db_path)
    project = projects.list_projects()[0]
    run_id = uuid.uuid4()
    staging = tmp_path / f"staging-{index}"
    request = ActivationRequest(
        run_id=run_id,
        project_id=project.id,
        input_path=prepared,
        input_hash=input_hash,
        staging_dir=staging,
        checkpoint_path=Path(CHECKPOINT),  # type: ignore[arg-type]
        model_id="beat_this_final0",
        model_manifest_hash=MODEL_HASH,
        adapter_version="beat-this-adapter-v1",
        project_sample_rate=sample_rate,
        threads=4,
    )
    run = RhythmAnalysisRun(
        id=run_id,
        project_id=project.id,
        input_asset_id=uuid.uuid4(),
        input_hash=input_hash,
        input_role="original_mix",
        model_manifest_id="beat_this_final0",
        model_manifest_hash=MODEL_HASH,
        model_preset="final0",
        adapter_version="beat-this-adapter-v1",
        preprocessing_profile="beat-this-logmel-22050-441-v1",
        preprocessing_version=1,
        requested_device="cpu",
        actual_device="cpu",
        started_at=datetime.now(UTC),
        status=RhythmAnalysisStatus.RUNNING,
    )
    repo = RhythmRepository(db_path)
    repo.create_run(run)
    store = RhythmActivationStore(tmp_path / "rhythm")
    completed, manifest = run_and_publish(
        run=run,
        request=request,
        store=store,
        repository=repo,
        source_asset_id=run.input_asset_id,
        output_semantics="test: raw Beat This! logits",
        timeout_seconds=600.0,
    )
    assert completed.status is RhythmAnalysisStatus.COMPLETED
    assert store.verify(manifest)  # type: ignore[arg-type]
    return completed, manifest


def test_real_final0_activation_determinism(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "basseparate.db"
    initialize_database(db_path)
    ProjectRepository(db_path).create_project("Rhythm")
    prepared, input_hash, sample_rate = _prepare(tmp_path)

    first_run, first = _run(tmp_path, db_path, prepared, input_hash, sample_rate, 1)
    second_run, second = _run(tmp_path, db_path, prepared, input_hash, sample_rate, 2)

    assert first_run.activation_artifact_id == first.artifact_id
    assert first.model_frame_count == 251
    assert first.beat.sha256 == second.beat.sha256
    assert first.downbeat.sha256 == second.downbeat.sha256
    assert first.content_hash == second.content_hash
    assert first.frame_mapping.project_sample_rate == 48_000
    assert first_run.peak_host_memory_bytes is not None
    assert first_run.peak_host_memory_bytes > 0
