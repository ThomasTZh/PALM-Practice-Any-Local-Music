import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getAssetMetadata,
  getAssetPcm,
  getPeakTile,
  getPeaksManifest,
  NoWaveformCacheError,
  RangeOutOfBoundsError,
  TileNotReadyError,
} from '../../src/api/waveform'

const { mockClient } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PUT: vi.fn(),
  },
}))

vi.mock('../../src/api/client', () => ({
  createApiClient: () => mockClient,
  errorMessage: (e: unknown, fallback: string) => {
    if (e && typeof e === 'object' && 'error' in e) {
      const inner = (e as { error: { message?: string } }).error
      if (inner?.message) return inner.message
    }
    return fallback
  },
}))

const ASSET_ID = '44444444-4444-4444-4444-444444444444'

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

function fail(status: number, code: string, message: string) {
  return {
    response: { ok: false, status },
    error: { error: { code, message } },
    data: undefined,
  }
}

function jsonError(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('getAssetMetadata', () => {
  it('maps the metadata response to camelCase', async () => {
    mockClient.GET.mockResolvedValue(
      ok({
        asset_id: ASSET_ID,
        role: 'source_pcm',
        content_hash: 'abc',
        sample_rate: 48000,
        channel_count: 2,
        frame_count: 48000,
        byte_count: 768000,
        waveform: null,
      }),
    )
    const meta = await getAssetMetadata(ASSET_ID)
    expect(meta.assetId).toBe(ASSET_ID)
    expect(meta.role).toBe('source_pcm')
    expect(meta.contentHash).toBe('abc')
    expect(meta.sampleRate).toBe(48000)
    expect(meta.channelCount).toBe(2)
    expect(meta.frameCount).toBe(48000)
    expect(meta.byteCount).toBe(768000)
    expect(meta.waveform).toBeNull()
  })

  it('throws with the envelope message on a non-OK response', async () => {
    mockClient.GET.mockResolvedValue(fail(500, 'INTERNAL', 'boom'))
    await expect(getAssetMetadata(ASSET_ID)).rejects.toThrow('boom')
  })
})

describe('getPeaksManifest', () => {
  it('returns the manifest on success', async () => {
    const manifest = {
      cache_version: 1,
      source_hash: 'a'.repeat(64),
      sample_rate: 48000,
      frame_count: 48000,
      channel_count: 2,
      base_bucket_frames: 64,
      aggregation: 4,
      levels: [
        { bucket_frame_count: 64, bucket_count: 750, tile_count: 1, final_tile_buckets: 750 },
      ],
      available_tiles: { '0': [[0, 0]] },
      final: true,
    }
    mockClient.GET.mockResolvedValue(ok(manifest))
    const result = await getPeaksManifest(ASSET_ID)
    expect(result).toEqual(manifest)
  })

  it('returns null on a 404 (no cache)', async () => {
    mockClient.GET.mockResolvedValue(fail(404, 'NO_WAVEFORM_CACHE', 'no cache'))
    const result = await getPeaksManifest(ASSET_ID)
    expect(result).toBeNull()
  })

  it('throws on other failures', async () => {
    mockClient.GET.mockResolvedValue(fail(500, 'INTERNAL', 'boom'))
    await expect(getPeaksManifest(ASSET_ID)).rejects.toThrow('boom')
  })
})

describe('getPeakTile', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the tile bytes and header values', async () => {
    const bytes = new ArrayBuffer(16)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(bytes, {
          status: 200,
          headers: {
            'X-Level': '1',
            'X-Tile': '3',
            'X-Bucket-Frames': '256',
            'X-Tile-Buckets': '4096',
          },
        }),
      ),
    )
    const tile = await getPeakTile(ASSET_ID, 1, 3)
    expect(tile.bytes.byteLength).toBe(bytes.byteLength)
    expect(new Uint8Array(tile.bytes)).toStrictEqual(new Uint8Array(bytes))
    expect(tile.level).toBe(1)
    expect(tile.tile).toBe(3)
    expect(tile.bucketFrameCount).toBe(256)
    expect(tile.tileBuckets).toBe(4096)
  })

  it('maps 404 TILE_NOT_READY to TileNotReadyError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonError(404, 'TILE_NOT_READY', 'not ready')))
    await expect(getPeakTile(ASSET_ID, 0, 5)).rejects.toBeInstanceOf(TileNotReadyError)
  })

  it('maps 404 NO_WAVEFORM_CACHE to NoWaveformCacheError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonError(404, 'NO_WAVEFORM_CACHE', 'no cache')),
    )
    await expect(getPeakTile(ASSET_ID, 0, 0)).rejects.toBeInstanceOf(NoWaveformCacheError)
  })

  it('maps 422 PEAK_RANGE_OUT_OF_BOUNDS to RangeOutOfBoundsError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonError(422, 'PEAK_RANGE_OUT_OF_BOUNDS', 'out of bounds')),
    )
    const err = await getPeakTile(ASSET_ID, 9, 0).catch((e) => e)
    expect(err).toBeInstanceOf(RangeOutOfBoundsError)
    expect((err as RangeOutOfBoundsError).code).toBe('PEAK_RANGE_OUT_OF_BOUNDS')
  })
})

describe('getAssetPcm', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the PCM bytes and header values', async () => {
    const bytes = new ArrayBuffer(32)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(bytes, {
          status: 200,
          headers: {
            'X-Asset-Id': ASSET_ID,
            'X-Content-Hash': 'abc',
            'X-Sample-Rate': '48000',
            'X-Channel-Count': '2',
            'X-Start-Frame': '100',
            'X-Frame-Count': '4',
            'X-EOF': 'false',
          },
        }),
      ),
    )
    const pcm = await getAssetPcm(ASSET_ID, 100, 4)
    expect(pcm.bytes.byteLength).toBe(bytes.byteLength)
    expect(new Uint8Array(pcm.bytes)).toStrictEqual(new Uint8Array(bytes))
    expect(pcm.startFrame).toBe(100)
    expect(pcm.frameCount).toBe(4)
    expect(pcm.eof).toBe(false)
    expect(pcm.sampleRate).toBe(48000)
    expect(pcm.channelCount).toBe(2)
    expect(pcm.contentHash).toBe('abc')
  })

  it('parses X-EOF true', async () => {
    const bytes = new ArrayBuffer(8)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(bytes, {
          status: 200,
          headers: { 'X-EOF': 'true', 'X-Start-Frame': '0', 'X-Frame-Count': '1' },
        }),
      ),
    )
    const pcm = await getAssetPcm(ASSET_ID, 0, 1)
    expect(pcm.eof).toBe(true)
  })

  it('maps 422 PCM_RANGE_OUT_OF_BOUNDS to RangeOutOfBoundsError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonError(422, 'PCM_RANGE_OUT_OF_BOUNDS', 'oob')),
    )
    const err = await getAssetPcm(ASSET_ID, 999_999, 1).catch((e) => e)
    expect(err).toBeInstanceOf(RangeOutOfBoundsError)
    expect((err as RangeOutOfBoundsError).code).toBe('PCM_RANGE_OUT_OF_BOUNDS')
  })
})
