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
from basseparate.domain.project import ProjectRecord, ProjectStatus

__all__ = [
    "JS_SAFE_INTEGER_MAX",
    "AssetRecord",
    "AssetRole",
    "AudioMetadata",
    "Confidence",
    "ConfidenceAlternative",
    "ConfidenceKind",
    "HalfOpenInterval",
    "ProjectRecord",
    "ProjectStatus",
    "Revision",
    "ReviewState",
    "SamplePosition",
    "SampleRate",
    "Sha256Hash",
    "UtcTimestamp",
    "Uuid",
]
