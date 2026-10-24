"""Rhythm analysis execution and activation publication (M3.4).

The application-side service runs the isolated Beat This! worker and
publishes immutable framewise activation artifacts. It imports no torch;
the worker environment does that.
"""

from basseparate.rhythm.activations import (
    BEAT_FILE,
    DOWNBEAT_FILE,
    MANIFEST_FILE,
    ActivationRequest,
    ActivationWorkerResult,
    RhythmActivationCancelled,
    RhythmActivationError,
    RhythmActivationFailed,
    RhythmActivationInvalid,
    RhythmActivationStore,
    artifact_content_hash,
    build_manifest,
    run_activation_worker,
    run_and_publish,
    validate_activation_array,
)
from basseparate.rhythm.decoder import (
    DecodeInput,
    RhythmDecodeError,
    decode_arrays,
    decode_artifact,
    decoded_content_hash,
)

__all__ = [
    "BEAT_FILE",
    "DOWNBEAT_FILE",
    "MANIFEST_FILE",
    "ActivationRequest",
    "ActivationWorkerResult",
    "RhythmActivationCancelled",
    "RhythmActivationError",
    "RhythmActivationFailed",
    "RhythmActivationInvalid",
    "RhythmActivationStore",
    "artifact_content_hash",
    "build_manifest",
    "run_activation_worker",
    "run_and_publish",
    "validate_activation_array",
    "DecodeInput",
    "RhythmDecodeError",
    "decode_arrays",
    "decode_artifact",
    "decoded_content_hash",
]
