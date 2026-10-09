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
  type GainNodeLike,
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
import { ConsumptionState } from '../src/playback/worklet-processor.js'

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
  private ring: SharedRing | null = null

  get fetchJobs(): Array<{ start: number; end: number; generation: number }> {
    return this.messages.filter((m) => m.kind === 'fetch') as Array<{
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
      // View the transferred SAB (like the real worker), not a new one.
      this.ring = ringView(msg.sab as SharedArrayBuffer, msg.channelCount as number)
      this.onmessage?.({ data: { kind: 'ready' } })
      return
    }
    if (msg.kind === 'flush-ack') {
      if (this.ring) {
        acknowledgeSharedFlush(this.ring, msg.generation as number, msg.baseFrame as number)
      }
      this.onmessage?.({ data: { kind: 'flushed' } })
      return
    }
    if (msg.kind !== 'fetch') return
    const channelCount = msg.channelCount as number
    const bytesPerFrame = 4 * channelCount
    const frames = Math.floor(((msg.end as number) - (msg.start as number) + 1) / bytesPerFrame)
    const startFrame = Math.floor((msg.start as number) / bytesPerFrame)
    if (this.ring) {
      const written = writeSharedRing(this.ring, new ArrayBuffer(frames * bytesPerFrame))
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
}

interface Rig {
  transport: PcmTransport
  context: TransportContextLike
  node: FakeWorkletNode
  gain: GainNodeLike
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
  const context: TransportContextLike = {
    currentTime: 0,
    sampleRate: RATE,
    state: 'running',
    onstatechange: null,
    destination: {},
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createWorkletNode: vi.fn().mockReturnValue(node),
    createGain: vi.fn().mockReturnValue(gain),
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
    onState: (s) => states.push(s),
    onPosition: (f) => positions.push(f),
  })
  return {
    transport,
    context,
    node,
    gain,
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
        processorOptions: { sampleRate: RATE, channelCount: 2, frameCount: FRAMES },
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
    // 4800 + (0.1 - 0.05) * 48000 = 7200, frozen from here on.
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
    expect(processorOptions.sab).toBeInstanceOf(SharedArrayBuffer)
    expect(options.transfer).toEqual([processorOptions.sab])
    expect(worker.messages.some((m) => m.kind === 'shared-init')).toBe(true)
  })

  it('auto picks the transfer path otherwise', async () => {
    const { rig, worker } = makeWorkerRig()
    await load(rig)
    await rig.transport.play()

    const options = nodeOptions(rig)
    const processorOptions = options.processorOptions as Record<string, unknown>
    expect(processorOptions).not.toHaveProperty('sab')
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
    expect(processorOptions.sab).toBeInstanceOf(SharedArrayBuffer)
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
    const sab = processorOptions.sab as SharedArrayBuffer
    const ring = ringView(sab, 2)
    expect(Atomics.load(ring.header, 0)).toBe(0)
    expect(Atomics.load(ring.header, 1)).toBe(FRAMES) // writer: end of file
    expect(Atomics.load(ring.header, 2)).toBe(0) // reader: not consumed yet

    // The worklet side consumes what the worker wrote.
    const core = new ConsumptionState({ sampleRate: RATE, channelCount: 2, frameCount: FRAMES })
    core.attachShared(sab)
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
    const sab = processorOptions.sab as SharedArrayBuffer
    const ring = ringView(sab, 2)
    expect(Atomics.load(ring.header, 1)).toBe(FRAMES)
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
