// @vitest-environment node
/**
 * Silence-until-play regression (t30).
 *
 * The worklet core starts paused; a load/seek/loop/grid/speed change must
 * never make sound before an explicit resume. The engine is the real
 * committed scalar WASM, so this is the same code path the browser runs.
 */

import { describe, expect, it } from "vitest";
import { PlaybackCore } from "./mix-processor";
import { makeEngine, QUANTUM, RATE, rms, sine } from "./test-utils";

function makeCore(frameCount = 4 * RATE): PlaybackCore {
  return new PlaybackCore({
    sampleRate: RATE,
    frameCount,
    sources: [{ channelCount: 2 }],
    engine: makeEngine(),
  });
}

function feedTone(core: PlaybackCore, frames = 4 * RATE): void {
  const tone = sine(frames);
  expect(core.enqueueChannels(0, [tone, tone.slice()])).toBe(true);
}

function renderRms(core: PlaybackCore, quanta: number, from = 0): number[] {
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  const levels: number[] = [];
  for (let q = 0; q < quanta; q += 1) {
    core.process(((from + q) * QUANTUM) / RATE, [outL, outR]);
    levels.push(rms(outL));
  }
  return levels;
}

describe("silence until an explicit resume", () => {
  it("a fresh core fed PCM but never resumed renders only silence", () => {
    const core = makeCore();
    expect(core.paused).toBe(true);
    feedTone(core);
    const levels = renderRms(core, 8);
    expect(levels.every((level) => level === 0)).toBe(true);
    expect(core.paused).toBe(true);
    // The PCM stayed queued; it was not consumed into an audible render.
    expect(core.buffered).toBeGreaterThan(0);
  });

  it("resumes, pauses with the existing ramp, and resumes again", () => {
    const core = makeCore();
    feedTone(core);
    expect(renderRms(core, 4).every((level) => level === 0)).toBe(true);

    core.resume();
    const first = renderRms(core, 8, 4);
    expect(first.slice(2).some((level) => level > 0.1)).toBe(true);

    core.pause();
    const paused = renderRms(core, 12, 12);
    // The 5 ms ramp is shorter than three 128-frame quanta.
    expect(paused.slice(3).every((level) => level === 0)).toBe(true);
    expect(renderRms(core, 8, 24).every((level) => level === 0)).toBe(true);

    core.resume();
    const again = renderRms(core, 8, 32);
    expect(again.some((level) => level > 0.1)).toBe(true);
  });

  it("keeps seek, loop install, rate and metronome changes silent while paused", () => {
    const core = makeCore();
    feedTone(core);
    core.pause();
    expect(renderRms(core, 2).every((level) => level === 0)).toBe(true);

    core.seek(24_000, 0, 24_000);
    expect(core.paused).toBe(true);
    core.setLoop({
      start: 24_000,
      end: 48_000,
      repeatCount: null,
      fade: true,
    });
    expect(core.paused).toBe(true);
    core.setRate(1.5);
    expect(core.paused).toBe(true);
    core.setTranspose(2);
    expect(core.paused).toBe(true);
    core.setBeats([{ frame: 24_000, strength: "downbeat" }]);
    core.setMetronomeVolume(1);

    const levels = renderRms(core, 10, 2);
    expect(levels.every((level) => level === 0)).toBe(true);
    expect(core.paused).toBe(true);
  });

  it("a paused seek preserves the paused flag across a rate change", () => {
    const core = makeCore();
    core.setRate(0.5);
    core.seek(12_000, 0, 12_000);
    feedTone(core);
    expect(core.paused).toBe(true);
    expect(renderRms(core, 8).every((level) => level === 0)).toBe(true);
    core.seek(48_000, 0, 48_000);
    expect(core.paused).toBe(true);
    expect(renderRms(core, 8).every((level) => level === 0)).toBe(true);
  });
});
