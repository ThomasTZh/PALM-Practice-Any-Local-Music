"""Meter feature extraction and inference (M3.8, milestone3.md §10).

Accent/onset features are extracted from the prepared reference mix with
bounded memory and versioned profiles. Inference scores explicit meter
candidates against accepted pulses, the tempo map, and those features,
retaining runner-ups, an uncertainty margin, and an explicit unmetered
result. Meter is never inferred from downbeats alone.

Automatic inference currently selects one region over the mapped pulse
range; multiple automatic meter changes and their sequence decoding are
deferred to the editing package, which can build a validated `MeterMap`
from manual regions today.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import uuid
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import numpy as np

from basseparate.domain.common import Uuid
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.meter import (
    DEFAULT_METER_CANDIDATES,
    METER_FEATURE_PROFILE,
    METER_SCORING_PROFILE,
    AutomaticMeterResult,
    MeterAlternative,
    MeterCandidate,
    MeterFeatureArtifact,
    MeterFeatureProfile,
    MeterScoreComponents,
    MeterScoringProfile,
    MeterSelection,
    confidence_for_selection,
    meter_result_content_hash,
)
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    MusicalPosition,
    PulseAcceptance,
    PulseRole,
    RhythmPulse,
)
from basseparate.domain.tempo import TempoMap

ACCENT_FILE = "accent.npy"
ONSET_FILE = "onset.npy"
MANIFEST_FILE = "manifest.json"


class MeterFeatureError(Exception):
    """Feature extraction or persistence failed."""


class MeterInferenceError(Exception):
    """Meter inference inputs are invalid."""


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


class MeterFeatureStore:
    """Managed store for compact accent/onset feature artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.staging = self.root / ".staging"
        self.features = self.root / "features"

    def artifact_dir(self, feature_id: Uuid) -> Path:
        return self.features / str(feature_id)

    def publish(
        self,
        artifact: MeterFeatureArtifact,
        *,
        accent_path: Path,
        onset_path: Path,
    ) -> Path:
        self.staging.mkdir(parents=True, exist_ok=True)
        self.features.mkdir(parents=True, exist_ok=True)
        destination = self.artifact_dir(artifact.id)
        if destination.exists():
            raise MeterFeatureError(f"feature artifact {artifact.id} already exists")
        tmp = self.staging / f"{artifact.id}.{uuid.uuid4().hex}.tmp"
        tmp.mkdir(parents=True)
        try:
            shutil.copyfile(accent_path, tmp / ACCENT_FILE)
            shutil.copyfile(onset_path, tmp / ONSET_FILE)
            (tmp / MANIFEST_FILE).write_text(
                json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tmp.replace(destination)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return destination

    def verify(self, artifact: MeterFeatureArtifact) -> bool:
        directory = self.artifact_dir(artifact.id)
        accent = directory / ACCENT_FILE
        onset = directory / ONSET_FILE
        return (
            accent.is_file()
            and onset.is_file()
            and _sha256_file(accent) == artifact.accent.sha256
            and _sha256_file(onset) == artifact.onset.sha256
        )

    def load(self, artifact: MeterFeatureArtifact) -> tuple[np.ndarray, np.ndarray]:
        directory = self.artifact_dir(artifact.id)
        try:
            accent = np.load(directory / ACCENT_FILE, allow_pickle=False)
            onset = np.load(directory / ONSET_FILE, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise MeterFeatureError(f"cannot read feature artifact: {exc}") from exc
        if accent.dtype != np.float32 or onset.dtype != np.float32:
            raise MeterFeatureError("feature arrays must be float32")
        if accent.ndim != 1 or onset.ndim != 1 or accent.size != onset.size:
            raise MeterFeatureError("feature arrays must be equal-length 1-D arrays")
        return accent, onset


def _normalize(values: np.ndarray, percentile: float) -> np.ndarray:
    positive = values[values > 0]
    if positive.size == 0:
        return np.zeros_like(values, dtype=np.float32)
    scale = float(np.percentile(positive, percentile))
    if not math.isfinite(scale) or scale <= 0:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip(values / scale, 0.0, 1.0).astype(np.float32)


def extract_meter_features(
    *,
    source_path: Path,
    source_hash: str,
    store: MeterFeatureStore,
    profile: MeterFeatureProfile = METER_FEATURE_PROFILE,
    feature_id: Uuid | None = None,
    created_at: datetime | None = None,
    chunk_frames: int = 2048,
) -> MeterFeatureArtifact:
    """Extract accent and onset arrays with chunked, bounded processing."""
    if not source_path.is_file():
        raise MeterFeatureError(f"prepared PCM not found: {source_path}")
    size = source_path.stat().st_size
    if size % 8 != 0:
        raise MeterFeatureError("prepared PCM must be aligned stereo f32le")
    mono = np.memmap(source_path, dtype="<f4", mode="r").reshape(-1, 2).mean(axis=1)
    total_frames = int(math.ceil(mono.size / profile.frame_hop))
    accent = np.zeros(total_frames, dtype=np.float32)
    onset = np.zeros(total_frames, dtype=np.float32)
    previous_magnitude: np.ndarray | None = None
    hop = profile.frame_hop
    fft_size = profile.spectral_fft_size
    for start_frame in range(0, total_frames, chunk_frames):
        end_frame = min(total_frames, start_frame + chunk_frames)
        for frame_index in range(start_frame, end_frame):
            start = frame_index * hop
            window = mono[start : start + fft_size].astype(np.float64)
            if window.size == 0:
                continue
            hopslice = mono[start : start + hop].astype(np.float64)
            accent[frame_index] = float(np.sqrt(np.mean(hopslice * hopslice)))
            padded = np.zeros(fft_size, dtype=np.float64)
            padded[: window.size] = window
            magnitude = np.abs(np.fft.rfft(padded))
            if previous_magnitude is not None:
                onset[frame_index] = float(np.maximum(magnitude - previous_magnitude, 0.0).sum())
            previous_magnitude = magnitude
    accent = _normalize(accent, profile.normalization_percentile)
    onset = _normalize(onset, profile.normalization_percentile)

    staging = store.staging / f"{feature_id or uuid.uuid4()}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(parents=True, exist_ok=True)
    accent_path = staging / ACCENT_FILE
    onset_path = staging / ONSET_FILE
    np.save(accent_path, accent)
    np.save(onset_path, onset)

    ident = feature_id or uuid.uuid4()
    artifact = MeterFeatureArtifact(
        id=ident,
        source_hash=source_hash,
        profile=profile,
        frame_count=total_frames,
        accent=ActivationArrayRef(
            relative_path=ACCENT_FILE,
            sha256=_sha256_file(accent_path),
            element_count=total_frames,
        ),
        onset=ActivationArrayRef(
            relative_path=ONSET_FILE,
            sha256=_sha256_file(onset_path),
            element_count=total_frames,
        ),
        content_hash=hashlib.sha256(
            (
                f"{_sha256_file(accent_path)}:{_sha256_file(onset_path)}:"
                f"{source_hash}:{profile.profile_id}:{profile.version}"
            ).encode()
        ).hexdigest(),
        created_at=created_at or _now(),
    )
    try:
        store.publish(artifact, accent_path=accent_path, onset_path=onset_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return artifact


def _feature_index(source_frame: int, project_rate: int, frame_rate: float) -> int:
    return max(0, int(math.floor(source_frame * frame_rate / project_rate + 0.5)))


def _feature_value(
    values: np.ndarray, source_frame: int, project_rate: int, frame_rate: float
) -> float:
    index = min(_feature_index(source_frame, project_rate, frame_rate), max(0, values.size - 1))
    return float(values[index])


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score_candidate(
    candidate: MeterCandidate,
    phase: int,
    *,
    pulses: list[RhythmPulse],
    musical: list[MusicalPosition],
    tempo_map: TempoMap,
    accent: np.ndarray,
    onset: np.ndarray,
    project_rate: int,
    frame_rate: float,
    profile: MeterScoringProfile,
) -> tuple[MeterScoreComponents, int] | None:
    beats = len(candidate.grouping)
    if len(pulses) < phase + beats * profile.min_bars + 1:
        return None
    bars = (len(pulses) - phase - 1) // beats
    if bars < profile.min_bars:
        return None
    bar_indices = [phase + bar * beats for bar in range(bars + 1)]
    bar_indices = [index for index in bar_indices if index < len(pulses)]
    if len(bar_indices) < profile.min_bars + 1:
        return None
    bar_pulses = [pulses[index] for index in bar_indices]
    primary = [
        pulses[index] for index in range(phase, phase + bars * beats + 1) if index < len(pulses)
    ]

    downbeat = sum(
        1.0 if pulse.role is PulseRole.DOWNBEAT else pulse.confidence.value or 0.0
        for pulse in bar_pulses
    ) / len(bar_pulses)
    beat = sum(pulse.confidence.value or 0.0 for pulse in primary) / len(primary)

    bar_accent = [
        _feature_value(accent, pulse.source_frame, project_rate, frame_rate) for pulse in bar_pulses
    ]
    other = [
        _feature_value(accent, pulse.source_frame, project_rate, frame_rate)
        for index, pulse in enumerate(primary)
        if index % beats != 0
    ]
    other_mean = sum(other) / len(other) if other else 0.0
    start_mean = sum(bar_accent) / len(bar_accent)
    accent_score = _clip(0.5 + (start_mean - other_mean) / 2.0)

    subdivision_values: list[float] = []
    for bar in range(bars):
        base = phase + bar * beats
        for offset, part in enumerate(candidate.grouping):
            index = base + offset
            if index + 1 >= len(pulses):
                continue
            left_musical = musical[index]
            right_musical = musical[index + 1]
            delta = right_musical.as_quarter_notes() - left_musical.as_quarter_notes()
            if delta <= 0:
                continue
            for step in range(1, part):
                position = left_musical.as_quarter_notes() + delta * Fraction(step, part)
                try:
                    source = tempo_map.map_musical_to_source(
                        MusicalPosition(
                            numerator=position.numerator, denominator=position.denominator
                        )
                    )
                except ValueError:
                    continue
                subdivision_values.append(_feature_value(onset, source, project_rate, frame_rate))
    subdivision = sum(subdivision_values) / len(subdivision_values) if subdivision_values else 0.5

    bar_sources = [pulse.source_frame for pulse in bar_pulses]
    intervals = [
        (right - left) / project_rate
        for left, right in zip(bar_sources, bar_sources[1:], strict=False)
    ]
    if intervals:
        mean = sum(intervals) / len(intervals)
        variance = sum((value - mean) ** 2 for value in intervals) / len(intervals)
        cv = math.sqrt(variance) / mean if mean > 0 else 1.0
        stability = _clip(1.0 - cv)
    else:
        stability = 0.0

    missing = _clip(1.0 - max(0, len(pulses) - (phase + bars * beats + 1)) / max(1, len(pulses)))
    total = (
        profile.weights["downbeat"] * _clip(downbeat)
        + profile.weights["beat"] * _clip(beat)
        + profile.weights["accent"] * accent_score
        + profile.weights["subdivision"] * _clip(subdivision)
        + profile.weights["stability"] * stability
        + profile.weights["missing_pulse"] * missing
    )
    return (
        MeterScoreComponents(
            downbeat=_clip(downbeat),
            beat=_clip(beat),
            accent=accent_score,
            subdivision=_clip(subdivision),
            stability=stability,
            missing_pulse=missing,
            total=_clip(total),
        ),
        bars,
    )


def infer_meter(
    *,
    project_id: Uuid,
    tempo_map: TempoMap,
    pulses: list[RhythmPulse],
    feature_artifact: MeterFeatureArtifact,
    accent: np.ndarray,
    onset: np.ndarray,
    profile: MeterScoringProfile = METER_SCORING_PROFILE,
    candidates: tuple[MeterCandidate, ...] = DEFAULT_METER_CANDIDATES,
    result_id: Uuid | None = None,
    created_at: datetime | None = None,
) -> AutomaticMeterResult:
    """Score candidates and publish one automatic meter result (§10.4)."""
    accepted = [
        pulse
        for pulse in pulses
        if pulse.acceptance is PulseAcceptance.ACCEPTED
        and tempo_map.anchors[0].source_frame
        <= pulse.source_frame
        <= tempo_map.anchors[-1].source_frame
    ]
    accepted.sort(key=lambda pulse: pulse.source_frame)
    if len(accepted) < 2:
        raise MeterInferenceError("meter inference needs at least two mapped pulses")
    musical = [tempo_map.map_source_to_musical(pulse.source_frame) for pulse in accepted]
    if len({(position.numerator, position.denominator) for position in musical}) != len(musical):
        raise MeterInferenceError("pulses collapse to duplicate musical positions")

    scored: list[tuple[MeterCandidate, int, MeterScoreComponents, int]] = []
    for candidate in candidates:
        best: tuple[int, MeterScoreComponents, int] | None = None
        for phase in range(len(candidate.grouping)):
            outcome = _score_candidate(
                candidate,
                phase,
                pulses=accepted,
                musical=musical,
                tempo_map=tempo_map,
                accent=accent,
                onset=onset,
                project_rate=tempo_map.project_sample_rate,
                frame_rate=feature_artifact.profile.frame_rate,
                profile=profile,
            )
            if outcome is None:
                continue
            score, bars = outcome
            if best is None or score.total > best[1].total:
                best = (phase, score, bars)
        if best is not None:
            scored.append((candidate, best[0], best[1], best[2]))

    now = created_at or _now()
    if not scored:
        selection = MeterSelection(
            candidate=DEFAULT_METER_CANDIDATES[2],
            phase=0,
            start=musical[0],
            end=musical[-1],
            bars=0,
            score=MeterScoreComponents(
                downbeat=0.0,
                beat=0.0,
                accent=0.0,
                subdivision=0.0,
                stability=0.0,
                missing_pulse=0.0,
                total=0.0,
            ),
            uncertain=True,
            unmetered=True,
            confidence=Confidence(
                kind=ConfidenceKind.UNAVAILABLE,
                value=None,
                calibrated=False,
                method="meter-score-v1",
            ),
        )
        selections = [selection]
        warnings = ["no candidate had enough mapped bars"]
    else:
        scored.sort(key=lambda entry: entry[2].total, reverse=True)
        best_candidate, best_phase, best_score, best_bars = scored[0]
        alternatives = [
            MeterAlternative(candidate=entry[0], phase=entry[1], score=entry[2])
            for entry in scored[1:7]
        ]
        margin = best_score.total - (alternatives[0].score.total if alternatives else 0.0)
        uncertain = margin < profile.uncertain_margin
        unmetered = best_score.total < profile.unmetered_threshold
        if unmetered:
            alternatives = []
        start = musical[best_phase]
        end_index = min(best_phase + best_bars * len(best_candidate.grouping), len(musical) - 1)
        end = musical[end_index]
        if end == start:
            end = start.add(MusicalPosition(numerator=1, denominator=1))
        confidence = confidence_for_selection(
            best_score, uncertain=uncertain, alternatives=alternatives
        )
        selection = MeterSelection(
            candidate=best_candidate,
            phase=best_phase,
            start=start,
            end=end,
            bars=0 if unmetered else best_bars,
            score=best_score,
            alternatives=alternatives,
            uncertain=uncertain or unmetered,
            unmetered=unmetered,
            confidence=confidence,
        )
        selections = [selection]
        warnings = ["meter inference is uncertain"] if uncertain else []
        if unmetered:
            warnings.append("best candidate score is below the unmetered threshold")

    content_hash = meter_result_content_hash(
        project_id=project_id,
        tempo_map_id=tempo_map.id,
        feature_artifact_id=feature_artifact.id,
        profile=profile,
        feature_profile=feature_artifact.profile,
        selections=selections,
    )
    return AutomaticMeterResult(
        id=result_id or uuid.uuid4(),
        project_id=project_id,
        tempo_map_id=tempo_map.id,
        feature_artifact_id=feature_artifact.id,
        profile=profile,
        feature_profile=feature_artifact.profile,
        selections=selections,
        warnings=warnings,
        content_hash=content_hash,
        created_at=now,
    )
