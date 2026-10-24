"""Stable rhythm module identifiers and the default run graph (M3.17 §19.1)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RhythmModuleId(StrEnum):
    ACTIVATION_INFERENCE = "rhythm.activation_inference.v1"
    PULSE_DECODING = "rhythm.pulse_decoding.v1"
    TEMPO_MAP = "rhythm.tempo_map.v1"
    METER_INFERENCE = "rhythm.meter_inference.v1"
    ANALYZE_RHYTHM = "rhythm.analyze.v1"


class RhythmPipelineStage(BaseModel):
    model_config = ConfigDict(frozen=True)

    module_id: RhythmModuleId
    requires: list[RhythmModuleId] = Field(default_factory=list)
    description: str


DEFAULT_RHYTHM_PIPELINE: tuple[RhythmPipelineStage, ...] = (
    RhythmPipelineStage(
        module_id=RhythmModuleId.ACTIVATION_INFERENCE,
        description="Beat This! framewise beat/downbeat activation inference.",
    ),
    RhythmPipelineStage(
        module_id=RhythmModuleId.PULSE_DECODING,
        requires=[RhythmModuleId.ACTIVATION_INFERENCE],
        description="Versioned source-aligned pulse decoding.",
    ),
    RhythmPipelineStage(
        module_id=RhythmModuleId.TEMPO_MAP,
        requires=[RhythmModuleId.PULSE_DECODING],
        description="Monotonic piecewise-linear tempo-map construction.",
    ),
    RhythmPipelineStage(
        module_id=RhythmModuleId.METER_INFERENCE,
        requires=[RhythmModuleId.TEMPO_MAP],
        description="Meter candidate scoring and ambiguity-preserving selection.",
    ),
)


def analyze_rhythm_stage() -> RhythmPipelineStage:
    return RhythmPipelineStage(
        module_id=RhythmModuleId.ANALYZE_RHYTHM,
        requires=[stage.module_id for stage in DEFAULT_RHYTHM_PIPELINE],
        description="Validated automatic rhythm result pipeline.",
    )


def module_catalog() -> list[RhythmPipelineStage]:
    return [*DEFAULT_RHYTHM_PIPELINE, analyze_rhythm_stage()]
