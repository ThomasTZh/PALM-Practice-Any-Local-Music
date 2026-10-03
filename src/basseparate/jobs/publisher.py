"""Backend publishers for verified job results (M1.4 probe, M1.5 decode,
M1.7 monitoring downmix and playback rate).

The publisher is the only code path that moves decoded audio into the
content-addressed asset store and attaches assets to a project. The
JobManager runs it while the job is still ``running`` (milestone1.md
§8.3.8), so a publisher failure fails the job: a completed job always has
its references committed.

Publishing is idempotent: assets are deduplicated by content hash,
``project_assets`` and ``representations`` rows use ``INSERT OR IGNORE``,
and the project source fields are re-set to the same values.
"""

from __future__ import annotations

import contextlib
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.import_record import (
    ImportRecord,
    ProbeResult,
    TransferState,
)
from basseparate.domain.media_job import JobType, MediaJob
from basseparate.domain.representation import (
    AudioRepresentation,
    CanonicalDecodeResult,
    MonitoringDownmixResult,
    PlaybackRateResult,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_downmix_key,
    compute_playback_key,
    compute_transform_key,
)
from basseparate.media.decode import mime_type_for_format
from basseparate.media.downmix import (
    MATRIX_VERSION,
    manual_matrix,
    standard_51_matrix,
)
from basseparate.storage import (
    ImportRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
)

#: A publisher receives the job (still RUNNING) and its verified result dict.
Publisher = Callable[[MediaJob, dict[str, Any]], None]

PCM_ASSET_MEDIA_TYPE = "application/octet-stream"  # raw f32le PCM, no container


class PublishError(Exception):
    """The publisher could not commit the job's references."""


def _remove_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _publish_probe(job: MediaJob, result: dict[str, Any], imports: ImportRepository) -> None:
    """Persist the verified probe result and auto-select a single stream."""
    if job.import_id is None:
        return
    probe = ProbeResult(**result)
    imports.set_probe_result(job.import_id, probe)
    if len(probe.audio_streams) == 1:
        imports.set_selected_stream(job.import_id, probe.audio_streams[0].index)


def _ensure_pcm_asset(
    projects: ProjectRepository,
    decode: CanonicalDecodeResult,
    asset_dir: Path,
) -> AssetRecord:
    """Move the staged PCM into ``data/assets/<hash>.pcm`` (dedup by hash).

    ``asset_dir`` is the content-addressed asset directory
    (``<storage_root>/data/assets``).

    Dedup policy (milestone1.md §8.4): reuse is by content hash only —
    never by filename or size. Content-hash equality is the stronger form
    of the transformation-key rule: for a deterministic pipeline, identical
    bytes imply an identical transformation key.
    """
    existing = projects.get_asset_by_hash(decode.content_hash)
    staged = Path(decode.staging_pcm_path)
    if existing is not None:
        _remove_quietly(staged)
        return existing
    if not staged.is_file():
        raise PublishError(f"staged PCM file is missing: {decode.staging_pcm_path}")
    destination = asset_dir / f"{decode.content_hash}.pcm"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(destination))
    else:
        # File with this hash already on disk (no DB row): keep it, drop staging.
        _remove_quietly(staged)
    return AssetRecord(
        id=uuid.uuid4(),
        content_hash=decode.content_hash,
        role=AssetRole.SOURCE_PCM,
        relative_path=f"data/assets/{decode.content_hash}.pcm",
        media_type=PCM_ASSET_MEDIA_TYPE,
        byte_count=decode.pcm_byte_count,
        created_at=datetime.now(UTC),
        audio=AudioMetadata(
            sample_rate=decode.sample_rate,
            channel_count=decode.channel_count,
            frame_count=decode.frame_count,
            sample_format="f32le",
        ),
    )


def _ensure_derived_asset(
    projects: ProjectRepository,
    *,
    content_hash: str,
    byte_count: int,
    sample_rate: int,
    channel_count: int,
    frame_count: int,
    staging_path: str,
    asset_dir: Path,
) -> AssetRecord:
    """Move a staged derived PCM into ``data/assets/<hash>.pcm`` (M1.7).

    Dedup by content hash, same policy as the canonical asset: identical
    bytes imply an identical transformation key, so reuse is safe.
    """
    existing = projects.get_asset_by_hash(content_hash)
    staged = Path(staging_path)
    if existing is not None:
        _remove_quietly(staged)
        return existing
    if not staged.is_file():
        raise PublishError(f"staged PCM file is missing: {staging_path}")
    destination = asset_dir / f"{content_hash}.pcm"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(destination))
    else:
        # File with this hash already on disk (no DB row): keep it, drop staging.
        _remove_quietly(staged)
    asset = AssetRecord(
        id=uuid.uuid4(),
        content_hash=content_hash,
        role=AssetRole.DERIVED_PCM,
        relative_path=f"data/assets/{content_hash}.pcm",
        media_type=PCM_ASSET_MEDIA_TYPE,
        byte_count=byte_count,
        created_at=datetime.now(UTC),
        audio=AudioMetadata(
            sample_rate=sample_rate,
            channel_count=channel_count,
            frame_count=frame_count,
            sample_format="f32le",
        ),
    )
    # The row must exist before any representation references it (FK).
    projects.register_asset(asset)
    return asset


def _ensure_original_asset(
    projects: ProjectRepository, import_record: ImportRecord
) -> AssetRecord:
    """Register (or reuse) the asset for the original uploaded file."""
    source_sha256 = import_record.source_sha256
    if source_sha256 is None:  # cannot happen for COMPLETE imports; be defensive
        raise PublishError("complete import is missing its source hash")
    existing = projects.get_asset_by_hash(source_sha256)
    if existing is not None:
        return existing
    probe = import_record.probe_result
    media_type = mime_type_for_format(probe.format_name) if probe else "application/octet-stream"
    return AssetRecord(
        id=uuid.uuid4(),
        content_hash=source_sha256,
        role=AssetRole.SOURCE_ORIGINAL,
        relative_path=f"runtime/uploads/{import_record.id}.part",
        media_type=media_type,
        byte_count=import_record.received_byte_count,
        created_at=datetime.now(UTC),
    )


def _publish_decode(
    job: MediaJob,
    result: dict[str, Any],
    imports: ImportRepository,
    projects: ProjectRepository,
    representations: RepresentationRepository,
    paths: StoragePaths,
) -> None:
    """Publish a canonical decode: assets + representation + project attach.

    The representation row is registered inside
    ``ProjectRepository.publish_source``'s single transaction (together with
    the asset rows it references); ``representations`` is kept in the
    signature for publisher paths that register representations standalone.
    """
    if job.import_id is None:
        raise PublishError("decode job has no import")
    import_record = imports.get_import(job.import_id)
    if import_record is None:
        raise PublishError("the import no longer exists")
    if import_record.transfer_state is not TransferState.COMPLETE:
        raise PublishError(f"import is {import_record.transfer_state.value}, not complete")
    if import_record.source_sha256 is None:
        raise PublishError("the completed import has no source hash")
    if import_record.probe_result is None:
        raise PublishError("the import has no probe result")
    if import_record.selected_stream_index is None:
        raise PublishError("no audio stream is selected on the import")

    decode = CanonicalDecodeResult(**result)
    stream = next(
        (
            s
            for s in import_record.probe_result.audio_streams
            if s.index == import_record.selected_stream_index
        ),
        None,
    )
    if stream is None:
        raise PublishError("the selected stream is not in the probe result")
    if stream.sample_rate != decode.sample_rate or stream.channel_count != decode.channel_count:
        raise PublishError(
            f"decode result ({decode.sample_rate} Hz, {decode.channel_count} ch) does not "
            f"match the selected stream ({stream.sample_rate} Hz, {stream.channel_count} ch)"
        )

    pcm_asset = _ensure_pcm_asset(projects, decode, paths.data / "assets")
    original_asset = _ensure_original_asset(projects, import_record)

    representation = AudioRepresentation(
        asset_id=pcm_asset.id,
        parent_asset_id=original_asset.id,
        role=RepresentationRole.CANONICAL,
        sample_rate=decode.sample_rate,
        channel_count=decode.channel_count,
        channel_layout=decode.channel_layout,
        frame_count=decode.frame_count,
        content_hash=decode.content_hash,
        transform_key=compute_transform_key(
            import_record.source_sha256,
            stream.index,
            decode.profile_version,
            decode.ffmpeg_version,
        ),
        time_mapping=TimeMapping(
            project_rate=decode.sample_rate,
            representation_rate=decode.sample_rate,
        ),
        provenance=RepresentationProvenance(
            tool="ffmpeg",
            tool_version=decode.ffmpeg_version,
            profile_version=decode.profile_version,
            created_at=datetime.now(UTC),
        ),
    )

    # Channel layout: the conventional name when known; a descriptive
    # fallback otherwise (the project invariant requires a non-null layout).
    channel_layout = decode.channel_layout or f"{decode.channel_count}ch"
    source_metadata: dict[str, str] = {
        "format": import_record.probe_result.format_name,
        "stream_codec": stream.codec,
        "max_amplitude": f"{decode.max_amplitude:.6f}",
        "decoder_warnings": "; ".join(decode.decoder_warnings),
        "timing_repair_warnings": "; ".join(decode.timing_repair_warnings),
    }
    if decode.duration_discrepancy_seconds is not None:
        source_metadata["duration_discrepancy_seconds"] = (
            f"{decode.duration_discrepancy_seconds:.3f}"
        )
    if decode.source_start_timestamp_seconds is not None:
        source_metadata["source_start_timestamp_seconds"] = (
            f"{decode.source_start_timestamp_seconds:.3f}"
        )

    projects.publish_source(
        project_id=job.project_id,
        original_asset=original_asset,
        pcm_asset=pcm_asset,
        representation=representation,
        source_stream_index=stream.index,
        sample_rate=decode.sample_rate,
        duration_frames=decode.frame_count,
        channel_count=decode.channel_count,
        channel_layout=channel_layout,
        decode_profile_version=decode.profile_version,
        source_metadata=source_metadata,
    )


def _publish_downmix(
    job: MediaJob,
    result: dict[str, Any],
    projects: ProjectRepository,
    representations: RepresentationRepository,
    paths: StoragePaths,
) -> None:
    """Publish a monitoring downmix: asset + representation + project attach.

    The representation's parent is the canonical asset; the time mapping is
    identity (a downmix does not change the sample rate). The effective
    L/R source channels are stored on the project with the asset.
    """
    downmix = MonitoringDownmixResult(**result)
    project = projects.get_project(job.project_id)
    if project is None:
        raise PublishError(f"project {job.project_id} no longer exists")
    if project.canonical_asset_id is None:
        raise PublishError("the project has no canonical asset")
    canonical = projects.get_asset(project.canonical_asset_id)
    if canonical is None:
        raise PublishError("the project's canonical asset is missing")

    asset = _ensure_derived_asset(
        projects,
        content_hash=downmix.content_hash,
        byte_count=downmix.pcm_byte_count,
        sample_rate=downmix.sample_rate,
        channel_count=downmix.channel_count,
        frame_count=downmix.frame_count,
        staging_path=downmix.staging_pcm_path,
        asset_dir=paths.data / "assets",
    )

    if downmix.downmix_mode == "standard_5_1":
        left_row, right_row = standard_51_matrix()
    else:
        left_row, right_row = manual_matrix(downmix.left_channel, downmix.right_channel)

    representation = AudioRepresentation(
        asset_id=asset.id,
        parent_asset_id=canonical.id,
        role=RepresentationRole.MONITORING_DOWNMIX,
        sample_rate=downmix.sample_rate,
        channel_count=downmix.channel_count,
        channel_layout="stereo",
        frame_count=downmix.frame_count,
        content_hash=downmix.content_hash,
        transform_key=compute_downmix_key(
            canonical.content_hash,
            downmix.downmix_mode,
            downmix.left_channel,
            downmix.right_channel,
            list(left_row),
            list(right_row),
            MATRIX_VERSION,
            downmix.profile_version,
            downmix.ffmpeg_version,
        ),
        time_mapping=TimeMapping(
            project_rate=downmix.sample_rate,
            representation_rate=downmix.sample_rate,
        ),
        provenance=RepresentationProvenance(
            tool="ffmpeg",
            tool_version=downmix.ffmpeg_version,
            profile_version=downmix.profile_version,
            created_at=datetime.now(UTC),
        ),
    )
    # Idempotency: a deduplicated asset already carries its representation.
    if representations.get_representation(asset.id) is None:
        representations.register_representation(representation)
    projects.set_monitoring(
        job.project_id, asset, downmix.left_channel, downmix.right_channel
    )


def _publish_playback(
    job: MediaJob,
    result: dict[str, Any],
    projects: ProjectRepository,
    representations: RepresentationRepository,
    paths: StoragePaths,
) -> None:
    """Publish a playback-rate representation (M1.7).

    Parent is the monitoring asset when present, else the canonical asset.
    The time mapping maps representation frames to project frames
    (``project_position = frame × source_rate / target_rate``). No project
    field is set: playback assets are resolved on demand and several rates
    may coexist.
    """
    playback = PlaybackRateResult(**result)
    project = projects.get_project(job.project_id)
    if project is None:
        raise PublishError(f"project {job.project_id} no longer exists")
    parent_id = project.monitoring_asset_id or project.canonical_asset_id
    if parent_id is None:
        raise PublishError("the project has no source audio asset")
    parent = projects.get_asset(parent_id)
    if parent is None:
        raise PublishError("the project's source audio asset is missing")

    asset = _ensure_derived_asset(
        projects,
        content_hash=playback.content_hash,
        byte_count=playback.pcm_byte_count,
        sample_rate=playback.sample_rate,
        channel_count=playback.channel_count,
        frame_count=playback.frame_count,
        staging_path=playback.staging_pcm_path,
        asset_dir=paths.data / "assets",
    )

    representation = AudioRepresentation(
        asset_id=asset.id,
        parent_asset_id=parent.id,
        role=RepresentationRole.PLAYBACK_RATE,
        sample_rate=playback.sample_rate,
        channel_count=playback.channel_count,
        frame_count=playback.frame_count,
        content_hash=playback.content_hash,
        transform_key=compute_playback_key(
            parent.content_hash,
            playback.source_sample_rate,
            playback.target_sample_rate,
            playback.profile_version,
            playback.ffmpeg_version,
        ),
        time_mapping=TimeMapping(
            project_rate=playback.source_sample_rate,
            representation_rate=playback.target_sample_rate,
        ),
        provenance=RepresentationProvenance(
            tool="ffmpeg",
            tool_version=playback.ffmpeg_version,
            profile_version=playback.profile_version,
            created_at=datetime.now(UTC),
        ),
    )
    # Idempotency: a deduplicated asset already carries its representation.
    if representations.get_representation(asset.id) is None:
        representations.register_representation(representation)


def build_publishers(
    import_repository: ImportRepository,
    project_repository: ProjectRepository,
    representation_repository: RepresentationRepository,
    paths: StoragePaths,
) -> Publisher:
    """Dispatch verified job results to their publisher (M1.4-M1.7)."""

    def publish(job: MediaJob, result: dict[str, Any]) -> None:
        if job.job_type is JobType.PROBE:
            _publish_probe(job, result, import_repository)
        elif job.job_type is JobType.CANONICAL_DECODE:
            _publish_decode(
                job,
                result,
                import_repository,
                project_repository,
                representation_repository,
                paths,
            )
        elif job.job_type is JobType.MONITORING_DOWNMIX:
            _publish_downmix(
                job,
                result,
                project_repository,
                representation_repository,
                paths,
            )
        elif job.job_type is JobType.PLAYBACK_RATE:
            _publish_playback(
                job,
                result,
                project_repository,
                representation_repository,
                paths,
            )
        # WAVEFORM has no publisher yet (M1.8).

    return publish


def build_import_publisher(import_repository: ImportRepository) -> Publisher:
    """Probe-only publisher (M1.4 API; use ``build_publishers`` from M1.5 on)."""

    def publish(job: MediaJob, result: dict[str, Any]) -> None:
        if job.job_type is JobType.PROBE:
            _publish_probe(job, result, import_repository)

    return publish
