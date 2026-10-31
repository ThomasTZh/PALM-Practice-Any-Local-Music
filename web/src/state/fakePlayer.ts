import {
  initialPlayerState,
  type PlayerState,
  type StudioPlayer,
} from "./player";

/**
 * Test double for the transport seam. Records calls so component tests can
 * assert both the behaviour the user sees and the engine calls that cause it.
 */
export interface FakePlayer extends StudioPlayer {
  readonly calls: string[];
  setState(partial: Partial<PlayerState>): void;
}

export function createFakePlayer(
  initial: Partial<PlayerState> = {},
): FakePlayer {
  let state = initialPlayerState(initial);
  const listeners = new Set<(state: PlayerState) => void>();
  const calls: string[] = [];

  function update(partial: Partial<PlayerState>): void {
    state = { ...state, ...partial };
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
    setState: update,
    play() {
      calls.push("play");
      update({ status: "playing" });
    },
    pause() {
      calls.push("pause");
      update({ status: "paused" });
    },
    toggle() {
      calls.push("toggle");
      update({ status: state.status === "playing" ? "paused" : "playing" });
    },
    seek(seconds) {
      calls.push(`seek:${seconds}`);
      update({ positionSeconds: seconds });
    },
    setSpeed(speed) {
      calls.push(`setSpeed:${speed}`);
      update({ speed });
    },
    setPitchSemitones(semitones) {
      calls.push(`setPitchSemitones:${semitones}`);
      update({ pitchSemitones: semitones });
    },
    setLoopEnabled(enabled) {
      calls.push(`setLoopEnabled:${enabled}`);
      update({ loopEnabled: enabled });
    },
    setLoopRange(range) {
      calls.push(`setLoopRange:${JSON.stringify(range)}`);
      update({
        loopRange: range,
        loopEnabled: range === null ? false : state.loopEnabled,
      });
    },
    setDuration(seconds) {
      calls.push(`setDuration:${seconds}`);
      update({ durationSeconds: seconds });
    },
    dispose() {
      listeners.clear();
    },
  };
}
