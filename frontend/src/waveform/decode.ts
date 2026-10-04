/**
 * Pure binary parsing for peak tiles and PCM (M1.10, spec §11.5).
 *
 * Validates expected byte lengths, reads little-endian values
 * explicitly through `DataView`, and rejects truncated bodies. This is
 * the code the browser worker (`worker.ts`) runs off the React render
 * path (§11.5.5–7); the unit tests exercise it directly.
 *
 * Peak tile layout (M1.8): `(bucket, channel, [min, max])` float32
 * little-endian — `bucketCount * channelCount * 8` bytes.
 */

import { deinterleaveF32le } from '../playback/pcm'

export class DecodeError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DecodeError'
  }
}

export interface PeakTile {
  /** One array per channel; `minima[c][b]` is bucket `b`'s minimum. */
  minima: Float32Array[]
  maxima: Float32Array[]
}

export function parsePeakTile(
  bytes: ArrayBuffer,
  channelCount: number,
  bucketCount: number,
): PeakTile {
  if (channelCount < 1) throw new DecodeError('channelCount must be >= 1')
  if (bucketCount < 0) throw new DecodeError('bucketCount must be >= 0')
  const expected = bucketCount * channelCount * 8
  if (bytes.byteLength !== expected) {
    throw new DecodeError(
      bytes.byteLength < expected
        ? `truncated tile: got ${bytes.byteLength} of ${expected} bytes`
        : `tile length ${bytes.byteLength} != expected ${expected} bytes`,
    )
  }
  const view = new DataView(bytes)
  const minima: Float32Array[] = []
  const maxima: Float32Array[] = []
  for (let c = 0; c < channelCount; c++) {
    minima.push(new Float32Array(bucketCount))
    maxima.push(new Float32Array(bucketCount))
  }
  for (let b = 0; b < bucketCount; b++) {
    for (let c = 0; c < channelCount; c++) {
      const offset = (b * channelCount + c) * 8
      const min = view.getFloat32(offset, true)
      const max = view.getFloat32(offset + 4, true)
      if (!Number.isFinite(min) || !Number.isFinite(max)) {
        throw new DecodeError(`non-finite extrema in bucket ${b} channel ${c}`)
      }
      minima[c][b] = min
      maxima[c][b] = max
    }
  }
  return { minima, maxima }
}

export interface PcmPixels {
  /** Source frame of the first decoded frame. */
  startFrame: number
  /** Decoded frames (complete frames only). */
  frames: number
  /** CSS pixels covered, `ceil(frames / framesPerCssPixel)`. */
  pixels: number
  /** Per-channel per-pixel minimums. */
  minima: Float32Array[]
  maxima: Float32Array[]
}

/**
 * Aggregate interleaved f32le PCM into per-pixel min/max (spec
 * §12.5.6): several frames may occupy one CSS pixel. `bytes` must hold
 * at least one complete frame.
 */
export function aggregatePcmToPixels(
  bytes: ArrayBuffer,
  channelCount: number,
  startFrame: number,
  framesPerCssPixel: number,
): PcmPixels {
  if (channelCount < 1) throw new DecodeError('channelCount must be >= 1')
  if (!(framesPerCssPixel > 0)) throw new DecodeError('framesPerCssPixel must be > 0')
  const frameBytes = 4 * channelCount
  if (bytes.byteLength % frameBytes !== 0) {
    throw new DecodeError(`truncated pcm: ${bytes.byteLength} bytes is not whole frames`)
  }
  const frames = bytes.byteLength / frameBytes
  if (frames < 1) throw new DecodeError('aggregatePcmToPixels needs at least one frame')
  const pixels = Math.ceil(frames / framesPerCssPixel)
  const view = new DataView(bytes)
  const minima: Float32Array[] = []
  const maxima: Float32Array[] = []
  for (let c = 0; c < channelCount; c++) {
    minima.push(new Float32Array(pixels).fill(Number.POSITIVE_INFINITY))
    maxima.push(new Float32Array(pixels).fill(Number.NEGATIVE_INFINITY))
  }
  for (let f = 0; f < frames; f++) {
    const pixel = Math.min(pixels - 1, Math.floor(f / framesPerCssPixel))
    for (let c = 0; c < channelCount; c++) {
      const value = view.getFloat32((f * channelCount + c) * 4, true)
      if (value < minima[c][pixel]) minima[c][pixel] = value
      if (value > maxima[c][pixel]) maxima[c][pixel] = value
    }
  }
  return { startFrame, frames, pixels, minima, maxima }
}

/**
 * Deinterleave PCM into per-channel sample arrays for sample-level
 * drawing (spec §12.5.7). Rejects truncated bodies.
 */
export function pcmSamples(bytes: ArrayBuffer, channelCount: number): Float32Array[] {
  if (channelCount < 1) throw new DecodeError('channelCount must be >= 1')
  if (bytes.byteLength % (4 * channelCount) !== 0) {
    throw new DecodeError(`truncated pcm: ${bytes.byteLength} bytes is not whole frames`)
  }
  return deinterleaveF32le(bytes, channelCount)
}
