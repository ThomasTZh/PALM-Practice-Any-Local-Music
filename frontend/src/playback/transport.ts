/**
 * AudioWorklet PCM transport (M1.12, spec §14).
 *
 * Replaces the `AudioBufferSourceNode` scheduling engine (M1.7): the
 * worklet (`worklet-processor.js`) consumes a bounded ring of f32le PCM
 * on the audio thread; this class owns everything on the main thread —
 * the eight transport states plus `desiredPlaying`, chunked prefetch
 * (~1 s network chunks, 2 s prebuffer target), seek generations,
 * anchor-based position extrapolation, and the monitoring gain stage
 * that sits after the worklet (canonical samples are never modified).
 *
 * The context factory, byte fetcher, and delay are injectable so the
 * transport is fully testable without a browser audio stack (see
 * `tests/transport.test.ts`).
 */

import { clampToDuration, playbackPosition, projectPosition } from './pcm'
import type { PlaybackTarget } from '../api/playback'
import processorSource from './worklet-processor.js?raw'

export type TransportState =
  'unloaded' | 'preparing' | 'paused' | 'playing' | 'seeking' | 'buffering' | 'ended' | 'error'

/** Structural subset of a worklet node's message port. */
export interface WorkletPortLike {
  postMessage(message: unknown, transfer?: Transferable[]): void
  onmessage: ((event: { data: unknown }) => void) | null
}

export interface WorkletNodeLike {
  port: WorkletPortLike
  connect(destination: unknown): void
  disconnect(): void
}

export interface GainParamLike {
  value: number
  setTargetAtTime(target: number, startTime: number, timeConstant: number): void
}

export interface GainNodeLike {
  gain: GainParamLike
  connect(destination: unknown): void
  disconnect(): void
}

/** Structural subset of the `AudioContext` the transport drives. */
export interface TransportContextLike {
  currentTime: number
  sampleRate: number
  state: string
  destination: unknown
  audioWorklet: { addModule(url: string): Promise<void> }
  createWorkletNode(name: string, options?: Record<string, unknown>): WorkletNodeLike
  createGain(): GainNodeLike
  resume(): Promise<void>
  close(): Promise<void>
}

export interface TransportOptions {
  contextFactory: () => TransportContextLike
  /** Fetch one inclusive byte range of the asset's interleaved f32le PCM. */
  fetchChunk: (startByte: number, endByte: number, signal?: AbortSignal) => Promise<ArrayBuffer>
  /**
   * Injectable delay for the prefetch loop; must settle early when
   * `signal` aborts (a seek/stop). Defaults to an abort-aware setTimeout.
   */
  delay?: (ms: number, signal?: AbortSignal) => Promise<void>
  /**
   * Build the worklet module URL from the processor source. Defaults to a
   * Blob URL; tests inject a stub (jsdom has no URL.createObjectURL).
   */
  moduleUrlFactory?: (source: string) => string
  onState?: (state: TransportState) => void
  /** Reports the playhead position in project frames. */
  onPosition?: (frame: number) => void
}

export interface LoadSourceOptions {
  target: PlaybackTarget
  projectRate: number
  projectDurationFrames: number
}

const PREBUFFER_SECONDS = 2
const CHUNK_SECONDS = 1
const FILL_CHECK_MS = 50
const MAX_GAIN = 4
const GAIN_RAMP_TIME_CONSTANT = 0.01

export class PcmTransport {
  private state: TransportState = 'unloaded'
  /** Kept separate from the actual state so seeks and underruns can
   * temporarily pause output without losing user intent (spec §14.3). */
  private desiredPlaying = false
  private readonly opts: TransportOptions
  private readonly delay: (ms: number, signal?: AbortSignal) => Promise<void>

  private target: PlaybackTarget | null = null
  private projectRate = 0
  private projectDurationFrames = 0
  /** Position park (project frames) before any source is loaded. */
  private parkedProjectFrame = 0

  private context: TransportContextLike | null = null
  private node: WorkletNodeLike | null = null
  private gainNode: GainNodeLike | null = null
  private blobUrl: string | null = null
  private pendingGain = 1

  /** Bumped on every seek/stop so stale fetches and port messages drop. */
  private generation = 0
  private abort: AbortController | null = null
  private genStartFrame = 0
  private fetchedFrame = 0
  /** Last acknowledged anchor frame (playback frames). */
  private consumedFrame = 0
  /** Context time of the last anchor. */
  private anchorTime = 0
  /** The worklet ring currently holds samples. */
  private hasData = false
  private fillLoopRunning = false
  private disposed = false
  private lastError: string | null = null

  constructor(opts: TransportOptions) {
    this.opts = opts
    this.delay =
      opts.delay ??
      ((ms: number, signal?: AbortSignal) =>
        new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, ms)
          signal?.addEventListener(
            'abort',
            () => {
              clearTimeout(timer)
              resolve()
            },
            { once: true },
          )
        }))
  }

  get currentState(): TransportState {
    return this.state
  }

  get currentError(): string | null {
    return this.lastError
  }

  /** Current playhead position in project frames. */
  get position(): number {
    if (!this.target) return this.parkedProjectFrame
    const rate = this.target.sampleRate
    let playbackFrame = this.consumedFrame
    if (
      this.context &&
      (this.state === 'playing' || this.state === 'seeking' || this.state === 'buffering')
    ) {
      // Extrapolate from the last anchor to the current context time.
      playbackFrame =
        this.consumedFrame + Math.max(0, this.context.currentTime - this.anchorTime) * rate
    }
    if (this.state === 'ended') playbackFrame = this.target.frameCount
    return clampToDuration(
      projectPosition(playbackFrame, this.projectRate, rate),
      this.projectDurationFrames,
    )
  }

  /**
   * Bind the playback representation to this transport. No audio graph is
   * created yet; `play` does that on a user gesture (spec §14.4).
   */
  async loadSource({
    target,
    projectRate,
    projectDurationFrames,
  }: LoadSourceOptions): Promise<void> {
    this.target = target
    this.projectRate = projectRate
    this.projectDurationFrames = projectDurationFrames
  }

  /** Start (or resume) playback from the current position. */
  async play(): Promise<void> {
    if (this.disposed || !this.target) return
    if (this.state === 'playing' || this.state === 'preparing' || this.state === 'seeking') {
      return
    }
    this.desiredPlaying = true
    this.lastError = null
    if (this.state === 'unloaded' || this.state === 'error') {
      this.setState('preparing')
      try {
        await this.initGraph()
      } catch (err) {
        this.fail(err)
        return
      }
    }
    if (this.state === 'ended') {
      this.flushTo(0)
    }
    this.node?.port.postMessage({ type: 'resume' })
    if (this.hasData) {
      this.setState('playing')
    } else if (this.state !== 'buffering') {
      this.setState('preparing')
    }
    void this.runFill()
  }

  /** Pause: ramp out, stop consumption, preserve the acknowledged position. */
  pause(): void {
    if (this.disposed) return
    if (
      this.state === 'unloaded' ||
      this.state === 'paused' ||
      this.state === 'ended' ||
      this.state === 'error'
    ) {
      return
    }
    this.desiredPlaying = false
    if (this.context && this.target) {
      // Freeze the playhead at the position extrapolated right now.
      this.consumedFrame +=
        Math.max(0, this.context.currentTime - this.anchorTime) * this.target.sampleRate
      this.anchorTime = this.context.currentTime
    }
    this.node?.port.postMessage({ type: 'pause' })
    this.abort?.abort()
    this.setState('paused')
    this.reportPosition()
  }

  /** Stop: pause semantics plus reset to zero (spec §14.5). */
  stop(): void {
    if (this.disposed) return
    this.desiredPlaying = false
    this.flushTo(0)
    this.setState('paused')
    this.reportPosition()
  }

  /**
   * Seek to a project frame. While playing this flushes the worklet,
   * aborts in-flight fetches, and refills (state `seeking`); otherwise it
   * only moves the playhead (M1.11 click-to-seek behavior).
   */
  seek(projectFrame: number): void {
    if (this.disposed) return
    if (!this.target) {
      this.parkedProjectFrame = Math.max(
        0,
        Math.min(Math.floor(projectFrame), this.projectDurationFrames),
      )
      this.reportPosition()
      return
    }
    const target = this.target
    const frame = clampToDuration(
      playbackPosition(projectFrame, this.projectRate, target.sampleRate),
      target.frameCount,
    )
    const wasPlaying = this.desiredPlaying
    this.flushTo(frame)
    if (wasPlaying && this.state !== 'unloaded') {
      this.setState('seeking')
      void this.runFill()
    } else if (
      this.state === 'playing' ||
      this.state === 'buffering' ||
      this.state === 'preparing' ||
      this.state === 'seeking'
    ) {
      this.setState('paused')
      this.reportPosition()
    }
  }

  /**
   * Set the monitoring output gain (clamped to [0, 4]) with a short ramp.
   * Canonical samples are untouched: the gain sits after the worklet.
   */
  setOutputGain(gain: number): void {
    const clamped = Math.max(0, Math.min(MAX_GAIN, Number.isFinite(gain) ? gain : 0))
    this.pendingGain = clamped
    if (this.gainNode && this.context) {
      this.gainNode.gain.setTargetAtTime(clamped, this.context.currentTime, GAIN_RAMP_TIME_CONSTANT)
    }
  }

  /** Tear down the graph and release the context and Blob URL. */
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.desiredPlaying = false
    this.abort?.abort()
    try {
      this.node?.port.postMessage({ type: 'dispose' })
      this.node?.disconnect()
      this.gainNode?.disconnect()
    } catch {
      // The graph may already be gone.
    }
    if (this.context) {
      void this.context.close().catch(() => {})
    }
    if (this.blobUrl?.startsWith('blob:')) {
      URL.revokeObjectURL(this.blobUrl)
    }
    this.blobUrl = null
    this.node = null
    this.gainNode = null
    this.context = null
  }

  /** Create context, worklet node, and gain stage (user-gesture path). */
  private async initGraph(): Promise<void> {
    const target = this.target
    if (!target) throw new Error('No source loaded')
    const context = this.opts.contextFactory()
    if (context.state === 'suspended') await context.resume()
    this.context = context
    this.blobUrl = this.opts.moduleUrlFactory
      ? this.opts.moduleUrlFactory(processorSource)
      : URL.createObjectURL(new Blob([processorSource], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(this.blobUrl)
    const node = context.createWorkletNode('basseparate-pcm', {
      processorOptions: {
        sampleRate: target.sampleRate,
        channelCount: target.channelCount,
        frameCount: target.frameCount,
      },
    })
    node.port.onmessage = (e) => this.handleWorkletMessage(e.data)
    const gainNode = context.createGain()
    gainNode.gain.value = this.pendingGain
    node.connect(gainNode)
    gainNode.connect(context.destination)
    this.node = node
    this.gainNode = gainNode
    this.abort = new AbortController()
    this.anchorTime = context.currentTime
  }

  /**
   * Reset fetch and position bookkeeping to `playbackFrame` and tell the
   * worklet to flush. Bumps the generation so everything from the old
   * generation (fetches, port messages) is dropped.
   */
  private flushTo(playbackFrame: number): void {
    const target = this.target
    if (!target) return
    this.generation += 1
    this.abort?.abort()
    this.abort = new AbortController()
    const frame = Math.max(0, Math.min(Math.floor(playbackFrame), target.frameCount))
    this.genStartFrame = frame
    this.fetchedFrame = frame
    this.consumedFrame = frame
    this.hasData = false
    if (this.context) this.anchorTime = this.context.currentTime
    this.node?.port.postMessage({ type: 'seek', frame, generation: this.generation })
  }

  private handleWorkletMessage(data: unknown): void {
    if (this.disposed) return
    if (typeof data !== 'object' || data === null) return
    const msg = data as { type: string; generation?: number }
    if (typeof msg.generation === 'number' && msg.generation !== this.generation) return
    switch (msg.type) {
      case 'data':
        this.hasData = true
        if (
          this.desiredPlaying &&
          (this.state === 'preparing' || this.state === 'seeking' || this.state === 'buffering')
        ) {
          this.setState('playing')
        }
        break
      case 'anchor': {
        const m = msg as { type: string; frame: number; time: number }
        this.consumedFrame = m.frame
        this.anchorTime = m.time
        this.reportPosition()
        break
      }
      case 'underrun':
        if (this.desiredPlaying && this.state === 'playing') this.setState('buffering')
        break
      case 'ended':
        this.desiredPlaying = false
        this.setState('ended')
        this.reportPosition()
        break
      default:
        // 'flushed' and 'dispose' need no main-thread action.
        break
    }
  }

  /**
   * Prefetch loop: keep the worklet ring filled to the target ahead of the
   * estimated consumed position. A single loop outlives generation bumps:
   * a seek/stop aborts in-flight fetches and the parking delay, the loop
   * wakes, and refetches from the new bookkeeping. Runs while
   * `desiredPlaying` and the state is active.
   */
  private async runFill(): Promise<void> {
    if (this.fillLoopRunning || this.disposed) return
    this.fillLoopRunning = true
    try {
      while (!this.disposed && this.desiredPlaying && this.node && this.target) {
        const s = this.state
        if (s !== 'preparing' && s !== 'playing' && s !== 'buffering' && s !== 'seeking') return
        const target = this.target
        const rate = target.sampleRate
        const bytesPerFrame = 4 * target.channelCount
        const consumedEstimate =
          this.consumedFrame +
          (this.context ? Math.max(0, this.context.currentTime - this.anchorTime) * rate : 0)
        const targetAhead = Math.max(
          rate * PREBUFFER_SECONDS,
          target.frameCount - this.genStartFrame,
        )
        let fetched = false
        while (
          this.fetchedFrame < target.frameCount &&
          this.fetchedFrame - consumedEstimate < targetAhead
        ) {
          const frames = Math.min(rate * CHUNK_SECONDS, target.frameCount - this.fetchedFrame)
          const start = Math.floor(this.fetchedFrame * bytesPerFrame)
          const end = start + frames * bytesPerFrame - 1
          const gen = this.generation
          let bytes: ArrayBuffer
          try {
            bytes = await this.opts.fetchChunk(start, end, this.abort?.signal)
          } catch (err) {
            if (
              (err instanceof DOMException && err.name === 'AbortError') ||
              gen !== this.generation
            ) {
              break // generation bump: re-evaluate with the new bookkeeping
            }
            this.fail(err)
            return
          }
          if (gen !== this.generation) break // completed after a seek: stale
          this.node.port.postMessage({ type: 'samples', buffer: bytes }, [bytes])
          this.fetchedFrame += frames
          fetched = true
        }
        if (this.fetchedFrame >= target.frameCount) return // 'ended' will arrive
        if (!fetched) await this.delay(FILL_CHECK_MS, this.abort?.signal)
        if (this.disposed) return
      }
    } finally {
      this.fillLoopRunning = false
    }
  }

  private fail(err: unknown): void {
    this.lastError = err instanceof Error ? err.message : String(err)
    this.desiredPlaying = false
    this.abort?.abort()
    this.setState('error')
  }

  private setState(next: TransportState): void {
    if (this.state === next) return
    this.state = next
    this.opts.onState?.(next)
  }

  private reportPosition(): void {
    this.opts.onPosition?.(this.position)
  }
}
