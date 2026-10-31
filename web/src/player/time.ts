/**
 * Time and frame arithmetic for the playback transport (t2).
 *
 * One place for the two conversions the transport performs:
 * - output time to stream frames (`extrapolateStreamFrame`), using the
 *   worklet's exact `(frame, contextTime, rate)` anchor and the audio
 *   clock;
 * - stream frames to project frames (`mapStreamToLoop`), because a loop
 *   stream is unbounded and repeats the loop range.
 *
 * The functions are pure so the mapping is testable without an audio
 * graph, and the transport never mixes the two coordinate systems.
 */

import { wrapIndex } from "./pcm";

export interface LoopFrames {
  startFrame: number;
  endFrame: number;
}

export interface PositionAnchor {
  /** Stream frame at the anchor. */
  frame: number;
  /** Audio-context time of the anchor, in seconds. */
  time: number;
  /** Playback rate at the anchor. */
  rate: number;
  /** A paused anchor does not advance with the clock. */
  paused: boolean;
}

export function framesToSeconds(frames: number, sampleRate: number): number {
  return sampleRate > 0 ? frames / sampleRate : 0;
}

export function secondsToFrames(seconds: number, sampleRate: number): number {
  return sampleRate > 0 ? seconds * sampleRate : 0;
}

/** Clamp a frame into `[0, durationFrames]`. */
export function clampFrame(frame: number, durationFrames: number): number {
  if (!Number.isFinite(frame)) return 0;
  return Math.max(0, Math.min(Math.floor(frame), Math.max(0, durationFrames)));
}

/**
 * Project frame carried by a stream coordinate. Without a loop the two
 * coordinate systems are identical; with a loop the stream repeats
 * `[startFrame, endFrame)`.
 */
export function mapStreamToLoop(
  streamFrame: number,
  loop: LoopFrames | null,
): number {
  if (!loop) return streamFrame;
  const length = loop.endFrame - loop.startFrame;
  if (!(length > 0)) return streamFrame;
  return loop.startFrame + wrapIndex(streamFrame - loop.startFrame, length);
}

/** Stream position at `nowSeconds` for an anchor (paused anchors freeze). */
export function extrapolateStreamFrame(
  anchor: PositionAnchor,
  nowSeconds: number,
  sampleRate: number,
): number {
  if (anchor.paused) return anchor.frame;
  const elapsed = Math.max(0, nowSeconds - anchor.time);
  return anchor.frame + secondsToFrames(elapsed, sampleRate) * anchor.rate;
}

/** Project position at `nowSeconds`, clamped to the source duration. */
export function projectPositionAt(
  anchor: PositionAnchor,
  nowSeconds: number,
  sampleRate: number,
  loop: LoopFrames | null,
  durationFrames: number,
): number {
  const stream = extrapolateStreamFrame(anchor, nowSeconds, sampleRate);
  return clampFrame(mapStreamToLoop(stream, loop), durationFrames);
}
