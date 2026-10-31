import {
  applyPracticeChange,
  DEFAULT_PRACTICE_STATE,
  type PracticeChange,
  type PracticeController,
  type PracticeState,
} from "./practice";

export interface FakePractice extends PracticeController {
  readonly calls: string[];
  /** Test-only: update the state as if the engine reported a change. */
  sync(change: PracticeChange): void;
}

export function createFakePractice(
  initial: Partial<PracticeState> = {},
): FakePractice {
  let state = applyPracticeChange({ ...DEFAULT_PRACTICE_STATE }, initial);
  const listeners = new Set<(state: PracticeState) => void>();
  const calls: string[] = [];

  function update(method: string, change: PracticeChange): void {
    calls.push(method);
    state = applyPracticeChange(state, change);
    for (const listener of listeners) {
      listener(state);
    }
  }

  return {
    get calls() {
      return calls;
    },
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setSpeed(speed) {
      update("setSpeed", { speed });
    },
    setPitchSemitones(semitones) {
      update("setPitchSemitones", { pitchSemitones: semitones });
    },
    setLoopEnabled(enabled) {
      update("setLoopEnabled", { loopEnabled: enabled });
    },
    setCountInBars(bars) {
      update("setCountInBars", { countInBars: bars });
    },
    setMetronomeEnabled(enabled) {
      update("setMetronomeEnabled", { metronomeEnabled: enabled });
    },
    setMetronomeVolume(volume) {
      update("setMetronomeVolume", { metronomeVolume: volume });
    },
    setAccentDownbeat(enabled) {
      update("setAccentDownbeat", { accentDownbeat: enabled });
    },
    sync(change) {
      update("sync", change);
    },
  };
}
