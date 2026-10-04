/**
 * Tests for the AudioWorklet transport (M1.12, plan §5, items 9–17).
 *
 * jsdom has no `AudioContext` / `AudioWorklet`, so the tests inject a
 * fake context whose worklet node exposes a scriptable port: the test
 * plays the worklet side by calling `node.post({type, ...})` (the same
 * shape the processor adapter in `worklet-processor.js` emits).
 */

import { describe, expect, it, vi } from 'vitest'
import {
  PcmTransport,
  type GainNodeLike,
  type TransportContextLike,
  type TransportState,
  type WorkletNodeLike,
} from '../src/playback/transport'
import type { PlaybackTarget } from '../src/api/playback'

const RATE = 48_000
const FRAMES = 48_000 // a one-second source
const BYTES_PER_FRAME = 4 * 2

const target: PlaybackTarget = {
  assetId: 'asset-1',
  role: 'playback',
  sampleRate: RATE,
  channelCount: 2,
  frameCount: FRAMES,
  byteCount: FRAMES * BYTES_PER_FRAME,
  durationSeconds: 1,
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

interface Rig {
  transport: PcmTransport
  context: TransportContextLike
  node: FakeWorkletNode
  gain: GainNodeLike
  contextFactoryCalls: number
  fetchCalls: { start: number; end: number; signal: AbortSignal | undefined }[]
  delay: ReturnType<typeof vi.fn>
  states: TransportState[]
  positions: number[]
}

function makeRig(
  fetchChunk?: (start: number, end: number, signal?: AbortSignal) => Promise<ArrayBuffer>,
): Rig {
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
    destination: {},
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createWorkletNode: vi.fn().mockReturnValue(node),
    createGain: vi.fn().mockReturnValue(gain),
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
  }
  let contextFactoryCalls = 0
  const fetchCalls: Rig['fetchCalls'] = []
  const defaultFetch: (
    start: number,
    end: number,
    signal?: AbortSignal,
  ) => Promise<ArrayBuffer> = async (start, end, signal) => {
    fetchCalls.push({ start, end, signal })
    const frames = Math.floor((end - start + 1) / BYTES_PER_FRAME)
    return new ArrayBuffer(frames * BYTES_PER_FRAME)
  }
  // Parks the prefetch loop after its initial fill (so the tests drive the
  // worklet side deterministically) but settles when the generation aborts.
  const delay = vi.fn(
    (_ms: number, signal?: AbortSignal) =>
      new Promise<void>((resolve) => {
        if (signal?.aborted) {
          resolve()
          return
        }
        signal?.addEventListener('abort', () => resolve(), { once: true })
      }),
  )
  const states: TransportState[] = []
  const positions: number[] = []
  const transport = new PcmTransport({
    contextFactory: () => {
      contextFactoryCalls += 1
      return context
    },
    fetchChunk: fetchChunk ?? defaultFetch,
    delay,
    // jsdom has no URL.createObjectURL; the fake addModule ignores the URL.
    moduleUrlFactory: (source: string) => `blob:fake-worklet-${source.length}`,
    onState: (s) => states.push(s),
    onPosition: (f) => positions.push(f),
  })
  return {
    transport,
    context,
    node,
    gain,
    contextFactoryCalls,
    fetchCalls,
    delay,
    states,
    positions,
  }
}

async function load(rig: Rig): Promise<void> {
  await rig.transport.loadSource({ target, projectRate: RATE, projectDurationFrames: FRAMES })
}

/** Load, play, and acknowledge the initial fill: state becomes `playing`. */
async function ready(rig: Rig): Promise<void> {
  await load(rig)
  await rig.transport.play()
  rig.node.post({ type: 'data', frames: FRAMES, generation: 0 })
}

describe('PcmTransport play', () => {
  it('initializes the graph, prefills, and reaches playing on data', async () => {
    const rig = makeRig()
    await load(rig)
    await rig.transport.play()

    expect(rig.context.audioWorklet.addModule).toHaveBeenCalledTimes(1)
    expect(rig.context.createWorkletNode).toHaveBeenCalledWith(
      'basseparate-pcm',
      expect.objectContaining({
        processorOptions: { sampleRate: RATE, channelCount: 2, frameCount: FRAMES },
      }),
    )
    // One-second file: the whole file is fetched in a single chunk.
    expect(rig.fetchCalls).toHaveLength(1)
    expect(rig.fetchCalls[0].start).toBe(0)
    expect(rig.fetchCalls[0].end).toBe(FRAMES * BYTES_PER_FRAME - 1)
    const samples = rig.node.posted('samples')
    expect(samples).toHaveLength(1)
    expect(samples[0].buffer).toBeInstanceOf(ArrayBuffer)

    expect(rig.transport.currentState).toBe('preparing')
    rig.node.post({ type: 'data', frames: FRAMES, generation: 0 })
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
    expect(rig.node.posted('seek')).toEqual([{ type: 'seek', frame: 0, generation: 1 }])
    expect(rig.fetchCalls[0].signal?.aborted).toBe(true)
  })

  it('seek while playing flushes, aborts, refetches, and drops stale messages', async () => {
    const rig = makeRig()
    await ready(rig)
    rig.context.currentTime = 0.1
    rig.node.post({ type: 'anchor', frame: 4800, time: 0.05, generation: 0 })

    rig.transport.seek(24_000)
    expect(rig.transport.currentState).toBe('seeking')
    expect(rig.node.posted('seek')).toEqual([{ type: 'seek', frame: 24_000, generation: 1 }])
    expect(rig.fetchCalls[0].signal?.aborted).toBe(true)
    // The refill starts at the new position.
    expect(rig.fetchCalls[1]?.start).toBe(24_000 * BYTES_PER_FRAME)

    // Stale-generation messages must not move the playhead or end playback.
    rig.node.post({ type: 'anchor', frame: 40_000, time: 0.9, generation: 0 })
    rig.node.post({ type: 'ended', generation: 0 })
    expect(rig.transport.position).toBe(24_000)
    expect(rig.transport.currentState).toBe('seeking')

    rig.node.post({ type: 'data', frames: 1000, generation: 1 })
    expect(rig.transport.currentState).toBe('playing')
  })

  it('seek before playback parks the position and starts from it', async () => {
    const rig = makeRig()
    await load(rig)

    rig.transport.seek(12_000)
    expect(rig.transport.currentState).toBe('unloaded')
    expect(rig.transport.position).toBe(12_000)
    expect(rig.contextFactoryCalls).toBe(0)

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
    expect(rig.node.posted('seek')).toEqual([{ type: 'seek', frame: 0, generation: 1 }])
    expect(rig.transport.currentState).toBe('preparing')
  })

  it('enters buffering on underrun and returns to playing on data', async () => {
    const rig = makeRig()
    await ready(rig)

    rig.node.post({ type: 'underrun', generation: 0 })
    expect(rig.transport.currentState).toBe('buffering')
    rig.node.post({ type: 'data', frames: 100, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
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
    const rig = makeRig(async () => {
      throw new Error('boom')
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
    rig.node.post({ type: 'data', frames: 1, generation: 0 })
    rig.node.post({ type: 'anchor', frame: 9999, time: 0.5, generation: 0 })
    expect(rig.transport.currentState).toBe('playing')
    const before = rig.transport.position
    expect(rig.transport.position).toBe(before)
  })
})
