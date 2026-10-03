"""Backend publishers for verified job results (M1.4 probe, M1.5 decode).

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
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_transform_key,
)
from basseparate.media.decode import mime_type_for_format
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


def build_publishers(
    import_repository: ImportRepository,
    project_repository: ProjectRepository,
    representation_repository: RepresentationRepository,
    paths: StoragePaths,
) -> Publisher:
    """Dispatch verified job results to their publisher (M1.5)."""

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
        # The remaining job types have no publisher yet (M1.6+).

    return publish


def build_import_publisher(import_repository: ImportRepository) -> Publisher:
    """Probe-only publisher (M1.4 API; use ``build_publishers`` from M1.5 on)."""

    def publish(job: MediaJob, result: dict[str, Any]) -> None:
        if job.job_type is JobType.PROBE:
            _publish_probe(job, result, import_repository)

    return publish
