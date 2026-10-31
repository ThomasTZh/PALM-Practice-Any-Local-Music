/**
 * Periodic Hann window. Periodic rather than symmetric because the STFT uses
 * it for overlap-add style analysis, and its coherent gain is exactly N/2.
 */
export function hannWindow(size: number): Float32Array {
  if (!Number.isInteger(size) || size <= 0) {
    throw new RangeError(
      `Hann window size must be a positive integer, got ${size}`,
    );
  }
  const window = new Float32Array(size);
  for (let index = 0; index < size; index += 1) {
    window[index] = 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / size);
  }
  return window;
}
