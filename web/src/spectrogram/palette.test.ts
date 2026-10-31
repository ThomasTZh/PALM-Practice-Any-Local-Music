import { describe, expect, it } from "vitest";

import { colorForLevel, paletteTable } from "./palette";

function luminance(color: [number, number, number, number]): number {
  return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2];
}

describe("colorForLevel", () => {
  it("maps silence to a dark blue and full level to a bright warm colour", () => {
    const low = colorForLevel(0);
    const high = colorForLevel(1);

    expect(low[0]).toBeLessThan(30);
    expect(low[1]).toBeLessThan(40);
    expect(low[2]).toBeLessThan(90);
    expect(high[0]).toBeGreaterThan(220);
    expect(high[1]).toBeGreaterThan(180);
    expect(high[2]).toBeGreaterThan(120);
  });

  it("never goes darker as level rises", () => {
    let previous = -1;
    for (let step = 0; step <= 20; step += 1) {
      const current = luminance(colorForLevel(step / 20));
      expect(current).toBeGreaterThanOrEqual(previous - 1);
      previous = current;
    }
  });

  it("clamps levels outside 0..1", () => {
    expect(colorForLevel(-4)).toEqual(colorForLevel(0));
    expect(colorForLevel(4)).toEqual(colorForLevel(1));
  });
});

describe("paletteTable", () => {
  it("builds an RGBA lookup table with opaque entries", () => {
    const table = paletteTable(16);

    expect(table).toBeInstanceOf(Uint8ClampedArray);
    expect(table.length).toBe(16 * 4);
    for (let index = 0; index < 16; index += 1) {
      expect(table[index * 4 + 3]).toBe(255);
    }
    expect(table[0]).toBe(colorForLevel(0)[0]);
    expect(table[table.length - 4]).toBe(colorForLevel(1)[0]);
  });

  it("rejects unusable sizes", () => {
    expect(() => paletteTable(0)).toThrow(RangeError);
    expect(() => paletteTable(1.5)).toThrow(RangeError);
  });
});
