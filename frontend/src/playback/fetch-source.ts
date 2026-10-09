/**
 * Fetch source abstraction (M1.13, spec §15).
 *
 * Both playback data paths fetch through a `FetchSource`:
 * - `WorkerFetchSource` posts jobs to the `fetch-worker.ts` worker
 *   (production browsers).
 * - `DirectFetchSource` runs the identical `pcm-fetch.ts` logic on the
 *   main thread (jsdom has no `Worker`), so the full pipeline stays
 *   testable without a browser.
 *
 * Generation discipline (spec §15.1.4 / §15.2.6): each source only
 * produces data for its current generation; `setGeneration` /
 * `acknowledgeFlush` moves it to a new one, and in-flight work of an
 * older generation resolves as a `StaleGenerationError` (dropped by the
 * transport).
 */

import {
  acknowledgeSharedFlush,
  deinterleaveChannels,
  viewSharedRing,
  writeSharedRing,
  type SharedRing,
} from './pcm-fetch'

/** Thrown when a fetch completes after its generation was superseded. */
export class StaleGenerationError extends Error {
  constructor() {
    super('fetch generation is stale')
    this.name = 'StaleGenerationError'
  }
}

export interface PcmChunk {
  startFrame: number
  frames: number
  channels: Float32Array[]
}

export interface PcmWriteResult {
  startFrame: number
  frames: number
}

export interface FetchSource {
  /** Transfer path: fetch + deinterleave an inclusive byte range. */
  fetchChunk(assetId: string, start: number, end: number, generation: number): Promise<PcmChunk>
  /** Shared path: fetch + write into the ring. 0 frames = ring full (dropped). */
  writeChunk(
    assetId: string,
    start: number,
    end: number,
    generation: number,
  ): Promise<PcmWriteResult>
  /** Transfer path: adopt a new generation; older in-flight work is dropped. */
  setGeneration(generation: number): void
  /** Shared path: flush ack — sets the generation and the writer base frame. */
  acknowledgeFlush(generation: number, baseFrame: number): Promise<void>
  /** Shared path: hand the SAB to the writer side; resolves when ready. */
  attachShared(sab: SharedArrayBuffer, channelCount: number): Promise<void>
  /** Abort in-flight network work (seek/stop). */
  stop(): void
  dispose(): void
}

/** Structural type for `Worker`; lets tests inject a fake. */
export interface WorkerLike {
  postMessage(message: unknown, transfer?: Transferable[]): void
  onmessage: ((event: { data: unknown }) => void) | null
  terminate(): void
}

type PendingResult = {
  resolve: (value: PcmChunk | PcmWriteResult) => void
  reject: (reason: unknown) => void
}

/** Wraps the `fetch-worker.ts` worker behind the `FetchSource` interface. */
export class WorkerFetchSource implements FetchSource {
  private nextId = 0
  private pending = new Map<number, PendingResult>()
  private readyAck: { resolve: () => void; reject: (e: unknown) => void } | null = null
  private flushAck: { resolve: () => void; reject: (e: unknown) => void } | null = null

  constructor(
    private worker: WorkerLike,
    private channelCount: number,
  ) {
    worker.onmessage = (event) => this.onMessage(event.data)
  }

  /** Hand the SAB to the worker (shared path); resolves on its `ready`. */
  attachShared(sab: SharedArrayBuffer, channelCount: number): Promise<void> {
    return new Promise((resolve, reject) => {
      this.readyAck = { resolve, reject }
      this.worker.postMessage({ kind: 'shared-init', sab, channelCount }, [sab])
    })
  }

  setGeneration(generation: number): void {
    this.worker.postMessage({ kind: 'generation', generation })
  }

  acknowledgeFlush(generation: number, baseFrame: number): Promise<void> {
    return new Promise((resolve, reject) => {
      this.flushAck = { resolve, reject }
      this.worker.postMessage({ kind: 'flush-ack', generation, baseFrame })
    })
  }

  fetchChunk(assetId: string, start: number, end: number, generation: number): Promise<PcmChunk> {
    const id = ++this.nextId
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        resolve: (v) => resolve(v as PcmChunk),
        reject,
      })
      this.worker.postMessage({
        id,
        kind: 'fetch',
        assetId,
        start,
        end,
        generation,
        channelCount: this.channelCount,
      })
    })
  }

  writeChunk(
    assetId: string,
    start: number,
    end: number,
    generation: number,
  ): Promise<PcmWriteResult> {
    const id = ++this.nextId
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        resolve: (v) => resolve(v as PcmWriteResult),
        reject,
      })
      this.worker.postMessage({
        id,
        kind: 'fetch',
        assetId,
        start,
        end,
        generation,
        channelCount: this.channelCount,
      })
    })
  }

  private onMessage(data: unknown): void {
    const m = data as Record<string, unknown> | null
    if (!m || typeof m !== 'object') return
    if (m.kind === 'ready') {
      this.readyAck?.resolve()
      this.readyAck = null
      return
    }
    if (m.kind === 'flushed') {
      this.flushAck?.resolve()
      this.flushAck = null
      return
    }
    const id = m.id
    if (typeof id !== 'number') return
    const p = this.pending.get(id)
    if (!p) return
    this.pending.delete(id)
    if (m.ok === false) {
      const message =
        typeof m.error === 'string' && m.error.length > 0
          ? m.error
          : m.kind === 'stale'
            ? 'stale generation'
            : 'fetch failed'
      p.reject(new Error(message))
      return
    }
    p.resolve({
      startFrame: m.startFrame as number,
      frames: m.frames as number,
      ...(m.kind === 'chunk' ? { channels: m.channels as Float32Array[] } : {}),
    })
  }

  stop(): void {
    this.worker.postMessage({ kind: 'stop' })
  }

  dispose(): void {
    this.stop()
    this.worker.terminate()
    for (const p of this.pending.values()) p.reject(new Error('fetch source disposed'))
    this.pending.clear()
    if (this.readyAck) {
      const ack = this.readyAck
      this.readyAck = null
      ack.reject(new Error('fetch source disposed'))
    }
    if (this.flushAck) {
      const ack = this.flushAck
      this.flushAck = null
      ack.reject(new Error('fetch source disposed'))
    }
  }
}

/**
 * Main-thread fallback: identical fetch + deinterleave (or ring write)
 * logic without a worker. Used in jsdom and anywhere `Worker` is
 * unavailable.
 */
export class DirectFetchSource implements FetchSource {
  private gen = -1
  private ring: SharedRing | null = null

  constructor(
    private fetcher: (assetId: string, start: number, end: number) => Promise<ArrayBuffer>,
    private channelCount: number,
  ) {}

  attachShared(sab: SharedArrayBuffer, channelCount: number): Promise<void> {
    // View the transferred SAB; never allocate a second one.
    this.ring = viewSharedRing(sab, channelCount)
    return Promise.resolve()
  }

  setGeneration(generation: number): void {
    this.gen = generation
  }

  acknowledgeFlush(generation: number, baseFrame: number): Promise<void> {
    this.gen = generation
    if (this.ring) acknowledgeSharedFlush(this.ring, generation, baseFrame)
    return Promise.resolve()
  }

  fetchChunk(assetId: string, start: number, end: number, generation: number): Promise<PcmChunk> {
    if (generation !== this.gen) return Promise.reject(new StaleGenerationError())
    return this.fetcher(assetId, start, end).then((bytes) => {
      if (generation !== this.gen) throw new StaleGenerationError()
      const channels = deinterleaveChannels(bytes, this.channelCount)
      return {
        startFrame: Math.floor(start / (4 * this.channelCount)),
        frames: channels.length > 0 ? channels[0].length : 0,
        channels,
      }
    })
  }

  writeChunk(
    assetId: string,
    start: number,
    end: number,
    generation: number,
  ): Promise<PcmWriteResult> {
    if (generation !== this.gen) return Promise.reject(new StaleGenerationError())
    return this.fetcher(assetId, start, end).then((bytes) => {
      if (generation !== this.gen) throw new StaleGenerationError()
      const frames = this.ring ? writeSharedRing(this.ring, bytes) : 0
      return { startFrame: Math.floor(start / (4 * this.channelCount)), frames }
    })
  }

  stop(): void {}

  dispose(): void {
    this.ring = null
  }
}
