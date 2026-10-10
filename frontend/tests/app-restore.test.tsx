/**
 * App-level restore + autosave tests (M1.15 §17.5/§17.6).
 *
 * Renders the full App with a ready project that has a saved working
 * state, and asserts:
 * - the editor restores viewport / selection / channel display / follow
 * - the panel seeds the monitoring volume and parks the playhead
 * - view changes are debounced and autosaved as commands
 * - the pending chip and the stale-resync notice surface
 *
 * The waveform / canvas / ResizeObserver / rAF infrastructure mirrors
 * WaveformEditor.test.tsx (real `useWaveform`, mocked `api/waveform`);
 * the client and playback modules are mocked the way app.test.tsx and
 * playback-panel.test.tsx do.
 */

import { act, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

// --- fixtures ----------------------------------------------------------------

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'
const ASSET_ID = '44444444-4444-4444-4444-444444444444'
const IMPORT_ID = '22222222-2222-2222-2222-222222222222'

/** 1 s of 48 kHz stereo: 750 buckets at level 0 (64 frames/bucket), 1 tile. */
const FRAMES = 48_000
const BUCKETS = 750
/** 750 CSS px means exactly 64 frames/px -> peak path at the fit view. */
const CONTENT_WIDTH = 750

const WORKING_STATE = {
  selection: { start: 9600, end: 19200 },
  viewport: { start_frame: 4800, frames_per_css_pixel: 6.4 },
  channel_display: { linked: false, scales: [2, 8] },
  monitoring_volume: 1.5,
  last_position_frames: 9600,
  follow_playhead: false,
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
  duration_samples: 48000,
  status: 'ready',
}

const SNAPSHOT = {
  ...READY_PROJECT,
  duration_frames: 48000,
  markers: [],
  working_state: WORKING_STATE,
  can_undo: false,
  can_redo: false,
}

// The mocked playback module returns the already-mapped camelCase types.
const SOURCE_INFO_STEREO = {
  sampleRate: 48000,
  durationFrames: 48000,
  durationSeconds: 1.0,
  channelCount: 2,
  channelLayout: 'stereo',
  channelLabels: ['L', 'R'],
  monitoring: null,
  playbackRates: [],
}

const PLAYBACK_TARGET = {
  assetId: ASSET_ID,
  role: 'canonical',
  sampleRate: 48000,
  channelCount: 2,
  frameCount: 48000,
  byteCount: 384000,
  durationSeconds: 1.0,
}

function ok<T>(data: T) {
  return { response: { ok: true, status: 200 }, data }
}

// --- canvas / ResizeObserver / rAF stubs (mirrors WaveformEditor.test.tsx) ---

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

/** f32le tile bytes: (bucket, channel, [min, max]) per bucket. */
function tileBytes(min = -0.25, max = 0.75) {
  const bytes = new ArrayBuffer(BUCKETS * 2 * 8)
  const view = new DataView(bytes)
  for (let b = 0; b < BUCKETS; b++) {
    for (let c = 0; c < 2; c++) {
      const off = (b * 2 + c) * 8
      view.setFloat32(off, min, true)
      view.setFloat32(off + 4, max, true)
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
    // 2 channels x 2 floats (min/max pair layout) x 4 bytes per frame.
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

// --- helpers -----------------------------------------------------------------

interface CommandBody {
  base_revision?: number
  op?: { type: string } & Record<string, unknown>
}

interface CommandCall {
  path: string
  body: CommandBody | undefined
}

const commandCalls: CommandCall[] = []

function commandBodies(opType: string): CommandBody[] {
  return commandCalls.filter((c) => c.body?.op?.type === opType).map((c) => c.body as CommandBody)
}

/** Render the App and open the ready project from the list. */
async function openReadyProject(): Promise<void> {
  render(<App />)
  const user = userEvent.setup()
  // The link's accessible name includes the status span ("… Ready").
  await user.click(await screen.findByRole('button', { name: /Ready Project/ }))
}

/** Give the editor a width and wait until the waveform lanes are painted. */
async function readyEditor(): Promise<void> {
  // The editor mounts after the click; wait for its ResizeObserver before
  // firing a width (the mock observer does not fire on observe).
  await waitFor(() => {
    expect(MockResizeObserver.instances.length).toBeGreaterThan(0)
  })
  act(() => {
    for (const ro of MockResizeObserver.instances) ro.fire(CONTENT_WIDTH)
  })
  // The playhead loop is rAF-driven; step the manual scheduler while
  // waiting for the lane canvas to be painted.
  await waitFor(() => {
    act(() => {
      tickRaf()
      tickRaf()
    })
    const el = document.querySelector('canvas[data-id="lane:0:waveform"]')
    expect(el ? ctxOf(el).rects.length : 0).toBeGreaterThan(0)
  })
}

/** The scrollbar thumb geometry: the navigation oracle of these tests. */
function thumb(): { width: number; left: number } {
  const el = document.querySelector('.wave-scrollbar-thumb')
  expect(el).not.toBeNull()
  const t = el as HTMLElement
  return { width: parseFloat(t.style.width), left: parseFloat(t.style.left) }
}

beforeEach(() => {
  vi.clearAllMocks()
  commandCalls.length = 0
  sessionStorage.clear()
  sessionStorage.setItem('basseparate.sessionToken', 'test-token')
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')

  wf.listProjectJobs.mockResolvedValue([])
  wf.createWaveformJob.mockResolvedValue({ id: 'job-1' })
  mockPlayback.latestCompletedImportId.mockResolvedValue(IMPORT_ID)
  mockPlayback.getSourceInfo.mockResolvedValue(SOURCE_INFO_STEREO)
  mockPlayback.ensurePlaybackTarget.mockResolvedValue(PLAYBACK_TARGET)
  mockReady()

  mockClient.GET.mockImplementation((path: string) => {
    switch (path) {
      case '/api/v1/system':
        return Promise.resolve(ok({ app_version: '0.1.0-dev', api_version: 1, ready: true }))
      case '/api/v1/projects':
        return Promise.resolve(ok({ projects: [READY_PROJECT] }))
      case '/api/v1/projects/{project_id}':
        return Promise.resolve(ok(SNAPSHOT))
      case '/api/v1/projects/{project_id}/source-info':
        return Promise.resolve(ok(SOURCE_INFO_STEREO))
      case '/api/v1/projects/{project_id}/imports':
        return Promise.resolve(ok({ imports: [] }))
      case '/api/v1/projects/{project_id}/playback':
        return Promise.resolve(ok(PLAYBACK_TARGET))
      default:
        return Promise.resolve(ok({}))
    }
  })
  mockClient.POST.mockImplementation((path: string, opts: { body?: unknown }) => {
    if (
      typeof path === 'string' &&
      (path.endsWith('/commands') || path.endsWith('/undo') || path.endsWith('/redo'))
    ) {
      commandCalls.push({ path, body: opts.body as CommandBody | undefined })
      const base = (opts.body as { base_revision?: number } | undefined)?.base_revision ?? 0
      return Promise.resolve(
        ok({
          revision: base + 1,
          markers: [],
          working_state: WORKING_STATE,
          can_undo: true,
          can_redo: false,
        }),
      )
    }
    return Promise.resolve(ok({}))
  })

  rafCbs = new Map()
  window.requestAnimationFrame = (cb: FrameRequestCallback) => {
    rafSeq += 1
    rafCbs.set(rafSeq, cb)
    return rafSeq
  }
  window.cancelAnimationFrame = (id: number) => {
    rafCbs.delete(id)
  }
})

afterEach(() => {
  MockResizeObserver.instances = []
  window.requestAnimationFrame = realRaf
  window.cancelAnimationFrame = realCaf
  rafCbs = new Map()
})

stubCanvasContext()
vi.stubGlobal('ResizeObserver', MockResizeObserver)
Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })

// jsdom's requestAnimationFrame runs in real time; the playhead loop needs
// deterministic stepping, so it is replaced with a manual scheduler.
const realRaf = window.requestAnimationFrame
const realCaf = window.cancelAnimationFrame
let rafSeq = 0
let rafCbs = new Map<number, FrameRequestCallback>()

/** Run every rAF callback registered so far once (one animation frame). */
function tickRaf(): void {
  const cbs = [...rafCbs.values()]
  rafCbs.clear()
  for (const cb of cbs) cb(0)
}

// --- tests -------------------------------------------------------------------

describe('app restore + autosave (M1.15)', () => {
  it('restores selection, viewport, channel display, and follow', async () => {
    await openReadyProject()
    await readyEditor()

    // Selection readout: 0.2 s – 0.4 s · 0.2 s
    expect(screen.getByText('0:00.200 – 0:00.400 · 0:00.200')).toBeInTheDocument()
    // Viewport: start 4800 @ 6.4 fpp over 750 px -> 4800 visible frames.
    expect(thumb()).toEqual({ width: 75, left: 75 })
    // Channel display: unlinked (the value readout shows "unlinked").
    const amp = within(screen.getByRole('group', { name: 'Display amplitude' }))
    expect(amp.getByRole('checkbox', { name: 'Link channels' })).not.toBeChecked()
    expect(amp.getByText('unlinked')).toBeInTheDocument()
    // Follow playhead: restored to off.
    expect(screen.getByRole('checkbox', { name: 'Follow playhead' })).not.toBeChecked()
  })

  it('seeds the monitoring volume from the working state', async () => {
    await openReadyProject()
    // 150 %: the slider value is seeded once the snapshot arrives.
    expect(await screen.findByDisplayValue('150')).toBeInTheDocument()
  })

  it('parks the playhead at the last saved position and saves it', async () => {
    await openReadyProject()
    // The park seeks the paused transport to 9600; the position is
    // reported immediately because playback is not active.
    await screen.findByText('9600', { selector: 'dd' })
    await waitFor(() => {
      expect(commandBodies('set_position').some((b) => b.op?.position_frames === 9600)).toBe(true)
    })
  })

  it('autosaves viewport changes after the view debounce', async () => {
    await openReadyProject()
    await readyEditor()
    const user = userEvent.setup()
    const before = commandBodies('set_viewport').length
    await user.click(screen.getByRole('button', { name: 'Zoom in (horizontal)' }))
    // Debounced: nothing is sent immediately.
    expect(commandBodies('set_viewport')).toHaveLength(before)
    await new Promise((resolve) => setTimeout(resolve, 1300))
    const sends = commandBodies('set_viewport')
    // One coalesced send, carrying the zoomed viewport (zoom in halves
    // the frames-per-pixel: 6.4 -> 3.2).
    expect(sends).toHaveLength(before + 1)
    const last = sends[sends.length - 1]
    expect(
      (last.op as { viewport?: { frames_per_css_pixel: number } })?.viewport?.frames_per_css_pixel,
    ).toBe(3.2)
  })

  it('shows the pending chip while ops are armed and clears it after the send', async () => {
    await openReadyProject()
    await readyEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Zoom in (horizontal)' }))
    // The zoom arms the debounced set_viewport send: the chip is visible.
    expect(screen.getByText('Saving…')).toBeInTheDocument()
    // It clears once the debounced send completes.
    await waitFor(() => expect(screen.queryByText('Saving…')).not.toBeInTheDocument(), {
      timeout: 3000,
    })
  })

  it('shows a stale notice and resyncs on a 409 conflict', async () => {
    // Every command send conflicts.
    mockClient.POST.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.endsWith('/commands')) {
        return Promise.resolve({
          response: { ok: false, status: 409 },
          error: {
            error: {
              code: 'STALE_REVISION',
              message: 'stale revision',
              details: { current_revision: 7 },
            },
          },
          data: undefined,
        })
      }
      return Promise.resolve(ok({}))
    })
    await openReadyProject()
    await readyEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Zoom in (horizontal)' }))
    expect(
      await screen.findByText('Project changed elsewhere — reloaded.', undefined, {
        timeout: 3000,
      }),
    ).toBeInTheDocument()
    // The hook resynced from the project snapshot (initial load + resync).
    const snapshotGets = mockClient.GET.mock.calls.filter(
      (c) => c[0] === '/api/v1/projects/{project_id}',
    )
    expect(snapshotGets.length).toBeGreaterThanOrEqual(2)
  })
})
