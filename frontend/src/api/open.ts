/**
 * Portable project open API module (M2.16, spec §18.1).
 *
 * Streams one `.basseparate` archive to the backend over the bounded
 * chunk protocol (sequential offsets, per-chunk SHA-256, retries) and
 * then asks the server to validate and import it. The complete call is
 * synchronous server-side — pure file I/O and database work, no media
 * jobs — so the UI shows an "Opening…" phase while it runs.
 */

import { createApiClient } from './client'
import type { components } from './schema'
import { sha256Hex } from './uploader'

const client = createApiClient()

const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
const MAX_RETRIES = 3

export interface OpenSession {
  sessionId: string
  chunkSize: number
  maxProjectArchiveBytes: number
}

export interface OpenProgress {
  bytesUploaded: number
  totalBytes: number
}

export interface OpenedProject {
  projectId: string
  name: string
  status: string
  revision: number
}

/** A request-level open failure carrying the server's stable code. */
export class OpenRequestError extends Error {
  readonly code: string
  readonly statusCode: number
  readonly details: Record<string, unknown>

  constructor(
    code: string,
    message: string,
    statusCode: number,
    details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'OpenRequestError'
    this.code = code
    this.statusCode = statusCode
    this.details = details
  }
}

function envelope(
  error: unknown,
): { code?: string; message?: string; details?: Record<string, unknown> } | undefined {
  if (error && typeof error === 'object') {
    const e = error as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> }
    }
    if (e.error?.code) return e.error
  }
  return undefined
}

function failure(response: { status: number }, error: unknown, fallback: string): OpenRequestError {
  const info = envelope(error)
  return new OpenRequestError(
    info?.code ?? 'OPEN_REQUEST_FAILED',
    info?.message ?? `${fallback} (${response.status})`,
    response.status,
    info?.details ?? {},
  )
}

/** A short, user-facing explanation for one open failure. */
export function describeOpenError(error: unknown): string {
  if (!(error instanceof OpenRequestError)) {
    return error instanceof Error ? error.message : String(error)
  }
  const details = error.details
  switch (error.code) {
    case 'ARCHIVE_BAD_FILENAME':
      return 'Choose a .basseparate project file.'
    case 'ARCHIVE_SIZE_LIMIT':
      return 'This project archive is larger than the configured limit.'
    case 'ARCHIVE_NOT_ZIP':
      return 'This file is not a readable project archive.'
    case 'ARCHIVE_MEMBER_MISSING': {
      const missing = Array.isArray(details.missing) ? details.missing.join(', ') : ''
      return missing
        ? `The archive is incomplete: ${missing} is missing.`
        : 'The archive is incomplete; an essential file is missing.'
    }
    case 'ARCHIVE_MEMBER_CORRUPT': {
      const member = typeof details.member === 'string' ? details.member : ''
      return member
        ? `The archive is damaged: ${member} failed verification.`
        : 'The archive is damaged; a file failed verification.'
    }
    case 'ARCHIVE_SCHEMA_MISMATCH':
    case 'ARCHIVE_VERSION_UNSUPPORTED':
      return 'This archive was created by a different app version.'
    case 'ARCHIVE_DB_INVALID':
    case 'ARCHIVE_MANIFEST_INVALID':
      return 'This project archive is not valid.'
    case 'OPEN_NO_SPACE':
      return 'Not enough free disk space to open this project.'
    case 'OPEN_ID_CONFLICT':
      return 'This project is already in the library. Open it as a new working copy instead.'
    case 'OPEN_SESSION_INCOMPLETE':
      return 'The upload did not finish; retry the transfer.'
    case 'OPEN_SESSION_NOT_FOUND':
      return 'The upload session expired; choose the file again.'
    default:
      return error.message
  }
}

/** Create a transfer session for one archive (spec §18.1). */
export async function createOpenSession(
  filename: string,
  declaredByteCount: number,
  signal?: AbortSignal,
): Promise<OpenSession> {
  const res = await client.POST('/api/v1/projects/open', {
    body: { filename, declared_byte_count: declaredByteCount },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw failure(res.response, res.error, 'Create open session failed')
  }
  return {
    sessionId: res.data.open_session_id,
    chunkSize: res.data.chunk_size,
    maxProjectArchiveBytes: res.data.max_project_archive_bytes,
  }
}

/** Upload one chunk of the archive (same protocol as media imports). */
export async function uploadOpenChunk(
  sessionId: string,
  offset: number,
  chunk: Blob,
  chunkSha256: string,
  signal?: AbortSignal,
): Promise<{ offset: number; idempotentReplay: boolean }> {
  // The generated schema types this raw-binary body as `never`.
  const res = await client.PUT('/api/v1/projects/open/{session_id}/chunks', {
    params: { path: { session_id: sessionId }, query: { offset } },
    body: chunk as unknown as undefined,
    headers: {
      'X-Chunk-SHA256': chunkSha256,
      'Content-Type': 'application/octet-stream',
    },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw failure(res.response, res.error, 'Chunk upload failed')
  }
  return { offset: res.data.offset, idempotentReplay: res.data.idempotent_replay }
}

/** Validate and import the fully transferred archive (spec §18). */
export async function completeOpenSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<OpenedProject> {
  const res = await client.POST('/api/v1/projects/open/{session_id}/complete', {
    params: { path: { session_id: sessionId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw failure(res.response, res.error, 'Opening the project failed')
  }
  return {
    projectId: res.data.project_id,
    name: res.data.name,
    status: res.data.status,
    revision: res.data.revision,
  }
}

/** Remove a session's transfer files (idempotent). */
export async function cancelOpenSession(sessionId: string, signal?: AbortSignal): Promise<void> {
  await client.POST('/api/v1/projects/open/{session_id}/cancel', {
    params: { path: { session_id: sessionId } },
    signal,
  })
}

/** The session's transfer state (used by tests and recovery UIs). */
export async function getOpenSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<components['schemas']['OpenSessionStateResponse'] | null> {
  const res = await client.GET('/api/v1/projects/open/{session_id}', {
    params: { path: { session_id: sessionId } },
    signal,
  })
  return res.response.ok && res.data ? res.data : null
}

export interface UploadArchiveOptions {
  file: File
  chunkSize?: number
  signal?: AbortSignal
  onProgress?: (progress: OpenProgress) => void
  /** The server session id, reported once the session is created. */
  onSession?: (sessionId: string) => void
  /** Called once the transfer is done and the server-side open starts. */
  onOpening?: () => void
}

/**
 * Transfer and open one archive: create the session, stream the chunks
 * in order with per-chunk hashing and retries, then run the import.
 */
export async function uploadArchive(options: UploadArchiveOptions): Promise<OpenedProject> {
  const { file, signal, onProgress, onSession, onOpening } = options
  const chunkSize = options.chunkSize ?? DEFAULT_CHUNK_SIZE
  const session = await createOpenSession(file.name, file.size, signal)
  onSession?.(session.sessionId)
  const totalChunks = Math.ceil(file.size / chunkSize)
  let offset = 0

  for (let index = 0; index < totalChunks; index++) {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    offset = index * chunkSize
    const slice = file.slice(offset, Math.min(offset + chunkSize, file.size))
    const hash = await sha256Hex(await slice.arrayBuffer())

    let lastError: Error | null = null
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      if (signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }
      try {
        const ack = await uploadOpenChunk(session.sessionId, offset, slice, hash, signal)
        onProgress?.({ bytesUploaded: ack.offset, totalBytes: file.size })
        lastError = null
        break
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') throw err
        lastError = err instanceof Error ? err : new Error(String(err))
        if (attempt < MAX_RETRIES - 1) {
          await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)))
        }
      }
    }
    if (lastError) throw lastError
  }

  onOpening?.()
  return completeOpenSession(session.sessionId, signal)
}
