/**
 * PCM fetch worker (M1.13, spec §15).
 *
 * The single producer for both playback data paths. It fetches bounded
 * byte ranges of the current playback asset and either:
 * - transfer path: deinterleaves into per-channel Float32Arrays and
 *   posts them *transferred* to the main thread (which relays them to
 *   the worklet), or
 * - shared path: copies the raw interleaved bytes into the shared ring
 *   (SAB) and advances the atomic writer index.
 *
 * Bundled by Vite via `new Worker(new URL('./fetch-worker.ts', ...))`
 * (same pattern as `waveform/worker-script.ts`). When `Worker` is
 * unavailable (jsdom in tests), the transport falls back to running the
 * same `pcm-fetch.ts` helpers on the main thread.
 *
 * Generation discipline (both paths, spec §15.1.4/§15.2.6): the worker
 * only produces data for its current generation; a `generation` or
 * `flush-ack` message moves it to a new one, and any in-flight or
 * completed fetch of an older generation is dropped. On the shared path
 * the writer index is reset only in `flush-ack` (spec §15.1.6), which
 * the transport sends after the worklet acknowledged the flush.
 */

import {
  acknowledgeSharedFlush,
  deinterleaveChannels,
  fetchPcmRange,
  viewSharedRing,
  writeSharedRing,
  type SharedRing,
} from './pcm-fetch'

type Job =
  | {
      id: number
      kind: 'fetch'
      assetId: string
      start: number
      end: number
      generation: number
      channelCount: number
    }
  | { kind: 'shared-init'; sab: SharedArrayBuffer; channelCount: number }
  | { kind: 'generation'; generation: number }
  | { kind: 'flush-ack'; generation: number; baseFrame: number }
  | { kind: 'stop' }

let ring: SharedRing | null = null
/** Current generation; -1 means "no valid generation yet". */
let currentGen = -1
let inflight: AbortController | null = null

/**
 * Worker-scope `postMessage` with a transfer list. The DOM lib types
 * `self` as `Window`, whose `postMessage` has no transferable parameter;
 * the dedicated-worker signature is what runs at runtime.
 */
const scope = self as unknown as {
  postMessage(message: unknown, transfer?: Transferable[]): void
}

function post(msg: Record<string, unknown>, transfers?: Transferable[]): void {
  if (transfers && transfers.length > 0) scope.postMessage(msg, transfers)
  else scope.postMessage(msg)
}

async function handle(job: Job): Promise<void> {
  try {
    if (job.kind === 'shared-init') {
      // View the transferred SAB; never allocate a second one.
      ring = viewSharedRing(job.sab, job.channelCount)
      post({ kind: 'ready' })
      return
    }
    if (job.kind === 'generation') {
      currentGen = job.generation
      inflight?.abort()
      inflight = null
      return
    }
    if (job.kind === 'flush-ack') {
      if (!ring) return
      currentGen = job.generation
      acknowledgeSharedFlush(ring, job.generation, job.baseFrame)
      post({ kind: 'flushed' })
      return
    }
    if (job.kind === 'stop') {
      inflight?.abort()
      inflight = null
      return
    }
    // kind === 'fetch'
    if (job.generation !== currentGen) {
      post({ id: job.id, kind: 'stale', ok: false })
      return
    }
    const controller = new AbortController()
    inflight = controller
    const { bytes } = await fetchPcmRange(job.assetId, job.start, job.end, controller.signal)
    if (inflight === controller) inflight = null
    if (job.generation !== currentGen) {
      // A generation change (seek) landed while this fetch was in flight.
      post({ id: job.id, kind: 'stale', ok: false })
      return
    }
    const startFrame = Math.floor(job.start / (4 * job.channelCount))
    if (ring) {
      // `frames` may be 0 when the ring is full: a dropped write is
      // normal flow control (the transport parks and retries), not an
      // error.
      const frames = writeSharedRing(ring, bytes)
      post({ id: job.id, kind: 'shared-chunk', ok: true, startFrame, frames })
    } else {
      const channels = deinterleaveChannels(bytes, job.channelCount)
      post(
        {
          id: job.id,
          kind: 'chunk',
          ok: true,
          startFrame,
          frames: channels.length > 0 ? channels[0].length : 0,
          channels,
        },
        channels.map((c) => c.buffer as ArrayBuffer),
      )
    }
  } catch (err) {
    const id = job && typeof job === 'object' && 'id' in job ? job.id : -1
    post({
      id,
      kind: 'error',
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    })
  }
}

self.onmessage = (event: MessageEvent<Job>) => {
  void handle(event.data)
}
