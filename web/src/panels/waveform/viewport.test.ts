import { describe, expect, it } from "vitest";

import {
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

describe("followViewport", () => {
  it("keeps the playhead in view by scrolling when it runs off the right edge", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const followed = followViewport(zoomed, 40, DURATION, WIDTH);

    expect(followed.startSeconds).toBeGreaterThan(zoomed.startSeconds);
    expect(
      followed.startSeconds <= 40 && 40 <= visibleEndSeconds(followed, WIDTH),
    ).toBe(true);
  });

  it("leaves the viewport untouched while the playhead is visible", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const inside = xToTime(WIDTH / 2, zoomed);
    expect(followViewport(zoomed, inside, DURATION, WIDTH)).toBe(zoomed);
  });

  it("scrolls back to the start when the playhead jumps home", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const scrolled = scrollViewport(zoomed, DURATION, WIDTH, 400);
    expect(followViewport(scrolled, 0, DURATION, WIDTH).startSeconds).toBe(0);
  });
});

describe("timeToX", () => {
  it("round-trips with xToTime", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 8, 100);
    expect(xToTime(timeToX(12.5, zoomed), zoomed)).toBeCloseTo(12.5);
  });
});
