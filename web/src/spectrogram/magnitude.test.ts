import { describe, expect, it } from "vitest";

import { amplitudeToDb, clampDb, normalizeDb } from "./magnitude";

describe("amplitudeToDb", () => {
  it("converts reference-scaled amplitudes to decibels", () => {
    expect(amplitudeToDb(1)).toBeCloseTo(0);
    expect(amplitudeToDb(10)).toBeCloseTo(20);
    expect(amplitudeToDb(0.1)).toBeCloseTo(-20);
    expect(amplitudeToDb(0.5)).toBeCloseTo(-6.0206, 3);
  });

  it("returns negative infinity for silence instead of NaN", () => {
    expect(amplitudeToDb(0)).toBe(-Infinity);
    expect(Number.isNaN(amplitudeToDb(-1))).toBe(true);
  });
});

describe("clampDb", () => {
  it("keeps values inside the display range", () => {
    expect(clampDb(-50, -100, 0)).toBe(-50);
    expect(clampDb(-Infinity, -100, 0)).toBe(-100);
    expect(clampDb(12, -100, 0)).toBe(0);
  });

  it("rejects an inverted range", () => {
    expect(() => clampDb(-50, 0, -100)).toThrow(RangeError);
  });
});

describe("normalizeDb", () => {
  it("maps the display range to 0..1", () => {
    expect(normalizeDb(-100, -100, 0)).toBe(0);
    expect(normalizeDb(-50, -100, 0)).toBeCloseTo(0.5);
    expect(normalizeDb(0, -100, 0)).toBe(1);
    expect(normalizeDb(-120, -100, 0)).toBe(0);
    expect(normalizeDb(20, -100, 0)).toBe(1);
  });

  it("handles a flat range without dividing by zero", () => {
    expect(normalizeDb(-20, -20, -20)).toBe(0);
  });
});
