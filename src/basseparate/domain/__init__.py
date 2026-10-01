"""Domain models for basseparate.

Pydantic models are the authoritative contract. JSON Schemas and
TypeScript types are generated from these definitions.
"""

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.common import (
    JS_SAFE_INTEGER_MAX,
    HalfOpenInterval,
    Revision,
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.confidence import (
    Confidence,
    ConfidenceAlternative,
    ConfidenceKind,
    ReviewState,
)
from basseparate.domain.import_record import (
    AudioStreamInfo,
    ImportRecord,
    ProbeResult,
    TransferState,
)
from basseparate.domain.project import (
    MAX_CHANNEL_COUNT,
    MAX_SAMPLE_RATE,
    MIN_SAMPLE_RATE,
    ProjectRecord,
    ProjectStatus,
    WaveformStatus,
)
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
)

__all__ = [
    "JS_SAFE_INTEGER_MAX",
    "AssetRecord",
    "AssetRole",
    "AudioMetadata",
    "AudioRepresentation",
    "AudioStreamInfo",
    "Confidence",
    "ConfidenceAlternative",
    "ConfidenceKind",
    "HalfOpenInterval",
    "ImportRecord",
    "MAX_CHANNEL_COUNT",
    "MAX_SAMPLE_RATE",
    "MIN_SAMPLE_RATE",
    "ProbeResult",
    "ProjectRecord",
    "ProjectStatus",
    "RepresentationProvenance",
    "RepresentationRole",
    "Revision",
    "ReviewState",
    "SamplePosition",
    "SampleRate",
    "Sha256Hash",
    "TimeMapping",
    "TransferState",
    "UtcTimestamp",
    "Uuid",
    "WaveformStatus",
]
