/**
 * Component tests for the waveform editor (M1.10 §12, M1.11 §13).
 *
 * jsdom has no 2D canvas context, no ResizeObserver, and no PointerEvent
 * constructor, so: the context stub records calls per canvas (that is how
 * the layer-isolation, selection, and amplitude assertions are made); the
 * observer stub lets a test fire a single resize with a known content
 * width; pointer interactions are dispatched as `MouseEvent`s with pointer
 * types. The waveform API is mocked end to end — the mocks return already
 * encoded tile and PCM bytes, which the real decode path parses.
 *
 * All geometry tests use the fit view: 48 000 frames at 750 CSS px is
 * exactly 64 frames/px. The scrollbar thumb is the navigation oracle —
 * `width` shows the visible fraction, `left` the clamped start position.
 */

import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { wf, mockLatestCompletedImportId } = vi.hoisted(() => ({
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
  mockLatestCompletedImportId: vi.fn(),
}))

vi.mock('../src/api/waveform', () => wf)
vi.mock('../src/api/playback', () => ({
  latestCompletedImportId: mockLatestCompletedImportId,
}))

import { WaveformEditor } from '../src/waveform/WaveformEditor'

const PROJECT_ID = '11111111-1111-1111-1111-111111111111'
const ASSET_ID = '44444444-4444-4444-4444-444444444444'
const IMPORT_ID = '22222222-2222-2222-2222-222222222222'

/** 1 s of 48 kHz stereo: 750 buckets at level 0 (64 frames/bucket), 1 tile. */
const FRAMES = 48_000
const BUCKETS = 750
/** 750 CSS px means exactly 64 frames/px -> peak path at the fit view. */
const CONTENT_WIDTH = 750
const LANE_HEIGHT = 48

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
  // Zooms below 64 fpp fetch raw PCM; constant extrema keep the painted
  // columns identical to the peak path.
  wf.getAssetPcm.mockImplementation((_asset: string, startFrame: number, count: number) => {
    const frames = Math.min(count, Math.max(0, FRAMES - startFrame))
    const bytes = new ArrayBuffer(frames * 2 * 4)
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

type EditorProps = Parameters<typeof WaveformEditor>[0]

function renderEditor(props: Partial<EditorProps> = {}) {
  return render(
    <WaveformEditor projectId={PROJECT_ID} sourceAssetId={ASSET_ID} playheadFrame={0} {...props} />,
  )
}

/** Render, wait for the ready layout, fire a 750 px resize, wait for paint. */
async function renderReadyEditor(props: Partial<EditorProps> = {}) {
  const utils = renderEditor(props)
  // The control row only mounts once the hook is ready.
  const group = await screen.findByRole('group', { name: 'Display amplitude' })
  await within(group).findByRole('button', { name: 'Zoom in' })
  act(() => {
    for (const ro of MockResizeObserver.instances) ro.fire(CONTENT_WIDTH)
  })
  const lane0 = document.querySelector('canvas[data-id="lane:0:waveform"]')
  await waitFor(() => {
    expect(lane0 ? ctxOf(lane0).rects.length : 0).toBeGreaterThan(0)
  })
  return utils
}

// --- M1.11 interaction helpers (jsdom has no PointerEvent) ------------------

function section(): HTMLElement {
  return document.querySelector('.waveform-editor') as HTMLElement
}

function hitbox(): HTMLElement {
  return document.querySelector('.wave-lane-hitarea') as HTMLElement
}

function pointer(type: string, el: Element, clientX: number): void {
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX }))
  })
}

function wheel(
  el: Element,
  init: {
    ctrlKey?: boolean
    shiftKey?: boolean
    deltaY?: number
    deltaX?: number
    clientX?: number
  },
): void {
  act(() => {
    el.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ...init }))
  })
}

function key(el: Element, k: string): void {
  act(() => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
  })
}

/** The scrollbar thumb geometry: the navigation oracle of these tests. */
function thumb(): { width: number; left: number } {
  const el = document.querySelector('.wave-scrollbar-thumb')
  expect(el).not.toBeNull()
  const t = el as HTMLElement
  return { width: parseFloat(t.style.width), left: parseFloat(t.style.left) }
}

function ampControls() {
  return within(screen.getByRole('group', { name: 'Display amplitude' }))
}

function zoomInH(): HTMLElement {
  return screen.getByRole('button', { name: 'Zoom in (horizontal)' })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  wf.listProjectJobs.mockResolvedValue([])
  mockLatestCompletedImportId.mockResolvedValue(IMPORT_ID)
  wf.createWaveformJob.mockResolvedValue({ id: 'job-1' })
})

afterEach(() => {
  MockResizeObserver.instances = []
})

stubCanvasContext()
vi.stubGlobal('ResizeObserver', MockResizeObserver)
Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })

describe('WaveformEditor states (spec §12.8)', () => {
  it('shows the empty state without a source asset', async () => {
    renderEditor({ sourceAssetId: null })
    expect(await screen.findByText('No source imported yet.', { exact: false })).toBeInTheDocument()
  })

  it('shows the decoding state while metadata is in flight', async () => {
    wf.getAssetMetadata.mockImplementation(() => new Promise(() => {}))
    renderEditor()
    expect(await screen.findByText('Building the waveform…')).toBeInTheDocument()
  })

  it('shows the pending state while a waveform job is running', async () => {
    wf.getAssetMetadata.mockResolvedValue({ waveform: null })
    wf.listProjectJobs.mockResolvedValue([
      { id: 'job-1', jobType: 'waveform', state: 'running', progressFraction: 0.4 },
    ])
    renderEditor()
    expect(await screen.findByText('Waveform build queued.', { exact: false })).toBeInTheDocument()
  })

  it('offers a rebuild when the waveform cache is missing', async () => {
    wf.getAssetMetadata.mockResolvedValue({ waveform: null })
    renderEditor()
    expect(
      await screen.findByText('The waveform data is missing.', { exact: false }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Rebuild waveform' }))
    expect(mockLatestCompletedImportId).toHaveBeenCalledWith(PROJECT_ID)
    expect(wf.createWaveformJob).toHaveBeenCalledWith(PROJECT_ID, IMPORT_ID)
    expect(await screen.findByText('Waveform build queued.', { exact: false })).toBeInTheDocument()
  })
})

describe('WaveformEditor layout (plan §8)', () => {
  it('renders the full layout with five canvas layers per lane when ready', async () => {
    mockReady()
    await renderReadyEditor()

    canvasById('overview')
    canvasById('ruler')
    for (const layer of ['waveform', 'grid', 'selection', 'markers', 'playhead']) {
      canvasById(`lane:0:${layer}`)
      canvasById(`lane:1:${layer}`)
    }

    // Lane labels (L/R) and the channel checkboxes.
    expect(screen.getAllByText('L').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('R').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('checkbox', { name: 'Show L' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Show R' })).toBeChecked()

    // Marker lane, selection readout, scrollbar.
    expect(screen.getByLabelText('Markers')).toBeInTheDocument()
    expect(screen.getByLabelText('Selection')).toHaveTextContent('—')
    expect(document.querySelector('.wave-scrollbar-thumb')).not.toBeNull()

    // Horizontal navigation controls; Fit selection needs a selection.
    expect(screen.getByRole('button', { name: 'Zoom out (horizontal)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit song' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit selection' })).toBeDisabled()

    // Amplitude controls, scoped to their fieldset.
    expect(ampControls().getByRole('button', { name: 'Zoom out' })).toBeInTheDocument()
    expect(ampControls().getByRole('button', { name: 'Reset' })).toBeDisabled()
    expect(ampControls().getByText('1×')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Link channels' })).toBeChecked()
  })

  it('allocates canvases in device pixels (css × dpr)', async () => {
    mockReady()
    await renderReadyEditor()
    const lane = canvasById('lane:0:waveform')
    expect(lane.width).toBe(CONTENT_WIDTH * 2)
    expect(lane.height).toBe(LANE_HEIGHT * 2)
    expect(canvasById('overview').width).toBe(CONTENT_WIDTH * 2)
    expect(canvasById('ruler').height).toBe(24 * 2)
  })
})

describe('WaveformEditor drawing', () => {
  it('paints the lane waveform, the overview, and the ruler', async () => {
    mockReady()
    await renderReadyEditor()

    const wave = ctxOf(canvasById('lane:0:waveform'))
    // 750 columns; first column at scale 1: top 24 - 0.75×24 = 6, height 24.
    expect(wave.rects.length).toBe(750)
    expect(wave.rects[0]).toEqual([0, 6, 1, 24])

    const overview = ctxOf(canvasById('overview'))
    expect(overview.rects.length).toBeGreaterThan(0)

    const ruler = ctxOf(canvasById('ruler'))
    expect(ruler.texts.length).toBeGreaterThan(0)
  })

  it('redraws only the playhead layer on position updates (spec §12.3)', async () => {
    mockReady()
    const { rerender } = await renderReadyEditor()
    const wave = ctxOf(canvasById('lane:0:waveform'))
    const head = ctxOf(canvasById('lane:0:playhead'))
    const waveClears = wave.clears
    const waveRects = wave.rects.length
    const headStrokes = head.strokes
    expect(waveRects).toBeGreaterThan(0)
    expect(headStrokes).toBe(1) // playhead at frame 0

    rerender(
      <WaveformEditor projectId={PROJECT_ID} sourceAssetId={ASSET_ID} playheadFrame={24_000} />,
    )

    expect(wave.clears).toBe(waveClears)
    expect(wave.rects.length).toBe(waveRects)
    expect(head.strokes).toBe(headStrokes + 1)
  })

  it('applies the display amplitude scale to the waveform layer', async () => {
    mockReady()
    await renderReadyEditor()
    const wave = ctxOf(canvasById('lane:0:waveform'))
    expect(wave.rects[0]).toEqual([0, 6, 1, 24])

    await userEvent.click(ampControls().getByRole('button', { name: 'Zoom in' }))
    // Scale 2: 0.75×2 > 1 clips at the lane top; column 0..36 plus a 2 px tick.
    expect(ampControls().getByText('2×')).toBeInTheDocument()
    expect(wave.rects[0]).toEqual([0, 0, 1, 36])
    expect(wave.rects[1]).toEqual([0, 0, 1, 2])

    await userEvent.click(ampControls().getByRole('button', { name: 'Reset' }))
    expect(ampControls().getByText('1×')).toBeInTheDocument()
    expect(wave.rects[0]).toEqual([0, 6, 1, 24])

    // Zoom out clamps at 0.25×.
    await userEvent.click(ampControls().getByRole('button', { name: 'Zoom out' }))
    await userEvent.click(ampControls().getByRole('button', { name: 'Zoom out' }))
    expect(ampControls().getByText('0.25×')).toBeInTheDocument()
    expect(ampControls().getByRole('button', { name: 'Zoom out' })).toBeDisabled()
  })

  it('unmounts a lane canvas stack when the lane is hidden', async () => {
    mockReady()
    await renderReadyEditor()
    expect(document.querySelectorAll('canvas[data-id^="lane:1:"]')).toHaveLength(5)

    await userEvent.click(screen.getByRole('checkbox', { name: 'Show R' }))
    expect(document.querySelectorAll('canvas[data-id^="lane:1:"]')).toHaveLength(0)
    expect(document.querySelectorAll('canvas[data-id^="lane:0:"]')).toHaveLength(5)
  })

  it('collapses a lane from the per-lane toggle', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Hide R' }))
    expect(document.querySelectorAll('canvas[data-id^="lane:1:"]')).toHaveLength(0)
  })
})

describe('WaveformEditor horizontal zoom (M1.11 §13.1)', () => {
  it('the Zoom in button doubles magnification, center-anchored', async () => {
    mockReady()
    await renderReadyEditor()
    expect(thumb()).toEqual({ width: 750, left: 0 })
    await userEvent.click(zoomInH())
    expect(thumb()).toEqual({ width: 375, left: 187.5 })
  })

  it('Ctrl-wheel zooms anchored at the pointer', async () => {
    mockReady()
    await renderReadyEditor()
    wheel(hitbox(), { ctrlKey: true, deltaY: -100, clientX: 375 })
    expect(thumb()).toEqual({ width: 600, left: 75 })
  })

  it('a plain wheel leaves the view unchanged', async () => {
    mockReady()
    await renderReadyEditor()
    wheel(hitbox(), { deltaY: -100, clientX: 375 })
    expect(thumb()).toEqual({ width: 750, left: 0 })
  })

  it('Shift-wheel pans horizontally', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(zoomInH())
    wheel(hitbox(), { shiftKey: true, deltaX: 100, clientX: 375 })
    expect(thumb()).toEqual({ width: 375, left: 237.5 })
  })

  it('+/- keys zoom anchored at the playhead', async () => {
    mockReady()
    await renderReadyEditor()
    key(section(), '+')
    expect(thumb()).toEqual({ width: 375, left: 0 })
    key(section(), '-')
    expect(thumb()).toEqual({ width: 750, left: 0 })
  })

  it('Fit song restores the fit view', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(zoomInH())
    await userEvent.click(screen.getByRole('button', { name: 'Fit song' }))
    expect(thumb()).toEqual({ width: 750, left: 0 })
  })

  it('the thumb clamps to the source bounds', async () => {
    mockReady()
    await renderReadyEditor()
    // Zoomed out beyond the source: the thumb covers the whole track.
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out (horizontal)' }))
    expect(thumb()).toEqual({ width: 750, left: 0 })
    // Back in: the anchor sits at the clamped right edge, so the view
    // lands on the fit; one more step in, then pan hard right.
    await userEvent.click(zoomInH())
    expect(thumb()).toEqual({ width: 750, left: 0 })
    await userEvent.click(zoomInH())
    wheel(hitbox(), { shiftKey: true, deltaX: 10_000, clientX: 0 })
    expect(thumb()).toEqual({ width: 375, left: 375 })
  })
})

describe('WaveformEditor panning (M1.11 §13.2)', () => {
  it('dragging the overview strip pans the view', async () => {
    mockReady()
    await renderReadyEditor()
    // At the fit view the visible range spans the whole source, so pan is
    // clamped; zoom in first. 50 px on the overview = 50 × 64 = 3200 frames.
    await userEvent.click(zoomInH())
    const ov = document.querySelector('.wave-overview-row .wave-content') as HTMLElement
    pointer('pointerdown', ov, 100)
    pointer('pointermove', ov, 150)
    expect(thumb()).toEqual({ width: 375, left: 237.5 })
    pointer('pointerup', ov, 150)
  })

  it('a track click jumps the view center under the pointer', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(zoomInH())
    const bar = document.querySelector('.wave-scrollbar') as HTMLElement
    pointer('pointerdown', bar, 700)
    expect(thumb()).toEqual({ width: 375, left: 375 }) // jump clamps right
    pointer('pointerup', bar, 700)
  })

  it('dragging the thumb pans the view', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(zoomInH())
    const bar = document.querySelector('.wave-scrollbar') as HTMLElement
    pointer('pointerdown', bar, 300)
    pointer('pointermove', bar, 400)
    expect(thumb()).toEqual({ width: 375, left: 287.5 })
    pointer('pointerup', bar, 400)
  })

  it('offers return-to-playhead when the playhead leaves the view', async () => {
    mockReady()
    await renderReadyEditor({ playheadFrame: 37_000 })
    expect(screen.queryByRole('button', { name: 'Return to playhead' })).toBeNull()
    await userEvent.click(zoomInH())
    const btn = await screen.findByRole('button', { name: 'Return to playhead' })
    await userEvent.click(btn)
    expect(thumb()).toEqual({ width: 375, left: 375 })
  })

  it('auto-follows the playhead once follow is re-enabled', async () => {
    mockReady()
    const { rerender } = await renderReadyEditor() // playhead 0, fit, following
    await userEvent.click(zoomInH()) // {12000, 32}; manual zoom suspends follow
    await userEvent.click(screen.getByRole('button', { name: 'Return to playhead' }))
    // Centered on frame 0: {0, 32}, follow re-enabled.
    expect(thumb()).toEqual({ width: 375, left: 0 })

    // Playback reaches frame 37 000: outside [0, 24000] -> follow pans.
    rerender(
      <WaveformEditor projectId={PROJECT_ID} sourceAssetId={ASSET_ID} playheadFrame={37_000} />,
    )
    await waitFor(() => expect(thumb()).toEqual({ width: 375, left: 375 }))
  })
})

describe('WaveformEditor selection (M1.11 §13.4)', () => {
  it('a click seeks to the clicked frame', async () => {
    const onSeek = vi.fn()
    mockReady()
    await renderReadyEditor({ onSeek })
    const hit = hitbox()
    pointer('pointerdown', hit, 375)
    pointer('pointerup', hit, 375)
    expect(onSeek).toHaveBeenCalledWith(24_000)
  })

  it('a drag creates a selection with readout and painted range', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 150)
    pointer('pointermove', hit, 200)
    pointer('pointerup', hit, 200)

    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.133 – 0:00.267 · 0:00.133')
    expect(ctxOf(canvasById('lane:0:selection')).rects[0]).toEqual([100, 0, 100, 48])
    expect(screen.getByRole('button', { name: 'Fit selection' })).toBeEnabled()
  })

  it('a right-to-left drag selects the same range', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    pointer('pointerdown', hit, 200)
    pointer('pointermove', hit, 100)
    pointer('pointerup', hit, 100)

    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.133 – 0:00.267 · 0:00.133')
  })

  it('clamps the selection to the source bounds', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    pointer('pointerdown', hit, 700)
    pointer('pointermove', hit, 800)
    pointer('pointerup', hit, 800)

    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.933 – 0:01.000 · 0:00.067')
  })

  it('resizes from the boundary handles without crossing', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    // Seed a [6400, 12800] selection (x 100..200 at the fit view).
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 200)
    pointer('pointerup', hit, 200)

    // Drag the start handle (x 100) right to x 125 -> frame 8000.
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 125)
    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.167 – 0:00.267 · 0:00.100')
    pointer('pointerup', hit, 125)

    // The start handle now sits at x 125. Drag it past the end: it stops
    // one frame short of the end boundary.
    pointer('pointerdown', hit, 125)
    pointer('pointermove', hit, 300)
    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.267 – 0:00.267 · 0:00.000')
    pointer('pointerup', hit, 300)
  })

  it('Escape clears the selection', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 200)
    pointer('pointerup', hit, 200)
    expect(screen.getByLabelText('Selection')).toHaveTextContent('0:00.133')

    key(section(), 'Escape')
    expect(screen.getByLabelText('Selection')).toHaveTextContent('—')
  })

  it('Seek to selection start seeks to the start frame', async () => {
    const onSeek = vi.fn()
    mockReady()
    await renderReadyEditor({ onSeek })
    const hit = hitbox()
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 200)
    pointer('pointerup', hit, 200)

    await userEvent.click(screen.getByRole('button', { name: 'Seek to selection start' }))
    expect(onSeek).toHaveBeenCalledWith(6_400)
  })

  it('Fit selection fits exactly the selected range', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()
    pointer('pointerdown', hit, 100)
    pointer('pointermove', hit, 200)
    pointer('pointerup', hit, 200)

    await userEvent.click(screen.getByRole('button', { name: 'Fit selection' }))
    expect(thumb()).toEqual({ width: 100, left: 100 })
  })
})

describe('WaveformEditor vertical amplitude (M1.11 §13.3)', () => {
  it('unlinking exposes per-lane amplitude controls and disables the global ones', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Link channels' }))
    expect(ampControls().getByText('unlinked')).toBeInTheDocument()
    expect(ampControls().getByRole('button', { name: 'Zoom in' })).toBeDisabled()
    expect(ampControls().getByRole('button', { name: 'Zoom out' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Decrease L amplitude' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Increase R amplitude' })).toBeInTheDocument()
  })

  it('per-lane scaling affects only that lane', async () => {
    mockReady()
    await renderReadyEditor()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Link channels' }))
    await userEvent.click(screen.getByRole('button', { name: 'Decrease L amplitude' }))

    // Lane 0 at 0.5×: top 24 - 0.75×12 = 15, height 12. Lane 1 stays at 1×.
    expect(ctxOf(canvasById('lane:0:waveform')).rects[0]).toEqual([0, 15, 1, 12])
    expect(ctxOf(canvasById('lane:1:waveform')).rects[0]).toEqual([0, 6, 1, 24])
  })

  it('persists the amplitude state across remounts', async () => {
    mockReady()
    const { unmount } = await renderReadyEditor()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Link channels' }))
    await userEvent.click(screen.getByRole('button', { name: 'Decrease L amplitude' }))
    unmount()

    await renderReadyEditor()
    expect(ampControls().getByText('unlinked')).toBeInTheDocument()
    expect(ctxOf(canvasById('lane:0:waveform')).rects[0]).toEqual([0, 15, 1, 12])
  })
})

describe('WaveformEditor position readout (M1.11 §13.5.5)', () => {
  it('shows the frame under the pointer and clears on leave', async () => {
    mockReady()
    await renderReadyEditor()
    const hit = hitbox()

    pointer('pointermove', hit, 375)
    expect(document.querySelector('.wave-frame-readout')).toHaveTextContent(
      'frame 24000 · 0:00.500',
    )

    // React derives onPointerLeave from the bubbling `pointerout` event.
    pointer('pointerout', hit, 375)
    expect(document.querySelector('.wave-frame-readout')).toBeNull()
  })
})
