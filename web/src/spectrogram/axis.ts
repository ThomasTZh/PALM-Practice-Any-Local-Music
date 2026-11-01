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

/** Equal-tempered note helpers for the vertical axis. */
export const NOTE_NAMES = [
  "C",
  "C#",
  "D",
  "D#",
  "E",
  "F",
  "F#",
  "G",
  "G#",
  "A",
  "A#",
  "B",
] as const;

/** Lowest/highest MIDI notes in the default musical range (C1..C8). */
export const DEFAULT_LOWEST_MIDI = 24;
export const DEFAULT_HIGHEST_MIDI = 108;
/** Roughly ten CSS pixels per semitone keeps every label readable. */
export const NOTE_LABEL_PX = 10;

export function midiToFrequency(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

export function frequencyToMidi(hz: number): number {
  if (!(hz > 0) || !Number.isFinite(hz)) {
    return Number.NaN;
  }
  return 69 + 12 * Math.log2(hz / 440);
}

export function nearestMidi(hz: number): number {
  return Math.round(frequencyToMidi(hz));
}

export function midiNoteName(midi: number): string {
  const rounded = Math.round(midi);
  const name = NOTE_NAMES[((rounded % 12) + 12) % 12];
  const octave = Math.floor(rounded / 12) - 1;
  return `${name}${octave}`;
}

export interface NoteLabel extends FrequencyLabel {
  midi: number;
}

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

/** Every semitone inside the axis, highest note first. */
export function noteLabels(axis: FrequencyAxis): NoteLabel[] {
  const lowest = Math.max(
    DEFAULT_LOWEST_MIDI,
    Math.ceil(frequencyToMidi(axis.minHz) - 1e-9),
  );
  const highest = Math.min(
    DEFAULT_HIGHEST_MIDI,
    Math.floor(frequencyToMidi(axis.maxHz) + 1e-9),
  );
  const labels: NoteLabel[] = [];
  for (let midi = lowest; midi <= highest; midi += 1) {
    const hz = midiToFrequency(midi);
    if (hz < axis.minHz - 1e-9 || hz > axis.maxHz + 1e-9) {
      continue;
    }
    labels.push({
      midi,
      hz,
      label: midiNoteName(midi),
      percentFromTop: (rowAtFrequency(axis, hz) / (axis.rows - 1)) * 100,
    });
  }
  return labels.reverse();
}

/** Default pane height: ~10 px for each semitone label, never below 148. */
export function noteAxisHeight(labels: readonly NoteLabel[]): number {
  return Math.max(148, labels.length * NOTE_LABEL_PX);
}
