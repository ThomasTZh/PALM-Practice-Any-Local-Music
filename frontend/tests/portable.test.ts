import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  downloadPortableSave,
  listPortableSaves,
  PortableSaveRequestError,
  savePortableProject,
  type PortableSave,
} from '../src/api/portable'

const { mockClient } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
    POST: vi.fn(),
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

vi.mock('../src/auth', () => ({
  getSessionToken: () => 'test-token',
}))

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const ART_ID = '88888888-8888-4888-8888-888888888888'

function ok<T>(data: T, status = 200) {
  return { response: { ok: true, status }, data }
}

function fail(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return {
    response: { ok: false, status },
    error: { error: { code, message, details: details ?? {} } },
    data: undefined,
  }
}

function savePayload(savedRevision = 5) {
  return {
    artifact_id: ART_ID,
    project_id: PROJECT_ID,
    saved_revision: savedRevision,
    sha256: 'c'.repeat(64),
    byte_size: 400_000,
    download_filename: 'Song-r5.basseparate',
    download_url: `/api/v1/portable-downloads/${ART_ID}`,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('savePortableProject', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('posts with a fresh Idempotency-Key and maps the artifact', async () => {
    mockClient.POST.mockResolvedValue(ok(savePayload(), 201))
    const save = await savePortableProject(PROJECT_ID)
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/portable-saves',
      expect.objectContaining({
        params: { path: { project_id: PROJECT_ID } },
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    )
    expect(save).toEqual({
      artifactId: ART_ID,
      projectId: PROJECT_ID,
      savedRevision: 5,
      sha256: 'c'.repeat(64),
      byteSize: 400_000,
      downloadFilename: 'Song-r5.basseparate',
      downloadUrl: `/api/v1/portable-downloads/${ART_ID}`,
      createdAt: '2026-01-01T00:00:00Z',
    })
  })

  it('surfaces the server error code and the missing file list', async () => {
    mockClient.POST.mockResolvedValue(
      fail(409, 'SAVE_ASSET_MISSING', 'essential asset file(s) are missing', {
        missing: ['data/assets/abc.pcm'],
      }),
    )
    const promise = savePortableProject(PROJECT_ID)
    await expect(promise).rejects.toBeInstanceOf(PortableSaveRequestError)
    await expect(promise).rejects.toMatchObject({
      code: 'SAVE_ASSET_MISSING',
      statusCode: 409,
      missing: ['data/assets/abc.pcm'],
    })
  })
})

describe('listPortableSaves', () => {
  beforeEach(() => {
    mockClient.GET.mockReset()
  })

  it('maps the save list to camelCase, newest first', async () => {
    mockClient.GET.mockResolvedValue(ok({ saves: [savePayload(7), savePayload(5)] }))
    const saves = await listPortableSaves(PROJECT_ID)
    expect(mockClient.GET).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/portable-saves',
      expect.objectContaining({ params: { path: { project_id: PROJECT_ID } } }),
    )
    expect(saves.map((s) => s.savedRevision)).toEqual([7, 5])
  })

  it('treats an empty listing as an empty array', async () => {
    mockClient.GET.mockResolvedValue(ok({ saves: [] }))
    await expect(listPortableSaves(PROJECT_ID)).resolves.toEqual([])
  })
})

describe('downloadPortableSave', () => {
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>
  let fetchMock: ReturnType<typeof vi.fn>
  let clickedAnchor: HTMLAnchorElement | null

  function saved(): PortableSave {
    return {
      artifactId: ART_ID,
      projectId: PROJECT_ID,
      savedRevision: 5,
      sha256: 'c'.repeat(64),
      byteSize: 400_000,
      downloadFilename: 'Song-r5.basseparate',
      downloadUrl: `/api/v1/portable-downloads/${ART_ID}`,
      createdAt: '2026-01-01T00:00:00Z',
    }
  }

  beforeEach(() => {
    createObjectURL = vi.fn(() => 'blob:mock-123')
    revokeObjectURL = vi.fn()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', {
      createObjectURL,
      revokeObjectURL,
    } as unknown as typeof URL)
    clickedAnchor = null
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedAnchor = this
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('fetches with the session token and triggers a browser download', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: 'application/zip' }),
    })
    await downloadPortableSave(saved())
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/portable-downloads/${ART_ID}`,
      expect.objectContaining({
        headers: { Authorization: 'Bearer test-token' },
      }),
    )
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickedAnchor).not.toBeNull()
    expect(clickedAnchor?.download).toBe('Song-r5.basseparate')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-123')
  })

  it('throws on a non-OK response without downloading', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 })
    await expect(downloadPortableSave(saved())).rejects.toThrow(
      'Portable save download failed (404)',
    )
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clickedAnchor).toBeNull()
  })
})
