/**
 * Pure canvas painters for the waveform editor (M1.10, spec §12.3–12.7).
 *
 * Every function draws in CSS pixels on a 2D context that the component
 * has already scaled for the device pixel ratio
 * (`ctx.setTransform(dpr, 0, 0, dpr, 0, 0)`), so all coordinates below
 * are CSS px (§12.4). The context is a minimal structural interface so
 * the unit tests can record calls without a real canvas (jsdom has no
 * 2D context). No painter allocates per frame beyond the draw calls.
 */

import { frameToX, xToFrame, type Viewport } from './viewport'

/** Minimal structural subset of `CanvasRenderingContext2D` used here. */
export interface WaveformContext {
  fillStyle: string | CanvasGradient | CanvasPattern
  strokeStyle: string | CanvasGradient | CanvasPattern
  lineWidth: number
  font: string
  textBaseline: CanvasTextBaseline
  fillRect(x: number, y: number, w: number, h: number): void
  clearRect(x: number, y: number, w: number, h: number): void
  beginPath(): void
  moveTo(x: number, y: number): void
  lineTo(x: number, y: number): void
  stroke(): void
  strokeRect(x: number, y: number, w: number, h: number): void
  fill(): void
  save(): void
  restore(): void
  translate(x: number, y: number): void
  fillText(text: string, x: number, y: number): void
}

/** Palette (matches `styles.css`). */
export const WAVEFORM_COLOR = '#4da3ff'
export const OVERVIEW_COLOR = '#3a6ea8'
export const RULER_COLOR = '#9aa7b4'
export const GRID_COLOR = 'rgba(154, 167, 180, 0.25)'
export const PLAYHEAD_COLOR = '#e6ebf0'

/** Per-bucket min/max accessor for one channel of a peak level. */
export interface BucketSource {
  /** Frames covered by one bucket (the level's `bucket_frame_count`). */
  bucketFrameCount: number
  /** Total buckets at this level. */
  bucketCount: number
  /** `[min, max]` for a bucket index, or null when not fetched yet. */
  bucketAt(index: number): [number, number] | null
}

/** Per-pixel min/max accessor for one channel of a PCM aggregate. */
export interface PcmPixelSource {
  /** Source frame of the first aggregated frame. */
  startFrame: number
  /** Aggregated CSS pixels (covers `startFrame` forward). */
  pixelCount: number
  /** `[min, max]` for a pixel index, or null when out of range. */
  pixelAt(index: number): [number, number] | null
}

/** One channel of deinterleaved PCM for sample-level drawing. */
export interface SampleSource {
  /** Source frame of the first sample. */
  startFrame: number
  samples: Float32Array
}

export interface LaneDrawOptions {
  /** Lane height in CSS px. */
  height: number
  /** Display amplitude multiplier (0.25–16, default 1). */
  amplitudeScale?: number
  /** Fill/stroke color (default `WAVEFORM_COLOR`). */
  color?: string
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/**
 * Map per-pixel min/max extrema to a filled column in a lane
 * (spec §12.7). `atPixel(px)` yields `[min, max]` for CSS pixel `px`
 * (0-based, canvas-relative) or null for blank columns. Columns whose
 * extrema exceed the scaled lane get a 2 px clip tick at the lane edge
 * (§12.7.4); silent columns collapse to a 1 px zero line.
 */
function paintColumns(
  ctx: WaveformContext,
  atPixel: (px: number) => [number, number] | null,
  x0: number,
  width: number,
  opts: LaneDrawOptions,
): void {
  const height = opts.height
  const scale = opts.amplitudeScale ?? 1
  const center = height / 2
  const half = height / 2
  ctx.fillStyle = opts.color ?? WAVEFORM_COLOR
  for (let px = 0; px < width; px++) {
    const ext = atPixel(px)
    if (!ext) continue
    const [min, max] = ext
    const clipTop = max * scale > 1
    const clipBottom = min * scale < -1
    const yTop = clamp(center - max * half * scale, 0, height)
    const yBottom = clamp(center - min * half * scale, 0, height)
    if (yBottom - yTop < 1) {
      ctx.fillRect(x0 + px, center, 1, 1)
    } else {
      ctx.fillRect(x0 + px, yTop, 1, yBottom - yTop)
    }
    if (clipTop) ctx.fillRect(x0 + px, 0, 1, 2)
    if (clipBottom) ctx.fillRect(x0 + px, height - 2, 1, 2)
  }
}

/**
 * Draw one lane from peak buckets (spec §12.7.1): for each CSS pixel,
 * the min/max over every bucket the pixel intersects. Columns past the
 * bucket data stay blank.
 */
export function drawLaneWaveform(
  ctx: WaveformContext,
  source: BucketSource,
  viewport: Viewport,
  x0: number,
  width: number,
  opts: LaneDrawOptions,
): void {
  const bfc = source.bucketFrameCount
  paintColumns(
    ctx,
    (px) => {
      const f0 = xToFrame(viewport, x0 + px)
      const f1 = xToFrame(viewport, x0 + px + 1)
      const b0 = Math.floor(f0 / bfc)
      const b1 = Math.min(source.bucketCount - 1, Math.floor((f1 - 1e-9) / bfc))
      if (b1 < b0) return null
      let min = Number.POSITIVE_INFINITY
      let max = Number.NEGATIVE_INFINITY
      for (let b = b0; b <= b1; b++) {
        const ext = source.bucketAt(b)
        if (!ext) continue
        if (ext[0] < min) min = ext[0]
        if (ext[1] > max) max = ext[1]
      }
      return Number.isFinite(min) ? [min, max] : null
    },
    x0,
    width,
    opts,
  )
}

/** Draw one lane from per-pixel PCM min/max (spec §12.5.6/§12.7.2). */
export function drawPcmWaveform(
  ctx: WaveformContext,
  source: PcmPixelSource,
  viewport: Viewport,
  x0: number,
  width: number,
  opts: LaneDrawOptions,
): void {
  const offset = (source.startFrame - viewport.startFrame) / viewport.framesPerCssPixel
  paintColumns(
    ctx,
    (px) => {
      const p = Math.round(px - offset)
      if (p < 0 || p >= source.pixelCount) return null
      return source.pixelAt(p)
    },
    x0,
    width,
    opts,
  )
}

/**
 * Draw one lane as a sample polyline (spec §12.5.7): used when
 * `framesPerCssPixel < 1` and individual samples are visible.
 */
export function drawSamplePoints(
  ctx: WaveformContext,
  source: SampleSource,
  viewport: Viewport,
  x0: number,
  width: number,
  opts: LaneDrawOptions,
): void {
  const height = opts.height
  const scale = opts.amplitudeScale ?? 1
  const center = height / 2
  const half = height / 2
  const f0 = xToFrame(viewport, x0)
  const f1 = xToFrame(viewport, x0 + width)
  const i0 = Math.max(0, Math.ceil(f0 - source.startFrame))
  const i1 = Math.min(source.samples.length - 1, Math.floor(f1 - source.startFrame))
  if (i1 < i0) return
  ctx.strokeStyle = opts.color ?? WAVEFORM_COLOR
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let i = i0; i <= i1; i++) {
    const x = frameToX(viewport, source.startFrame + i)
    const y = clamp(center - source.samples[i] * half * scale, 0, height)
    if (i === i0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()
}

/**
 * Ruler ticks and labels (spec §13.5, static in M1.10). The tick step
 * is the smallest 1/2/5 × 10^k second value keeping labels at least
 * `minLabelGap` px apart; labels carry milliseconds when the step is
 * sub-second.
 */
export interface RulerOptions {
  sampleRate: number
  /** Ruler canvas height in CSS px. */
  height: number
  /** Minimum horizontal gap between labels (default 56 px). */
  minLabelGap?: number
}

function niceStep(seconds: number): number {
  for (let exp = -2; exp <= 10; exp++) {
    for (const n of [1, 2, 5]) {
      const s = n * 10 ** exp
      if (s >= seconds) return s
    }
  }
  return 10 ** 10
}

function rulerLabel(seconds: number, step: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds - m * 60
  if (step < 1) return `${m}:${s.toFixed(3).padStart(6, '0')}`
  return `${m}:${Math.round(s).toString().padStart(2, '0')}`
}

export function drawRuler(
  ctx: WaveformContext,
  viewport: Viewport,
  width: number,
  opts: RulerOptions,
): void {
  const rate = opts.sampleRate
  if (!(rate > 0)) throw new RangeError('sampleRate must be > 0')
  const gap = opts.minLabelGap ?? 56
  const secondsPerPx = viewport.framesPerCssPixel / rate
  const step = niceStep(gap * secondsPerPx)
  const t0 = viewport.startFrame / rate
  const t1 = (viewport.startFrame + width * viewport.framesPerCssPixel) / rate
  ctx.strokeStyle = RULER_COLOR
  ctx.fillStyle = RULER_COLOR
  ctx.lineWidth = 1
  ctx.font = '11px system-ui, sans-serif'
  ctx.textBaseline = 'top'
  for (let i = Math.ceil(t0 / step - 1e-9); i * step <= t1 + 1e-9; i++) {
    const t = i * step
    const x = Math.round(frameToX(viewport, t * rate)) + 0.5
    ctx.beginPath()
    ctx.moveTo(x, opts.height - 6)
    ctx.lineTo(x, opts.height)
    ctx.stroke()
    ctx.fillText(rulerLabel(t, step), x + 4, 2)
  }
}

/** The playhead: the only painter run on position updates (§12.3). */
export function drawPlayhead(ctx: WaveformContext, x: number, height: number): void {
  const px = Math.round(x) + 0.5
  ctx.strokeStyle = PLAYHEAD_COLOR
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(px, 0)
  ctx.lineTo(px, height)
  ctx.stroke()
}

/** Lane grid: the centered zero line (lane separators are CSS borders). */
export function drawLaneGrid(ctx: WaveformContext, width: number, height: number): void {
  ctx.strokeStyle = GRID_COLOR
  ctx.lineWidth = 1
  const y = Math.round(height / 2) + 0.5
  ctx.beginPath()
  ctx.moveTo(0, y)
  ctx.lineTo(width, y)
  ctx.stroke()
}

/**
 * Overview strip (spec §12.6): one mini lane per channel from the
 * coarsest level, fitted to the full source width.
 */
export function drawOverview(
  ctx: WaveformContext,
  sources: BucketSource[],
  width: number,
  height: number,
): void {
  const lanes = Math.max(1, sources.length)
  const laneH = Math.max(4, Math.floor(height / lanes))
  for (let c = 0; c < sources.length; c++) {
    const src = sources[c]
    const totalFrames = src.bucketCount * src.bucketFrameCount
    if (!(totalFrames > 0) || !(width > 0)) continue
    const viewport: Viewport = {
      startFrame: 0,
      framesPerCssPixel: totalFrames / width,
      widthCssPx: width,
    }
    ctx.save()
    ctx.translate(0, c * laneH)
    drawLaneWaveform(ctx, src, viewport, 0, width, { height: laneH, color: OVERVIEW_COLOR })
    ctx.restore()
  }
}

/** Selection palette (M1.11, spec §13.4). */
export const SELECTION_COLOR = 'rgba(77, 163, 255, 0.18)'
export const SELECTION_HANDLE_COLOR = '#4da3ff'
export const OVERVIEW_WINDOW_COLOR = 'rgba(230, 235, 240, 0.25)'
export const OVERVIEW_WINDOW_BORDER = 'rgba(230, 235, 240, 0.9)'

export interface SelectionDrawOptions {
  /** Translucent fill of the range (default `SELECTION_COLOR`). */
  color?: string
  /** Handle fill (default `SELECTION_HANDLE_COLOR`). */
  handleColor?: string
  /** Handle width in CSS px, the boundary hit target (default 3). */
  handleWidth?: number
}

/**
 * Selection range on one lane (M1.11, spec §13.4.7–8): a translucent
 * fill of `[x0, x1]` plus a handle at each boundary.
 */
export function drawSelection(
  ctx: WaveformContext,
  x0: number,
  x1: number,
  height: number,
  opts: SelectionDrawOptions = {},
): void {
  if (!(x1 > x0)) return
  const handle = opts.handleWidth ?? 3
  ctx.fillStyle = opts.color ?? SELECTION_COLOR
  ctx.fillRect(x0, 0, x1 - x0, height)
  ctx.fillStyle = opts.handleColor ?? SELECTION_HANDLE_COLOR
  ctx.fillRect(x0 - handle / 2, 0, handle, height)
  ctx.fillRect(x1 - handle / 2, 0, handle, height)
}

/** Practice-loop palette (M2.11, spec §13.1): amber first (server default). */
export const LOOP_DEFAULT_COLOR = '#f59e0b'
export const LOOP_COLORS = [
  '#f59e0b',
  '#10b981',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
  '#e11d48',
] as const

/** `#rrggbb` → `rgba(r, g, b, a)`; malformed input uses the loop default. */
export function loopFillColor(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) return `rgba(245, 158, 11, ${alpha})`
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 0xff}, ${(n >> 8) & 0xff}, ${n & 0xff}, ${alpha})`
}

export interface LoopDrawOptions {
  /** Loop color (default `LOOP_DEFAULT_COLOR`). */
  color?: string
  /** Tint alpha (default 0.15). */
  fillAlpha?: number
  /** Boundary handle width in CSS px, the hit target (default 3). */
  handleWidth?: number
}

/** Width of the top-center loop grip in CSS px. */
export const LOOP_GRIP_WIDTH = 20
/** Height of the top-center loop grip in CSS px. */
export const LOOP_GRIP_HEIGHT = 4
/** Top offset of the loop grip in CSS px. */
export const LOOP_GRIP_TOP = 2

/**
 * Practice-loop overlay on one lane (M2.11, spec §13.2.3–4): a tinted
 * fill of `[x0, x1]`, a handle at each boundary, and a 2 px top border
 * with a grip bar at the top center. The border keeps the range readable
 * over the selection tint; the grip is the plain-drag target for moving
 * the whole interval.
 */
export function drawLoop(
  ctx: WaveformContext,
  x0: number,
  x1: number,
  height: number,
  opts: LoopDrawOptions = {},
): void {
  if (!(x1 > x0)) return
  const handle = opts.handleWidth ?? 3
  const color = opts.color ?? LOOP_DEFAULT_COLOR
  ctx.fillStyle = loopFillColor(color, opts.fillAlpha ?? 0.15)
  ctx.fillRect(x0, 0, x1 - x0, height)
  ctx.fillStyle = color
  ctx.fillRect(x0 - handle / 2, 0, x1 - x0 + handle, 2)
  ctx.fillRect(x0 - handle / 2, 0, handle, height)
  ctx.fillRect(x1 - handle / 2, 0, handle, height)
  // The grip is clamped to the visible portion by the caller, so a loop
  // running past the viewport edge still shows a usable center handle.
  const grip = Math.min(LOOP_GRIP_WIDTH, x1 - x0)
  ctx.fillRect((x0 + x1) / 2 - grip / 2, LOOP_GRIP_TOP, grip, LOOP_GRIP_HEIGHT)
}

export interface OverviewWindowOptions {
  /** Window fill (default `OVERVIEW_WINDOW_COLOR`). */
  color?: string
  /** Window border (default `OVERVIEW_WINDOW_BORDER`). */
  borderColor?: string
}

/**
 * Viewport window indicator on the overview strip (M1.11, spec
 * §13.2.3): a translucent fill of the visible range plus a 1 px border.
 */
export function drawOverviewWindow(
  ctx: WaveformContext,
  x0: number,
  x1: number,
  height: number,
  opts: OverviewWindowOptions = {},
): void {
  if (!(x1 > x0)) return
  ctx.fillStyle = opts.color ?? OVERVIEW_WINDOW_COLOR
  ctx.fillRect(x0, 0, x1 - x0, height)
  ctx.strokeStyle = opts.borderColor ?? OVERVIEW_WINDOW_BORDER
  ctx.lineWidth = 1
  ctx.strokeRect(x0 + 0.5, 0.5, Math.max(1, x1 - x0 - 1), height - 1)
}

// --- markers (M1.15, spec §17.2) ------------------------------------------------

/** The 6-color marker palette cycled by the swatch button (§17.2.6). */
export const MARKER_COLORS = [
  '#e11d48',
  '#f59e0b',
  '#10b981',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
] as const

/** Fixed flag body size (the label is truncated to fit, §17.2). */
export const MARKER_FLAG_WIDTH = 76
export const MARKER_FLAG_HEIGHT = 12

export interface MarkerFlagOptions {
  color: string
  /** Draw the selection outline around the flag (§17.2.9). */
  selected?: boolean
}

/**
 * One marker flag on the marker row: a full-height 2 px stem, a fixed-size
 * colored body at the top, and the label truncated to ~12 characters.
 * `x` is the flag's left edge in CSS px (ruler-aligned).
 */
export function drawMarkerFlag(
  ctx: WaveformContext,
  x: number,
  label: string,
  height: number,
  opts: MarkerFlagOptions,
): void {
  const fx = Math.round(x)
  ctx.fillStyle = opts.color
  ctx.fillRect(fx, 0, 2, height)
  ctx.fillRect(fx, 0, MARKER_FLAG_WIDTH, MARKER_FLAG_HEIGHT)
  const text = label.length > 12 ? `${label.slice(0, 11)}…` : label
  ctx.fillStyle = '#ffffff'
  ctx.font = '11px system-ui, sans-serif'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, fx + 4, MARKER_FLAG_HEIGHT / 2)
  if (opts.selected) {
    ctx.strokeStyle = '#0f172a'
    ctx.lineWidth = 1
    ctx.strokeRect(fx + 0.5, 0.5, Math.max(1, MARKER_FLAG_WIDTH - 1), Math.max(1, height - 1))
  }
}

/**
 * A 1 px vertical tick on a lane's `markers` layer at the marker's frame
 * position (§17.2).
 */
export function drawMarkerTick(
  ctx: WaveformContext,
  x: number,
  height: number,
  color: string,
): void {
  const px = Math.round(x) + 0.5
  ctx.strokeStyle = color
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(px, 0)
  ctx.lineTo(px, height)
  ctx.stroke()
}
