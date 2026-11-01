import { describe, expect, it } from "vitest";

import {
  clampViewport,
  defaultZoomRange,
  fitViewport,
  followViewport,
  scrollViewport,
  timeToX,
  visibleEndSeconds,
  xToTime,
  zoomToSelection,
  zoomViewport,
} from "./viewport";

const WIDTH = 960;
const DURATION = 60;
const FIT = fitViewport(DURATION, WIDTH);

describe("fitViewport", () => {
  it("spans the whole track", () => {
    expect(FIT.startSeconds).toBe(0);
    expect(FIT.secondsPerPixel).toBeCloseTo(DURATION / WIDTH);
    expect(visibleEndSeconds(FIT, WIDTH)).toBeCloseTo(DURATION);
  });

  it("gives an empty track a usable span instead of dividing by zero", () => {
    const viewport = fitViewport(0, WIDTH);
    expect(viewport.startSeconds).toBe(0);
    expect(viewport.secondsPerPixel).toBeGreaterThan(0);
    expect(Number.isFinite(viewport.secondsPerPixel)).toBe(true);
  });
});

describe("zoomViewport", () => {
  it("keeps the anchored time under the anchor pixel while zooming in", () => {
    const anchorX = 480;
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 2, anchorX);

    expect(zoomed.secondsPerPixel).toBeCloseTo(FIT.secondsPerPixel / 2);
    expect(xToTime(anchorX, zoomed)).toBeCloseTo(xToTime(anchorX, FIT));
  });

  it("clamps zooming out at the fit span", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 0.5, 480);
    expect(zoomed.secondsPerPixel).toBeCloseTo(FIT.secondsPerPixel);
    expect(zoomed.startSeconds).toBe(0);
  });

  it("does not scroll before the start of the track", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    expect(zoomed.startSeconds).toBe(0);
  });
});

describe("scrollViewport", () => {
  it("moves by pixels and clamps at both ends", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const start = zoomed.startSeconds;
    const scrolled = scrollViewport(zoomed, DURATION, WIDTH, 120);

    expect(scrolled.startSeconds).toBeCloseTo(
      start + 120 * zoomed.secondsPerPixel,
    );
    expect(scrollViewport(zoomed, DURATION, WIDTH, -10_000).startSeconds).toBe(
      0,
    );
    expect(
      scrollViewport(zoomed, DURATION, WIDTH, 10_000).startSeconds,
    ).toBeCloseTo(DURATION - WIDTH * zoomed.secondsPerPixel);
  });

  it("cannot scroll a fitted viewport", () => {
    expect(scrollViewport(FIT, DURATION, WIDTH, 500)).toEqual(FIT);
  });
});

describe("zoomToSelection", () => {
  it("frames the selection with a small margin", () => {
    const viewport = zoomToSelection(
      { startSeconds: 10, endSeconds: 20 },
      DURATION,
      WIDTH,
    );

    expect(viewport.startSeconds).toBeLessThanOrEqual(10);
    expect(visibleEndSeconds(viewport, WIDTH)).toBeGreaterThanOrEqual(20);
    expect(viewport.secondsPerPixel).toBeCloseTo((10 * 1.16) / WIDTH);
  });

  it("clamps at the start of the track", () => {
    const viewport = zoomToSelection(
      { startSeconds: 0, endSeconds: 10 },
      DURATION,
      WIDTH,
    );
    expect(viewport.startSeconds).toBe(0);
    expect(visibleEndSeconds(viewport, WIDTH)).toBeGreaterThanOrEqual(10);
  });

  it("ignores an empty selection", () => {
    expect(
      zoomToSelection({ startSeconds: 5, endSeconds: 5 }, DURATION, WIDTH),
    ).toEqual(FIT);
  });
});

describe("defaultZoomRange", () => {
  it("centres eight bars on a middle playhead with the fallback grid", () => {
    expect(defaultZoomRange(30, 60, null, null)).toEqual({
      startSeconds: 22,
      endSeconds: 38,
    });
    expect(defaultZoomRange(30, 60, Number.NaN, 0)).toEqual({
      startSeconds: 22,
      endSeconds: 38,
    });
  });

  it("clamps four bars each side at the track start and end", () => {
    expect(defaultZoomRange(0, 60, 120, 4)).toEqual({
      startSeconds: 0,
      endSeconds: 8,
    });
    expect(defaultZoomRange(60, 60, 120, 4)).toEqual({
      startSeconds: 52,
      endSeconds: 60,
    });
  });

  it("uses a detected 3/4 tempo for the bar width", () => {
    expect(defaultZoomRange(30, 60, 100, 3)).toEqual({
      startSeconds: 22.8,
      endSeconds: 37.2,
    });
  });

  it("never produces an inverted window on a short track", () => {
    const range = defaultZoomRange(5, 6, 120, 4);
    expect(range.startSeconds).toBeGreaterThanOrEqual(0);
    expect(range.endSeconds).toBeLessThanOrEqual(6);
    expect(range.endSeconds).toBeGreaterThan(range.startSeconds);
  });

  it("fits the default window exactly and centres the playhead", () => {
    const range = defaultZoomRange(30, 60, 120, 4);
    const viewport = zoomToSelection(range, DURATION, WIDTH, 0);
    expect(viewport.startSeconds).toBe(22);
    expect(visibleEndSeconds(viewport, WIDTH)).toBeCloseTo(38);
    const centre = (range.startSeconds + range.endSeconds) / 2;
    expect(centre).toBe(30);
  });

  it("keeps the existing selection path with its margin", () => {
    const selected = zoomToSelection(
      { startSeconds: 10, endSeconds: 20 },
      DURATION,
      WIDTH,
    );
    expect(selected.secondsPerPixel).toBeCloseTo((10 * 1.16) / WIDTH);
  });
});

describe("followViewport", () => {
  it("pages forward when the playhead reaches the 70% line", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const span = WIDTH * zoomed.secondsPerPixel;
    const atPageLine = zoomed.startSeconds + span * 0.69;
    expect(followViewport(zoomed, atPageLine, DURATION, WIDTH)).toBe(zoomed);

    const pastPageLine = zoomed.startSeconds + span * 0.71;
    const followed = followViewport(zoomed, pastPageLine, DURATION, WIDTH);

    expect(followed.startSeconds).toBeGreaterThan(zoomed.startSeconds);
    expect(followed.startSeconds).toBeCloseTo(pastPageLine - span * 0.2);
    expect(
      followed.startSeconds <= pastPageLine &&
        pastPageLine <= visibleEndSeconds(followed, WIDTH),
    ).toBe(true);
    expect(timeToX(pastPageLine, followed)).toBeCloseTo(WIDTH * 0.2);
  });

  it("keeps a playhead that is still inside the page untouched", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const inside = xToTime(WIDTH * 0.5, zoomed);
    expect(followViewport(zoomed, inside, DURATION, WIDTH)).toBe(zoomed);
  });

  it("pages back when a loop jumps behind the visible window", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const scrolled = clampViewport(
      { startSeconds: 30, secondsPerPixel: zoomed.secondsPerPixel },
      DURATION,
      WIDTH,
    );
    const followed = followViewport(scrolled, 0, DURATION, WIDTH);
    expect(followed.startSeconds).toBe(0);
  });
});

describe("timeToX", () => {
  it("round-trips with xToTime", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 8, 100);
    expect(xToTime(timeToX(12.5, zoomed), zoomed)).toBeCloseTo(12.5);
  });
});
