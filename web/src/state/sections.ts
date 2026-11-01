import type { Viewport } from "../panels/waveform/viewport";
import type { Grid } from "./types";

/** Detected or synthesised beat times plus the beats-per-bar count. */
export interface BeatGrid {
  beats: number[];
  bpb: number;
}

export type SnapMode = "bar" | "beat" | "free";

export interface Section {
  id: string;
  name: string;
  startSeconds: number;
  endSeconds: number;
}

export interface TimeRange {
  startSeconds: number;
  endSeconds: number;
}

export interface BeatMark {
  timeSeconds: number;
  bar: number;
  beat: number;
  downbeat: boolean;
}

export interface BarMark {
  timeSeconds: number;
  bar: number;
}

export const MIN_SECTION_SECONDS = 0.05;
const EPSILON = 1e-9;

function cleanBeats(beats: number[]): number[] {
  return beats
    .filter((beat) => Number.isFinite(beat) && beat >= 0)
    .slice()
    .sort((a, b) => a - b);
}

function validGrid(grid: BeatGrid | null): grid is BeatGrid {
  return grid !== null && Number.isInteger(grid.bpb) && grid.bpb >= 1;
}

/** Bar/beat marks derived from the detected beat list. */
export function beatMarks(beats: number[], bpb: number): BeatMark[] {
  if (!Number.isInteger(bpb) || bpb < 1) {
    return [];
  }
  return cleanBeats(beats).map((timeSeconds, index) => {
    const bar = Math.floor(index / bpb) + 1;
    const beat = (index % bpb) + 1;
    return { timeSeconds, bar, beat, downbeat: beat === 1 };
  });
}

export function barMarks(beats: number[], bpb: number): BarMark[] {
  return beatMarks(beats, bpb)
    .filter((mark) => mark.downbeat)
    .map((mark) => ({ timeSeconds: mark.timeSeconds, bar: mark.bar }));
}

function barBoundaries(grid: BeatGrid): number[] {
  const beats = cleanBeats(grid.beats);
  const boundaries: number[] = [];
  for (let index = 0; index < beats.length; index += grid.bpb) {
    boundaries.push(beats[index]);
  }
  // When the grid covers complete bars, the end of the last bar is a legal
  // boundary too; otherwise a section could never end at the track's end.
  if (beats.length >= 2 && beats.length % grid.bpb === 0) {
    const beatSeconds =
      (beats[beats.length - 1] - beats[0]) / (beats.length - 1);
    if (beatSeconds > 0) {
      boundaries.push(beats[beats.length - 1] + beatSeconds);
    }
  }
  return boundaries;
}

function nearest(value: number, candidates: number[]): number | null {
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const candidate of candidates) {
    const distance = Math.abs(candidate - value);
    if (distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
  }
  return best;
}

/** First bar (or beat) boundary strictly after `seconds`. */
export function nextBoundary(
  seconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
): number | null {
  if (!validGrid(grid) || mode === "free") {
    return null;
  }
  const candidates =
    mode === "bar" ? barBoundaries(grid) : cleanBeats(grid.beats);
  for (const candidate of candidates) {
    if (candidate > seconds + EPSILON) {
      return candidate;
    }
  }
  return null;
}

/**
 * Snaps a time to the nearest bar boundary (default), beat, or leaves it free.
 * Without a usable grid every mode behaves like free time.
 */
export function snapTime(
  seconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
): number {
  const value = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  if (mode === "free" || !validGrid(grid)) {
    return value;
  }
  const candidates =
    mode === "bar" ? barBoundaries(grid) : cleanBeats(grid.beats);
  return nearest(value, candidates) ?? value;
}

/**
 * Snaps both ends of a range. A collapsed bar/beat range grows to the next
 * boundary so adding a section never silently does nothing.
 */
export function snapRange(
  range: TimeRange,
  mode: SnapMode,
  grid: BeatGrid | null,
  durationSeconds = Infinity,
): TimeRange | null {
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : Infinity;
  const clamp = (value: number) => Math.min(duration, Math.max(0, value));
  const start = clamp(snapTime(range.startSeconds, mode, grid));
  let end = clamp(snapTime(range.endSeconds, mode, grid));
  if (end <= start + EPSILON) {
    const next =
      mode === "free"
        ? start + 1
        : (nextBoundary(start, mode, grid) ?? start + 1);
    end = clamp(next);
  }
  if (end <= start + EPSILON) {
    return null;
  }
  return { startSeconds: start, endSeconds: end };
}

function nextSectionId(sections: Section[]): string {
  const used = new Set(sections.map((section) => section.id));
  let index = 1;
  while (used.has(`section-${index}`)) {
    index += 1;
  }
  return `section-${index}`;
}

/** Adds a section whose boundaries follow the current snap mode. */
export function addSection(
  sections: Section[],
  range: TimeRange,
  mode: SnapMode,
  grid: BeatGrid | null,
  options: { name?: string; durationSeconds?: number } = {},
): Section[] {
  const snapped = snapRange(range, mode, grid, options.durationSeconds);
  if (snapped === null) {
    return sections;
  }
  const section: Section = {
    id: nextSectionId(sections),
    name: options.name?.trim() || `Section ${sections.length + 1}`,
    startSeconds: snapped.startSeconds,
    endSeconds: snapped.endSeconds,
  };
  return [...sections, section];
}

/** Splits a section at the snapped playhead position. */
export function splitSection(
  sections: Section[],
  sectionId: string,
  atSeconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
): Section[] {
  const index = sections.findIndex((section) => section.id === sectionId);
  if (index === -1) {
    return sections;
  }
  const section = sections[index];
  const at = snapTime(atSeconds, mode, grid);
  if (
    at <= section.startSeconds + MIN_SECTION_SECONDS ||
    at >= section.endSeconds - MIN_SECTION_SECONDS
  ) {
    return sections;
  }
  const left: Section = { ...section, endSeconds: at };
  const right: Section = {
    id: nextSectionId(sections),
    name: `${section.name} (2)`,
    startSeconds: at,
    endSeconds: section.endSeconds,
  };
  return [
    ...sections.slice(0, index),
    left,
    right,
    ...sections.slice(index + 1),
  ];
}

export function renameSection(
  sections: Section[],
  sectionId: string,
  name: string,
): Section[] {
  const clean = name.trim() || "Section";
  return sections.map((section) =>
    section.id === sectionId ? { ...section, name: clean } : section,
  );
}

/** Moves one edge of a section, snapped and kept above the minimum length. */
export function resizeSection(
  sections: Section[],
  sectionId: string,
  edge: "start" | "end",
  seconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
): Section[] {
  const section = sections.find((item) => item.id === sectionId);
  if (!section) {
    return sections;
  }
  const snapped = Math.max(0, snapTime(seconds, mode, grid));
  if (
    (edge === "start" && snapped >= section.endSeconds - MIN_SECTION_SECONDS) ||
    (edge === "end" && snapped <= section.startSeconds + MIN_SECTION_SECONDS)
  ) {
    return sections;
  }
  return sections.map((item) =>
    item.id === sectionId
      ? {
          ...item,
          startSeconds: edge === "start" ? snapped : item.startSeconds,
          endSeconds: edge === "end" ? snapped : item.endSeconds,
        }
      : item,
  );
}

/** Moves a whole section while keeping its length, snapped and clamped. */
export function moveSectionRange(
  section: Section,
  targetStartSeconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
  durationSeconds: number,
): TimeRange {
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : Infinity;
  const length = Math.max(0, section.endSeconds - section.startSeconds);
  const maxStart = Math.max(0, duration - length);
  const start = Math.min(
    maxStart,
    Math.max(0, snapTime(targetStartSeconds, mode, grid)),
  );
  return { startSeconds: start, endSeconds: start + length };
}

export interface PlayheadSectionDraft {
  range: TimeRange | null;
  reason: string | null;
}

/**
 * Add-section draft ending at the snapped playhead. It is four bars long and
 * clamped after the previous section's end; when that leaves no room it
 * returns a plain-language reason instead of a range.
 */
export function draftSectionEndingAt(
  positionSeconds: number,
  mode: SnapMode,
  grid: BeatGrid | null,
  durationSeconds: number,
  sections: Section[],
): PlayheadSectionDraft {
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : Infinity;
  const end = Math.min(
    duration,
    Math.max(0, snapTime(positionSeconds, mode, grid)),
  );
  const fourBars = defaultBarSeconds(grid) * DEFAULT_SECTION_BARS;
  const gridStart =
    validGrid(grid) && grid.beats.length > 0
      ? Math.max(0, cleanBeats(grid.beats)[0] ?? 0)
      : 0;
  if (end <= gridStart + EPSILON) {
    // The first bar can start a few milliseconds into the recording. With no
    // section yet, place the first four bars on that grid instead of making a
    // zero-length sliver from 0 to the first downbeat.
    if (sections.length === 0 && Number.isFinite(duration)) {
      const start = Math.min(gridStart, duration);
      const fallbackEnd = Math.min(duration, start + fourBars);
      if (fallbackEnd > start + EPSILON) {
        return {
          range: { startSeconds: start, endSeconds: fallbackEnd },
          reason: null,
        };
      }
    }
    return {
      range: null,
      reason: "No room: the playhead is at the start of the track.",
    };
  }
  const previous = [...sections]
    .filter((section) => section.startSeconds < end + EPSILON)
    .sort((left, right) => right.endSeconds - left.endSeconds)[0];
  const previousEnd = previous?.endSeconds ?? 0;
  const start = Math.max(gridStart, end - fourBars, previousEnd);
  if (start >= end - EPSILON) {
    const where =
      previous === undefined
        ? "the start of the track"
        : `${previous.name} ends at ${previous.endSeconds.toFixed(2)} s`;
    return {
      range: null,
      reason: `No room: ${where} and the playhead is at ${end.toFixed(2)} s.`,
    };
  }
  return { range: { startSeconds: start, endSeconds: end }, reason: null };
}

export function deleteSection(
  sections: Section[],
  sectionId: string,
): Section[] {
  return sections.filter((section) => section.id !== sectionId);
}

/** The section containing a time, end-exclusive. */
export function sectionAt(
  sections: Section[],
  seconds: number,
): Section | null {
  for (const section of sections) {
    if (seconds >= section.startSeconds && seconds < section.endSeconds) {
      return section;
    }
  }
  return null;
}

export function sectionLoopRange(section: Section): TimeRange {
  return {
    startSeconds: section.startSeconds,
    endSeconds: section.endSeconds,
  };
}

const DEFAULT_SECTION_BARS = 4;
const FALLBACK_BPM = 120;
const FALLBACK_BPB = 4;

/** One bar from the detected grid, or 4/4 at 120 BPM before analysis. */
function defaultBarSeconds(grid: BeatGrid | null): number {
  if (validGrid(grid) && grid.beats.length >= 2) {
    const beatSeconds =
      (grid.beats[grid.beats.length - 1] - grid.beats[0]) /
      (grid.beats.length - 1);
    if (beatSeconds > EPSILON) {
      return beatSeconds * grid.bpb;
    }
  }
  return (60 / FALLBACK_BPM) * FALLBACK_BPB;
}

/** Range the Add button should create: the selection, or four snapped bars. */
export function draftSectionRange(
  positionSeconds: number,
  selection: TimeRange | null,
  mode: SnapMode,
  grid: BeatGrid | null,
  durationSeconds: number,
): TimeRange | null {
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : Infinity;
  if (
    selection !== null &&
    selection.endSeconds - selection.startSeconds > EPSILON
  ) {
    return snapRange(selection, mode, grid, duration);
  }
  const start = Math.min(
    duration,
    Math.max(0, snapTime(positionSeconds, mode, grid)),
  );
  if (start >= duration - EPSILON) {
    return null;
  }
  const end = Math.min(
    duration,
    start + defaultBarSeconds(grid) * DEFAULT_SECTION_BARS,
  );
  if (end <= start + EPSILON) {
    return null;
  }
  return { startSeconds: start, endSeconds: end };
}

/** Builds a beat grid from the tempo when no Vamp analysis is available yet. */
export function uniformBeats(grid: Grid, durationSeconds: number): BeatGrid {
  const bpb = Math.max(1, Math.round(grid.meter.numerator));
  if (!(grid.bpm > 0) || !(durationSeconds > 0)) {
    return { beats: [], bpb };
  }
  const beatSeconds = 60 / grid.bpm;
  const beats: number[] = [];
  for (
    let time = Math.max(0, grid.offsetSeconds);
    time < durationSeconds - EPSILON;
    time += beatSeconds
  ) {
    beats.push(time);
  }
  return { beats, bpb };
}

export interface SectionBlock {
  section: Section;
  leftPx: number;
  widthPx: number;
}

function roundPixels(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Pixel layout of the sections visible in a viewport, clipped at the edges. */
export function sectionBlocks(
  sections: Section[],
  viewport: Viewport,
  widthPx: number,
): SectionBlock[] {
  const visibleStart = viewport.startSeconds;
  const visibleEnd = visibleStart + widthPx * viewport.secondsPerPixel;
  const blocks: SectionBlock[] = [];
  for (const section of sections) {
    const start = Math.max(section.startSeconds, visibleStart);
    const end = Math.min(section.endSeconds, visibleEnd);
    if (!(end > start)) {
      continue;
    }
    blocks.push({
      section,
      leftPx: roundPixels((start - visibleStart) / viewport.secondsPerPixel),
      widthPx: roundPixels((end - start) / viewport.secondsPerPixel),
    });
  }
  return blocks;
}
