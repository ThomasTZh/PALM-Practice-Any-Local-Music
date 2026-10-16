import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useProjectCommands } from '../src/projects/useProjectCommands'

const m = vi.hoisted(() => {
  class StaleRevisionError extends Error {
    readonly currentRevision: number

    constructor(currentRevision: number) {
      super(`The project was modified elsewhere (current revision ${currentRevision})`)
      this.name = 'StaleRevisionError'
      this.currentRevision = currentRevision
    }
  }
  const DEFAULT_WORKING_STATE = {
    selection: null,
    viewport: null,
    channel_display: { linked: true, scales: [] },
    monitoring_volume: 1.0,
    last_position_frames: 0,
    follow_playhead: true,
  }
  return {
    StaleRevisionError,
    DEFAULT_WORKING_STATE,
    sendCommand: vi.fn(),
    undoCommand: vi.fn(),
    redoCommand: vi.fn(),
    getProjectSnapshot: vi.fn(),
  }
})

vi.mock('../src/api/commands', () => ({
  StaleRevisionError: m.StaleRevisionError,
  DEFAULT_WORKING_STATE: m.DEFAULT_WORKING_STATE,
  sendCommand: m.sendCommand,
  undoCommand: m.undoCommand,
  redoCommand: m.redoCommand,
  getProjectSnapshot: m.getProjectSnapshot,
}))

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'

// The generated types mark defaulted props (label, color) as required.
function addMarkerOp(positionFrames: number) {
  return {
    type: 'add_marker',
    position_frames: positionFrames,
    label: 'Marker',
    color: '#e11d48',
  } as const
}

const VIEWPORT_OP = {
  type: 'set_viewport',
  viewport: { start_frame: 10, frames_per_css_pixel: 2 },
} as const

const PRACTICE_STATE = {
  loop_enabled: false,
  master_gain: 1.0,
  monitoring_limiter: true,
  playback_mode: 'original',
  playback_speed: 1.0,
  tracks: {},
}

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    status: 'ready',
    revision: 0,
    markers: [],
    workingState: { ...m.DEFAULT_WORKING_STATE },
    practiceState: PRACTICE_STATE,
    canUndo: false,
    canRedo: false,
    sampleRate: 48000,
    durationFrames: 100_000,
    ...overrides,
  }
}

function commandResult(revision: number, overrides: Record<string, unknown> = {}) {
  return {
    revision,
    markers: [],
    workingState: { ...m.DEFAULT_WORKING_STATE },
    practiceState: PRACTICE_STATE,
    canUndo: revision > 0,
    canRedo: false,
    ...overrides,
  }
}

async function loadHook(projectId: string = PROJECT_ID) {
  const hook = renderHook(() => useProjectCommands(projectId))
  // Fake timers are active: flush microtasks so the async load settles.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(hook.result.current.loaded).toBe(true)
  return hook
}

describe('useProjectCommands', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    m.getProjectSnapshot.mockResolvedValue(snapshot())
    m.sendCommand.mockImplementation(async (_id: string, base: number) => commandResult(base + 1))
    m.undoCommand.mockImplementation(async (_id: string, base: number) => commandResult(base + 1))
    m.redoCommand.mockImplementation(async (_id: string, base: number) => commandResult(base + 1))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads the project snapshot on mount', async () => {
    m.getProjectSnapshot.mockResolvedValueOnce(
      snapshot({
        revision: 4,
        markers: [
          {
            id: '33333333-3333-4333-8333-333333333333',
            project_id: PROJECT_ID,
            position_frames: 5,
            label: 'Intro',
            color: '#e11d48',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
        workingState: { ...m.DEFAULT_WORKING_STATE, monitoring_volume: 1.25 },
        canUndo: true,
      }),
    )
    const { result } = await loadHook()
    expect(result.current.revision).toBe(4)
    expect(result.current.markers).toHaveLength(1)
    expect(result.current.markers[0].label).toBe('Intro')
    expect(result.current.workingState.monitoring_volume).toBe(1.25)
    expect(result.current.practiceState?.playback_mode).toBe('original')
    expect(result.current.canUndo).toBe(true)
    expect(result.current.canRedo).toBe(false)
  })

  it('tracks practiceState from command results', async () => {
    const { result } = await loadHook()
    expect(result.current.practiceState?.monitoring_limiter).toBe(true)

    m.sendCommand.mockResolvedValueOnce(
      commandResult(1, {
        practiceState: { ...PRACTICE_STATE, monitoring_limiter: false, master_gain: 2.0 },
      }),
    )
    await act(async () => {
      await result.current.send({ type: 'set_monitoring_limiter', enabled: false })
    })
    expect(result.current.practiceState?.monitoring_limiter).toBe(false)
    expect(result.current.practiceState?.master_gain).toBe(2.0)
  })

  it('serializes concurrent sends: one in flight, base revisions chain', async () => {
    let inFlight = 0
    let maxInFlight = 0
    m.sendCommand.mockImplementation(async (_id: string, base: number) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      // Yield a microtask (no timers: fake timers are active here).
      await new Promise<void>((resolve) => {
        queueMicrotask(resolve)
      })
      inFlight -= 1
      return commandResult(base + 1)
    })
    const { result } = await loadHook()
    const [a, b] = await act(async () => {
      return Promise.all([result.current.send(addMarkerOp(1)), result.current.send(addMarkerOp(2))])
    })
    expect(maxInFlight).toBe(1)
    expect(a?.revision).toBe(1)
    expect(b?.revision).toBe(2)
    // The second send chained on the first result's revision.
    expect(m.sendCommand.mock.calls[0][1]).toBe(0)
    expect(m.sendCommand.mock.calls[1][1]).toBe(1)
    expect(result.current.revision).toBe(2)
  })

  it('debounces view ops: one send per type after ~1 s of quiet, last op wins', async () => {
    const { result } = await loadHook()
    act(() => {
      result.current.scheduleView({
        type: 'set_viewport',
        viewport: { start_frame: 0, frames_per_css_pixel: 1 },
      } as never)
      result.current.scheduleView({
        type: 'set_viewport',
        viewport: { start_frame: 5, frames_per_css_pixel: 1 },
      } as never)
      result.current.scheduleView(VIEWPORT_OP as never)
    })
    expect(m.sendCommand).not.toHaveBeenCalled()
    expect(result.current.armedTypes).toEqual(['set_viewport'])
    expect(result.current.pending).toBe(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999)
    })
    expect(m.sendCommand).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(1)
    expect(m.sendCommand.mock.calls[0][2]).toEqual(VIEWPORT_OP)
    expect(result.current.armedTypes).toEqual([])
    expect(result.current.pending).toBe(false)
  })

  it('flush sends armed debounced ops and awaits the queue', async () => {
    const { result } = await loadHook()
    act(() => {
      result.current.scheduleView(VIEWPORT_OP as never)
      result.current.scheduleView({ type: 'set_follow_playhead', follow_playhead: false } as never)
    })
    await act(async () => {
      await result.current.flush()
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(2)
    const sent = m.sendCommand.mock.calls.map((call) => call[2])
    expect(sent).toContainEqual(VIEWPORT_OP)
    expect(sent).toContainEqual({ type: 'set_follow_playhead', follow_playhead: false })
    expect(result.current.armedTypes).toEqual([])
  })

  it('sends set_position immediately on pause, at most every 5 s while playing', async () => {
    const { result } = await loadHook()
    await act(async () => {
      result.current.notePosition(100, false)
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(1)
    expect(m.sendCommand.mock.calls[0][2]).toEqual({ type: 'set_position', position_frames: 100 })

    act(() => {
      vi.advanceTimersByTime(1000)
      result.current.notePosition(200, true)
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(1)

    await act(async () => {
      vi.advanceTimersByTime(4000)
      result.current.notePosition(300, true)
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(2)
    expect(m.sendCommand.mock.calls[1][2]).toEqual({ type: 'set_position', position_frames: 300 })
  })

  it('undo and redo use the current revision as base', async () => {
    const { result } = await loadHook()
    await act(async () => {
      await result.current.send(addMarkerOp(1))
    })
    expect(result.current.revision).toBe(1)
    await act(async () => {
      await result.current.undo()
    })
    expect(m.undoCommand).toHaveBeenCalledWith(PROJECT_ID, 1)
    await act(async () => {
      await result.current.redo()
    })
    expect(m.redoCommand).toHaveBeenCalledWith(PROJECT_ID, 2)
    expect(result.current.revision).toBe(3)
  })

  it('resyncs on a stale revision: refetch, resync state, surface notice', async () => {
    m.sendCommand.mockRejectedValueOnce(new m.StaleRevisionError(9))
    m.getProjectSnapshot.mockResolvedValueOnce(snapshot({ revision: 0 })).mockResolvedValueOnce(
      snapshot({
        revision: 9,
        markers: [
          {
            id: '44444444-4444-4444-8444-444444444444',
            project_id: PROJECT_ID,
            position_frames: 77,
            label: 'Elsewhere',
            color: '#112233',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
      }),
    )
    const { result } = await loadHook()
    let sent: unknown
    await act(async () => {
      sent = await result.current.send(addMarkerOp(1))
    })
    expect(sent).toBeNull()
    expect(result.current.revision).toBe(9)
    expect(result.current.markers).toHaveLength(1)
    expect(result.current.markers[0].label).toBe('Elsewhere')
    expect(result.current.staleNotice).toBe('Project changed elsewhere — reloaded.')
    act(() => {
      result.current.clearStaleNotice()
    })
    expect(result.current.staleNotice).toBeNull()
  })

  it('drops armed view ops during a stale resync', async () => {
    m.sendCommand.mockRejectedValueOnce(new m.StaleRevisionError(2))
    m.getProjectSnapshot
      .mockResolvedValueOnce(snapshot({ revision: 0 }))
      .mockResolvedValueOnce(snapshot({ revision: 2 }))
    const { result } = await loadHook()
    act(() => {
      result.current.scheduleView(VIEWPORT_OP as never)
    })
    expect(result.current.armedTypes).toEqual(['set_viewport'])
    await act(async () => {
      await result.current.send(addMarkerOp(1))
    })
    expect(result.current.armedTypes).toEqual([])
    // After the queue drains, no debounced send follows.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(m.sendCommand).toHaveBeenCalledTimes(1)
  })
})
