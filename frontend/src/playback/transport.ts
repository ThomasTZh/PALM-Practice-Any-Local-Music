/**
 * AudioWorklet PCM transport (M1.12/M1.13, spec §14–15; M2.8, spec §10).
 *
 * Replaces the `AudioBufferSourceNode` scheduling engine (M1.7): the
 * worklet (`worklet-processor.js`) consumes bounded PCM on the audio
 * thread; this class owns everything on the main thread — the eight
 * transport states plus `desiredPlaying`, chunked prefetch (~1 s
 * network chunks, 2 s prebuffer, 8 s steady lookahead scaled by
 * playback speed, and the M2.12 §14.1 group buffer budget: 24 s
 * duration cap and 32 MiB byte cap per stem, minimised over the
 * group), seek generations, anchor-based position extrapolation,
 * local diagnostics, browser-suspend tracking, and the monitoring
 * gain/limiter stages that sit after the worklet (canonical samples
 * are never modified).
 *
 * Multi-source mixing (M2.8, spec §10.5): the transport binds N
 * `SourceSpec`s that all match the project rate and duration (hard
 * validation, no resampling). One fetch source serves the whole mix —
 * N per-asset queues behind a single worker — and the worklet mixes the
 * sources with a shared cursor (one `MixState`), so drift is impossible.
 * Mixer parameters (gain/balance/mute/solo, master gain) are forwarded
 * to the worklet; per-quantum peaks come back on the `anchor` messages.
 *
 * Two data paths (spec §15.1/§15.2), selected by `mode`:
 * - `shared`: cross-origin isolated; the fetch worker writes the shared
 *   SAB rings directly (SPSC, atomic indices; one ring per source).
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
import { getSessionToken } from '../auth'
import { createSharedRing, type SharedRing } from './pcm-fetch'
import { LoopPin, PINNED_BYTES_MAX } from './loop-pin'
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
import stretchWorkletSource from './stretch/stretch-worklet.js?raw'
import { simdSupported } from './stretch/stretch-host'

export type TransportState =
  'unloaded' | 'preparing' | 'paused' | 'playing' | 'seeking' | 'buffering' | 'ended' | 'error'

/** Data path selection; `auto` picks shared memory when isolated. */
export type TransportMode = 'auto' | 'shared' | 'transfer'

/**
 * One playback source in the mix (M2.8, spec §10.5). All sources must
 * match the project rate and duration; `loadSource` validates this and
 * refuses to resample.
 */
export interface SourceSpec {
  assetId: string
  sampleRate: number
  channelCount: number
  frameCount: number
}

/**
 * Mixer parameter patch for one source (spec §10.3). `gain` is linear
 * amplitude; the worklet ramps changes over 5 ms.
 */
export interface SourceParamPatch {
  gain?: number
  balance?: number
  mute?: boolean
  solo?: boolean
}

/** Per-quantum peak metering (spec §10.3.7), ~20 Hz, mixer path only. */
export interface MixPeaks {
  tracks: number[]
  master: number
}

/**
 * M2.11 (spec §13): the active practice loop, in source frames.
 * `repeatCount` is the total number of passes (a partial first pass
 * counts as pass 1); `null` repeats forever. `boundaryFade` enables the
 * 5 ms join fades at the pass crossings (§13.6). The range is validated
 * by the domain (`0 ≤ start < end ≤ duration`); the transport trusts it.
 */
export interface TransportLoopSpec {
  startFrame: number
  endFrame: number
  repeatCount: number | null
  boundaryFade: boolean
}

/** One metronome click in absolute worklet render frames (M3.14). */
export interface MusicalGridEvent {
  /** Context render frame of the grid event boundary. */
  renderFrame: number
  /** Musical label for diagnostics; never used for arithmetic here. */
  label: string
  /** Grid revision that produced the event. */
  revision: number
}

export interface MusicalGridSchedule {
  revision: number
  events: readonly MusicalGridEvent[]
}

export interface MetronomeTransportState {
  enabled: boolean
  volume: number
  clicks: MetronomeClickSpec[]
}

export interface CountInTransportState {
  clicks: MetronomeClickSpec[]
  volume: number
}

export interface MetronomeClickSpec {
  frame: number
  strength: 'downbeat' | 'beat' | 'grouping' | 'subdivision'
}

/** Underrun accounting surfaced to the panel (spec §15.4). */
export interface TransportDiagnostics {
  underruns: number
  lastUnderrunAt: number | null
  droppedChunks: number
  /**
   * M2.10 §12.5: control-response latency (seconds) for mixer changes —
   * the DSP lookahead the worklet reads ahead of the audible cursor
   * (`speed × outputLatency + inputLatency` source frames at the current
   * rate). Zero without an engine: with no stretcher, mixer changes are
   * heard at the next render quantum.
   */
  controlResponseLatencySeconds: number
  /** M2.12 §14.4: group ring capacity in frames (source domain). */
  capacityFrames: number
  /** M2.12 §14.1: bytes buffered across the active group. */
  bufferedBytes: number
  /** M2.12 §14.1: ring capacity in bytes across the active group. */
  budgetBytes: number
  /** M2.12 §14.1.4: bytes pinned for loop playback across the group. */
  pinnedBytes: number
  /** M2.12 §14.2.1: buffered source frames per stem (worklet report). */
  stemBufferedFrames: number[]
  /** M2.12 §14.4: last worklet render-callback duration (ms). */
  callbackDurationMs: number | null
  /** M2.12 §14.4: stretcher state as reported by the worklet. */
  stretcher: { rate: number; bypass: boolean; warmup: number } | null
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

/** Structural subset of a `DynamicsCompressorNode` (monitoring only). */
export interface CompressorNodeLike {
  threshold: GainParamLike
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
  /**
   * Test seam: the context fakes provide a node factory. Real
   * `AudioContext` objects do not have this method, so the transport
   * bridges them through the global `AudioWorkletNode` constructor
   * (`createTransportWorkletNode`).
   */
  createWorkletNode?(name: string, options?: Record<string, unknown>): WorkletNodeLike
  createGain(): GainNodeLike
  /** Absent in minimal test fakes; the limiter is then skipped. */
  createDynamicsCompressor?(): CompressorNodeLike
  resume(): Promise<void>
  close(): Promise<void>
  /** Output-device timestamp (spec §16.2); absent in test fakes. */
  getOutputTimestamp?(): { contextTime: number; performanceTime: number } | null
}

type WorkletNodeConstructor = new (
  context: unknown,
  name: string,
  options?: Record<string, unknown>,
) => WorkletNodeLike

/**
 * Create the transport's AudioWorklet node.
 *
 * Browsers do not expose a `createWorkletNode` factory on `AudioContext`
 * (that method is a test seam for the context fakes), so a real context
 * is bridged through the global `AudioWorkletNode` constructor.
 */
export function createTransportWorkletNode(
  context: TransportContextLike,
  name: string,
  options: Record<string, unknown>,
): WorkletNodeLike {
  if (typeof context.createWorkletNode === 'function') {
    return context.createWorkletNode(name, options)
  }
  const ctor = (globalThis as { AudioWorkletNode?: WorkletNodeConstructor }).AudioWorkletNode
  if (ctor === undefined) {
    throw new Error('AudioWorkletNode is not available in this environment')
  }
  return new ctor(context, name, options)
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
  /**
   * Monitoring-only limiter (spec §10.6.5): a DynamicsCompressor after
   * the monitoring gain. Never touches sample storage; its documented
   * delay is folded into the audible-time mapping.
   */
  limiter?: boolean
  /**
   * M2.9: load the stretch artifact (selected variant) as an
   * ArrayBuffer for the worklet. Defaults to fetching the bundled
   * `dist/stretch-<variant>.wasm` (SIMD when supported).
   */
  fetchStretchBytes?: () => Promise<ArrayBuffer>
  onState?: (state: TransportState) => void
  /** Reports the playhead position in project frames. */
  onPosition?: (frame: number) => void
  /** Reports browser suspension of the audio context (spec §15.5). */
  onSuspend?: (suspended: boolean) => void
  /** Per-quantum peak metering from the worklet mixer (~20 Hz). */
  onPeaks?: (peaks: MixPeaks) => void
  /**
   * M2.11 §13.4.5: a seek landed outside the enabled loop, so looping
   * was disabled (the saved loop is retained). The App persists
   * `loop_enabled = false` through the command pipeline.
   */
  onLoopDisabled?: () => void
}

export interface LoadSourceOptions {
  /**
   * M2.8: every source in the mix. All must match the project rate and
   * duration (hard validation, no resampling).
   */
  sources?: SourceSpec[]
  /** Legacy single-source form (equivalent to `sources: [target]`). */
  target?: PlaybackTarget
  projectRate: number
  projectDurationFrames: number
}

/**
 * A transport segment: generation `generation` started playing from
 * `startFrame` at context time `startContextTime` (spec §16.2.3).
 * `speed` is the playback speed when the segment started (M2.9,
 * spec §11.7.5): each segment extrapolates with its own speed.
 */
interface TransportSegment {
  startContextTime: number
  startFrame: number
  generation: number
  speed: number
}

/**
 * The loop shape sent to the worklet (M2.11 §13.7): stream coordinates
 * are source-aligned at each seek boundary, so `start`/`end` are plain
 * source frames and the worklet reads the ring linearly.
 */
interface WorkletLoopSpec {
  start: number
  end: number
  repeatCount: number | null
  fade: boolean
}

function sameWorkletLoop(a: WorkletLoopSpec | null, b: WorkletLoopSpec | null): boolean {
  if (a === null || b === null) return a === b
  return (
    a.start === b.start && a.end === b.end && a.repeatCount === b.repeatCount && a.fade === b.fade
  )
}

/**
 * §14.1 (M2.12) buffer sizing, replacing M1's flat 12 s cap: how much
 * source audio a stem may retain (duration cap), how many bytes the
 * ring may occupy (byte cap), and the steady lookahead the scaled
 * target is allowed to reach. The group gets one frame capacity — the
 * tighter of the two caps, minimised over the active sources.
 */
const SOURCE_BUFFER_SECONDS = 24
const SOURCE_BUFFER_BYTES = 32 * 1024 * 1024
const BYTES_PER_SAMPLE = 4
/** Initial prebuffer and post-underrun start threshold. */
const PREBUFFER_SECONDS = 2
/** Steady-state lookahead target (multiplied by playback speed). */
const LOOKAHEAD_SECONDS = 8
/** One network chunk. */
const CHUNK_SECONDS = 1
const FILL_CHECK_MS = 50

/**
 * §14.1 (M2.12) group ring capacity in frames: every stem of the active
 * group gets the same capacity, the minimum over the sources of the
 * tighter of the duration cap (24 s) and the byte cap (32 MiB). The
 * transport passes the result to the worklet, which never sizes rings
 * itself; the shared path derives it from the SAB (same value).
 */
export function sourceBufferCapacityFrames(
  sources: ReadonlyArray<{ sampleRate: number; channelCount: number }>,
): number {
  let capacity = Number.POSITIVE_INFINITY
  for (const source of sources) {
    const byDuration = Math.ceil(source.sampleRate * SOURCE_BUFFER_SECONDS)
    const byBytes = Math.floor(SOURCE_BUFFER_BYTES / (source.channelCount * BYTES_PER_SAMPLE))
    capacity = Math.min(capacity, Math.max(1, Math.min(byDuration, byBytes)))
  }
  return Number.isFinite(capacity) ? capacity : 0
}

/** M2.12 §14.4: fresh diagnostics state (also the per-load baseline). */
export function initialTransportDiagnostics(): TransportDiagnostics {
  return {
    underruns: 0,
    lastUnderrunAt: null,
    droppedChunks: 0,
    controlResponseLatencySeconds: 0,
    capacityFrames: 0,
    bufferedBytes: 0,
    budgetBytes: 0,
    pinnedBytes: 0,
    stemBufferedFrames: [],
    callbackDurationMs: null,
    stretcher: null,
  }
}
const MAX_GAIN = 4
const GAIN_RAMP_TIME_CONSTANT = 0.01
/**
 * §16.2.4 documented fallback: without `getOutputTimestamp()` the context
 * time is assumed to be the audible time (zero output latency).
 */
const FALLBACK_OUTPUT_LATENCY_SECONDS = 0
/**
 * §10.6.5 documented limiter delay: the monitoring compressor adds this
 * much graph latency between the worklet and the output device. It is
 * folded into the audible-time mapping while the limiter is active.
 */
const LIMITER_DELAY_SECONDS = 0.01
/** §10.6.5 limiter threshold in dBFS (monitoring only). */
const LIMITER_THRESHOLD_DB = -1
/** §16.2.3: recent segments retained for time → frame mapping. */
const MAX_SEGMENTS = 16
/**
 * M2.10 §12.3 pre-roll fetched before the audible boundary on every
 * seek: a wet start's silent warm-up covers `5760 × rate` source frames
 * plus the first context window's back-reach (the worklet's
 * `WARMUP_OUT_FRAMES` and the rolling-window law). 12288 covers 2× with
 * margin; at 1× the boundary itself is exact (the dry bypass).
 */
const PRE_ROLL_FRAMES = 12_288

function defaultWorkerFactory(): WorkerLike | null {
  if (typeof Worker === 'undefined') return null
  // The DOM `Worker` matches the structural `WorkerLike` at runtime; the
  // `onmessage` signature differs only in the event type.
  const worker = new Worker(new URL('./fetch-worker.ts', import.meta.url), {
    type: 'module',
  }) as unknown as WorkerLike
  // Dedicated workers cannot read `sessionStorage`; hand the fetch token
  // over before any fetch job (message order is preserved).
  const token = getSessionToken()
  if (token) worker.postMessage({ kind: 'auth', token })
  return worker
}

function resolveMode(requested: TransportMode): 'shared' | 'transfer' {
  if (requested === 'shared') return 'shared'
  if (requested === 'transfer') return 'transfer'
  const isolated = (globalThis as { crossOriginIsolated?: boolean }).crossOriginIsolated === true
  return isolated && typeof SharedArrayBuffer !== 'undefined' ? 'shared' : 'transfer'
}

/**
 * M2.9 (spec §11.3.7/§11.3.11): load the bundled stretch artifact —
 * the SIMD build when the runtime supports it, the scalar build
 * otherwise. The bytes are transferred to the worklet, which
 * instantiates the engine synchronously (no fetch in the worklet).
 */
async function defaultFetchStretchBytes(): Promise<ArrayBuffer> {
  const url = simdSupported()
    ? new URL('./stretch/dist/stretch-simd.wasm', import.meta.url)
    : new URL('./stretch/dist/stretch-scalar.wasm', import.meta.url)
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`stretch: failed to load the artifact (HTTP ${res.status})`)
  }
  return res.arrayBuffer()
}

export class PcmTransport {
  private state: TransportState = 'unloaded'
  /** Kept separate from the actual state so seeks and underruns can
   * temporarily pause output without losing user intent (spec §14.3). */
  private desiredPlaying = false
  private readonly opts: TransportOptions
  private readonly delay: (ms: number, signal?: AbortSignal) => Promise<void>
  private readonly fetchStretchBytes: () => Promise<ArrayBuffer>

  /** Every source in the mix (M2.8); all match the project rate/duration. */
  private sources: SourceSpec[] = []
  private projectRate = 0
  private projectDurationFrames = 0
  /** Position park (project frames) before any source is loaded. */
  private parkedProjectFrame = 0

  private context: TransportContextLike | null = null
  private node: WorkletNodeLike | null = null
  private gainNode: GainNodeLike | null = null
  /** Monitoring-only limiter after the gain stage (spec §10.6.5). */
  private limiterNode: CompressorNodeLike | null = null
  private blobUrl: string | null = null
  private pendingGain = 1
  private musicalGridRevision = -1
  private musicalGrid: readonly MusicalGridEvent[] = []
  private metronomeState: MetronomeTransportState | null = null
  private countInState: CountInTransportState | null = null
  /** Master monitoring gain (linear), applied in the worklet mixer. */
  private pendingMasterGain = 1
  /** M2.9: target playback speed (0.25…2.0), remembered for fresh graphs. */
  private speed = 1
  /** M2.9: engine latencies (source frames) from `stretch-ready`. */
  private stretchInputLatency = 0
  private stretchOutputLatency = 0

  /**
   * M2.9: engine latencies (source frames) from `stretch-ready`, or
   * `null` before the worklet reports them. The worklet's rolling seek
   * window (`speed × outputLatency + inputLatency`) is the read-ahead
   * the transport fetches for; the anchors map the audible position
   * directly (spec §12.3/§12.7).
   */
  get engineLatencies(): { inputLatency: number; outputLatency: number } | null {
    if (this.stretchInputLatency === 0 && this.stretchOutputLatency === 0) return null
    return {
      inputLatency: this.stretchInputLatency,
      outputLatency: this.stretchOutputLatency,
    }
  }

  /**
   * §12.5 control-response latency: a mixer change (gain/pan/mute/solo)
   * applies to the source frames entering the stretcher's context window
   * and is heard after the worklet's read-ahead
   * (`speed × outputLatency + inputLatency` source frames). The master
   * gain is applied after the stretcher, so it is not part of this.
   */
  get controlResponseLatencySeconds(): number {
    const target = this.primary
    if (!target || this.stretchInputLatency === 0) return 0
    const frames = this.speed * this.stretchOutputLatency + this.stretchInputLatency
    return frames / target.sampleRate
  }

  private mode: 'shared' | 'transfer' = 'transfer'
  private source: FetchSource | null = null
  /** Shared rings (shared path only, one per source); SABs worklet-owned. */
  private rings: SharedRing[] = []

  /** M2.11 §13: the active practice loop (source frames) or null. */
  private loop: TransportLoopSpec | null = null
  /** Whether looping is enabled (enabling ≠ starting, §13.4.1). */
  private loopEnabled = false
  /**
   * Source frame where a finite repeat sequence stopped (§13.4.6), or
   * null. Set by `loop-complete`; cleared by the next flush/seek. The
   * frozen playhead reports it exactly (the loop end, not the wrapped
   * start).
   */
  private loopStoppedSource: number | null = null
  /** The loop shape the worklet currently holds (idempotent sync). */
  private workletLoop: WorkletLoopSpec | null = null
  private workletLoopKnown = false
  /**
   * True while a fetch round is between its awaits: a mid-stream loop
   * install must then take the rebuffering transition path, because the
   * round's range was computed under the previous loop state.
   */
  private fillRoundInFlight = false

  /** Bumped on every seek/stop so stale fetches and port messages drop. */
  private generation = 0
  private abort: AbortController | null = null
  private genStartFrame = 0
  private fetchedFrame = 0
  /** Last acknowledged anchor frame (audible source frames). */
  private consumedFrame = 0
  /** Context time of the last anchor. */
  private anchorTime = 0
  /** Playback rate named by the last anchor (the worklet's ramped rate). */
  private anchorRate = 1
  /** Recent segments for audible-time → frame mapping (spec §16.2.3). */
  private segments: TransportSegment[] = []
  /** Segment the last acknowledged anchor landed in (null before any). */
  private anchorSegment: TransportSegment | null = null
  /** The worklet ring/queue currently holds samples. */
  private hasData = false
  /** Worklet-reported buffered frames (ring + queue, or writer−reader). */
  private bufferedFrames = 0
  /** M2.12 §14.1: group ring capacity in frames (M2 sizing policy). */
  private bufferCapacity = 0
  /**
   * M2.12 §14.1.4: the pinned-loop cache of the enabled loop, or null
   * while the loop streams (ineligible or no loop). Released on loop
   * change/disable/dispose; keeps serving seeks inside the range.
   */
  private pin: LoopPin | null = null
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
  private diagnosticsState: TransportDiagnostics = initialTransportDiagnostics()

  constructor(opts: TransportOptions) {
    this.opts = opts
    this.fetchStretchBytes = opts.fetchStretchBytes ?? defaultFetchStretchBytes
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

  /** Context render clock in seconds; null before the graph exists. */
  get contextTime(): number | null {
    return this.context ? this.context.currentTime : null
  }

  /** Current playback speed (1 = source speed). */
  get playbackRate(): number {
    return this.speed
  }

  get currentError(): string | null {
    return this.lastError
  }

  get isSuspended(): boolean {
    return this.suspended
  }

  /** Sample rate of the live context (null before the graph exists). */
  get contextRate(): number | null {
    return this.context ? this.context.sampleRate : null
  }

  get diagnostics(): TransportDiagnostics {
    return {
      ...this.diagnosticsState,
      controlResponseLatencySeconds: this.controlResponseLatencySeconds,
    }
  }

  /**
   * The first source in the mix. All sources are equal in rate and
   * duration (hard-validated in `loadSource`), so the first is the
   * position-mapping reference.
   */
  private get primary(): SourceSpec | null {
    return this.sources[0] ?? null
  }

  /** Output latency folded into the audible-time mapping (spec §10.6.5). */
  private get effectiveLatency(): number {
    return this.limiterNode ? LIMITER_DELAY_SECONDS : FALLBACK_OUTPUT_LATENCY_SECONDS
  }

  /**
   * Audible position in project frames (spec §16.2): the source frame at
   * the output device's current context time, mapped through the retained
   * transport segments. Extrapolation is frozen while paused, buffering,
   * suspended, or ended — the last acknowledged anchor is reported.
   */
  getAudiblePosition(): number {
    const target = this.primary
    if (!target) return this.parkedProjectFrame
    // After context loss the graph (and its consumption tracking) is gone;
    // report the retained position until `rebind` resets the bookkeeping.
    if (this.contextLost) return this.retainedProjectFrame
    const rate = target.sampleRate
    const context = this.context
    let playbackFrame: number
    if (context && !this.suspended && (this.state === 'playing' || this.state === 'seeking')) {
      const ts = context.getOutputTimestamp ? context.getOutputTimestamp() : null
      const latency = this.effectiveLatency
      const t = ts ? ts.contextTime - latency : Math.max(0, context.currentTime - latency)
      // Newest segment that started at or before t; a time before all
      // segments (device latency right after a seek) clamps to the oldest
      // segment's start (§16.2.3/§16.2.5).
      const seg = this.segmentAt(t) ?? {
        startContextTime: this.anchorTime,
        startFrame: this.genStartFrame,
        generation: this.generation,
        speed: this.speed,
      }
      // The last acknowledged anchor in this segment is the freshest
      // measurement (it absorbs underrun stalls); otherwise map from the
      // segment start. M2.10: the anchor names the audible source frame
      // and the context time it plays, so extrapolation advances at the
      // anchor's rate (the worklet's ramped rate) × speed.
      if (this.anchorSegment === seg && t >= this.anchorTime) {
        playbackFrame = this.consumedFrame + (t - this.anchorTime) * rate * this.anchorRate
      } else {
        playbackFrame = seg.startFrame + Math.max(0, t - seg.startContextTime) * rate * seg.speed
      }
      // M2.11 §13: a looped stream is unbounded in stream coordinates
      // (the source length does not cap it); the mod mapping below folds
      // it back into the source.
      playbackFrame =
        this.workletLoop !== null
          ? Math.max(seg.startFrame, playbackFrame)
          : Math.max(seg.startFrame, Math.min(playbackFrame, target.frameCount))
    } else {
      // Frozen (§16.2.6): the last acknowledged anchor, no extrapolation.
      playbackFrame = this.state === 'ended' ? target.frameCount : this.consumedFrame
    }
    // M2.11 §13: stream coordinates are mapped to source frames through
    // the loop (a completed sequence reports its exact stop position).
    const sourceFrame =
      this.loopStoppedSource !== null
        ? this.loopStoppedSource
        : this.state === 'ended'
          ? playbackFrame
          : this.sourceFromStream(playbackFrame)
    return clampToDuration(
      projectPosition(sourceFrame, this.projectRate, rate),
      this.projectDurationFrames,
    )
  }

  /** Current playhead position in project frames (audible estimate). */
  get position(): number {
    return this.getAudiblePosition()
  }

  /** M2.11 §13: looping is enabled on an active loop. */
  private isLooping(): boolean {
    return this.loopEnabled && this.loop !== null
  }

  /** The loop shape sent to the worklet (§13.7), or null when disabled. */
  private workletLoopSpec(): WorkletLoopSpec | null {
    const loop = this.loop
    if (!this.loopEnabled || !loop) return null
    return {
      start: loop.startFrame,
      end: loop.endFrame,
      repeatCount: loop.repeatCount,
      fade: loop.boundaryFade,
    }
  }

  /**
   * M2.11 §13: the source frame carried by stream coordinate `c` —
   * `start + ((c − start) mod len)` — or `c` unchanged for a linear
   * stream. The mapping follows the loop the WORKLET holds (the stream
   * content was fed to match it): a loop enabled while paused takes
   * effect on the next seek, not on the frozen position.
   */
  private sourceFromStream(c: number): number {
    const loop = this.loop
    if (!loop || this.workletLoop === null) return c
    const len = loop.endFrame - loop.startFrame
    if (len <= 0) return c
    return loop.startFrame + ((((c - loop.startFrame) % len) + len) % len)
  }

  /** The live audible estimate in stream coordinates (no mod mapping). */
  private currentStreamFrame(): number {
    const target = this.primary
    if (!target) return this.consumedFrame
    if (this.context && !this.suspended && this.isActiveState(this.state)) {
      return (
        this.consumedFrame +
        Math.max(0, this.context.currentTime - this.anchorTime) *
          target.sampleRate *
          this.anchorRate
      )
    }
    return this.consumedFrame
  }

  /** The current audible position as a source frame. */
  private currentSourceFrame(): number {
    return this.sourceFromStream(this.currentStreamFrame())
  }

  /**
   * §13.4.2/§13.4.7: when the loop is enabled and the current source
   * position is outside `[start, end)` — including the completion
   * position `== end` and the ended state — playback starts with a
   * synchronized seek to the loop start. Returns that source frame, or
   * null when the position is inside (or no loop is enabled).
   */
  private loopStartIfOutside(): number | null {
    const loop = this.loop
    if (!this.isLooping() || !loop) return null
    const source =
      this.state === 'ended'
        ? loop.endFrame
        : this.loopStoppedSource !== null
          ? this.loopStoppedSource
          : this.currentSourceFrame()
    if (source < loop.startFrame || source >= loop.endFrame) return loop.startFrame
    return null
  }

  /** A live graph is running and the user intends playback. */
  private isPlayingLive(): boolean {
    return this.desiredPlaying && this.node !== null && this.isActiveState(this.state)
  }

  /** The worklet's loop shape differs from the transport's desired one. */
  private loopStateChanged(): boolean {
    return !this.workletLoopKnown || !sameWorkletLoop(this.workletLoop, this.workletLoopSpec())
  }

  /**
   * The stream content fed so far is entirely inside the loop:
   * `fetchedFrame` is the next frame to fetch and the worklet cannot
   * have played past it, so the buffered content is the loop's first
   * pass (which is the plain source). Installing — or removing — the
   * loop mid-stream then keeps that content correct with no flush
   * (§13.4.3). False once the fetch cursor crossed the loop end: the
   * content past it is the linear source and must be refetched as the
   * periodic stream.
   */
  private midStreamInstallSafe(): boolean {
    const loop = this.loop
    return loop !== null && !this.fillRoundInFlight && this.fetchedFrame <= loop.endFrame
  }

  /** Push the worklet loop shape mid-stream (no re-seek, §13.4.3). */
  private installLoopMidStream(spec: WorkletLoopSpec | null): void {
    this.node?.port.postMessage({ type: 'loop', loop: spec })
    this.workletLoop = spec
    this.workletLoopKnown = true
  }

  /**
   * Controlled transition (§13.8): a synchronized re-seek to
   * `sourceFrame` with the loop state the transport now holds (an
   * enable/disable, a boundary edit, or a completion restart). The
   * flush drops buffered content — the periodic stream is refetched —
   * so the audible position continues exactly where it was.
   */
  private transitionTo(sourceFrame: number): void {
    const wasPlaying = this.desiredPlaying
    const wasActive = this.isActiveState(this.state)
    this.flushBookkeeping(sourceFrame)
    // Mid-playback transitions surface as `seeking` (the refill completes
    // the start); from stopped states the `play` flow decides the state
    // (`preparing`, or the preserved `buffering`).
    if (wasPlaying && wasActive) this.setState('seeking')
    const align = this.alignWorklet()
    if (align === undefined) {
      void this.runFill()
    } else {
      void align.then(() => {
        if (this.desiredPlaying && this.state === 'seeking') void this.runFill()
      })
    }
  }

  /** §14.1 (M2.12) budget: the group ring capacity in frames. */
  private get budgetFrames(): number {
    return this.bufferCapacity
  }

  /** §15.3 gate margin: one 1 s chunk, at most a quarter of the ring. */
  private get marginFrames(): number {
    if (!this.primary || this.bufferCapacity <= 0) return 0
    return Math.min(
      Math.ceil(this.primary.sampleRate * CHUNK_SECONDS),
      Math.floor(this.bufferCapacity / 4),
    )
  }

  /** §15.4 post-underrun start threshold: 2 s, at most half the ring. */
  private get startThresholdFrames(): number {
    if (!this.primary || this.bufferCapacity <= 0) return 0
    return Math.min(
      Math.ceil(this.primary.sampleRate * PREBUFFER_SECONDS),
      Math.floor(this.bufferCapacity / 2),
    )
  }

  private isActiveState(s: TransportState): boolean {
    return s === 'preparing' || s === 'playing' || s === 'buffering' || s === 'seeking'
  }

  /**
   * Normalize and hard-validate the mix sources (M2.8, spec §10.5):
   * every source must match the project rate and duration. A mismatch is
   * a prepare error — the transport never resamples.
   */
  private normalizeSources(opts: LoadSourceOptions): SourceSpec[] {
    const specs = opts.sources ?? (opts.target ? [opts.target] : [])
    if (specs.length === 0) throw new RangeError('at least one source is required')
    for (const s of specs) {
      if (s.sampleRate !== opts.projectRate) {
        throw new RangeError(
          `source ${s.assetId}: sample rate ${s.sampleRate} does not match the ` +
            `project rate ${opts.projectRate} (no resampling)`,
        )
      }
      if (s.frameCount !== opts.projectDurationFrames) {
        throw new RangeError(
          `source ${s.assetId}: ${s.frameCount} frames does not match the ` +
            `project duration ${opts.projectDurationFrames}`,
        )
      }
    }
    return specs
  }

  /**
   * Bind the mix sources to this transport. No audio graph is created
   * yet; `play` does that on a user gesture (spec §14.4).
   */
  async loadSource({
    sources,
    target,
    projectRate,
    projectDurationFrames,
  }: LoadSourceOptions): Promise<void> {
    this.sources = this.normalizeSources({
      sources,
      target,
      projectRate,
      projectDurationFrames,
    })
    this.projectRate = projectRate
    this.projectDurationFrames = projectDurationFrames
    // A new source set has new channel counts: rebuild the pin (M2.12).
    this.syncPin()
    // A pre-target park (M1.15 §17.6.4): first play starts from there.
    if (this.parkedProjectFrame > 0) {
      const primary = this.primary
      if (!primary) throw new RangeError('at least one source is required')
      const frame = clampToDuration(
        playbackPosition(this.parkedProjectFrame, projectRate, primary.sampleRate),
        primary.frameCount,
      )
      this.genStartFrame = frame
      // Fetch the §12.3 pre-roll so a wet start can warm up inaudibly.
      this.fetchedFrame = Math.max(0, frame - PRE_ROLL_FRAMES)
      this.consumedFrame = frame
      this.parkedProjectFrame = 0
      this.reportPosition()
    }
  }

  /**
   * Rebind to a new set of mix sources after context loss
   * (spec §15.6): discards the dead graph, keeps the retained position,
   * and parks the playhead there. The next `play` creates a fresh
   * context and starts from the retained position.
   */
  rebind({ sources, target, projectRate, projectDurationFrames }: LoadSourceOptions): void {
    if (this.disposed) return
    this.teardownGraph()
    this.sources = this.normalizeSources({
      sources,
      target,
      projectRate,
      projectDurationFrames,
    })
    this.projectRate = projectRate
    this.projectDurationFrames = projectDurationFrames
    this.contextLost = false
    // New source set (new channel counts): rebuild the pin (M2.12).
    this.syncPin()
    this.lastError = null
    this.suspended = false
    this.generation = 0
    this.abort = new AbortController()
    const primary = this.primary
    if (!primary) throw new RangeError('at least one source is required')
    const frame = clampToDuration(
      playbackPosition(this.retainedProjectFrame, projectRate, primary.sampleRate),
      primary.frameCount,
    )
    this.genStartFrame = frame
    // Fetch the §12.3 pre-roll so a wet resume can warm up inaudibly.
    this.fetchedFrame = Math.max(0, frame - PRE_ROLL_FRAMES)
    this.consumedFrame = frame
    this.hasData = false
    this.bufferedFrames = 0
    this.workerPaused = false
    this.lastFlushedGeneration = -1
    // Underrun/byte counters restart per load, but the ring capacity and
    // the pin are fixed properties of the group graph (M2.12 §14.1):
    // keep reporting them so diagnostics do not flicker between seeks.
    this.diagnosticsState = initialTransportDiagnostics()
    this.diagnosticsState.capacityFrames = this.bufferCapacity
    this.diagnosticsState.budgetBytes = this.sources.reduce(
      (bytes, s) => bytes + this.bufferCapacity * s.channelCount * BYTES_PER_SAMPLE,
      0,
    )
    this.diagnosticsState.pinnedBytes = this.pin ? this.pin.bytes : 0
    this.setState('unloaded')
    this.reportPosition()
  }

  /** Start (or resume) playback from the current position. */
  async play(): Promise<void> {
    if (this.disposed || this.sources.length === 0) return
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
    const wasEnded = this.state === 'ended'
    const wasUnloaded = this.state === 'unloaded' || this.state === 'error'
    // §13.4.2/§13.4.7: with the loop enabled and the position outside
    // `[start, end)` — including the completion position `== end` and
    // the ended state — playback starts with a synchronized seek to the
    // loop start. A finite sequence that stopped with looping since
    // disabled restarts linearly from its stop position (the fresh seek
    // also clears the worklet's completion freeze).
    const startFrame = this.loopStartIfOutside()
    if (wasEnded) {
      this.transitionTo(startFrame ?? 0)
    } else if (startFrame !== null) {
      this.transitionTo(startFrame)
    } else if (this.loopStoppedSource !== null) {
      this.transitionTo(this.loopStoppedSource)
    } else if (!wasUnloaded && this.node !== null && this.loopStateChanged()) {
      // §13.4.1: the loop was enabled/disabled while not playing, so the
      // worklet does not have it yet. Install it mid-stream when the
      // buffered content is still the loop's first pass; otherwise
      // rebuffer the periodic stream from the current position.
      if (this.midStreamInstallSafe()) {
        this.installLoopMidStream(this.workletLoopSpec())
      } else {
        this.transitionTo(this.currentSourceFrame())
      }
    }
    if (wasUnloaded) {
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
      // M2.11: the seek carries the loop shape, so a fresh graph starts
      // with the practice loop already in effect.
      try {
        this.pushSegment(this.context?.currentTime ?? 0, this.genStartFrame)
        this.node?.port.postMessage({
          type: 'seek',
          frame: this.fetchedFrame,
          audibleFrame: this.genStartFrame,
          generation: this.generation,
          loop: this.workletLoopSpec(),
        })
        this.workletLoop = this.workletLoopSpec()
        this.workletLoopKnown = true
        await this.alignWorklet()
      } catch (err) {
        this.fail(err)
        return
      }
    }
    if (wasEnded) {
      try {
        await this.alignWorklet()
      } catch (err) {
        this.fail(err)
        return
      }
    }
    this.node?.port.postMessage({ type: 'resume' })
    const stateNow = this.state as TransportState
    if (stateNow === 'buffering') {
      // Keep buffering: the 2 s start threshold decides on the next
      // `buffered` acknowledgment (spec §15.4).
    } else if (this.hasData) {
      this.setState('playing')
    } else if (stateNow !== 'seeking') {
      // A loop transition already put the transport in `seeking`; its
      // refill completes the start.
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
    if (this.context && this.primary) {
      // Freeze the playhead at the position extrapolated right now
      // (the audible position advances at `rate × anchorRate`).
      this.consumedFrame +=
        Math.max(0, this.context.currentTime - this.anchorTime) *
        this.primary.sampleRate *
        this.anchorRate
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
    const target = this.primary
    if (!target) {
      // No duration is known until the source loads; do not clamp to the
      // zero placeholder (the park survives to `loadSource`).
      const max =
        this.projectDurationFrames > 0 ? this.projectDurationFrames : Number.MAX_SAFE_INTEGER
      this.parkedProjectFrame = Math.max(0, Math.min(Math.floor(projectFrame), max))
      this.reportPosition()
      return
    }
    const frame = clampToDuration(
      playbackPosition(projectFrame, this.projectRate, target.sampleRate),
      target.frameCount,
    )
    // §13.4.5: a seek outside the enabled loop disables looping but keeps
    // the saved loop (the App persists `loop_enabled = false`).
    const loop = this.loop
    if (this.isLooping() && loop && (frame < loop.startFrame || frame >= loop.endFrame)) {
      this.loopEnabled = false
      this.loopStoppedSource = null
      this.syncPin()
      this.opts.onLoopDisabled?.()
    }
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
   * Install (or clear) the practice loop (M2.11 §13). The spec is in
   * source frames (validated by the domain). While playing this is a
   * controlled transition (§13.8): the stream re-seeks to the current
   * source position when it is inside the new range, else to the new
   * start. Boundary edits are committed by the UI on drag end, so one
   * drag is one transition. While not playing it only sets state
   * (§13.4.1); the next play/seek applies it.
   */
  setLoop(spec: TransportLoopSpec | null): void {
    if (this.disposed) return
    // The current source position under the loop that is in effect now.
    const currentSource = this.currentSourceFrame()
    const previous = this.loop
    const held = this.workletLoop
    this.loop = spec
    this.syncPin()
    if (!this.isPlayingLive()) return
    if (!spec || !this.loopEnabled) {
      // No loop in effect any more: continue linearly from the current
      // source position (a saved loop is retained, §13.4.5). While the
      // worklet holds no loop, storing the spec alone changes nothing —
      // no rebuffer needed.
      if (held === null) return
      if (previous && !this.fillRoundInFlight && this.fetchedFrame <= previous.endFrame) {
        // The buffered content is still the old loop's first pass — the
        // plain source — so dropping the loop mid-stream is exact.
        this.installLoopMidStream(null)
      } else {
        this.transitionTo(currentSource)
      }
      return
    }
    const inside = currentSource >= spec.startFrame && currentSource < spec.endFrame
    this.transitionTo(inside ? currentSource : spec.startFrame)
  }

  /**
   * Enable or disable the practice loop (M2.11 §13.4). While not playing
   * this only sets state (§13.4.1). While playing: enabling inside the
   * range continues from the current position — mid-stream with no
   * re-seek while the buffered content is still the loop's first pass,
   * else a synchronized rebuffered transition (§13.4.3); enabling
   * outside seeks to the loop start (§13.4.4); disabling returns to the
   * linear stream at the current source position (the loop stays saved,
   * §13.4.5).
   */
  setLoopEnabled(enabled: boolean): void {
    if (this.disposed) return
    if (this.loopEnabled === enabled) return
    // The current source position under the loop state in effect now.
    const currentSource = this.currentSourceFrame()
    if (!enabled) {
      const safe = this.midStreamInstallSafe()
      this.loopEnabled = false
      this.syncPin()
      // A completion stop position is a source frame — keep it so the
      // frozen playhead and the later linear restart stay put (§13.4.7);
      // the next flush clears it.
      if (!this.isPlayingLive()) return
      if (safe) {
        // The buffered content is still the loop's first pass, which is
        // the plain source: dropping the loop mid-stream continues
        // linearly from the same position.
        this.installLoopMidStream(null)
      } else {
        this.transitionTo(currentSource)
      }
      return
    }
    if (!this.loop) return
    this.loopEnabled = true
    this.loopStoppedSource = null
    this.syncPin()
    if (!this.isPlayingLive()) return
    const loop = this.loop
    if (currentSource < loop.startFrame || currentSource >= loop.endFrame) {
      // §13.4.4: enabling while playing outside → synchronized seek.
      this.transitionTo(loop.startFrame)
    } else if (this.midStreamInstallSafe()) {
      // §13.4.3: the buffered content is still inside the loop — it is
      // exactly the first pass — so playback continues from the current
      // position with no re-seek (the first pass is partial and counts
      // as pass 1).
      this.installLoopMidStream(this.workletLoopSpec())
    } else {
      this.transitionTo(currentSource)
    }
  }

  /**
   * M2.12 §14.1.4: (re)install the pinned-loop cache. A pin exists while
   * an enabled loop fits the remaining group pin budget
   * (`PINNED_BYTES_MAX`, one pin at a time across the group); a changed
   * or disabled loop releases the old pin and streaming continues
   * unchanged. Seeks inside the range keep the pin: every pass and every
   * seek is served from the same immutable arrays.
   */
  private syncPin(): void {
    const loop = this.loopEnabled ? this.loop : null
    const current = this.pin
    const matches =
      current !== null &&
      loop !== null &&
      current.startFrame === loop.startFrame &&
      current.endFrame === loop.endFrame
    if (!matches) {
      if (loop && loop.endFrame > loop.startFrame && this.sources.length > 0) {
        const bytes =
          (loop.endFrame - loop.startFrame) *
          this.sources.reduce((sum, s) => sum + 4 * s.channelCount, 0)
        this.pin =
          bytes <= PINNED_BYTES_MAX
            ? new LoopPin({
                startFrame: loop.startFrame,
                endFrame: loop.endFrame,
                channelCounts: this.sources.map((s) => s.channelCount),
              })
            : null
      } else {
        this.pin = null
      }
    }
    this.diagnosticsState.pinnedBytes = this.pin ? this.pin.bytes : 0
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
   * Set one source's mixer parameters (spec §10.3). `gain` is linear
   * amplitude; the worklet ramps the change over 5 ms. No-op until the
   * graph exists — re-apply after (re)load.
   */
  setSourceParams(index: number, patch: SourceParamPatch): void {
    if (!this.node) return
    this.node.port.postMessage({ type: 'params', source: index, ...patch })
  }

  /**
   * Set the master monitoring gain (linear amplitude, spec §10.3.8).
   * Applied in the worklet mixer — never to the stored samples.
   * Remembered and applied to a fresh graph on `play`.
   */
  /**
   * Replace the upcoming metronome schedule. Clicks are absolute render
   * frames (context time × sample rate); the worklet keeps only the
   * bounded lookahead it receives.
   */
  scheduleMetronome(clicks: MetronomeClickSpec[], volume?: number): void {
    this.node?.port.postMessage({ type: 'metronome', clicks, volume })
  }

  /**
   * Host a compact musical-grid schedule (M3.17 §19.8). The transport
   * owns the revision so a stale schedule can never overwrite a newer
   * one; worklet message details stay private to this layer.
   */
  setMusicalGrid(grid: MusicalGridSchedule | null): void {
    if (grid === null) {
      this.musicalGridRevision = -1
      this.musicalGrid = []
      return
    }
    if (grid.revision < this.musicalGridRevision) return
    this.musicalGridRevision = grid.revision
    this.musicalGrid = grid.events
  }

  /** Forget a grid schedule at or below `revision` (stale-revision guard). */
  invalidateGridSchedule(revision: number): void {
    if (revision < this.musicalGridRevision) return
    this.musicalGridRevision = -1
    this.musicalGrid = []
  }

  /** The currently hosted grid revision and its bounded event list. */
  gridSchedule(): { revision: number; events: readonly MusicalGridEvent[] } {
    return { revision: this.musicalGridRevision, events: this.musicalGrid }
  }

  /**
   * Apply metronome settings. Clicks are absolute render frames; an empty
   * list clears the worklet's lookahead.
   */
  setMetronomeState(state: MetronomeTransportState): void {
    this.metronomeState = state
    this.node?.port.postMessage({
      type: 'metronome',
      clicks: state.clicks,
      volume: state.volume,
    })
  }

  /** Remember the count-in clicks that `prepareCountInAndPlay` will use. */
  setCountIn(state: CountInTransportState): void {
    this.countInState = state
  }

  /**
   * Schedule the count-in clicks and start playback from the current
   * position (M3.17 §19.8). Count-in audio is heard before project audio
   * only when the caller has advanced the position itself.
   */
  async prepareCountInAndPlay(): Promise<void> {
    if (this.countInState !== null) {
      this.scheduleMetronome(this.countInState.clicks, this.countInState.volume)
    }
    await this.play()
  }

  /** The last metronome settings applied through this transport. */
  metronomeSettings(): MetronomeTransportState | null {
    return this.metronomeState
  }

  setMasterGain(gain: number): void {
    const clamped = Math.max(0, Number.isFinite(gain) ? gain : 0)
    this.pendingMasterGain = clamped
    if (this.node) this.node.port.postMessage({ type: 'master', gain: clamped })
  }

  /**
   * Set the playback speed (0.25…2.0, spec §11). The worklet engine
   * owns the ≈50 ms rate ramp; the transport remembers the speed for a
   * fresh graph and scales the source-frame consumption estimates. A
   * change on a live graph starts a new mapping segment (§11.7.5).
   */
  setRate(speed: number): void {
    const clamped = Math.max(0.25, Math.min(2.0, Number.isFinite(speed) ? speed : 1))
    // The UI re-applies the full mixer state on every practice-state update
    // (the 5 s playhead autosave). An unchanged rate must not add a timing
    // segment: its coordinate is clamped to the project duration, while a
    // looped stream is unbounded, so repeated segments would make the
    // audible-position mapping jump after the first loop pass.
    if (clamped === this.speed) return
    this.speed = clamped
    // Optimistic: the worklet's next anchor confirms the ramped rate.
    this.anchorRate = clamped
    const node = this.node
    if (!node) return
    const context = this.context
    const target = this.primary
    if (context && target && this.isActiveState(this.state)) {
      const now = context.currentTime
      // Segment coordinates are stream coordinates: do not clamp a looped
      // stream to the project frame count (the linear mapping clamps in
      // getAudiblePosition when needed).
      const frame = Math.max(
        0,
        Math.round(
          this.consumedFrame +
            Math.max(0, now - this.anchorTime) * target.sampleRate * this.anchorRate,
        ),
      )
      this.pushSegment(now, frame)
    }
    node.port.postMessage({ type: 'rate', value: clamped })
  }

  /**
   * Enable or disable the monitoring limiter live (spec §10.6.6).
   * Rewires the gain stage on a live graph; always remembered for a
   * fresh graph. The audible-time mapping follows `limiterNode`.
   */
  setLimiter(enabled: boolean): void {
    this.opts.limiter = enabled
    const context = this.context
    const gainNode = this.gainNode
    if (!context || !gainNode) return
    if (enabled) {
      if (this.limiterNode) return
      if (typeof context.createDynamicsCompressor !== 'function') return
      gainNode.disconnect()
      const limiter = context.createDynamicsCompressor()
      limiter.threshold.value = LIMITER_THRESHOLD_DB
      gainNode.connect(limiter)
      limiter.connect(context.destination)
      this.limiterNode = limiter
    } else {
      this.limiterNode?.disconnect()
      this.limiterNode = null
      gainNode.disconnect()
      gainNode.connect(context.destination)
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
    // M2.12 §14.1.4: drop the pinned-loop cache with the transport.
    this.pin = null
    const context = this.context
    this.teardownGraph()
    if (context && context.state !== 'closed') {
      void context.close().catch(() => {})
    }
  }

  /**
   * Create context, shared rings (one per source), worklet node, gain
   * stage, optional limiter, and the fetch source.
   */
  private async initGraph(): Promise<void> {
    const target = this.primary
    if (!target) throw new Error('No sources loaded')
    const context = this.opts.contextFactory()
    if (context.state === 'suspended') await context.resume()
    this.context = context
    context.onstatechange = () => this.onContextStateChange()
    this.mode = resolveMode(this.opts.mode ?? 'auto')
    // M2.12 §14.1: one sizing policy for the whole group — the byte and
    // duration caps minimised over the active sources. The worklet gets
    // the same number (shared rings derive it from the SAB, transfer
    // rings from `processorOptions`), so both paths agree by
    // construction.
    const capacity = sourceBufferCapacityFrames(this.sources)
    this.bufferCapacity = capacity
    this.diagnosticsState.capacityFrames = capacity
    this.diagnosticsState.budgetBytes = this.sources.reduce(
      (bytes, s) => bytes + capacity * s.channelCount * BYTES_PER_SAMPLE,
      0,
    )
    if (this.mode === 'shared') {
      // One ring per source; every ring gets the group capacity so the
      // stems stay one synchronized set (spec §14.2).
      this.rings = this.sources.map((s) =>
        createSharedRing(16 + capacity * s.channelCount * 4, s.channelCount),
      )
    }
    // M2.9 (spec §11.3.11): the engine artifact is loaded on the main
    // thread and transferred to the worklet (no fetch in the worklet).
    const stretchBytes = await this.fetchStretchBytes()
    this.stretchInputLatency = 0
    this.stretchOutputLatency = 0
    // The blob prepends the stretch core (plain script, no imports): a
    // blob URL has no base for relative imports, so the worklet gets
    // `globalThis.StretchWasm` by concatenation (M2.9, spec §11).
    const workletSource = `${stretchWorkletSource}\n${processorSource}`
    this.blobUrl = this.opts.moduleUrlFactory
      ? this.opts.moduleUrlFactory(workletSource)
      : URL.createObjectURL(new Blob([workletSource], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(this.blobUrl)
    const sabs = this.rings.map((r) => r.sab)
    const options: Record<string, unknown> = {
      // The transport has no audio inputs (it feeds the rings) and the
      // worklet mixer always renders stereo (spec §10.5); without an
      // explicit output channel count a real browser gives the output
      // zero channels.
      numberOfInputs: 0,
      numberOfOutputs: 1,
      outputChannelCount: [2],
      processorOptions: {
        sampleRate: target.sampleRate,
        frameCount: target.frameCount,
        // M2.12 §14.1: the group ring capacity the worklet must use.
        capacityFrames: capacity,
        // Mixer path (M2.8): the worklet mixes all sources on one cursor.
        sources: this.sources.map((s) => ({ channelCount: s.channelCount })),
        ...(sabs.length > 0 ? { sabs } : {}),
        // M2.9: the engine instantiates synchronously from the bytes.
        stretch: { wasmBytes: stretchBytes },
      },
    }
    // The WASM artifact is a real ArrayBuffer and is transferred; the
    // rings are `SharedArrayBuffer`s, which serialize by sharing into
    // `processorOptions.sabs` and must stay out of the transfer list
    // (a browser throws "Shared memory objects must not be in the
    // transfer list" otherwise).
    options.transfer = [stretchBytes]
    const node = createTransportWorkletNode(context, 'basseparate-pcm', options)
    node.port.onmessage = (e) => this.handleWorkletMessage(e.data)
    const gainNode = context.createGain()
    gainNode.gain.value = this.pendingGain
    node.connect(gainNode)
    if (this.opts.limiter && typeof context.createDynamicsCompressor === 'function') {
      // Monitoring-only limiter (spec §10.6.5): after the gain, never in
      // the sample storage path.
      const limiter = context.createDynamicsCompressor()
      limiter.threshold.value = LIMITER_THRESHOLD_DB
      gainNode.connect(limiter)
      limiter.connect(context.destination)
      this.limiterNode = limiter
    } else {
      gainNode.connect(context.destination)
    }
    this.node = node
    this.gainNode = gainNode
    this.abort = new AbortController()
    this.anchorTime = context.currentTime
    this.source = this.createSource()
    if (sabs.length > 0) {
      await this.source.attachShared(
        sabs,
        this.sources.map((s) => s.channelCount),
      )
    }
    // Apply the pending mixer state to the fresh worklet.
    if (this.pendingMasterGain !== 1) {
      node.port.postMessage({ type: 'master', gain: this.pendingMasterGain })
    }
    if (this.speed !== 1) {
      node.port.postMessage({ type: 'rate', value: this.speed })
    }
  }

  /** Pick the fetch source: real worker when available, else main thread. */
  private createSource(): FetchSource {
    const channelCounts = this.sources.map((s) => s.channelCount)
    const factory = this.opts.workerFactory ?? defaultWorkerFactory
    const worker = factory()
    if (worker) return new WorkerFetchSource(worker, channelCounts)
    return new DirectFetchSource(
      (assetId, start, end) => this.opts.fetchChunk(assetId, start, end, this.abort?.signal),
      channelCounts,
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
    const seg: TransportSegment = {
      startContextTime,
      startFrame,
      generation: this.generation,
      speed: this.speed,
    }
    this.segments.push(seg)
    if (this.segments.length > MAX_SEGMENTS) {
      this.segments = this.segments.slice(-MAX_SEGMENTS)
    }
    // The segment start is a virtual anchor (the bookkeeping baseline).
    this.anchorSegment = seg
  }

  private flushBookkeeping(frame: number): void {
    const target = this.primary
    if (!target) return
    this.generation += 1
    this.abort?.abort()
    this.abort = new AbortController()
    const clamped = Math.max(0, Math.min(Math.floor(frame), target.frameCount))
    // M2.11 §13: the seek carries the loop shape; a looped stream is
    // rebased to `clamped` (source-aligned) and the worklet then reads
    // the ring linearly while the fetch cursor cycles.
    const loop = this.workletLoopSpec()
    // M2.10 §12.3 / M2.11 §13.7.4: fetch a pre-roll before the audible
    // boundary; the worklet starts hearing at `clamped` (the dry bypass
    // is exact at 1×; a wet start runs the silent warm-up from the
    // pre-roll). With a loop the pre-roll may reach before frame 0: a
    // negative stream coordinate maps (via the mod) to the loop's tail,
    // which is the periodic pre-roll §13.7.2 asks for.
    const fetchFrame =
      loop !== null ? clamped - PRE_ROLL_FRAMES : Math.max(0, clamped - PRE_ROLL_FRAMES)
    this.genStartFrame = clamped
    this.fetchedFrame = fetchFrame
    this.consumedFrame = clamped
    this.hasData = false
    this.bufferedFrames = 0
    this.workerPaused = false
    this.loopStoppedSource = null
    this.workletLoop = loop
    this.workletLoopKnown = true
    if (this.context) this.anchorTime = this.context.currentTime
    this.pushSegment(this.context ? this.context.currentTime : 0, clamped)
    this.source?.stop()
    this.node?.port.postMessage({
      type: 'seek',
      frame: fetchFrame,
      audibleFrame: clamped,
      generation: this.generation,
      loop,
    })
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
      // The writer index resets to the frame the worklet reads first:
      // the fetch frame, which leads the audible boundary by the pre-roll.
      this.source!.acknowledgeFlush(this.generation, this.fetchedFrame),
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

  /** Fold one worklet buffer report into the diagnostics ledger (M2.12). */
  private recordBufferReport(m: {
    stems?: number[]
    capacityFrames?: number
    callbackMs?: number
    stretcher?: { rate: number; bypass: boolean; warmup?: number }
  }): void {
    if (Array.isArray(m.stems)) {
      const stems = m.stems
      this.diagnosticsState.stemBufferedFrames = [...stems]
      let bytes = 0
      this.sources.forEach((s, i) => {
        bytes += Math.max(0, stems[i] ?? 0) * s.channelCount * BYTES_PER_SAMPLE
      })
      this.diagnosticsState.bufferedBytes = bytes
    }
    if (typeof m.capacityFrames === 'number' && m.capacityFrames > 0) {
      this.diagnosticsState.capacityFrames = m.capacityFrames
    }
    if (typeof m.callbackMs === 'number' && Number.isFinite(m.callbackMs)) {
      this.diagnosticsState.callbackDurationMs = m.callbackMs
    }
    if (m.stretcher !== undefined) {
      this.diagnosticsState.stretcher = {
        rate: m.stretcher.rate,
        bypass: m.stretcher.bypass,
        warmup: m.stretcher.warmup ?? 0,
      }
    }
  }

  private handleWorkletMessage(data: unknown): void {
    if (this.disposed) return
    if (typeof data !== 'object' || data === null) return
    const msg = data as { type: string; generation?: number }
    if (typeof msg.generation === 'number' && msg.generation !== this.generation) return
    switch (msg.type) {
      case 'buffered': {
        const m = msg as unknown as {
          frames: number
          queuedFrames: number
          stems?: number[]
          capacityFrames?: number
          callbackMs?: number
          stretcher?: { rate: number; bypass: boolean; warmup?: number }
        }
        this.bufferedFrames = m.frames
        if (m.frames > 0) this.hasData = true
        this.recordBufferReport(m)
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
        const m = msg as unknown as {
          frame: number
          time: number
          paused?: boolean
          rate?: number
          peaks?: MixPeaks
        }
        this.consumedFrame = m.frame
        this.anchorTime = m.time
        if (typeof m.rate === 'number' && m.rate > 0) this.anchorRate = m.rate
        this.anchorSegment = this.segmentAt(m.time)
        // Per-quantum peak metering (spec §10.3.7), mixer path only.
        if (m.peaks) this.opts.onPeaks?.(m.peaks)
        this.reportPosition()
        break
      }
      case 'stretch-ready': {
        // M2.9: engine latencies (source frames) at the context rate.
        // The audible-time mapping folds the input latency in (the
        // anchor reports the consumed cursor, which leads the audible
        // output); the output latency feeds the M2.10 ledger.
        const m = msg as unknown as { inputLatency: number; outputLatency: number }
        this.stretchInputLatency = m.inputLatency
        this.stretchOutputLatency = m.outputLatency
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
      case 'loop-complete': {
        // M2.11 §13.4.6: a finite repeat sequence finished. The worklet
        // froze exactly at the final pass end (silence after it); park
        // the transport there — the loop end, not the wrapped start.
        const m = msg as unknown as { frame: number; time: number }
        this.consumedFrame = m.frame
        this.anchorTime = m.time
        this.anchorSegment = this.segmentAt(m.time)
        this.loopStoppedSource = this.loop ? this.loop.endFrame : null
        this.desiredPlaying = false
        this.source?.stop()
        this.abort?.abort()
        this.setState('paused')
        this.reportPosition()
        break
      }
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
      this.limiterNode?.disconnect()
    } catch {
      // The graph may already be gone.
    }
    this.node = null
    this.gainNode = null
    this.limiterNode = null
    this.rings = []
    // A fresh graph starts with no loop installed (M2.11): the next
    // seek carries the shape again.
    this.workletLoop = null
    this.workletLoopKnown = false
    if (this.blobUrl?.startsWith('blob:')) URL.revokeObjectURL(this.blobUrl)
    this.blobUrl = null
    this.context = null
    // A fresh context starts a fresh time base; old segments would map
    // new context times to the dead representation (spec §16.2.3).
    this.segments = []
    this.stretchInputLatency = 0
    this.stretchOutputLatency = 0
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
   * Prefetch loop: keep the worklet fed to the §14.1 target ahead of the
   * estimated consumed position, gated by the group ring budget. A
   * single loop outlives generation bumps: a seek/stop aborts in-flight
   * fetches and the parking delay, the loop wakes, and refetches from the
   * new bookkeeping. Runs while `desiredPlaying` and the state is active.
   */
  private async runFill(): Promise<void> {
    if (this.fillLoopRunning || this.disposed) return
    this.fillLoopRunning = true
    try {
      while (!this.disposed && this.desiredPlaying && this.node && this.primary && this.source) {
        const s = this.state
        if (s !== 'preparing' && s !== 'playing' && s !== 'buffering' && s !== 'seeking') return
        const target = this.primary
        const rate = target.sampleRate
        // M2.11 §13: a looped stream is unbounded (the fetch cursor
        // cycles through the pass); otherwise the source length caps the
        // fill. The loop in effect is the one the worklet holds.
        const loop = this.workletLoop !== null ? this.loop : null
        // M2.10: the audible position advances at `rate × anchorRate`
        // frames/s, so the fill budget scales with the anchor's rate.
        const consumedEstimate =
          this.consumedFrame +
          (this.context && !this.suspended
            ? Math.max(0, this.context.currentTime - this.anchorTime) * rate * this.anchorRate
            : 0)
        // M2.12 §14.1: the speed-scaled target (M2.10's `rate × speed ×
        // 8 s`) is clamped to what the ring can hold, so the flow-control
        // gate can never deadlock against a byte-capped capacity.
        const speedTarget = rate * this.speed * LOOKAHEAD_SECONDS
        const ringLimit = Math.max(0, this.budgetFrames - this.marginFrames)
        const targetAhead = Math.min(
          loop
            ? speedTarget
            : Math.min(
                speedTarget,
                Math.max(
                  rate * this.speed * PREBUFFER_SECONDS,
                  target.frameCount - this.genStartFrame,
                ),
              ),
          ringLimit,
        )
        let fetched = false
        while (
          (loop !== null || this.fetchedFrame < target.frameCount) &&
          this.fetchedFrame - consumedEstimate < targetAhead &&
          !this.workerPaused &&
          this.bufferedFrames < this.budgetFrames - this.marginFrames
        ) {
          // M2.11 §13.7.1: with a loop the source frame of the fetch
          // cursor comes from the mod mapping and the chunk is clamped
          // to the pass end, so the byte range never crosses a wrap.
          const sourceCursor = loop ? this.sourceFromStream(this.fetchedFrame) : this.fetchedFrame
          const passEnd = loop ? loop.endFrame : target.frameCount
          const frames = Math.min(rate * CHUNK_SECONDS, passEnd - sourceCursor)
          if (frames <= 0) break
          const gen = this.generation
          // One round fetches the same frame range for every source
          // (shared cursor, M2.8); the cursor advances by the minimum
          // written, so the sources can never drift apart.
          let roundFailed = false
          let written = Infinity
          this.fillRoundInFlight = true
          const pin = this.pin
          for (let i = 0; i < this.sources.length; i++) {
            const src = this.sources[i]
            const bytesPerFrame = 4 * src.channelCount
            const start = Math.floor(sourceCursor * bytesPerFrame)
            const end = start + frames * bytesPerFrame - 1
            let w = 0
            // M2.12 §14.1.4: a ready pin serves the whole range with no
            // network round trip — every pass and every seek inside the
            // loop (the pre-roll is mapped into the loop tail and hits
            // the pin the same way).
            if (pin && pin.ready && pin.covers(sourceCursor, frames)) {
              if (this.mode === 'shared') {
                w = pin.writeShared(this.rings[i], i, sourceCursor, frames)
              } else {
                const channels = pin.copyChannels(i, sourceCursor, frames)
                this.node.port.postMessage(
                  {
                    type: 'channels',
                    source: i,
                    channels,
                    startFrame: sourceCursor,
                    frames,
                    generation: gen,
                  },
                  channels.map((c) => c.buffer as ArrayBuffer),
                )
                w = frames
              }
            } else if (this.mode === 'shared') {
              // M2.12 §14.1.4: while the pin fills, the shared path asks
              // the worker for the payload so the frames can be retained
              // alongside the SAB write.
              const retain = pin !== null && pin.wantsChunk(i, sourceCursor, frames)
              let result: PcmWriteResult
              try {
                result = await this.source.writeChunk(i, src.assetId, start, end, gen, retain)
              } catch (err) {
                if (this.isStale(err, gen)) {
                  roundFailed = true
                  break
                }
                this.fail(err)
                return
              }
              if (gen !== this.generation) {
                roundFailed = true
                break
              }
              if (retain && result.channels) {
                pin.retain(i, result.startFrame, result.channels)
              }
              w = result.frames
            } else {
              let chunk: PcmChunk
              try {
                chunk = await this.source.fetchChunk(i, src.assetId, start, end, gen)
              } catch (err) {
                if (this.isStale(err, gen)) {
                  roundFailed = true
                  break
                }
                this.fail(err)
                return
              }
              if (gen !== this.generation) {
                roundFailed = true
                break
              }
              // Retain before relaying: the posted buffers are detached
              // by the transfer (M2.12 §14.1.4).
              if (pin) pin.retain(i, chunk.startFrame, chunk.channels)
              this.node.port.postMessage(
                {
                  type: 'channels',
                  source: i,
                  channels: chunk.channels,
                  startFrame: chunk.startFrame,
                  frames: chunk.frames,
                  generation: gen,
                },
                chunk.channels.map((c) => c.buffer as ArrayBuffer),
              )
              w = chunk.frames
            }
            if (w <= 0) {
              // A source's ring is full (flow control should make this
              // unreachable): drop the round and re-check after a park.
              this.diagnosticsState.droppedChunks += 1
              roundFailed = true
              break
            }
            if (w < written) written = w
          }
          if (roundFailed) break
          this.fetchedFrame += written
          fetched = true
        }
        this.fillRoundInFlight = false
        if (loop === null && this.fetchedFrame >= target.frameCount) return // 'ended' will arrive
        if (!fetched) await this.delay(FILL_CHECK_MS, this.abort?.signal)
        if (this.disposed) return
      }
    } finally {
      this.fillLoopRunning = false
      this.fillRoundInFlight = false
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
