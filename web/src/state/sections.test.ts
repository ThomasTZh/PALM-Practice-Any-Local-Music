import { describe, expect, it } from "vitest";

import type { Grid } from "./types";
import {
  addSection,
  sectionBlocks,
  barMarks,
  beatMarks,
  deleteSection,
  draftSectionRange,
  renameSection,
  resizeSection,
  sectionAt,
  sectionLoopRange,
  snapRange,
  snapTime,
  splitSection,
  uniformBeats,
  type Section,
} from "./sections";

const BEATS = Array.from({ length: 16 }, (_, index) => index * 0.5);
const GRID = { beats: BEATS, bpb: 4 };
const TEMPO: Grid = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

const VERSE: Section = {
  id: "s1",
  name: "Verse",
  startSeconds: 0,
  endSeconds: 8,
};

describe("beat and bar marks", () => {
  it("numbers beats and bars from the detected beat list", () => {
    const marks = beatMarks(BEATS, 4);

    expect(marks).toHaveLength(16);
    expect(marks[0]).toMatchObject({ bar: 1, beat: 1, downbeat: true });
    expect(marks[5]).toMatchObject({ bar: 2, beat: 2, downbeat: false });
    expect(
      marks.filter((mark) => mark.downbeat).map((mark) => mark.timeSeconds),
    ).toEqual([0, 2, 4, 6]);
  });

  it("returns bar downbeats only", () => {
    expect(
      barMarks(BEATS, 4).map((mark) => [mark.timeSeconds, mark.bar]),
    ).toEqual([
      [0, 1],
      [2, 2],
      [4, 3],
      [6, 4],
    ]);
  });

  it("ignores unusable grids", () => {
    expect(beatMarks([], 4)).toEqual([]);
    expect(barMarks(BEATS, 0)).toEqual([]);
  });
});

describe("snapTime", () => {
  it("snaps to the nearest bar by default", () => {
    expect(snapTime(1.7, "bar", GRID)).toBe(2);
    expect(snapTime(0.9, "bar", GRID)).toBe(0);
  });

  it("snaps to the nearest beat in beat mode", () => {
    expect(snapTime(1.7, "beat", GRID)).toBeCloseTo(1.5);
    expect(snapTime(1.8, "beat", GRID)).toBeCloseTo(2);
  });

  it("leaves the value alone in free mode", () => {
    expect(snapTime(1.7, "free", GRID)).toBe(1.7);
  });

  it("falls back to free when no grid is known", () => {
    expect(snapTime(1.7, "bar", null)).toBe(1.7);
    expect(snapTime(-1, "bar", null)).toBe(0);
  });
});

describe("snapRange", () => {
  it("snaps both boundaries", () => {
    expect(
      snapRange({ startSeconds: 1.7, endSeconds: 3.2 }, "bar", GRID, 8),
    ).toEqual({
      startSeconds: 2,
      endSeconds: 4,
    });
    expect(
      snapRange({ startSeconds: 1.7, endSeconds: 3.2 }, "beat", GRID, 8),
    ).toEqual({
      startSeconds: 1.5,
      endSeconds: 3,
    });
    expect(
      snapRange({ startSeconds: 1.7, endSeconds: 3.2 }, "free", GRID, 8),
    ).toEqual({
      startSeconds: 1.7,
      endSeconds: 3.2,
    });
  });

  it("expands a collapsed bar range to the next bar", () => {
    expect(
      snapRange({ startSeconds: 1.9, endSeconds: 2.1 }, "bar", GRID, 8),
    ).toEqual({
      startSeconds: 2,
      endSeconds: 4,
    });
  });

  it("rejects a range that cannot exist", () => {
    expect(
      snapRange({ startSeconds: 7.9, endSeconds: 8 }, "bar", GRID, 8),
    ).toBeNull();
  });
});

describe("addSection", () => {
  it("adds a bar-snapped section with a deterministic name and id", () => {
    const sections = addSection(
      [],
      { startSeconds: 1.9, endSeconds: 4.1 },
      "bar",
      GRID,
    );

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "section-1",
      name: "Section 1",
      startSeconds: 2,
      endSeconds: 4,
    });
  });

  it("uses free boundaries when free snapping is selected", () => {
    const sections = addSection(
      [],
      { startSeconds: 1.7, endSeconds: 3.2 },
      "free",
      GRID,
    );
    expect(sections[0]).toMatchObject({ startSeconds: 1.7, endSeconds: 3.2 });
  });

  it("leaves the list untouched when the range collapses", () => {
    const existing = [VERSE];
    const sections = addSection(
      existing,
      { startSeconds: 7.9, endSeconds: 8 },
      "bar",
      GRID,
      { durationSeconds: 8 },
    );
    expect(sections).toBe(existing);
  });
});

describe("splitSection", () => {
  it("splits at the nearest bar by default", () => {
    const sections = splitSection([VERSE], "s1", 3.2, "bar", GRID);

    expect(sections).toHaveLength(2);
    expect(sections[0]).toMatchObject({
      name: "Verse",
      startSeconds: 0,
      endSeconds: 4,
    });
    expect(sections[1]).toMatchObject({
      name: "Verse (2)",
      startSeconds: 4,
      endSeconds: 8,
    });
    expect(sections[1].id).not.toBe(sections[0].id);
  });

  it("splits at the nearest beat in beat mode", () => {
    const sections = splitSection([VERSE], "s1", 3.2, "beat", GRID);
    expect(sections[1].startSeconds).toBeCloseTo(3);
  });

  it("does not split at a boundary with no room on one side", () => {
    const existing = [VERSE];
    expect(splitSection(existing, "s1", 0.1, "bar", GRID)).toBe(existing);
  });
});

describe("editing sections", () => {
  it("renames a section without touching its bounds", () => {
    const sections = renameSection([VERSE], "s1", "Chorus");
    expect(sections[0]).toMatchObject({
      name: "Chorus",
      startSeconds: 0,
      endSeconds: 8,
    });
  });

  it("resizes an edge with snapping and enforces a minimum length", () => {
    const wider = resizeSection([VERSE], "s1", "end", 5.9, "bar", GRID);
    expect(wider[0].endSeconds).toBe(6);

    const existing = [VERSE];
    const tooShort = resizeSection(existing, "s1", "start", 7.99, "free", GRID);
    expect(tooShort).toBe(existing);
  });

  it("deletes a section", () => {
    expect(deleteSection([VERSE], "s1")).toEqual([]);
  });

  it("finds the section containing a time (end exclusive)", () => {
    expect(sectionAt([VERSE], 0)?.id).toBe("s1");
    expect(sectionAt([VERSE], 7.99)?.id).toBe("s1");
    expect(sectionAt([VERSE], 8)).toBeNull();
  });

  it("turns a section into a loop range", () => {
    expect(sectionLoopRange(VERSE)).toEqual({ startSeconds: 0, endSeconds: 8 });
  });
});

describe("draftSectionRange", () => {
  it("uses the selection when one exists", () => {
    expect(
      draftSectionRange(
        2,
        { startSeconds: 1.7, endSeconds: 3.2 },
        "bar",
        GRID,
        8,
      ),
    ).toEqual({ startSeconds: 2, endSeconds: 4 });
  });

  it("starts at the snapped playhead and spans four bars", () => {
    expect(draftSectionRange(1.9, null, "bar", GRID, 60)).toEqual({
      startSeconds: 2,
      endSeconds: 10,
    });
  });

  it("uses a four-bar length while respecting the snapped start", () => {
    expect(draftSectionRange(1.7, null, "beat", GRID, 60)).toEqual({
      startSeconds: 1.5,
      endSeconds: 9.5,
    });
    expect(draftSectionRange(1.7, null, "free", GRID, 60)).toEqual({
      startSeconds: 1.7,
      endSeconds: 9.7,
    });
  });

  it("uses the detected beat grid for the four-bar length", () => {
    const detected = {
      beats: Array.from({ length: 12 }, (_, index) => index * 0.6),
      bpb: 3,
    };
    const range = draftSectionRange(0, null, "bar", detected, 60);
    expect(range?.startSeconds).toBe(0);
    expect(range?.endSeconds).toBeCloseTo(7.2);
  });

  it("falls back to 4/4 at 120 BPM without a grid", () => {
    expect(draftSectionRange(2.3, null, "bar", null, 60)).toEqual({
      startSeconds: 2.3,
      endSeconds: 10.3,
    });
  });

  it("returns null when there is no room left", () => {
    expect(draftSectionRange(7.9, null, "bar", GRID, 8)).toBeNull();
  });
});

describe("sectionBlocks", () => {
  it("lays sections out on the shared timeline and clips them", () => {
    const blocks = sectionBlocks(
      [VERSE, { id: "s2", name: "Chorus", startSeconds: 8, endSeconds: 10 }],
      { startSeconds: 4, secondsPerPixel: 0.02 },
      400,
    );

    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ leftPx: 0, widthPx: 200 });
    expect(blocks[1]).toMatchObject({ leftPx: 200, widthPx: 100 });
  });
});

describe("uniformBeats", () => {
  it("synthesises beats from the analysis-free tempo", () => {
    const grid = uniformBeats(TEMPO, 8);
    expect(grid.bpb).toBe(4);
    expect(grid.beats).toHaveLength(16);
    expect(grid.beats[0]).toBeCloseTo(0);
    expect(grid.beats[15]).toBeCloseTo(7.5);
  });

  it("honours the grid offset", () => {
    const grid = uniformBeats({ ...TEMPO, offsetSeconds: 0.25 }, 1.25);
    expect(grid.beats[0]).toBeCloseTo(0.25);
  });

  it("returns an empty grid for an unusable tempo", () => {
    expect(uniformBeats({ ...TEMPO, bpm: 0 }, 8).beats).toEqual([]);
  });
});
