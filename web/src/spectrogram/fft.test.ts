import { describe, expect, it } from "vitest";

import { fftInPlace, isPowerOfTwo, realFft } from "./fft";

interface Spectrum {
  re: Float64Array;
  im: Float64Array;
}

/** Naive reference DFT: O(n^2), deliberately independent of the implementation. */
function referenceDft(re: ArrayLike<number>, im: ArrayLike<number>): Spectrum {
  const n = re.length;
  const outRe = new Float64Array(n);
  const outIm = new Float64Array(n);
  for (let k = 0; k < n; k += 1) {
    let sumRe = 0;
    let sumIm = 0;
    for (let j = 0; j < n; j += 1) {
      const angle = (-2 * Math.PI * j * k) / n;
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      sumRe += re[j] * cos - im[j] * sin;
      sumIm += re[j] * sin + im[j] * cos;
    }
    outRe[k] = sumRe;
    outIm[k] = sumIm;
  }
  return { re: outRe, im: outIm };
}

function makeComplex(n: number) {
  const re = new Float32Array(n);
  const im = new Float32Array(n);
  for (let index = 0; index < n; index += 1) {
    re[index] = Math.sin(index * 1.7) + 0.3 * Math.cos(index * 0.4);
    im[index] = 0.2 * Math.cos(index * 2.1) - 0.1 * Math.sin(index * 0.3);
  }
  return { re, im };
}

function expectClose(
  actual: ArrayLike<number>,
  expected: ArrayLike<number>,
): void {
  expect(actual.length).toBe(expected.length);
  for (let index = 0; index < expected.length; index += 1) {
    expect(actual[index]).toBeCloseTo(expected[index], 5);
  }
}

describe("fftInPlace", () => {
  it.each([2, 4, 8, 16, 32])("matches the reference DFT for n=%i", (n) => {
    const { re, im } = makeComplex(n);
    const expected = referenceDft(re, im);

    fftInPlace(re, im);

    expectClose(re, expected.re);
    expectClose(im, expected.im);
  });

  it("leaves a single sample unchanged", () => {
    const re = new Float32Array([0.5]);
    const im = new Float32Array([-0.25]);

    fftInPlace(re, im);

    expect(re[0]).toBeCloseTo(0.5);
    expect(im[0]).toBeCloseTo(-0.25);
  });

  it("rejects lengths that are not powers of two", () => {
    expect(() => fftInPlace(new Float32Array(3), new Float32Array(3))).toThrow(
      RangeError,
    );
    expect(() => fftInPlace(new Float32Array(6), new Float32Array(6))).toThrow(
      RangeError,
    );
  });

  it("rejects mismatched real and imaginary lengths", () => {
    expect(() => fftInPlace(new Float32Array(4), new Float32Array(8))).toThrow(
      RangeError,
    );
  });
});

describe("realFft", () => {
  it("matches the reference DFT of the real signal up to Nyquist", () => {
    const samples = new Float32Array([
      0.5, -0.25, 0.75, 0.1, -0.6, 0.2, 0, 0.9,
    ]);
    const expected = referenceDft(samples, new Float32Array(samples.length));

    const { re, im } = realFft(samples);

    expect(re.length).toBe(samples.length / 2 + 1);
    expectClose(re, expected.re.slice(0, samples.length / 2 + 1));
    expectClose(im, expected.im.slice(0, samples.length / 2 + 1));
  });

  it("returns the expected DC and Nyquist bins", () => {
    const samples = new Float32Array([1, 1, 1, 1]);

    const { re, im } = realFft(samples);

    expect(re[0]).toBeCloseTo(4);
    expect(im[0]).toBeCloseTo(0);
    expect(re[2]).toBeCloseTo(0);
    expect(im[2]).toBeCloseTo(0);
  });

  it("rejects invalid lengths", () => {
    expect(() => realFft(new Float32Array(0))).toThrow(RangeError);
    expect(() => realFft(new Float32Array(3))).toThrow(RangeError);
    expect(() => realFft(new Float32Array(6))).toThrow(RangeError);
  });
});

describe("isPowerOfTwo", () => {
  it("recognises powers of two and rejects the rest", () => {
    expect(isPowerOfTwo(1)).toBe(true);
    expect(isPowerOfTwo(2)).toBe(true);
    expect(isPowerOfTwo(2048)).toBe(true);
    expect(isPowerOfTwo(0)).toBe(false);
    expect(isPowerOfTwo(3)).toBe(false);
    expect(isPowerOfTwo(-4)).toBe(false);
    expect(isPowerOfTwo(2.5)).toBe(false);
  });
});
