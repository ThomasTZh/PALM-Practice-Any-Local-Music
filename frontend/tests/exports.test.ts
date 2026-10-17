import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createExport,
  downloadExport,
  ExportRequestError,
  listExports,
  type ExportArtifact,
} from '../src/api/exports'
import { waitForJob } from '../src/api/playback'

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
const RS_ID = '44444444-4444-4444-8444-444444444444'
const JOB_ID = '22222222-2222-4222-8222-222222222222'
const STEM_ID = '55555555-5555-4555-8555-555555555555'
const ASSET_ID = '66666666-6666-4666-8666-666666666666'
const ART_ID = '88888888-8888-4888-8888-888888888888'

function ok<T>(data: T, status = 200) {
  return { response: { ok: true, status }, data }
}

function fail(status: number, code: string, message: string) {
  return {
    response: { ok: false, status },
    error: { error: { code, message, details: {} } },
    data: undefined,
  }
}

function jobPayload(state = 'queued', stage: string | null = null) {
  return {
    id: JOB_ID,
    state,
    stage,
    progress_fraction: state === 'completed' ? 1 : null,
    error_code: null,
    error: null,
  }
}

function artifactPayload() {
  return {
    artifact_id: ART_ID,
    job_id: JOB_ID,
    job_state: 'completed',
    result_set_id: RS_ID,
    stem_id: STEM_ID,
    asset_id: ASSET_ID,
    role: 'bass',
    format: 'wav24',
    sample_rate: 48000,
    channel_count: 2,
    frame_count: 100_000,
    normalized: true,
    gain_db: 3.2,
    dither: 'triangular',
    sha256: 'c'.repeat(64),
    byte_size: 400_000,
    download_filename: 'Bass-abc123-48k-24bit.wav',
    download_url: `/api/v1/downloads/${ART_ID}`,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('createExport', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('posts the selection and a fresh Idempotency-Key, and maps the job', async () => {
    mockClient.POST.mockResolvedValue(ok(jobPayload()))
    const job = await createExport(PROJECT_ID, {
      resultSetId: RS_ID,
      assetIds: [ASSET_ID],
      format: 'wav24',
      sampleRate: null,
      normalize: 'off',
    })
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/exports',
      expect.objectContaining({
        params: { path: { project_id: PROJECT_ID } },
        body: {
          result_set_id: RS_ID,
          asset_ids: [ASSET_ID],
          format: 'wav24',
          sample_rate: null,
          normalize: 'off',
        },
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    )
    expect(job).toEqual({
      id: JOB_ID,
      state: 'queued',
      stage: null,
      progressFraction: null,
      errorCode: null,
      error: null,
    })
  })

  it('surfaces the server error code and message', async () => {
    mockClient.POST.mockResolvedValue(
      fail(400, 'EXPORT_CLIPPING', 'the selected stems peak above the full-scale bound'),
    )
    const promise = createExport(PROJECT_ID, {
      resultSetId: RS_ID,
      assetIds: [ASSET_ID],
      format: 'wav16',
      sampleRate: null,
      normalize: 'off',
    })
    await expect(promise).rejects.toBeInstanceOf(ExportRequestError)
    await expect(promise).rejects.toMatchObject({ code: 'EXPORT_CLIPPING', statusCode: 400 })
    await expect(promise).rejects.toThrow(/full-scale bound/)
  })
})

describe('listExports', () => {
  beforeEach(() => {
    mockClient.GET.mockReset()
  })

  it('maps the artifact list to camelCase', async () => {
    mockClient.GET.mockResolvedValue(ok({ artifacts: [artifactPayload()] }))
    const artifacts = await listExports(PROJECT_ID)
    expect(mockClient.GET).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/exports',
      expect.objectContaining({ params: { path: { project_id: PROJECT_ID } } }),
    )
    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toEqual({
      artifactId: ART_ID,
      jobId: JOB_ID,
      jobState: 'completed',
      resultSetId: RS_ID,
      stemId: STEM_ID,
      assetId: ASSET_ID,
      role: 'bass',
      format: 'wav24',
      sampleRate: 48000,
      channelCount: 2,
      frameCount: 100_000,
      normalized: true,
      gainDb: 3.2,
      dither: 'triangular',
      sha256: 'c'.repeat(64),
      byteSize: 400_000,
      downloadFilename: 'Bass-abc123-48k-24bit.wav',
      downloadUrl: `/api/v1/downloads/${ART_ID}`,
      createdAt: '2026-01-01T00:00:00Z',
    })
  })

  it('treats an empty listing as an empty array', async () => {
    mockClient.GET.mockResolvedValue(ok({ artifacts: [] }))
    await expect(listExports(PROJECT_ID)).resolves.toEqual([])
  })
})

async function exportedArtifact(): Promise<ExportArtifact> {
  mockClient.GET.mockReset()
  mockClient.GET.mockResolvedValue(ok({ artifacts: [artifactPayload()] }))
  return (await listExports(PROJECT_ID))[0]
}

describe('downloadExport', () => {
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>
  let fetchMock: ReturnType<typeof vi.fn>
  let clickedAnchor: HTMLAnchorElement | null

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
      blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/wav' }),
    })
    const artifact = await exportedArtifact()
    await downloadExport(artifact)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/downloads/${ART_ID}`,
      expect.objectContaining({
        headers: { Authorization: 'Bearer test-token' },
      }),
    )
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickedAnchor).not.toBeNull()
    expect(clickedAnchor?.download).toBe('Bass-abc123-48k-24bit.wav')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-123')
  })

  it('throws on a non-OK response without downloading', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 })
    const artifact = await exportedArtifact()
    await expect(downloadExport(artifact)).rejects.toThrow('Export download failed (404)')
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clickedAnchor).toBeNull()
  })
})

describe('waitForJob (M2.13 onProgress)', () => {
  beforeEach(() => {
    mockClient.GET.mockReset()
  })

  it('reports each polled state, including the terminal one', async () => {
    const states = [
      jobPayload('queued'),
      { ...jobPayload('running', 'encoding'), progress_fraction: 0.5 },
      jobPayload('completed'),
    ]
    mockClient.GET.mockImplementation(async () => ok(states.shift()!))
    const seen: Array<[string, string | null]> = []
    const final = await waitForJob(JOB_ID, {
      pollMs: 1,
      onProgress: (job) => seen.push([job.state, job.stage]),
    })
    expect(final.state).toBe('completed')
    expect(seen).toEqual([
      ['queued', null],
      ['running', 'encoding'],
      ['completed', null],
    ])
  })
})
