import {
  applyMixerChange,
  createInitialMixerState,
  type MixerChange,
  type MixerController,
  type MixerState,
} from "./mixer";

export interface FakeMixer extends MixerController {
  readonly calls: string[];
  /** Test-only: update a channel as if the engine reported a change. */
  sync(channelId: string, change: MixerChange): void;
}

export function createFakeMixer(channelIds: string[]): FakeMixer {
  let state = createInitialMixerState(channelIds);
  const listeners = new Set<(state: MixerState) => void>();
  const calls: string[] = [];

  function set(channelId: string, change: MixerChange, label: string): void {
    calls.push(`${label}:${channelId}`);
    state = applyMixerChange(state, channelId, change);
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
    setGain(channelId, gainDb) {
      set(channelId, { gainDb }, "setGain");
    },
    setPan(channelId, pan) {
      set(channelId, { pan }, "setPan");
    },
    setMuted(channelId, muted) {
      set(channelId, { muted }, "setMuted");
    },
    setSoloed(channelId, soloed) {
      set(channelId, { soloed }, "setSoloed");
    },
    sync(channelId, change) {
      set(channelId, change, "sync");
    },
  };
}
