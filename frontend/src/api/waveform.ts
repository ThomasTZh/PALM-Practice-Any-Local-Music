/**
 * Waveform API module (M1.10).
 *
 * Fetchers for the M1.9 asset media routes the waveform editor consumes:
 * asset metadata (with waveform-cache summary), the peaks manifest,
 * individual peak tiles, and bounded raw-PCM windows.
 *
 * JSON routes use the shared openapi-fetch client. Binary routes (peak
 * tiles, PCM) use plain `fetch` because openapi-fetch does not handle
 * binary responses; the Authorization header mirrors the shared client
 * (same convention as `fetchAssetBytes` in `playback.ts`).
 */

import { createApiClient, errorMessage } from './client'
import { getSessionToken } from '../auth'
import type { components } from './schema'

const client = createApiClient()

export type WaveformManifest = components['schemas']['WaveformManifest']
export type WaveformCacheInfo = components['schemas']['WaveformCacheInfo']
export type JobType = components['schemas']['JobType']

export interface ProjectJob {
  id: string
  jobType: JobType
  state: string
  progressFraction: number | null
}

export interface AssetMetadata {
  assetId: string
  role: string
  contentHash: string
  sampleRate: number | null
  channelCount: number | null
  frameCount: number | null
  byteCount: number
  /** Waveform-cache summary; null when no cache exists for the asset. */
  waveform: WaveformCacheInfo | null
}

export interface PeakTileBytes {
  bytes: ArrayBuffer
  level: number
  tile: number
  /** Sample frames covered by one bucket at this level. */
  bucketFrameCount: number
  /** Buckets in this tile (the final tile may be partial). */
  tileBuckets: number
}

export interface PcmWindow {
  bytes: ArrayBuffer
  startFrame: number
  frameCount: number
  /** True when the window reaches the end of the asset. */
  eof: boolean
  sampleRate: number
  channelCount: number
  contentHash: string
}

/** 404 `NO_WAVEFORM_CACHE`: no waveform cache exists for the asset. */
export class NoWaveformCacheError extends Error {
  constructor(assetId: string) {
    super(`No waveform cache for asset ${assetId}`)
    this.name = 'NoWaveformCacheError'
  }
}

/** 404 `TILE_NOT_READY`: the tile is still being built; retry later. */
export class TileNotReadyError extends Error {
  readonly level: number
  readonly tile: number

  constructor(level: number, tile: number) {
    super(`Peak tile ${tile} at level ${level} is not ready`)
    this.name = 'TileNotReadyError'
    this.level = level
    this.tile = tile
  }
}

/** 422 `PEAK_RANGE_OUT_OF_BOUNDS` / `PCM_RANGE_OUT_OF_BOUNDS`. */
export class RangeOutOfBoundsError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'RangeOutOfBoundsError'
    this.code = code
  }
}

/** Pull the standard `error.code` out of a plain-fetch error body. */
async function errorCodeOf(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { error?: { code?: string } }
    return body.error?.code ?? null
  } catch {
    return null
  }
}

/** Pull the standard `error.message` out of a plain-fetch error body. */
async function errorMessageOf(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } }
    return body.error?.message ?? fallback
  } catch {
    return fallback
  }
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const token = getSessionToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

export async function getAssetMetadata(
  assetId: string,
  signal?: AbortSignal,
): Promise<AssetMetadata> {
  const res = await client.GET('/api/v1/assets/{asset_id}/metadata', {
    params: { path: { asset_id: assetId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Asset metadata failed (${res.response.status})`))
  }
  return {
    assetId: res.data.asset_id,
    role: res.data.role,
    contentHash: res.data.content_hash,
    sampleRate: res.data.sample_rate,
    channelCount: res.data.channel_count,
    frameCount: res.data.frame_count,
    byteCount: res.data.byte_count,
    waveform: res.data.waveform,
  }
}

/**
 * List the project's media jobs. Used to detect a live `waveform` job
 * (so the editor shows `pending` instead of `missing`).
 */
export async function listProjectJobs(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectJob[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/jobs', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) return []
  return res.data.jobs.map((j) => ({
    id: j.id,
    jobType: j.job_type,
    state: j.state,
    progressFraction: j.progress_fraction ?? null,
  }))
}

/**
 * Post a `waveform` build job for the project's latest completed import.
 * Returns the created job. Used by the `missing`-state rebuild button.
 */
export async function createWaveformJob(
  projectId: string,
  importId: string,
  signal?: AbortSignal,
): Promise<ProjectJob> {
  const res = await client.POST('/api/v1/projects/{project_id}/jobs', {
    params: { path: { project_id: projectId } },
    body: { import_id: importId, job_type: 'waveform' },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(
      errorMessage(res.error, `Waveform job creation failed (${res.response.status})`),
    )
  }
  const j = res.data
  return {
    id: j.id,
    jobType: j.job_type,
    state: j.state,
    progressFraction: j.progress_fraction ?? null,
  }
}

/**
 * Fetch the on-disk peaks manifest. Returns `null` on a 404 (no cache
 * yet); the caller's state machine maps that to pending/missing.
 */
export async function getPeaksManifest(
  assetId: string,
  signal?: AbortSignal,
): Promise<WaveformManifest | null> {
  const res = await client.GET('/api/v1/assets/{asset_id}/peaks/manifest', {
    params: { path: { asset_id: assetId } },
    signal,
  })
  if (res.response.status === 404) {
    return null
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Peaks manifest failed (${res.response.status})`))
  }
  return res.data
}

export async function getPeakTile(
  assetId: string,
  level: number,
  tile: number,
  signal?: AbortSignal,
): Promise<PeakTileBytes> {
  const url = `/api/v1/assets/${assetId}/peaks?level=${level}&tile=${tile}`
  // M2.12 §14.3: waveform tiles are background work (priority 'low').
  const res = await fetch(url, { headers: authHeaders(), signal, priority: 'low' })
  if (res.status === 404) {
    const code = await errorCodeOf(res)
    if (code === 'TILE_NOT_READY') throw new TileNotReadyError(level, tile)
    if (code === 'NO_WAVEFORM_CACHE') throw new NoWaveformCacheError(assetId)
    throw new Error(await errorMessageOf(res, `Peak tile failed (404)`))
  }
  if (res.status === 422) {
    const code = await errorCodeOf(res)
    if (code === 'PEAK_RANGE_OUT_OF_BOUNDS') {
      throw new RangeOutOfBoundsError(code, await errorMessageOf(res, 'Peak range out of bounds'))
    }
    throw new Error(await errorMessageOf(res, `Peak tile failed (422)`))
  }
  if (!res.ok) {
    throw new Error(await errorMessageOf(res, `Peak tile failed (${res.status})`))
  }
  return {
    bytes: await res.arrayBuffer(),
    level: Number(res.headers.get('X-Level') ?? level),
    tile: Number(res.headers.get('X-Tile') ?? tile),
    bucketFrameCount: Number(res.headers.get('X-Bucket-Frames') ?? 0),
    tileBuckets: Number(res.headers.get('X-Tile-Buckets') ?? 0),
  }
}

export async function getAssetPcm(
  assetId: string,
  startFrame: number,
  frameCount: number,
  signal?: AbortSignal,
): Promise<PcmWindow> {
  const url = `/api/v1/assets/${assetId}/pcm?start_frame=${startFrame}&frame_count=${frameCount}`
  // M2.12 §14.3: waveform PCM windows are background work (priority 'low').
  const res = await fetch(url, { headers: authHeaders(), signal, priority: 'low' })
  if (res.status === 422) {
    const code = await errorCodeOf(res)
    if (code === 'PCM_RANGE_OUT_OF_BOUNDS') {
      throw new RangeOutOfBoundsError(code, await errorMessageOf(res, 'PCM range out of bounds'))
    }
    throw new Error(await errorMessageOf(res, `PCM window failed (422)`))
  }
  if (!res.ok) {
    throw new Error(await errorMessageOf(res, `PCM window failed (${res.status})`))
  }
  return {
    bytes: await res.arrayBuffer(),
    startFrame: Number(res.headers.get('X-Start-Frame') ?? startFrame),
    frameCount: Number(res.headers.get('X-Frame-Count') ?? frameCount),
    eof: res.headers.get('X-EOF') === 'true',
    sampleRate: Number(res.headers.get('X-Sample-Rate') ?? 0),
    channelCount: Number(res.headers.get('X-Channel-Count') ?? 0),
    contentHash: res.headers.get('X-Content-Hash') ?? '',
  }
}
