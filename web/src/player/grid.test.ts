// @vitest-environment node
/**
 * Grid conversion tests (t9): detected beats and the analysis-free fallback,
 * bar accents, and section seconds -> clamped loop frames.
 */

import { describe, expect, it } from "vitest";
import {
  FALLBACK_BPB,
  FALLBACK_BPM,
  gridBeatSpecs,
  gridBeatTimes,
  loopFromSeconds,
  normalizeGrid,
} from "./grid";

const RATE = 48_000;

describe("grid normalization", () => {
  it("falls back to 120 BPM in 4/4 when analysis has not run", () => {
    const grid = normalizeGrid(null);
    expect(grid.bpm).toBe(FALLBACK_BPM);
    expect(grid.bpb).toBe(FALLBACK_BPB);
    expect(grid.beatsSeconds).toEqual([]);
    expect(grid.offsetSeconds).toBe(0);
  });

  it("rejects non-finite tempo/meter and keeps valid beats sorted", () => {
    const grid = normalizeGrid({
      bpm: Number.NaN,
      bpb: 0,
      beatsSeconds: [2, 0.5, Number.NaN, 1],
      offsetSeconds: -3,
    });
    expect(grid.bpm).toBe(120);
    expect(grid.bpb).toBe(4);
    expect(grid.beatsSeconds).toEqual([0.5, 1, 2]);
    expect(grid.offsetSeconds).toBe(0);
  });
});

describe("beat times", () => {
  it("uses the detected beat list when present", () => {
    const grid = normalizeGrid({
      bpm: 100,
      bpb: 3,
      beatsSeconds: [0.1, 0.6, 1.1],
    });
    expect(gridBeatTimes(grid, 10)).toEqual([0.1, 0.6, 1.1]);
  });

  it("synthesises an even grid from the fallback tempo", () => {
    const grid = normalizeGrid({ bpm: 120, bpb: 4, beatsSeconds: [] });
    // 120 BPM = 0.5 s per beat, inclusive of t=0 and the duration.
    expect(gridBeatTimes(grid, 2)).toEqual([0, 0.5, 1, 1.5, 2]);
  });

  it("accents the first beat of every bar and respects the toggle", () => {
    const grid = normalizeGrid({ bpm: 120, bpb: 4, beatsSeconds: [] });
    const accented = gridBeatSpecs(grid, RATE, 2, true);
    expect(accented.map((beat) => beat.frame)).toEqual([
      0, 24_000, 48_000, 72_000, 96_000,
    ]);
    expect(accented.map((beat) => beat.strength)).toEqual([
      "downbeat",
      "beat",
      "beat",
      "beat",
      "downbeat",
    ]);
    const flat = gridBeatSpecs(grid, RATE, 2, false);
    expect(flat.every((beat) => beat.strength === "beat")).toBe(true);
  });
});

describe("section loop conversion", () => {
  const DURATION = 8 * RATE;

  it("converts bar-snapped seconds to exact frame boundaries", () => {
    const loop = loopFromSeconds(2, 4, RATE, DURATION);
    expect(loop).toEqual({
      startFrame: 2 * RATE,
      endFrame: 4 * RATE,
      repeatCount: null,
      fade: true,
    });
  });

  it("clamps to the source and drops collapsed/huge ranges", () => {
    expect(loopFromSeconds(-1, 99, RATE, DURATION)).toMatchObject({
      startFrame: 0,
      endFrame: DURATION,
    });
    expect(loopFromSeconds(4, 4, RATE, DURATION)).toBeNull();
    expect(loopFromSeconds(5, 2, RATE, DURATION)).toBeNull();
    expect(loopFromSeconds(0, 1, 0, DURATION)).toBeNull();
  });
});
