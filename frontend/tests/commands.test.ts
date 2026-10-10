import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_WORKING_STATE,
  getProjectSnapshot,
  redoCommand,
  sendCommand,
  StaleRevisionError,
  undoCommand,
  type CommandOp,
} from '../src/api/commands'

const { mockClient } = vi.hoisted(() => ({
  mockClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PUT: vi.fn(),
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

const ADD_MARKER: CommandOp = {
  type: 'add_marker',
  position_frames: 100,
  label: 'Marker',
  color: '#e11d48',
}

function resultPayload(overrides: Record<string, unknown> = {}) {
  return {
    revision: 1,
    markers: [
      {
        id: '22222222-2222-4222-8222-222222222222',
        project_id: PROJECT_ID,
        position_frames: 100,
        label: 'Marker',
        color: '#e11d48',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    working_state: { ...DEFAULT_WORKING_STATE },
    can_undo: true,
    can_redo: false,
    ...overrides,
  }
}

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

function fail(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return {
    response: { ok: false, status },
    error: { error: { code, message, details } },
    data: undefined,
  }
}

describe('sendCommand', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('sends command_id, idempotency_key, and base_revision', async () => {
    mockClient.POST.mockResolvedValue(ok(resultPayload()))
    await sendCommand(PROJECT_ID, 3, ADD_MARKER)
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/commands',
      expect.objectContaining({
        params: { path: { project_id: PROJECT_ID } },
        body: expect.objectContaining({ base_revision: 3, op: ADD_MARKER }),
      }),
    )
    const body = mockClient.POST.mock.calls[0][1].body
    expect(body.command_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    )
    expect(body.idempotency_key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    )
    expect(body.command_id).not.toBe(body.idempotency_key)
  })

  it('maps the resulting state to camelCase', async () => {
    mockClient.POST.mockResolvedValue(ok(resultPayload({ revision: 7 })))
    const result = await sendCommand(PROJECT_ID, 6, ADD_MARKER)
    expect(result.revision).toBe(7)
    expect(result.markers).toHaveLength(1)
    expect(result.markers[0].position_frames).toBe(100)
    expect(result.workingState.follow_playhead).toBe(true)
    expect(result.canUndo).toBe(true)
    expect(result.canRedo).toBe(false)
  })

  it('throws StaleRevisionError with the current revision on 409 STALE_REVISION', async () => {
    mockClient.POST.mockResolvedValue(fail(409, 'STALE_REVISION', 'stale', { current_revision: 9 }))
    const err = await sendCommand(PROJECT_ID, 3, ADD_MARKER).catch((e) => e)
    expect(err).toBeInstanceOf(StaleRevisionError)
    expect((err as StaleRevisionError).currentRevision).toBe(9)
  })

  it('throws a plain error on other failures', async () => {
    mockClient.POST.mockResolvedValue(fail(422, 'INVALID_COMMAND', 'bad op'))
    await expect(sendCommand(PROJECT_ID, 0, ADD_MARKER)).rejects.toThrow('bad op')
  })
})

describe('undoCommand / redoCommand', () => {
  beforeEach(() => {
    mockClient.POST.mockReset()
  })

  it('posts the base revision to /undo', async () => {
    mockClient.POST.mockResolvedValue(ok(resultPayload({ revision: 2, can_redo: true })))
    const result = await undoCommand(PROJECT_ID, 1)
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/undo',
      expect.objectContaining({ body: { base_revision: 1 } }),
    )
    expect(result.canRedo).toBe(true)
  })

  it('posts the base revision to /redo', async () => {
    mockClient.POST.mockResolvedValue(ok(resultPayload({ revision: 3, can_undo: true })))
    const result = await redoCommand(PROJECT_ID, 2)
    expect(mockClient.POST).toHaveBeenCalledWith(
      '/api/v1/projects/{project_id}/redo',
      expect.objectContaining({ body: { base_revision: 2 } }),
    )
    expect(result.canUndo).toBe(true)
  })

  it('maps a stale undo to StaleRevisionError', async () => {
    mockClient.POST.mockResolvedValue(fail(409, 'STALE_REVISION', 'stale', { current_revision: 4 }))
    const err = await undoCommand(PROJECT_ID, 1).catch((e) => e)
    expect(err).toBeInstanceOf(StaleRevisionError)
    expect((err as StaleRevisionError).currentRevision).toBe(4)
  })
})

describe('getProjectSnapshot', () => {
  it('maps the project to a snapshot', async () => {
    mockClient.GET.mockResolvedValue(
      ok({
        id: PROJECT_ID,
        name: 'Test',
        status: 'ready',
        revision: 5,
        markers: resultPayload().markers,
        working_state: { ...DEFAULT_WORKING_STATE, monitoring_volume: 1.5 },
        can_undo: true,
        can_redo: true,
        sample_rate: 48000,
        duration_frames: 100_000,
      }),
    )
    const snap = await getProjectSnapshot(PROJECT_ID)
    expect(snap.status).toBe('ready')
    expect(snap.revision).toBe(5)
    expect(snap.markers).toHaveLength(1)
    expect(snap.workingState.monitoring_volume).toBe(1.5)
    expect(snap.canUndo).toBe(true)
    expect(snap.canRedo).toBe(true)
    expect(snap.sampleRate).toBe(48000)
    expect(snap.durationFrames).toBe(100_000)
  })
})
