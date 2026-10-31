import { describe, expect, it } from "vitest";

import {
  beginSelection,
  hasSelection,
  MIN_SELECTION_SECONDS,
  selectionSpan,
  updateSelection,
} from "./selection";

describe("selection drag", () => {
  const duration = 10;

  it("creates a selection dragging right", () => {
    const drag = beginSelection(2, duration);
    expect(updateSelection(drag, 5)).toEqual({
      startSeconds: 2,
      endSeconds: 5,
    });
  });

  it("normalises a selection dragging left", () => {
    const drag = beginSelection(5, duration);
    expect(updateSelection(drag, 2)).toEqual({
      startSeconds: 2,
      endSeconds: 5,
    });
  });

  it("clamps both ends to the track", () => {
    const drag = beginSelection(2, duration);
    expect(updateSelection(drag, -3)).toEqual({
      startSeconds: 0,
      endSeconds: 2,
    });
    expect(updateSelection(drag, 99)).toEqual({
      startSeconds: 2,
      endSeconds: 10,
    });
  });

  it("clamps the anchor when the drag starts outside the track", () => {
    expect(beginSelection(-4, duration).anchorSeconds).toBe(0);
    expect(beginSelection(40, duration).anchorSeconds).toBe(10);
  });

  it("keeps a collapsed selection for a click without movement", () => {
    const drag = beginSelection(3, duration);
    const selection = updateSelection(drag, 3);

    expect(selectionSpan(selection)).toBe(0);
    expect(hasSelection(selection)).toBe(false);
  });
});

describe("selection helpers", () => {
  it("reports a usable span only above the minimum", () => {
    const atMinimum = {
      startSeconds: 1,
      endSeconds: 1 + MIN_SELECTION_SECONDS,
    };
    expect(hasSelection(atMinimum)).toBe(true);
    expect(
      hasSelection({
        startSeconds: 1,
        endSeconds: 1 + MIN_SELECTION_SECONDS / 2,
      }),
    ).toBe(false);
  });

  it("measures the span regardless of direction", () => {
    expect(selectionSpan({ startSeconds: 5, endSeconds: 2 })).toBe(3);
  });
});
