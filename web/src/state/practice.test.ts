import { describe, expect, it } from "vitest";

import {
  applyPracticeChange,
  clampCountInBars,
  clampMetronomeVolume,
  COUNT_IN_OPTIONS,
  DEFAULT_PRACTICE_STATE,
  type PracticeState,
} from "./practice";

describe("practice defaults", () => {
  it("starts at normal speed with metronome off", () => {
    expect(DEFAULT_PRACTICE_STATE).toEqual({
      speed: 1,
      loopEnabled: false,
      countInBars: 0,
      metronomeEnabled: false,
      metronomeVolume: 1,
      accentDownbeat: true,
    });
    expect(COUNT_IN_OPTIONS).toEqual([0, 1, 2]);
  });
});

describe("practice clamps", () => {
  it("keeps count-in within the offered bars", () => {
    expect(clampCountInBars(0)).toBe(0);
    expect(clampCountInBars(1)).toBe(1);
    expect(clampCountInBars(2)).toBe(2);
    expect(clampCountInBars(9)).toBe(2);
    expect(clampCountInBars(-1)).toBe(0);
    expect(clampCountInBars(Number.NaN)).toBe(0);
  });

  it("keeps metronome volume in 0..1", () => {
    expect(clampMetronomeVolume(0.25)).toBe(0.25);
    expect(clampMetronomeVolume(-1)).toBe(0);
    expect(clampMetronomeVolume(2)).toBe(1);
    expect(clampMetronomeVolume(Number.NaN)).toBe(1);
  });
});

describe("applyPracticeChange", () => {
  const state: PracticeState = { ...DEFAULT_PRACTICE_STATE };

  it("applies and clamps a single change without mutating", () => {
    const next = applyPracticeChange(state, { speed: 4 });

    expect(next.speed).toBe(2);
    expect(state.speed).toBe(1);
  });

  it("clamps count-in and volume", () => {
    const next = applyPracticeChange(state, {
      countInBars: 5,
      metronomeVolume: 4,
    });

    expect(next).toMatchObject({
      countInBars: 2,
      metronomeVolume: 1,
    });
  });
});
