// @vitest-environment node
/**
 * Acceptance tests for the playback core driven by the REAL Signalsmith
 * Stretch WASM (t2 contract):
 *
 * - pitch is preserved at 0.5× and 1.5× (440 Hz ±1%);
 * - output duration scales with the rate;
 * - +2 semitones yields 493.9 Hz ±1%, independent of the rate;
 * - a 2 s loop runs ten passes with no gap over 20 ms and no drift over
 *   60 s (wrap anchors exactly one loop length apart);
 * - metronome clicks follow the supplied beat list with an accented bar
 *   start, and count-in bars precede the first loop pass;
 * - missing source, underrun and out-of-range controls never throw into
 *   the render callback.
 */

import { describe, expect, it } from "vitest";
import { PlaybackCore } from "./mix-processor";
import {
  clickOnsets,
  dominantFrequency,
  makeEngine,
  QUANTUM,
  RATE,
  render,
  rms,
  sine,
} from "./test-utils";

const SOURCE_SECONDS = 10;
const SOURCE_FRAMES = SOURCE_SECONDS * RATE;

function makeCore(
  options: { engine?: boolean; frameCount?: number } = {},
): PlaybackCore {
  const engine = options.engine === false ? null : makeEngine();
  return new PlaybackCore({
    sampleRate: RATE,
    frameCount: options.frameCount ?? SOURCE_FRAMES,
    sources: [{ channelCount: 2 }],
    ...(engine ? { engine } : {}),
  });
}

/** Feed a full-length stereo tone once; the default ring holds 12 s. */
function feedTone(core: PlaybackCore, frames = SOURCE_FRAMES): void {
  const tone = sine(frames);
  core.enqueueChannels(0, [tone, tone.slice()]);
}

/** Pitch of the steady output after the engine warm-up. */
function measurePitch(core: PlaybackCore): number {
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  // 120 quanta cover the 5760-frame wet pre-roll at every rate.
  for (let q = 0; q < 120; q += 1)
    core.process((q * QUANTUM) / RATE, [outL, outR]);
  const samples = new Float32Array(256 * QUANTUM);
  for (let q = 0; q < 256; q += 1) {
    core.process(((120 + q) * QUANTUM) / RATE, [outL, outR]);
    samples.set(outL, q * QUANTUM);
  }
  return dominantFrequency(samples);
}

describe("pitch through the real stretch WASM", () => {
  it.each([0.5, 1.5])("keeps 440 Hz at %sx within 1%%", (rate) => {
    const core = makeCore();
    core.seek(0, 0, 0);
    core.setRate(rate);
    feedTone(core);
    const measured = measurePitch(core);
    expect(measured).toBeGreaterThan(440 * 0.99);
    expect(measured).toBeLessThan(440 * 1.01);
  });

  it.each([1, 0.5, 1.5])(
    "shifts +2 semitones to 493.9 Hz at %sx within 1%%",
    (rate) => {
      const core = makeCore();
      core.seek(0, 0, 0);
      core.setRate(rate);
      core.setTranspose(2);
      feedTone(core);
      const measured = measurePitch(core);
      const expected = 440 * Math.pow(2, 2 / 12);
      expect(measured).toBeGreaterThan(expected * 0.99);
      expect(measured).toBeLessThan(expected * 1.01);
    },
  );

  it("clamps transpose to ±12 semitones and treats NaN as 0", () => {
    const core = makeCore();
    expect(core.setTranspose(99)).toBe(12);
    expect(core.setTranspose(-99)).toBe(-12);
    expect(core.setTranspose(Number.NaN)).toBe(0);
    expect(core.setTranspose(2)).toBe(2);
  });
});

describe("duration scales with the playback rate", () => {
  const seconds = 4;
  const frames = seconds * RATE;

  it.each([0.5, 1, 1.5])(
    "plays a 4 s source in %sx its source time",
    (rate) => {
      const core = makeCore({ frameCount: frames });
      core.seek(0, 0, 0);
      core.setRate(rate);
      feedTone(core, frames);
      // Render generously (warm-up + duration + tail) and measure the span
      // between the first and last quantum that carries audio.
      const quanta = Math.ceil((frames / rate + RATE) / QUANTUM);
      const { left } = render(core, quanta);
      let first = -1;
      let last = -1;
      for (let q = 0; q < quanta; q += 1) {
        const energy = rms(left, q * QUANTUM, QUANTUM);
        if (energy > 1e-3) {
          if (first < 0) first = q;
          last = q;
        }
      }
      expect(first).toBeGreaterThanOrEqual(0);
      expect(last).toBeGreaterThan(first);
      const audibleFrames = (last - first + 1) * QUANTUM;
      const ratio = audibleFrames / frames;
      // 128-frame quantum granularity at both ends; 1.5% covers it with
      // margin (measured 0.9997 / 1.999 / 0.669).
      expect(Math.abs(ratio - 1 / rate)).toBeLessThan(0.015);
    },
  );
});

describe("2 s practice loop over 60 s", () => {
  const LOOP = 2 * RATE;

  /** Periodic stream content: 440 Hz repeats every 880 cycles, so the join is smooth. */
  function streamChunk(
    streamStart: number,
    frames: number,
  ): [Float32Array, Float32Array] {
    const left = new Float32Array(frames);
    const right = new Float32Array(frames);
    for (let i = 0; i < frames; i += 1) {
      const sourceFrame = (((streamStart + i) % LOOP) + LOOP) % LOOP;
      const value = 0.5 * Math.sin((2 * Math.PI * 440 * sourceFrame) / RATE);
      left[i] = value;
      right[i] = value;
    }
    return [left, right];
  }

  // The loop test renders once and measures both properties; the helper
  // shape above is folded into the test to keep the fed stream exact.
  it.each([1, 0.5, 1.5])(
    "wraps exactly every loop length and never gaps over 20 ms at %sx",
    (rate) => {
      const core = makeCore({ frameCount: LOOP });
      core.setRate(rate);
      const preRoll = 12_288;
      core.seek(-preRoll, 0, 0, {
        start: 0,
        end: LOOP,
        repeatCount: null,
        fade: true,
      });
      let fed = -preRoll;
      const seconds = 61;
      const quanta = Math.ceil((seconds * RATE) / QUANTUM);
      const wraps: Array<{ frame: number; time: number }> = [];
      let silentRun = 0;
      let maxSilent = 0;
      const outL = new Float32Array(QUANTUM);
      const outR = new Float32Array(QUANTUM);
      for (let q = 0; q < quanta; q += 1) {
        if (core.buffered < core.capacity / 2) {
          const [left, right] = streamChunk(fed, LOOP);
          expect(core.enqueueChannels(0, [left, right])).toBe(true);
          fed += LOOP;
        }
        const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
        if (result.anchor?.wrap)
          wraps.push({ frame: result.anchor.frame, time: result.anchor.time });
        if (rms(outL) < 1e-4) {
          silentRun += 1;
          maxSilent = Math.max(maxSilent, silentRun);
        } else {
          silentRun = 0;
        }
      }
      const expectedPasses = Math.floor((seconds * rate) / (LOOP / RATE));
      expect(core.loopPasses).toBeGreaterThanOrEqual(expectedPasses);
      expect(wraps.length).toBeGreaterThanOrEqual(10);
      // No drift: every crossing is exactly one loop length after the last.
      for (let i = 1; i < wraps.length; i += 1) {
        expect(wraps[i].frame - wraps[i - 1].frame).toBe(LOOP);
      }
      const firstWrap = wraps[0];
      expect(firstWrap.frame).toBe(LOOP);
      // Ten passes fit in this run; check the tenth crossing precisely.
      expect(wraps[9].frame).toBe(10 * LOOP);
      // No gap over 20 ms: the 5 ms join fade is the longest quiet stretch.
      expect(maxSilent * (QUANTUM / RATE)).toBeLessThan(0.02);
      // No cumulative drift over the whole run: steady-state wrap time
      // spacing is exactly one pass of output time (the initial 50 ms rate
      // ramp only shifts the first crossing, never the spacing).
      for (let i = 1; i < wraps.length; i += 1) {
        const outputSpacing = (wraps[i].time - wraps[i - 1].time) * RATE;
        expect(Math.abs(outputSpacing - LOOP / rate)).toBeLessThan(
          (QUANTUM / rate) * 2,
        );
      }
    },
  );
});

describe("metronome beat list", () => {
  const LOOP = 2 * RATE;

  it("renders clicks on the supplied beats and accents bar starts", () => {
    const core = makeCore({ engine: false, frameCount: LOOP });
    core.seek(0, 0, 0, { start: 0, end: LOOP, repeatCount: null, fade: false });
    const beats = [0, 24000, 48000, 72000].map((frame, index) => ({
      frame,
      strength: (index === 0 ? "downbeat" : "beat") as "downbeat" | "beat",
    }));
    core.setBeats(beats);
    core.setMetronomeVolume(0.8);
    const silence = new Float32Array(LOOP);
    core.enqueueChannels(0, [silence, silence.slice()]);
    const { left } = render(core, Math.ceil((2 * LOOP) / QUANTUM), () => {
      if (core.buffered < core.capacity / 2) {
        expect(core.enqueueChannels(0, [silence, silence.slice()])).toBe(true);
      }
    });
    const onsets = clickOnsets(left);
    const expected = [0, 24000, 48000, 72000, 96000, 120000, 144000, 168000];
    const measured = onsets
      .slice(0, expected.length)
      .map((onset) => onset.frame);
    for (let i = 0; i < expected.length; i += 1) {
      expect(Math.abs(measured[i] - expected[i])).toBeLessThanOrEqual(2);
    }
    // The downbeat table is louder than the beat table.
    expect(onsets[0].peak).toBeGreaterThan(onsets[1].peak * 1.2);
    expect(onsets[4].peak).toBeGreaterThan(onsets[5].peak * 1.2);
  });

  it("maps beats through the playback rate (engine path)", () => {
    const core = makeCore({ frameCount: SOURCE_FRAMES });
    core.setRate(0.5);
    core.seek(0, 0, 0);
    core.setBeats([
      { frame: 0, strength: "downbeat" },
      { frame: 24000, strength: "beat" },
    ]);
    core.setMetronomeVolume(0.8);
    const silence = new Float32Array(SOURCE_FRAMES);
    core.enqueueChannels(0, [silence, silence.slice()]);
    const { left } = render(core, 500);
    const onsets = clickOnsets(left);
    expect(onsets.length).toBeGreaterThanOrEqual(2);
    // At 0.5× the 0.5 s beat spacing becomes 1 s of output (the first
    // click starts after the engine's silent pre-roll).
    expect(
      Math.abs(onsets[1].frame - onsets[0].frame - RATE),
    ).toBeLessThanOrEqual(4);
  });
});

describe("count-in before the first loop pass", () => {
  const LOOP = 2 * RATE;
  const BEAT = RATE / 2; // 120 BPM

  it("plays one bar of accented clicks, then starts the loop", () => {
    const core = makeCore({ engine: false, frameCount: LOOP });
    core.seek(0, 0, 0, { start: 0, end: LOOP, repeatCount: null, fade: false });
    feedTone(core, LOOP);
    const total = core.startCountIn({
      bars: 1,
      beatsPerBar: 4,
      beatFrames: BEAT,
    });
    expect(total).toBe(4 * BEAT);
    const quanta = Math.ceil((4 * BEAT + 4 * QUANTUM) / QUANTUM);
    const results: boolean[] = [];
    const { left } = render(core, quanta, (result) => {
      if (result.countInDone) results.push(true);
      // The cursor stays frozen for the whole count-in.
      if (result.countInDone) expect(core.position).toBe(0);
    });
    expect(results).toEqual([true]);
    // Four clicks, one per beat, accented on the bar start.
    const onsets = clickOnsets(left).filter((onset) => onset.frame < 4 * BEAT);
    expect(onsets.length).toBe(4);
    for (let i = 0; i < 4; i += 1) {
      expect(Math.abs(onsets[i].frame - i * BEAT)).toBeLessThanOrEqual(2);
    }
    expect(onsets[0].peak).toBeGreaterThan(onsets[1].peak * 1.2);
    // The first loop pass starts only after the last click: the gaps
    // between count-in clicks carry no tone, and the tone resumes
    // immediately after the count-in ends.
    expect(
      rms(left, Math.round(BEAT + 0.1 * RATE), BEAT - Math.round(0.1 * RATE)),
    ).toBeLessThan(0.005);
    expect(rms(left, 4 * BEAT, 4 * QUANTUM)).toBeGreaterThan(0.1);
    expect(core.countInRemaining()).toBe(0);
  });

  it("cancels a count-in on pause", () => {
    const core = makeCore({ engine: false, frameCount: LOOP });
    core.seek(0, 0, 0, { start: 0, end: LOOP, repeatCount: null, fade: false });
    core.startCountIn({ bars: 2, beatsPerBar: 4, beatFrames: BEAT });
    core.pause();
    expect(core.countInRemaining()).toBe(0);
    expect(core.paused).toBe(true);
  });
});

describe("audio-thread error handling", () => {
  it("stays silent without throwing when no source data exists", () => {
    const core = makeCore({ frameCount: SOURCE_FRAMES });
    core.seek(0, 0, 0);
    const outL = new Float32Array(QUANTUM);
    const outR = new Float32Array(QUANTUM);
    for (let q = 0; q < 8; q += 1) {
      const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
      expect(result.underrun).toBe(false);
      expect(outL.every((value) => value === 0)).toBe(true);
    }
    expect(core.position).toBe(0);
  });

  it("reports underrun on the engine path and recovers when data arrives", () => {
    const core = makeCore({ frameCount: SOURCE_FRAMES });
    core.seek(0, 0, 0);
    core.enqueueChannels(0, [sine(100), sine(100)]);
    const outL = new Float32Array(QUANTUM);
    const outR = new Float32Array(QUANTUM);
    const starved = core.process(0, [outL, outR]);
    expect(starved.underrun).toBe(true);
    expect(core.position).toBe(0);
    feedTone(core);
    const recovered = core.process(QUANTUM / RATE, [outL, outR]);
    expect(recovered.underrun).toBe(false);
    expect(rms(outL)).toBeGreaterThan(0.1);
  });

  it("clamps out-of-range rates without throwing", () => {
    const core = makeCore();
    core.setRate(100);
    expect(core.rateTarget).toBe(2);
    core.setRate(-1);
    expect(core.rateTarget).toBe(0.25);
    core.setRate(Number.NaN);
    expect(core.rateTarget).toBe(1);
    core.setRate(Number.POSITIVE_INFINITY);
    expect(core.rateTarget).toBe(1);
  });

  it("accepts a master gain and mixer params without throwing on bad values", () => {
    const core = makeCore();
    core.setMasterGain(0.5);
    core.setMasterGain(Number.NaN);
    core.setSourceParams(0, { gain: 0.5, balance: 2 });
    core.setSourceParams(9, { gain: 1 });
    expect(core.params[0].balance).toBe(1);
  });
});
