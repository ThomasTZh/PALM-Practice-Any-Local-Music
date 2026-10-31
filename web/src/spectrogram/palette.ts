/**
 * dB colour palette for the spectrogram. Dark blue for silence rising through
 * violet and orange to a warm near-white for the loudest bins.
 */

export type Rgba = [number, number, number, number];

const STOPS: Array<[number, number, number, number]> = [
  [0, 8, 12, 36],
  [0.25, 24, 28, 92],
  [0.5, 88, 20, 110],
  [0.65, 150, 40, 80],
  [0.8, 220, 90, 30],
  [1, 255, 240, 190],
];

function clampLevel(level: number): number {
  if (!Number.isFinite(level)) {
    return 0;
  }
  return Math.min(1, Math.max(0, level));
}

/** Colour for a normalized level, with clamped inputs. */
export function colorForLevel(level: number): Rgba {
  const value = clampLevel(level);
  for (let index = 1; index < STOPS.length; index += 1) {
    const [endPosition, endR, endG, endB] = STOPS[index];
    if (value <= endPosition) {
      const [startPosition, startR, startG, startB] = STOPS[index - 1];
      const span = endPosition - startPosition;
      const mix = span === 0 ? 0 : (value - startPosition) / span;
      return [
        Math.round(startR + (endR - startR) * mix),
        Math.round(startG + (endG - startG) * mix),
        Math.round(startB + (endB - startB) * mix),
        255,
      ];
    }
  }
  return [255, 240, 190, 255];
}

/** RGBA lookup table so per-pixel colouring is an index, not a lerp. */
export function paletteTable(size = 256): Uint8ClampedArray {
  if (!Number.isInteger(size) || size < 1) {
    throw new RangeError(
      `palette size must be a positive integer, got ${size}`,
    );
  }
  const table = new Uint8ClampedArray(size * 4);
  for (let index = 0; index < size; index += 1) {
    const [r, g, b, a] = colorForLevel(size === 1 ? 0 : index / (size - 1));
    const offset = index * 4;
    table[offset] = r;
    table[offset + 1] = g;
    table[offset + 2] = b;
    table[offset + 3] = a;
  }
  return table;
}
