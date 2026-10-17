import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deinterleaveChannels, fetchPcmRange } from '../src/playback/pcm-fetch'

function pcmResponse(
  body: ArrayBuffer,
  init: { status?: number; headers?: Record<string, string> } = {},
) {
  return new Response(body, { status: init.status ?? 200, headers: init.headers })
}

describe('fetchPcmRange', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('requests a byte range with Bearer auth and parses the content-range total', async () => {
    sessionStorage.setItem('basseparate.sessionToken', 'tok-123')
    const source = new Float32Array([1, 2, 3])
    const bytes = source.buffer as ArrayBuffer
    const fetchMock = vi.fn().mockResolvedValue(
      pcmResponse(bytes, {
        status: 206,
        headers: { 'content-range': 'bytes 100-111/1000' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const result = await fetchPcmRange('asset-1', 100, 111)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/assets/asset-1/bytes',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer tok-123',
          Range: 'bytes=100-111',
        }),
      }),
    )
    expect(result.total).toBe(1000)
    // `arrayBuffer()` returns a copy, so compare contents, not identity.
    expect(Array.from(new Float32Array(result.bytes))).toEqual([1, 2, 3])
  })

  it('fetches the whole asset without Range or auth headers when unauthenticated', async () => {
    const bytes = new ArrayBuffer(8)
    const fetchMock = vi
      .fn()
      .mockResolvedValue(pcmResponse(bytes, { headers: { 'content-length': '8' } }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await fetchPcmRange('asset-1')
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.Range).toBeUndefined()
    expect(headers.Authorization).toBeUndefined()
    expect(result.total).toBe(8)
  })

  it('throws a RangeError on 416', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 416 })))
    await expect(fetchPcmRange('asset-1', 0, 999_999)).rejects.toThrow(RangeError)
  })

  it('throws a plain Error on other failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 500 })))
    await expect(fetchPcmRange('asset-1')).rejects.toThrow('Asset bytes failed (500)')
  })

  it('passes the abort signal through', async () => {
    const fetchMock = vi.fn().mockResolvedValue(pcmResponse(new ArrayBuffer(4)))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await fetchPcmRange('asset-1', 0, 3, controller.signal)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.signal).toBe(controller.signal)
  })

  it('hints playback PCM as high priority and waveform work as low (M2.12 §14.3)', async () => {
    // A fresh Response per call: a body can only be read once.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(pcmResponse(new ArrayBuffer(4))))
    vi.stubGlobal('fetch', fetchMock)
    await fetchPcmRange('asset-1', 0, 3)
    expect((fetchMock.mock.calls[0][1] as RequestInit).priority).toBe('high')
    await fetchPcmRange('asset-1', 0, 3, undefined, 'low')
    expect((fetchMock.mock.calls[1][1] as RequestInit).priority).toBe('low')
  })
})

describe('deinterleaveChannels', () => {
  it('splits interleaved stereo f32le into per-channel arrays', () => {
    // Values are exactly representable in f32, so deep equality is exact.
    const interleaved = new Float32Array([0.5, -0.25, 0.75, -0.125, 1, -0.5])
    const [left, right] = deinterleaveChannels(interleaved.buffer as ArrayBuffer, 2)
    expect(Array.from(left)).toEqual([0.5, 0.75, 1])
    expect(Array.from(right)).toEqual([-0.25, -0.125, -0.5])
  })

  it('rejects an invalid channel count', () => {
    expect(() => deinterleaveChannels(new ArrayBuffer(8), 0)).toThrow(RangeError)
  })
})
