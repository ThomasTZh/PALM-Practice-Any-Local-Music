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
from basseparate.domain.media_job import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidJobTransition,
    JobStage,
    JobState,
    JobType,
    MediaJob,
    assert_transition,
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
from basseparate.domain.waveform import (
    AGGREGATION,
    BASE_BUCKET_FRAMES,
    TILE_BUCKETS,
    WAVEFORM_CACHE_VERSION,
    WaveformCacheRecord,
    WaveformLevelSummary,
    WaveformManifest,
    WaveformResult,
    expected_levels,
    tile_byte_count,
    validate_manifest,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidJobTransition",
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
    "JobState",
    "JobStage",
    "JobType",
    "MediaJob",
    "TERMINAL_STATES",
    "assert_transition",
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
    "WaveformCacheRecord",
    "WaveformLevelSummary",
    "WaveformManifest",
    "WaveformResult",
    "WaveformStatus",
    "AGGREGATION",
    "BASE_BUCKET_FRAMES",
    "TILE_BUCKETS",
    "WAVEFORM_CACHE_VERSION",
    "expected_levels",
    "tile_byte_count",
    "validate_manifest",
]
