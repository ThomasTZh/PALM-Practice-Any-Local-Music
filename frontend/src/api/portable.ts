/**
 * Portable project save API module (M2.15, spec §17).
 *
 * Saves the working project as a self-contained `.basseparate` archive
 * (synchronous save, one 201 response), lists the project's saved
 * artifacts, and downloads one archive (authenticated fetch → Blob →
 * synthetic `<a download>`).
 */

import { createApiClient, errorMessage } from './client'
import type { components } from './schema'
import { getSessionToken } from '../auth'

const client = createApiClient()

/** One published portable save with its download endpoint (spec §17.5). */
export interface PortableSave {
  artifactId: string
  projectId: string
  savedRevision: number
  sha256: string
  byteSize: number
  downloadFilename: string
  downloadUrl: string
  createdAt: string
}

/** A request-level portable save failure carrying the server's code. */
export class PortableSaveRequestError extends Error {
  readonly code: string
  readonly statusCode: number
  /** Missing essential asset files (code SAVE_ASSET_MISSING). */
  readonly missing: string[]

  constructor(code: string, message: string, statusCode: number, missing: string[] = []) {
    super(message)
    this.name = 'PortableSaveRequestError'
    this.code = code
    this.statusCode = statusCode
    this.missing = missing
  }
}

function envelope(error: unknown): { code?: string; details?: { missing?: string[] } } | undefined {
  if (error && typeof error === 'object') {
    const e = error as { error?: { code?: string; details?: { missing?: string[] } } }
    if (e.error?.code) return e.error
  }
  return undefined
}

function mapSave(s: components['schemas']['PortableSaveResponse']): PortableSave {
  return {
    artifactId: s.artifact_id,
    projectId: s.project_id,
    savedRevision: s.saved_revision,
    sha256: s.sha256,
    byteSize: s.byte_size,
    downloadFilename: s.download_filename,
    downloadUrl: s.download_url,
    createdAt: s.created_at,
  }
}

/**
 * Save the working project as a portable archive (spec §17.1). Each call
 * sends a fresh `Idempotency-Key`, so a repeated click while the first
 * request is in flight returns the same artifact instead of a duplicate
 * save.
 */
export async function savePortableProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<PortableSave> {
  const res = await client.POST('/api/v1/projects/{project_id}/portable-saves', {
    params: { path: { project_id: projectId } },
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    signal,
  })
  if (!res.response.ok || !res.data) {
    const info = envelope(res.error)
    throw new PortableSaveRequestError(
      info?.code ?? 'PORTABLE_SAVE_REQUEST',
      errorMessage(res.error, `Portable save failed (${res.response.status})`),
      res.response.status,
      info?.details?.missing ?? [],
    )
  }
  return mapSave(res.data)
}

/** The project's portable saves, newest first (spec §17.5). */
export async function listPortableSaves(
  projectId: string,
  signal?: AbortSignal,
): Promise<PortableSave[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/portable-saves', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new PortableSaveRequestError(
      envelope(res.error)?.code ?? 'PORTABLE_SAVE_LIST',
      errorMessage(res.error, `Portable save list failed (${res.response.status})`),
      res.response.status,
    )
  }
  return (res.data.saves ?? []).map(mapSave)
}

/**
 * Download one published archive (spec §17.5): authenticated fetch →
 * Blob → synthetic `<a download>`. The browser picks the save location;
 * the app supplies the safe, deterministic filename.
 */
export async function downloadPortableSave(
  save: PortableSave,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getSessionToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(save.downloadUrl, { headers, signal })
  if (!res.ok) {
    throw new Error(`Portable save download failed (${res.status})`)
  }
  const blob = await res.blob()
  triggerBrowserDownload(blob, save.downloadFilename)
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
