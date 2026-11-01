// @vitest-environment node
/**
 * t9 integration tests on the real WASM engine: the mix + four stems as one
 * aligned group, live mixer changes, a bar-snapped section loop, speed
 * changes without pitch/position glitches, and 60 s sessions at 1x/0.5x.
 */

import { describe, expect, it } from "vitest";
import { PlaybackCore } from "./mix-processor";
import {
  dominantFrequency,
  makeEngine,
  QUANTUM,
  RATE,
  rms,
  sine,
} from "./test-utils";

const STEM_VALUES = [0, 0.1, 0.2, 0.3, 0.4];

function makeGroup(
  frameCount: number,
  sourceCount = 5,
  engine = true,
): PlaybackCore {
  const stretch = engine ? makeEngine() : null;
  const core = new PlaybackCore({
    sampleRate: RATE,
    frameCount,
    sources: Array.from({ length: sourceCount }, () => ({
      channelCount: 2,
    })),
    ...(stretch ? { engine: stretch } : {}),
  });
  core.resume();
  return core;
}

function constantSource(value: number, frames: number): Float32Array[] {
  return [
    new Float32Array(frames).fill(value),
    new Float32Array(frames).fill(value),
  ];
}

function feedAll(core: PlaybackCore, frames: number): boolean {
  let accepted = false;
  for (let index = 0; index < core.sources.length; index += 1) {
    const source = core.sources[index];
    const remaining = core.frameCount - source.position;
    if (remaining <= 0) continue;
    accepted =
      core.enqueueChannels(
        index,
        constantSource(STEM_VALUES[index] ?? 0, Math.min(frames, remaining)),
      ) || accepted;
  }
  return accepted;
}

function processQuanta(core: PlaybackCore, count: number, from = 0): number[] {
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  const peaks: number[] = [];
  for (let q = 0; q < count; q += 1) {
    core.process(((from + q) * QUANTUM) / RATE, [outL, outR]);
    peaks.push(rms(outL));
  }
  return peaks;
}

describe("mix + four stems", () => {
  it("sums five aligned sources sample-exactly at 1x", () => {
    const core = makeGroup(24_000);
    core.seek(0, 0, 0);
    feedAll(core, 24_000);
    const outL = new Float32Array(QUANTUM);
    const outR = new Float32Array(QUANTUM);
    core.process(0, [outL, outR]);
    const expected = STEM_VALUES.reduce((sum, value) => sum + value, 0);
    for (const index of [0, 1, 63, 127]) {
      expect(outL[index]).toBeCloseTo(expected, 6);
      expect(outR[index]).toBeCloseTo(expected, 6);
    }
    // Every source advanced by the same amount: no relative drift. The
    // source cursor runs ahead of the output by the ring lookahead.
    const positions = core.sources.map((source) => source.position);
    expect(new Set(positions).size).toBe(1);
    expect(positions[0]).toBeGreaterThan(0);
    expect(core.position).toBe(QUANTUM);
  });

  it("applies mute, solo and gain while the cursor keeps moving", () => {
    const core = makeGroup(10 * RATE);
    core.seek(0, 0, 0);
    feedAll(core, 10 * RATE);
    processQuanta(core, 20);
    const position = core.position;

    core.setSourceParams(1, { mute: true });
    // The wet path reads a mix ring ahead of the audible cursor; the 5 ms
    // ramp plus that lookahead is the documented control-response latency.
    processQuanta(core, 200, 20);
    expect(core.position).toBeGreaterThan(position);
    // Source 1 (0.1) is silenced; the others still sum.
    const mutedOut = new Float32Array(QUANTUM);
    core.process((220 * QUANTUM) / RATE, [mutedOut, new Float32Array(QUANTUM)]);
    expect(mutedOut[0]).toBeCloseTo(0.2 + 0.3 + 0.4, 5);

    core.setSourceParams(2, { solo: true });
    processQuanta(core, 200, 221);
    const soloOut = new Float32Array(QUANTUM);
    core.process((421 * QUANTUM) / RATE, [soloOut, new Float32Array(QUANTUM)]);
    expect(soloOut[0]).toBeCloseTo(0.2, 5);

    core.setSourceParams(2, { solo: false, gain: 0.5 });
    core.setSourceParams(1, { mute: false });
    processQuanta(core, 200, 422);
    const gained = new Float32Array(QUANTUM);
    core.process((622 * QUANTUM) / RATE, [gained, new Float32Array(QUANTUM)]);
    expect(gained[0]).toBeCloseTo(0.1 + 0.2 * 0.5 + 0.3 + 0.4, 5);
    // The mixer changes never repositioned or restarted the group.
    expect(core.position).toBe(623 * QUANTUM);
  });
});

describe("section loop at a bar boundary", () => {
  const LOOP_START = 2 * RATE; // bar 2 at 120 BPM 4/4
  const LOOP_END = 4 * RATE; // bar 4
  const LOOP_LEN = LOOP_END - LOOP_START;

  function streamChunk(streamStart: number, frames: number): Float32Array[] {
    const left = new Float32Array(frames);
    const right = new Float32Array(frames);
    for (let i = 0; i < frames; i += 1) {
      const sourceFrame =
        LOOP_START +
        ((((streamStart + i - LOOP_START) % LOOP_LEN) + LOOP_LEN) % LOOP_LEN);
      const value = 0.5 * Math.sin((2 * Math.PI * 440 * sourceFrame) / RATE);
      left[i] = value;
      right[i] = value;
    }
    return [left, right];
  }

  it.each([1, 0.5])("wraps exactly at the section end at %sx", (rate) => {
    const core = makeGroup(LOOP_END + RATE, 1, true);
    core.setRate(rate);
    const preRoll = 12_288;
    core.seek(LOOP_START - preRoll, 0, LOOP_START, {
      start: LOOP_START,
      end: LOOP_END,
      repeatCount: null,
      fade: true,
    });
    let fed = LOOP_START - preRoll;
    const wraps: number[] = [];
    const quanta = Math.ceil((12 * RATE) / QUANTUM);
    for (let q = 0; q < quanta; q += 1) {
      if (core.buffered < core.capacity / 2) {
        expect(core.enqueueChannels(0, streamChunk(fed, LOOP_LEN))).toBe(true);
        fed += LOOP_LEN;
      }
      const outL = new Float32Array(QUANTUM);
      const outR = new Float32Array(QUANTUM);
      const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
      if (result.anchor?.wrap) wraps.push(result.anchor.frame);
    }
    expect(wraps.length).toBeGreaterThanOrEqual(2);
    expect(wraps[0]).toBe(LOOP_END);
    for (let i = 1; i < wraps.length; i += 1) {
      expect(wraps[i] - wraps[i - 1]).toBe(LOOP_LEN);
    }
    // The crossing lands on the bar boundary and the loop source is the
    // section start, not an arbitrary wrap point.
    expect(core.loopSourceOf(wraps[0])).toBe(LOOP_START);
  });
});

describe("speed changes while playing", () => {
  it("keeps 440 Hz and a continuous position through 1x -> 1.5x", () => {
    const core = makeGroup(10 * RATE, 1, true);
    core.seek(0, 0, 0);
    const tone = sine(10 * RATE);
    core.enqueueChannels(0, [tone, tone.slice()]);
    processQuanta(core, 120);
    const before = core.audible;
    core.setRate(1.5);
    // Let the 50 ms rate ramp and the dry->wet crossfade finish.
    processQuanta(core, 200, 120);
    const mid = core.audible;
    const samples = new Float32Array(256 * QUANTUM);
    const outL = new Float32Array(QUANTUM);
    const outR = new Float32Array(QUANTUM);
    let previous = core.audible;
    let maxStep = 0;
    for (let q = 0; q < 256; q += 1) {
      core.process(((320 + q) * QUANTUM) / RATE, [outL, outR]);
      samples.set(outL, q * QUANTUM);
      maxStep = Math.max(maxStep, core.audible - previous);
      previous = core.audible;
    }
    const measured = dominantFrequency(samples);
    expect(measured).toBeGreaterThan(440 * 0.99);
    expect(measured).toBeLessThan(440 * 1.01);
    expect(core.audible).toBeGreaterThan(before);
    // No reset and no jump: the cursor advances at most 2× a quantum.
    expect(maxStep).toBeLessThanOrEqual(2 * QUANTUM + 1e-6);
    expect(core.audible - before).toBeGreaterThan(0);
    // Steady state: after the ramp the cursor advances exactly 1.5×.
    expect(core.audible - mid).toBeCloseTo(1.5 * 256 * QUANTUM, -3);
  });
});

describe("60 s sessions", () => {
  it.each([1, 0.5])(
    "run without errors or silent stalls at %sx",
    (rate) => {
      const seconds = 60;
      const core = makeGroup(seconds * RATE, 5, true);
      core.setRate(rate);
      core.seek(0, 0, 0);
      feedAll(core, 4 * RATE);
      const quanta = Math.ceil((seconds * RATE) / QUANTUM);
      const outL = new Float32Array(QUANTUM);
      const outR = new Float32Array(QUANTUM);
      let silentRun = 0;
      let maxSilent = 0;
      let underruns = 0;
      for (let q = 0; q < quanta; q += 1) {
        if (core.buffered < core.capacity / 3) {
          feedAll(core, RATE);
        }
        const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
        if (result.underrun) underruns += 1;
        if (q > 200) {
          if (rms(outL) < 1e-4) {
            silentRun += 1;
            maxSilent = Math.max(maxSilent, silentRun);
          } else {
            silentRun = 0;
          }
        }
      }
      expect(underruns).toBe(0);
      expect(maxSilent * (QUANTUM / RATE)).toBeLessThan(0.02);
      expect(core.position).toBeGreaterThan(seconds * RATE * rate * 0.95);
      const positions = core.sources.map((source) => source.position);
      expect(new Set(positions).size).toBe(1);
    },
    30_000,
  );
});
