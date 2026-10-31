/**
 * Test helpers for the playback core (t2). Node-only: reads the real
 * stretch WASM artifact from disk and provides deterministic signal
 * analysis (RMS, FFT pitch, click-onset detection).
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import "./stretch/stretch-worklet.js";
import type { StretchEngineLike, PlaybackCore } from "./worklet-processor";

export const RATE = 48_000;
export const QUANTUM = 128;
export const STRETCH_WASM = fileURLToPath(
  new URL("./stretch/dist/stretch-scalar.wasm", import.meta.url),
);

export interface StretchApi {
  STRETCH_MAX_FRAMES: number;
  instantiateStretch(bytes: ArrayBuffer | Uint8Array): StretchEngineLike;
}

export function stretchApi(): StretchApi {
  const api = (globalThis as unknown as { StretchWasm?: StretchApi })
    .StretchWasm;
  if (!api) throw new Error("stretch WASM core did not attach to globalThis");
  return api;
}

export function stretchBytes(): Uint8Array {
  return readFileSync(STRETCH_WASM);
}

/** A fresh engine configured for 48 kHz (one instance per test core). */
export function makeEngine(): StretchEngineLike {
  const engine = stretchApi().instantiateStretch(stretchBytes());
  engine.configure(RATE);
  return engine;
}

export function sine(
  frames: number,
  frequency = 440,
  amplitude = 0.5,
  phase = 0,
  sampleRate = RATE,
): Float32Array {
  const out = new Float32Array(frames);
  for (let i = 0; i < frames; i += 1) {
    out[i] =
      amplitude * Math.sin((2 * Math.PI * frequency * i) / sampleRate + phase);
  }
  return out;
}

export function rms(
  samples: Float32Array,
  from = 0,
  count = samples.length - from,
): number {
  let sum = 0;
  for (let i = from; i < from + count; i += 1) sum += samples[i] * samples[i];
  return Math.sqrt(sum / Math.max(1, count));
}

/** Iterative radix-2 FFT (in place). */
function fft(real: Float64Array, imag: Float64Array): void {
  const n = real.length;
  for (let i = 1, j = 0; i < n; i += 1) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [real[i], real[j]] = [real[j], real[i]];
      [imag[i], imag[j]] = [imag[j], imag[i]];
    }
  }
  for (let length = 2; length <= n; length <<= 1) {
    const angle = (-2 * Math.PI) / length;
    const wReal = Math.cos(angle);
    const wImag = Math.sin(angle);
    for (let start = 0; start < n; start += length) {
      let curReal = 1;
      let curImag = 0;
      for (let k = 0; k < length / 2; k += 1) {
        const even = start + k;
        const odd = even + length / 2;
        const oddReal = real[odd] * curReal - imag[odd] * curImag;
        const oddImag = real[odd] * curImag + imag[odd] * curReal;
        real[odd] = real[even] - oddReal;
        imag[odd] = imag[even] - oddImag;
        real[even] += oddReal;
        imag[even] += oddImag;
        const nextReal = curReal * wReal - curImag * wImag;
        curImag = curReal * wImag + curImag * wReal;
        curReal = nextReal;
      }
    }
  }
}

/**
 * Dominant frequency of `samples` (Hann window + parabolic peak
 * interpolation). Uses the largest power-of-two prefix.
 */
export function dominantFrequency(
  samples: Float32Array,
  sampleRate = RATE,
): number {
  const n = 1 << Math.floor(Math.log2(samples.length));
  if (n < 1024)
    throw new RangeError("need at least 1024 samples for a pitch estimate");
  const real = new Float64Array(n);
  const imag = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));
    real[i] = samples[i] * window;
  }
  fft(real, imag);
  let peak = 1;
  let peakPower = -Infinity;
  for (let bin = 1; bin < n / 2; bin += 1) {
    const power = real[bin] * real[bin] + imag[bin] * imag[bin];
    if (power > peakPower) {
      peakPower = power;
      peak = bin;
    }
  }
  const magnitude = (bin: number): number => Math.hypot(real[bin], imag[bin]);
  const left = magnitude(peak - 1);
  const centre = magnitude(peak);
  const right = magnitude(peak + 1);
  const denominator = left - 2 * centre + right;
  const shift = denominator === 0 ? 0 : (0.5 * (left - right)) / denominator;
  return ((peak + shift) * sampleRate) / n;
}

export interface ClickOnset {
  frame: number;
  peak: number;
}

/**
 * Click onsets in a signal: samples above `threshold`, with a new onset
 * only after `gapFrames` of quiet. Reports the peak in the first 10 ms
 * of each click (bar accents use a louder table).
 */
export function clickOnsets(
  samples: Float32Array,
  threshold = 0.02,
  gapFrames = Math.round(RATE * 0.05),
): ClickOnset[] {
  const onsets: ClickOnset[] = [];
  let last = -Infinity;
  for (let i = 0; i < samples.length; i += 1) {
    if (Math.abs(samples[i]) <= threshold) continue;
    if (i - last < gapFrames) continue;
    let peak = 0;
    for (
      let j = i;
      j < Math.min(samples.length, i + Math.round(RATE * 0.01));
      j += 1
    ) {
      peak = Math.max(peak, Math.abs(samples[j]));
    }
    onsets.push({ frame: i, peak });
    last = i;
  }
  return onsets;
}

/** Render `quanta` quanta and concatenate the left channel. */
export function render(
  core: PlaybackCore,
  quanta: number,
  onQuantum?: (
    result: ReturnType<PlaybackCore["process"]>,
    quantum: number,
  ) => void,
): {
  left: Float32Array;
  right: Float32Array;
  results: ReturnType<PlaybackCore["process"]>[];
} {
  const left = new Float32Array(quanta * QUANTUM);
  const right = new Float32Array(quanta * QUANTUM);
  const results: ReturnType<PlaybackCore["process"]>[] = [];
  const outL = new Float32Array(QUANTUM);
  const outR = new Float32Array(QUANTUM);
  for (let q = 0; q < quanta; q += 1) {
    const result = core.process((q * QUANTUM) / RATE, [outL, outR]);
    results.push(result);
    left.set(outL, q * QUANTUM);
    right.set(outR, q * QUANTUM);
    if (onQuantum) onQuantum(result, q);
  }
  return { left, right, results };
}
