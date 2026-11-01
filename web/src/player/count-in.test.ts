// @vitest-environment node
/**
 * Count-in independence (t37).
 *
 * Count-in bars must be audible on any play: with the metronome toggle off,
 * without a loop, and with a detected or fallback tempo. The count-in uses
 * its own click pool; the metronome keeps its toggle exactly as before.
 *
 * Click frames are asserted on the real committed WASM for the four
 * loop/no-loop × metronome-off/on cases.
 */

import { describe, expect, it } from "vitest";
import { PlaybackCore } from "./mix-processor";
import { clickOnsets, makeEngine, QUANTUM, RATE } from "./test-utils";

const BEAT = RATE / 2; // 120 BPM
const BEATS_PER_BAR = 4;
const BAR_FRAMES = BEAT * BEATS_PER_BAR; // 96 000 output frames
const LOOP_FRAMES = 2 * RATE;

interface CountInRun {
  left: Float32Array;
  core: PlaybackCore;
}

function makeCore(frameCount: number): PlaybackCore {
  const core = new PlaybackCore({
    sampleRate: RATE,
    frameCount,
    sources: [{ channelCount: 2 }],
    engine: makeEngine(),
  });
  core.resume();
  return core;
}

function feedSilence(core: PlaybackCore, frames: number): void {
  const chunk = new Float32Array(frames);
  expect(core.enqueueChannels(0, [chunk, chunk.slice()])).toBe(true);
}

function runCountIn(options: {
  loop: boolean;
  metronome: boolean;
  rate?: number;
  bpb?: number;
  beatFrames?: number;
  bars?: number;
}): CountInRun {
  const rate = options.rate ?? 1;
  const bpb = options.bpb ?? BEATS_PER_BAR;
  const beatFrames = options.beatFrames ?? BEAT;
  const bars = options.bars ?? 1;
  const total = bars * bpb * beatFrames;
  const frameCount = options.loop ? LOOP_FRAMES : 10 * RATE;
  const core = makeCore(frameCount);
  core.setRate(rate);
  if (options.loop) {
    core.seek(0, 0, 0, {
      start: 0,
      end: LOOP_FRAMES,
      repeatCount: null,
      fade: true,
    });
    feedSilence(core, LOOP_FRAMES);
  } else {
    core.seek(0, 0, 0);
    feedSilence(core, frameCount);
  }
  core.setMetronomeVolume(options.metronome ? 0.8 : 0);
  core.setBeats(
    [0, 1, 2, 3, 4, 5, 6, 7].map((index) => ({
      frame: index * 24_000,
      strength: index % bpb === 0 ? ("downbeat" as const) : ("beat" as const),
    })),
  );
  core.startCountIn({ bars, beatsPerBar: bpb, beatFrames });
  const quanta = Math.ceil((total + 4 * beatFrames + RATE / 2) / QUANTUM);
  const left = new Float32Array(quanta * QUANTUM);
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  for (let q = 0; q < quanta; q += 1) {
    if (options.loop && core.buffered < core.capacity / 2) {
      feedSilence(core, LOOP_FRAMES);
    }
    core.process((q * QUANTUM) / RATE, [outL, outR]);
    left.set(outL, q * QUANTUM);
  }
  return { left, core };
}

/** Count-in clicks at 120 BPM 4/4, one bar. */
function countInFrames(onsets: number[], total: number): number[] {
  return onsets.filter((frame) => frame < total);
}

describe("count-in with metronome off", () => {
  it("clicks for one bar with no loop, then plays on with no metronome", () => {
    const { left, core } = runCountIn({ loop: false, metronome: false });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    expect(countInFrames(onsets, BAR_FRAMES).length).toBe(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(Math.abs(onsets[beat] - beat * BEAT)).toBeLessThanOrEqual(2);
    }
    // Metronome off: nothing after the count-in.
    expect(onsets.filter((frame) => frame >= BAR_FRAMES)).toEqual([]);
    expect(core.position).toBeGreaterThan(0);
  });

  it("clicks with a loop installed and no metronome afterwards", () => {
    const { left, core } = runCountIn({ loop: true, metronome: false });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    expect(countInFrames(onsets, BAR_FRAMES).length).toBe(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(Math.abs(onsets[beat] - beat * BEAT)).toBeLessThanOrEqual(2);
    }
    expect(onsets.filter((frame) => frame >= BAR_FRAMES)).toEqual([]);
    expect(core.loopPasses).toBeGreaterThanOrEqual(0);
  });
});

describe("count-in with metronome on", () => {
  it("clicks for one bar with no loop, then the metronome continues", () => {
    const { left } = runCountIn({ loop: false, metronome: true });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    expect(countInFrames(onsets, BAR_FRAMES).length).toBe(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(Math.abs(onsets[beat] - beat * BEAT)).toBeLessThanOrEqual(2);
    }
    const after = onsets.filter((frame) => frame >= BAR_FRAMES);
    expect(after.length).toBeGreaterThanOrEqual(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(
        Math.abs(after[beat] - (BAR_FRAMES + beat * BEAT)),
      ).toBeLessThanOrEqual(2);
    }
  });

  it("clicks with a loop and the metronome continues", () => {
    const { left } = runCountIn({ loop: true, metronome: true });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    expect(countInFrames(onsets, BAR_FRAMES).length).toBe(4);
    const after = onsets.filter((frame) => frame >= BAR_FRAMES);
    expect(after.length).toBeGreaterThanOrEqual(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(
        Math.abs(after[beat] - (BAR_FRAMES + beat * BEAT)),
      ).toBeLessThanOrEqual(2);
    }
  });
});

describe("tempo, meter and speed independence", () => {
  it("uses a detected 3/4 grid at 100 BPM", () => {
    const beatFrames = 28_800; // 60 / 100 s at 48 kHz
    const { left } = runCountIn({
      loop: false,
      metronome: false,
      bpb: 3,
      beatFrames,
    });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    const total = 3 * beatFrames;
    const clicks = countInFrames(onsets, total);
    expect(clicks.length).toBe(3);
    for (let beat = 0; beat < 3; beat += 1) {
      expect(Math.abs(clicks[beat] - beat * beatFrames)).toBeLessThanOrEqual(2);
    }
  });

  it("counts in at 0.5x without a loop and still starts playback", () => {
    const { left, core } = runCountIn({
      loop: false,
      metronome: false,
      rate: 0.5,
    });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    expect(countInFrames(onsets, BAR_FRAMES).length).toBe(4);
    for (let beat = 0; beat < 4; beat += 1) {
      expect(Math.abs(onsets[beat] - beat * BEAT)).toBeLessThanOrEqual(2);
    }
    expect(onsets.filter((frame) => frame >= BAR_FRAMES)).toEqual([]);
    // The count-in is output time, not source time: it stays one bar.
    expect(core.position).toBeGreaterThan(0);
  });

  it("uses the 120/4 fallback callback shape with two bars", () => {
    const { left } = runCountIn({
      loop: false,
      metronome: false,
      bars: 2,
    });
    const onsets = clickOnsets(left).map((onset) => onset.frame);
    const total = 2 * BAR_FRAMES;
    const clicks = countInFrames(onsets, total);
    expect(clicks.length).toBe(8);
    expect(clicks[4]).toBeGreaterThanOrEqual(BAR_FRAMES - 2);
    expect(Math.abs(clicks[4] - BAR_FRAMES)).toBeLessThanOrEqual(2);
  });
});
