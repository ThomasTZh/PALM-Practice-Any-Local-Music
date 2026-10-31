import { describe, expect, it } from "vitest";

import {
  barBeatTicks,
  chooseBarLabelEvery,
  chooseSecondsTicks,
  formatTickLabel,
} from "./ticks";

const FIT = { startSeconds: 0, secondsPerPixel: 60 / 960 };

describe("chooseSecondsTicks", () => {
  it("keeps major labels at least 80px apart at fit zoom", () => {
    const ticks = chooseSecondsTicks(FIT, 960);
    const majors = ticks.filter((tick) => tick.major);

    expect(majors.map((tick) => tick.time)).toEqual([
      0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55,
    ]);
    for (const tick of ticks) {
      expect(tick.time).toBeGreaterThanOrEqual(0);
      expect(tick.time).toBeLessThan(60);
    }
  });

  it("labels only the major ticks and adds minor ticks between them", () => {
    const ticks = chooseSecondsTicks(FIT, 960);
    const labelled = ticks.filter((tick) => tick.label !== null);

    expect(labelled).toHaveLength(12);
    expect(labelled[1].label).toBe("0:05");
    expect(ticks.filter((tick) => !tick.major && tick.time < 5)).toHaveLength(
      4,
    );
    expect(ticks[0]).toMatchObject({ time: 0, major: true, label: "0:00" });
  });

  it("tightens the step and anchors to the visible range when zoomed in", () => {
    const ticks = chooseSecondsTicks(
      { startSeconds: 10, secondsPerPixel: 1 / 200 },
      960,
    );

    expect(ticks[0].time).toBeCloseTo(10);
    expect(ticks[1].time - ticks[0].time).toBeCloseTo(0.1);
    expect(ticks.find((tick) => tick.major)?.label).toBe("0:10.0");
    expect(ticks[ticks.length - 1].time).toBeLessThan(14.8);
  });

  it("starts at the first visible multiple, not at zero, after scrolling", () => {
    const ticks = chooseSecondsTicks(
      { startSeconds: 7.3, secondsPerPixel: 1 / 16 },
      960,
    );

    expect(ticks[0].time).toBeCloseTo(8);
    expect(ticks.every((tick) => tick.time >= 7.3)).toBe(true);
  });
});

describe("formatTickLabel", () => {
  it("shows whole seconds for coarse steps", () => {
    expect(formatTickLabel(65, 5)).toBe("1:05");
    expect(formatTickLabel(0, 15)).toBe("0:00");
  });

  it("shows tenths for sub-second steps", () => {
    expect(formatTickLabel(5.5, 0.5)).toBe("0:05.5");
  });

  it("grows to hours", () => {
    expect(formatTickLabel(3661, 60)).toBe("1:01:01");
  });
});

describe("chooseBarLabelEvery", () => {
  it("labels every bar when bars are wide enough", () => {
    expect(chooseBarLabelEvery(200)).toBe(1);
  });

  it("thins bar labels when bars get narrow", () => {
    expect(chooseBarLabelEvery(32)).toBe(2);
    expect(chooseBarLabelEvery(5)).toBe(10);
  });
});

describe("barBeatTicks", () => {
  it("walks beats and bars for a 4/4 grid at 120 BPM", () => {
    const ticks = barBeatTicks(
      { bpm: 120, meter: { numerator: 4, denominator: 4 }, offsetSeconds: 0 },
      0,
      4.2,
      16,
    );

    expect(ticks.map((tick) => tick.time)).toEqual([
      0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4,
    ]);
    expect(
      ticks.filter((tick) => tick.downbeat).map((tick) => tick.time),
    ).toEqual([0, 2, 4]);
    expect(ticks[0]).toMatchObject({ bar: 1, beat: 1, downbeat: true });
    expect(ticks[5]).toMatchObject({ bar: 2, beat: 2, downbeat: false });
  });

  it("labels only bars that are wide enough apart", () => {
    const ticks = barBeatTicks(
      { bpm: 120, meter: { numerator: 4, denominator: 4 }, offsetSeconds: 0 },
      0,
      4.2,
      16,
    );
    const labels = ticks.filter((tick) => tick.label !== null);

    expect(labels.map((tick) => [tick.time, tick.label])).toEqual([
      [0, "1"],
      [4, "3"],
    ]);
  });

  it("respects the grid offset", () => {
    const ticks = barBeatTicks(
      {
        bpm: 120,
        meter: { numerator: 4, denominator: 4 },
        offsetSeconds: 0.25,
      },
      0,
      1.3,
      16,
    );

    expect(ticks.map((tick) => tick.time)).toEqual([0.25, 0.75, 1.25]);
    expect(ticks[0]).toMatchObject({ bar: 1, beat: 1, downbeat: true });
  });

  it("ignores a non-positive tempo instead of looping forever", () => {
    expect(
      barBeatTicks(
        { bpm: 0, meter: { numerator: 4, denominator: 4 }, offsetSeconds: 0 },
        0,
        10,
        16,
      ),
    ).toEqual([]);
  });
});
