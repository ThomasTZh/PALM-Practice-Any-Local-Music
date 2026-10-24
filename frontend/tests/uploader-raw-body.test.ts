import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * openapi-fetch JSON-serializes object bodies by default. A Blob/File is
 * an object, so without an explicit raw serializer the server receives
 * the two bytes "{}" and every import fails with CHUNK_CONFLICT at
 * offset 0. This test inspects the request body before it leaves the
 * client.
 */
class CapturingRequest {
  body: BodyInit | null
  headers: Headers
  url: string

  constructor(url: string, init?: RequestInit) {
    this.url = url
    this.body = (init?.body as BodyInit | null | undefined) ?? null
    this.headers = new Headers(init?.headers)
  }
}

describe('raw binary chunk uploads', () => {
  let captured: CapturingRequest | null

  beforeEach(() => {
    captured = null
    vi.resetModules()
    vi.stubGlobal('Request', CapturingRequest)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: CapturingRequest) => {
        captured = request
        return new Response(
          JSON.stringify({ offset: 3, chunk_bytes: 3, idempotent_replay: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the media chunk bytes, not a JSON placeholder', async () => {
    const { uploadChunk } = await import('../src/api/uploader')
    const blob = new Blob([new Uint8Array([1, 2, 3])])
    await uploadChunk('import-1', 0, blob, 'a'.repeat(64))

    expect(captured?.body).toBe(blob)
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([1, 2, 3])
  })

  it('sends the portable archive chunk bytes unchanged', async () => {
    const { uploadOpenChunk } = await import('../src/api/open')
    const blob = new Blob([new Uint8Array([9, 8, 7])])
    await uploadOpenChunk('session-1', 0, blob, 'b'.repeat(64))

    expect(captured?.body).toBe(blob)
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([9, 8, 7])
  })
})
