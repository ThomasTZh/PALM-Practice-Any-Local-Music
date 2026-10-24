"""Meter features, inference, and manual regions (M3.8, §10)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.meter import (
    DEFAULT_METER_CANDIDATES,
    ManualMeterRegion,
    MeterFeatureArtifact,
    MeterFeatureProfile,
    MeterMap,
    build_meter_map,
    manual_candidate,
    region_validity,
)
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    GridValidity,
    MusicalPosition,
    PulseAcceptance,
    PulseRole,
    RhythmOrigin,
    RhythmPulse,
)
from basseparate.domain.tempo import PULSE_UNIT_QUARTER
from basseparate.rhythm.meter import (
    MeterFeatureError,
    MeterFeatureStore,
    MeterInferenceError,
    extract_meter_features,
    infer_meter,
)
from basseparate.rhythm.tempo import build_automatic_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000
PROJECT_ID = uuid.uuid4()


def _pulse(source: int, index: int, role: PulseRole = PulseRole.BEAT) -> RhythmPulse:
    return RhythmPulse(
        id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        source_frame=source,
        model_frame_index=index,
        role=role,
        acceptance=PulseAcceptance.ACCEPTED,
        confidence=Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9),
        origin=RhythmOrigin.AUTOMATIC,
    )


def _pulses(count: int = 17, interval: int = 24_000) -> list[RhythmPulse]:
    return [
        _pulse(index * interval, index, PulseRole.DOWNBEAT if index % 4 == 0 else PulseRole.BEAT)
        for index in range(count)
    ]


def _tempo(pulses: list[RhythmPulse]):
    return build_automatic_tempo_map(
        pulses,
        project_id=PROJECT_ID,
        project_sample_rate=RATE,
        source_duration_frames=count_frames(pulses),
        hypothesis=PULSE_UNIT_QUARTER,
        created_at=NOW,
    )


def count_frames(pulses: list[RhythmPulse]) -> int:
    return max(pulse.source_frame for pulse in pulses) + 2 * 24_000


def _feature_artifact(frame_count: int, source_hash: str = "ab" * 32) -> MeterFeatureArtifact:
    accent_sha = "cd" * 32
    onset_sha = "ef" * 32
    return MeterFeatureArtifact(
        id=uuid.uuid4(),
        source_hash=source_hash,
        profile=MeterFeatureProfile(),
        frame_count=frame_count,
        accent=ActivationArrayRef(
            relative_path="accent.npy", sha256=accent_sha, element_count=frame_count
        ),
        onset=ActivationArrayRef(
            relative_path="onset.npy", sha256=onset_sha, element_count=frame_count
        ),
        content_hash="12" * 32,
        created_at=NOW,
    )


def _features(pulses: list[RhythmPulse], frame_count: int = 500) -> tuple[np.ndarray, np.ndarray]:
    accent = np.full(frame_count, 0.2, dtype=np.float32)
    onset = np.full(frame_count, 0.2, dtype=np.float32)
    for pulse in pulses:
        index = pulse.source_frame * 50 // RATE
        if pulse.role is PulseRole.DOWNBEAT and index < frame_count:
            accent[index] = 1.0
            onset[index] = 0.9
    return accent, onset


class TestFeatureExtraction:
    def test_extracts_compact_arrays_and_store(self, tmp_path: Path) -> None:
        sample_rate = 22_050
        seconds = 2.0
        times = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
        mono = 0.2 * np.sin(2 * np.pi * 220 * times)
        for beat in range(4):
            start = int(beat * 0.5 * sample_rate)
            length = min(441, len(mono) - start)
            mono[start : start + length] += 0.7 * np.hanning(length)
        pcm = np.stack([mono, mono], axis=1).astype("<f4")
        source = tmp_path / "prepared.pcm"
        source.write_bytes(pcm.tobytes())
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        store = MeterFeatureStore(tmp_path / "features")
        artifact = extract_meter_features(
            source_path=source,
            source_hash=source_hash,
            store=store,
            created_at=NOW,
            chunk_frames=256,
        )
        assert artifact.frame_count == 100
        assert store.verify(artifact)
        accent, onset = store.load(artifact)
        assert accent.dtype == np.float32 and accent.size == 100
        assert onset.size == 100
        assert float(accent.min()) >= 0.0 and float(accent.max()) <= 1.0
        assert float(accent.max()) > float(accent.min())
        assert not list(store.staging.iterdir())

    def test_missing_source(self, tmp_path: Path) -> None:
        with pytest.raises(MeterFeatureError):
            extract_meter_features(
                source_path=tmp_path / "missing.pcm",
                source_hash="ab" * 32,
                store=MeterFeatureStore(tmp_path / "features"),
            )


class TestInference:
    def test_prefers_quadruple_meter_with_downbeats(self) -> None:
        pulses = _pulses()
        tempo = _tempo(pulses)
        accent, onset = _features(pulses)
        artifact = _feature_artifact(len(accent))
        result = infer_meter(
            project_id=PROJECT_ID,
            tempo_map=tempo,
            pulses=pulses,
            feature_artifact=artifact,
            accent=accent,
            onset=onset,
            created_at=NOW,
        )
        selection = result.selections[0]
        assert not selection.unmetered
        assert selection.candidate.numerator == 4
        assert selection.candidate.denominator == 4
        assert selection.bars >= 2
        assert selection.alternatives
        assert selection.confidence.calibrated is False
        assert result.content_hash

    def test_uncertainty_and_alternatives(self) -> None:
        pulses = _pulses()
        tempo = _tempo(pulses)
        accent = np.full(300, 0.5, dtype=np.float32)
        onset = np.full(300, 0.5, dtype=np.float32)
        artifact = _feature_artifact(300)
        from basseparate.domain.meter import MeterScoringProfile

        profile = MeterScoringProfile(uncertain_margin=1.0)
        result = infer_meter(
            project_id=PROJECT_ID,
            tempo_map=tempo,
            pulses=pulses,
            feature_artifact=artifact,
            accent=accent,
            onset=onset,
            profile=profile,
            created_at=NOW,
        )
        selection = result.selections[0]
        assert selection.uncertain
        assert selection.alternatives
        assert selection.score.total <= 1.0

    def test_unmetered_when_too_short(self) -> None:
        pulses = _pulses(count=3)
        tempo = _tempo(pulses)
        accent, onset = _features(pulses, 200)
        artifact = _feature_artifact(200)
        result = infer_meter(
            project_id=PROJECT_ID,
            tempo_map=tempo,
            pulses=pulses,
            feature_artifact=artifact,
            accent=accent,
            onset=onset,
            created_at=NOW,
        )
        selection = result.selections[0]
        assert selection.unmetered
        assert selection.bars == 0
        assert selection.confidence.kind is ConfidenceKind.UNAVAILABLE

    def test_needs_mapped_pulses(self) -> None:
        with pytest.raises(MeterInferenceError):
            infer_meter(
                project_id=PROJECT_ID,
                tempo_map=_tempo(_pulses()),
                pulses=[_pulse(0, 0)],
                feature_artifact=_feature_artifact(10),
                accent=np.zeros(10, dtype=np.float32),
                onset=np.zeros(10, dtype=np.float32),
                created_at=NOW,
            )

    def test_default_candidates(self) -> None:
        labels = {candidate.label for candidate in DEFAULT_METER_CANDIDATES}
        assert {"4/4", "6/8 (3+3)", "7/8 (2+2+3)"} <= labels


class TestManualMeter:
    def test_manual_map_and_boundary_validation(self) -> None:
        four = manual_candidate(4, 4, [1, 1, 1, 1])
        three = manual_candidate(3, 4, [1, 1, 1])
        meter_map = build_meter_map(
            [
                ManualMeterRegion(
                    start=MusicalPosition(numerator=0, denominator=1), candidate=four
                ),
                ManualMeterRegion(
                    start=MusicalPosition(numerator=4, denominator=1), candidate=three
                ),
            ]
        )
        assert meter_map.ends()[0] == MusicalPosition(numerator=4, denominator=1)
        assert region_validity(meter_map) is GridValidity.VALID
        with pytest.raises(ValidationError):
            MeterMap(
                regions=[
                    ManualMeterRegion(
                        start=MusicalPosition(numerator=0, denominator=1), candidate=four
                    ),
                    ManualMeterRegion(
                        start=MusicalPosition(numerator=3, denominator=1), candidate=three
                    ),
                ]
            )

    def test_arbitrary_manual_meter(self) -> None:
        candidate = manual_candidate(5, 16, [2, 3])
        assert candidate.numerator == 5
        assert candidate.denominator == 16
        with pytest.raises(ValidationError):
            manual_candidate(5, 16, [2, 2])

    def test_uncertain_map_validity(self) -> None:
        four = manual_candidate(4, 4, [1, 1, 1, 1])
        meter_map = build_meter_map(
            [
                ManualMeterRegion(
                    start=MusicalPosition(numerator=0, denominator=1),
                    candidate=four,
                    uncertain=True,
                )
            ]
        )
        assert region_validity(meter_map) is GridValidity.UNCERTAIN
