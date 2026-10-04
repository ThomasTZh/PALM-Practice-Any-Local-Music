/**
 * Peak-level and tile selection (M1.10, spec §12.5).
 *
 * The waveform pyramid (M1.8) stores per-channel min/max buckets:
 * level 0 covers `baseBucketFrames` (64) frames per bucket, each
 * higher level aggregates `aggregation` (4) buckets of the level
 * below, and buckets are grouped into tiles of `tileBuckets` (4096).
 *
 * Resolution selection picks the coarsest level that still yields at
 * most two buckets per CSS pixel (≈ one-to-two buckets per pixel,
 * spec §12.5.1), then the visible tiles plus one adjacent tile in each
 * direction (§12.5.2). Below 64 frames per CSS pixel the editor switches
 * to raw PCM (§12.5.5) — see `PCM_MIN_FPP`.
 */

import type { components } from '../api/schema'
import type { Viewport } from './viewport'
import { xToFrame } from './viewport'

export const TILE_BUCKETS = 4096

/** Below this zoom the peak pyramid is too coarse; use PCM (§12.5.5). */
export const PCM_MIN_FPP = 64

/** Below this zoom individual frames are visible; draw samples (§12.5.7). */
export const SAMPLE_LEVEL_FPP = 1

/**
 * Canonical waveform types, sourced from the generated OpenAPI contract
 * so the pure core never drifts from the backend manifest shape.
 */
export type WaveformLevel = components['schemas']['WaveformLevelSummary']
export type WaveformManifest = components['schemas']['WaveformManifest']

/** Inclusive bucket range of the viewport at the given level. */
export function visibleBucketRange(level: WaveformLevel, viewport: Viewport): [number, number] {
  const first = Math.max(0, Math.floor(viewport.startFrame / level.bucket_frame_count))
  const lastFrame = xToFrame(viewport, viewport.widthCssPx)
  const last = Math.min(level.bucket_count - 1, Math.floor(lastFrame / level.bucket_frame_count))
  return [first, last]
}

/**
 * Visible tile range at the level, clamped to the level's tile count.
 */
export function visibleTileRange(level: WaveformLevel, viewport: Viewport): [number, number] {
  const [firstBucket, lastBucket] = visibleBucketRange(level, viewport)
  return [
    Math.floor(firstBucket / TILE_BUCKETS),
    Math.min(level.tile_count - 1, Math.floor(lastBucket / TILE_BUCKETS)),
  ]
}

/**
 * Tiles to fetch: the visible range plus one adjacent tile in each
 * direction (spec §12.5.2), clamped to the level's tile count.
 */
export function adjacentTileRange(level: WaveformLevel, viewport: Viewport): [number, number] {
  const [first, last] = visibleTileRange(level, viewport)
  return [Math.max(0, first - 1), Math.min(level.tile_count - 1, last + 1)]
}

/**
 * Choose the peak level for a zoom (spec §12.5.1): the smallest level
 * whose bucket covers at least half a CSS pixel, i.e. at most two
 * buckets per CSS pixel. Level 0 for fpp <= 2 × base bucket frames.
 */
export function chooseLevel(manifest: WaveformManifest, framesPerCssPixel: number): number {
  if (!(framesPerCssPixel > 0)) throw new RangeError('framesPerCssPixel must be > 0')
  for (let level = 0; level < manifest.levels.length; level++) {
    if (manifest.levels[level].bucket_frame_count * 2 >= framesPerCssPixel) {
      return level
    }
  }
  return manifest.levels.length - 1
}

/**
 * True when the zoom is fine enough that the peak pyramid is too
 * coarse and raw PCM must be used (spec §12.5.5).
 */
export function usePcm(framesPerCssPixel: number): boolean {
  return framesPerCssPixel < PCM_MIN_FPP
}

/**
 * True when individual frames occupy less than a CSS pixel and should
 * be drawn as sample points/lines (spec §12.5.7).
 */
export function useSampleLevel(framesPerCssPixel: number): boolean {
  return framesPerCssPixel < SAMPLE_LEVEL_FPP
}

/**
 * Inclusive source-frame range to fetch as PCM for the viewport
 * (spec §12.5.6). The caller bounds this to the 8 MiB response cap.
 */
export function pcmFrameRange(viewport: Viewport, durationFrames: number): [number, number] {
  const first = Math.max(0, Math.floor(viewport.startFrame))
  const last = Math.min(durationFrames, Math.ceil(xToFrame(viewport, viewport.widthCssPx)))
  return [first, Math.max(first, last)]
}
