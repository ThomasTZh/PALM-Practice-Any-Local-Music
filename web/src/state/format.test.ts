import { describe, expect, it } from "vitest";

import {
  formatBarBeat,
  formatClock,
  formatPosition,
  formatSpeed,
} from "./format";
import type { Grid } from "./types";

const GRID: Grid = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

describe("formatClock", () => {
  it("shows minutes and whole seconds", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65)).toBe("1:05");
  });

  it("shows tenths when asked", () => {
    expect(formatClock(65.42, true)).toBe("1:05.4");
  });

  it("grows to hours and clamps nonsense", () => {
    expect(formatClock(3661)).toBe("1:01:01");
    expect(formatClock(-3)).toBe("0:00");
    expect(formatClock(Number.NaN)).toBe("0:00");
  });
});

describe("formatPosition", () => {
  it("is the tenths readout used by the transport", () => {
    expect(formatPosition(4.25)).toBe("0:04.3");
  });
});

describe("formatSpeed", () => {
  it("drops trailing zeros", () => {
    expect(formatSpeed(1)).toBe("1×");
    expect(formatSpeed(0.75)).toBe("0.75×");
    expect(formatSpeed(0.625)).toBe("0.625×");
  });
});

describe("formatBarBeat", () => {
  it("turns a position into bar and beat", () => {
    expect(formatBarBeat(2.5, GRID)).toBe("bar 2 · beat 2");
    expect(formatBarBeat(0, GRID)).toBe("bar 1 · beat 1");
  });

  it("honours the grid offset", () => {
    expect(formatBarBeat(0.75, { ...GRID, offsetSeconds: 0.25 })).toBe(
      "bar 1 · beat 2",
    );
  });

  it("returns null without a usable grid", () => {
    expect(formatBarBeat(2, null)).toBeNull();
    expect(formatBarBeat(2, { ...GRID, bpm: 0 })).toBeNull();
  });
});
