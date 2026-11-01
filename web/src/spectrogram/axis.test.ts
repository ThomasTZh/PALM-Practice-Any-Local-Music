import { describe, expect, it } from "vitest";

import {
  DEFAULT_HIGHEST_MIDI,
  DEFAULT_LOWEST_MIDI,
  NOTE_LABEL_PX,
  createFrequencyAxis,
  frequencyAtRow,
  frequencyToMidi,
  midiNoteName,
  midiToFrequency,
  nearestMidi,
  noteAxisHeight,
  noteLabels,
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

describe("noteLabels", () => {
  const axis = createFrequencyAxis(
    midiToFrequency(DEFAULT_LOWEST_MIDI),
    midiToFrequency(DEFAULT_HIGHEST_MIDI),
    256,
  );
  const labels = noteLabels(axis);

  it("labels every semitone from C1 to C8", () => {
    expect(labels).toHaveLength(85);
    expect(labels[labels.length - 1].label).toBe("C1");
    expect(labels[0].label).toBe("C8");
    expect(labels.map((label) => label.label)).toEqual(
      expect.arrayContaining(["C1", "C#1", "D1", "B1", "C2", "A4", "C8"]),
    );
    expect(new Set(labels.map((label) => label.midi)).size).toBe(85);
    expect(labels[0].midi).toBe(108);
    expect(labels[labels.length - 1].midi).toBe(24);
  });

  it("positions labels at their logarithmically mapped frequencies", () => {
    const low = labels.find((label) => label.label === "C1");
    const high = labels.find((label) => label.label === "C8");
    expect(low).toBeDefined();
    expect(high).toBeDefined();
    expect(high!.percentFromTop).toBeCloseTo(0, 6);
    expect(low!.percentFromTop).toBeCloseTo(100, 6);
    expect(high!.percentFromTop).toBeLessThan(low!.percentFromTop);
  });

  it("round-trips each note against the frequency mapping", () => {
    for (const label of labels) {
      expect(frequencyToMidi(label.hz)).toBeCloseTo(label.midi, 6);
      expect(nearestMidi(label.hz)).toBe(label.midi);
      expect(midiNoteName(nearestMidi(label.hz))).toBe(label.label);
    }
    expect(midiNoteName(24)).toBe("C1");
    expect(midiNoteName(60)).toBe("C4");
    expect(midiNoteName(108)).toBe("C8");
    expect(midiNoteName(61)).toBe("C#4");
  });

  it("derives about ten pixels per label with a 148px floor", () => {
    expect(noteAxisHeight(labels)).toBe(85 * NOTE_LABEL_PX);
    expect(noteAxisHeight(labels)).toBe(850);
    expect(noteAxisHeight([])).toBe(148);
  });
});
