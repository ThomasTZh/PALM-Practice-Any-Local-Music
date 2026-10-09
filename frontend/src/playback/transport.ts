/**
 * AudioWorklet PCM transport (M1.12/M1.13, spec §14–15).
 *
 * Replaces the `AudioBufferSourceNode` scheduling engine (M1.7): the
 * worklet (`worklet-processor.js`) consumes a bounded ring of f32le PCM
 * on the audio thread; this class owns everything on the main thread —
 * the eight transport states plus `desiredPlaying`, chunked prefetch
 * (~1 s network chunks, 2 s prebuffer, 8 s steady lookahead, 12 s
 * total-retention budget), seek generations, anchor-based position
 * extrapolation, underrun diagnostics, browser-suspend tracking, and
 * the monitoring gain stage that sits after the worklet (canonical
 * samples are never modified).
 *
 * Two data paths (spec §15.1/§15.2), selected by `mode`:
 * - `shared`: cross-origin isolated; the fetch worker writes the shared
 *   SAB ring directly (SPSC, atomic indices).
 * - `transfer`: the fetch worker posts deinterleaved chunks transferred
 *   to the main thread, which relays them to the worklet's bounded queue.
 * Both fetch through a `FetchSource`: a real worker when available,
 * else the identical main-thread logic (jsdom has no `Worker`).
 *
 * The context factory, byte fetcher, worker factory, and delay are
 * injectable so the transport is fully testable without a browser audio
 * stack (see `tests/transport.test.ts`).
 */

import { clampToDuration, playbackPosition, projectPosition } from './pcm'
import type { PlaybackTarget } from '../api/playback'
import { createSharedRing, type SharedRing } from './pcm-fetch'
import {
  DirectFetchSource,
  StaleGenerationError,
  WorkerFetchSource,
  type FetchSource,
  type PcmChunk,
  type PcmWriteResult,
  type WorkerLike,
} from './fetch-source'
import processorSource from './worklet-processor.js?raw'

export type TransportState =
  'unloaded' | 'preparing' | 'paused' | 'playing' | 'seeking' | 'buffering' | 'ended' | 'error'

/** Data path selection; `auto` picks shared memory when isolated. */
export type TransportMode = 'auto' | 'shared' | 'transfer'

/** Underrun accounting surfaced to the panel (spec §15.4). */
export interface TransportDiagnostics {
  underruns: number
  lastUnderrunAt: number | null
  droppedChunks: number
}

/** Snapshot returned by `sync()` (spec §15.5). */
export interface SyncInfo {
  state: TransportState
  position: number
  isSuspended: boolean
  contextLost: boolean
}

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
  onstatechange: ((event: { type: string }) => void) | null
  destination: unknown
  audioWorklet: { addModule(url: string): Promise<void> }
  createWorkletNode(name: string, options?: Record<string, unknown>): WorkletNodeLike
  createGain(): GainNodeLike
  resume(): Promise<void>
  close(): Promise<void>
  /** Output-device timestamp (spec §16.2); absent in test fakes. */
  getOutputTimestamp?(): { contextTime: number; performanceTime: number } | null
}

export interface TransportOptions {
  contextFactory: () => TransportContextLike
  /** Fetch one inclusive byte range of the asset's interleaved f32le PCM. */
  fetchChunk: (
    assetId: string,
    startByte: number,
    endByte: number,
    signal?: AbortSignal,
  ) => Promise<ArrayBuffer>
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
  /**
   * Create the fetch worker; returning `null` selects the main-thread
   * fallback. Defaults to the Vite-bundled `fetch-worker.ts` when
   * `Worker` is available.
   */
  workerFactory?: () => WorkerLike | null
  /** Data path; `auto` picks shared memory when cross-origin isolated. */
  mode?: TransportMode
  onState?: (state: TransportState) => void
  /** Reports the playhead position in project frames. */
  onPosition?: (frame: number) => void
  /** Reports browser suspension of the audio context (spec §15.5). */
  onSuspend?: (suspended: boolean) => void
}

export interface LoadSourceOptions {
  target: PlaybackTarget
  projectRate: number
  projectDurationFrames: number
}

/**
 * A transport segment: generation `generation` started playing from
 * `startFrame` at context time `startContextTime` (spec §16.2.3).
 */
interface TransportSegment {
  startContextTime: number
  startFrame: number
  generation: number
}

/** §15.3 buffer budget: one 12 s retention cap per representation. */
const RING_SECONDS = 12
/** Initial prebuffer and post-underrun start threshold. */
const PREBUFFER_SECONDS = 2
/** Steady-state lookahead target. */
const LOOKAHEAD_SECONDS = 8
/** One network chunk. */
const CHUNK_SECONDS = 1
const FILL_CHECK_MS = 50
const MAX_GAIN = 4
const GAIN_RAMP_TIME_CONSTANT = 0.01
/**
 * §16.2.4 documented fallback: without `getOutputTimestamp()` the context
 * time is assumed to be the audible time (zero output latency).
 */
const FALLBACK_OUTPUT_LATENCY_SECONDS = 0
/** §16.2.3: recent segments retained for time → frame mapping. */
const MAX_SEGMENTS = 16

function defaultWorkerFactory(): WorkerLike | null {
  if (typeof Worker === 'undefined') return null
  // The DOM `Worker` matches the structural `WorkerLike` at runtime; the
  // `onmessage` signature differs only in the event type.
  return new Worker(new URL('./fetch-worker.ts', import.meta.url), {
    type: 'module',
  }) as unknown as WorkerLike
}

function resolveMode(requested: TransportMode): 'shared' | 'transfer' {
  if (requested === 'shared') return 'shared'
  if (requested === 'transfer') return 'transfer'
  const isolated = (globalThis as { crossOriginIsolated?: boolean }).crossOriginIsolated === true
  return isolated && typeof SharedArrayBuffer !== 'undefined' ? 'shared' : 'transfer'
}

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

  private mode: 'shared' | 'transfer' = 'transfer'
  private source: FetchSource | null = null
  /** Shared ring (shared path only); the SAB is owned by the worklet. */
  private ring: SharedRing | null = null

  /** Bumped on every seek/stop so stale fetches and port messages drop. */
  private generation = 0
  private abort: AbortController | null = null
  private genStartFrame = 0
  private fetchedFrame = 0
  /** Last acknowledged anchor frame (playback frames). */
  private consumedFrame = 0
  /** Context time of the last anchor. */
  private anchorTime = 0
  /** Recent segments for audible-time → frame mapping (spec §16.2.3). */
  private segments: TransportSegment[] = []
  /** Segment the last acknowledged anchor landed in (null before any). */
  private anchorSegment: TransportSegment | null = null
  /** The worklet ring/queue currently holds samples. */
  private hasData = false
  /** Worklet-reported buffered frames (ring + queue, or writer−reader). */
  private bufferedFrames = 0
  /** Flow control: the worker is paused while the budget is full. */
  private workerPaused = false
  /** The context is suspended (browser/tab suspension, spec §15.5). */
  private suspended = false
  /** The context closed under us (device change, spec §15.6). */
  contextLost = false
  /** Last acknowledged position, retained across context loss. */
  private retainedProjectFrame = 0
  /** Generation of the last worklet `flushed` acknowledgment. */
  private lastFlushedGeneration = -1
  private flushAckResolve: (() => void) | null = null
  private fillLoopRunning = false
  private disposed = false
  private lastError: string | null = null
  private diagnosticsState: TransportDiagnostics = {
    underruns: 0,
    lastUnderrunAt: null,
    droppedChunks: 0,
  }

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

  get isSuspended(): boolean {
    return this.suspended
  }

  get diagnostics(): TransportDiagnostics {
    return this.diagnosticsState
  }

  /**
   * Audible position in project frames (spec §16.2): the source frame at
   * the output device's current context time, mapped through the retained
   * transport segments. Extrapolation is frozen while paused, buffering,
   * suspended, or ended — the last acknowledged anchor is reported.
   */
  getAudiblePosition(): number {
    if (!this.target) return this.parkedProjectFrame
    // After context loss the graph (and its consumption tracking) is gone;
    // report the retained position until `rebind` resets the bookkeeping.
    if (this.contextLost) return this.retainedProjectFrame
    const rate = this.target.sampleRate
    const context = this.context
    let playbackFrame: number
    if (context && !this.suspended && (this.state === 'playing' || this.state === 'seeking')) {
      const ts = context.getOutputTimestamp ? context.getOutputTimestamp() : null
      const t = ts
        ? ts.contextTime
        : Math.max(0, context.currentTime - FALLBACK_OUTPUT_LATENCY_SECONDS)
      // Newest segment that started at or before t; a time before all
      // segments (device latency right after a seek) clamps to the oldest
      // segment's start (§16.2.3/§16.2.5).
      const seg = this.segmentAt(t) ?? {
        startContextTime: this.anchorTime,
        startFrame: this.genStartFrame,
        generation: this.generation,
      }
      // The last acknowledged anchor in this segment is the freshest
      // measurement (it absorbs underrun stalls); otherwise map from the
      // segment start.
      if (this.anchorSegment === seg && t >= this.anchorTime) {
        playbackFrame = this.consumedFrame + (t - this.anchorTime) * rate
      } else {
        playbackFrame = seg.startFrame + Math.max(0, t - seg.startContextTime) * rate
      }
      playbackFrame = Math.max(seg.startFrame, Math.min(playbackFrame, this.target.frameCount))
    } else {
      // Frozen (§16.2.6): the last acknowledged anchor, no extrapolation.
      playbackFrame = this.state === 'ended' ? this.target.frameCount : this.consumedFrame
    }
    return clampToDuration(
      projectPosition(playbackFrame, this.projectRate, rate),
      this.projectDurationFrames,
    )
  }

  /** Current playhead position in project frames (audible estimate). */
  get position(): number {
    return this.getAudiblePosition()
  }

  /** §15.3 budget: the 12 s ring capacity in frames. */
  private get budgetFrames(): number {
    return this.target ? Math.ceil(this.target.sampleRate * RING_SECONDS) : 0
  }

  /** §15.3 gate margin: one 1 s chunk. */
  private get marginFrames(): number {
    return this.target ? Math.ceil(this.target.sampleRate * CHUNK_SECONDS) : 0
  }

  /** §15.4 post-underrun start threshold: 2 s. */
  private get startThresholdFrames(): number {
    return this.target ? Math.ceil(this.target.sampleRate * PREBUFFER_SECONDS) : 0
  }

  private isActiveState(s: TransportState): boolean {
    return s === 'preparing' || s === 'playing' || s === 'buffering' || s === 'seeking'
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

  /**
   * Rebind to a new playback representation after context loss
   * (spec §15.6): discards the dead graph, keeps the retained position,
   * and parks the playhead there. The next `play` creates a fresh
   * context and starts from the retained position.
   */
  rebind({ target, projectRate, projectDurationFrames }: LoadSourceOptions): void {
    if (this.disposed) return
    this.teardownGraph()
    this.target = target
    this.projectRate = projectRate
    this.projectDurationFrames = projectDurationFrames
    this.contextLost = false
    this.lastError = null
    this.suspended = false
    this.generation = 0
    this.abort = new AbortController()
    const frame = clampToDuration(
      playbackPosition(this.retainedProjectFrame, projectRate, target.sampleRate),
      target.frameCount,
    )
    this.genStartFrame = frame
    this.fetchedFrame = frame
    this.consumedFrame = frame
    this.hasData = false
    this.bufferedFrames = 0
    this.workerPaused = false
    this.lastFlushedGeneration = -1
    this.diagnosticsState = { underruns: 0, lastUnderrunAt: null, droppedChunks: 0 }
    this.setState('unloaded')
    this.reportPosition()
  }

  /** Start (or resume) playback from the current position. */
  async play(): Promise<void> {
    if (this.disposed || !this.target) return
    if (this.context && this.suspended) {
      // A suspended context freezes the transport even in active states
      // (spec §15.5); `play` is the user gesture that resumes it.
      try {
        await this.context.resume()
      } catch (err) {
        this.fail(err)
        return
      }
    }
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
      if (this.context && this.context.state === 'suspended') {
        // Resumption needs a user gesture where the browser requires one
        // (spec §15.5): `play` is that gesture.
        try {
          await this.context.resume()
        } catch (err) {
          this.fail(err)
          return
        }
      }
      // The fresh worklet starts at frame 0, generation 0; align it with
      // the transport bookkeeping (a pre-playback seek may have moved it).
      try {
        this.pushSegment(this.context?.currentTime ?? 0, this.genStartFrame)
        this.node?.port.postMessage({
          type: 'seek',
          frame: this.genStartFrame,
          generation: this.generation,
        })
        await this.alignWorklet()
      } catch (err) {
        this.fail(err)
        return
      }
    }
    if (this.state === 'ended') {
      this.flushBookkeeping(0)
      try {
        await this.alignWorklet()
      } catch (err) {
        this.fail(err)
        return
      }
    }
    this.node?.port.postMessage({ type: 'resume' })
    if (this.state === 'buffering') {
      // Keep buffering: the 2 s start threshold decides on the next
      // `buffered` acknowledgment (spec §15.4).
    } else if (this.hasData) {
      this.setState('playing')
    } else {
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
    this.source?.stop()
    this.abort?.abort()
    this.setState('paused')
    this.reportPosition()
  }

  /** Stop: pause semantics plus reset to zero (spec §14.5). */
  stop(): void {
    if (this.disposed) return
    this.desiredPlaying = false
    this.flushBookkeeping(0)
    const align = this.alignWorklet()
    if (align !== undefined) void align.catch(() => {})
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
    this.flushBookkeeping(frame)
    if (wasPlaying && this.state !== 'unloaded') {
      this.setState('seeking')
    } else if (this.isActiveState(this.state)) {
      this.setState('paused')
      this.reportPosition()
    }
    const align = this.alignWorklet()
    if (wasPlaying && this.state === 'seeking') {
      if (align === undefined) {
        // Transfer path: the generation message reached the worker
        // before this point; refill immediately.
        void this.runFill()
      } else {
        // Shared path: the worker's writer index resets only after the
        // flush handshake, so refill once it completes.
        void align.then(() => {
          if (this.desiredPlaying && this.state === 'seeking') void this.runFill()
        })
      }
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

  /**
   * Report the current state and position (spec §15.5). Called on tab
   * visibility return so the UI redraws from actual transport state.
   * Also picks up a context that closed while the tab was hidden.
   */
  sync(): SyncInfo {
    if (this.context && this.context.state === 'closed' && !this.contextLost) {
      this.handleContextLost()
    }
    this.reportPosition()
    return {
      state: this.state,
      position: this.position,
      isSuspended: this.suspended,
      contextLost: this.contextLost,
    }
  }

  /** Tear down the graph, source, and ring, and close the context. */
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.desiredPlaying = false
    const context = this.context
    this.teardownGraph()
    if (context && context.state !== 'closed') {
      void context.close().catch(() => {})
    }
  }

  /** Create context, shared ring, worklet node, gain stage, and source. */
  private async initGraph(): Promise<void> {
    const target = this.target
    if (!target) throw new Error('No source loaded')
    const context = this.opts.contextFactory()
    if (context.state === 'suspended') await context.resume()
    this.context = context
    context.onstatechange = () => this.onContextStateChange()
    this.mode = resolveMode(this.opts.mode ?? 'auto')
    if (this.mode === 'shared') {
      const capacity = Math.ceil(target.sampleRate * RING_SECONDS)
      this.ring = createSharedRing(16 + capacity * target.channelCount * 4, target.channelCount)
    }
    this.blobUrl = this.opts.moduleUrlFactory
      ? this.opts.moduleUrlFactory(processorSource)
      : URL.createObjectURL(new Blob([processorSource], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(this.blobUrl)
    const options: Record<string, unknown> = {
      processorOptions: {
        sampleRate: target.sampleRate,
        channelCount: target.channelCount,
        frameCount: target.frameCount,
        ...(this.ring ? { sab: this.ring.sab } : {}),
      },
    }
    if (this.ring) options.transfer = [this.ring.sab]
    const node = context.createWorkletNode('basseparate-pcm', options)
    node.port.onmessage = (e) => this.handleWorkletMessage(e.data)
    const gainNode = context.createGain()
    gainNode.gain.value = this.pendingGain
    node.connect(gainNode)
    gainNode.connect(context.destination)
    this.node = node
    this.gainNode = gainNode
    this.abort = new AbortController()
    this.anchorTime = context.currentTime
    this.source = this.createSource()
    if (this.mode === 'shared' && this.ring) {
      await this.source.attachShared(this.ring.sab, target.channelCount)
    }
  }

  /** Pick the fetch source: real worker when available, else main thread. */
  private createSource(): FetchSource {
    const target = this.target
    if (!target) throw new Error('No source loaded')
    const factory = this.opts.workerFactory ?? defaultWorkerFactory
    const worker = factory()
    if (worker) return new WorkerFetchSource(worker, target.channelCount)
    return new DirectFetchSource(
      (assetId, start, end) => this.opts.fetchChunk(assetId, start, end, this.abort?.signal),
      target.channelCount,
    )
  }

  /**
   * Reset fetch and position bookkeeping to `frame` and tell the worklet
   * to flush (synchronous). Bumps the generation so everything from the
   * old generation (fetches, port messages) is dropped.
   */
  /** The newest segment that started at or before `time` (or null). */
  private segmentAt(time: number): TransportSegment | null {
    for (let i = this.segments.length - 1; i >= 0; i--) {
      if (this.segments[i].startContextTime <= time) return this.segments[i]
    }
    return null
  }

  private pushSegment(startContextTime: number, startFrame: number): void {
    const seg: TransportSegment = { startContextTime, startFrame, generation: this.generation }
    this.segments.push(seg)
    if (this.segments.length > MAX_SEGMENTS) {
      this.segments = this.segments.slice(-MAX_SEGMENTS)
    }
    // The segment start is a virtual anchor (the bookkeeping baseline).
    this.anchorSegment = seg
  }

  private flushBookkeeping(frame: number): void {
    const target = this.target
    if (!target) return
    this.generation += 1
    this.abort?.abort()
    this.abort = new AbortController()
    const clamped = Math.max(0, Math.min(Math.floor(frame), target.frameCount))
    this.genStartFrame = clamped
    this.fetchedFrame = clamped
    this.consumedFrame = clamped
    this.hasData = false
    this.bufferedFrames = 0
    this.workerPaused = false
    if (this.context) this.anchorTime = this.context.currentTime
    this.pushSegment(this.context ? this.context.currentTime : 0, clamped)
    this.source?.stop()
    this.node?.port.postMessage({ type: 'seek', frame: clamped, generation: this.generation })
  }

  /**
   * Align the fetch source with the current bookkeeping after a seek.
   * Transfer path: synchronous (`setGeneration`); shared path: awaits the
   * worklet's `flushed` acknowledgment and only then resets the worker's
   * writer index (spec §15.1.6), so the handshake cannot race the
   * refill. Returns `undefined` when nothing async was needed.
   */
  private alignWorklet(): void | Promise<void> {
    if (this.mode !== 'shared' || !this.source) {
      this.source?.setGeneration(this.generation)
      return
    }
    return this.awaitFlushedAck(this.generation).then(() =>
      this.source!.acknowledgeFlush(this.generation, this.genStartFrame),
    )
  }

  /**
   * Resolve when the worklet acknowledges the flush for `generation`.
   * A `flushed` message that arrived before this call (fast fakes) is
   * honored via `lastFlushedGeneration`.
   */
  private awaitFlushedAck(generation: number): Promise<void> {
    if (this.lastFlushedGeneration === generation) return Promise.resolve()
    return new Promise((resolve) => {
      this.flushAckResolve = resolve
    })
  }

  private handleWorkletMessage(data: unknown): void {
    if (this.disposed) return
    if (typeof data !== 'object' || data === null) return
    const msg = data as { type: string; generation?: number }
    if (typeof msg.generation === 'number' && msg.generation !== this.generation) return
    switch (msg.type) {
      case 'buffered': {
        const m = msg as unknown as { frames: number; queuedFrames: number }
        this.bufferedFrames = m.frames
        if (m.frames > 0) this.hasData = true
        // Flow control: resume the worker below budget − margin.
        if (this.workerPaused && m.queuedFrames < this.budgetFrames - this.marginFrames) {
          this.workerPaused = false
        }
        if (this.desiredPlaying) {
          if (this.state === 'buffering' && m.frames >= this.startThresholdFrames) {
            // Post-underrun resume needs the 2 s threshold (spec §15.4).
            this.setState('playing')
          } else if ((this.state === 'preparing' || this.state === 'seeking') && m.frames > 0) {
            // Initial start: any acknowledged data (M1.12 rule).
            this.setState('playing')
          }
        }
        break
      }
      case 'queue-high':
        this.workerPaused = true
        break
      case 'chunk-dropped':
        this.diagnosticsState.droppedChunks += 1
        break
      case 'flushed':
        this.lastFlushedGeneration = (msg.generation as number) ?? -1
        if (this.flushAckResolve) {
          this.flushAckResolve()
          this.flushAckResolve = null
        }
        break
      case 'anchor': {
        const m = msg as unknown as { frame: number; time: number; paused?: boolean }
        this.consumedFrame = m.frame
        this.anchorTime = m.time
        this.anchorSegment = this.segmentAt(m.time)
        this.reportPosition()
        break
      }
      case 'underrun':
        this.diagnosticsState.underruns += 1
        this.diagnosticsState.lastUnderrunAt = Date.now()
        if (this.desiredPlaying && this.state === 'playing') this.setState('buffering')
        break
      case 'ended':
        this.desiredPlaying = false
        this.setState('ended')
        this.reportPosition()
        break
      default:
        break
    }
  }

  /** React to context state changes (spec §15.5/§15.6). */
  private onContextStateChange(): void {
    if (this.disposed) return
    const context = this.context
    if (!context) return
    if (context.state === 'closed') {
      this.handleContextLost()
    } else if (context.state === 'suspended') {
      this.suspended = true
      this.opts.onSuspend?.(true)
    } else if (context.state === 'running') {
      this.suspended = false
      this.opts.onSuspend?.(false)
      if (this.desiredPlaying && this.isActiveState(this.state)) void this.runFill()
    }
  }

  /**
   * The context closed under us (device change, spec §15.6): retain the
   * last acknowledged position, tear everything down, and surface an
   * error the panel can recover from via `rebind`.
   */
  private handleContextLost(): void {
    if (this.contextLost) return
    // Read the position before flipping the flag: the getter returns the
    // retained frame once `contextLost` is set.
    const retained = this.position
    this.contextLost = true
    this.retainedProjectFrame = retained
    this.desiredPlaying = false
    this.lastError = 'The audio context was closed (the audio device may have changed)'
    this.teardownGraph()
    this.setState('error')
    this.reportPosition()
  }

  /**
   * Disconnect the graph, fetch source, and ring. The context is not
   * closed here: it is already closed on the loss path, and `dispose`
   * closes it when it is still open.
   */
  private teardownGraph(): void {
    this.abort?.abort()
    if (this.flushAckResolve) {
      this.flushAckResolve()
      this.flushAckResolve = null
    }
    this.source?.dispose()
    this.source = null
    try {
      this.node?.port.postMessage({ type: 'dispose' })
      this.node?.disconnect()
      this.gainNode?.disconnect()
    } catch {
      // The graph may already be gone.
    }
    this.node = null
    this.gainNode = null
    this.ring = null
    if (this.blobUrl?.startsWith('blob:')) URL.revokeObjectURL(this.blobUrl)
    this.blobUrl = null
    this.context = null
    // A fresh context starts a fresh time base; old segments would map
    // new context times to the dead representation (spec §16.2.3).
    this.segments = []
  }

  private isStale(err: unknown, gen: number): boolean {
    return (
      this.disposed ||
      gen !== this.generation ||
      err instanceof StaleGenerationError ||
      (err instanceof DOMException && err.name === 'AbortError')
    )
  }

  /**
   * Prefetch loop: keep the worklet fed to the §15.3 target ahead of the
   * estimated consumed position, gated by the 12 s retention budget. A
   * single loop outlives generation bumps: a seek/stop aborts in-flight
   * fetches and the parking delay, the loop wakes, and refetches from the
   * new bookkeeping. Runs while `desiredPlaying` and the state is active.
   */
  private async runFill(): Promise<void> {
    if (this.fillLoopRunning || this.disposed) return
    this.fillLoopRunning = true
    try {
      while (!this.disposed && this.desiredPlaying && this.node && this.target && this.source) {
        const s = this.state
        if (s !== 'preparing' && s !== 'playing' && s !== 'buffering' && s !== 'seeking') return
        const target = this.target
        const rate = target.sampleRate
        const bytesPerFrame = 4 * target.channelCount
        const consumedEstimate =
          this.consumedFrame +
          (this.context && !this.suspended
            ? Math.max(0, this.context.currentTime - this.anchorTime) * rate
            : 0)
        const targetAhead = Math.min(
          rate * LOOKAHEAD_SECONDS,
          Math.max(rate * PREBUFFER_SECONDS, target.frameCount - this.genStartFrame),
        )
        let fetched = false
        while (
          this.fetchedFrame < target.frameCount &&
          this.fetchedFrame - consumedEstimate < targetAhead &&
          !this.workerPaused &&
          this.bufferedFrames < this.budgetFrames - this.marginFrames
        ) {
          const frames = Math.min(rate * CHUNK_SECONDS, target.frameCount - this.fetchedFrame)
          if (frames <= 0) break
          const start = Math.floor(this.fetchedFrame * bytesPerFrame)
          const end = start + frames * bytesPerFrame - 1
          const gen = this.generation
          let written = 0
          if (this.mode === 'shared') {
            let result: PcmWriteResult
            try {
              result = await this.source.writeChunk(target.assetId, start, end, gen)
            } catch (err) {
              if (this.isStale(err, gen)) break
              this.fail(err)
              return
            }
            if (gen !== this.generation) break
            written = result.frames
            if (written <= 0) {
              // The ring is full (flow control should make this
              // unreachable): drop and re-check after a park.
              this.diagnosticsState.droppedChunks += 1
              break
            }
          } else {
            let chunk: PcmChunk
            try {
              chunk = await this.source.fetchChunk(target.assetId, start, end, gen)
            } catch (err) {
              if (this.isStale(err, gen)) break
              this.fail(err)
              return
            }
            if (gen !== this.generation) break
            this.node.port.postMessage(
              {
                type: 'channels',
                channels: chunk.channels,
                startFrame: chunk.startFrame,
                frames: chunk.frames,
                generation: gen,
              },
              chunk.channels.map((c) => c.buffer as ArrayBuffer),
            )
            written = chunk.frames
          }
          this.fetchedFrame += written
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
    if (this.disposed) return
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
