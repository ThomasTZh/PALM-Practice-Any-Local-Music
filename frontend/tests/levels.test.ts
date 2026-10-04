import { describe, expect, it } from 'vitest'
import {
  adjacentTileRange,
  chooseLevel,
  PCM_MIN_FPP,
  pcmFrameRange,
  SAMPLE_LEVEL_FPP,
  TILE_BUCKETS,
  usePcm,
  useSampleLevel,
  visibleBucketRange,
  visibleTileRange,
  type WaveformManifest,
} from '../src/waveform/levels'
import { fitViewport, makeViewport } from '../src/waveform/viewport'

/** 1,200,000 frames @ geometry (64, 4, 4096): bfc [64, 256, 1024]. */
const manifest: WaveformManifest = {
  cache_version: 1,
  source_hash: 'a'.repeat(64),
  sample_rate: 48000,
  frame_count: 1_200_000,
  channel_count: 2,
  base_bucket_frames: 64,
  aggregation: 4,
  levels: [
    { bucket_frame_count: 64, bucket_count: 18_750, tile_count: 5, final_tile_buckets: 2_366 },
    { bucket_frame_count: 256, bucket_count: 4_688, tile_count: 2, final_tile_buckets: 592 },
    { bucket_frame_count: 1024, bucket_count: 1_172, tile_count: 1, final_tile_buckets: 1_172 },
  ],
  available_tiles: { '0': [[0, 4]], '1': [[0, 1]], '2': [[0, 0]] },
  final: true,
}

describe('chooseLevel', () => {
  const cases: Array<[number, number]> = [
    [1, 0],
    [63, 0],
    [64, 0], // exactly one level-0 bucket per pixel
    [128, 0], // exactly two level-0 buckets per pixel
    [129, 1],
    [256, 1],
    [512, 1], // exactly two level-1 buckets per pixel
    [513, 2],
    [1024, 2],
    [100_000, 2], // beyond the finest level: stay on the coarsest
  ]

  it.each(cases)('fpp %i -> level %i', (fpp, level) => {
    expect(chooseLevel(manifest, fpp)).toBe(level)
  })

  it('never exceeds two buckets per CSS pixel while the pyramid is deep enough', () => {
    // The coarsest level (bfc 1024) covers at most 2 buckets/px up to
    // fpp 2048; beyond that the pyramid runs out of levels.
    for (const fpp of [1, 64, 128, 200, 512, 2048]) {
      const level = chooseLevel(manifest, fpp)
      expect(fpp / manifest.levels[level].bucket_frame_count).toBeLessThanOrEqual(2)
    }
  })

  it('rejects non-positive zoom', () => {
    expect(() => chooseLevel(manifest, 0)).toThrow(RangeError)
    expect(() => chooseLevel(manifest, -1)).toThrow(RangeError)
  })
})

describe('visibleBucketRange / visibleTileRange', () => {
  it('covers a viewport straddling a tile boundary', () => {
    // Frames [260000, 262500] at level 0 (bfc 64); tile 1 starts at
    // bucket 4096 (frame 262144).
    const vp = makeViewport(260_000, 2.5, 1000)
    expect(visibleBucketRange(manifest.levels[0], vp)).toEqual([4062, 4101])
    expect(visibleTileRange(manifest.levels[0], vp)).toEqual([0, 1])
  })

  it('stays inside one tile for a narrow viewport', () => {
    const vp = makeViewport(0, 1.2, 1000) // frames [0, 1200]
    expect(visibleTileRange(manifest.levels[0], vp)).toEqual([0, 0])
    expect(visibleTileRange(manifest.levels[2], vp)).toEqual([0, 0])
  })

  it('a fit viewport spans the whole source', () => {
    const vp = fitViewport(1_200_000, 1000)
    expect(visibleTileRange(manifest.levels[0], vp)).toEqual([0, 4])
    expect(visibleTileRange(manifest.levels[2], vp)).toEqual([0, 0])
  })

  it('clamps to the last bucket at the end of the source', () => {
    const vp = makeViewport(1_198_000, 2, 1000) // frames [1198000, 1200000]
    const [first, last] = visibleBucketRange(manifest.levels[0], vp)
    expect(first).toBe(18_718)
    expect(last).toBe(18_749) // bucket_count - 1, not 18750
    expect(visibleTileRange(manifest.levels[0], vp)).toEqual([4, 4])
  })

  it('clamps a one-bucket source to bucket zero', () => {
    const tiny: WaveformManifest = {
      ...manifest,
      frame_count: 64,
      levels: [{ bucket_frame_count: 64, bucket_count: 1, tile_count: 1, final_tile_buckets: 1 }],
    }
    const vp = fitViewport(64, 100)
    expect(visibleBucketRange(tiny.levels[0], vp)).toEqual([0, 0])
    expect(visibleTileRange(tiny.levels[0], vp)).toEqual([0, 0])
  })
})

describe('adjacentTileRange', () => {
  it('adds one tile on each side', () => {
    const vp = makeViewport(260_000, 2.5, 1000) // visible tiles [0, 1]
    expect(adjacentTileRange(manifest.levels[0], vp)).toEqual([0, 2])
  })

  it('clamps at tile zero', () => {
    const vp = makeViewport(0, 1.2, 1000) // visible tile [0, 0]
    expect(adjacentTileRange(manifest.levels[0], vp)).toEqual([0, 1])
  })

  it('clamps at the last tile', () => {
    const vp = makeViewport(1_198_000, 2, 1000) // visible tile [4, 4]
    expect(adjacentTileRange(manifest.levels[0], vp)).toEqual([3, 4])
  })

  it('expands a single-tile level to itself', () => {
    const vp = fitViewport(1_200_000, 1000)
    expect(adjacentTileRange(manifest.levels[2], vp)).toEqual([0, 0])
  })
})

describe('usePcm / useSampleLevel', () => {
  it('switches to PCM below the coarsest bucket width', () => {
    expect(usePcm(PCM_MIN_FPP)).toBe(false) // 64 fpp: one bucket per pixel
    expect(usePcm(PCM_MIN_FPP - 0.5)).toBe(true)
    expect(usePcm(1)).toBe(true)
  })

  it('switches to sample drawing below one frame per pixel', () => {
    expect(useSampleLevel(SAMPLE_LEVEL_FPP)).toBe(false)
    expect(useSampleLevel(0.999)).toBe(true)
  })
})

describe('pcmFrameRange', () => {
  it('covers the viewport with whole frames', () => {
    const vp = makeViewport(100.5, 0.5, 100) // end frame 150.5
    expect(pcmFrameRange(vp, 1_200_000)).toEqual([100, 151])
  })

  it('clamps to the source duration', () => {
    const vp = makeViewport(100.5, 0.5, 100)
    expect(pcmFrameRange(vp, 120)).toEqual([100, 120])
  })

  it('clamps to frame zero at the start', () => {
    const vp = fitViewport(48_000, 800)
    expect(pcmFrameRange(vp, 48_000)).toEqual([0, 48_000])
  })

  it('is identity-free for a sub-pixel start', () => {
    // The first whole frame is floor(startFrame), never ceil.
    const vp = makeViewport(0.25, 0.1, 10)
    expect(pcmFrameRange(vp, 1000)[0]).toBe(0)
  })
})

describe('TILE_BUCKETS', () => {
  it('matches the M1.8 tile size', () => {
    expect(TILE_BUCKETS).toBe(4096)
  })
})
