/**
 * Playback engine (M1.7).
 *
 * Plays a resolved PCM asset through the Web Audio API:
 *
 *  - owns an AudioContext (created lazily from a user gesture);
 *  - fetches the asset in ranged byte chunks and builds an AudioBuffer
 *    per chunk (the browser has no raw-PCM decoder);
 *  - schedules back-to-back AudioBufferSourceNodes on a lookahead
 *    timer for gapless playback;
 *  - supports play / pause / resume / stop and reports the position in
 *    project (canonical) frames.
 *
 * The AudioContext and the byte fetcher are injectable so the engine
 * is fully testable without a browser audio stack.
 */

import { clampToDuration, deinterleaveF32le, projectPosition } from './pcm'

export type EngineState = 'idle' | 'loading' | 'playing' | 'paused' | 'stopped' | 'error'

export interface AudioBufferLike {
  duration: number
  numberOfChannels: number
  sampleRate: number
  getChannelData(channel: number): Float32Array
}

export interface AudioBufferSourceLike {
  buffer: AudioBufferLike | null
  connect(destination: unknown): void
  start(when?: number): void
  stop(when?: number): void
  onended: (() => void) | null
}

export interface AudioContextLike {
  readonly currentTime: number
  readonly sampleRate: number
  readonly state: 'suspended' | 'running' | 'closed'
  readonly destination: unknown
  resume(): Promise<void>
  close(): Promise<void>
  createBuffer(numberOfChannels: number, length: number, sampleRate: number): AudioBufferLike
  createBufferSource(): AudioBufferSourceLike
}

export interface EngineTarget {
  assetId: string
  sampleRate: number
  channelCount: number
  frameCount: number
  byteCount: number
  durationSeconds: number
}

export interface EngineOptions {
  target: EngineTarget
  /** Canonical (project) sample rate, for position mapping. */
  projectRate: number
  /** Canonical (project) duration in frames, for position clamping. */
  projectDurationFrames: number
  /** Fetch an inclusive byte range of the asset. */
  fetchChunk: (start: number, end: number) => Promise<ArrayBuffer>
  /** Injected context; when omitted, `createContext` is used. */
  context?: AudioContextLike | null
  createContext?: () => AudioContextLike
  /** Ranged-fetch size in bytes (default 4 MiB). */
  chunkBytes?: number
  /** Scheduler idle delay; injectable for tests (default 150 ms). */
  delay?: (ms: number) => Promise<void>
  onState?: (state: EngineState) => void
  onPosition?: (projectFrame: number) => void
}

const DEFAULT_CHUNK_BYTES = 4 * 1024 * 1024
const LOOKAHEAD_SECONDS = 1.5
const SCHEDULER_INTERVAL_MS = 150
const START_DELAY_SECONDS = 0.05

function defaultDelay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export class PlaybackEngine {
  private readonly opts: EngineOptions
  private readonly rate: number
  private readonly channelCount: number
  private readonly frameCount: number
  private readonly bytesPerFrame: number
  private readonly chunkFrames: number

  private context: AudioContextLike | null = null
  private ownsContext = false
  private state: EngineState = 'idle'
  private lastError: string | null = null

  private playStartTime = 0
  private playStartOffset = 0
  private scheduledUntil = 0
  private sources = new Set<AudioBufferSourceLike>()
  private schedulerRunning = false
  private endReached = false

  constructor(opts: EngineOptions) {
    this.opts = opts
    this.rate = opts.target.sampleRate
    this.channelCount = opts.target.channelCount
    this.frameCount = opts.target.frameCount
    this.bytesPerFrame = 4 * this.channelCount
    this.chunkFrames = Math.max(
      1,
      Math.floor((opts.chunkBytes ?? DEFAULT_CHUNK_BYTES) / this.bytesPerFrame),
    )
  }

  get currentState(): EngineState {
    return this.state
  }

  get currentError(): string | null {
    return this.lastError
  }

  /** The asset offset currently at the playhead (clamped). */
  get currentOffset(): number {
    if (this.state === 'playing' || this.state === 'loading') {
      const ctx = this.context
      if (!ctx) return 0
      const offset = this.playStartOffset + (ctx.currentTime - this.playStartTime) * this.rate
      return clampToDuration(offset, this.frameCount)
    }
    if (this.state === 'paused') return this.playStartOffset
    if (this.state === 'stopped') return this.endReached ? this.frameCount : 0
    return 0
  }

  /** The playhead mapped into project (canonical) frames. */
  get currentProjectFrame(): number {
    const mapped = projectPosition(this.currentOffset, this.opts.projectRate, this.rate)
    return clampToDuration(mapped, this.opts.projectDurationFrames)
  }

  async start(): Promise<void> {
    if (this.state === 'playing' || this.state === 'loading') return
    this.setState('loading')
    this.lastError = null
    this.endReached = false
    try {
      await this.ensureContext()
      this.playStartOffset = 0
      this.scheduledUntil = 0
      this.playStartTime = this.context!.currentTime + START_DELAY_SECONDS
      this.setState('playing')
      void this.schedulerLoop()
    } catch (err) {
      this.fail(err)
    }
  }

  async pause(): Promise<void> {
    if (this.state !== 'playing') return
    const offset = Math.floor(this.currentOffset)
    this.stopAllSources()
    this.playStartOffset = offset
    this.scheduledUntil = offset
    this.setState('paused')
    this.reportPosition()
  }

  async resume(): Promise<void> {
    if (this.state !== 'paused') return
    this.playStartTime = this.context!.currentTime + START_DELAY_SECONDS
    this.setState('playing')
    this.reportPosition()
    void this.schedulerLoop()
  }

  stop(): void {
    this.stopAllSources()
    this.playStartOffset = 0
    this.scheduledUntil = 0
    this.endReached = false
    if (this.state !== 'idle') {
      this.setState('stopped')
      this.reportPosition()
    }
  }

  /** Stop playback and release the AudioContext we created. */
  async dispose(): Promise<void> {
    this.stop()
    if (this.ownsContext && this.context) {
      const ctx = this.context
      this.context = null
      this.ownsContext = false
      try {
        await ctx.close()
      } catch {
        // Closing an already-closed context is not an error we surface.
      }
    }
  }

  private async ensureContext(): Promise<void> {
    if (this.context) {
      if (this.context.state === 'suspended') await this.context.resume()
      return
    }
    if (this.opts.context) {
      this.context = this.opts.context
      this.ownsContext = false
    } else {
      const create =
        this.opts.createContext ??
        (() => new AudioContext() as unknown as AudioContextLike)
      this.context = create()
      this.ownsContext = true
    }
    if (this.context.state === 'suspended') await this.context.resume()
  }

  private async schedulerLoop(): Promise<void> {
    if (this.schedulerRunning) return
    this.schedulerRunning = true
    const delay = this.opts.delay ?? defaultDelay
    try {
      while (this.state === 'playing') {
        try {
          await this.scheduleAhead()
        } catch (err) {
          this.fail(err)
          return
        }
        if (this.state !== 'playing') return
        this.reportPosition()
        await delay(SCHEDULER_INTERVAL_MS)
      }
    } finally {
      this.schedulerRunning = false
    }
  }

  /** Fetch and schedule chunks until the lookahead is filled. */
  private async scheduleAhead(): Promise<void> {
    const ctx = this.context!
    while (this.state === 'playing' && this.scheduledUntil < this.frameCount) {
      const secondsScheduled = this.timeFor(this.scheduledUntil) - ctx.currentTime
      if (secondsScheduled >= LOOKAHEAD_SECONDS) return
      const frames = Math.min(this.chunkFrames, this.frameCount - this.scheduledUntil)
      const start = this.scheduledUntil * this.bytesPerFrame
      const end = start + frames * this.bytesPerFrame - 1
      const bytes = await this.opts.fetchChunk(start, end)
      this.scheduleChunk(bytes, frames, this.scheduledUntil)
      this.scheduledUntil += frames
    }
  }

  private scheduleChunk(bytes: ArrayBuffer, frames: number, offset: number): void {
    const ctx = this.context!
    const buffer = ctx.createBuffer(this.channelCount, frames, this.rate)
    const channels = deinterleaveF32le(bytes, this.channelCount)
    for (let c = 0; c < this.channelCount; c++) {
      buffer.getChannelData(c).set(channels[c])
    }
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    source.start(this.timeFor(offset))
    this.sources.add(source)
    if (this.scheduledUntil + frames >= this.frameCount) {
      source.onended = () => this.handleSourceEnded(source)
    } else {
      // Drop finished sources so the set stays bounded.
      source.onended = () => this.sources.delete(source)
    }
  }

  private handleSourceEnded(source: AudioBufferSourceLike): void {
    this.sources.delete(source)
    if (this.state === 'playing' && this.scheduledUntil >= this.frameCount) {
      // Media finished naturally: the playhead sits at the end.
      this.endReached = true
      this.playStartOffset = this.frameCount
      this.stopAllSources()
      this.setState('stopped')
      this.reportPosition()
    }
  }

  private stopAllSources(): void {
    for (const source of this.sources) {
      source.onended = null
      try {
        source.stop()
      } catch {
        // Already stopped; nothing to do.
      }
    }
    this.sources.clear()
  }

  private timeFor(offset: number): number {
    return this.playStartTime + (offset - this.playStartOffset) / this.rate
  }

  private setState(state: EngineState): void {
    if (this.state === state) return
    this.state = state
    this.opts.onState?.(state)
  }

  private reportPosition(): void {
    this.opts.onPosition?.(this.currentProjectFrame)
  }

  private fail(err: unknown): void {
    this.lastError = err instanceof Error ? err.message : String(err)
    this.stopAllSources()
    this.setState('error')
  }
}
