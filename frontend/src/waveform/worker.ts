/**
 * Decode worker wrapper (M1.10, spec §11.5).
 *
 * A thin wrapper that posts `{ kind: 'tile' | 'pcm' }` jobs to a worker
 * running the pure `decode.ts` functions, keeping large parses off the
 * render path. M1.10 (fit-to-song) decodes synchronously on the main
 * thread; M1.11's interactive zoom switches to this worker. When a
 * `Worker` is unavailable (e.g. jsdom in tests) every call falls back to
 * direct main-thread decode, so the API is safe everywhere.
 */

import {
  aggregatePcmToPixels,
  parsePeakTile,
  pcmSamples,
  type PcmPixels,
  type PeakTile,
} from './decode'

let worker: Worker | null = null

function getWorker(): Worker | null {
  if (typeof Worker === 'undefined') return null
  if (!worker) {
    worker = new Worker(new URL('./worker-script.ts', import.meta.url), { type: 'module' })
  }
  return worker
}

interface WorkerReply {
  id: number
  ok: boolean
  result?: unknown
  error?: string
}

function post<T>(job: Record<string, unknown>, fallback: () => T): Promise<T> {
  const w = getWorker()
  if (!w) return Promise.resolve(fallback())
  return new Promise<T>((resolve, reject) => {
    const onMessage = (event: MessageEvent<WorkerReply>) => {
      if (event.data.id !== job.id) return
      w.removeEventListener('message', onMessage)
      if (event.data.ok) resolve(event.data.result as T)
      else reject(new Error(event.data.error ?? 'decode failed'))
    }
    w.addEventListener('message', onMessage)
    w.postMessage(job)
  })
}

/** Decode one peak tile (per-channel min/max buckets). */
export function decodeTile(
  bytes: ArrayBuffer,
  channelCount: number,
  bucketCount: number,
): Promise<PeakTile> {
  return post({ kind: 'tile', id: nextId(), bytes, channelCount, bucketCount }, () =>
    parsePeakTile(bytes, channelCount, bucketCount),
  )
}

/** Aggregate PCM into per-pixel min/max (fpp >= 1). */
export function decodePcmPixels(
  bytes: ArrayBuffer,
  channelCount: number,
  startFrame: number,
  framesPerCssPixel: number,
): Promise<PcmPixels> {
  return post(
    { kind: 'pcm-pixels', id: nextId(), bytes, channelCount, startFrame, framesPerCssPixel },
    () => aggregatePcmToPixels(bytes, channelCount, startFrame, framesPerCssPixel),
  )
}

/** Deinterleave PCM into per-channel sample arrays (fpp < 1). */
export function decodePcmSamples(
  bytes: ArrayBuffer,
  channelCount: number,
): Promise<Float32Array[]> {
  return post({ kind: 'pcm-samples', id: nextId(), bytes, channelCount }, () =>
    pcmSamples(bytes, channelCount),
  )
}

let counter = 0
function nextId(): number {
  counter += 1
  return counter
}
