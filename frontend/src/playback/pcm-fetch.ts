/**
 * Shared PCM fetch + deinterleave helpers (M1.13, spec §15).
 *
 * One implementation is used by both the fetch worker
 * (`fetch-worker.ts`) and the main-thread fallback (jsdom has no
 * `Worker`), so the byte-fetch and deinterleave logic lives here
 * instead of being duplicated. The Authorization header mirrors the
 * shared client (`api/client.ts`): the token comes from
 * `sessionStorage`, which same-origin dedicated workers can read.
 */

import { getSessionToken } from '../auth'
import { deinterleaveF32le } from './pcm'

export interface PcmRange {
  bytes: ArrayBuffer
  total: number
}

/**
 * Fetch raw PCM bytes, optionally for a single inclusive byte range.
 * Uses plain `fetch` because openapi-fetch does not handle binary
 * responses. A 416 response means the range is outside the asset and
 * surfaces as a `RangeError`; other failures throw a plain `Error`.
 */
export async function fetchPcmRange(
  assetId: string,
  start?: number,
  end?: number,
  signal?: AbortSignal,
): Promise<PcmRange> {
  const headers: Record<string, string> = {}
  const token = getSessionToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (start !== undefined && end !== undefined) {
    headers.Range = `bytes=${start}-${end}`
  }
  const res = await fetch(`/api/v1/assets/${assetId}/bytes`, { headers, signal })
  if (res.status === 416) {
    throw new RangeError('The requested byte range is not satisfiable')
  }
  if (!res.ok) {
    throw new Error(`Asset bytes failed (${res.status})`)
  }
  const contentRange = res.headers.get('content-range')
  const total = contentRange
    ? Number(contentRange.split('/')[1])
    : Number(res.headers.get('content-length') ?? 0)
  return { bytes: await res.arrayBuffer(), total }
}

/**
 * Split interleaved f32le bytes into per-channel Float32Arrays
 * (one per channel, each `floor(frames)` samples long).
 */
export function deinterleaveChannels(bytes: ArrayBuffer, channelCount: number): Float32Array[] {
  return deinterleaveF32le(bytes, channelCount)
}

// ---------------------------------------------------------------------------
// Shared-memory ring (spec §15.1)
//
// One SharedArrayBuffer holds a 16-byte Int32 header
// `[generation, writerIdx, readerIdx, 0]` followed by an interleaved f32
// data region. The fetch worker is the sole writer (data + writer index);
// the worklet is the sole reader (reader index). Atomic index access gives
// the required ordering; no blocking waits are ever used.
// ---------------------------------------------------------------------------

export interface SharedRing {
  /** The underlying buffer (allocated by `createSharedRing` or transferred). */
  sab: SharedArrayBuffer
  header: Int32Array
  data: Uint8Array
  frameCapacity: number
  channelCount: number
}

/**
 * Allocate the shared ring. `byteLength` must be at least 16 (header) plus
 * the interleaved data region; the frame capacity is derived from the
 * remaining bytes.
 */
export function createSharedRing(byteLength: number, channelCount: number): SharedRing {
  if (!(byteLength >= 16)) throw new RangeError('Shared ring must be at least 16 bytes')
  const sab = new SharedArrayBuffer(byteLength)
  const header = new Int32Array(sab, 0, 4)
  const data = new Uint8Array(sab, 16)
  const frameCapacity = Math.floor(data.byteLength / (4 * channelCount))
  return { sab, header, data, frameCapacity, channelCount }
}

/**
 * View a ring over an existing SharedArrayBuffer (the receiving side of a
 * transfer): the layout is the 16-byte header plus interleaved data.
 */
export function viewSharedRing(sab: SharedArrayBuffer, channelCount: number): SharedRing {
  const header = new Int32Array(sab, 0, 4)
  const data = new Uint8Array(sab, 16)
  return {
    sab,
    header,
    data,
    frameCapacity: Math.floor(data.byteLength / (4 * channelCount)),
    channelCount,
  }
}

/**
 * Copy interleaved f32le bytes into the ring at the current writer
 * position (wrap-aware). Returns the number of frames written, or 0 when
 * the ring cannot hold them (the caller drops the chunk). Indices are
 * absolute stream frames and may be negative (M2.11 loop pre-roll), so
 * the slot modulo is normalized.
 */
export function writeSharedRing(ring: SharedRing, bytes: ArrayBuffer): number {
  const writer = Atomics.load(ring.header, 1)
  const reader = Atomics.load(ring.header, 2)
  const bytesPerFrame = 4 * ring.channelCount
  const frames = Math.floor(bytes.byteLength / bytesPerFrame)
  if (frames <= 0) return 0
  if (writer - reader + frames > ring.frameCapacity) return 0
  const src = new Uint8Array(bytes)
  for (let f = 0; f < frames; f++) {
    const slot = (((writer + f) % ring.frameCapacity) + ring.frameCapacity) % ring.frameCapacity
    const dest = slot * bytesPerFrame
    ring.data.set(src.subarray(f * bytesPerFrame, (f + 1) * bytesPerFrame), dest)
  }
  Atomics.store(ring.header, 1, writer + frames)
  return frames
}

/**
 * Worker-side flush acknowledgment (spec §15.1.6): store the new
 * generation and writer position. Only called after the worklet has
 * acknowledged the flush, and the worklet owns the reader index (it
 * stores its own on seek), so this touches only the writer-owned slots.
 */
export function acknowledgeSharedFlush(
  ring: SharedRing,
  generation: number,
  baseFrame: number,
): void {
  Atomics.store(ring.header, 0, generation)
  Atomics.store(ring.header, 1, baseFrame)
}
