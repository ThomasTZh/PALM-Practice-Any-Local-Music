import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
  mockGetAssetMetadata,
  mockGetPeaksManifest,
  mockGetPeakTile,
  mockGetAssetPcm,
  mockListProjectJobs,
  mockCreateWaveformJob,
  mockLatestCompletedImportId,
} = vi.hoisted(() => ({
  mockGetAssetMetadata: vi.fn(),
  mockGetPeaksManifest: vi.fn(),
  mockGetPeakTile: vi.fn(),
  mockGetAssetPcm: vi.fn(),
  mockListProjectJobs: vi.fn(),
  mockCreateWaveformJob: vi.fn(),
  mockLatestCompletedImportId: vi.fn(),
}))

vi.mock('../src/api/waveform', () => ({
  getAssetMetadata: mockGetAssetMetadata,
  getPeaksManifest: mockGetPeaksManifest,
  getPeakTile: mockGetPeakTile,
  getAssetPcm: mockGetAssetPcm,
  listProjectJobs: mockListProjectJobs,
  createWaveformJob: mockCreateWaveformJob,
  TileNotReadyError: class TileNotReadyError extends Error {},
  NoWaveformCacheError: class NoWaveformCacheError extends Error {},
  RangeOutOfBoundsError: class RangeOutOfBoundsError extends Error {},
}))

vi.mock('../src/api/playback', () => ({
  latestCompletedImportId: mockLatestCompletedImportId,
}))

import { useWaveform } from '../src/waveform/useWaveform'
import { fitViewport, makeViewport, type Viewport } from '../src/waveform/viewport'

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'
const ASSET_ID = '44444444-4444-4444-4444-444444444444'
const IMPORT_ID = '22222222-2222-2222-2222-222222222222'

/** Build a pyramid manifest for `frameCount` frames (2 channels). */
function makeManifest(frameCount: number, final = true) {
  const levels: Array<{
    bucket_frame_count: number
    bucket_count: number
    tile_count: number
    final_tile_buckets: number
  }> = []
  let bfc = 64
  let buckets = Math.ceil(frameCount / bfc)
  while (buckets > 0) {
    levels.push({
      bucket_frame_count: bfc,
      bucket_count: buckets,
      tile_count: Math.ceil(buckets / 4096),
      final_tile_buckets: buckets % 4096 === 0 ? 4096 : buckets % 4096,
    })
    if (buckets === 1) break // coarsest level is a single bucket
    bfc *= 4
    buckets = Math.ceil(buckets / 4)
  }
  return {
    cache_version: 1,
    source_hash: 'a'.repeat(64),
    sample_rate: 48000,
    frame_count: frameCount,
    channel_count: 2,
    base_bucket_frames: 64,
    aggregation: 4,
    levels,
    available_tiles: {},
    final,
  }
}

function metadata(frameCount: number, withWaveform: boolean) {
  return {
    assetId: ASSET_ID,
    role: 'source_pcm',
    contentHash: 'abc',
    sampleRate: 48000,
    channelCount: 2,
    frameCount,
    byteCount: frameCount * 8,
    waveform: withWaveform ? { final: true, frame_count: frameCount } : null,
  }
}

function tileResponse(level: number, tile: number, bucketCount: number) {
  return {
    bytes: new ArrayBuffer(bucketCount * 2 * 8),
    level,
    tile,
    bucketFrameCount: 64,
    tileBuckets: bucketCount,
  }
}

/** Mock `getPeakTile` with correctly sized tiles for `manifest`. */
function mockTiles(manifest: ReturnType<typeof makeManifest>) {
  mockGetPeakTile.mockImplementation((_a, level, tile) => {
    const summary = manifest.levels[level]
    const bucketCount = tile === summary.tile_count - 1 ? summary.final_tile_buckets : 4096
    return Promise.resolve(tileResponse(level, tile, bucketCount))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListProjectJobs.mockResolvedValue([])
})

describe('useWaveform', () => {
  it('is empty with no asset', () => {
    const { result } = renderHook(() => useWaveform(PROJECT_ID, null, null))
    expect(result.current.state).toBe('empty')
    expect(result.current.manifest).toBeNull()
  })

  it('reaches ready with a final manifest and decodes the chosen level', async () => {
    const manifest = makeManifest(480_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(480_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    // fpp = 480000/800 = 600 -> level 2 (bfc 1024), single tile of 469 buckets.
    mockTiles(manifest)
    // Stable identity: the hook re-fetches when the viewport changes.
    const viewport = fitViewport(480_000, 800)
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, viewport))
    await waitFor(() => expect(result.current.state).toBe('ready'))
    expect(result.current.levels).toHaveLength(1)
    expect(result.current.levels[0].level).toBe(2)
    expect(result.current.levels[0].tiles.get(0)).toBeDefined()
    expect(result.current.pcm).toBeNull()
  })

  it('uses the PCM path for a short song (fpp below the coarsest bucket)', async () => {
    const manifest = makeManifest(48_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    mockGetAssetPcm.mockResolvedValue({
      bytes: new ArrayBuffer(48_000 * 8),
      startFrame: 0,
      frameCount: 48_000,
      eof: true,
      sampleRate: 48000,
      channelCount: 2,
      contentHash: 'abc',
    })
    const viewport = fitViewport(48_000, 800)
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, viewport))
    await waitFor(() => expect(result.current.state).toBe('ready'))
    expect(result.current.pcm).not.toBeNull()
    expect(result.current.pcm?.kind).toBe('pixels')
    expect(result.current.levels).toHaveLength(0)
  })

  it('is missing when there is no waveform and no live job', async () => {
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, false))
    mockListProjectJobs.mockResolvedValue([])
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, null))
    await waitFor(() => expect(result.current.state).toBe('missing'))
  })

  it('is pending when a live waveform job is running', async () => {
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, false))
    mockListProjectJobs.mockResolvedValue([
      { id: 'job1', jobType: 'waveform', state: 'running', progressFraction: 0.5 },
    ])
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, null))
    await waitFor(() => expect(result.current.state).toBe('pending'))
  })

  it('polls the manifest while pending, then reaches ready', async () => {
    vi.useFakeTimers()
    try {
      const manifest = makeManifest(480_000)
      mockGetAssetMetadata.mockResolvedValue(metadata(480_000, true))
      mockGetPeaksManifest
        .mockResolvedValueOnce(makeManifest(480_000, false))
        .mockResolvedValue(manifest)
      mockTiles(manifest)
      const viewport = fitViewport(480_000, 800)
      const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, viewport))
      await act(async () => {})
      expect(result.current.state).toBe('pending')
      await act(async () => {
        vi.advanceTimersByTime(500)
      })
      expect(result.current.state).toBe('ready')
    } finally {
      vi.useRealTimers()
    }
  })

  it('switches from PCM to peaks when the width crosses the threshold', async () => {
    const manifest = makeManifest(48_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    mockGetAssetPcm.mockResolvedValue({
      bytes: new ArrayBuffer(48_000 * 8),
      startFrame: 0,
      frameCount: 48_000,
      eof: true,
      sampleRate: 48000,
      channelCount: 2,
      contentHash: 'abc',
    })
    mockTiles(manifest)
    // Cache the viewport per width so its identity is stable across the
    // hook's own re-renders (a fresh object would loop the data effect).
    let cached: { width: number; vp: Viewport } | null = null
    const { result, rerender } = renderHook(
      ({ width }: { width: number }) => {
        if (!cached || cached.width !== width) {
          cached = { width, vp: fitViewport(48_000, width) }
        }
        return useWaveform(PROJECT_ID, ASSET_ID, cached.vp)
      },
      { initialProps: { width: 800 } },
    )
    await waitFor(() => expect(result.current.state).toBe('ready'))
    expect(result.current.pcm).not.toBeNull() // fpp 60 -> PCM
    expect(result.current.levels).toHaveLength(0)
    rerender({ width: 400 }) // fpp 120 -> peaks
    await waitFor(() => expect(result.current.levels).toHaveLength(1))
    expect(result.current.pcm).toBeNull()
  })

  it('rebuild posts a waveform job and moves to pending', async () => {
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, false))
    mockListProjectJobs.mockResolvedValue([])
    mockLatestCompletedImportId.mockResolvedValue(IMPORT_ID)
    mockCreateWaveformJob.mockResolvedValue({
      id: 'job1',
      jobType: 'waveform',
      state: 'queued',
      progressFraction: null,
    })
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, null))
    await waitFor(() => expect(result.current.state).toBe('missing'))
    act(() => {
      result.current.rebuild()
    })
    await waitFor(() => expect(mockCreateWaveformJob).toHaveBeenCalledWith(PROJECT_ID, IMPORT_ID))
    expect(result.current.state).toBe('pending')
  })

  it('fetches the coarsest level in full for the overview, independent of the viewport', async () => {
    const manifest = makeManifest(480_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(480_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    mockTiles(manifest)
    const coarse = manifest.levels.length - 1
    // A zoomed viewport: fpp 128 -> level 0, so the main view is not the coarsest.
    const viewport = makeViewport(0, 128, 800)
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, viewport))
    await waitFor(() => expect(result.current.overview).not.toBeNull())
    expect(result.current.overview?.level).toBe(coarse)
    expect(result.current.overview?.tiles.size).toBe(manifest.levels[coarse].tile_count)
    expect(mockGetPeakTile).toHaveBeenCalledWith(ASSET_ID, coarse, 0, expect.any(AbortSignal))
    await waitFor(() => expect(result.current.levels).toHaveLength(1))
    expect(result.current.levels[0].level).toBe(0)
  })

  it('re-fetches data when the viewport zooms', async () => {
    const manifest = makeManifest(480_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(480_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    mockTiles(manifest)
    const { result, rerender } = renderHook(
      (vp: Viewport) => useWaveform(PROJECT_ID, ASSET_ID, vp),
      { initialProps: fitViewport(480_000, 800) },
    )
    await waitFor(() => expect(result.current.levels).toHaveLength(1))
    expect(result.current.levels[0].level).toBe(2)
    mockGetPeakTile.mockClear()
    // Zoom in: fpp 128 -> level 0, tiles 0..1 (with the adjacent tile).
    rerender(makeViewport(0, 128, 800))
    await waitFor(() => expect(result.current.levels[0].level).toBe(0))
    expect(mockGetPeakTile).toHaveBeenCalledWith(ASSET_ID, 0, 0, expect.any(AbortSignal))
    expect(mockGetPeakTile).toHaveBeenCalledWith(ASSET_ID, 0, 1, expect.any(AbortSignal))
  })
})
