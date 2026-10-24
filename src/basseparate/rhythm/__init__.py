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
from basseparate.rhythm.commands import (
    RhythmCommandConflict,
    RhythmCommandError,
    RhythmCommandService,
    apply_rhythm_op,
)
from basseparate.rhythm.decoder import (
    DecodeInput,
    RhythmDecodeError,
    decode_arrays,
    decode_artifact,
    decoded_content_hash,
)
from basseparate.rhythm.grid import (
    GridError,
    bar_beat_label,
    default_bar_origin,
    derive_grid,
    first_downbeat_origin,
    pickup_interval,
    set_first_numbered_bar,
)
from basseparate.rhythm.meter import (
    MeterFeatureError,
    MeterFeatureStore,
    MeterInferenceError,
    extract_meter_features,
    infer_meter,
)
from basseparate.rhythm.results import (
    RhythmResultError,
    activate_branch,
    activate_result,
    create_branch_from_result,
    publish_decoded_result,
)
from basseparate.rhythm.tempo import (
    TempoMapBuildError,
    TempoMapConflictError,
    bpm_for_display_unit,
    build_automatic_tempo_map,
    build_manual_tempo_map,
    map_round_trip_error_frames,
    reinterpret_tempo_map,
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
    "RhythmResultError",
    "activate_branch",
    "activate_result",
    "create_branch_from_result",
    "publish_decoded_result",
    "TempoMapBuildError",
    "TempoMapConflictError",
    "bpm_for_display_unit",
    "build_automatic_tempo_map",
    "build_manual_tempo_map",
    "map_round_trip_error_frames",
    "reinterpret_tempo_map",
    "MeterFeatureError",
    "MeterFeatureStore",
    "MeterInferenceError",
    "extract_meter_features",
    "infer_meter",
    "GridError",
    "bar_beat_label",
    "default_bar_origin",
    "derive_grid",
    "first_downbeat_origin",
    "pickup_interval",
    "set_first_numbered_bar",
    "RhythmCommandConflict",
    "RhythmCommandError",
    "RhythmCommandService",
    "apply_rhythm_op",
]
