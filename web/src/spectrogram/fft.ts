/**
 * Hand-written radix-2 FFT.
 *
 * The spectrogram runs this once per pixel column, so the implementation keeps
 * twiddle factors cached per transform size and exposes an in-place complex
 * transform plus a real-input wrapper that packs even/odd samples into one
 * complex transform of half the length.
 */

export interface RealSpectrum {
  re: Float32Array;
  im: Float32Array;
}

export interface RealFftScratch {
  re: Float32Array;
  im: Float32Array;
}

interface FftPlan {
  reversal: Uint32Array;
  /** Twiddles for every stage, concatenated; stage 1 starts at 0. */
  cos: Float32Array;
  sin: Float32Array;
  stageOffsets: Uint32Array;
}

const planCache = new Map<number, FftPlan>();

export function isPowerOfTwo(value: number): boolean {
  return Number.isInteger(value) && value > 0 && (value & (value - 1)) === 0;
}

function planFor(size: number): FftPlan {
  const cached = planCache.get(size);
  if (cached !== undefined) {
    return cached;
  }
  const bits = Math.round(Math.log2(size));
  const reversal = new Uint32Array(size);
  for (let index = 0; index < size; index += 1) {
    let reversed = 0;
    for (let bit = 0; bit < bits; bit += 1) {
      if ((index & (1 << bit)) !== 0) {
        reversed |= 1 << (bits - 1 - bit);
      }
    }
    reversal[index] = reversed;
  }
  const cos = new Float32Array(Math.max(1, size - 1));
  const sin = new Float32Array(Math.max(1, size - 1));
  const stages = bits;
  const stageOffsets = new Uint32Array(stages + 1);
  let cursor = 0;
  let stage = 0;
  for (let length = 2; length <= size; length <<= 1) {
    stageOffsets[stage] = cursor;
    const half = length >> 1;
    for (let offset = 0; offset < half; offset += 1) {
      const angle = (2 * Math.PI * offset) / length;
      cos[cursor + offset] = Math.cos(angle);
      sin[cursor + offset] = Math.sin(angle);
    }
    cursor += half;
    stage += 1;
  }
  stageOffsets[stages] = cursor;
  const created = { reversal, cos, sin, stageOffsets };
  planCache.set(size, created);
  return created;
}

/**
 * In-place forward FFT. `re` and `im` must have the same power-of-two length.
 */
export function fftInPlace(re: Float32Array, im: Float32Array): void {
  const size = re.length;
  if (im.length !== size) {
    throw new RangeError(
      `FFT real and imaginary lengths differ: ${size} vs ${im.length}`,
    );
  }
  if (!isPowerOfTwo(size)) {
    throw new RangeError(`FFT size must be a power of two, got ${size}`);
  }
  if (size === 1) {
    return;
  }

  const { reversal, cos, sin, stageOffsets } = planFor(size);

  // Bit-reversal permutation from the precomputed table.
  for (let index = 1; index < size; index += 1) {
    const reversed = reversal[index];
    if (index < reversed) {
      const real = re[index];
      re[index] = re[reversed];
      re[reversed] = real;
      const imaginary = im[index];
      im[index] = im[reversed];
      im[reversed] = imaginary;
    }
  }

  let stage = 0;
  for (let length = 2; length <= size; length <<= 1) {
    const half = length >> 1;
    const base = stageOffsets[stage];
    for (let start = 0; start < size; start += length) {
      for (let offset = 0; offset < half; offset += 1) {
        const wr = cos[base + offset];
        const wi = sin[base + offset];
        const even = start + offset;
        const odd = even + half;
        const oddRe = re[odd] * wr + im[odd] * wi;
        const oddIm = im[odd] * wr - re[odd] * wi;
        re[odd] = re[even] - oddRe;
        im[odd] = im[even] - oddIm;
        re[even] += oddRe;
        im[even] += oddIm;
      }
    }
    stage += 1;
  }
}

interface Untangle {
  cos: Float32Array;
  sin: Float32Array;
}

const untangleCache = new Map<number, Untangle>();

function untangle(size: number): Untangle {
  const cached = untangleCache.get(size);
  if (cached !== undefined) {
    return cached;
  }
  const half = size >> 1;
  const cos = new Float32Array(half);
  const sin = new Float32Array(half);
  for (let index = 0; index < half; index += 1) {
    const angle = (2 * Math.PI * index) / size;
    cos[index] = Math.cos(angle);
    sin[index] = Math.sin(angle);
  }
  const created = { cos, sin };
  untangleCache.set(size, created);
  return created;
}

/**
 * Real-input FFT of `samples` into the caller's `re`/`im` arrays (length
 * `samples.length / 2 + 1`). `scratch` holds two complex arrays of length
 * `samples.length / 2` and is reused between columns.
 */
/**
 * Transforms samples that are already packed into `scratch` as
 * `x[2i] + i x[2i+1]` and writes the real spectrum bins.
 */
export function realFftPackedInto(
  scratch: RealFftScratch,
  re: Float32Array,
  im: Float32Array,
): void {
  const half = scratch.re.length;
  const size = half * 2;
  if (re.length !== half + 1 || im.length !== half + 1) {
    throw new RangeError(
      `real FFT output must have ${half + 1} bins, got ${re.length}/${im.length}`,
    );
  }

  const zr = scratch.re;
  const zi = scratch.im;
  fftInPlace(zr, zi);

  re[0] = zr[0] + zi[0];
  im[0] = 0;
  re[half] = zr[0] - zi[0];
  im[half] = 0;

  const { cos, sin } = untangle(size);
  for (let bin = 1; bin < half; bin += 1) {
    const mirror = half - bin;
    const ar = zr[bin];
    const ai = zi[bin];
    const br = zr[mirror];
    const bi = -zi[mirror];
    const evenRe = (ar + br) * 0.5;
    const evenIm = (ai + bi) * 0.5;
    const diffRe = ar - br;
    const diffIm = ai - bi;
    const productRe = diffRe * cos[bin] + diffIm * sin[bin];
    const productIm = diffIm * cos[bin] - diffRe * sin[bin];
    re[bin] = evenRe + 0.5 * productIm;
    im[bin] = evenIm - 0.5 * productRe;
  }
}

export function realFftInto(
  samples: Float32Array,
  re: Float32Array,
  im: Float32Array,
  scratch: RealFftScratch,
): void {
  const size = samples.length;
  if (!isPowerOfTwo(size) || size < 2) {
    throw new RangeError(
      `real FFT size must be a power of two of at least 2, got ${size}`,
    );
  }
  const half = size >> 1;
  if (scratch.re.length !== half || scratch.im.length !== half) {
    throw new RangeError(
      `real FFT scratch must have ${half} complex samples, got ${scratch.re.length}/${scratch.im.length}`,
    );
  }
  for (let index = 0; index < half; index += 1) {
    scratch.re[index] = samples[index * 2];
    scratch.im[index] = samples[index * 2 + 1];
  }
  realFftPackedInto(scratch, re, im);
}

export function createRealFftScratch(size: number): RealFftScratch {
  if (!isPowerOfTwo(size) || size < 2) {
    throw new RangeError(
      `real FFT size must be a power of two of at least 2, got ${size}`,
    );
  }
  return {
    re: new Float32Array(size >> 1),
    im: new Float32Array(size >> 1),
  };
}

/** Convenience wrapper that allocates the output arrays. */
export function realFft(samples: Float32Array): RealSpectrum {
  const half = samples.length >> 1;
  const re = new Float32Array(half + 1);
  const im = new Float32Array(half + 1);
  realFftInto(samples, re, im, createRealFftScratch(samples.length));
  return { re, im };
}
