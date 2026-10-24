"""Immutable automatic rhythm results (M3.6, milestone3.md §8).

An automatic result is published from one completed activation run and a
versioned decode. It is immutable: manual corrections live in editable
branches that reference it, and reruns create new result versions while
keeping older results and all branches.

Publishing is progressive. This package publishes the `decoded` stage
(accepted and candidate pulses) with the grid pending; the tempo-map,
meter, and complete stages arrive with M3.7–M3.9 and add references to
their artifacts.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import (
    SamplePosition,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.rhythm import (
    BarOriginState,
    PulseAcceptance,
    RhythmInputRole,
    RhythmPulse,
)
from basseparate.domain.rhythm_decode import BeatDecoderProfile


class RhythmResultStage(StrEnum):
    """Progressive publication stage (§8.2)."""

    ACTIVATION = "activation"
    DECODED = "decoded"
    TEMPO_MAP = "tempo_map"
    METER = "meter"
    COMPLETE = "complete"


class RhythmResultStatus(StrEnum):
    """Validation status of an automatic result."""

    DECODED = "decoded"
    VALID = "valid"
    INVALID = "invalid"


class RhythmResultRecord(BaseModel):
    """One immutable automatic rhythm result (§8.1).

    ``accepted_pulses`` seed automatic tempo-map construction;
    ``candidate_pulses`` preserve ambiguous evidence. The pulse parent is
    this result, never a branch: a branch copy changes the parent while
    preserving the source frame and provenance.
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    run_id: Uuid
    activation_artifact_id: Uuid
    decoded_content_hash: Sha256Hash
    decoder_profile: BeatDecoderProfile
    input_role: RhythmInputRole
    stage: RhythmResultStage = RhythmResultStage.DECODED
    status: RhythmResultStatus = RhythmResultStatus.DECODED
    accepted_pulses: list[RhythmPulse] = Field(default_factory=list)
    candidate_pulses: list[RhythmPulse] = Field(default_factory=list)
    tempo_map_id: Uuid | None = None
    meter_result_id: Uuid | None = None
    bar_origin_hypothesis: BarOriginState | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: UtcTimestamp
    source_duration_frames: SamplePosition
    content_hash: Sha256Hash

    @model_validator(mode="after")
    def _check_result(self) -> RhythmResultRecord:
        accepted_sources = [pulse.source_frame for pulse in self.accepted_pulses]
        if len(set(accepted_sources)) != len(accepted_sources):
            raise ValueError("accepted pulses must not share a source frame")
        for pulse in self.accepted_pulses:
            if pulse.parent_id != self.id:
                raise ValueError("automatic result pulses must belong to the result")
            if pulse.acceptance is not PulseAcceptance.ACCEPTED:
                raise ValueError("the accepted layer may only contain accepted pulses")
            if pulse.source_frame > self.source_duration_frames:
                raise ValueError("an accepted pulse lies beyond the source duration")
        for pulse in self.candidate_pulses:
            if pulse.parent_id != self.id:
                raise ValueError("automatic result pulses must belong to the result")
            if pulse.acceptance is PulseAcceptance.ACCEPTED:
                raise ValueError("the candidate layer must not contain accepted pulses")
        if self.stage is RhythmResultStage.COMPLETE:
            if self.status is not RhythmResultStatus.VALID:
                raise ValueError("a complete result must be valid")
            if self.tempo_map_id is None or self.meter_result_id is None:
                raise ValueError("a complete result requires tempo-map and meter references")
        elif self.status is RhythmResultStatus.VALID:
            raise ValueError("only a complete result may be valid")
        if (
            self.status is RhythmResultStatus.DECODED
            and self.stage is RhythmResultStage.COMPLETE
        ):
            raise ValueError("a decoded result cannot be at the complete stage")
        return self


def result_content_hash(
    *,
    run_id: Uuid,
    activation_artifact_id: Uuid,
    decoded_content_hash: str,
    decoder_profile: BeatDecoderProfile,
    accepted_pulses: list[RhythmPulse],
    candidate_pulses: list[RhythmPulse],
    stage: RhythmResultStage,
    status: RhythmResultStatus,
    source_duration_frames: int,
) -> Sha256Hash:
    """Deterministic identity of one automatic result (no random IDs)."""

    def pulse_data(pulse: RhythmPulse) -> dict[str, Any]:
        return {
            "source_frame": pulse.source_frame,
            "model_frame": pulse.model_frame_index,
            "role": pulse.role.value,
            "acceptance": pulse.acceptance.value,
            "confidence": pulse.confidence.model_dump(mode="json"),
        }

    payload = {
        "artefact": "automatic-rhythm-result",
        "version": 1,
        "run_id": str(run_id),
        "activation_artifact_id": str(activation_artifact_id),
        "decoded_content_hash": decoded_content_hash,
        "decoder_profile": decoder_profile.model_dump(mode="json"),
        "accepted": [pulse_data(pulse) for pulse in accepted_pulses],
        "candidates": [pulse_data(pulse) for pulse in candidate_pulses],
        "stage": stage.value,
        "status": status.value,
        "source_duration_frames": source_duration_frames,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
