import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchResultSetDetail, ResultSetNotFoundError } from '../src/api/result-sets'

const { mockClient } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
  },
}))

vi.mock('../src/api/client', () => ({
  createApiClient: () => mockClient,
  errorMessage: (e: unknown, fallback: string) => {
    if (e && typeof e === 'object' && 'error' in e) {
      const inner = (e as { error: { message?: string } }).error
      if (inner?.message) return inner.message
    }
    return fallback
  },
}))

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const RS_ID = '44444444-4444-4444-8444-444444444444'

function detailPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: RS_ID,
    created_at: '2026-01-01T00:00:00Z',
    validation_status: 'valid',
    cache_key: 'a'.repeat(64),
    stems: [
      {
        id: '55555555-5555-4555-8555-555555555555',
        role: 'bass',
        display_name: 'Bass',
        audio_asset_id: '66666666-6666-4666-8666-666666666666',
        sample_rate: 48000,
        channel_count: 2,
        frame_count: 100_000,
      },
    ],
    engine_version: 'demucs-4.1.0',
    adapter_version: 'adapter-1',
    model_manifest_id: '77777777-7777-4777-8777-777777777777',
    model_manifest_hash: 'b'.repeat(64),
    ...overrides,
  }
}

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

function fail(status: number, code: string, message: string) {
  return {
    response: { ok: false, status },
    error: { error: { code, message, details: {} } },
    data: undefined,
  }
}

describe('fetchResultSetDetail', () => {
  beforeEach(() => {
    mockClient.GET.mockReset()
  })

  it('maps the detail to camelCase', async () => {
    mockClient.GET.mockResolvedValue(ok(detailPayload()))
    const detail = await fetchResultSetDetail(PROJECT_ID, RS_ID)
    expect(mockClient.GET).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/result-sets/{result_set_id}',
      expect.objectContaining({
        params: { path: { project_id: PROJECT_ID, result_set_id: RS_ID } },
      }),
    )
    expect(detail.id).toBe(RS_ID)
    expect(detail.createdAt).toBe('2026-01-01T00:00:00Z')
    expect(detail.validationStatus).toBe('valid')
    expect(detail.cacheKey).toBe('a'.repeat(64))
    expect(detail.engineVersion).toBe('demucs-4.1.0')
    expect(detail.adapterVersion).toBe('adapter-1')
    expect(detail.modelManifestHash).toBe('b'.repeat(64))
    expect(detail.stems).toHaveLength(1)
    expect(detail.stems[0]).toEqual({
      id: '55555555-5555-4555-8555-555555555555',
      role: 'bass',
      displayName: 'Bass',
      audioAssetId: '66666666-6666-4666-8666-666666666666',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 100_000,
    })
  })

  it('treats a null cache_key as null', async () => {
    mockClient.GET.mockResolvedValue(ok(detailPayload({ cache_key: null })))
    const detail = await fetchResultSetDetail(PROJECT_ID, RS_ID)
    expect(detail.cacheKey).toBeNull()
  })

  it('throws ResultSetNotFoundError on 404', async () => {
    mockClient.GET.mockResolvedValue(fail(404, 'RESULT_SET_NOT_FOUND', 'nope'))
    await expect(fetchResultSetDetail(PROJECT_ID, RS_ID)).rejects.toThrow(ResultSetNotFoundError)
  })

  it('surfaces the server message on other failures', async () => {
    mockClient.GET.mockResolvedValue(fail(500, 'INTERNAL', 'boom'))
    await expect(fetchResultSetDetail(PROJECT_ID, RS_ID)).rejects.toThrow('boom')
  })
})
