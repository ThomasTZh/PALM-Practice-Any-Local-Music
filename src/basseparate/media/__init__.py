"""Media processing helpers (M1.3+)."""

from basseparate.media.decode import (
    DEFAULT_DECODE_TIMEOUT_SECONDS,
    DecodeCancelledError,
    DecodeError,
    DecodeFailedError,
    DecodeProgress,
    DecodeTimeoutError,
    EmptyAudioError,
    InsufficientDiskSpaceError,
    NonFiniteSamplesError,
    decode_canonical,
    validate_pcm,
)
from basseparate.media.probe import (
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    NoAudioStreamError,
    ProbeCancelledError,
    ProbeError,
    ProbeFailedError,
    ProbeTimeoutError,
    UnsupportedMediaError,
    probe_media,
    tool_versions,
)

__all__ = [
    "DEFAULT_DECODE_TIMEOUT_SECONDS",
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "DecodeCancelledError",
    "DecodeError",
    "DecodeFailedError",
    "DecodeProgress",
    "DecodeTimeoutError",
    "EmptyAudioError",
    "InsufficientDiskSpaceError",
    "NoAudioStreamError",
    "NonFiniteSamplesError",
    "ProbeCancelledError",
    "ProbeError",
    "ProbeFailedError",
    "ProbeTimeoutError",
    "UnsupportedMediaError",
    "decode_canonical",
    "probe_media",
    "tool_versions",
    "validate_pcm",
]
