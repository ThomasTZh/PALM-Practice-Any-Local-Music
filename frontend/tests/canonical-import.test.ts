import { beforeEach, describe, expect, it, vi } from 'vitest'

import { decodeCanonicalImport } from '../src/api/playback'

const { mockClient } = vi.hoisted(() => ({
  mockClient: { GET: vi.fn(), POST: vi.fn() },
}))

vi.mock('../src/api/client', () => ({
  createApiClient: () => mockClient,
  errorMessage: () => 'request failed',
}))

const JOB = {
  id: 'job-1',
  project_id: 'project-1',
  import_id: 'import-1',
  job_type: 'canonical_decode',
  state: 'queued',
  stage: null,
  progress_fraction: null,
  progress_detail: null,
  error_code: null,
  error: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('decodeCanonicalImport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockClient.POST.mockResolvedValue({
      response: { ok: true, status: 201 },
      data: JOB,
    })
    mockClient.GET.mockResolvedValue({
      response: { ok: true, status: 200 },
      data: { ...JOB, state: 'completed', progress_fraction: 1 },
    })
  })

  it('creates the canonical decode job and waits for completion', async () => {
    const job = await decodeCanonicalImport('project-1', 'import-1')

    expect(job.state).toBe('completed')
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/jobs',
      expect.objectContaining({
        params: { path: { project_id: 'project-1' } },
        body: { import_id: 'import-1', job_type: 'canonical_decode' },
      }),
    )
    expect(mockClient.GET).toHaveBeenCalledWith(
      '/api/v1/jobs/{job_id}',
      expect.objectContaining({ params: { path: { job_id: 'job-1' } } }),
    )
  })
})
