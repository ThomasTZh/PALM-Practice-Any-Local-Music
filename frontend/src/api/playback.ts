/**
 * Playback API module (M1.7).
 *
 * Source info, playback-target resolution (with on-demand conversion
 * jobs), monitoring-channel selection, and ranged raw-PCM byte fetches.
 *
 * Job creation and polling follow the same client + error-envelope
 * conventions as the uploader module.
 */

import { createApiClient, errorMessage } from './client'
import { fetchPcmRange } from '../playback/pcm-fetch'
import type { components } from './schema'

const client = createApiClient()

export type JobType = components['schemas']['JobType']

export interface MonitoringInfo {
  mode: string
  assetId: string
  leftChannel: number
  rightChannel: number
}

export interface SourceInfo {
  sampleRate: number
  durationFrames: number
  durationSeconds: number
  channelCount: number
  channelLayout: string | null
  channelLabels: string[]
  monitoring: MonitoringInfo | null
  playbackRates: number[]
}

export interface PlaybackTarget {
  assetId: string
  role: string
  sampleRate: number
  channelCount: number
  frameCount: number
  byteCount: number
  durationSeconds: number
}

export interface JobState {
  id: string
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelling' | 'cancelled' | 'interrupted'
  stage: string | null
  progressFraction: number | null
  errorCode: string | null
  error: string | null
}

/** Thrown when no playback representation exists for the requested rate. */
export class NoPlaybackRepresentationError extends Error {
  readonly rate: number

  constructor(rate: number) {
    super(`No playback representation at ${rate} Hz`)
    this.name = 'NoPlaybackRepresentationError'
    this.rate = rate
  }
}

/** Extract the standard error code from an openapi-fetch error payload. */
function errorCodeOf(error: unknown): string | null {
  if (error && typeof error === 'object' && 'error' in error) {
    const inner = (error as { error?: { code?: string } }).error
    if (inner?.code) return inner.code
  }
  return null
}

export async function getSourceInfo(projectId: string, signal?: AbortSignal): Promise<SourceInfo> {
  const res = await client.GET('/api/v1/projects/{project_id}/source-info', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Source info failed (${res.response.status})`))
  }
  return {
    sampleRate: res.data.sample_rate,
    durationFrames: res.data.duration_frames,
    durationSeconds: res.data.duration_seconds,
    channelCount: res.data.channel_count,
    channelLayout: res.data.channel_layout ?? null,
    channelLabels: res.data.channel_labels,
    monitoring: res.data.monitoring
      ? {
          mode: res.data.monitoring.mode,
          assetId: res.data.monitoring.asset_id,
          leftChannel: res.data.monitoring.left_channel,
          rightChannel: res.data.monitoring.right_channel,
        }
      : null,
    playbackRates: res.data.playback_rates,
  }
}

export async function resolvePlayback(
  projectId: string,
  rate: number,
  signal?: AbortSignal,
): Promise<PlaybackTarget> {
  const res = await client.GET('/api/v1/projects/{project_id}/playback', {
    params: { path: { project_id: projectId }, query: { rate } },
    signal,
  })
  if (res.response.status === 404 && errorCodeOf(res.error) === 'NO_PLAYBACK_REPRESENTATION') {
    throw new NoPlaybackRepresentationError(rate)
  }
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Playback resolution failed (${res.response.status})`))
  }
  return {
    assetId: res.data.asset_id,
    role: res.data.role,
    sampleRate: res.data.sample_rate,
    channelCount: res.data.channel_count,
    frameCount: res.data.frame_count,
    byteCount: res.data.byte_count,
    durationSeconds: res.data.duration_seconds,
  }
}

export async function createJob(
  projectId: string,
  importId: string,
  jobType: JobType,
  targetSampleRate?: number,
  signal?: AbortSignal,
): Promise<JobState> {
  const body: { import_id: string; job_type: JobType; target_sample_rate?: number } = {
    import_id: importId,
    job_type: jobType,
  }
  if (targetSampleRate !== undefined) {
    body.target_sample_rate = targetSampleRate
  }
  const res = await client.POST('/api/v1/projects/{project_id}/jobs', {
    params: { path: { project_id: projectId } },
    body,
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Job creation failed (${res.response.status})`))
  }
  return toJobState(res.data)
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<JobState> {
  const res = await client.GET('/api/v1/jobs/{job_id}', {
    params: { path: { job_id: jobId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Job lookup failed (${res.response.status})`))
  }
  return toJobState(res.data)
}

function toJobState(job: {
  id: string
  state: string
  stage?: string | null
  progress_fraction?: number | null
  error_code?: string | null
  error?: string | null
}): JobState {
  return {
    id: job.id,
    state: job.state as JobState['state'],
    stage: job.stage ?? null,
    progressFraction: job.progress_fraction ?? null,
    errorCode: job.error_code ?? null,
    error: job.error ?? null,
  }
}

export interface WaitForJobOptions {
  timeoutMs?: number
  pollMs?: number
  signal?: AbortSignal
  /** Called with the latest job state after each poll (M2.13). */
  onProgress?: (job: JobState) => void
}

/** Poll a job until it reaches a terminal state. Throws on failure/timeout. */
export async function waitForJob(jobId: string, opts: WaitForJobOptions = {}): Promise<JobState> {
  const timeoutMs = opts.timeoutMs ?? 120_000
  const pollMs = opts.pollMs ?? 500
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const job = await getJob(jobId, opts.signal)
    opts.onProgress?.(job)
    if (job.state === 'completed') return job
    if (job.state === 'failed' || job.state === 'cancelled' || job.state === 'interrupted') {
      const code = job.errorCode ?? job.state.toUpperCase()
      const detail = job.error ? `: ${job.error}` : ''
      throw new Error(`Job ${job.id} ${job.state} (${code}${detail})`)
    }
    if (Date.now() > deadline) {
      throw new Error(`Timed out after ${timeoutMs} ms waiting for job ${jobId}`)
    }
    await sleep(pollMs, opts.signal)
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}

/**
 * Resolve the asset to play at `rate`, creating and awaiting a
 * `playback_rate` conversion job when no representation exists yet.
 */
export async function ensurePlaybackTarget(
  projectId: string,
  importId: string | null,
  rate: number,
  signal?: AbortSignal,
): Promise<PlaybackTarget> {
  try {
    return await resolvePlayback(projectId, rate, signal)
  } catch (err) {
    if (!(err instanceof NoPlaybackRepresentationError)) throw err
  }
  if (!importId) {
    throw new Error('No completed import to derive a playback representation from')
  }
  const job = await createJob(projectId, importId, 'playback_rate', rate, signal)
  await waitForJob(job.id, { signal })
  return resolvePlayback(projectId, rate, signal)
}

export async function setMonitoringChannels(
  projectId: string,
  left: number,
  right: number,
  signal?: AbortSignal,
): Promise<void> {
  const res = await client.PUT('/api/v1/projects/{project_id}/monitoring-channels', {
    params: { path: { project_id: projectId } },
    body: { left, right },
    signal,
  })
  if (!res.response.ok) {
    throw new Error(errorMessage(res.error, `Monitoring selection failed (${res.response.status})`))
  }
}

export async function latestCompletedImportId(
  projectId: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const res = await client.GET('/api/v1/projects/{project_id}/imports', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) return null
  const done = res.data.imports.filter((i) => i.transfer_state === 'complete')
  return done.length > 0 ? done[done.length - 1].id : null
}

export interface AssetBytes {
  bytes: ArrayBuffer
  total: number
}

/**
 * Fetch raw PCM bytes, optionally for a single inclusive byte range.
 * Delegates to the shared `fetchPcmRange` helper (also used by the
 * fetch worker, M1.13). M2.12 §14.3: this is waveform work (editor
 * decode/preview), so it takes the `'low'` fetch-priority hint.
 */
export async function fetchAssetBytes(
  assetId: string,
  start?: number,
  end?: number,
  signal?: AbortSignal,
): Promise<AssetBytes> {
  return fetchPcmRange(assetId, start, end, signal, 'low')
}
