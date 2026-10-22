import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  completeOpenSession,
  createOpenSession,
  describeOpenError,
  OpenRequestError,
  uploadArchive,
} from '../src/api/open'

const { mockClient, mockSha256 } = vi.hoisted(() => ({
  mockClient: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() },
  mockSha256: vi.fn(async () => 'a'.repeat(64)),
}))

vi.mock('../src/api/client', () => ({
  createApiClient: () => mockClient,
}))

vi.mock('../src/api/uploader', () => ({
  sha256Hex: mockSha256,
}))

vi.mock('../src/auth', () => ({
  getSessionToken: () => 'test-token',
}))

const SESSION_ID = '22222222-2222-4222-8222-222222222222'
const PROJECT_ID = '33333333-3333-4333-8333-333333333333'

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

function sessionPayload() {
  return {
    open_session_id: SESSION_ID,
    chunk_size: 1024,
    max_project_archive_bytes: 900_000,
    state: 'created',
  }
}

function completePayload() {
  return {
    project_id: PROJECT_ID,
    name: 'Song A',
    status: 'ready',
    revision: 5,
  }
}

describe('createOpenSession', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('posts the archive size and maps the session', async () => {
    mockClient.POST.mockResolvedValue(ok(sessionPayload(), 201))
    const session = await createOpenSession('song.basseparate', 500_000)
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/open',
      expect.objectContaining({
        body: {
          filename: 'song.basseparate',
          declared_byte_count: 500_000,
          open_mode: 'new-copy',
        },
      }),
    )
    expect(session).toEqual({
      sessionId: SESSION_ID,
      chunkSize: 1024,
      maxProjectArchiveBytes: 900_000,
    })
  })

  it('carries the server code and details on failure', async () => {
    mockClient.POST.mockResolvedValue(fail(413, 'ARCHIVE_SIZE_LIMIT', 'too large', { limit: 10 }))
    await expect(createOpenSession('song.basseparate', 11)).rejects.toMatchObject({
      code: 'ARCHIVE_SIZE_LIMIT',
      statusCode: 413,
      details: { limit: 10 },
    })
  })
})

describe('uploadArchive', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
    mockClient.PUT.mockReset()
    mockSha256.mockClear()
  })

  it('streams chunks in order and completes the open', async () => {
    mockClient.POST.mockResolvedValueOnce(ok(sessionPayload(), 201)).mockResolvedValueOnce(
      ok(completePayload(), 201),
    )
    mockClient.PUT.mockResolvedValueOnce(
      ok({ offset: 2, chunk_bytes: 2, idempotent_replay: false }),
    )
      .mockResolvedValueOnce(ok({ offset: 4, chunk_bytes: 2, idempotent_replay: false }))
      .mockResolvedValueOnce(ok({ offset: 5, chunk_bytes: 1, idempotent_replay: false }))

    const file = new File([new Uint8Array([1, 2, 3, 4, 5])], 'song.basseparate')
    const onSession = vi.fn()
    const progress: number[] = []
    const onOpening = vi.fn()

    const project = await uploadArchive({
      file,
      chunkSize: 2,
      onSession,
      onProgress: (p) => progress.push(p.bytesUploaded),
      onOpening,
    })

    expect(onSession).toHaveBeenCalledWith(SESSION_ID)
    expect(progress).toEqual([2, 4, 5])
    expect(onOpening).toHaveBeenCalledTimes(1)
    expect(project).toEqual({
      projectId: PROJECT_ID,
      name: 'Song A',
      status: 'ready',
      revision: 5,
    })

    expect(mockClient.PUT).toHaveBeenCalledTimes(3)
    const [, firstOptions] = mockClient.PUT.mock.calls[0]
    expect(firstOptions.params).toEqual({
      path: { session_id: SESSION_ID },
      query: { offset: 0 },
    })
    expect(firstOptions.headers['X-Chunk-SHA256']).toBe('a'.repeat(64))
    const [, thirdOptions] = mockClient.PUT.mock.calls[2]
    expect(thirdOptions.params.query).toEqual({ offset: 4 })
    // The open ran only after all chunks were acknowledged.
    expect(mockClient.POST.mock.calls[1][0]).toBe('/api/v1/projects/open/{session_id}/complete')
  })

  it('stops and reports the failure when a chunk is rejected', async () => {
    mockClient.POST.mockResolvedValueOnce(ok(sessionPayload(), 201))
    mockClient.PUT.mockResolvedValue(fail(409, 'CHUNK_CONFLICT', 'hash mismatch'))

    const file = new File([new Uint8Array([1, 2, 3])], 'song.basseparate')
    await expect(uploadArchive({ file, chunkSize: 2 })).rejects.toMatchObject({
      code: 'CHUNK_CONFLICT',
    })
    expect(mockClient.POST).toHaveBeenCalledTimes(1) // no complete call
  })
})

describe('completeOpenSession', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('maps the opened project', async () => {
    mockClient.POST.mockResolvedValue(ok(completePayload(), 201))
    expect(await completeOpenSession(SESSION_ID)).toEqual({
      projectId: PROJECT_ID,
      name: 'Song A',
      status: 'ready',
      revision: 5,
    })
  })

  it('exposes OPEN_ID_CONFLICT', async () => {
    mockClient.POST.mockResolvedValue(
      fail(409, 'OPEN_ID_CONFLICT', 'already exists', { project_id: PROJECT_ID }),
    )
    await expect(completeOpenSession(SESSION_ID)).rejects.toMatchObject({
      code: 'OPEN_ID_CONFLICT',
      statusCode: 409,
    })
  })
})

describe('describeOpenError', () => {
  it('names a missing archive member', () => {
    const error = new OpenRequestError('ARCHIVE_MEMBER_MISSING', 'missing', 422, {
      missing: ['assets/sha256/abc.pcm'],
    })
    expect(describeOpenError(error)).toContain('assets/sha256/abc.pcm is missing')
  })

  it('explains an ID conflict and a damaged archive', () => {
    expect(describeOpenError(new OpenRequestError('OPEN_ID_CONFLICT', 'x', 409))).toContain(
      'already in the library',
    )
    expect(
      describeOpenError(
        new OpenRequestError('ARCHIVE_MEMBER_CORRUPT', 'x', 422, {
          member: 'project.sqlite',
        }),
      ),
    ).toContain('project.sqlite failed verification')
  })

  it('passes through unknown errors', () => {
    expect(describeOpenError(new Error('boom'))).toBe('boom')
  })
})
