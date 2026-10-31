import { describe, expect, it } from "vitest";

import {
  chordAt,
  chordBlocks,
  normalizeChordLabel,
  normalizeChords,
} from "./chords";

describe("normalizeChordLabel", () => {
  it("normalises Chordino labels to compact symbols", () => {
    expect(normalizeChordLabel("C:maj")).toBe("C");
    expect(normalizeChordLabel("A:min7")).toBe("Am7");
    expect(normalizeChordLabel("F#:min")).toBe("F#m");
    expect(normalizeChordLabel("Bb:maj7")).toBe("Bbmaj7");
    expect(normalizeChordLabel("G:7")).toBe("G7");
    expect(normalizeChordLabel("D:dim7")).toBe("Ddim7");
    expect(normalizeChordLabel("E:aug")).toBe("Eaug");
    expect(normalizeChordLabel("C:sus4")).toBe("Csus4");
    expect(normalizeChordLabel("A:min6")).toBe("Am6");
    expect(normalizeChordLabel("C:maj9")).toBe("Cmaj9");
    expect(normalizeChordLabel("B:hdim7")).toBe("Bm7b5");
  });

  it("keeps already compact labels and trims whitespace", () => {
    expect(normalizeChordLabel("C")).toBe("C");
    expect(normalizeChordLabel("Am7")).toBe("Am7");
    expect(normalizeChordLabel("  D:min  ")).toBe("Dm");
  });

  it("renders the no-chord label as N.C.", () => {
    expect(normalizeChordLabel("N")).toBe("N.C.");
    expect(normalizeChordLabel("N.C.")).toBe("N.C.");
    expect(normalizeChordLabel("")).toBe("N.C.");
    expect(normalizeChordLabel("   ")).toBe("N.C.");
  });

  it("normalises unicode accidentals and slash bass notes", () => {
    expect(normalizeChordLabel("E♭:maj")).toBe("Eb");
    expect(normalizeChordLabel("C:maj/E")).toBe("C/E");
    expect(normalizeChordLabel("Dm/F")).toBe("Dm/F");
  });

  it("keeps unknown qualities visible instead of dropping them", () => {
    expect(normalizeChordLabel("C:foo")).toBe("Cfoo");
  });

  it("does not mistake a bare note name for a chord quality", () => {
    expect(normalizeChordLabel("B")).toBe("B");
    expect(normalizeChordLabel("Bb")).toBe("Bb");
  });
});

describe("normalizeChords", () => {
  it("adds a symbol to every region", () => {
    const normalized = normalizeChords([
      { startSeconds: 0, endSeconds: 2, label: "C:maj" },
      { startSeconds: 2, endSeconds: 4, label: "A:min7" },
      { startSeconds: 4, endSeconds: 5, label: "N" },
    ]);

    expect(normalized.map((chord) => chord.symbol)).toEqual(["C", "Am7", "N.C."]);
    expect(normalized[1]).toMatchObject({
      startSeconds: 2,
      endSeconds: 4,
      label: "A:min7",
    });
  });
});

describe("chordAt", () => {
  const chords = [
    { startSeconds: 0, endSeconds: 2, label: "C:maj" },
    { startSeconds: 2, endSeconds: 4, label: "A:min7" },
    { startSeconds: 4, endSeconds: 5, label: "N" },
  ];

  it("finds the chord under the playhead", () => {
    expect(chordAt(chords, 1)?.label).toBe("C:maj");
    expect(chordAt(chords, 2)?.label).toBe("A:min7");
    expect(chordAt(chords, 4.5)?.label).toBe("N");
  });

  it("returns null outside every region", () => {
    expect(chordAt(chords, -1)).toBeNull();
    expect(chordAt(chords, 5)).toBeNull();
    expect(chordAt(chords, 99)).toBeNull();
  });
});

describe("chordBlocks", () => {
  const chords = [
    { startSeconds: 0, endSeconds: 2, label: "C:maj" },
    { startSeconds: 2, endSeconds: 4, label: "A:min7" },
    { startSeconds: 4, endSeconds: 5, label: "N" },
  ];
  const viewport = { startSeconds: 0, secondsPerPixel: 0.01 };

  it("lays blocks out in pixels on the shared timeline", () => {
    const blocks = chordBlocks(chords, viewport, 500);

    expect(blocks).toHaveLength(3);
    expect(blocks[0]).toMatchObject({ leftPx: 0, widthPx: 200, symbol: "C" });
    expect(blocks[1]).toMatchObject({ leftPx: 200, widthPx: 200, symbol: "Am7" });
    expect(blocks[2]).toMatchObject({ leftPx: 400, widthPx: 100, symbol: "N.C." });
  });

  it("clips blocks to the visible window", () => {
    const blocks = chordBlocks(chords, { startSeconds: 1, secondsPerPixel: 0.01 }, 500);

    expect(blocks[0]).toMatchObject({ leftPx: 0, widthPx: 100 });
    expect(blocks[1]).toMatchObject({ leftPx: 100, widthPx: 200 });
  });

  it("drops blocks outside the window", () => {
    const blocks = chordBlocks(chords, { startSeconds: 10, secondsPerPixel: 0.01 }, 500);
    expect(blocks).toEqual([]);
  });
});
