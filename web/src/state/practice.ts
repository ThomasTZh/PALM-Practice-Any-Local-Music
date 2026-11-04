import { clampSpeed } from "./player";

/** Practice settings shared by the practice panel and the engine adapter. */
export interface PracticeState {
  speed: number;
  loopEnabled: boolean;
  countInBars: number;
  metronomeEnabled: boolean;
  metronomeVolume: number;
  accentDownbeat: boolean;
}

export type PracticeChange = Partial<PracticeState>;

export interface PracticeController {
  getState(): PracticeState;
  subscribe(listener: (state: PracticeState) => void): () => void;
  setSpeed(speed: number): void;
  setLoopEnabled(enabled: boolean): void;
  setCountInBars(bars: number): void;
  setMetronomeEnabled(enabled: boolean): void;
  setMetronomeVolume(volume: number): void;
  setAccentDownbeat(enabled: boolean): void;
}

export const COUNT_IN_OPTIONS = [0, 1, 2] as const;

export const DEFAULT_PRACTICE_STATE: PracticeState = {
  speed: 1,
  loopEnabled: false,
  countInBars: 0,
  metronomeEnabled: false,
  metronomeVolume: 1,
  accentDownbeat: true,
};

export function clampCountInBars(bars: number): number {
  if (!Number.isFinite(bars)) {
    return 0;
  }
  return Math.min(2, Math.max(0, Math.round(bars)));
}

export function clampMetronomeVolume(volume: number): number {
  if (!Number.isFinite(volume)) {
    return 1;
  }
  return Math.min(1, Math.max(0, volume));
}

/** Pure reducer the fake and the t16 adapter share. */
export function applyPracticeChange(
  state: PracticeState,
  change: PracticeChange,
): PracticeState {
  return {
    speed: clampSpeed(change.speed ?? state.speed),
    loopEnabled: change.loopEnabled ?? state.loopEnabled,
    countInBars: clampCountInBars(change.countInBars ?? state.countInBars),
    metronomeEnabled: change.metronomeEnabled ?? state.metronomeEnabled,
    metronomeVolume: clampMetronomeVolume(
      change.metronomeVolume ?? state.metronomeVolume,
    ),
    accentDownbeat: change.accentDownbeat ?? state.accentDownbeat,
  };
}
