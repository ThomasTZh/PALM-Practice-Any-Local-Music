/**
 * The transport seam between the UI and whatever engine plays audio.
 *
 * The UI only ever talks to this interface. `state/localPlayer.ts` is a silent
 * fallback for the shell, and the WASM/PCM engine implements the same shape
 * when it lands. Keeping the names here means the panels do not depend on the
 * engine's internals.
 */

export type PlaybackStatus =
  "idle" | "loading" | "ready" | "playing" | "paused" | "ended" | "error";

export interface LoopRange {
  startSeconds: number;
  endSeconds: number;
}

/** Live musical grid fed into a running transport after analysis completes. */
export interface PlayerGrid {
  bpm?: number | null;
  bpb?: number | null;
  beatsSeconds?: readonly number[] | null;
  offsetSeconds?: number | null;
}

export interface PlayerState {
  status: PlaybackStatus;
  positionSeconds: number;
  durationSeconds: number;
  speed: number;
  pitchSemitones: number;
  loopEnabled: boolean;
  loopRange: LoopRange | null;
  error: string | null;
}

export interface StudioPlayer {
  getState(): PlayerState;
  subscribe(listener: (state: PlayerState) => void): () => void;
  play(): void;
  pause(): void;
  toggle(): void;
  seek(seconds: number): void;
  setSpeed(speed: number): void;
  setPitchSemitones(semitones: number): void;
  setLoopEnabled(enabled: boolean): void;
  setLoopRange(range: LoopRange | null): void;
  setDuration(seconds: number): void;
  /** Optional live grid update; engines that support it apply it without reloading. */
  updateGrid?(grid: PlayerGrid): void;
  dispose(): void;
}

/** YouTube-style practice speeds. */
export const SPEED_OPTIONS = [0.5, 0.625, 0.75, 0.875, 1, 1.25, 1.5] as const;

export const MIN_SPEED = 0.25;
export const MAX_SPEED = 2;
export const MIN_PITCH_SEMITONES = -12;
export const MAX_PITCH_SEMITONES = 12;
export const MIN_LOOP_SECONDS = 0.05;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clampSpeed(speed: number): number {
  return Number.isFinite(speed) ? clamp(speed, MIN_SPEED, MAX_SPEED) : 1;
}

export function clampPitchSemitones(semitones: number): number {
  return Number.isFinite(semitones)
    ? clamp(semitones, MIN_PITCH_SEMITONES, MAX_PITCH_SEMITONES)
    : 0;
}

export function normalizeLoopRange(
  range: LoopRange | null,
  durationSeconds: number,
): LoopRange | null {
  if (range === null) {
    return null;
  }
  const duration = Number.isFinite(durationSeconds)
    ? Math.max(0, durationSeconds)
    : 0;
  const start = clamp(
    Math.min(range.startSeconds, range.endSeconds),
    0,
    duration,
  );
  const end = clamp(
    Math.max(range.startSeconds, range.endSeconds),
    0,
    duration,
  );
  if (end - start < MIN_LOOP_SECONDS) {
    return null;
  }
  return { startSeconds: start, endSeconds: end };
}

/**
 * Clamps a loop into a (possibly shorter) track without silently discarding it:
 * a range that collapses at the end keeps the shortest legal loop at the tail.
 */
export function clampLoopRangeToDuration(
  range: LoopRange | null,
  durationSeconds: number,
): LoopRange | null {
  if (range === null) {
    return null;
  }
  const duration = Number.isFinite(durationSeconds)
    ? Math.max(0, durationSeconds)
    : 0;
  if (!(duration > 0)) {
    return null;
  }
  const start = clamp(
    Math.min(range.startSeconds, range.endSeconds),
    0,
    duration,
  );
  const end = clamp(
    Math.max(range.startSeconds, range.endSeconds),
    0,
    duration,
  );
  if (end - start >= MIN_LOOP_SECONDS) {
    return { startSeconds: start, endSeconds: end };
  }
  const span = Math.min(MIN_LOOP_SECONDS, duration);
  return {
    startSeconds: Math.max(0, duration - span),
    endSeconds: duration,
  };
}

export function initialPlayerState(
  overrides: Partial<PlayerState> = {},
): PlayerState {
  const durationSeconds = Math.max(0, overrides.durationSeconds ?? 0);
  return {
    status: durationSeconds > 0 ? "paused" : "idle",
    positionSeconds: 0,
    durationSeconds,
    speed: 1,
    pitchSemitones: 0,
    loopEnabled: false,
    loopRange: null,
    error: null,
    ...overrides,
  };
}
