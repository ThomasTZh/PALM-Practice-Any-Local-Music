import { describe, expect, it } from "vitest";

import { hannWindow } from "./window";

describe("hannWindow", () => {
  it("starts at zero and peaks in the middle (periodic Hann)", () => {
    const window = hannWindow(8);
    const expected = [
      0, 0.14644662, 0.5, 0.8535534, 1, 0.8535534, 0.5, 0.14644662,
    ];

    expect(window.length).toBe(expected.length);
    expected.forEach((value, index) => {
      expect(window[index]).toBeCloseTo(value, 5);
    });
  });

  it("sums to half the window length so coherent gain is known", () => {
    const window = hannWindow(2048);
    const sum = window.reduce((total, value) => total + value, 0);
    expect(sum).toBeCloseTo(1024, 3);
  });

  it("is symmetric around the centre", () => {
    const window = hannWindow(64);
    for (let index = 1; index < window.length; index += 1) {
      expect(window[index]).toBeCloseTo(window[window.length - index], 6);
    }
  });

  it("rejects non-positive or fractional sizes", () => {
    expect(() => hannWindow(0)).toThrow(RangeError);
    expect(() => hannWindow(-2)).toThrow(RangeError);
    expect(() => hannWindow(2.5)).toThrow(RangeError);
  });
});
