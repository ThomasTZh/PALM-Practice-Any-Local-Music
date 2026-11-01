import {
  DEFAULT_HIGHEST_MIDI,
  DEFAULT_LOWEST_MIDI,
  createFrequencyAxis,
  frequencyAtRow,
  midiToFrequency,
  type FrequencyAxis,
} from "./axis";
import { createRealFftScratch, isPowerOfTwo, realFftPackedInto } from "./fft";
import { amplitudeToDb, normalizeDb } from "./magnitude";
import { paletteTable } from "./palette";
import { hannWindow } from "./window";

/** The analysis window the product specifies. */
export const DEFAULT_FFT_SIZE = 2048;
export const DEFAULT_ROWS = 256;
/** Default musical range C1..C8, matching the labelled note axis. */
export const DEFAULT_MIN_HZ = midiToFrequency(DEFAULT_LOWEST_MIDI);
export const DEFAULT_MAX_HZ = midiToFrequency(DEFAULT_HIGHEST_MIDI);
export const DEFAULT_FLOOR_DB = -100;
export const DEFAULT_CEILING_DB = 0;

const PALETTE_SIZE = 256;
const PALETTE = paletteTable(PALETTE_SIZE);
const HANN_CACHE = new Map<number, Float32Array>();

export interface SpectrogramComputeInput {
  /** Mono PCM starting at `pcmStartSeconds`. */
  pcm: Float32Array;
  pcmStartSeconds: number;
  sampleRate: number;
  /** Time of the left edge of the image. */
  startSeconds: number;
  secondsPerPixel: number;
  widthPx: number;
  fftSize?: number;
  rows?: number;
  minHz?: number;
  maxHz?: number;
  floorDb?: number;
  ceilingDb?: number;
}

export interface SpectrogramImage {
  width: number;
  height: number;
  /** RGBA rows, top row highest frequency. */
  pixels: Uint8ClampedArray;
  floorDb: number;
  ceilingDb: number;
  fftSize: number;
  sampleRate: number;
  startSeconds: number;
  secondsPerPixel: number;
}

export interface SpectrogramAxisRange {
  minHz: number;
  maxHz: number;
}

export function spectrogramAxisRange(
  sampleRate: number,
  minHz = DEFAULT_MIN_HZ,
  maxHz = DEFAULT_MAX_HZ,
): SpectrogramAxisRange {
  const nyquist = sampleRate / 2;
  return {
    minHz,
    maxHz: Math.min(maxHz, nyquist),
  };
}

function cachedHann(size: number): Float32Array {
  const cached = HANN_CACHE.get(size);
  if (cached !== undefined) {
    return cached;
  }
  const window = hannWindow(size);
  HANN_CACHE.set(size, window);
  return window;
}

function windowSum(window: Float32Array): number {
  let sum = 0;
  for (let index = 0; index < window.length; index += 1) {
    sum += window[index];
  }
  return sum;
}

function validate(input: SpectrogramComputeInput): {
  fftSize: number;
  rows: number;
  minHz: number;
  maxHz: number;
  floorDb: number;
  ceilingDb: number;
} {
  const fftSize = input.fftSize ?? DEFAULT_FFT_SIZE;
  const rows = input.rows ?? DEFAULT_ROWS;
  const floorDb = input.floorDb ?? DEFAULT_FLOOR_DB;
  const ceilingDb = input.ceilingDb ?? DEFAULT_CEILING_DB;
  const { minHz, maxHz } = spectrogramAxisRange(
    input.sampleRate,
    input.minHz ?? DEFAULT_MIN_HZ,
    input.maxHz ?? DEFAULT_MAX_HZ,
  );

  if (!(input.sampleRate > 0) || !Number.isFinite(input.sampleRate)) {
    throw new RangeError(
      `sample rate must be positive, got ${input.sampleRate}`,
    );
  }
  if (!isPowerOfTwo(fftSize) || fftSize < 8) {
    throw new RangeError(
      `FFT size must be a power of two of at least 8, got ${fftSize}`,
    );
  }
  if (!Number.isInteger(rows) || rows < 2) {
    throw new RangeError(`spectrogram needs at least two rows, got ${rows}`);
  }
  if (!Number.isInteger(input.widthPx) || input.widthPx < 1) {
    throw new RangeError(
      `spectrogram width must be a positive integer, got ${input.widthPx}`,
    );
  }
  if (!(input.secondsPerPixel > 0) || !Number.isFinite(input.secondsPerPixel)) {
    throw new RangeError(
      `seconds per pixel must be positive, got ${input.secondsPerPixel}`,
    );
  }
  if (floorDb >= ceilingDb) {
    throw new RangeError(
      `dB floor ${floorDb} must be below the ceiling ${ceilingDb}`,
    );
  }
  if (!(minHz > 0) || !(maxHz > minHz)) {
    throw new RangeError(
      `spectrogram needs 0 < minHz < maxHz, got ${minHz}..${maxHz}`,
    );
  }
  return { fftSize, rows, minHz, maxHz, floorDb, ceilingDb };
}

/**
 * Computes the visible spectrogram image: one FFT column per pixel, Hann
 * windowed, magnitudes mapped onto a logarithmic frequency axis and a dB
 * colour palette. Pure and synchronous; the worker owns it in the app.
 */
export function computeSpectrogram(
  input: SpectrogramComputeInput,
): SpectrogramImage {
  const { fftSize, rows, minHz, maxHz, floorDb, ceilingDb } = validate(input);
  const { pcm, sampleRate, startSeconds, secondsPerPixel, widthPx } = input;
  const axis: FrequencyAxis = createFrequencyAxis(minHz, maxHz, rows);
  const window = cachedHann(fftSize);
  const gain = windowSum(window);
  const binHz = sampleRate / fftSize;
  const maxBin = fftSize >> 1;
  const lowerBins = new Uint16Array(rows);
  const upperBins = new Uint16Array(rows);
  const fractions = new Float32Array(rows);
  for (let row = 0; row < rows; row += 1) {
    const bin = frequencyAtRow(axis, row) / binHz;
    const lower = Math.min(maxBin, Math.max(0, Math.floor(bin)));
    lowerBins[row] = lower;
    upperBins[row] = Math.min(maxBin, lower + 1);
    fractions[row] = bin - lower;
  }

  // Only the bins the log axis actually touches are transformed per column.
  const usedBins: number[] = [];
  const binSlots = new Int32Array(maxBin + 1).fill(-1);
  for (let row = 0; row < rows; row += 1) {
    for (const bin of [lowerBins[row], upperBins[row]]) {
      if (binSlots[bin] === -1) {
        binSlots[bin] = usedBins.length;
        usedBins.push(bin);
      }
    }
  }
  const lowerSlots = new Uint16Array(rows);
  const upperSlots = new Uint16Array(rows);
  for (let row = 0; row < rows; row += 1) {
    lowerSlots[row] = binSlots[lowerBins[row]];
    upperSlots[row] = binSlots[upperBins[row]];
  }

  const pixels = new Uint8ClampedArray(widthPx * rows * 4);
  const re = new Float32Array(maxBin + 1);
  const im = new Float32Array(maxBin + 1);
  const scratch = createRealFftScratch(fftSize);
  const magnitudes = new Float32Array(usedBins.length);
  const half = fftSize >> 1;
  const pcmStartSeconds = input.pcmStartSeconds;
  const zr = scratch.re;
  const zi = scratch.im;

  for (let x = 0; x < widthPx; x += 1) {
    const time = startSeconds + x * secondsPerPixel;
    const centre = Math.round((time - pcmStartSeconds) * sampleRate);
    const first = centre - half;

    if (first >= 0 && first + fftSize <= pcm.length) {
      for (let index = 0; index < half; index += 1) {
        const source = first + index * 2;
        zr[index] = pcm[source] * window[index * 2];
        zi[index] = pcm[source + 1] * window[index * 2 + 1];
      }
    } else {
      for (let index = 0; index < half; index += 1) {
        const even = first + index * 2;
        const odd = even + 1;
        zr[index] =
          even >= 0 && even < pcm.length ? pcm[even] * window[index * 2] : 0;
        zi[index] =
          odd >= 0 && odd < pcm.length ? pcm[odd] * window[index * 2 + 1] : 0;
      }
    }
    realFftPackedInto(scratch, re, im);

    for (let slot = 0; slot < usedBins.length; slot += 1) {
      const bin = usedBins[slot];
      magnitudes[slot] = Math.sqrt(re[bin] * re[bin] + im[bin] * im[bin]);
    }

    for (let row = 0; row < rows; row += 1) {
      const lowerMagnitude = magnitudes[lowerSlots[row]];
      const upperMagnitude = magnitudes[upperSlots[row]];
      const magnitude =
        lowerMagnitude + (upperMagnitude - lowerMagnitude) * fractions[row];
      const amplitude = (2 * magnitude) / gain;
      const level = normalizeDb(amplitudeToDb(amplitude), floorDb, ceilingDb);
      const paletteIndex = Math.round(level * (PALETTE_SIZE - 1));
      const target = (row * widthPx + x) * 4;
      const source = paletteIndex * 4;
      pixels[target] = PALETTE[source];
      pixels[target + 1] = PALETTE[source + 1];
      pixels[target + 2] = PALETTE[source + 2];
      pixels[target + 3] = PALETTE[source + 3];
    }
  }

  return {
    width: widthPx,
    height: rows,
    pixels,
    floorDb,
    ceilingDb,
    fftSize,
    sampleRate,
    startSeconds,
    secondsPerPixel,
  };
}
