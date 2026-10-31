import type { Grid } from "../../state/types";

export type { Grid, Meter } from "../../state/types";

export interface ViewportLike {
  startSeconds: number;
  secondsPerPixel: number;
}

export interface SecondsTick {
  time: number;
  major: boolean;
  label: string | null;
}

export interface BarBeatTick {
  time: number;
  bar: number;
  beat: number;
  downbeat: boolean;
  label: string | null;
}

/**
 * Candidate tick steps, in seconds. The chooser walks this list so every tick
 * lands on a value a musician reads without arithmetic.
 */
export const SECONDS_STEPS = [
  0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600,
];

const MIN_MAJOR_TICK_PX = 80;
const MIN_MINOR_TICK_PX = 8;
const MIN_BAR_LABEL_PX = 48;
const EPSILON = 1e-9;
const MAX_TICKS = 2000;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Formats a tick using the precision its step needs. */
export function formatTickLabel(
  timeSeconds: number,
  stepSeconds: number,
): string {
  const subSecond = stepSeconds < 1;
  const rounded = subSecond
    ? Math.round(Math.max(0, timeSeconds) * 10) / 10
    : Math.round(Math.max(0, timeSeconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const seconds = Math.floor(rounded % 60);
  const tenths = subSecond
    ? Math.round((rounded - Math.floor(rounded)) * 10)
    : 0;
  const secondText = subSecond
    ? `${String(seconds).padStart(2, "0")}.${tenths}`
    : String(seconds).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${secondText}`;
  }
  return `${minutes}:${secondText}`;
}

/**
 * Chooses the visible second ticks for a viewport. Ticks always fall on
 * multiples of the step from zero, so scrolling reveals more ticks instead of
 * moving them under the cursor.
 */
export function chooseSecondsTicks(
  viewport: ViewportLike,
  widthPx: number,
): SecondsTick[] {
  const { startSeconds, secondsPerPixel } = viewport;
  if (!(secondsPerPixel > 0) || !(widthPx > 0)) {
    return [];
  }
  const majorStep =
    SECONDS_STEPS.find((step) => step / secondsPerPixel >= MIN_MAJOR_TICK_PX) ??
    SECONDS_STEPS[SECONDS_STEPS.length - 1];
  const minorCandidate = majorStep / 5;
  const step =
    minorCandidate / secondsPerPixel >= MIN_MINOR_TICK_PX
      ? minorCandidate
      : majorStep;
  const majorEvery = Math.max(1, Math.round(majorStep / step));
  const endSeconds = startSeconds + widthPx * secondsPerPixel;
  const firstIndex = Math.ceil((startSeconds - EPSILON) / step);
  const ticks: SecondsTick[] = [];

  for (let index = firstIndex; ticks.length < MAX_TICKS; index += 1) {
    const rawTime = index * step;
    const time = rawTime === 0 ? 0 : rawTime;
    if (time >= endSeconds - EPSILON) {
      break;
    }
    if (time < startSeconds - EPSILON) {
      continue;
    }
    const major = index % majorEvery === 0;
    ticks.push({
      time,
      major,
      label: major ? formatTickLabel(time, majorStep) : null,
    });
  }
  return ticks;
}

/** How many bars to skip between bar-number labels at the current density. */
export function chooseBarLabelEvery(barPixels: number): number {
  if (!(barPixels > 0)) {
    return 1;
  }
  return Math.max(1, Math.ceil(MIN_BAR_LABEL_PX / barPixels));
}

/**
 * Beat ticks derived from the detected grid. The tempo is read as beats per
 * minute of the meter's denominator unit, which is how the analysis reports it.
 */
export function barBeatTicks(
  grid: Grid,
  startSeconds: number,
  endSeconds: number,
  pixelsPerSecond: number,
): BarBeatTick[] {
  const { bpm, meter, offsetSeconds } = grid;
  if (!(bpm > 0) || !(meter.numerator > 0) || !(endSeconds > startSeconds)) {
    return [];
  }
  const beatSeconds = 60 / bpm;
  const barSeconds = beatSeconds * meter.numerator;
  const labelEvery = chooseBarLabelEvery(barSeconds * pixelsPerSecond);
  const firstIndex = Math.ceil(
    (startSeconds - offsetSeconds - EPSILON) / beatSeconds,
  );
  const ticks: BarBeatTick[] = [];

  for (let index = firstIndex; ticks.length < MAX_TICKS; index += 1) {
    const time = offsetSeconds + index * beatSeconds;
    if (time >= endSeconds - EPSILON) {
      break;
    }
    if (time < startSeconds - EPSILON) {
      continue;
    }
    const bar = Math.floor(index / meter.numerator) + 1;
    const beat =
      (((index % meter.numerator) + meter.numerator) % meter.numerator) + 1;
    const downbeat = beat === 1;
    const label = downbeat && (bar - 1) % labelEvery === 0 ? String(bar) : null;
    ticks.push({ time, bar, beat, downbeat, label });
  }
  return ticks;
}

export function clampToRange(value: number, min: number, max: number): number {
  return clamp(value, min, max);
}
