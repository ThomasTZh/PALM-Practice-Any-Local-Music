/**
 * Chunked file uploader (M1.2).
 *
 * Splits a File into 8 MiB chunks via File.slice(), uploads them
 * sequentially with SHA-256 hash verification, retries up to 3 times
 * per chunk, and supports cancellation via AbortController.
 */

import { createApiClient, errorMessage } from './client'

const client = createApiClient()

const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
const MAX_RETRIES = 3

export interface UploadProgress {
  bytesUploaded: number
  totalBytes: number
  chunkIndex: number
  totalChunks: number
}

export interface AudioStreamSummary {
  index: number
  codec: string
  sampleRate: number
  channelCount: number
  channelLayout: string | null
  language: string | null
  title: string | null
  isDefault: boolean
}

export interface UploadResult {
  importId: string
  sourceSha256: string
  selectedStreamIndex: number | null
  audioStreams: AudioStreamSummary[]
}

export type UploadState =
  | { kind: 'idle' }
  | { kind: 'uploading'; progress: UploadProgress }
  | { kind: 'completing' }
  | { kind: 'done'; result: UploadResult }
  | { kind: 'error'; message: string }
  | { kind: 'cancelled' }

export async function sha256Hex(data: ArrayBuffer | Uint8Array): Promise<string> {
  const buffer: ArrayBuffer = data instanceof Uint8Array ? (data.buffer as ArrayBuffer) : data
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function createImportSession(
  projectId: string,
  filename: string,
  declaredByteCount: number,
  signal?: AbortSignal,
): Promise<{ importId: string; chunkSize: number }> {
  const res = await client.POST('/api/v1/imports', {
    body: { project_id: projectId, filename, declared_byte_count: declaredByteCount },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Create import failed (${res.response.status})`))
  }
  return { importId: res.data.import_id, chunkSize: res.data.chunk_size }
}

export async function uploadChunk(
  importId: string,
  offset: number,
  chunk: Blob,
  chunkSha256: string,
  signal?: AbortSignal,
): Promise<{ offset: number; idempotentReplay: boolean }> {
  // The generated schema types requestBody as `never` for this raw-binary
  // endpoint. We cast the body to satisfy the type checker.
  const res = await client.PUT('/api/v1/imports/{import_id}/chunks', {
    params: { path: { import_id: importId }, query: { offset } },
    body: chunk as unknown as undefined,
    // openapi-fetch serializes object bodies with JSON.stringify by
    // default, which turns a Blob into "{}"; the chunk route needs the
    // raw binary body.
    bodySerializer: (value) => value as unknown as BodyInit,
    headers: { 'X-Chunk-SHA256': chunkSha256, 'Content-Type': 'application/octet-stream' },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Chunk upload failed (${res.response.status})`))
  }
  return { offset: res.data.offset, idempotentReplay: res.data.idempotent_replay }
}

export async function completeImport(
  importId: string,
  signal?: AbortSignal,
): Promise<UploadResult> {
  const res = await client.POST('/api/v1/imports/{import_id}/complete', {
    params: { path: { import_id: importId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    throw new Error(errorMessage(res.error, `Complete failed (${res.response.status})`))
  }
  const probe = res.data.probe_result
  return {
    importId: res.data.import_id,
    sourceSha256: res.data.source_sha256,
    selectedStreamIndex: res.data.selected_stream_index ?? null,
    audioStreams: (probe?.audio_streams ?? []).map((s) => ({
      index: s.index,
      codec: s.codec,
      sampleRate: s.sample_rate,
      channelCount: s.channel_count,
      channelLayout: s.channel_layout ?? null,
      language: s.language ?? null,
      title: s.title ?? null,
      isDefault: s.is_default,
    })),
  }
}

export async function selectStream(
  importId: string,
  streamIndex: number,
  signal?: AbortSignal,
): Promise<void> {
  const res = await client.POST('/api/v1/imports/{import_id}/select-stream', {
    params: { path: { import_id: importId } },
    body: { stream_index: streamIndex },
    signal,
  })
  if (!res.response.ok) {
    throw new Error(errorMessage(res.error, `Stream selection failed (${res.response.status})`))
  }
}

export async function cancelImport(importId: string, signal?: AbortSignal): Promise<void> {
  await client.POST('/api/v1/imports/{import_id}/cancel', {
    params: { path: { import_id: importId } },
    signal,
  })
}

export interface IncompleteImport {
  id: string
  filename: string
  declaredByteCount: number
  receivedByteCount: number
  transferState: string
}

export async function listProjectImports(
  projectId: string,
  signal?: AbortSignal,
): Promise<IncompleteImport[]> {
  const res = await client.GET('/api/v1/projects/{project_id}/imports', {
    params: { path: { project_id: projectId } },
    signal,
  })
  if (!res.response.ok || !res.data) {
    return []
  }
  return res.data.imports
    .filter((i) => i.transfer_state === 'created' || i.transfer_state === 'uploading')
    .map((i) => ({
      id: i.id,
      filename: i.filename,
      declaredByteCount: i.declared_byte_count,
      receivedByteCount: i.received_byte_count,
      transferState: i.transfer_state,
    }))
}

export interface UploadOptions {
  projectId: string
  file: File
  chunkSize?: number
  signal?: AbortSignal
  onProgress?: (state: UploadState) => void
  resumeOffset?: number
}

export async function uploadFile(opts: UploadOptions): Promise<UploadResult> {
  const { projectId, file, signal, onProgress, resumeOffset = 0 } = opts
  const chunkSize = opts.chunkSize ?? DEFAULT_CHUNK_SIZE

  const report = (state: UploadState) => onProgress?.(state)

  let importId: string | undefined
  let startOffset = resumeOffset

  if (startOffset > 0) {
    const existing = await listProjectImports(projectId, signal)
    const match = existing.find((i) => i.filename === file.name)
    if (match) {
      importId = match.id
      startOffset = match.receivedByteCount
    } else {
      throw new Error('Resume import not found on server')
    }
  }

  if (!importId) {
    const session = await createImportSession(projectId, file.name, file.size, signal)
    importId = session.importId
    startOffset = 0
  }

  const resolvedImportId = importId!

  const totalChunks = Math.ceil(file.size / chunkSize)

  for (let i = 0; i < totalChunks; i++) {
    if (signal?.aborted) {
      report({ kind: 'cancelled' })
      throw new DOMException('Aborted', 'AbortError')
    }

    const offset = i * chunkSize
    if (offset < startOffset) continue

    const end = Math.min(offset + chunkSize, file.size)
    const slice = file.slice(offset, end)
    const hash = await sha256Hex(await slice.arrayBuffer())

    let lastError: Error | null = null
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      if (signal?.aborted) {
        report({ kind: 'cancelled' })
        throw new DOMException('Aborted', 'AbortError')
      }
      try {
        const ack = await uploadChunk(resolvedImportId, offset, slice, hash, signal)
        report({
          kind: 'uploading',
          progress: {
            bytesUploaded: ack.offset,
            totalBytes: file.size,
            chunkIndex: i + 1,
            totalChunks,
          },
        })
        lastError = null
        break
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') throw err
        lastError = err instanceof Error ? err : new Error(String(err))
        if (attempt < MAX_RETRIES - 1) {
          await new Promise((r) => setTimeout(r, 500 * (attempt + 1)))
        }
      }
    }
    if (lastError) {
      report({ kind: 'error', message: lastError.message })
      throw lastError
    }
  }

  report({ kind: 'completing' })
  const result = await completeImport(resolvedImportId, signal)
  report({ kind: 'done', result })
  return result
}
