/**
 * StudioPlayer adapter (t9): the bridge between the PcmTransport and the
 * UI's transport/mixer/practice seams.
 *
 * The factory loads a project's canonical mix plus its four stems from the
 * ranged PCM endpoints, plays them as one aligned group, and exposes:
 *
 * - `player`: t4's `StudioPlayer` (idle/loading/ready/playing/paused/ended/
 *   error, positions in seconds);
 * - `mixer`: per-stem gain (dB), pan, mute and solo; changes go to the
 *   audio-thread mixer without a restart;
 * - `practice`: speed, pitch, loop, count-in, metronome and accent controls
 *   mapped onto `PcmTransport`.
 *
 * Stem labels follow the server exactly: drums, bass, other, vocals. When the
 * stem set cannot be loaded (analysis-free project, cache evicted, HTTP
 * error) the factory falls back to the canonical mix and publishes a notice
 * the shell can show; playback still works.
 *
 * State mapping (fixed with the captain):
 * - engine unloaded -> idle
 * - loading / seeking / buffering -> loading
 * - playing -> playing, paused -> paused
 * - error -> error
 * - ended only when paused at the duration after a natural end (never while
 *   seeking/buffering, never for an active loop).
 */

import {
  clampPitchSemitones,
  clampSpeed,
  normalizeLoopRange,
  type LoopRange,
  type PlaybackStatus,
  type PlayerState,
  type StudioPlayer,
} from "../state/player";
import {
  gridBeatSpecs,
  loopFromSeconds,
  normalizeGrid,
  type PlaybackGrid,
  type PlaybackGridInput,
} from "./grid";
import {
  PcmTransport,
  type TransportDiagnostics,
  type TransportOptions,
  type TransportSource,
} from "./transport";

export const STEM_LABELS = ["drums", "bass", "other", "vocals"] as const;
export type StemLabel = (typeof STEM_LABELS)[number];

export interface MixerChannelState {
  gainDb: number;
  pan: number;
  muted: boolean;
  soloed: boolean;
}

export type MixerState = Record<string, MixerChannelState>;

export interface MixerController {
  getState(): MixerState;
  subscribe(listener: (state: MixerState) => void): () => void;
  setGain(channelId: string, gainDb: number): void;
  setPan(channelId: string, pan: number): void;
  setMuted(channelId: string, muted: boolean): void;
  setSoloed(channelId: string, soloed: boolean): void;
}

export interface PracticeState {
  speed: number;
  pitchSemitones: number;
  loopEnabled: boolean;
  countInBars: number;
  metronomeEnabled: boolean;
  metronomeVolume: number;
  accentDownbeat: boolean;
}

export interface PracticeController {
  getState(): PracticeState;
  subscribe(listener: (state: PracticeState) => void): () => void;
  setSpeed(speed: number): void;
  setPitchSemitones(semitones: number): void;
  setLoopEnabled(enabled: boolean): void;
  setCountInBars(bars: number): void;
  setMetronomeEnabled(enabled: boolean): void;
  setMetronomeVolume(volume: number): void;
  setAccentDownbeat(enabled: boolean): void;
}

export const DEFAULT_PRACTICE_STATE: PracticeState = {
  speed: 1,
  pitchSemitones: 0,
  loopEnabled: false,
  countInBars: 0,
  metronomeEnabled: false,
  metronomeVolume: 0.5,
  accentDownbeat: true,
};

export interface StudioStemSource {
  /** Stem label: drums, bass, other or vocals. */
  id: string;
  /** Defaults to /api/projects/{projectId}/stems/{id}/pcm. */
  url?: string;
  channelCount?: number;
  frameCount?: number;
}

export interface StudioPlayerOptions {
  projectId: string;
  sampleRate: number;
  channelCount: number;
  frameCount: number;
  durationSeconds?: number;
  baseUrl?: string;
  mixUrl?: string;
  stems?: StudioStemSource[];
  grid?: PlaybackGridInput | null;
  transportOptions?: TransportOptions;
  /** Set false to construct the state machine without loading audio. */
  autoLoad?: boolean;
}

/** The engine bundle the app shell wires into panels. */
export interface StudioEngine {
  readonly player: StudioPlayer;
  readonly mixer: MixerController;
  readonly practice: PracticeController;
  readonly transport: PcmTransport;
  /** Resolves after the first load attempt (audio or mix fallback). */
  readonly ready: Promise<void>;
  getNotice(): string | null;
  subscribeNotice(listener: (notice: string | null) => void): () => void;
  diagnostics(): TransportDiagnostics;
  dispose(): void;
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

function clampCountInBars(bars: number): number {
  return Number.isFinite(bars) ? Math.min(2, Math.max(0, Math.round(bars))) : 0;
}

function clampMetronomeVolume(volume: number): number {
  return Number.isFinite(volume) ? Math.min(1, Math.max(0, volume)) : 0.5;
}

function joinUrl(base: string, path: string): string {
  const trimmed = base.replace(/\/+$/, "");
  return `${trimmed}${path}`;
}

/**
 * Build the factory options from a parsed project + optional analysis grid.
 * Kept as a pure helper so the shell does not have to know endpoint shapes.
 */
export function studioPlayerOptionsFromProject(
  project: {
    id: string;
    durationSeconds: number;
    asset: { sampleRate: number; channels: number };
    stems: Array<{ id: string; role?: string; audioUrl?: string }>;
    grid?: { bpm: number; meter: { numerator: number } } | null;
  },
  extras: {
    baseUrl?: string;
    grid?: PlaybackGridInput | null;
    transportOptions?: TransportOptions;
    /** Server frame count; wins over duration × sampleRate rounding. */
    frameCount?: number;
    channelCount?: number;
  } = {},
): StudioPlayerOptions {
  const sampleRate = project.asset.sampleRate;
  const frameCount = Math.max(
    0,
    Math.floor(extras.frameCount ?? project.durationSeconds * sampleRate),
  );
  const base = extras.baseUrl ?? "";
  const stems = project.stems.map((stem) => {
    const label =
      stem.role && (STEM_LABELS as readonly string[]).includes(stem.role)
        ? stem.role
        : stem.id;
    return {
      id: label,
      url:
        stem.audioUrl ??
        joinUrl(base, `/api/projects/${project.id}/stems/${label}/pcm`),
    };
  });
  return {
    projectId: project.id,
    sampleRate,
    channelCount: extras.channelCount ?? project.asset.channels,
    frameCount,
    durationSeconds: project.durationSeconds,
    baseUrl: base,
    stems,
    grid: extras.grid ?? {
      bpm: project.grid?.bpm ?? 120,
      bpb: project.grid?.meter.numerator ?? 4,
      beatsSeconds: [],
    },
    ...(extras.transportOptions
      ? { transportOptions: extras.transportOptions }
      : {}),
  };
}

function samePlayerState(a: PlayerState, b: PlayerState): boolean {
  return (
    a.status === b.status &&
    a.positionSeconds === b.positionSeconds &&
    a.durationSeconds === b.durationSeconds &&
    a.speed === b.speed &&
    a.pitchSemitones === b.pitchSemitones &&
    a.loopEnabled === b.loopEnabled &&
    a.loopRange === b.loopRange &&
    a.error === b.error
  );
}

/**
 * Create the real playback engine for one project. The returned `player`
 * satisfies t4's StudioPlayer seam; `mixer` and `practice` are the fixed
 * controller surfaces for the panels.
 */
export function createStudioPlayer(options: StudioPlayerOptions): StudioEngine {
  const sampleRate =
    Number.isFinite(options.sampleRate) && options.sampleRate > 0
      ? options.sampleRate
      : 48_000;
  const groupFrames = Math.max(0, Math.floor(options.frameCount));
  let configuredDuration = Math.max(
    0,
    options.durationSeconds ?? groupFrames / sampleRate,
  );
  const grid: PlaybackGrid = normalizeGrid(
    options.grid ?? {
      bpm: 120,
      bpb: 4,
      beatsSeconds: [],
    },
  );
  const transport = new PcmTransport({
    ...options.transportOptions,
    metronomeVolume: 0,
  });
  const base = options.baseUrl ?? "";
  const projectId = options.projectId;
  const mixUrl =
    options.mixUrl ?? joinUrl(base, `/api/projects/${projectId}/pcm`);
  const stems = (options.stems ?? []).map((stem) => ({
    id: stem.id,
    url:
      stem.url ??
      joinUrl(base, `/api/projects/${projectId}/stems/${stem.id}/pcm`),
    channelCount: stem.channelCount ?? options.channelCount,
    frameCount: stem.frameCount ?? groupFrames,
  }));

  let practice: PracticeState = { ...DEFAULT_PRACTICE_STATE };
  let practiceLoopRange: LoopRange | null = null;
  let practiceCache: PracticeState = { ...practice };
  let playerCache: PlayerState;
  let phase: "loading" | "ready" | "error" =
    options.autoLoad === false ? "ready" : "loading";
  let fatalError: string | null = null;
  let fallbackNotice: string | null = null;
  let noticeCache: string | null = null;
  let positionFallback = 0;
  let suppressEndAt = false;
  let ticker: ReturnType<typeof setInterval> | null = null;
  let disposed = false;

  const playerListeners = new Set<(state: PlayerState) => void>();
  const practiceListeners = new Set<(state: PracticeState) => void>();
  const noticeListeners = new Set<(notice: string | null) => void>();
  const mixerListeners = new Set<(state: MixerState) => void>();

  const durationFrames = (): number =>
    transport.durationFrames > 0 ? transport.durationFrames : groupFrames;
  const durationSeconds = (): number =>
    transport.durationFrames > 0
      ? transport.durationFrames / transport.sampleRate
      : configuredDuration;
  const currentPositionFrame = (): number =>
    transport.durationFrames > 0
      ? transport.positionFrame
      : Math.round(positionFallback * sampleRate);

  function computeNotice(): string | null {
    if (fatalError !== null) return null;
    if (transport.state === "buffering") return "Buffering audio…";
    if (transport.diagnose.droppedChunks > 0) {
      return "Audio buffer overflow; some frames were dropped.";
    }
    return fallbackNotice;
  }

  function status(): PlaybackStatus {
    if (fatalError !== null || transport.state === "error") return "error";
    if (phase === "loading") return "loading";
    const state = transport.state;
    if (state === "playing") return "playing";
    if (state === "seeking" || state === "buffering") return "loading";
    if (state === "unloaded") return durationSeconds() > 0 ? "paused" : "idle";
    if (state === "paused") {
      const atEnd =
        durationFrames() > 0 &&
        currentPositionFrame() >= durationFrames() - 1 &&
        transport.reachedEnd &&
        !(practice.loopEnabled && practiceLoopRange !== null);
      if (atEnd && !suppressEndAt) return "ended";
      return "paused";
    }
    return "paused";
  }

  function buildPlayerState(): PlayerState {
    return {
      status: status(),
      positionSeconds: Math.max(
        0,
        Math.min(
          durationSeconds(),
          transport.durationFrames > 0
            ? transport.positionSeconds
            : positionFallback,
        ),
      ),
      durationSeconds: durationSeconds(),
      speed: practice.speed,
      pitchSemitones: practice.pitchSemitones,
      loopEnabled: practice.loopEnabled,
      loopRange: practiceLoopRange,
      error: fatalError ?? transport.error,
    };
  }

  function emitPlayer(force = false): void {
    const next = buildPlayerState();
    if (!force && samePlayerState(playerCache, next)) return;
    playerCache = next;
    for (const listener of playerListeners) listener(next);
  }

  function emitPractice(): void {
    practiceCache = { ...practice };
    for (const listener of practiceListeners) listener(practiceCache);
    emitPlayer();
  }

  function emitNotice(): void {
    const next = computeNotice();
    if (next === noticeCache) return;
    noticeCache = next;
    for (const listener of noticeListeners) listener(next);
    emitPlayer();
  }

  function applyControls(): void {
    transport.setSpeed(practice.speed);
    transport.setPitch(practice.pitchSemitones);
    transport.setCountIn(practice.countInBars);
    transport.setTempo(grid.bpm, grid.bpb);
    transport.setBeats(
      gridBeatSpecs(
        grid,
        sampleRate,
        durationSeconds(),
        practice.accentDownbeat,
      ),
    );
    transport.setMetronomeVolume(
      practice.metronomeEnabled ? practice.metronomeVolume : 0,
    );
  }

  function applyLoop(): void {
    if (
      !practice.loopEnabled ||
      practiceLoopRange === null ||
      durationFrames() <= 0
    ) {
      transport.setLoop(null);
      return;
    }
    transport.setLoop(
      loopFromSeconds(
        practiceLoopRange.startSeconds,
        practiceLoopRange.endSeconds,
        sampleRate,
        durationFrames(),
      ),
    );
  }

  function setLoopEnabledInternal(enabled: boolean): void {
    const canLoop = durationSeconds() > 0;
    let range = practiceLoopRange;
    if (enabled && range === null && canLoop) {
      range = { startSeconds: 0, endSeconds: durationSeconds() };
    }
    const wasEnabled = practice.loopEnabled;
    practiceLoopRange = range;
    practice = {
      ...practice,
      loopEnabled: enabled && range !== null && canLoop,
    };
    // SectionLane sets the range and then enables; avoid a second seek when
    // the transport already holds this loop.
    if (practice.loopEnabled !== wasEnabled || !practice.loopEnabled) {
      applyLoop();
    }
    emitPractice();
  }

  function setLoopRangeInternal(range: LoopRange | null): void {
    const loopRange = normalizeLoopRange(range, durationSeconds());
    practiceLoopRange = loopRange;
    practice = {
      ...practice,
      loopEnabled: loopRange === null ? false : practice.loopEnabled,
    };
    if (loopRange === null) {
      transport.setLoop(null);
    } else if (practice.loopEnabled) {
      applyLoop();
    }
    emitPractice();
  }

  function setSpeedInternal(speed: number): void {
    practice = { ...practice, speed: clampSpeed(speed) };
    transport.setSpeed(practice.speed);
    emitPractice();
  }

  function setPitchInternal(semitones: number): void {
    practice = { ...practice, pitchSemitones: clampPitchSemitones(semitones) };
    transport.setPitch(practice.pitchSemitones);
    emitPractice();
  }

  function startTicker(): void {
    if (ticker !== null) return;
    ticker = setInterval(() => emitPlayer(), 50);
  }

  function stopTicker(): void {
    if (ticker === null) return;
    clearInterval(ticker);
    ticker = null;
  }

  function applyPlayingState(): void {
    if (transport.state === "playing") startTicker();
    else stopTicker();
    emitPlayer();
    emitNotice();
  }

  const player: StudioPlayer = {
    getState: () => playerCache,
    subscribe(listener) {
      playerListeners.add(listener);
      listener(playerCache);
      return () => {
        playerListeners.delete(listener);
      };
    },
    play() {
      if (fatalError !== null || phase === "loading" || durationSeconds() <= 0)
        return;
      const atEnd =
        currentPositionFrame() >= durationFrames() - 1 && durationFrames() > 0;
      if (atEnd || status() === "ended") {
        positionFallback = 0;
        transport.seek(0);
        suppressEndAt = false;
      }
      transport.play();
      applyPlayingState();
    },
    pause() {
      transport.pause();
      stopTicker();
      emitPlayer();
      emitNotice();
    },
    toggle() {
      if (player.getState().status === "playing") player.pause();
      else player.play();
    },
    seek(seconds) {
      if (durationSeconds() <= 0) return;
      const target = Math.max(0, Math.min(seconds, durationSeconds()));
      positionFallback = target;
      suppressEndAt =
        durationFrames() > 0 && target * sampleRate >= durationFrames() - 1;
      transport.seek(Math.round(target * sampleRate));
      emitPlayer();
    },
    setSpeed: setSpeedInternal,
    setPitchSemitones: setPitchInternal,
    setLoopEnabled: setLoopEnabledInternal,
    setLoopRange: setLoopRangeInternal,
    setDuration(seconds) {
      if (transport.durationFrames > 0) return;
      const duration = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
      configuredDuration = duration;
      if (practiceLoopRange !== null) {
        practiceLoopRange = normalizeLoopRange(practiceLoopRange, duration);
      }
      emitPractice();
    },
    dispose() {
      disposed = true;
      stopTicker();
      transport.dispose();
      playerListeners.clear();
      practiceListeners.clear();
      noticeListeners.clear();
      mixerListeners.clear();
      emitPlayer();
    },
  };
  playerCache = buildPlayerState();

  const practiceController: PracticeController = {
    getState: () => practiceCache,
    subscribe(listener) {
      practiceListeners.add(listener);
      listener(practiceCache);
      return () => {
        practiceListeners.delete(listener);
      };
    },
    setSpeed: setSpeedInternal,
    setPitchSemitones: setPitchInternal,
    setLoopEnabled: setLoopEnabledInternal,
    setCountInBars(bars) {
      practice = { ...practice, countInBars: clampCountInBars(bars) };
      transport.setCountIn(practice.countInBars);
      emitPractice();
    },
    setMetronomeEnabled(enabled) {
      practice = { ...practice, metronomeEnabled: enabled === true };
      applyControls();
      emitPractice();
    },
    setMetronomeVolume(volume) {
      practice = { ...practice, metronomeVolume: clampMetronomeVolume(volume) };
      applyControls();
      emitPractice();
    },
    setAccentDownbeat(enabled) {
      practice = { ...practice, accentDownbeat: enabled === true };
      applyControls();
      emitPractice();
    },
  };

  let mixerCache: MixerState = transport.getMixerState();
  transport.subscribeMixer((state) => {
    mixerCache = state;
    for (const listener of mixerListeners) listener(state);
  });

  const mixerController: MixerController = {
    getState: () => mixerCache,
    subscribe(listener) {
      mixerListeners.add(listener);
      listener(mixerCache);
      return () => {
        mixerListeners.delete(listener);
      };
    },
    setGain(channelId, gainDb) {
      transport.setGain(channelId, clampGainDb(gainDb));
    },
    setPan(channelId, pan) {
      transport.setPan(channelId, clampPan(pan));
    },
    setMuted(channelId, muted) {
      transport.setMuted(channelId, muted);
    },
    setSoloed(channelId, soloed) {
      transport.setSoloed(channelId, soloed);
    },
  };

  transport.subscribe(() => {
    if (transport.state === "error" && phase !== "loading") {
      fatalError = fatalError ?? transport.error ?? "Playback failed";
      stopTicker();
    }
    if (transport.state === "playing") startTicker();
    else if (transport.state !== "buffering") stopTicker();
    if (transport.reachedEnd) {
      suppressEndAt = false;
      stopTicker();
    }
    emitPlayer();
    emitNotice();
  });

  const ready = (async () => {
    if (options.autoLoad === false) {
      applyControls();
      emitNotice();
      return;
    }
    const withStems: TransportSource[] = [
      {
        id: "mix",
        url: mixUrl,
        channelCount: options.channelCount,
        frameCount: groupFrames,
      },
      ...stems,
    ];
    const hasStems = stems.length > 0;
    await transport.load({
      url: mixUrl,
      sampleRate,
      channelCount: options.channelCount,
      frameCount: groupFrames,
      ...(hasStems ? { sources: withStems } : {}),
    });
    let stemsLoaded = hasStems;
    if (transport.state === "error" && hasStems) {
      // One missing/stale stem must not cost the user the whole project.
      fallbackNotice = "Stems unavailable; playing the mix.";
      stemsLoaded = false;
      transport.dispose();
      await transport.load({
        url: mixUrl,
        sampleRate,
        channelCount: options.channelCount,
        frameCount: groupFrames,
      });
    }
    if (transport.state === "error") {
      fatalError = transport.error ?? "Playback failed";
      phase = "error";
      stopTicker();
    } else {
      fatalError = null;
      phase = "ready";
      suppressEndAt = false;
      if (stemsLoaded) {
        // The canonical mix and the stems are the same performance; play
        // the stems by default so audio is not doubled.
        transport.setMuted("mix", true);
      }
      applyControls();
      if (practice.loopEnabled) applyLoop();
    }
    emitPractice();
    emitNotice();
  })();

  const engine: StudioEngine = {
    player,
    mixer: mixerController,
    practice: practiceController,
    transport,
    ready,
    getNotice: () => noticeCache,
    subscribeNotice(listener) {
      noticeListeners.add(listener);
      listener(noticeCache);
      return () => {
        noticeListeners.delete(listener);
      };
    },
    diagnostics: () => transport.diagnose,
    dispose() {
      if (disposed) return;
      player.dispose();
    },
  };
  return engine;
}
