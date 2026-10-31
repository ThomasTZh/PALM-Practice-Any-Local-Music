import type { AnalysisSnapshot } from "./analysis";
import type { MixerController, MixerState } from "./mixer";
import type { PracticeController, PracticeState } from "./practice";
import type { LoopRange, StudioPlayer } from "./player";
import type { StudioProject } from "./project";

/** One project's live audio runtime: player plus the two practice seams. */
export interface StudioRuntime {
  player: StudioPlayer;
  mixer: MixerController;
  practice: PracticeController;
  ready?: Promise<void>;
  getNotice?: () => string | null;
  subscribeNotice?: (listener: (notice: string | null) => void) => () => void;
  diagnostics?: () => unknown;
  dispose?: () => void;
}

/** Everything that must survive rebuilding the runtime for a new stem set. */
export interface StudioRuntimeSnapshot {
  positionSeconds: number;
  durationSeconds: number;
  speed: number;
  pitchSemitones: number;
  loopRange: LoopRange | null;
  loopEnabled: boolean;
  wasPlaying: boolean;
  practice: PracticeState;
  mixer: MixerState;
}

export function captureStudioRuntime(
  runtime: StudioRuntime,
): StudioRuntimeSnapshot {
  const player = runtime.player.getState();
  const practice = runtime.practice.getState();
  return {
    positionSeconds: player.positionSeconds,
    durationSeconds: player.durationSeconds,
    speed: practice.speed,
    pitchSemitones: practice.pitchSemitones,
    loopRange: player.loopRange,
    loopEnabled: player.loopEnabled,
    wasPlaying: player.status === "playing",
    practice,
    mixer: runtime.mixer.getState(),
  };
}

export function applyStudioRuntimeSnapshot(
  runtime: StudioRuntime,
  snapshot: StudioRuntimeSnapshot,
  options: { resumePlayback?: boolean } = {},
): void {
  const player = runtime.player;
  if (snapshot.durationSeconds > 0) {
    player.setDuration(snapshot.durationSeconds);
  }
  runtime.practice.setSpeed(snapshot.speed);
  runtime.practice.setPitchSemitones(snapshot.pitchSemitones);
  runtime.practice.setCountInBars(snapshot.practice.countInBars);
  runtime.practice.setMetronomeEnabled(snapshot.practice.metronomeEnabled);
  runtime.practice.setMetronomeVolume(snapshot.practice.metronomeVolume);
  runtime.practice.setAccentDownbeat(snapshot.practice.accentDownbeat);
  player.setSpeed(snapshot.speed);
  player.setPitchSemitones(snapshot.pitchSemitones);
  player.setLoopRange(snapshot.loopRange);
  player.setLoopEnabled(snapshot.loopEnabled);
  player.seek(snapshot.positionSeconds);

  const channels = runtime.mixer.getState();
  for (const [channelId, channel] of Object.entries(snapshot.mixer)) {
    if (!(channelId in channels)) {
      continue;
    }
    runtime.mixer.setGain(channelId, channel.gainDb);
    runtime.mixer.setPan(channelId, channel.pan);
    runtime.mixer.setMuted(channelId, channel.muted);
    runtime.mixer.setSoloed(channelId, channel.soloed);
  }

  if (options.resumePlayback === true && snapshot.wasPlaying) {
    player.play();
  }
}

export type StudioRuntimeFactory = (
  project: StudioProject,
  analysis: AnalysisSnapshot | null,
) => StudioRuntime | Promise<StudioRuntime>;

export interface ShellTransport {
  open(
    project: StudioProject,
    analysis?: AnalysisSnapshot | null,
  ): Promise<StudioRuntime>;
  current(): StudioRuntime | null;
  dispose(): void;
}

function abortError(): Error {
  const error = new Error("project load superseded");
  error.name = "AbortError";
  return error;
}

/**
 * Owns one runtime at a time. Opening a project disposes the previous engine,
 * waits for the new one to be ready (or its mix fallback) and rejects stale
 * opens so a fast project switch cannot wire the wrong audio.
 */
export function createShellTransport(
  factory: StudioRuntimeFactory,
): ShellTransport {
  let currentRuntime: StudioRuntime | null = null;
  let generation = 0;
  let disposed = false;

  return {
    async open(project, analysis = null) {
      if (disposed) {
        throw abortError();
      }
      const current = generation + 1;
      generation = current;
      currentRuntime?.dispose?.();
      currentRuntime = null;
      const runtime = await factory(project, analysis);
      if (current !== generation || disposed) {
        runtime.dispose?.();
        throw abortError();
      }
      currentRuntime = runtime;
      // The shell renders the project immediately; callers that need audio
      // state await `runtime.ready` themselves, so a slow or blocked audio
      // context cannot hide the whole workspace.
      return runtime;
    },

    current() {
      return currentRuntime;
    },

    dispose() {
      disposed = true;
      generation += 1;
      currentRuntime?.dispose?.();
      currentRuntime = null;
    },
  };
}
