import { describe, expect, it } from "vitest";

import {
  createFrequencyAxis,
  formatFrequency,
  frequencyAtRow,
  frequencyLabels,
  rowAtFrequency,
} from "./axis";

describe("frequency axis", () => {
  const axis = createFrequencyAxis(30, 20000, 256);

  it("puts the highest frequency at the top and the lowest at the bottom", () => {
    expect(frequencyAtRow(axis, 0)).toBeCloseTo(20000, 3);
    expect(frequencyAtRow(axis, 255)).toBeCloseTo(30, 3);
  });

  it("is logarithmic, so the midpoint is the geometric mean", () => {
    expect(frequencyAtRow(axis, 127.5)).toBeCloseTo(Math.sqrt(30 * 20000), 3);
  });

  it("maps frequencies back to rows", () => {
    expect(rowAtFrequency(axis, 20000)).toBeCloseTo(0, 3);
    expect(rowAtFrequency(axis, 30)).toBeCloseTo(255, 3);
    expect(rowAtFrequency(axis, 1000)).toBeGreaterThan(0);
    expect(rowAtFrequency(axis, 1000)).toBeLessThan(255);
  });

  it("rejects invalid ranges", () => {
    expect(() => createFrequencyAxis(0, 20000, 256)).toThrow(RangeError);
    expect(() => createFrequencyAxis(1000, 100, 256)).toThrow(RangeError);
    expect(() => createFrequencyAxis(30, 20000, 0)).toThrow(RangeError);
  });
});

describe("frequencyLabels", () => {
  const axis = createFrequencyAxis(30, 20000, 256);

  it("labels the octaves a musician reads", () => {
    const labels = frequencyLabels(axis);
    const values = labels.map((label) => label.hz);

    expect(values).toContain(50);
    expect(values).toContain(100);
    expect(values).toContain(1000);
    expect(values).toContain(10000);
    expect(values.every((hz) => hz >= 30 && hz <= 20000)).toBe(true);
  });

  it("positions labels logarithmically from the top", () => {
    const labels = frequencyLabels(axis);
    const low = labels.find((label) => label.hz === 100);
    const high = labels.find((label) => label.hz === 10000);

    expect(low).toBeDefined();
    expect(high).toBeDefined();
    expect(low!.percentFromTop).toBeGreaterThan(high!.percentFromTop);
    expect(high!.percentFromTop).toBeGreaterThanOrEqual(0);
    expect(low!.percentFromTop).toBeLessThanOrEqual(100);
  });
});

describe("formatFrequency", () => {
  it("uses Hz below one kilohertz and kHz above", () => {
    expect(formatFrequency(50)).toBe("50 Hz");
    expect(formatFrequency(1000)).toBe("1 kHz");
    expect(formatFrequency(1500)).toBe("1.5 kHz");
    expect(formatFrequency(20000)).toBe("20 kHz");
  });
});
