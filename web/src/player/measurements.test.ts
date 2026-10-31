// @vitest-environment node
/**
 * Committed measurement harness (t9, closes t12 finding 1).
 *
 * Run this file to reproduce every number quoted in docs/progress.md and the
 * t9 report:
 *
 *   pnpm --dir web exec vitest run src/player/measurements.test.ts
 *
 * The loop section reports warm-up and join fade separately (t12 finding 2):
 * `warmupMs` is the wet-path pre-roll, `maxQuietMsAfterWarmup` is the longest
 * quiet run after audio starts, and `joinFadeMs` is the 5 ms join notch.
 */

import { describe, expect, it } from "vitest";
import {
  LOOP_FRAMES,
  LOOP_SECONDS,
  measureAcceptance,
  measureLoop,
  measurePitch,
} from "./measurements";
import { QUANTUM, RATE } from "./test-utils";

const measurements = measureAcceptance();

describe("quoted acceptance measurements", () => {
  it("keeps pitch within 1% at 0.5x and 1.5x", () => {
    for (const measurement of measurements.pitch) {
      expect(Math.abs(measurement.hz - 440) / 440).toBeLessThan(0.01);
    }
  });

  it("shifts +2 semitones to 493.9 Hz within 1% at 1x/0.5x/1.5x", () => {
    for (const measurement of measurements.transpose) {
      expect(measurement.semitones).toBe(2);
      expect(measurement.errorPercent).toBeLessThan(1);
    }
  });

  it("matches the duration ratio within 1.5% at 0.5x/1x/1.5x", () => {
    for (const measurement of measurements.duration) {
      expect(measurement.errorPercent).toBeLessThan(1.5);
    }
  });

  it("wraps the 2 s loop exactly, with warm-up and join fade separated", () => {
    for (const measurement of measurements.loop) {
      expect(measurement.spacing.every((gap) => gap === LOOP_FRAMES)).toBe(
        true,
      );
      expect(measurement.passes).toBeGreaterThanOrEqual(
        Math.floor((measurement.seconds * measurement.rate) / LOOP_SECONDS),
      );
      expect(measurement.maxQuietMsAfterWarmup).toBeLessThan(10);
      expect(measurement.joinFadeMs).toBeGreaterThan(4);
      expect(measurement.joinFadeMs).toBeLessThan(6);
      expect(measurement.longestWrapTimeErrorFrames).toBeLessThan(
        QUANTUM / measurement.rate,
      );
    }
    const fast = measurements.loop.find((entry) => entry.rate === 0.5);
    const unity = measurements.loop.find((entry) => entry.rate === 1);
    // The wet path has a ~16 ms silent pre-roll; the dry path at 1x does not.
    expect(fast?.warmupMs).toBeCloseTo((6 * QUANTUM * 1000) / RATE, 3);
    expect(unity?.warmupMs).toBe(0);
  });

  it("is deterministic for the committed WASM artifact", () => {
    const first = measurePitch(0.5);
    const second = measurePitch(0.5);
    expect(first.hz).toBe(second.hz);
    const loop = measureLoop(1, 6);
    expect(loop.spacing.every((gap) => gap === LOOP_FRAMES)).toBe(true);
  });

  it("prints the exact table", () => {
    process.stdout.write(
      `\n${JSON.stringify(
        {
          pitch: measurements.pitch.map(({ rate, hz, errorPercent }) => ({
            rate,
            hz,
            errorPercent,
          })),
          transpose: measurements.transpose.map(
            ({ rate, hz, targetHz, errorPercent }) => ({
              rate,
              hz,
              targetHz,
              errorPercent,
            }),
          ),
          duration: measurements.duration.map(
            ({ rate, ratio, expectedRatio, errorPercent }) => ({
              rate,
              ratio,
              expectedRatio,
              errorPercent,
            }),
          ),
          loop: measurements.loop.map(
            ({
              rate,
              passes,
              warmupMs,
              maxQuietMsAfterWarmup,
              joinFadeMs,
              longestWrapTimeErrorFrames,
            }) => ({
              rate,
              passes,
              warmupMs,
              maxQuietMsAfterWarmup,
              joinFadeMs,
              longestWrapTimeErrorFrames,
            }),
          ),
        },
        null,
        2,
      )}\n`,
    );
    expect(measurements.loop.length).toBe(3);
  });
});
