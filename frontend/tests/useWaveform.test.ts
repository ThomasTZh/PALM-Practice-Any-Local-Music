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

beforeEach(() => {
  vi.clearAllMocks()
  mockListProjectJobs.mockResolvedValue([])
})

describe('useWaveform', () => {
  it('is empty with no asset', () => {
    const { result } = renderHook(() => useWaveform(PROJECT_ID, null, 800))
    expect(result.current.state).toBe('empty')
    expect(result.current.manifest).toBeNull()
  })

  it('reaches ready with a final manifest and decodes the chosen level', async () => {
    const manifest = makeManifest(480_000)
    mockGetAssetMetadata.mockResolvedValue(metadata(480_000, true))
    mockGetPeaksManifest.mockResolvedValue(manifest)
    // fpp = 480000/800 = 600 -> level 2 (bfc 1024), single tile of 469 buckets.
    mockGetPeakTile.mockImplementation((_a, level, tile) =>
      Promise.resolve(tileResponse(level, tile, manifest.levels[level].final_tile_buckets)),
    )
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
    await waitFor(() => expect(result.current.state).toBe('ready'))
    expect(result.current.viewport).not.toBeNull()
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
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
    await waitFor(() => expect(result.current.state).toBe('ready'))
    expect(result.current.pcm).not.toBeNull()
    expect(result.current.pcm?.kind).toBe('pixels')
    expect(result.current.levels).toHaveLength(0)
  })

  it('is missing when there is no waveform and no live job', async () => {
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, false))
    mockListProjectJobs.mockResolvedValue([])
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
    await waitFor(() => expect(result.current.state).toBe('missing'))
  })

  it('is pending when a live waveform job is running', async () => {
    mockGetAssetMetadata.mockResolvedValue(metadata(48_000, false))
    mockListProjectJobs.mockResolvedValue([
      { id: 'job1', jobType: 'waveform', state: 'running', progressFraction: 0.5 },
    ])
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
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
      mockGetPeakTile.mockImplementation((_a, level, tile) =>
        Promise.resolve(tileResponse(level, tile, manifest.levels[level].final_tile_buckets)),
      )
      const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
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
    mockGetPeakTile.mockImplementation((_a, level, tile) =>
      Promise.resolve(tileResponse(level, tile, manifest.levels[level].final_tile_buckets)),
    )
    const { result, rerender } = renderHook(
      ({ width }: { width: number }) => useWaveform(PROJECT_ID, ASSET_ID, width),
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
    const { result } = renderHook(() => useWaveform(PROJECT_ID, ASSET_ID, 800))
    await waitFor(() => expect(result.current.state).toBe('missing'))
    act(() => {
      result.current.rebuild()
    })
    await waitFor(() => expect(mockCreateWaveformJob).toHaveBeenCalledWith(PROJECT_ID, IMPORT_ID))
    expect(result.current.state).toBe('pending')
  })
})
