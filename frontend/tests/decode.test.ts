import { describe, expect, it } from 'vitest'
import {
  aggregatePcmToPixels,
  DecodeError,
  parsePeakTile,
  pcmSamples,
} from '../src/waveform/decode'

/** Little-endian float32 bytes for `values`, packed into one buffer. */
function f32leBuffer(values: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(values.length * 4)
  new Float32Array(buffer).set(values)
  return buffer
}

/**
 * Tile bytes in the M1.8 layout `(bucket, channel, [min, max])`:
 * `extrema[bucket][channel] = [min, max]`.
 */
function tileBuffer(extrema: number[][][]): ArrayBuffer {
  const values: number[] = []
  for (const bucket of extrema) {
    for (const [min, max] of bucket) {
      values.push(min, max)
    }
  }
  return f32leBuffer(values)
}

describe('parsePeakTile', () => {
  it('parses known bytes into per-channel min/max', () => {
    // 2 buckets x 2 channels:
    //   b0: ch0 [-0.5, 0.25], ch1 [-0.75, 0.5]
    //   b1: ch0 [0.1, 0.9],   ch1 [-0.2, 0.3]
    const tile = parsePeakTile(
      tileBuffer([
        [
          [-0.5, 0.25],
          [-0.75, 0.5],
        ],
        [
          [0.1, 0.9],
          [-0.2, 0.3],
        ],
      ]),
      2,
      2,
    )
    expect(tile.minima).toHaveLength(2)
    expect(tile.maxima).toHaveLength(2)
    expect(tile.minima[0]).toEqual(new Float32Array([-0.5, 0.1]))
    expect(tile.maxima[0]).toEqual(new Float32Array([0.25, 0.9]))
    expect(tile.minima[1]).toEqual(new Float32Array([-0.75, -0.2]))
    expect(tile.maxima[1]).toEqual(new Float32Array([0.5, 0.3]))
  })

  it('reads little-endian explicitly (big-endian bytes would misparse)', () => {
    // 0.5f32 is 0x3F000000; LE bytes are 00 00 00 3F. A BE reader of
    // those bytes yields ~1e-40, not 0.5.
    const bytes = new Uint8Array([0x00, 0x00, 0x00, 0x3f, 0x00, 0x00, 0x00, 0x3f])
    const buffer = bytes.buffer as ArrayBuffer
    const tile = parsePeakTile(buffer, 1, 1)
    expect(tile.minima[0][0]).toBeCloseTo(0.5)
    expect(tile.maxima[0][0]).toBeCloseTo(0.5)
  })

  it('handles mono', () => {
    const tile = parsePeakTile(tileBuffer([[[-1, 1]]]), 1, 1)
    expect(tile.minima[0]).toEqual(new Float32Array([-1]))
    expect(tile.maxima[0]).toEqual(new Float32Array([1]))
  })

  it('rejects a truncated body', () => {
    const full = tileBuffer([
      [
        [-0.5, 0.25],
        [-0.75, 0.5],
      ],
      [
        [0.1, 0.9],
        [-0.2, 0.3],
      ],
    ])
    const truncated = full.slice(0, full.byteLength - 4)
    expect(() => parsePeakTile(truncated, 2, 2)).toThrow(DecodeError)
    expect(() => parsePeakTile(truncated, 2, 2)).toThrow(/truncated/)
  })

  it('rejects an over-long body', () => {
    const full = tileBuffer([[[-0.5, 0.25]]])
    const tooLong = f32leBuffer([-0.5, 0.25, 0, 0])
    expect(() => parsePeakTile(tooLong, 1, 1)).toThrow(DecodeError)
    expect(() => parsePeakTile(tooLong, 1, 1)).not.toThrow(/truncated/)
    expect(full.byteLength).toBe(8)
  })

  it('rejects non-finite extrema', () => {
    const bad = tileBuffer([[[-0.5, Number.NaN]]])
    expect(() => parsePeakTile(bad, 1, 1)).toThrow(DecodeError)
  })

  it('rejects invalid channel counts', () => {
    const good = tileBuffer([[[-0.5, 0.25]]])
    expect(() => parsePeakTile(good, 0, 1)).toThrow(DecodeError)
  })
})

describe('aggregatePcmToPixels', () => {
  it('aggregates multi-frame pixels per channel', () => {
    // 2 channels, 6 frames, fpp 2 -> 3 pixels (2 frames each).
    // ch0: [1, -2, 0.5, 3, -1, 2]
    // ch1: [0, 0, 0, 0, 5, -5]
    const bytes = f32leBuffer([1, 0, -2, 0, 0.5, 0, 3, 0, -1, 5, 2, -5])
    const pixels = aggregatePcmToPixels(bytes, 2, 100, 2)
    expect(pixels.startFrame).toBe(100)
    expect(pixels.frames).toBe(6)
    expect(pixels.pixels).toBe(3)
    expect(pixels.minima[0]).toEqual(new Float32Array([-2, 0.5, -1]))
    expect(pixels.maxima[0]).toEqual(new Float32Array([1, 3, 2]))
    expect(pixels.minima[1]).toEqual(new Float32Array([0, 0, -5]))
    expect(pixels.maxima[1]).toEqual(new Float32Array([0, 0, 5]))
  })

  it('splits fractional pixels by frame index', () => {
    // 6 frames, fpp 2.5 -> ceil(6/2.5) = 3 pixels:
    // f0,f1,f2 -> px0; f3,f4 -> px1; f5 -> px2.
    const ch0 = [1, -2, 0.5, 3, -1, 2]
    const bytes = f32leBuffer(ch0)
    const pixels = aggregatePcmToPixels(bytes, 1, 0, 2.5)
    expect(pixels.pixels).toBe(3)
    expect(pixels.minima[0]).toEqual(new Float32Array([-2, -1, 2]))
    expect(pixels.maxima[0]).toEqual(new Float32Array([1, 3, 2]))
  })

  it('handles a single frame per pixel', () => {
    const bytes = f32leBuffer([0.25, -0.75, 1, 1])
    const pixels = aggregatePcmToPixels(bytes, 2, 10, 1)
    expect(pixels.pixels).toBe(2)
    expect(pixels.minima[0]).toEqual(new Float32Array([0.25, 1]))
    expect(pixels.maxima[1]).toEqual(new Float32Array([-0.75, 1]))
  })

  it('rejects a trailing partial frame', () => {
    const bytes = f32leBuffer([0.25, -0.75, 1]) // 3 samples, 2 channels
    expect(() => aggregatePcmToPixels(bytes, 2, 0, 1)).toThrow(DecodeError)
    expect(() => aggregatePcmToPixels(bytes, 2, 0, 1)).toThrow(/truncated pcm/)
  })

  it('rejects an empty body', () => {
    expect(() => aggregatePcmToPixels(new ArrayBuffer(0), 1, 0, 1)).toThrow(DecodeError)
  })

  it('rejects invalid arguments', () => {
    const bytes = f32leBuffer([0.25])
    expect(() => aggregatePcmToPixels(bytes, 0, 0, 1)).toThrow(DecodeError)
    expect(() => aggregatePcmToPixels(bytes, 1, 0, 0)).toThrow(DecodeError)
  })
})

describe('pcmSamples', () => {
  it('deinterleaves into per-channel sample arrays', () => {
    const bytes = f32leBuffer([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    const channels = pcmSamples(bytes, 2)
    expect(channels).toHaveLength(2)
    expect(channels[0]).toEqual(new Float32Array([0.1, 0.3, 0.5]))
    expect(channels[1]).toEqual(new Float32Array([0.2, 0.4, 0.6]))
  })

  it('rejects a truncated body', () => {
    const bytes = f32leBuffer([0.1, 0.2, 0.3])
    expect(() => pcmSamples(bytes, 2)).toThrow(DecodeError)
  })
})
