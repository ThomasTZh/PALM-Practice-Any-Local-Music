/**
 * Musical grid helpers for playback (t9).
 *
 * The analysis job persists `project.document.grid` (bpm + bpb + beats) and
 * the UI passes section ranges in seconds. The transport works in project
 * frames, so this module owns the two conversions:
 *
 * - beat times -> metronome beat specs in frames, with the bar accent on
 *   every `bpb`-th beat;
 * - section/loop seconds -> clamped frame ranges.
 *
 * Analysis-free projects fall back to 120 BPM in 4/4, synthesising an even
 * beat grid from the offset; the metronome then still lines up with the
 * ruler instead of being silently unavailable.
 */

import { clampFrame } from "./time";
import type { BeatSpec, TransportLoop } from "./transport";

export const FALLBACK_BPM = 120;
export const FALLBACK_BPB = 4;

export interface PlaybackGrid {
  bpm: number;
  bpb: number;
  /** Beat times in project seconds, sorted ascending. May be empty. */
  beatsSeconds: readonly number[];
  /** Grid origin in seconds (normalized to 0 when absent). */
  offsetSeconds: number;
}

export interface PlaybackGridInput {
  bpm?: number | null;
  bpb?: number | null;
  beatsSeconds?: readonly number[] | null;
  offsetSeconds?: number | null;
}

/** Normalise partial grid data; invalid values fall back to 120 BPM / 4/4. */
export function normalizeGrid(
  input: PlaybackGridInput | null | undefined,
): PlaybackGrid {
  const bpm =
    input && Number.isFinite(input.bpm) && (input.bpm as number) > 0
      ? (input.bpm as number)
      : FALLBACK_BPM;
  const bpb =
    input && Number.isFinite(input.bpb) && (input.bpb as number) >= 1
      ? Math.round(input.bpb as number)
      : FALLBACK_BPB;
  const offsetSeconds =
    input && Number.isFinite(input.offsetSeconds)
      ? Math.max(0, input.offsetSeconds as number)
      : 0;
  const beatsSeconds = (input?.beatsSeconds ?? [])
    .filter((seconds) => Number.isFinite(seconds) && seconds >= 0)
    .slice()
    .sort((a, b) => a - b);
  return { bpm, bpb, beatsSeconds, offsetSeconds };
}

/**
 * Beat times covering `durationSeconds`. Detected beats win; without them an
 * even grid is synthesised from `bpm` and `offsetSeconds`.
 */
export function gridBeatTimes(
  grid: PlaybackGrid,
  durationSeconds: number,
): number[] {
  if (grid.beatsSeconds.length > 0) {
    return grid.beatsSeconds.map((seconds) =>
      Math.min(seconds, durationSeconds),
    );
  }
  const beatSeconds = 60 / grid.bpm;
  const times: number[] = [];
  for (
    let time = grid.offsetSeconds;
    time <= durationSeconds + 1e-9;
    time += beatSeconds
  ) {
    times.push(Number(time.toFixed(9)));
  }
  return times;
}

/** Metronome beat specs in project frames, accenting every bar start. */
export function gridBeatSpecs(
  grid: PlaybackGrid,
  sampleRate: number,
  durationSeconds: number,
  accentDownbeat = true,
): BeatSpec[] {
  return gridBeatTimes(grid, durationSeconds).map((seconds, index) => ({
    frame: Math.round(seconds * sampleRate),
    strength: accentDownbeat && index % grid.bpb === 0 ? "downbeat" : "beat",
  }));
}

/**
 * Section range in seconds -> loop frames. The end is clamped to the source
 * duration and the range must stay positive; otherwise no loop is installed.
 */
export function loopFromSeconds(
  startSeconds: number,
  endSeconds: number,
  sampleRate: number,
  durationFrames: number,
): TransportLoop | null {
  if (!(sampleRate > 0) || !(durationFrames > 0)) return null;
  const startFrame = clampFrame(startSeconds * sampleRate, durationFrames);
  const endFrame = clampFrame(endSeconds * sampleRate, durationFrames);
  if (!(endFrame > startFrame)) return null;
  return {
    startFrame,
    endFrame,
    repeatCount: null,
    // Keep the 5 ms join fade: a bar-snapped section still joins smoothly.
    fade: true,
  };
}
