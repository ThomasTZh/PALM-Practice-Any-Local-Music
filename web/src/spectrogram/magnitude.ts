/** Amplitude to decibels, with silence mapped to negative infinity. */
export function amplitudeToDb(amplitude: number, reference = 1): number {
  if (amplitude === 0) {
    return -Infinity;
  }
  return 20 * Math.log10(amplitude / reference);
}

/** Clamps a dB value into the display floor/ceiling. */
export function clampDb(
  value: number,
  floorDb: number,
  ceilingDb: number,
): number {
  if (floorDb > ceilingDb) {
    throw new RangeError(
      `dB floor ${floorDb} is above the ceiling ${ceilingDb}`,
    );
  }
  if (Number.isNaN(value)) {
    return floorDb;
  }
  if (value === -Infinity) {
    return floorDb;
  }
  if (value === Infinity) {
    return ceilingDb;
  }
  return Math.min(ceilingDb, Math.max(floorDb, value));
}

/** Maps a dB value onto 0..1 for the colour palette. */
export function normalizeDb(
  value: number,
  floorDb: number,
  ceilingDb: number,
): number {
  if (ceilingDb <= floorDb) {
    return 0;
  }
  return (clampDb(value, floorDb, ceilingDb) - floorDb) / (ceilingDb - floorDb);
}
