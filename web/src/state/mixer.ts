/** Stem mixer state and the seam the app maps onto the real audio engine. */

export interface StemMixState {
  gainDb: number;
  pan: number;
  muted: boolean;
  soloed: boolean;
}

export type MixerState = Record<string, StemMixState>;

export interface MixerChange {
  gainDb?: number;
  pan?: number;
  muted?: boolean;
  soloed?: boolean;
}

export interface MixerController {
  getState(): MixerState;
  subscribe(listener: (state: MixerState) => void): () => void;
  setGain(channelId: string, gainDb: number): void;
  setPan(channelId: string, pan: number): void;
  setMuted(channelId: string, muted: boolean): void;
  setSoloed(channelId: string, soloed: boolean): void;
}

export const MIN_GAIN_DB = -60;
export const MAX_GAIN_DB = 6;
export const MIN_PAN = -1;
export const MAX_PAN = 1;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clampGainDb(gainDb: number): number {
  return Number.isFinite(gainDb) ? clamp(gainDb, MIN_GAIN_DB, MAX_GAIN_DB) : 0;
}

export function clampPan(pan: number): number {
  return Number.isFinite(pan) ? clamp(pan, MIN_PAN, MAX_PAN) : 0;
}

export function defaultStemMix(): StemMixState {
  return { gainDb: 0, pan: 0, muted: false, soloed: false };
}

export function createInitialMixerState(channelIds: string[]): MixerState {
  const state: MixerState = {};
  for (const id of channelIds) {
    state[id] = defaultStemMix();
  }
  return state;
}

export function anySoloed(state: MixerState): boolean {
  return Object.values(state).some((channel) => channel.soloed);
}

/** Solo wins over everything else; a muted channel is never audible. */
export function isAudible(state: MixerState, channelId: string): boolean {
  const channel = state[channelId];
  if (channel === undefined || channel.muted) {
    return false;
  }
  return anySoloed(state) ? channel.soloed : true;
}

/** Gain the engine should apply, or the floor when the channel is silenced. */
export function effectiveGainDb(state: MixerState, channelId: string): number {
  if (!isAudible(state, channelId)) {
    return MIN_GAIN_DB;
  }
  return clampGainDb(state[channelId].gainDb);
}

export function applyMixerChange(
  state: MixerState,
  channelId: string,
  change: MixerChange,
): MixerState {
  const current = state[channelId] ?? defaultStemMix();
  return {
    ...state,
    [channelId]: {
      gainDb: change.gainDb === undefined ? current.gainDb : clampGainDb(change.gainDb),
      pan: change.pan === undefined ? current.pan : clampPan(change.pan),
      muted: change.muted === undefined ? current.muted : change.muted,
      soloed: change.soloed === undefined ? current.soloed : change.soloed,
    },
  };
}
