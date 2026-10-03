"""Asset media routes (M1.9, milestone1.md §11.3).

Routes (all authenticated, loopback-only):
- GET /api/v1/assets/{asset_id}/metadata — audio + waveform cache metadata
- GET /api/v1/assets/{asset_id}/pcm?start_frame=&frame_count= — bounded raw
  PCM (contract §11.4): interleaved f32le body, metadata in headers, one
  response capped at 8 MiB, complete frames only, clipped at EOF, zero
  frames + EOF at exactly the end, starts beyond the end rejected
- GET /api/v1/assets/{asset_id}/peaks/manifest — waveform levels and
  progressive tile availability (the on-disk manifest is the source of
  truth while a WAVEFORM job runs)
- GET /api/v1/assets/{asset_id}/peaks?level=&tile= — one binary peak tile

Every response is tied to the single asset row resolved at request start
(spec §11.4 rule 7): bytes and metadata headers never mix
representations.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

from basseparate.api.errors import (
    AssetNotFoundError,
    NonPcmAssetError,
    NoWaveformCacheError,
    PcmRangeError,
    PeakRangeError,
    TileNotReadyError,
)
from basseparate.domain.asset import AssetRecord, AssetRole
from basseparate.domain.waveform import (
    TILE_BUCKETS,
    WaveformLevelSummary,
    WaveformManifest,
    validate_manifest,
)
from basseparate.storage import ProjectRepository, StoragePaths, WaveformCacheRepository

router = APIRouter(prefix="/api/v1")

#: Maximum raw PCM bytes in one response (spec §11.4 rule 2).
PCM_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: One streamed chunk of a PCM response.
_PCM_CHUNK_SIZE = 1 << 20

#: Asset roles whose on-disk file is raw interleaved f32le PCM.
_PCM_ROLES = frozenset({AssetRole.SOURCE_PCM, AssetRole.DERIVED_PCM})


class WaveformCacheInfo(BaseModel):
    """Waveform cache metadata for an asset (null when no cache exists)."""

    cache_version: int
    source_hash: str
    sample_rate: int
    frame_count: int
    channel_count: int
    levels: list[WaveformLevelSummary]
    #: Progressive tile availability; empty when only the DB row is known.
    available_tiles: dict[str, list[list[int]]]
    final: bool


class AssetMetadataResponse(BaseModel):
    asset_id: uuid.UUID
    role: str
    content_hash: str
    byte_count: int
    sample_rate: int | None
    frame_count: int | None
    channel_count: int | None
    waveform: WaveformCacheInfo | None


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _waveform_caches(request: Request) -> WaveformCacheRepository:
    return cast(WaveformCacheRepository, request.app.state.waveform_cache_repository)


def _get_asset(request: Request, asset_id: uuid.UUID) -> AssetRecord:
    asset = _projects(request).get_asset(asset_id)
    if asset is None:
        raise AssetNotFoundError(str(asset_id))
    return asset


def _manifest_path(paths: StoragePaths, asset: AssetRecord) -> str:
    return f"cache/waveforms/{asset.content_hash}/manifest.json"


def _load_manifest(paths: StoragePaths, asset: AssetRecord) -> WaveformManifest | None:
    """Read and validate the on-disk manifest; ``None`` when absent or invalid."""
    path = paths.resolve_asset_path(_manifest_path(paths, asset))
    if not path.is_file():
        return None
    try:
        manifest = WaveformManifest.model_validate_json(path.read_bytes())
        validate_manifest(manifest, source_hash=asset.content_hash)
    except (ValueError, OSError):
        return None
    return manifest


@router.get("/assets/{asset_id}/metadata", response_model=AssetMetadataResponse)
async def get_asset_metadata(asset_id: uuid.UUID, request: Request) -> AssetMetadataResponse:
    asset = _get_asset(request, asset_id)
    audio = asset.audio
    manifest = _load_manifest(_paths(request), asset)
    if manifest is not None:
        waveform = WaveformCacheInfo(
            cache_version=manifest.cache_version,
            source_hash=manifest.source_hash,
            sample_rate=manifest.sample_rate,
            frame_count=manifest.frame_count,
            channel_count=manifest.channel_count,
            levels=manifest.levels,
            available_tiles=manifest.available_tiles,
            final=manifest.final,
        )
    else:
        record = _waveform_caches(request).get_for_asset(asset.id)
        if record is None:
            waveform = None
        else:
            waveform = WaveformCacheInfo(
                cache_version=record.cache_version,
                source_hash=record.source_hash,
                sample_rate=record.sample_rate,
                frame_count=record.frame_count,
                channel_count=record.channel_count,
                levels=list(record.levels),
                available_tiles={},
                final=True,
            )
    return AssetMetadataResponse(
        asset_id=asset.id,
        role=asset.role.value,
        content_hash=asset.content_hash,
        byte_count=asset.byte_count,
        sample_rate=audio.sample_rate if audio is not None else None,
        frame_count=audio.frame_count if audio is not None else None,
        channel_count=audio.channel_count if audio is not None else None,
        waveform=waveform,
    )


@router.get("/assets/{asset_id}/pcm")
async def get_asset_pcm(
    asset_id: uuid.UUID,
    start_frame: Annotated[int, Query(ge=0)],
    frame_count: Annotated[int, Query(ge=1)],
    request: Request,
) -> StreamingResponse:
    """Bounded raw PCM window (spec §11.4).

    The asset is resolved once; the body, the content hash, and every
    metadata header derive from that single resolution.
    """
    asset = _get_asset(request, asset_id)
    if asset.role not in _PCM_ROLES or asset.audio is None:
        raise NonPcmAssetError(str(asset_id))
    audio = asset.audio
    total_frames = audio.frame_count
    if start_frame > total_frames:
        raise PcmRangeError(start_frame, total_frames)

    channels = audio.channel_count
    max_by_bytes = PCM_MAX_RESPONSE_BYTES // (4 * channels)
    frames = min(frame_count, max_by_bytes, total_frames - start_frame)
    byte_count = frames * 4 * channels
    path = _paths(request).resolve_asset_path(asset.relative_path)
    if not path.is_file():
        raise AssetNotFoundError(str(asset_id), missing_file=True)

    def iter_chunks() -> Iterator[bytes]:
        with path.open("rb") as handle:
            handle.seek(start_frame * 4 * channels)
            remaining = byte_count
            while remaining > 0:
                chunk = handle.read(min(_PCM_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(byte_count),
        "X-Asset-Id": str(asset.id),
        "X-Content-Hash": asset.content_hash,
        "X-Sample-Rate": str(audio.sample_rate),
        "X-Channel-Count": str(channels),
        "X-Start-Frame": str(start_frame),
        "X-Frame-Count": str(frames),
        "X-EOF": "true" if start_frame + frames >= total_frames else "false",
    }
    return StreamingResponse(iter_chunks(), headers=headers)


@router.get("/assets/{asset_id}/peaks/manifest", response_model=WaveformManifest)
async def get_peaks_manifest(asset_id: uuid.UUID, request: Request) -> WaveformManifest:
    """Waveform levels and progressive tile availability (M1.8 manifest)."""
    asset = _get_asset(request, asset_id)
    manifest = _load_manifest(_paths(request), asset)
    if manifest is None:
        raise NoWaveformCacheError(str(asset_id))
    return manifest


@router.get("/assets/{asset_id}/peaks")
async def get_peak_tile(
    asset_id: uuid.UUID,
    level: Annotated[int, Query(ge=0)],
    tile: Annotated[int, Query(ge=0)],
    request: Request,
) -> Response:
    """One binary peak tile (f32le per-channel min/max buckets)."""
    asset = _get_asset(request, asset_id)
    manifest = _load_manifest(_paths(request), asset)
    if manifest is None:
        raise NoWaveformCacheError(str(asset_id))
    level_count = len(manifest.levels)
    if level >= level_count:
        raise PeakRangeError(level, tile, level_count, 0)
    level_summary = manifest.levels[level]
    if tile >= level_summary.tile_count:
        raise PeakRangeError(level, tile, level_count, level_summary.tile_count)
    ranges = manifest.available_tiles.get(str(level), [])
    if not any(start <= tile <= end for start, end in ranges):
        raise TileNotReadyError(level, tile)
    tile_path = _paths(request).resolve_asset_path(
        f"cache/waveforms/{asset.content_hash}/level_{level}/tile_{tile:06d}.bin"
    )
    if not tile_path.is_file():
        raise TileNotReadyError(level, tile)
    tile_buckets = (
        level_summary.final_tile_buckets
        if tile == level_summary.tile_count - 1
        else TILE_BUCKETS
    )
    return Response(
        content=tile_path.read_bytes(),
        media_type="application/octet-stream",
        headers={
            "X-Level": str(level),
            "X-Tile": str(tile),
            "X-Bucket-Frames": str(level_summary.bucket_frame_count),
            "X-Tile-Buckets": str(tile_buckets),
        },
    )
