import { createLocalPlayer } from "./localPlayer";
import {
  applyMixerChange,
  createInitialMixerState,
  type MixerChange,
  type MixerController,
  type MixerState,
} from "./mixer";
import {
  applyPracticeChange,
  DEFAULT_PRACTICE_STATE,
  type PracticeChange,
  type PracticeController,
  type PracticeState,
} from "./practice";
import type { StudioRuntime } from "./studioRuntime";

/** Silent fallback controllers used before the real engine is attached. */
export function createLocalMixer(channelIds: string[]): MixerController {
  let state = createInitialMixerState(channelIds);
  const listeners = new Set<(state: MixerState) => void>();

  function update(channelId: string, change: MixerChange): void {
    state = applyMixerChange(state, channelId, change);
    for (const listener of listeners) {
      listener(state);
    }
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setGain: (channelId, gainDb) => update(channelId, { gainDb }),
    setPan: (channelId, pan) => update(channelId, { pan }),
    setMuted: (channelId, muted) => update(channelId, { muted }),
    setSoloed: (channelId, soloed) => update(channelId, { soloed }),
  };
}

export function createLocalPractice(
  initial: Partial<PracticeState> = {},
): PracticeController {
  let state = applyPracticeChange({ ...DEFAULT_PRACTICE_STATE }, initial);
  const listeners = new Set<(state: PracticeState) => void>();

  function update(change: PracticeChange): void {
    state = applyPracticeChange(state, change);
    for (const listener of listeners) {
      listener(state);
    }
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setSpeed: (speed) => update({ speed }),
    setPitchSemitones: (semitones) => update({ pitchSemitones: semitones }),
    setLoopEnabled: (enabled) => update({ loopEnabled: enabled }),
    setCountInBars: (bars) => update({ countInBars: bars }),
    setMetronomeEnabled: (enabled) => update({ metronomeEnabled: enabled }),
    setMetronomeVolume: (volume) => update({ metronomeVolume: volume }),
    setAccentDownbeat: (enabled) => update({ accentDownbeat: enabled }),
  };
}

export interface LocalProjectShape {
  durationSeconds?: number;
  stems?: Array<{ id: string }>;
}

/**
 * Runtime used when the shell has no engine (tests, SSR, or before main wires
 * the real factory). It keeps UI state consistent but produces no sound.
 */
export function createLocalStudioRuntime(
  project: LocalProjectShape = {},
): StudioRuntime {
  const player = createLocalPlayer({
    durationSeconds: Math.max(0, project.durationSeconds ?? 0),
  });
  const mixer = createLocalMixer((project.stems ?? []).map((stem) => stem.id));
  const practice = createLocalPractice();
  const listeners = new Set<(notice: string | null) => void>();
  return {
    player,
    mixer,
    practice,
    ready: Promise.resolve(),
    getNotice: () => null,
    subscribeNotice(listener) {
      listeners.add(listener);
      listener(null);
      return () => {
        listeners.delete(listener);
      };
    },
    diagnostics: () => ({}),
    dispose() {
      player.dispose();
      listeners.clear();
    },
  };
}
