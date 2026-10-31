/**
 * Log-frequency vertical axis shared by the spectrogram image and its labels.
 * Row 0 is the top (highest frequency), the last row is the bottom (lowest).
 */

export interface FrequencyAxis {
  minHz: number;
  maxHz: number;
  rows: number;
}

export interface FrequencyLabel {
  hz: number;
  label: string;
  /** 0 at the top of the pane, 100 at the bottom. */
  percentFromTop: number;
}

const LABEL_FREQUENCIES = [
  20, 30, 50, 100, 200, 300, 500, 1000, 2000, 3000, 5000, 10000, 15000, 20000,
];

export function createFrequencyAxis(
  minHz: number,
  maxHz: number,
  rows: number,
): FrequencyAxis {
  if (!(minHz > 0) || !(maxHz > minHz)) {
    throw new RangeError(
      `frequency axis needs 0 < minHz < maxHz, got ${minHz}..${maxHz}`,
    );
  }
  if (!Number.isInteger(rows) || rows < 2) {
    throw new RangeError(`frequency axis needs at least two rows, got ${rows}`);
  }
  return { minHz, maxHz, rows };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Frequency at a row index, interpolated logarithmically. */
export function frequencyAtRow(axis: FrequencyAxis, row: number): number {
  const position = clamp(row, 0, axis.rows - 1) / (axis.rows - 1);
  return axis.maxHz * Math.pow(axis.minHz / axis.maxHz, position);
}

/** Fractional row for a frequency, clamped to the axis. */
export function rowAtFrequency(axis: FrequencyAxis, hz: number): number {
  const frequency = clamp(hz, axis.minHz, axis.maxHz);
  const position =
    Math.log(frequency / axis.maxHz) / Math.log(axis.minHz / axis.maxHz);
  return position * (axis.rows - 1);
}

export function formatFrequency(hz: number): string {
  if (hz >= 1000) {
    const kilohertz = hz / 1000;
    const text = Number.isInteger(kilohertz)
      ? String(kilohertz)
      : kilohertz.toFixed(1).replace(/\.0$/, "");
    return `${text} kHz`;
  }
  return `${Math.round(hz)} Hz`;
}

/** Canonical labels that fall inside the axis, highest frequency first. */
export function frequencyLabels(axis: FrequencyAxis): FrequencyLabel[] {
  const labels: FrequencyLabel[] = [];
  for (const hz of LABEL_FREQUENCIES) {
    if (hz < axis.minHz || hz > axis.maxHz) {
      continue;
    }
    labels.push({
      hz,
      label: formatFrequency(hz),
      percentFromTop: (rowAtFrequency(axis, hz) / (axis.rows - 1)) * 100,
    });
  }
  return labels.reverse();
}
