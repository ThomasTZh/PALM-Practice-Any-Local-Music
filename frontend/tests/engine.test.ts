import { describe, expect, it } from 'vitest'
import {
  PlaybackEngine,
  type AudioBufferLike,
  type AudioBufferSourceLike,
  type AudioContextLike,
  type EngineTarget,
} from '../src/playback/engine'
import { f32leBytes } from './helpers/pcm-fixture'

class FakeBuffer implements AudioBufferLike {
  duration: number
  numberOfChannels: number
  sampleRate: number
  private readonly data: Float32Array[]

  constructor(numberOfChannels: number, length: number, sampleRate: number) {
    this.numberOfChannels = numberOfChannels
    this.sampleRate = sampleRate
    this.duration = length / sampleRate
    this.data = Array.from({ length: numberOfChannels }, () => new Float32Array(length))
  }

  getChannelData(channel: number): Float32Array {
    return this.data[channel]
  }
}

class FakeSource implements AudioBufferSourceLike {
  buffer: AudioBufferLike | null = null
  onended: (() => void) | null = null
  startedAt: number | null = null
  stoppedAt: number | null = null
  private readonly ctx: FakeContext

  constructor(ctx: FakeContext) {
    this.ctx = ctx
  }

  connect(): void {}

  start(when?: number): void {
    this.startedAt = when ?? this.ctx.currentTime
  }

  stop(when?: number): void {
    this.stoppedAt = when ?? this.ctx.currentTime
  }
}

class FakeContext implements AudioContextLike {
  currentTime = 0
  sampleRate = 48000
  state: 'suspended' | 'running' | 'closed' = 'running'
  readonly destination = {}
  readonly sources: FakeSource[] = []
  closed = false

  resume(): Promise<void> {
    this.state = 'running'
    return Promise.resolve()
  }

  close(): Promise<void> {
    this.state = 'closed'
    this.closed = true
    return Promise.resolve()
  }

  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    return new FakeBuffer(channels, length, sampleRate)
  }

  createBufferSource(): AudioBufferSourceLike {
    const source = new FakeSource(this)
    this.sources.push(source)
    return source
  }
}

interface DelayControl {
  delay: (ms: number) => Promise<void>
  release: () => void
}

/** A delay that parks the scheduler until the test releases it. */
function controlledDelay(): DelayControl {
  let resolve: (() => void) | null = null
  return {
    delay: (_ms: number) => new Promise<void>((r) => (resolve = r)),
    release: () => {
      const r = resolve
      resolve = null
      r?.()
    },
  }
}

function makeTarget(overrides: Partial<EngineTarget> = {}): EngineTarget {
  const frameCount = overrides.frameCount ?? 60
  const channelCount = overrides.channelCount ?? 2
  return {
    assetId: 'asset-1',
    sampleRate: 48000,
    channelCount,
    frameCount,
    byteCount: frameCount * 4 * channelCount,
    durationSeconds: frameCount / 48000,
    ...overrides,
  }
}

interface EngineHarness {
  engine: PlaybackEngine
  ctx: FakeContext
  delay: DelayControl
  fetchCalls: Array<[number, number]>
  states: string[]
  positions: number[]
}

function makeEngine(
  opts: {
    target?: Partial<EngineTarget>
    fetched?: (start: number, end: number) => Promise<ArrayBuffer>
    projectRate?: number
    projectDurationFrames?: number
    chunkBytes?: number
  } = {},
): EngineHarness {
  const ctx = new FakeContext()
  const delayControl = controlledDelay()
  const target = makeTarget(opts.target)
  const fullBytes = f32leBytes(target.frameCount, target.channelCount)
  const fetchCalls: Array<[number, number]> = []
  const states: string[] = []
  const positions: number[] = []
  const fetched =
    opts.fetched ??
    ((start: number, end: number) => {
      fetchCalls.push([start, end])
      return Promise.resolve(fullBytes.slice(start, end + 1))
    })
  const engine = new PlaybackEngine({
    target,
    projectRate: opts.projectRate ?? 44100,
    projectDurationFrames: opts.projectDurationFrames ?? 55,
    fetchChunk: fetched,
    context: ctx,
    chunkBytes: opts.chunkBytes ?? 160, // 20 frames per chunk at stereo f32
    delay: delayControl.delay,
    onState: (s) => states.push(s),
    onPosition: (p) => positions.push(p),
  })
  return { engine, ctx, delay: delayControl, fetchCalls, states, positions }
}

async function flush(): Promise<void> {
  // Let pending microtasks (start, scheduler loop, fetch) settle.
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('PlaybackEngine', () => {
  it('starts and schedules only the lookahead, then more on demand', async () => {
    // 4.425 s file; each chunk is 1.475 s so one chunk barely fills the
    // 1.5 s lookahead.
    const { engine, ctx, delay, fetchCalls, states } = makeEngine({
      target: { frameCount: 212400 },
      projectDurationFrames: 187635,
      chunkBytes: 566400, // 70800 frames * 8 bytes
    })
    expect(engine.currentState).toBe('idle')

    await engine.start()
    await flush()
    expect(engine.currentState).toBe('playing')
    expect(states).toEqual(['loading', 'playing'])
    // First chunk (1.475 s) is scheduled; the lookahead is now full.
    expect(ctx.sources).toHaveLength(1)
    expect(ctx.sources[0].startedAt).toBeCloseTo(0.05)
    expect(fetchCalls).toEqual([[0, 566399]])

    ctx.currentTime = 1.0
    delay.release()
    await flush()
    expect(ctx.sources).toHaveLength(2)
    expect(fetchCalls[1]).toEqual([566400, 1132799])

    ctx.currentTime = 2.5
    delay.release()
    await flush()
    expect(ctx.sources).toHaveLength(3)
    expect(fetchCalls[2]).toEqual([1132800, 1699199])

    engine.stop()
    expect(engine.currentState).toBe('stopped')
    expect(engine.currentOffset).toBe(0)
    expect(ctx.sources[0].stoppedAt).not.toBeNull()
  })

  it('pauses at the playhead and resumes from the same offset', async () => {
    // 2.0 s file, 1.5 s chunks so the first pass schedules exactly one chunk.
    const { engine, ctx, delay, fetchCalls } = makeEngine({
      target: { frameCount: 96000 },
      chunkBytes: 576000, // 72000 frames * 8 bytes = 1.5 s
    })
    await engine.start()
    await flush()
    expect(ctx.sources).toHaveLength(1) // one 1.5 s chunk fills the lookahead

    // Play exactly 0.5 s (24000 frames) past the start delay.
    ctx.currentTime = 0.05 + 0.5
    await engine.pause()
    expect(engine.currentState).toBe('paused')
    expect(engine.currentOffset).toBe(24000)

    await engine.resume()
    expect(engine.currentState).toBe('playing')
    // Resumes scheduling from the paused offset (remaining 1.5 s).
    delay.release()
    await flush()
    const resumed = ctx.sources[1]
    expect(resumed.startedAt).toBeCloseTo(ctx.currentTime + 0.05)
    expect(resumed.buffer?.duration).toBeCloseTo(1.5)
    expect(fetchCalls[1][0]).toBe(24000 * 8)

    engine.stop()
    expect(engine.currentState).toBe('stopped')
  })

  it('reports the position in project frames', async () => {
    const { engine, ctx } = makeEngine({
      target: { frameCount: 96000 },
      projectDurationFrames: 44100,
    })
    await engine.start()
    await flush()

    // One second of 48 kHz asset time = 44100 project frames.
    ctx.currentTime = 0.05 + 1.0
    expect(engine.currentOffset).toBe(48000)
    expect(engine.currentProjectFrame).toBe(44100) // clamped to project duration
  })

  it('reports the end position when media finishes naturally', async () => {
    const { engine, ctx, positions } = makeEngine()
    await engine.start()
    await flush()
    // The 1.25 ms file is shorter than the lookahead: all 3 chunks
    // schedule in the first pass.
    expect(ctx.sources).toHaveLength(3)

    ctx.currentTime = 1.0
    ctx.sources[2].onended?.()
    expect(engine.currentState).toBe('stopped')
    expect(engine.currentOffset).toBe(60)
    expect(engine.currentProjectFrame).toBe(55)
    expect(positions.at(-1)).toBe(55)
  })

  it('seeks while paused and resumes from the new offset', async () => {
    const { engine, ctx } = makeEngine({
      target: { frameCount: 96000 },
      projectDurationFrames: 44100,
    })
    await engine.start()
    await flush()
    ctx.currentTime = 0.55
    await engine.pause()

    await engine.seek(48000)
    expect(engine.currentState).toBe('paused')
    expect(engine.currentOffset).toBe(48000)
    expect(engine.currentProjectFrame).toBe(44100)

    await engine.resume()
    // The position catches up once the 0.05 s start delay elapses.
    ctx.currentTime += 0.05
    expect(engine.currentOffset).toBe(48000)
  })

  it('seeks while stopped and starts from the parked position', async () => {
    const { engine, ctx, delay, positions } = makeEngine({
      target: { frameCount: 96000 },
      projectDurationFrames: 44100,
      chunkBytes: 576000, // 72000 frames = 1.5 s per chunk
    })
    await engine.start()
    await flush()
    engine.stop()
    expect(engine.currentOffset).toBe(0)

    await engine.seek(48000)
    expect(engine.currentState).toBe('stopped')
    expect(engine.currentOffset).toBe(48000)
    expect(positions.at(-1)).toBe(44100)

    // start() plays from the seeked position, not from zero. The
    // scheduler parked in the first pass resumes and reschedules.
    const t = ctx.currentTime
    await engine.start()
    delay.release()
    await flush()
    const last = ctx.sources.at(-1)
    expect(last?.startedAt).toBeCloseTo(t + 0.05)
    expect(last?.buffer?.duration).toBeCloseTo((96000 - 48000) / 48000)
    ctx.currentTime = t + 0.05 // start delay elapsed
    expect(engine.currentOffset).toBe(48000)
  })

  it('seeks while playing: stops sources and reschedules from the offset', async () => {
    const { engine, ctx, delay, fetchCalls } = makeEngine({
      target: { frameCount: 96000 },
      chunkBytes: 576000, // 72000 frames = 1.5 s per chunk
    })
    await engine.start()
    await flush()
    expect(ctx.sources).toHaveLength(1)

    ctx.currentTime = 0.3
    await engine.seek(24000)
    expect(ctx.sources[0].stoppedAt).not.toBeNull()

    // The rescheduled audio begins at ctx.currentTime + the start delay.
    ctx.currentTime = 0.35
    delay.release()
    await flush()
    const last = ctx.sources.at(-1)
    expect(ctx.sources).toHaveLength(2)
    expect(last?.startedAt).toBeCloseTo(0.35)
    expect(last?.buffer?.duration).toBeCloseTo(1.5)
    expect(fetchCalls.at(-1)?.[0]).toBe(24000 * 8)
    expect(engine.currentOffset).toBe(24000)
  })

  it('clamps seeks to the media bounds', async () => {
    const { engine } = makeEngine({ target: { frameCount: 96000 } })
    await engine.seek(-500)
    expect(engine.currentState).toBe('stopped') // idle -> stopped, position observable
    expect(engine.currentOffset).toBe(0)
    await engine.seek(10_000_000)
    expect(engine.currentOffset).toBe(96000)
  })

  it('enters the error state when a chunk fetch fails', async () => {
    const { engine } = makeEngine({
      fetched: () => Promise.reject(new Error('network down')),
    })
    await engine.start()
    await flush()
    expect(engine.currentState).toBe('error')
    expect(engine.currentError).toBe('network down')
  })

  it('dispose closes a context the engine created', async () => {
    const ctx = new FakeContext()
    const engine = new PlaybackEngine({
      target: makeTarget(),
      projectRate: 44100,
      projectDurationFrames: 55,
      fetchChunk: (start, end) => {
        const n = end - start + 1
        const buf = new ArrayBuffer(n)
        new Float32Array(buf).fill(0.25)
        return Promise.resolve(buf)
      },
      createContext: () => ctx,
    })
    await engine.start()
    await flush()
    await engine.dispose()
    expect(ctx.closed).toBe(true)
    expect(engine.currentState).toBe('stopped')
  })
})
