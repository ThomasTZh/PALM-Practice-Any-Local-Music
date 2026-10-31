/**
 * Reproducible acceptance measurements (t9, closes t12 finding 1).
 *
 * The numbers quoted in docs/progress.md and in the task report come from
 * this module, not from an ad-hoc probe: `measurements.test.ts` runs it and
 * prints the JSON, and the engine tests assert the same tolerances. All
 * measurements use the committed real-WASM artifact through PlaybackCore.
 *
 * Loop gap accounting is split on purpose (t12 finding 2): the engine's wet
 * start has a 5760-output-frame silent pre-roll (~16 ms at 0.5x/1.5x), which
 * is not a loop join. `measureLoop` reports `warmupMs` separately and only
 * measures quiet runs after the first audible quantum; `joinFadeMs` is the
 * width of the loop's 5 ms join notch around a wrap anchor.
 */

import { PlaybackCore } from "./mix-processor";
import {
  dominantFrequency,
  makeEngine,
  QUANTUM,
  RATE,
  rms,
  sine,
} from "./test-utils";

export const LOOP_SECONDS = 2;
export const LOOP_FRAMES = LOOP_SECONDS * RATE;

export interface PitchMeasurement {
  rate: number;
  semitones: number;
  hz: number;
  targetHz: number;
  errorPercent: number;
}

export interface DurationMeasurement {
  rate: number;
  sourceSeconds: number;
  ratio: number;
  expectedRatio: number;
  errorPercent: number;
}

export interface LoopMeasurement {
  rate: number;
  seconds: number;
  passes: number;
  wrapFrames: number[];
  spacing: number[];
  warmupMs: number;
  maxQuietMsAfterWarmup: number;
  joinFadeMs: number;
  longestWrapTimeErrorFrames: number;
}

function toneCore(frameCount: number): PlaybackCore {
  return new PlaybackCore({
    sampleRate: RATE,
    frameCount,
    sources: [{ channelCount: 2 }],
    engine: makeEngine(),
  });
}

/** Pitch of a 440 Hz source through the real engine (FFT peak). */
export function measurePitch(
  rate: number,
  semitones = 0,
  sourceSeconds = 10,
): PitchMeasurement {
  const sourceFrames = sourceSeconds * RATE;
  const core = toneCore(sourceFrames);
  core.seek(0, 0, 0);
  core.setRate(rate);
  core.setTranspose(semitones);
  const tone = sine(sourceFrames);
  core.enqueueChannels(0, [tone, tone.slice()]);
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  for (let q = 0; q < 120; q += 1) {
    core.process((q * QUANTUM) / RATE, [outL, outR]);
  }
  const samples = new Float32Array(256 * QUANTUM);
  for (let q = 0; q < 256; q += 1) {
    core.process(((120 + q) * QUANTUM) / RATE, [outL, outR]);
    samples.set(outL, q * QUANTUM);
  }
  const hz = dominantFrequency(samples);
  const targetHz = 440 * Math.pow(2, semitones / 12);
  return {
    rate,
    semitones,
    hz,
    targetHz,
    errorPercent: (Math.abs(hz - targetHz) / targetHz) * 100,
  };
}

/** Audible duration ratio of a 4 s source through the real engine. */
export function measureDuration(
  rate: number,
  sourceSeconds = 4,
): DurationMeasurement {
  const sourceFrames = sourceSeconds * RATE;
  const core = toneCore(sourceFrames);
  core.seek(0, 0, 0);
  core.setRate(rate);
  const tone = sine(sourceFrames);
  core.enqueueChannels(0, [tone, tone.slice()]);
  const totalQuanta = Math.ceil((sourceFrames / rate + RATE) / QUANTUM);
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  let first = -1;
  let last = -1;
  for (let q = 0; q < totalQuanta; q += 1) {
    core.process((q * QUANTUM) / RATE, [outL, outR]);
    if (rms(outL) > 1e-3) {
      if (first < 0) first = q;
      last = q;
    }
  }
  const audibleFrames = Math.max(0, (last - first + 1) * QUANTUM);
  const ratio = audibleFrames / sourceFrames;
  return {
    rate,
    sourceSeconds,
    ratio,
    expectedRatio: 1 / rate,
    errorPercent: Math.abs(ratio - 1 / rate) * 100,
  };
}

/**
 * Loop join fade at sample resolution around the first wrap. A constant
 * 0.5 source is attenuated only by the join notch, so the contiguous run
 * below half amplitude is the fade itself (5 ms by construction).
 */
export function measureJoinFade(
  rate: number,
  loopFrames = LOOP_FRAMES,
): number {
  const core = toneCore(loopFrames);
  core.setRate(rate);
  const preRoll = 12_288;
  core.seek(-preRoll, 0, 0, {
    start: 0,
    end: loopFrames,
    repeatCount: null,
    fade: true,
  });
  let fed = -preRoll;
  const seconds = 6;
  const quanta = Math.ceil((seconds * RATE) / QUANTUM);
  const samples = new Float32Array(quanta * QUANTUM);
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  let center = -1;
  for (let q = 0; q < quanta; q += 1) {
    if (core.buffered < core.capacity / 2) {
      const chunk = new Float32Array(loopFrames).fill(0.5);
      core.enqueueChannels(0, [chunk, chunk.slice()]);
      fed += loopFrames;
    }
    const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
    samples.set(outL, q * QUANTUM);
    if (center < 0 && result.anchor?.wrap) {
      center = Math.round(result.anchor.time * RATE);
    }
  }
  void fed;
  if (center < 0) return 0;
  let left = center;
  let right = center;
  while (left > 0 && Math.abs(samples[left]) < 0.25) left -= 1;
  while (right < samples.length && Math.abs(samples[right]) < 0.25) right += 1;
  return ((right - left) / RATE) * 1000;
}

/**
 * Loop wrap, gap and join-fade measurement on a constant 0.5 source. The
 * constant source makes the join notch directly measurable: away from a
 * wrap the output is 0.5, and the notch is the only quiet region.
 */
export function measureLoop(
  rate: number,
  seconds = 61,
  loopFrames = LOOP_FRAMES,
): LoopMeasurement {
  const core = toneCore(loopFrames);
  core.setRate(rate);
  const preRoll = 12_288;
  core.seek(-preRoll, 0, 0, {
    start: 0,
    end: loopFrames,
    repeatCount: null,
    fade: true,
  });
  const quanta = Math.ceil((seconds * RATE) / QUANTUM);
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  const wraps: Array<{ frame: number; time: number }> = [];
  const levels: number[] = [];
  for (let q = 0; q < quanta; q += 1) {
    if (core.buffered < core.capacity / 2) {
      const chunk = new Float32Array(loopFrames).fill(0.5);
      core.enqueueChannels(0, [chunk, chunk.slice()]);
    }
    const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
    if (result.anchor?.wrap) {
      wraps.push({ frame: result.anchor.frame, time: result.anchor.time });
    }
    levels.push(rms(outL));
  }
  const firstAudible = levels.findIndex((level) => level > 1e-3);
  let silentRun = 0;
  let maxSilent = 0;
  for (let q = Math.max(0, firstAudible); q < levels.length; q += 1) {
    if (levels[q] < 1e-4) {
      silentRun += 1;
      maxSilent = Math.max(maxSilent, silentRun);
    } else {
      silentRun = 0;
    }
  }
  const warmupMs =
    firstAudible < 0 ? 0 : ((firstAudible * QUANTUM) / RATE) * 1000;
  const maxQuietMsAfterWarmup = (maxSilent * QUANTUM * 1000) / RATE;

  const spacing: number[] = [];
  let longestWrapTimeErrorFrames = 0;
  for (let i = 1; i < wraps.length; i += 1) {
    spacing.push(wraps[i].frame - wraps[i - 1].frame);
    const outputSpacing = (wraps[i].time - wraps[i - 1].time) * RATE;
    longestWrapTimeErrorFrames = Math.max(
      longestWrapTimeErrorFrames,
      Math.abs(outputSpacing - loopFrames / rate),
    );
  }
  return {
    rate,
    seconds,
    passes: core.loopPasses,
    wrapFrames: wraps.map((wrap) => wrap.frame),
    spacing,
    warmupMs,
    maxQuietMsAfterWarmup,
    joinFadeMs: measureJoinFade(rate, loopFrames),
    longestWrapTimeErrorFrames,
  };
}

/** The exact table quoted in docs/progress.md and the task report. */
export interface AcceptanceMeasurements {
  pitch: PitchMeasurement[];
  transpose: PitchMeasurement[];
  duration: DurationMeasurement[];
  loop: LoopMeasurement[];
}

export function measureAcceptance(): AcceptanceMeasurements {
  return {
    pitch: [measurePitch(0.5), measurePitch(1.5)],
    transpose: [measurePitch(1, 2), measurePitch(0.5, 2), measurePitch(1.5, 2)],
    duration: [measureDuration(0.5), measureDuration(1), measureDuration(1.5)],
    loop: [measureLoop(1), measureLoop(0.5), measureLoop(1.5)],
  };
}
