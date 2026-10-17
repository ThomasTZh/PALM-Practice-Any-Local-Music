/**
 * Export API module (M2.13, spec §15).
 *
 * Creates WAV stem export jobs, lists the project's delivered export
 * artifacts, and downloads one artifact (authenticated fetch → Blob →
 * synthetic `<a download>`; the browser picks the save location).
 * Exports are raw: mixer, limiter, and speed state never affect the
 * delivered files (§15.4).
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'
import { getSessionToken } from '../auth'
import type { JobState } from './playback'

const client = createApiClient()

export type ExportFormat = components['schemas']['ExportFormat']
export type ExportNormalization = components['schemas']['ExportNormalization']

/** Export creation options (spec §15.1–15.2). */
export interface ExportOptions {
  /** Immutable result set to export; defaults to the active set. */
  resultSetId?: string | null
  /** Stem audio asset ids to export; defaults to every stem. */
  assetIds?: string[] | null
  /** Output encoding (wav24 by default). */
  format: ExportFormat
  /** Output sample rate; null keeps the source rate. */
  sampleRate?: 44100 | 48000 | null
  /** Linked peak normalization to −1 dBFS (off by default). */
  normalize: ExportNormalization
}

/** One delivered export file with its job state (spec §15.5). */
export interface ExportArtifact {
  artifactId: string
  jobId: string
  jobState: string
  resultSetId: string
  stemId: string
  assetId: string
  role: string
  format: ExportFormat
  sampleRate: number
  channelCount: number
  frameCount: number
  normalized: boolean
  gainDb: number | null
  dither: string | null
  sha256: string
  byteSize: number
  downloadFilename: string
  downloadUrl: string
  createdAt: string
}

/** A request-level export failure carrying the server's error code. */
export class ExportRequestError extends Error {
  readonly code: string
  readonly statusCode: number

  constructor(code: string, message: string, statusCode: number) {
    super(message)
    this.name = 'ExportRequestError'
    this.code = code
    this.statusCode = statusCode
  }
}

function envelopeCode(error: unknown): string | undefined {
  if (error && typeof error === 'object') {
    const e = error as { error?: { code?: string } }
    if (e.error?.code) return e.error.code
  }
  return undefined
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

/**
 * Create an export job (spec §15.3.1–3). Each call sends a fresh
 * `Idempotency-Key`, so a repeated click while the first request is in
 * flight returns the same job instead of a duplicate.
 */
export async function createExport(
  projectId: string,
  options: ExportOptions,
  signal?: AbortSignal,
): Promise<JobState> {
  const res = await client.POST('/api/v1/projects/{project_id}/exports', {
    params: { path: { project_id: projectId } },
    body: {
      result_set_id: options.resultSetId ?? null,
      asset_ids: options.assetIds ?? null,
      format: options.format,
      sample_rate: options.sampleRate ?? null,
      normalize: options.normalize,
    },
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new ExportRequestError(
      envelopeCode(res.error) ?? 'EXPORT_REQUEST',
      errorMessage(res.error, `Export creation failed (${res.response.status})`),
      res.response.status,
    )
  }
  return toJobState(res.data)
}

/** The project's delivered export artifacts, newest first (spec §15.5). */
export async function listExports(
  projectId: string,
  signal?: AbortSignal,
): Promise<ExportArtifact[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/exports', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new ExportRequestError(
      envelopeCode(res.error) ?? 'EXPORT_LIST',
      errorMessage(res.error, `Export list failed (${res.response.status})`),
      res.response.status,
    )
  }
  return (res.data.artifacts ?? []).map(mapArtifact)
}

function mapArtifact(a: components['schemas']['ExportArtifactResponse']): ExportArtifact {
  return {
    artifactId: a.artifact_id,
    jobId: a.job_id,
    jobState: a.job_state,
    resultSetId: a.result_set_id,
    stemId: a.stem_id,
    assetId: a.asset_id,
    role: a.role,
    format: a.format,
    sampleRate: a.sample_rate,
    channelCount: a.channel_count,
    frameCount: a.frame_count,
    normalized: a.normalized,
    gainDb: a.gain_db ?? null,
    dither: a.dither ?? null,
    sha256: a.sha256,
    byteSize: a.byte_size,
    downloadFilename: a.download_filename,
    downloadUrl: a.download_url,
    createdAt: a.created_at,
  }
}

/**
 * Download one artifact (spec §15.6): authenticated fetch → Blob →
 * synthetic `<a download>`. The browser picks the save location; the
 * app only supplies the safe, deterministic filename.
 */
export async function downloadExport(
  artifact: ExportArtifact,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getSessionToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(artifact.downloadUrl, { headers, signal })
  if (!res.ok) {
    throw new Error(`Export download failed (${res.status})`)
  }
  const blob = await res.blob()
  triggerBrowserDownload(blob, artifact.downloadFilename)
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
