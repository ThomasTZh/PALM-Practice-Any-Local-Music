/**
 * Playback transport (t2): the main-thread state machine that maps
 * output time to project frames.
 *
 * Responsibilities, ported from the proven legacy transport model:
 * - eight-stage lifecycle exposed as the contract's seven states
 *   (`unloaded → loading → paused/playing`, plus `seeking`, `buffering`
 *   and `error`);
 * - ranged PCM prefetch through `fetch-source.ts` (one shared cursor,
 *   periodic stream when a practice loop is active);
 * - seek generations so stale fetches can never feed the ring;
 * - anchor-based position mapping: the worklet reports exact
 *   `(streamFrame, contextTime, rate)` pairs, the transport
 *   extrapolates with the audio clock and maps loop stream coordinates
 *   back to project frames;
 * - live speed / pitch, beat-list metronome and count-in plumbing.
 *
 * The transport never touches samples; it moves frame ranges and posts
 * control messages. Audio-context and worklet creation are injectable,
 * so the state machine is testable without a browser audio stack.
 */

import {
  clampRate,
  clampTranspose,
  createSharedRing,
  wrapIndex,
  type SharedRing,
} from "./pcm";
import {
  createPcmSource,
  type PcmSource,
  type WorkerLike,
} from "./fetch-source";
import { StaleGenerationError, type FetchBytes } from "./fetch-core";
import {
  clampFrame,
  extrapolateStreamFrame,
  framesToSeconds,
  mapStreamToLoop,
} from "./time";
import processorSource from "./mix-processor.js?raw";
import stretchWorkletSource from "./stretch/stretch-worklet.js?raw";

export type TransportState =
  | "unloaded"
  | "loading"
  | "paused"
  | "playing"
  | "seeking"
  | "buffering"
  | "error";

export type TransportMode = "auto" | "shared" | "transfer";

export interface PlayerSource {
  url: string;
  sampleRate: number;
  channelCount: number;
  frameCount: number;
  /** Optional explicit stem set; the single-source shape is the mix only. */
  sources?: TransportSource[];
  /** Channel id used for the single-source shape (default "mix"). */
  id?: string;
}

/** One ranged PCM source in the aligned playback group. */
export interface TransportSource {
  /** Stable channel id: "mix" or a stem label (drums/bass/other/vocals). */
  id: string;
  url: string;
  /** Defaults to the group channel count. */
  channelCount?: number;
  /** Defaults to the group frame count; all sources must match. */
  frameCount?: number;
}

/** Per-channel mixer state, matching the UI's MixerController shape. */
export interface MixerChannelState {
  gainDb: number;
  pan: number;
  muted: boolean;
  soloed: boolean;
}

export type MixerState = Record<string, MixerChannelState>;

/** Bounded diagnostics for the status line (t9). */
export interface TransportDiagnostics {
  underruns: number;
  lastUnderrunAt: number | null;
  droppedChunks: number;
  bufferedFrames: number;
  capacityFrames: number;
  /** Decoder/engine latency reported by the worklet, in seconds. */
  latencySeconds: number;
  sourceIds: string[];
}

const MIN_GAIN_DB = -60;
const MAX_GAIN_DB = 6;

function clampGainDb(gainDb: number): number {
  if (!Number.isFinite(gainDb)) return 0;
  return Math.min(MAX_GAIN_DB, Math.max(MIN_GAIN_DB, gainDb));
}

function clampPan(pan: number): number {
  if (!Number.isFinite(pan)) return 0;
  return Math.min(1, Math.max(-1, pan));
}

export interface TransportLoop {
  startFrame: number;
  endFrame: number;
  repeatCount?: number | null;
  fade?: boolean;
}

export interface BeatSpec {
  frame: number;
  strength: "downbeat" | "beat" | "subdivision";
}

export interface TransportSnapshot {
  state: TransportState;
  positionFrame: number;
  durationFrames: number;
  speed: number;
  pitchSemitones: number;
  loop: TransportLoop | null;
  countInBars: number;
  error: string | null;
}

export interface WorkletNodeLike {
  port: {
    postMessage(message: unknown, transfer?: Transferable[]): void;
    onmessage: ((event: { data: unknown }) => void) | null;
  };
  connect?(destination: unknown): void;
  disconnect?(): void;
}

export interface AudioContextLike {
  currentTime: number;
  sampleRate: number;
  destination?: unknown;
  audioWorklet?: { addModule(url: string): Promise<void> };
  resume?(): Promise<void>;
  close?(): Promise<void>;
}

export interface TransportOptions {
  /** Existing context factory; a fresh context is created otherwise. */
  contextFactory?: () => AudioContextLike;
  /** Worklet node factory; the real Blob-URL module is created otherwise. */
  workletFactory?: (
    context: AudioContextLike,
    processorOptions: Record<string, unknown>,
  ) => WorkletNodeLike | Promise<WorkletNodeLike>;
  fetchBytes?: FetchBytes;
  workerFactory?: (() => WorkerLike | null) | null;
  mode?: TransportMode;
  /** Stretch WASM bytes, or a loader; scalar artifact is loaded otherwise. */
  stretchBytes?: ArrayBuffer | Uint8Array | (() => Promise<ArrayBuffer>);
  maxFrames?: number;
  capacityFrames?: number;
  prebufferFrames?: number;
  lookaheadFrames?: number;
  chunkFrames?: number;
  /** Stream pre-roll fetched before the audible boundary (engine warm-up). */
  preRollFrames?: number;
  metronomeVolume?: number;
}

interface Anchor {
  frame: number;
  time: number;
  rate: number;
  paused: boolean;
}

interface LoadedSource {
  id: string;
  url: string;
  channelCount: number;
  pcm: PcmSource;
  ring: SharedRing | null;
}

const DEFAULT_PREBUFFER_SECONDS = 2;
const DEFAULT_LOOKAHEAD_SECONDS = 4;
const DEFAULT_CHUNK_SECONDS = 1;
const DEFAULT_PRE_ROLL_FRAMES = 12_288;
/** Ring capacity for the shared path; the worklet mirrors this value. */
const DEFAULT_CAPACITY_SECONDS = 8;

function defaultContextFactory(): AudioContextLike | null {
  if (typeof AudioContext === "undefined") return null;
  return new AudioContext({
    latencyHint: "interactive",
  }) as unknown as AudioContextLike;
}

async function loadStretchBytes(): Promise<ArrayBuffer> {
  const url = new URL("./stretch/dist/stretch-scalar.wasm", import.meta.url);
  const response = await fetch(url);
  if (!response.ok)
    throw new Error(
      `stretch: failed to load the artifact (HTTP ${response.status})`,
    );
  return response.arrayBuffer();
}

async function defaultWorkletFactory(
  context: AudioContextLike,
  processorOptions: Record<string, unknown>,
): Promise<WorkletNodeLike> {
  const real = context as unknown as BaseAudioContext;
  const blob = new Blob([stretchWorkletSource, processorSource], {
    type: "application/javascript",
  });
  const url = URL.createObjectURL(blob);
  try {
    if (!real.audioWorklet)
      throw new Error("AudioWorklet is not available in this context");
    await real.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const node = new AudioWorkletNode(real, "basseparate-player", {
    numberOfInputs: 0,
    numberOfOutputs: 1,
    outputChannelCount: [2],
    processorOptions,
  });
  if (context.destination != null)
    node.connect(context.destination as AudioNode);
  return node as unknown as WorkletNodeLike;
}

/**
 * The transport. Construct it with an injected context factory in tests;
 * production uses the real AudioContext and the Blob-URL worklet.
 */
export class PcmTransport {
  private stateValue: TransportState = "unloaded";
  private errorValue: string | null = null;
  private readonly listeners = new Set<(snapshot: TransportSnapshot) => void>();
  private context: AudioContextLike | null = null;
  private ownsContext = false;
  private node: WorkletNodeLike | null = null;
  private loadedSources: LoadedSource[] = [];
  private asset: PlayerSource | null = null;
  private loaded = false;
  private desiredPlaying = false;
  private generation = 0;
  private anchor: Anchor | null = null;
  private pendingPosition = 0;
  private fetchedStream = 0;
  private filling = false;
  private bufferedFrames = 0;
  private speedValue = 1;
  private pitchValue = 0;
  private loopValue: TransportLoop | null = null;
  private countInBarsValue = 0;
  private tempoBpm = 120;
  private beatsPerBar = 4;
  private beats: BeatSpec[] = [];
  private metronomeVolume: number;
  private readonly prebufferFrames: number;
  private readonly lookaheadFrames: number;
  private readonly chunkFrames: number;
  private readonly preRollFrames: number;
  private readonly capacityFrames: number;
  private stretchReady: { inputLatency: number; outputLatency: number } | null =
    null;
  private mixerValue: MixerState = {};
  private readonly mixerListeners = new Set<(state: MixerState) => void>();
  private underruns = 0;
  private droppedChunks = 0;
  private lastUnderrunAt: number | null = null;
  private reachedEndValue = false;
  private seekResolver: {
    generation: number;
    resolve: () => void;
    timer: ReturnType<typeof setTimeout> | null;
  } | null = null;

  constructor(private readonly options: TransportOptions = {}) {
    this.prebufferFrames = options.prebufferFrames ?? 0;
    this.lookaheadFrames = options.lookaheadFrames ?? 0;
    this.chunkFrames = options.chunkFrames ?? 0;
    this.preRollFrames = options.preRollFrames ?? DEFAULT_PRE_ROLL_FRAMES;
    this.capacityFrames = options.capacityFrames ?? 0;
    this.metronomeVolume = options.metronomeVolume ?? 0.5;
  }

  // -- observable state -----------------------------------------------------

  get state(): TransportState {
    return this.stateValue;
  }

  get error(): string | null {
    return this.errorValue;
  }

  /** True after a natural end-of-source / finite-loop completion, not a seek. */
  get reachedEnd(): boolean {
    return this.reachedEndValue;
  }

  get durationFrames(): number {
    return this.asset?.frameCount ?? 0;
  }

  get sampleRate(): number {
    return this.asset?.sampleRate ?? this.context?.sampleRate ?? 48_000;
  }

  /** Loaded channel ids in playback order (mix first, then stems). */
  get sourceIds(): string[] {
    return this.loadedSources.map((source) => source.id);
  }

  get speed(): number {
    return this.speedValue;
  }

  get pitchSemitones(): number {
    return this.pitchValue;
  }

  get loop(): TransportLoop | null {
    return this.loopValue;
  }

  get countInBars(): number {
    return this.countInBarsValue;
  }

  get latencies(): { inputLatency: number; outputLatency: number } | null {
    return this.stretchReady;
  }

  get mode(): "shared" | "transfer" {
    return this.loadedSources.some((source) => source.ring !== null)
      ? "shared"
      : "transfer";
  }

  get diagnose(): TransportDiagnostics {
    return {
      underruns: this.underruns,
      lastUnderrunAt: this.lastUnderrunAt,
      droppedChunks: this.droppedChunks,
      bufferedFrames: this.bufferedFrames,
      capacityFrames: this.capacity(),
      latencySeconds: this.stretchReady
        ? (this.stretchReady.inputLatency + this.stretchReady.outputLatency) /
          this.sampleRate
        : 0,
      sourceIds: this.sourceIds,
    };
  }

  // -- mixer ---------------------------------------------------------------

  getMixerState(): MixerState {
    return Object.fromEntries(
      Object.entries(this.mixerValue).map(([id, channel]) => [
        id,
        { ...channel },
      ]),
    );
  }

  subscribeMixer(listener: (state: MixerState) => void): () => void {
    this.mixerListeners.add(listener);
    listener(this.getMixerState());
    return () => this.mixerListeners.delete(listener);
  }

  setGain(id: string, gainDb: number): void {
    this.updateMixer(id, { gainDb: clampGainDb(gainDb) });
  }

  setPan(id: string, pan: number): void {
    this.updateMixer(id, { pan: clampPan(pan) });
  }

  setMuted(id: string, muted: boolean): void {
    this.updateMixer(id, { muted: muted === true });
  }

  setSoloed(id: string, soloed: boolean): void {
    this.updateMixer(id, { soloed: soloed === true });
  }

  private emitMixer(): void {
    const snapshot = this.getMixerState();
    for (const listener of this.mixerListeners) listener(snapshot);
  }

  private updateMixer(id: string, change: Partial<MixerChannelState>): void {
    const current = this.mixerValue[id];
    if (!current) return;
    this.mixerValue = {
      ...this.mixerValue,
      [id]: { ...current, ...change },
    };
    const index = this.loadedSources.findIndex((source) => source.id === id);
    if (index >= 0 && this.node) {
      const channel = this.mixerValue[id];
      this.node.port.postMessage({
        type: "params",
        source: index,
        gain: Math.pow(10, channel.gainDb / 20),
        balance: channel.pan,
        mute: channel.muted,
        solo: channel.soloed,
      });
    }
    this.emitMixer();
  }

  /** Audible position in project frames. */
  get positionFrame(): number {
    if (!this.loaded) return 0;
    if (this.stateValue === "seeking") return this.pendingPosition;
    const anchor = this.anchor;
    if (
      anchor &&
      !anchor.paused &&
      (this.stateValue === "playing" || this.stateValue === "buffering")
    ) {
      const now = this.context?.currentTime ?? anchor.time;
      return this.mapStreamToProject(
        extrapolateStreamFrame(anchor, now, this.sampleRate),
      );
    }
    return this.pendingPosition;
  }

  get positionSeconds(): number {
    return framesToSeconds(this.positionFrame, this.sampleRate);
  }

  snapshot(): TransportSnapshot {
    return {
      state: this.stateValue,
      positionFrame: this.positionFrame,
      durationFrames: this.durationFrames,
      speed: this.speedValue,
      pitchSemitones: this.pitchValue,
      loop: this.loopValue,
      countInBars: this.countInBarsValue,
      error: this.errorValue,
    };
  }

  subscribe(listener: (snapshot: TransportSnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  private setState(state: TransportState): void {
    if (state === this.stateValue) return;
    this.stateValue = state;
    this.notify();
  }

  private notify(): void {
    const snapshot = this.snapshot();
    for (const listener of this.listeners) listener(snapshot);
  }

  private fail(error: unknown): void {
    this.errorValue = error instanceof Error ? error.message : String(error);
    this.desiredPlaying = false;
    // A failed load/seek leaves no playable source; `play()` must stay in
    // error instead of pretending the graph is usable.
    this.loaded = false;
    this.setState("error");
  }

  // -- lifecycle ------------------------------------------------------------

  /**
   * Load a source: build the context + worklet, bind the PCM source,
   * seek to frame 0 and prebuffer. Fetch failures land in the `error`
   * state; they are never thrown at the caller of `play`.
   */
  async load(source: PlayerSource): Promise<void> {
    if (!(source.sampleRate > 0))
      throw new RangeError("sampleRate must be > 0");
    if (!(source.channelCount >= 1))
      throw new RangeError("channelCount must be >= 1");
    if (!(source.frameCount >= 0))
      throw new RangeError("frameCount must be >= 0");
    let specs: ReturnType<PcmTransport["normalizeSources"]>;
    try {
      specs = this.normalizeSources(source);
    } catch (error) {
      this.fail(error);
      return;
    }
    this.teardownGraph();
    this.asset = source;
    this.errorValue = null;
    this.desiredPlaying = false;
    this.loopValue = null;
    this.pendingPosition = 0;
    this.anchor = null;
    this.bufferedFrames = 0;
    this.underruns = 0;
    this.droppedChunks = 0;
    this.lastUnderrunAt = null;
    this.reachedEndValue = false;
    this.mixerValue = Object.fromEntries(
      specs.map((spec) => [
        spec.id,
        { gainDb: 0, pan: 0, muted: false, soloed: false },
      ]),
    );
    this.setState("loading");
    try {
      const context = this.options.contextFactory
        ? this.options.contextFactory()
        : defaultContextFactory();
      if (!context) throw new Error("AudioContext is not available");
      this.context = context;
      this.ownsContext = !this.options.contextFactory;
      const stretchBytes = await this.resolveStretchBytes();
      const capacity =
        this.capacityFrames ||
        Math.ceil(source.sampleRate * DEFAULT_CAPACITY_SECONDS);
      const useShared =
        this.options.mode === "shared" ||
        (this.options.mode !== "transfer" &&
          typeof SharedArrayBuffer !== "undefined" &&
          (globalThis as { crossOriginIsolated?: boolean })
            .crossOriginIsolated === true);
      const rings = specs.map((spec) =>
        useShared ? createSharedRing(capacity, spec.channelCount) : null,
      );
      const processorOptions: Record<string, unknown> = {
        sampleRate: source.sampleRate,
        frameCount: source.frameCount,
        sources: specs.map((spec) => ({ channelCount: spec.channelCount })),
        capacityFrames: capacity,
        stretch: {
          wasmBytes: stretchBytes,
          ...(this.options.maxFrames
            ? { maxFrames: this.options.maxFrames }
            : {}),
        },
        metronomeVolume: this.metronomeVolume,
        rate: this.speedValue,
        transpose: this.pitchValue,
        ...(rings.some((ring) => ring !== null)
          ? { sabs: rings.map((ring) => ring?.sab) }
          : {}),
      };
      const factory = this.options.workletFactory ?? defaultWorkletFactory;
      this.node = await factory(context, processorOptions);
      this.node.port.onmessage = (event) => this.onMessage(event.data);
      const sources = await Promise.all(
        specs.map(async (spec, index) => {
          const ring = rings[index];
          const pcm = await createPcmSource({
            url: spec.url,
            channelCount: spec.channelCount,
            ...(ring ? { sab: ring.sab } : {}),
            ...(this.options.fetchBytes
              ? { fetchBytes: this.options.fetchBytes }
              : {}),
            ...(this.options.workerFactory !== undefined
              ? { workerFactory: this.options.workerFactory }
              : {}),
          });
          return {
            id: spec.id,
            url: spec.url,
            channelCount: spec.channelCount,
            pcm,
            ring: pcm.ring,
          } satisfies LoadedSource;
        }),
      );
      this.loadedSources = sources;
      this.loaded = true;
      this.generation += 1;
      this.postSeek(0);
      this.emitMixer();
      await this.fill(this.prebuffer());
      if (this.stateValue !== "error") this.setState("paused");
    } catch (error) {
      this.fail(error);
    }
  }

  /**
   * Resolve the single-source and multi-source shapes into one aligned
   * group. The server constructs every stem at the project rate and frame
   * count, so a mismatch is a boundary error, not something to resample.
   */
  private normalizeSources(source: PlayerSource): Array<{
    id: string;
    url: string;
    channelCount: number;
    frameCount: number;
  }> {
    const raw =
      source.sources && source.sources.length > 0
        ? source.sources
        : [
            {
              id: source.id ?? "mix",
              url: source.url,
              channelCount: source.channelCount,
              frameCount: source.frameCount,
            },
          ];
    const specs = raw.map((entry) => ({
      id: entry.id,
      url: entry.url,
      channelCount: entry.channelCount ?? source.channelCount,
      frameCount: entry.frameCount ?? source.frameCount,
    }));
    for (const spec of specs) {
      if (!spec.id) throw new RangeError("every source needs an id");
      if (!spec.url) throw new RangeError(`source ${spec.id} has no url`);
      if (!(spec.channelCount >= 1))
        throw new RangeError(`source ${spec.id} has an invalid channelCount`);
      if (spec.frameCount !== source.frameCount) {
        throw new RangeError(
          `source ${spec.id} has ${spec.frameCount} frames; expected ${source.frameCount}`,
        );
      }
    }
    const ids = new Set(specs.map((spec) => spec.id));
    if (ids.size !== specs.length)
      throw new RangeError("source ids must be unique");
    return specs;
  }

  /** Start (or resume) playback from the current position. */
  play(): void {
    if (!this.loaded) {
      this.fail(new Error("no source loaded"));
      return;
    }
    if (this.stateValue === "playing") return;
    this.desiredPlaying = true;
    if (this.stateValue === "buffering") return;
    if (this.stateValue === "seeking") return;
    const countIn = this.countInBarsValue > 0 && this.loopValue !== null;
    if (countIn) {
      this.node?.port.postMessage({
        type: "count-in",
        bars: this.countInBarsValue,
        beatsPerBar: this.beatsPerBar,
        beatFrames: this.beatFrames(),
      });
    }
    this.node?.port.postMessage({ type: "resume" });
    this.setState("playing");
    void this.fill(this.lookahead());
  }

  pause(): void {
    this.desiredPlaying = false;
    this.node?.port.postMessage({ type: "pause" });
    if (this.loaded && this.stateValue !== "error") this.setState("paused");
  }

  /** Seek to a project frame; keeps the play/pause intent. */
  seek(frame: number): void {
    if (!this.loaded) return;
    let target = this.clampProjectFrame(frame);
    if (this.loopValue) {
      // A seek inside an active loop stays inside it; the worklet would
      // otherwise disable the loop while the transport keeps feeding a
      // periodic stream.
      target = Math.max(
        this.loopValue.startFrame,
        Math.min(target, this.loopValue.endFrame),
      );
    }
    this.pendingPosition = target;
    this.anchor = null;
    this.reachedEndValue = false;
    this.setState("seeking");
    this.generation += 1;
    this.postSeek(target);
    void this.afterSeek();
  }

  setSpeed(rate: number): void {
    this.speedValue = clampRate(rate);
    this.node?.port.postMessage({ type: "rate", value: this.speedValue });
    // Speed changes are audible immediately; the anchor rate follows the
    // worklet's own 50 ms ramp, so no position jump is synthesized here.
    this.notify();
  }

  setPitch(semitones: number): void {
    this.pitchValue = clampTranspose(semitones);
    this.node?.port.postMessage({ type: "transpose", value: this.pitchValue });
    this.notify();
  }

  /**
   * Install/clear the practice loop. A loop change needs a fresh
   * periodic stream, so this performs a controlled re-seek (the
   * transport requests the pre-roll before the audible boundary).
   */
  setLoop(loop: TransportLoop | null): void {
    if (loop) {
      const start = Math.max(0, Math.floor(loop.startFrame));
      const end = Math.min(
        this.durationFrames || Math.floor(loop.endFrame),
        Math.floor(loop.endFrame),
      );
      if (!(end > start)) {
        this.loopValue = null;
      } else {
        this.loopValue = {
          startFrame: start,
          endFrame: end,
          repeatCount: loop.repeatCount ?? null,
          fade: loop.fade !== false,
        };
      }
    } else {
      this.loopValue = null;
    }
    if (this.loaded) {
      const position = this.positionFrame;
      const loopValue = this.loopValue;
      const outside =
        loopValue !== null &&
        (position < loopValue.startFrame || position >= loopValue.endFrame);
      this.seek(outside && loopValue ? loopValue.startFrame : position);
    } else {
      this.notify();
    }
  }

  setBeats(beats: BeatSpec[]): void {
    this.beats = (beats ?? []).filter(
      (beat) =>
        beat &&
        Number.isFinite(beat.frame) &&
        (beat.strength === "downbeat" ||
          beat.strength === "beat" ||
          beat.strength === "subdivision"),
    );
    this.postMetronome();
  }

  setMetronomeVolume(volume: number): void {
    this.metronomeVolume = Number.isFinite(volume)
      ? Math.min(1, Math.max(0, volume))
      : 0;
    this.postMetronome();
  }

  setCountIn(bars: number): void {
    this.countInBarsValue = Math.max(0, Math.floor(bars));
    this.notify();
  }

  setTempo(bpm: number, beatsPerBar = 4): void {
    this.tempoBpm = Number.isFinite(bpm) && bpm > 0 ? bpm : 120;
    this.beatsPerBar = Math.max(1, Math.floor(beatsPerBar));
    this.notify();
  }

  /** Output frames per beat at the current tempo. */
  beatFrames(): number {
    return Math.max(1, Math.round((this.sampleRate * 60) / this.tempoBpm));
  }

  dispose(): void {
    this.teardownGraph();
    if (this.ownsContext && this.context?.close) void this.context.close();
    this.context = null;
    this.loaded = false;
    this.setState("unloaded");
  }

  // -- internals ------------------------------------------------------------

  private teardownGraph(): void {
    for (const source of this.loadedSources) source.pcm.dispose();
    this.loadedSources = [];
    this.node?.disconnect?.();
    this.node = null;
    this.stretchReady = null;
    this.loaded = false;
  }

  /** Shared ring/queue capacity the prefetch must stay inside. */
  private capacity(): number {
    return (
      this.capacityFrames ||
      Math.ceil(this.sampleRate * DEFAULT_CAPACITY_SECONDS)
    );
  }

  private async resolveStretchBytes(): Promise<ArrayBuffer> {
    const bytes = this.options.stretchBytes;
    if (bytes instanceof ArrayBuffer) return bytes;
    if (bytes instanceof Uint8Array) {
      return bytes.buffer.slice(
        bytes.byteOffset,
        bytes.byteOffset + bytes.byteLength,
      ) as ArrayBuffer;
    }
    if (typeof bytes === "function") return bytes();
    return loadStretchBytes();
  }

  private prebuffer(): number {
    return (
      this.prebufferFrames ||
      Math.ceil(this.sampleRate * DEFAULT_PREBUFFER_SECONDS)
    );
  }

  private lookahead(): number {
    return (
      this.lookaheadFrames ||
      Math.ceil(this.sampleRate * DEFAULT_LOOKAHEAD_SECONDS)
    );
  }

  private chunk(): number {
    return (
      this.chunkFrames || Math.ceil(this.sampleRate * DEFAULT_CHUNK_SECONDS)
    );
  }

  private clampProjectFrame(frame: number): number {
    if (!Number.isFinite(frame)) return 0;
    return Math.max(0, Math.min(Math.floor(frame), this.durationFrames));
  }

  /** Stream frame the transport must feed first for `audibleFrame`. */
  private fetchStartFor(audibleFrame: number): number {
    if (this.loopValue) return audibleFrame - this.preRollFrames;
    return Math.max(0, audibleFrame - this.preRollFrames);
  }

  private postSeek(audibleFrame: number): void {
    const fetchStart = this.fetchStartFor(audibleFrame);
    this.fetchedStream = fetchStart;
    // A newer seek supersedes any pending flush wait.
    if (this.seekResolver) {
      if (this.seekResolver.timer) clearTimeout(this.seekResolver.timer);
      this.seekResolver.resolve();
      this.seekResolver = null;
    }
    const loop = this.loopValue
      ? {
          start: this.loopValue.startFrame,
          end: this.loopValue.endFrame,
          repeatCount: this.loopValue.repeatCount ?? null,
          fade: this.loopValue.fade !== false,
        }
      : null;
    this.node?.port.postMessage({
      type: "seek",
      frame: fetchStart,
      audibleFrame,
      generation: this.generation,
      generations: this.loadedSources.map(() => this.generation),
      loop,
    });
    for (const source of this.loadedSources) {
      source.pcm.setGeneration(this.generation);
      // The writer index is absolute in stream coordinates (it may be
      // negative for loop pre-roll), so reset it with the generation.
      // Safe to do before the worklet processes the seek: the generation
      // mismatch keeps the reader silent until it adopts the new one.
      void source.pcm.acknowledgeFlush(this.generation, fetchStart);
    }
    this.anchor = {
      frame: audibleFrame,
      time: this.context?.currentTime ?? 0,
      rate: 1,
      paused: true,
    };
  }

  private async afterSeek(): Promise<void> {
    const generation = this.generation;
    await this.waitForFlush(generation);
    if (generation !== this.generation || !this.loaded) return;
    this.pendingPosition = this.positionFrame;
    this.setState(this.desiredPlaying ? "playing" : "paused");
    await this.fill(this.prebuffer());
  }

  private waitForFlush(generation: number): Promise<void> {
    return new Promise((resolve) => {
      const done = (): void => {
        if (this.seekResolver?.timer) clearTimeout(this.seekResolver.timer);
        this.seekResolver = null;
        resolve();
      };
      // Bounded wait: a wedged worklet must not leave the transport in
      // `seeking` forever (the graph can be rebuilt by the caller).
      const timer = setTimeout(() => {
        if (this.seekResolver?.generation === generation) done();
      }, 2000);
      this.seekResolver = { generation, resolve: done, timer };
    });
  }

  /** Stream position derived from the current anchor (for prefetch). */
  private streamPosition(): number {
    const anchor = this.anchor;
    if (!anchor) return this.fetchedStream;
    const now = this.context?.currentTime ?? anchor.time;
    return extrapolateStreamFrame(anchor, now, this.sampleRate);
  }

  private mapStreamToProject(streamFrame: number): number {
    return clampFrame(
      mapStreamToLoop(streamFrame, this.loopValue),
      this.durationFrames,
    );
  }

  /**
   * Prefetch until the ring holds `target` frames ahead of the
   * playhead, or the source ends. A loop stream wraps at the loop
   * boundary; the transport splits each request so the worklet always
   * receives contiguous passes in stream order.
   */
  private async fill(target: number): Promise<void> {
    if (this.filling || !this.loaded || this.loadedSources.length === 0) return;
    this.filling = true;
    try {
      while (this.loaded && this.loadedSources.length > 0) {
        const ahead = this.fetchedStream - this.streamPosition();
        if (ahead >= target) break;
        // Stay inside the shared ring / transfer queue: a chunk that would
        // overflow would desynchronise the group (one stem drops frames).
        if (ahead + this.chunk() > this.capacity()) break;
        const start = this.fetchedStream;
        const progressed = await this.feedRange(start, start + this.chunk());
        if (progressed <= 0) break;
        this.fetchedStream += progressed;
        if (!this.loopValue && this.fetchedStream >= this.durationFrames) break;
      }
    } catch (error) {
      // A seek bumped the generation while this round was in flight: the
      // result is intentionally discarded and the new position refills.
      if (error instanceof StaleGenerationError) {
        setTimeout(() => {
          if (this.loaded) void this.fill(this.lookahead());
        }, 0);
      } else if (this.loaded) {
        this.fail(error);
      }
    } finally {
      this.filling = false;
    }
  }

  /**
   * Fetch one stream range. Returns the contiguous frames delivered (a
   * short count means the ring is full and the prefetch loop must wait
   * for consumption). Loop streams are split at pass boundaries.
   */
  private async feedRange(start: number, end: number): Promise<number> {
    if (this.loadedSources.length === 0) return 0;
    let cursor = start;
    while (cursor < end) {
      let sourceStart: number;
      let take: number;
      if (this.loopValue) {
        const loop = this.loopValue;
        const length = loop.endFrame - loop.startFrame;
        sourceStart =
          loop.startFrame + wrapIndex(cursor - loop.startFrame, length);
        take = Math.min(end - cursor, loop.endFrame - sourceStart);
      } else {
        if (cursor >= this.durationFrames) return cursor - start;
        sourceStart = cursor;
        take = Math.min(end - cursor, this.durationFrames - cursor);
      }
      // Every stem reads the same source-frame range, in parallel, so the
      // group cannot drift: the fetched length is the group's step.
      const chunks = await Promise.all(
        this.loadedSources.map((source) =>
          source.pcm.fetchRange(sourceStart, sourceStart + take),
        ),
      );
      const frames = Math.min(...chunks.map((chunk) => chunk.frames));
      if (frames <= 0) return cursor - start;
      chunks.forEach((chunk, index) => this.deliver(chunk, index));
      cursor += frames;
      // A short read means the asset ended; a loop re-checks the pass map.
      if (frames < take && !this.loopValue) break;
    }
    return cursor - start;
  }

  private deliver(
    chunk: { frames: number; channels?: Float32Array[] },
    index: number,
  ): void {
    if (!chunk.channels || !this.node) return;
    this.node.port.postMessage(
      {
        type: "channels",
        source: index,
        frames: chunk.frames,
        channels: chunk.channels,
      },
      chunk.channels.map((channel) => channel.buffer as ArrayBuffer),
    );
  }

  private postMetronome(): void {
    this.node?.port.postMessage({
      type: "metronome",
      beats: this.beats,
      volume: this.metronomeVolume,
    });
  }

  private onMessage(data: unknown): void {
    const message = data as Record<string, unknown> | null;
    if (!message || typeof message !== "object") return;
    switch (message.type) {
      case "stretch-ready":
        this.stretchReady = {
          inputLatency: Number(message.inputLatency) || 0,
          outputLatency: Number(message.outputLatency) || 0,
        };
        return;
      case "anchor":
        this.anchor = {
          frame: Number(message.frame) || 0,
          time: Number(message.time) || 0,
          rate: Number(message.rate) || 1,
          paused: message.paused === true,
        };
        this.pendingPosition = this.mapStreamToProject(this.anchor.frame);
        if (this.stateValue === "buffering" && this.desiredPlaying)
          this.setState("playing");
        this.notify();
        return;
      case "flushed": {
        const resolver = this.seekResolver;
        if (resolver && resolver.generation === this.generation)
          resolver.resolve();
        return;
      }
      case "buffered":
        this.bufferedFrames = Number(message.frames) || 0;
        if (
          this.stateValue === "buffering" &&
          this.desiredPlaying &&
          this.bufferedFrames >= this.prebuffer()
        ) {
          this.setState("playing");
        }
        void this.fill(this.lookahead());
        return;
      case "underrun":
        this.underruns += 1;
        this.lastUnderrunAt = this.context?.currentTime ?? null;
        if (this.desiredPlaying && this.stateValue === "playing")
          this.setState("buffering");
        return;
      case "chunk-dropped":
        this.droppedChunks += 1;
        return;
      case "ended":
        this.desiredPlaying = false;
        this.reachedEndValue = true;
        this.pendingPosition = this.durationFrames;
        this.setState("paused");
        return;
      case "loop-complete":
        this.desiredPlaying = false;
        this.reachedEndValue = true;
        this.pendingPosition = this.loopValue
          ? this.loopValue.endFrame
          : this.positionFrame;
        this.setState("paused");
        return;
      default:
        return;
    }
  }
}
