// @vitest-environment node
/**
 * Pure time/frame mapping tests (t2). The transport's position contract
 * rests on these two conversions; they are tested without an audio
 * graph so a failure names the arithmetic, not the plumbing.
 */

import { describe, expect, it } from "vitest";
import {
  clampFrame,
  extrapolateStreamFrame,
  framesToSeconds,
  mapStreamToLoop,
  projectPositionAt,
  secondsToFrames,
  type PositionAnchor,
} from "./time";

const RATE = 48_000;
const LOOP = { startFrame: 0, endFrame: 2 * RATE };

describe("time and frame conversion", () => {
  it("round-trips frames and seconds", () => {
    expect(framesToSeconds(RATE, RATE)).toBe(1);
    expect(secondsToFrames(1.5, RATE)).toBe(72_000);
    expect(framesToSeconds(0, 0)).toBe(0);
  });

  it("clamps frames into the source duration", () => {
    expect(clampFrame(-10, 1000)).toBe(0);
    expect(clampFrame(1000.9, 1000)).toBe(1000);
    expect(clampFrame(Number.NaN, 1000)).toBe(0);
  });
});

describe("stream to project mapping", () => {
  it("is the identity without a loop", () => {
    expect(mapStreamToLoop(1234, null)).toBe(1234);
  });

  it("wraps stream coordinates into the loop range", () => {
    expect(mapStreamToLoop(10, LOOP)).toBe(10);
    expect(mapStreamToLoop(2 * RATE + 10, LOOP)).toBe(10);
    expect(mapStreamToLoop(-100, LOOP)).toBe(2 * RATE - 100);
    expect(mapStreamToLoop(100_000, LOOP)).toBe(4000);
  });

  it("freezes a paused anchor and extrapolates a running one", () => {
    const anchor: PositionAnchor = {
      frame: 24_000,
      time: 1,
      rate: 2,
      paused: false,
    };
    expect(extrapolateStreamFrame(anchor, 1.25, RATE)).toBe(48_000);
    expect(extrapolateStreamFrame({ ...anchor, paused: true }, 9, RATE)).toBe(
      24_000,
    );
  });

  it("maps an extrapolated stream position into the project", () => {
    const anchor: PositionAnchor = {
      frame: 100_000,
      time: 2,
      rate: 1,
      paused: false,
    };
    expect(projectPositionAt(anchor, 2.1, RATE, LOOP, 4 * RATE)).toBe(8800);
    // Clamped at the duration.
    expect(projectPositionAt(anchor, 10, RATE, null, 2 * RATE)).toBe(2 * RATE);
  });
});
