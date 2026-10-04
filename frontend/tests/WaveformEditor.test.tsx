/**
 * Component tests for the waveform editor (M1.10, plan §9).
 *
 * jsdom has no 2D canvas context and no ResizeObserver, so both are
 * stubbed: the context stub records calls per canvas (that is how the
 * layer-isolation and amplitude assertions are made) and the observer
 * stub lets a test fire a single resize with a known content width.
 * The waveform API is mocked end to end — the mocks return already
 * encoded tile bytes, which the real decode path parses (direct decode
 * injection).
 */

import { act, render, screen, waitFor } from '@testing-library/react'
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
/** 750 CSS px means exactly 64 frames/px -> peak path, level 0. */
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
  await screen.findByRole('button', { name: 'Zoom in' })
  act(() => {
    for (const ro of MockResizeObserver.instances) ro.fire(CONTENT_WIDTH)
  })
  const lane0 = document.querySelector('canvas[data-id="lane:0:waveform"]')
  await waitFor(() => {
    expect(lane0 ? ctxOf(lane0).rects.length : 0).toBeGreaterThan(0)
  })
  return utils
}

beforeEach(() => {
  vi.clearAllMocks()
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
    expect(await screen.findByText('No source imported.')).toBeInTheDocument()
  })

  it('shows the decoding state while metadata is in flight', async () => {
    wf.getAssetMetadata.mockImplementation(() => new Promise(() => {}))
    renderEditor()
    expect(await screen.findByText('Decoding audio…')).toBeInTheDocument()
  })

  it('shows the pending state while a waveform job is running', async () => {
    wf.getAssetMetadata.mockResolvedValue({ waveform: null })
    wf.listProjectJobs.mockResolvedValue([
      { id: 'job-1', jobType: 'waveform', state: 'running', progressFraction: 0.4 },
    ])
    renderEditor()
    expect(await screen.findByText('Building waveform…')).toBeInTheDocument()
  })

  it('offers a rebuild when the waveform cache is missing', async () => {
    wf.getAssetMetadata.mockResolvedValue({ waveform: null })
    renderEditor()
    expect(await screen.findByText('Waveform unavailable.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Build waveform' }))
    expect(mockLatestCompletedImportId).toHaveBeenCalledWith(PROJECT_ID)
    expect(wf.createWaveformJob).toHaveBeenCalledWith(PROJECT_ID, IMPORT_ID)
    expect(await screen.findByText('Building waveform…')).toBeInTheDocument()
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

    // Marker lane, selection readout, static scrollbar.
    expect(screen.getByLabelText('Markers')).toBeInTheDocument()
    expect(screen.getByLabelText('Selection')).toHaveTextContent('—')
    expect(document.querySelector('.wave-scrollbar-thumb')).not.toBeNull()

    // Amplitude controls.
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled()
    expect(screen.getByText('1×')).toBeInTheDocument()
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

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    // Scale 2: 0.75×2 > 1 clips at the lane top; column 0..36 plus a 2 px tick.
    expect(screen.getByText('2×')).toBeInTheDocument()
    expect(wave.rects[0]).toEqual([0, 0, 1, 36])
    expect(wave.rects[1]).toEqual([0, 0, 1, 2])

    await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByText('1×')).toBeInTheDocument()
    expect(wave.rects[0]).toEqual([0, 6, 1, 24])

    // Zoom out clamps at 0.25×.
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByText('0.25×')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled()
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
