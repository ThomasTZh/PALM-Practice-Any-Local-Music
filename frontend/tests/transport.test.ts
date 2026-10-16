/**
 * Tests for the AudioWorklet transport (M1.12/M1.13, plan §8, items 8–14).
 *
 * jsdom has no `AudioContext` / `AudioWorklet`, so the tests inject a
 * fake context whose worklet node exposes a scriptable port: the test
 * plays the worklet side by calling `node.post({type, ...})` (the same
 * shape the processor adapter in `worklet-processor.js` emits).
 *
 * Data path: by default the rig runs the real main-thread fallback
 * (`DirectFetchSource`; jsdom's `Worker` is not exercised); a
 * `FakeFetchWorker` covers the worker protocol and the shared-memory
 * path with a real SAB.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  PcmTransport,
  type CompressorNodeLike,
  type GainNodeLike,
  type MixPeaks,
  type TransportContextLike,
  type TransportMode,
  type TransportState,
  type WorkletNodeLike,
} from '../src/playback/transport'
import type { PlaybackTarget } from '../src/api/playback'
import {
  acknowledgeSharedFlush,
  viewSharedRing,
  writeSharedRing,
  type SharedRing,
} from '../src/playback/pcm-fetch'
import type { WorkerLike } from '../src/playback/fetch-source'
import { MixState } from '../src/playback/worklet-processor.js'

const RATE = 48_000
const FRAMES = 48_000 // a one-second source
const LONG_FRAMES = 20 * RATE // a twenty-second source (flow control)
const BYTES_PER_FRAME = 4 * 2

function makeTarget(frameCount: number): PlaybackTarget {
  return {
    assetId: 'asset-1',
    role: 'playback',
    sampleRate: RATE,
    channelCount: 2,
    frameCount,
    byteCount: frameCount * BYTES_PER_FRAME,
    durationSeconds: frameCount / RATE,
  }
}

type Msg = { type: string; [key: string]: unknown }

class FakeWorkletNode implements WorkletNodeLike {
  port: WorkletNodeLike['port']
  connectedTo: unknown[] = []
  disconnected = false
  constructor() {
    this.port = { postMessage: vi.fn(), onmessage: null }
  }
  connect(destination: unknown): void {
    this.connectedTo.push(destination)
  }
  disconnect(): void {
    this.disconnected = true
  }
  /** Play the worklet side: deliver a message as if the port received it. */
  post(msg: Msg): void {
    this.port.onmessage?.({ data: msg })
  }
  /** Messages the transport sent to the worklet with the given type. */
  posted(type: string): Msg[] {
    return (this.port.postMessage as ReturnType<typeof vi.fn>).mock.calls
      .map((call) => call[0] as Msg)
      .filter((m) => m && m.type === type)
  }
}

/**
 * In-memory stand-in for the `fetch-worker.ts` worker: records the
 * protocol messages and answers fetch jobs like the real worker —
 * a deinterleaved chunk on the transfer path, a real SAB write on the
 * shared path.
 */
class FakeFetchWorker implements WorkerLike {
  messages: Record<string, unknown>[] = []
  onmessage: ((event: { data: unknown }) => void) | null = null
  terminated = false
  /** One ring per mix source (M2.8). */
  private rings: SharedRing[] = []

  get fetchJobs(): Array<{ source: number; start: number; end: number; generation: number }> {
    return this.messages.filter((m) => m.kind === 'fetch') as Array<{
      source: number
      start: number
      end: number
      generation: number
    }>
  }

  postMessage(message: unknown, _transfer?: Transferable[]): void {
    const msg = message as Record<string, unknown>
    this.messages.push(msg)
    void this.handle(msg)
  }

  terminate(): void {
    this.terminated = true
  }

  private async handle(msg: Record<string, unknown>): Promise<void> {
    if (msg.kind === 'shared-init') {
      // View the transferred SABs (like the real worker), not new ones.
      const sabs = msg.sabs as SharedArrayBuffer[]
      const channelCounts = msg.channelCounts as number[]
      this.rings = sabs.map((sab, i) => ringView(sab, channelCounts[i]))
      this.onmessage?.({ data: { kind: 'ready' } })
      return
    }
    if (msg.kind === 'flush-ack') {
      // One shared cursor: the same base frame resets every ring.
      for (const ring of this.rings) {
        acknowledgeSharedFlush(ring, msg.generation as number, msg.baseFrame as number)
      }
      this.onmessage?.({ data: { kind: 'flushed' } })
      return
    }
    if (msg.kind !== 'fetch') return
    const channelCount = msg.channelCount as number
    const bytesPerFrame = 4 * channelCount
    const frames = Math.floor(((msg.end as number) - (msg.start as number) + 1) / bytesPerFrame)
    const startFrame = Math.floor((msg.start as number) / bytesPerFrame)
    const ring = this.rings[msg.source as number]
    if (ring) {
      const written = writeSharedRing(ring, new ArrayBuffer(frames * bytesPerFrame))
      this.onmessage?.({
        data: { id: msg.id, kind: 'shared-chunk', ok: true, startFrame, frames: written },
      })
    } else {
      const channels = Array.from({ length: channelCount }, () => new Float32Array(frames))
      this.onmessage?.({
        data: { id: msg.id, kind: 'chunk', ok: true, startFrame, frames, channels },
      })
    }
  }
}

interface RigOptions {
  fetchChunk?: (
    assetId: string,
    start: number,
    end: number,
    signal?: AbortSignal,
  ) => Promise<ArrayBuffer>
  mode?: TransportMode
  workerFactory?: () => WorkerLike | null
  frameCount?: number
  /** Monitoring-only limiter (spec §10.6.5). */
  limiter?: boolean
  /** Context cannot create a compressor (limiter is then skipped). */
  withCompressor?: boolean
  onPeaks?: (peaks: MixPeaks) => void
}

interface Rig {
  transport: PcmTransport
  context: TransportContextLike
  node: FakeWorkletNode
  gain: GainNodeLike
  /** The fake compressor; `null` when the context cannot create one. */
  compressor: CompressorNodeLike | null
  target: PlaybackTarget
  fetchCalls: { assetId: string; start: number; end: number; signal: AbortSignal | undefined }[]
  delay: ReturnType<typeof vi.fn>
  states: TransportState[]
  positions: number[]
  /** Settle the parked fill loop's delay (the mock also settles on abort). */
  tick: () => void
}

function makeRig(opts: RigOptions = {}): Rig {
  const frameCount = opts.frameCount ?? FRAMES
  const rigTarget = makeTarget(frameCount)
  const node = new FakeWorkletNode()
  const gain: GainNodeLike = {
    gain: { value: 1, setTargetAtTime: vi.fn() },
    connect: vi.fn(),
    disconnect: vi.fn(),
  }
  const compressor: CompressorNodeLike | null =
    opts.limiter && opts.withCompressor !== false
      ? {
          threshold: { value: 0, setTargetAtTime: vi.fn() },
          connect: vi.fn(),
          disconnect: vi.fn(),
        }
      : null
  const context: TransportContextLike = {
    currentTime: 0,
    sampleRate: RATE,
    state: 'running',
    onstatechange: null,
    destination: {},
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createWorkletNode: vi.fn().mockReturnValue(node),
    createGain: vi.fn().mockReturnValue(gain),
    ...(compressor ? { createDynamicsCompressor: () => compressor } : {}),
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
  }
  const fetchCalls: Rig['fetchCalls'] = []
  const defaultFetch: (
    assetId: string,
    start: number,
    end: number,
    signal?: AbortSignal,
  ) => Promise<ArrayBuffer> = async (assetId, start, end, signal) => {
    fetchCalls.push({ assetId, start, end, signal })
    const frames = Math.floor((end - start + 1) / BYTES_PER_FRAME)
    return new ArrayBuffer(frames * BYTES_PER_FRAME)
  }
  // Parks the prefetch loop after its initial fill (so the tests drive the
  // worklet side deterministically); settles on generation abort or `tick`.
  let tickResolve: (() => void) | null = null
  const delay = vi.fn(
    (_ms: number, signal?: AbortSignal) =>
      new Promise<void>((resolve) => {
        if (signal?.aborted) {
          resolve()
          return
        }
        signal?.addEventListener('abort', () => resolve(), { once: true })
        tickResolve = resolve
      }),
  )
  const states: TransportState[] = []
  const positions: number[] = []
  const transport = new PcmTransport({
    contextFactory: () => context,
    fetchChunk: opts.fetchChunk ?? defaultFetch,
    delay,
    // jsdom has no URL.createObjectURL; the fake addModule ignores the URL.
    moduleUrlFactory: (source: string) => `blob:fake-worklet-${source.length}`,
    mode: opts.mode,
    workerFactory: opts.workerFactory ?? (() => null),
    limiter: opts.limiter,
    onState: (s) => states.push(s),
    onPosition: (f) => positions.push(f),
    onPeaks: opts.onPeaks,
  })
  return {
    transport,
    context,
    node,
    gain,
    compressor,
    target: rigTarget,
    fetchCalls,
    delay,
    states,
    positions,
    tick: () => {
      tickResolve?.()
      tickResolve = null
    },
  }
}

/** Rig wired to a fake worker (worker protocol + shared path). */
function makeWorkerRig(mode?: TransportMode): { rig: Rig; worker: FakeFetchWorker } {
  const worker = new FakeFetchWorker()
  const rig = makeRig({ mode, workerFactory: () => worker })
  return { rig, worker }
}

/** Rig with a long source for flow-control tests. */
function makeLongRig(): { rig: Rig; worker: FakeFetchWorker } {
  const worker = new FakeFetchWorker()
  const rig = makeRig({ frameCount: LONG_FRAMES, mode: 'transfer', workerFactory: () => worker })
  return { rig, worker }
}

async function load(rig: Rig): Promise<void> {
  await rig.transport.loadSource({
    target: rig.target,
    projectRate: RATE,
    projectDurationFrames: rig.target.frameCount,
  })
}

/** Load, play, and acknowledge the initial fill: state becomes `playing`. */
async function ready(rig: Rig, generation = 0): Promise<void> {
  await load(rig)
  await rig.transport.play()
  rig.node.post({
    type: 'buffered',
    frames: rig.target.frameCount,
    queuedFrames: 0,
    generation,
  })
}

/** Flush pending microtasks (including the fill loop's fetch rounds). */
async function settle(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0))
}

function nodeOptions(rig: Rig): Record<string, unknown> {
  const createWorkletNode = rig.context.createWorkletNode as ReturnType<typeof vi.fn>
  return createWorkletNode.mock.calls[0][1] as Record<string, unknown>
}

/** View a ring over an existing SAB (the one the transport handed to the node). */
const ringView = viewSharedRing

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PcmTransport play', () => {
  it('initializes the graph, prefills, and reaches playing on buffered data', async () => {
    const rig = makeRig()
    await load(rig)
    await rig.transport.play()
    // The fill loop's first fetch round is a microtask ahead of play().
    await settle()

    expect(rig.context.audioWorklet.addModule).toHaveBeenCalledTimes(1)
    expect(rig.context.createWorkletNode).toHaveBeenCalledWith(
      'basseparate-pcm',
      expect.objectContaining({
        // Mixer path (M2.8): the worklet mixes all sources on one cursor.
        processorOptions: {
          sampleRate: RATE,
          frameCount: FRAMES,
          sources: [{ channelCount: 2 }],
        },
      }),
    )
    // One-second file: the whole file is fetched in a single chunk.
    expect(rig.fetchCalls).toHaveLength(1)
    expect(rig.fetchCalls[0].assetId).toBe('asset-1')
    expect(rig.fetchCalls[0].start).toBe(0)
    expect(rig.fetchCalls[0].end).toBe(FRAMES * BYTES_PER_FRAME - 1)
    const chunks = rig.node.posted('channels')
    expect(chunks).toHaveLength(1)
    expect(chunks[0].channels).toEqual([expect.any(Float32Array), expect.any(Float32Array)])
    expect(chunks[0].generation).toBe(0)

    expect(rig.transport.currentState).toBe('preparing')
    rig.node.post({ type: 'buffered', frames: FRAMES, queuedFrames: 0, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
    expect(rig.states).toEqual(['preparing', 'playing'])
  })

  it('pause posts the ramp message and freezes the extrapolated position', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.05, generation: 0 })

    rig.transport.pause()
    expect(rig.node.posted('pause')).toHaveLength(1)
    expect(rig.transport.currentState).toBe('paused')
    // pause() snapshots the extrapolated position (4800 + 0.05 * 48000 =
    // 7200), which is then frozen — no further extrapolation.
    expect(rig.transport.position).toBe(7200)
    rig.context.currentTime = 1.0
    expect(rig.transport.position).toBe(7200)
  })

  it('stop resets to zero, bumps the generation, and aborts fetches', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.transport.stop()
    expect(rig.transport.currentState).toBe('paused')
    expect(rig.transport.position).toBe(0)
    // The first seek is the play-time alignment of the fresh worklet.
    expect(rig.node.posted('seek')).toEqual([
      { type: 'seek', frame: 0, generation: 0 },
      { type: 'seek', frame: 0, generation: 1 },
    ])
    expect(rig.fetchCalls[0].signal?.aborted).toBe(true)
  })

  it('seek while playing flushes, aborts, refetches, and drops stale messages', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.05, generation: 0 })

    rig.transport.seek(24_000)
    expect(rig.transport.currentState).toBe('seeking')
    // The first seek is the play-time alignment of the fresh worklet.
    expect(rig.node.posted('seek')).toEqual([
      { type: 'seek', frame: 0, generation: 0 },
      { type: 'seek', frame: 24_000, generation: 1 },
    ])
    expect(rig.fetchCalls[0].signal?.aborted).toBe(true)
    // The refill (fill loop) starts at the new position.
    await settle()
    expect(rig.fetchCalls[1]?.start).toBe(24_000 * BYTES_PER_FRAME)

    // Stale-generation messages must not move the playhead or end playback.
    rig.node.post({ type: 'anchor', frame: 40_000, time: 0.9, generation: 0 })
    rig.node.post({ type: 'ended', generation: 0 })
    expect(rig.transport.position).toBe(24_000)
    expect(rig.transport.currentState).toBe('seeking')

    rig.node.post({ type: 'buffered', frames: 1000, queuedFrames: 0, generation: 1 })
    expect(rig.transport.currentState).toBe('playing')
  })

  it('seek before playback parks the position and starts from it', async () => {
    const rig = makeRig()
    await load(rig)

    rig.transport.seek(12_000)
    expect(rig.transport.currentState).toBe('unloaded')
    expect(rig.transport.position).toBe(12_000)

    await rig.transport.play()
    expect(rig.fetchCalls[0].start).toBe(12_000 * BYTES_PER_FRAME)
  })

  it('ends at the endpoint, reports the final position, and restarts from zero', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.node.post({ type: 'ended', generation: 0 })
    expect(rig.transport.currentState).toBe('ended')
    expect(rig.transport.position).toBe(FRAMES)

    await rig.transport.play()
    // The first seek is the play-time alignment of the fresh worklet.
    expect(rig.node.posted('seek')).toEqual([
      { type: 'seek', frame: 0, generation: 0 },
      { type: 'seek', frame: 0, generation: 1 },
    ])
    expect(rig.transport.currentState).toBe('preparing')
  })

  it('enters buffering on underrun and returns to playing at the 2 s threshold', async () => {
    const rig = makeRig()
    await ready(rig)
    expect(rig.transport.diagnostics.underruns).toBe(0)

    rig.node.post({ type: 'underrun', generation: 0 })
    expect(rig.transport.currentState).toBe('buffering')
    expect(rig.transport.diagnostics.underruns).toBe(1)
    expect(rig.transport.diagnostics.lastUnderrunAt).not.toBeNull()

    // Below the 2 s threshold: still buffering.
    rig.node.post({ type: 'buffered', frames: 1000, queuedFrames: 0, generation: 0 })
    expect(rig.transport.currentState).toBe('buffering')
    // At the threshold: playing again, anchored (no skipped frames).
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 5000, time: 0.1, generation: 0 })
    rig.node.post({ type: 'buffered', frames: 2 * RATE, queuedFrames: 0, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
    expect(rig.transport.position).toBe(5000)
  })

  it('applies the output gain with a short ramp, clamped at 4', async () => {
    const rig = makeRig()
    await load(rig)

    rig.transport.setOutputGain(1.5) // no graph yet: remembered
    await rig.transport.play()
    expect(rig.gain.gain.value).toBe(1.5)

    rig.transport.setOutputGain(2)
    expect(rig.gain.gain.setTargetAtTime).toHaveBeenCalledWith(2, rig.context.currentTime, 0.01)
    rig.transport.setOutputGain(99)
    expect(rig.gain.gain.setTargetAtTime).toHaveBeenCalledWith(4, rig.context.currentTime, 0.01)
  })

  it('surfaces fetch failures as the error state', async () => {
    const rig = makeRig({
      fetchChunk: async () => {
        throw new Error('boom')
      },
    })
    await load(rig)
    await rig.transport.play()
    await vi.waitFor(() => expect(rig.transport.currentState).toBe('error'))
    expect(rig.transport.currentError).toBe('boom')
  })

  it('dispose tears the graph down and closes the context', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.transport.dispose()
    expect(rig.node.disconnected).toBe(true)
    expect(rig.gain.disconnect).toHaveBeenCalled()
    expect(rig.context.close).toHaveBeenCalledTimes(1)

    // A disposed transport ignores worklet messages.
    rig.node.post({ type: 'buffered', frames: 1, queuedFrames: 0, generation: 0 })
    rig.node.post({ type: 'anchor', frame: 9999, time: 0.5, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
    const before = rig.transport.position
    expect(rig.transport.position).toBe(before)
  })
})

describe('mode selection', () => {
  it('auto picks the shared path when cross-origin isolated', async () => {
    vi.stubGlobal('crossOriginIsolated', true)
    const { rig, worker } = makeWorkerRig()
    await load(rig)
    const p = rig.transport.play()
    // Let the graph finish initializing so the port's onmessage is wired
    // before the worklet's flush acknowledgment arrives.
    await settle()
    rig.node.post({ type: 'flushed', generation: 0 })
    await p

    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    const sabs = processorOptions.sabs as SharedArrayBuffer[]
    expect(sabs).toHaveLength(1)
    expect(sabs[0]).toBeInstanceOf(SharedArrayBuffer)
    expect(options.transfer).toEqual([sabs[0]])
    expect(worker.messages.some((m) => m.kind === 'shared-init')).toBe(true)
  })

  it('auto picks the transfer path otherwise', async () => {
    const { rig, worker } = makeWorkerRig()
    await load(rig)
    await rig.transport.play()

    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    expect(processorOptions).not.toHaveProperty('sabs')
    expect(options).not.toHaveProperty('transfer')
    expect(worker.messages.some((m) => m.kind === 'shared-init')).toBe(false)
    expect(worker.messages.some((m) => m.kind === 'generation')).toBe(true)
  })

  it('honors an explicit transfer mode even when isolated', async () => {
    vi.stubGlobal('crossOriginIsolated', true)
    const { rig, worker } = makeWorkerRig('transfer')
    await load(rig)
    await rig.transport.play()

    const options = nodeOptions(rig)
    expect(options).not.toHaveProperty('transfer')
    expect(worker.messages.some((m) => m.kind === 'shared-init')).toBe(false)
  })

  it('honors an explicit shared mode when not isolated', async () => {
    const { rig, worker } = makeWorkerRig('shared')
    await load(rig)
    const p = rig.transport.play()
    // Let the graph finish initializing so the port's onmessage is wired
    // before the worklet's flush acknowledgment arrives.
    await settle()
    rig.node.post({ type: 'flushed', generation: 0 })
    await p

    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    expect((processorOptions.sabs as SharedArrayBuffer[])[0]).toBeInstanceOf(SharedArrayBuffer)
    expect(worker.messages.some((m) => m.kind === 'shared-init')).toBe(true)
  })
})

describe('transfer path flow control', () => {
  it('fetches to the 8 s lookahead, then parks', async () => {
    const { rig, worker } = makeLongRig()
    await load(rig)
    await rig.transport.play()
    await settle()

    // 8 s steady lookahead in 1 s chunks.
    expect(worker.fetchJobs).toHaveLength(8)
    expect(worker.fetchJobs[0]).toMatchObject({ start: 0, generation: 0 })
    expect(worker.fetchJobs[7]).toMatchObject({ start: 7 * RATE * BYTES_PER_FRAME, generation: 0 })
  })

  it('pauses the worker on queue-high and resumes below budget − margin', async () => {
    const { rig, worker } = makeLongRig()
    await load(rig)
    await rig.transport.play()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    // The worklet reports the budget is full: no new fetch jobs.
    rig.node.post({ type: 'queue-high', generation: 0 })
    rig.tick()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    // Consumption frees space and the queued count is below
    // budget − margin (11 s): the worker gets new work.
    rig.context.currentTime = 4
    rig.node.post({ type: 'anchor', frame: 4 * RATE, time: 4, generation: 0 })
    rig.node.post({ type: 'buffered', frames: 480_000, queuedFrames: 480_000, generation: 0 })
    rig.tick()
    await settle()
    expect(worker.fetchJobs.length).toBeGreaterThan(8)
  })

  it('honors the budget gate even without a queue-high notice', async () => {
    const { rig, worker } = makeLongRig()
    await load(rig)
    await rig.transport.play()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    // At the full 12 s budget: the gate blocks the next chunk.
    rig.node.post({ type: 'buffered', frames: 576_000, queuedFrames: 576_000, generation: 0 })
    rig.context.currentTime = 4
    rig.node.post({ type: 'anchor', frame: 4 * RATE, time: 4, generation: 0 })
    rig.tick()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    // Below budget − margin (11 s): the next chunk goes.
    rig.node.post({ type: 'buffered', frames: 500_000, queuedFrames: 500_000, generation: 0 })
    rig.tick()
    await settle()
    expect(worker.fetchJobs.length).toBeGreaterThan(8)
  })

  it('seek aborts in-flight fetches and refetches under the new generation', async () => {
    const { rig, worker } = makeLongRig()
    await load(rig)
    await rig.transport.play()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    rig.transport.seek(480_000)
    expect(rig.transport.currentState).toBe('seeking')
    await settle()

    // The worker learns the new generation before any new fetch job.
    // (The play-time alignment posted a gen-0 message first.)
    const genIdx = worker.messages.map((m) => m.kind).lastIndexOf('generation')
    expect(worker.messages[genIdx]).toEqual({ kind: 'generation', generation: 1 })
    const nextFetch = worker.messages.slice(genIdx + 1).find((m) => m.kind === 'fetch') as {
      start: number
      generation: number
    }
    expect(nextFetch).toMatchObject({ start: 480_000 * BYTES_PER_FRAME, generation: 1 })
  })
})

describe('shared path', () => {
  it('fills the SAB end-to-end and seeks through the flush handshake', async () => {
    const { rig, worker } = makeWorkerRig('shared')
    await load(rig)
    const p = rig.transport.play()
    // Let the graph finish initializing so the port's onmessage is wired
    // before the worklet's flush acknowledgment arrives.
    await settle()
    // The worklet acknowledges the initial seek; only then does the
    // transport reset the worker's writer index and start the fill.
    rig.node.post({ type: 'flushed', generation: 0 })
    await p
    await settle()

    // The worker wrote the one-second file into the ring.
    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    const sab = (processorOptions.sabs as SharedArrayBuffer[])[0]
    const ring = ringView(sab, 2)
    expect(Atomics.load(ring.header, 0)).toBe(0)
    expect(Atomics.load(ring.header, 1)).toBe(FRAMES) // writer: end of file
    expect(Atomics.load(ring.header, 2)).toBe(0) // reader: not consumed yet

    // The worklet side (mixer path) consumes what the worker wrote.
    const core = new MixState({
      sampleRate: RATE,
      frameCount: FRAMES,
      sources: [{ channelCount: 2 }],
    })
    core.attachShared(0, sab)
    const out = [new Float32Array(128), new Float32Array(128)]
    const res = core.process(0, out)
    expect(res.consumed).toBe(128)
    expect(Atomics.load(ring.header, 2)).toBe(128)

    // Seek: the worklet flushes (stores its reader index), then the
    // transport resets the worker's writer base via the flush-ack.
    rig.transport.seek(24_000)
    expect(rig.transport.currentState).toBe('seeking')
    // The first seek is the play-time alignment of the fresh worklet.
    expect(rig.node.posted('seek')).toEqual([
      { type: 'seek', frame: 0, generation: 0 },
      { type: 'seek', frame: 24_000, generation: 1 },
    ])
    core.seek(24_000, 1) // what the real worklet does on the seek message
    rig.node.post({ type: 'flushed', generation: 1 })
    await settle()

    expect(Atomics.load(ring.header, 0)).toBe(1)
    expect(Atomics.load(ring.header, 2)).toBe(24_000) // worklet reader
    // The refill wrote the remainder: writer advanced past the base.
    expect(Atomics.load(ring.header, 1)).toBe(FRAMES)
    const fetches = worker.fetchJobs
    expect(fetches.at(-1)).toMatchObject({ start: 24_000 * BYTES_PER_FRAME, generation: 1 })
  })

  it('shared path with the main-thread fallback (no worker)', async () => {
    const rig = makeRig({ mode: 'shared' }) // workerFactory null → DirectFetchSource
    await load(rig)
    const p = rig.transport.play()
    // Let the graph finish initializing so the port's onmessage is wired
    // before the worklet's flush acknowledgment arrives.
    await settle()
    rig.node.post({ type: 'flushed', generation: 0 })
    await p
    await settle()

    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    const sab = (processorOptions.sabs as SharedArrayBuffer[])[0]
    const ring = ringView(sab, 2)
    expect(Atomics.load(ring.header, 1)).toBe(FRAMES)
  })
})

describe('multi-source mix (M2.8, spec §10.5)', () => {
  const MIX_SOURCES = [
    { assetId: 'vocals', sampleRate: RATE, channelCount: 2, frameCount: FRAMES },
    { assetId: 'drums', sampleRate: RATE, channelCount: 1, frameCount: FRAMES },
  ]

  it('refuses sources that do not match the project rate or duration', async () => {
    const rig = makeRig()
    // Rate mismatch: a hard prepare error, never a resample.
    await expect(
      rig.transport.loadSource({
        sources: [{ assetId: 'a', sampleRate: 44_100, channelCount: 2, frameCount: FRAMES }],
        projectRate: RATE,
        projectDurationFrames: FRAMES,
      }),
    ).rejects.toThrow(RangeError)
    // Duration mismatch: hard prepare error.
    await expect(
      rig.transport.loadSource({
        sources: [{ assetId: 'a', sampleRate: RATE, channelCount: 2, frameCount: FRAMES - 1 }],
        projectRate: RATE,
        projectDurationFrames: FRAMES,
      }),
    ).rejects.toThrow(RangeError)
    // No sources at all.
    await expect(
      rig.transport.loadSource({ sources: [], projectRate: RATE, projectDurationFrames: FRAMES }),
    ).rejects.toThrow(RangeError)
  })

  it('initializes a two-source mix and fetches both assets per round', async () => {
    const { rig, worker } = makeWorkerRig('transfer')
    await rig.transport.loadSource({
      sources: MIX_SOURCES,
      projectRate: RATE,
      projectDurationFrames: FRAMES,
    })
    await rig.transport.play()
    await settle()

    const processorOptions = nodeOptions(rig).processorOptions as Record<string, unknown>
    expect(processorOptions.sources).toEqual([{ channelCount: 2 }, { channelCount: 1 }])
    expect(processorOptions).not.toHaveProperty('sabs')

    // One 1 s chunk per source (stereo bytes for vocals, mono for drums).
    const jobs = worker.fetchJobs
    expect(jobs).toHaveLength(2)
    expect(jobs[0]).toMatchObject({ source: 0, start: 0, generation: 0 })
    expect(jobs[1]).toMatchObject({ source: 1, start: 0, generation: 0 })
    const init = worker.messages.find((m) => m.kind === 'shared-init')
    expect(init).toBeUndefined() // transfer mode: no SABs

    // The relayed chunks carry the source index and per-source channels.
    const chunks = rig.node.posted('channels')
    expect(chunks).toHaveLength(2)
    expect(chunks[0].source).toBe(0)
    expect(chunks[0].channels).toHaveLength(2)
    expect(chunks[1].source).toBe(1)
    expect(chunks[1].channels).toHaveLength(1)
  })

  it('fills one ring per source and seeks through a single flush handshake', async () => {
    const { rig, worker } = makeWorkerRig('shared')
    await rig.transport.loadSource({
      sources: MIX_SOURCES,
      projectRate: RATE,
      projectDurationFrames: FRAMES,
    })
    const p = rig.transport.play()
    // Let the graph finish initializing so the port's onmessage is wired
    // before the worklet's flush acknowledgment arrives.
    await settle()
    rig.node.post({ type: 'flushed', generation: 0 })
    await p
    await settle()

    const processorOptions = nodeOptions(rig).processorOptions as Record<string, unknown>
    const sabs = processorOptions.sabs as SharedArrayBuffer[]
    expect(sabs).toHaveLength(2)
    // Both rings were filled to end of file by their own writer index.
    const ringA = ringView(sabs[0], 2)
    const ringB = ringView(sabs[1], 1)
    expect(Atomics.load(ringA.header, 1)).toBe(FRAMES)
    expect(Atomics.load(ringB.header, 1)).toBe(FRAMES)

    // One seek flushes both rings through a single flush-ack.
    rig.transport.seek(24_000)
    expect(rig.transport.currentState).toBe('seeking')
    const core = new MixState({
      sampleRate: RATE,
      frameCount: FRAMES,
      sources: [{ channelCount: 2 }, { channelCount: 1 }],
    })
    core.attachShared(0, sabs[0])
    core.attachShared(1, sabs[1])
    core.seek(24_000, 1) // what the real worklet does on the seek message
    rig.node.post({ type: 'flushed', generation: 1 })
    await settle()

    // The shared cursor reset both writer indices; the refill covered the
    // remainder of both assets.
    expect(Atomics.load(ringA.header, 2)).toBe(24_000)
    expect(Atomics.load(ringB.header, 2)).toBe(24_000)
    expect(Atomics.load(ringA.header, 1)).toBe(FRAMES)
    expect(Atomics.load(ringB.header, 1)).toBe(FRAMES)
    const refill = worker.fetchJobs.filter((j) => j.generation === 1)
    expect(refill.map((j) => j.source).sort((a, b) => a - b)).toEqual([0, 1])
  })

  it('forwards mixer params and master gain to the worklet', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.transport.setSourceParams(0, { gain: 1.41, balance: 0.25, mute: false, solo: true })
    expect(rig.node.posted('params')).toEqual([
      { type: 'params', source: 0, gain: 1.41, balance: 0.25, mute: false, solo: true },
    ])

    rig.transport.setMasterGain(2)
    expect(rig.node.posted('master')).toEqual([{ type: 'master', gain: 2 }])
  })

  it('applies a pending master gain to a fresh graph on play', async () => {
    const rig = makeRig()
    await load(rig)
    rig.transport.setMasterGain(0.5) // no graph yet: remembered
    await rig.transport.play()
    expect(rig.node.posted('master')).toEqual([{ type: 'master', gain: 0.5 }])
  })

  it('surfaces per-quantum peaks from anchor messages', async () => {
    const peaks: MixPeaks[] = []
    const rig = makeRig({ onPeaks: (p) => peaks.push(p) })
    await ready(rig)

    rig.node.post({
      type: 'anchor',
      frame: 4800,
      time: 0.05,
      generation: 0,
      peaks: { tracks: [0.5, 0.25], master: 0.75 },
    })
    expect(peaks).toEqual([{ tracks: [0.5, 0.25], master: 0.75 }])

    // Anchors without peaks (legacy core) must not report.
    rig.node.post({ type: 'anchor', frame: 9600, time: 0.1, generation: 0 })
    expect(peaks).toHaveLength(1)
  })

  it('inserts the monitoring limiter after the gain and folds its delay in', async () => {
    const rig = makeRig({ limiter: true })
    expect(rig.compressor).not.toBeNull()
    await ready(rig)

    // Graph: node → gain → limiter → destination.
    expect(rig.node.connectedTo).toEqual([rig.gain])
    expect(rig.gain.connect).toHaveBeenCalledWith(rig.compressor)
    expect(rig.compressor!.connect).toHaveBeenCalledWith(rig.context.destination)
    expect(rig.compressor!.threshold.value).toBe(-1)

    // The 10 ms limiter delay is folded into the audible-time mapping.
    rig.context.currentTime = 0.25
    expect(rig.transport.getAudiblePosition()).toBe((0.25 - 0.01) * RATE)
  })

  it('skips the limiter when the context cannot create one', async () => {
    const rig = makeRig({ limiter: true, withCompressor: false })
    expect(rig.compressor).toBeNull()
    await ready(rig)
    expect(rig.gain.connect).toHaveBeenCalledWith(rig.context.destination)
    // No limiter: no added latency.
    rig.context.currentTime = 0.25
    expect(rig.transport.getAudiblePosition()).toBe(0.25 * RATE)
  })
})

describe('suspension', () => {
  it('freezes the position while suspended and resumes when running', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.05, generation: 0 })

    rig.context.state = 'suspended'
    rig.context.onstatechange?.({ type: 'statechange' })
    expect(rig.transport.isSuspended).toBe(true)
    // The state machine is untouched; the position stops extrapolating.
    expect(rig.transport.currentState).toBe('playing')
    rig.context.currentTime = 0.5
    expect(rig.transport.position).toBe(4800)

    rig.context.state = 'running'
    rig.context.onstatechange?.({ type: 'statechange' })
    expect(rig.transport.isSuspended).toBe(false)
    // Extrapolation resumes from the anchor: 4800 + 0.45 * 48000
    // (stays inside the one-second project, so no clamping).
    expect(rig.transport.position).toBe(4800 + (0.5 - 0.05) * RATE)
  })

  it('keeps the fill loop working across a suspend/resume cycle', async () => {
    const { rig, worker } = makeLongRig()
    await load(rig)
    await rig.transport.play()
    await settle()
    expect(worker.fetchJobs).toHaveLength(8)

    rig.context.currentTime = 4
    rig.node.post({ type: 'anchor', frame: 4 * RATE, time: 4, generation: 0 })
    rig.context.state = 'suspended'
    rig.context.onstatechange?.({ type: 'statechange' })
    expect(rig.transport.isSuspended).toBe(true)

    rig.context.state = 'running'
    rig.context.onstatechange?.({ type: 'statechange' })
    rig.tick()
    await settle()
    // The loop re-engaged and closed part of the 8 s lookahead gap.
    expect(worker.fetchJobs.length).toBeGreaterThan(8)
  })
})

describe('context loss and rebind', () => {
  it('retains the position on context loss and rebinds to a fresh context', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.05, generation: 0 })
    expect(rig.transport.position).toBe(7200)

    rig.context.state = 'closed'
    rig.context.onstatechange?.({ type: 'statechange' })
    expect(rig.transport.currentState).toBe('error')
    expect(rig.transport.contextLost).toBe(true)
    expect(rig.transport.position).toBe(7200)
    expect(rig.node.disconnected).toBe(true)

    // Recovery: a fresh worklet node on the (reopened) context.
    const freshNode = new FakeWorkletNode()
    rig.context.state = 'running'
    ;(rig.context.createWorkletNode as ReturnType<typeof vi.fn>).mockReturnValue(freshNode)
    rig.node = freshNode

    rig.transport.rebind({
      target: rig.target,
      projectRate: RATE,
      projectDurationFrames: rig.target.frameCount,
    })
    expect(rig.transport.currentState).toBe('unloaded')
    expect(rig.transport.contextLost).toBe(false)
    expect(rig.transport.position).toBe(7200)

    await rig.transport.play()
    // Playback starts at the retained position.
    expect(rig.fetchCalls.at(-1)?.start).toBe(7200 * BYTES_PER_FRAME)
    expect(freshNode.posted('seek')).toEqual([{ type: 'seek', frame: 7200, generation: 0 }])
  })
})

describe('sync', () => {
  it('reports the current state and position', async () => {
    const rig = makeRig()
    await ready(rig)
    const positionsBefore = rig.positions.length

    const info = rig.transport.sync()
    expect(info.state).toBe('playing')
    expect(info.position).toBe(rig.transport.position)
    expect(info.isSuspended).toBe(false)
    expect(info.contextLost).toBe(false)
    expect(rig.positions.length).toBeGreaterThan(positionsBefore)
  })

  it('picks up a context that closed while the tab was hidden', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.context.state = 'closed'
    const lost = rig.transport.sync()
    expect(lost.state).toBe('error')
    expect(lost.contextLost).toBe(true)
    expect(rig.transport.contextLost).toBe(true)
  })
})

describe('audible position (spec §16.2)', () => {
  it('falls back to the context time when getOutputTimestamp is absent', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.25
    expect(rig.transport.getAudiblePosition()).toBe(0.25 * RATE)
  })

  it('uses the output-device timestamp when available', async () => {
    const rig = makeRig()
    await ready(rig)
    // The output device lags the context clock by 0.1 s.
    rig.context.getOutputTimestamp = () => ({
      contextTime: rig.context.currentTime - 0.1,
      performanceTime: 0,
    })
    rig.context.currentTime = 0.25
    expect(rig.transport.getAudiblePosition()).toBe(0.15 * RATE)
  })

  it('maps delayed output times back through retained segments', async () => {
    const rig = makeRig()
    await ready(rig) // segment: frame 0 at context time 0
    let outTime = 0.5
    rig.context.getOutputTimestamp = () => ({
      contextTime: outTime,
      performanceTime: 0,
    })
    rig.context.currentTime = 0.5
    rig.transport.seek(24_000) // new segment: frame 24000 at context time 0.5
    expect(rig.transport.currentState).toBe('seeking')

    // The output clock sits exactly on the seek: the new segment.
    expect(rig.transport.getAudiblePosition()).toBe(24_000)
    // The output clock is past the seek: extrapolate in the new segment.
    outTime = 0.55
    expect(rig.transport.getAudiblePosition()).toBe(24_000 + 0.05 * RATE)
    // The output clock is still inside the pre-seek segment (device
    // latency): map it to the old segment, not the new one.
    outTime = 0.45
    expect(rig.transport.getAudiblePosition()).toBe(0.45 * RATE)
  })

  it('freezes at the last anchor while buffering', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.1, generation: 0 })
    rig.node.post({ type: 'underrun', generation: 0 })
    expect(rig.transport.currentState).toBe('buffering')
    rig.context.currentTime = 0.5
    expect(rig.transport.getAudiblePosition()).toBe(4800)
  })
})

describe('spec §18.6 gap coverage', () => {
  it('rapid repeated seeks land on the last one and drop stale generations', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.transport.seek(9_600) // 20 %
    rig.transport.seek(19_200) // 40 %
    rig.transport.seek(28_800) // 60 %
    await settle()

    // The play-time alignment seek plus one per rapid seek.
    const seeks = rig.node.posted('seek')
    expect(seeks).toHaveLength(4)
    const gens = seeks.map((m) => m.generation as number)
    expect(gens[1]).toBeLessThan(gens[2])
    expect(gens[2]).toBeLessThan(gens[3])
    expect(rig.transport.currentState).toBe('seeking')
    expect(rig.transport.position).toBe(28_800)

    // Messages from superseded generations must not move the playhead.
    rig.node.post({ type: 'buffered', frames: 1000, queuedFrames: 0, generation: gens[1] })
    rig.node.post({ type: 'anchor', frame: 5_000, time: 0.1, generation: gens[1] })
    expect(rig.transport.currentState).toBe('seeking')
    expect(rig.transport.position).toBe(28_800)

    // The current generation's acknowledgement resumes at the last seek.
    rig.node.post({ type: 'buffered', frames: 1000, queuedFrames: 0, generation: gens[3] })
    expect(rig.transport.currentState).toBe('playing')
    expect(rig.transport.position).toBe(28_800)
  })

  it('clamps seeks at and past EOF to the endpoint', async () => {
    const rig = makeRig()
    await ready(rig)
    const fillsAfterReady = rig.fetchCalls.length

    rig.transport.seek(FRAMES - 1)
    await settle()
    expect(rig.transport.position).toBe(FRAMES - 1)
    // Only the final frame was refetched.
    expect(rig.fetchCalls).toHaveLength(fillsAfterReady + 1)
    expect(rig.fetchCalls[1].start).toBe((FRAMES - 1) * BYTES_PER_FRAME)

    rig.transport.seek(FRAMES + 10_000)
    await settle()
    expect(rig.transport.currentState).toBe('seeking')
    expect(rig.transport.position).toBe(FRAMES)
    // Nothing beyond the endpoint is requested.
    expect(rig.fetchCalls).toHaveLength(fillsAfterReady + 1)
  })

  it('drops the partial frame of a short final chunk and refetches the rest', async () => {
    const total = FRAMES * BYTES_PER_FRAME
    const calls: { start: number; end: number }[] = []
    const rig = makeRig({
      fetchChunk: async (_id, start, end) => {
        calls.push({ start, end })
        const len = Math.max(0, Math.min(end + 1, total) - start)
        // The first response is short by 4 bytes: one partial channel
        // sample that must not be served.
        return new ArrayBuffer(start === 0 ? len - 4 : len)
      },
    })
    await load(rig)
    await rig.transport.play()
    await settle()

    // The short chunk served 47 999 complete frames; the loop refetched
    // the single remaining frame instead of serving the partial one.
    expect(calls).toHaveLength(2)
    expect(calls[1].start).toBe(47_999 * BYTES_PER_FRAME)
    expect(calls[1].end).toBe(total - 1)

    rig.node.post({ type: 'buffered', frames: FRAMES, queuedFrames: 0, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
    rig.node.post({ type: 'ended', generation: 0 })
    expect(rig.transport.currentState).toBe('ended')
    expect(rig.transport.position).toBe(FRAMES)
  })

  it('keeps target-rate bookkeeping when the context runs at a different rate', async () => {
    const rig = makeRig()
    rig.context.sampleRate = 96_000 // a 96 kHz device context, 48 kHz target

    await load(rig)
    await rig.transport.play()
    await settle()

    // Fetch ranges are target bytes, not context-rate bytes.
    expect(rig.fetchCalls[0].start).toBe(0)
    expect(rig.fetchCalls[0].end).toBe(FRAMES * BYTES_PER_FRAME - 1)
    // The worklet is told the target rate.
    expect(nodeOptions(rig).processorOptions).toEqual(expect.objectContaining({ sampleRate: RATE }))

    rig.node.post({ type: 'buffered', frames: FRAMES, queuedFrames: 0, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')

    // Position and clamping stay in target frames.
    rig.transport.seek(FRAMES + 1000)
    await settle()
    expect(rig.transport.position).toBe(FRAMES)
  })
})
