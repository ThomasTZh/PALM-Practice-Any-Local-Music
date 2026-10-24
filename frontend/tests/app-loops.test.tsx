/**
 * App-level practice-loop tests (M2.11, spec §13).
 *
 * Renders the full App against a ready project with saved loops and a
 * fake command backend that applies loop ops to the practice state
 * (mirroring the repository semantics: add appends, set_active_loop
 * selects, set_loop_enabled flips). Asserts the wiring paths:
 *
 * - the practice state's active loop is applied to the transport
 *   (`setLoop` spec + `setLoopEnabled`),
 * - the panel and the `L` shortcut send `set_loop_enabled` (with the
 *   100 ms minimum explained locally, and the typing guard),
 * - "Create from selection" sends `add_loop` + `set_active_loop`, and
 *   the new loop appears in the panel and as a waveform overlay,
 * - a loop boundary drag sends exactly one `update_loop` on release and
 *   the transport follows the new spec.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'

const { mockClient, wf, mockPlayback } = vi.hoisted(() => ({
  mockClient: { GET: vi.fn(), POST: vi.fn() },
  wf: {
    getAssetMetadata: vi.fn(),
    getPeaksManifest: vi.fn(),
    getPeakTile: vi.fn(),
    getAssetPcm: vi.fn(),
    listProjectJobs: vi.fn(),
    createWaveformJob: vi.fn(),
    TileNotReadyError: class TileNotReadyError extends Error {},
    NoWaveformCacheError: class NoWaveformCacheError extends Error {},
    RangeOutOfBoundsError: class RangeOutOfBoundsError extends Error {},
  },
  mockPlayback: {
    createJob: vi.fn(),
    ensurePlaybackTarget: vi.fn(),
    fetchAssetBytes: vi.fn(),
    getSourceInfo: vi.fn(),
    latestCompletedImportId: vi.fn(),
    setMonitoringChannels: vi.fn(),
    waitForJob: vi.fn(),
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

vi.mock('../src/api/waveform', () => wf)
vi.mock('../src/api/playback', () => mockPlayback)

import App from '../src/App'
import { PcmTransport, type TransportLoopSpec } from '../src/playback/transport'
import type { PracticeLoop, PracticeState } from '../src/api/commands'

// --- fixtures ----------------------------------------------------------------

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'
const ASSET_ID = '44444444-4444-4444-4444-444444444444'
const IMPORT_ID = '22222222-2222-2222-2222-222222222222'

const FRAMES = 48_000
const BUCKETS = 750
const CONTENT_WIDTH = 750

const WORKING_STATE = {
  selection: null,
  viewport: null,
  channel_display: { linked: true, scales: [] },
  monitoring_volume: 1.0,
  last_position_frames: 0,
  follow_playhead: true,
}

const READY_PROJECT = {
  schema_version: 1,
  id: PROJECT_ID,
  name: 'Ready Project',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  revision: 1,
  source_asset_id: ASSET_ID,
  canonical_asset_id: ASSET_ID,
  sample_rate: 48000,
  duration_samples: FRAMES,
  status: 'ready',
}

const SOURCE_INFO_STEREO = {
  sampleRate: 48000,
  durationFrames: FRAMES,
  durationSeconds: 1.0,
  channelCount: 2,
  channelLayout: 'stereo',
  channelLabels: ['L', 'R'],
  monitoring: null,
  playbackRates: [],
}

function makeLoop(overrides: Partial<PracticeLoop> = {}): PracticeLoop {
  return {
    id: 'loop-1',
    name: 'Verse',
    start_frames: 4800,
    end_frames: 24_480,
    color: '#f59e0b',
    repeat_count: null,
    boundary_fade: true,
    anchor_mode: 'source',
    unresolved: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makePracticeState(overrides: Partial<PracticeState> = {}): PracticeState {
  return {
    active_loop_id: null,
    active_result_set_id: null,
    loop_enabled: false,
    loops: [],
    master_gain: 1.0,
    monitoring_limiter: true,
    playback_mode: 'original',
    playback_speed: 1.0,
    tracks: {},
    ...overrides,
  }
}

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

// --- canvas / ResizeObserver stubs (mirrors app-restore.test.tsx) ------------

class Stub2DContext {
  fillStyle = ''
  strokeStyle = ''
  lineWidth = 1
  font = ''
  textBaseline = ''
  rects: number[][] = []
  clears = 0
  strokes = 0
  texts: string[] = []
  setTransform(): void {}
  fillRect(x: number, y: number, w: number, h: number): void {
    this.rects.push([x, y, w, h])
  }
  clearRect(): void {
    this.rects = []
    this.clears += 1
  }
  beginPath(): void {}
  moveTo(): void {}
  lineTo(): void {}
  stroke(): void {
    this.strokes += 1
  }
  strokeRect(x: number, y: number, w: number, h: number): void {
    this.rects.push([x, y, w, h])
  }
  fill(): void {}
  save(): void {}
  restore(): void {}
  translate(): void {}
  fillText(text: string): void {
    this.texts.push(text)
  }
}

type StubCanvas = HTMLCanvasElement & { __stubCtx?: Stub2DContext }

/** Fresh per test (afterEach restores all spies). */
function stubCanvasContext(): void {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: StubCanvas,
    kind: string,
  ) {
    if (kind !== '2d') return null
    return (this.__stubCtx ??= new Stub2DContext()) as unknown as CanvasRenderingContext2D
  })
}

function ctxOf(canvas: Element): Stub2DContext {
  const ctx = (canvas as StubCanvas).__stubCtx
  expect(ctx).toBeDefined()
  return ctx as Stub2DContext
}

function canvasById(id: string): HTMLCanvasElement {
  const el = document.querySelector(`canvas[data-id="${id}"]`)
  expect(el).not.toBeNull()
  return el as HTMLCanvasElement
}

class MockResizeObserver {
  static instances: MockResizeObserver[] = []
  callback: ResizeObserverCallback
  observed: Element[] = []
  constructor(cb: ResizeObserverCallback) {
    this.callback = cb
    MockResizeObserver.instances.push(this)
  }
  observe(el: Element): void {
    this.observed.push(el)
  }
  unobserve(): void {}
  disconnect(): void {}
  fire(width: number): void {
    this.callback(
      [{ contentRect: { width } } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    )
  }
}

vi.stubGlobal('ResizeObserver', MockResizeObserver)
Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })

function makeManifest() {
  return {
    cache_version: 1,
    source_hash: 'a'.repeat(64),
    sample_rate: 48_000,
    frame_count: FRAMES,
    channel_count: 2,
    base_bucket_frames: 64,
    aggregation: 4,
    levels: [
      {
        bucket_frame_count: 64,
        bucket_count: BUCKETS,
        tile_count: 1,
        final_tile_buckets: BUCKETS,
      },
    ],
    available_tiles: {},
    final: true,
  }
}

function tileBytes() {
  const bytes = new ArrayBuffer(BUCKETS * 2 * 8)
  const view = new DataView(bytes)
  for (let b = 0; b < BUCKETS; b++) {
    for (let c = 0; c < 2; c++) {
      const off = (b * 2 + c) * 8
      view.setFloat32(off, -0.25, true)
      view.setFloat32(off + 4, 0.75, true)
    }
  }
  return bytes
}

function mockReady(): void {
  wf.getAssetMetadata.mockResolvedValue({ waveform: { final: true, frame_count: FRAMES } })
  wf.getPeaksManifest.mockResolvedValue(makeManifest())
  wf.getPeakTile.mockImplementation((_asset: string, level: number, tile: number) =>
    Promise.resolve({
      bytes: tileBytes(),
      level,
      tile,
      bucketFrameCount: 64,
      tileBuckets: BUCKETS,
    }),
  )
  wf.getAssetPcm.mockImplementation((_asset: string, startFrame: number, count: number) => {
    const frames = Math.min(count, Math.max(0, FRAMES - startFrame))
    const bytes = new ArrayBuffer(frames * 2 * 8)
    const view = new DataView(bytes)
    for (let f = 0; f < frames; f++) {
      for (let c = 0; c < 2; c++) {
        view.setFloat32((f * 2 + c) * 4, -0.25, true)
        view.setFloat32((f * 2 + c) * 4 + 4, 0.75, true)
      }
    }
    return Promise.resolve({
      bytes,
      startFrame,
      frameCount: frames,
      eof: startFrame + frames >= FRAMES,
      sampleRate: 48_000,
      channelCount: 2,
      contentHash: '',
    })
  })
}

// --- fake command backend ----------------------------------------------------

interface CommandBody {
  base_revision?: number
  op?: { type: string } & Record<string, unknown>
}

const commandCalls: CommandBody[] = []

function commandBodies(opType: string): CommandBody[] {
  return commandCalls.filter((c) => c.op?.type === opType)
}

/** Apply a loop op to the practice state (mirrors the repository). */
function applyOp(ps: PracticeState, op: { type: string } & Record<string, unknown>): PracticeState {
  const loops: PracticeLoop[] = ps.loops ?? []
  switch (op.type) {
    case 'add_loop': {
      const n = loops.length + 1
      const loop = makeLoop({
        id: `loop-${n}`,
        name: `Loop ${n}`,
        start_frames: op.start_frames as number,
        end_frames: op.end_frames as number,
        repeat_count: (op.repeat_count as number | null | undefined) ?? null,
        boundary_fade: (op.boundary_fade as boolean | undefined) ?? true,
      })
      return { ...ps, loops: [...loops, loop] }
    }
    case 'set_active_loop': {
      const id = (op.loop_id as string | null | undefined) ?? null
      return id === null
        ? { ...ps, active_loop_id: null, loop_enabled: false }
        : { ...ps, active_loop_id: id }
    }
    case 'set_loop_enabled':
      return { ...ps, loop_enabled: op.enabled as boolean }
    case 'update_loop': {
      return {
        ...ps,
        loops: loops.map((l) => {
          if (l.id !== op.loop_id) return l
          const next: PracticeLoop = { ...l }
          if (typeof op.name === 'string') next.name = op.name
          if (typeof op.color === 'string') next.color = op.color
          if (typeof op.start_frames === 'number') next.start_frames = op.start_frames
          if (typeof op.end_frames === 'number') next.end_frames = op.end_frames
          if (typeof op.boundary_fade === 'boolean') next.boundary_fade = op.boundary_fade
          if ('repeat_count' in op) {
            next.repeat_count = (op.repeat_count as number | null | undefined) ?? null
          }
          return next
        }),
      }
    }
    default:
      return ps
  }
}

/**
 * Wire the snapshot GET and the command POST against `state.ps`.
 * `workingState` overrides the restored working state (selection etc.);
 * `state.revision` advances with every applied command.
 */
function mockBackend(state: { ps: PracticeState }, workingState: unknown = WORKING_STATE): void {
  mockClient.GET.mockImplementation((path: string) => {
    switch (path) {
      case '/api/v1/system':
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      case '/api/v1/projects':
        return Promise.resolve(ok({ projects: [READY_PROJECT] }))
      case '/api/v1/projects/{project_id}':
        return Promise.resolve(
          ok({
            ...READY_PROJECT,
            duration_frames: FRAMES,
            markers: [],
            working_state: workingState,
            practice_state: state.ps,
            can_undo: false,
            can_redo: false,
          }),
        )
      case '/api/v1/projects/{project_id}/source-info':
        return Promise.resolve(ok(SOURCE_INFO_STEREO))
      case '/api/v1/projects/{project_id}/imports':
        return Promise.resolve(ok({ imports: [] }))
      default:
        return Promise.resolve(ok({}))
    }
  })
  mockClient.POST.mockImplementation((path: string, opts: { body?: unknown }) => {
    if (typeof path === 'string' && path.endsWith('/commands')) {
      const body = opts.body as CommandBody | undefined
      commandCalls.push(body ?? {})
      const op = body?.op
      if (op) state.ps = applyOp(state.ps, op)
      const base = body?.base_revision ?? 0
      return Promise.resolve(
        ok({
          revision: base + 1,
          markers: [],
          working_state: workingState,
          practice_state: state.ps,
          can_undo: true,
          can_redo: false,
        }),
      )
    }
    return Promise.resolve(ok({}))
  })
}

// --- helpers -----------------------------------------------------------------

let setLoopSpy: MockInstance
let setLoopEnabledSpy: MockInstance

/** Render the App and open the ready project from the list. */
async function openReadyProject(): Promise<void> {
  render(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Ready Project/ }))
}

/** Give the editor a width and wait until the waveform lanes are painted. */
async function readyEditor(): Promise<void> {
  await waitFor(() => {
    expect(MockResizeObserver.instances.length).toBeGreaterThan(0)
  })
  act(() => {
    for (const ro of MockResizeObserver.instances) ro.fire(CONTENT_WIDTH)
  })
  await waitFor(() => {
    expect(ctxOf(canvasById('lane:0:waveform')).rects.length).toBeGreaterThan(0)
  })
}

function hitbox(): HTMLElement {
  return document.querySelector('.wave-lane-hitarea') as HTMLElement
}

function pointer(type: string, el: Element, clientX: number): void {
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX }))
  })
}

function pressL(el: Element = document.body): void {
  fireEvent.keyDown(el, { key: 'l' })
}

beforeEach(() => {
  vi.clearAllMocks()
  commandCalls.length = 0
  MockResizeObserver.instances = []
  sessionStorage.clear()
  sessionStorage.setItem('basseparate.sessionToken', 'test-token')
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  wf.listProjectJobs.mockResolvedValue([])
  wf.createWaveformJob.mockResolvedValue({ id: 'job-1' })
  mockPlayback.latestCompletedImportId.mockResolvedValue(IMPORT_ID)
  mockPlayback.getSourceInfo.mockResolvedValue(SOURCE_INFO_STEREO)
  mockReady()
  stubCanvasContext()
  setLoopSpy = vi.spyOn(PcmTransport.prototype, 'setLoop')
  setLoopEnabledSpy = vi.spyOn(PcmTransport.prototype, 'setLoopEnabled')
  // The playhead rAF loop is not under test here.
  window.requestAnimationFrame = () => 0
  window.cancelAnimationFrame = () => {}
})

afterEach(() => {
  vi.restoreAllMocks()
  window.requestAnimationFrame = realRaf
  window.cancelAnimationFrame = realCaf
})

// jsdom's requestAnimationFrame is real-time; capture the originals before
// any test replaces them (the playhead loop is not stepped in these tests).
const realRaf = window.requestAnimationFrame
const realCaf = window.cancelAnimationFrame

// --- tests -------------------------------------------------------------------

describe('app practice loops (M2.11 §13)', () => {
  it('applies the restored active loop to the transport', async () => {
    const state = {
      ps: makePracticeState({
        active_loop_id: 'loop-1',
        loop_enabled: true,
        loops: [makeLoop()],
      }),
    }
    mockBackend(state)
    await openReadyProject()

    const spec: TransportLoopSpec = {
      startFrame: 4800,
      endFrame: 24_480,
      repeatCount: null,
      boundaryFade: true,
    }
    await waitFor(() => expect(setLoopSpy).toHaveBeenCalledWith(spec))
    await waitFor(() => expect(setLoopEnabledSpy).toHaveBeenCalledWith(true))
  })

  it('toggles looping from the checkbox and the L key', async () => {
    const state = {
      ps: makePracticeState({ active_loop_id: 'loop-1', loops: [makeLoop()] }),
    }
    mockBackend(state)
    await openReadyProject()
    await screen.findByLabelText('Loop name')
    const checkbox = screen.getByLabelText('Looping')
    await waitFor(() => expect(checkbox).toBeEnabled())

    const user = userEvent.setup()
    await user.click(checkbox)
    await waitFor(() =>
      expect(commandBodies('set_loop_enabled').some((b) => b.op?.enabled === true)).toBe(true),
    )
    await waitFor(() => expect(setLoopEnabledSpy).toHaveBeenCalledWith(true))

    // `L` disables it again.
    pressL()
    await waitFor(() =>
      expect(commandBodies('set_loop_enabled').some((b) => b.op?.enabled === false)).toBe(true),
    )
    await waitFor(() => expect(setLoopEnabledSpy).toHaveBeenCalledWith(false))
  })

  it('ignores L while typing in an input', async () => {
    const state = {
      ps: makePracticeState({ active_loop_id: 'loop-1', loops: [makeLoop()] }),
    }
    mockBackend(state)
    await openReadyProject()
    const name = await screen.findByLabelText('Loop name')

    pressL(name)
    expect(commandBodies('set_loop_enabled')).toHaveLength(0)

    // Outside a field the same key toggles.
    pressL(document.body)
    await waitFor(() => expect(commandBodies('set_loop_enabled')).toHaveLength(1))
    expect(commandBodies('set_loop_enabled')[0].op).toMatchObject({ enabled: true })
  })

  it('is a no-op without an active loop and gates the checkbox', async () => {
    const state = { ps: makePracticeState({ loops: [makeLoop()] }) }
    mockBackend(state)
    await openReadyProject()
    await screen.findByLabelText('Loop name')

    expect(screen.getByLabelText('Looping')).toBeDisabled()
    pressL()
    expect(commandBodies('set_loop_enabled')).toHaveLength(0)
  })

  it('explains the 100 ms minimum instead of enabling a short loop', async () => {
    const state = {
      ps: makePracticeState({
        active_loop_id: 'loop-1',
        loops: [makeLoop({ start_frames: 0, end_frames: 4000 })], // 83 ms
      }),
    }
    mockBackend(state)
    await openReadyProject()
    await screen.findByLabelText('Loop name')
    const checkbox = screen.getByLabelText('Looping')
    await waitFor(() => expect(checkbox).toBeEnabled())

    const user = userEvent.setup()
    await user.click(checkbox)
    expect(await screen.findByRole('alert')).toHaveTextContent('shorter than 100 ms')
    expect(commandBodies('set_loop_enabled')).toHaveLength(0)
    // The active row carries the same explanation (spec §13.3.4).
    expect(screen.getByText(/cannot repeat/)).toBeInTheDocument()
  })

  it('creates a loop from the restored selection, activates it, and draws it', async () => {
    const state = { ps: makePracticeState() }
    mockBackend(state, {
      ...WORKING_STATE,
      selection: { start: 9600, end: 19_200 },
    })
    await openReadyProject()
    const create = await screen.findByRole('button', { name: 'Create from selection' })
    await waitFor(() => expect(create).toBeEnabled())
    await readyEditor()

    const user = userEvent.setup()
    await user.click(create)
    await waitFor(() => expect(commandBodies('add_loop')).toHaveLength(1))
    expect(commandBodies('add_loop')[0].op).toMatchObject({
      start_frames: 9600,
      end_frames: 19_200,
      boundary_fade: true,
    })
    await waitFor(() => expect(commandBodies('set_active_loop')).toHaveLength(1))
    expect(commandBodies('set_active_loop')[0].op).toMatchObject({ loop_id: 'loop-1' })

    // The new loop shows in the panel and as the waveform overlay:
    // [9600, 19200) at the fit view (64 frames/px) -> x 150..300. Since
    // `2e1c2f0` the selection is drawn first and the active loop last,
    // with a 2 px top border, boundary handles, and a top-center grip.
    expect(await screen.findByDisplayValue('Loop 1')).toBeInTheDocument()
    const sel = ctxOf(canvasById('lane:0:selection'))
    await waitFor(() =>
      expect(sel.rects).toEqual([
        [150, 0, 150, 48], // restored selection tint
        [148.5, 0, 3, 48], // selection handle left
        [298.5, 0, 3, 48], // selection handle right
        [150, 0, 150, 48], // active loop tint, drawn above the selection
        [148.5, 0, 153, 2], // loop top border
        [148.5, 0, 3, 48], // loop handle left
        [298.5, 0, 3, 48], // loop handle right
        [215, 2, 20, 4], // top-center grip
      ]),
    )
  })

  it('sends one update_loop when a loop boundary drag is released', async () => {
    const state = {
      ps: makePracticeState({ active_loop_id: 'loop-1', loops: [makeLoop()] }),
    }
    mockBackend(state)
    await openReadyProject()
    await readyEditor()
    // Wait for the restored loop to reach the transport (creation seed).
    await waitFor(() => expect(setLoopSpy).toHaveBeenCalled())
    // ... and for its overlay on the selection layer.
    const sel = ctxOf(canvasById('lane:0:selection'))
    await waitFor(() => expect(sel.rects.length).toBeGreaterThan(0))

    // The end handle of [4800, 24480) sits at x 382.5; drag to x 400
    // (frame 25600) and release: exactly one command.
    const hit = hitbox()
    pointer('pointerdown', hit, 382.5)
    pointer('pointermove', hit, 400)
    expect(commandBodies('update_loop')).toHaveLength(0)
    pointer('pointerup', hit, 400)
    await waitFor(() => expect(commandBodies('update_loop')).toHaveLength(1))
    expect(commandBodies('update_loop')[0].op).toMatchObject({
      loop_id: 'loop-1',
      start_frames: 4800,
      end_frames: 25_600,
    })
    // The transport follows the edited spec.
    await waitFor(() =>
      expect(setLoopSpy).toHaveBeenCalledWith({
        startFrame: 4800,
        endFrame: 25_600,
        repeatCount: null,
        boundaryFade: true,
      }),
    )
  })
})
