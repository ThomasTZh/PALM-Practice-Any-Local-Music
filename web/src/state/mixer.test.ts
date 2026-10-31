import { describe, expect, it } from "vitest";

import {
  anySoloed,
  clampGainDb,
  clampPan,
  createInitialMixerState,
  defaultStemMix,
  effectiveGainDb,
  isAudible,
  MAX_GAIN_DB,
  MIN_GAIN_DB,
} from "./mixer";

describe("clamps", () => {
  it("keeps gain inside the practical mixer range", () => {
    expect(clampGainDb(0)).toBe(0);
    expect(clampGainDb(20)).toBe(MAX_GAIN_DB);
    expect(clampGainDb(-200)).toBe(MIN_GAIN_DB);
    expect(clampGainDb(Number.NaN)).toBe(0);
  });

  it("keeps pan between hard left and hard right", () => {
    expect(clampPan(0)).toBe(0);
    expect(clampPan(2)).toBe(1);
    expect(clampPan(-2)).toBe(-1);
    expect(clampPan(Number.NaN)).toBe(0);
  });
});

describe("initial mixer state", () => {
  it("gives every stem a neutral channel", () => {
    const state = createInitialMixerState(["bass", "drums"]);

    expect(state).toEqual({
      bass: defaultStemMix(),
      drums: defaultStemMix(),
    });
    expect(state.bass).not.toBe(state.drums);
  });
});

describe("solo and mute logic", () => {
  const state = {
    bass: { gainDb: 0, pan: 0, muted: false, soloed: false },
    drums: { gainDb: 0, pan: 0, muted: false, soloed: false },
    other: { gainDb: 0, pan: 0, muted: false, soloed: false },
  };

  it("mutes a channel without affecting the others", () => {
    const muted = { ...state, bass: { ...state.bass, muted: true } };
    expect(isAudible(muted, "bass")).toBe(false);
    expect(isAudible(muted, "drums")).toBe(true);
  });

  it("soloing one channel silences the rest", () => {
    const soloed = { ...state, bass: { ...state.bass, soloed: true } };
    expect(anySoloed(soloed)).toBe(true);
    expect(isAudible(soloed, "bass")).toBe(true);
    expect(isAudible(soloed, "drums")).toBe(false);
  });

  it("a muted solo channel is still silent", () => {
    const soloMuted = {
      ...state,
      bass: { ...state.bass, soloed: true, muted: true },
    };
    expect(isAudible(soloMuted, "bass")).toBe(false);
  });

  it("applies the solo logic to the effective gain", () => {
    const soloed = { ...state, bass: { ...state.bass, soloed: true } };
    expect(effectiveGainDb(soloed, "bass")).toBe(0);
    expect(effectiveGainDb(soloed, "drums")).toBe(MIN_GAIN_DB);
  });
});
