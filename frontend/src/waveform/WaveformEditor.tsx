/**
 * Waveform editor component (M1.10 §12; M1.11 §13).
 *
 * Renders the §12.1 layout — overview strip, time ruler, per-channel lanes
 * (five stacked canvas layers each), marker lane, selection readout,
 * horizontal scrollbar, channel visibility controls, and the display
 * amplitude controls — plus the M1.11 interactions:
 *
 * - Horizontal zoom (§13.1): Zoom in/out buttons (×2/÷2, viewport-center
 *   anchored), `+`/`=` and `-`/`_` keys (playhead-anchored), Ctrl/Cmd-wheel
 *   (pointer-anchored), Fit song, Fit selection. 8 px/frame max, fractional
 *   coordinates, boundary clamping.
 * - Panning (§13.2): scrollbar track/thumb drag, Shift-wheel,
 *   overview-window drag, playhead follow with a Return-to-playhead button.
 * - Selection (§13.4): click seeks (3 px click/drag threshold), drag
 *   selects, boundary handles, Escape clears, start/end/duration readout.
 * - Vertical zoom (§13.3): per-lane amplitude, linked scaling, reset,
 *   localStorage persistence.
 * - Position readout (§13.5.5): `frame N · m:ss.mmm` chip over the lanes.
 *
 * The component stores a width-free `View` (start frame + fpp); the full
 * `Viewport` is derived with `useMemo` (stable identity) and passed to
 * `useWaveform`, which fetches and decodes exactly that window. Manual
 * zoom/pan suspends playhead follow; the follow effect re-pans only when a
 * position update lands outside the visible range (state changes only when
 * needed, so 60 Hz playhead updates do not cause render loops).
 *
 * Canvas layers (§12.3): waveform / grid / selection / markers / playhead.
 * Only the playhead canvases are redrawn on position updates. Each canvas
 * is allocated in device pixels (`css × devicePixelRatio`) and drawn in CSS
 * pixels after a DPR transform (§12.4).
 *
 * States (§12.8): `empty` / `decoding` / `pending` / `missing` render an
 * overlay (with a rebuild button for `missing`); `ready` renders the
 * layout. A `ready` editor whose tiles are still building draws the
 * available tiles and leaves the rest blank (progressive).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formatTime } from '../playback/pcm'
import {
  drawLaneGrid,
  drawLaneWaveform,
  drawOverview,
  drawOverviewWindow,
  drawPcmWaveform,
  drawPlayhead,
  drawRuler,
  drawSamplePoints,
  drawSelection,
  type BucketSource,
  type PcmPixelSource,
  type SampleSource,
  type WaveformContext,
} from './render'
import {
  clampView,
  fitRangeView,
  frameToX,
  makeViewport,
  panView,
  visibleFrames,
  xToFrame,
  zoomView,
  type View,
  type Viewport,
} from './viewport'
import { TILE_BUCKETS } from './levels'
import { useWaveform, type PcmData, type WaveformLevelData } from './useWaveform'

export interface WaveformEditorProps {
  projectId: string
  /** Canonical source asset; null when no source has been imported. */
  sourceAssetId: string | null
  /** Playhead position in project frames (canonical rate). */
  playheadFrame: number
  /** Seek the transport to a project frame (M1.11 click / selection). */
  onSeek?: (projectFrame: number) => void
}

/** Layout constants (CSS px). */
const LANE_HEIGHT = 48
const OVERVIEW_HEIGHT = 44
const RULER_HEIGHT = 24
const LANE_AREA_HEIGHT = 240

/** The five stacked layers of a lane (spec §12.3), bottom to top. */
const LAYERS = ['waveform', 'grid', 'selection', 'markers', 'playhead'] as const

/** Display amplitude range (spec §13.3.1). */
const AMP_MIN = 0.25
const AMP_MAX = 16
/** Below this pointer travel a down/up pair is a click, not a drag (§13.4.2). */
const DRAG_THRESHOLD_PX = 3
/** Boundary handle hit radius in CSS px (§13.4.8). */
const HANDLE_HIT_PX = 4

interface AmpState {
  linked: boolean
  scales: number[]
}

function ampKey(projectId: string): string {
  return `basseparate:wave-amplitude:${projectId}`
}

/** Read persisted amplitude state; null when absent or malformed. */
function readAmp(projectId: string): AmpState | null {
  try {
    const raw = window.localStorage.getItem(ampKey(projectId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { linked?: unknown; scales?: unknown }
    if (typeof parsed.linked !== 'boolean' || !Array.isArray(parsed.scales)) return null
    return { linked: parsed.linked, scales: parsed.scales as number[] }
  } catch {
    return null
  }
}

function clampScale(scale: number): number {
  return Math.max(AMP_MIN, Math.min(AMP_MAX, scale))
}

/** Derived lane labels (layout-aware labels are a later polish). */
function channelLabel(count: number, i: number): string {
  if (count === 1) return 'Mono'
  if (count === 2) return i === 0 ? 'L' : 'R'
  return `Ch ${i}`
}

/**
 * One channel's bucket source for a decoded level. Buckets are laid out
 * `[channel][bucket]`, so a channel's buckets straddle tile boundaries;
 * the source answers per-bucket from the tile map.
 */
function bucketSourceFor(
  level: WaveformLevelData,
  bucketCount: number,
  channel: number,
): BucketSource {
  const tiles = level.tiles
  const bfc = level.bucketFrameCount
  return {
    bucketFrameCount: bfc,
    bucketCount,
    bucketAt: (i) => {
      const t = Math.floor(i / TILE_BUCKETS)
      const b = i % TILE_BUCKETS
      const tile = tiles.get(t)
      if (!tile) return null
      const min = tile.minima[channel]?.[b]
      const max = tile.maxima[channel]?.[b]
      return typeof min === 'number' && typeof max === 'number' ? [min, max] : null
    },
  }
}

/** One channel's per-pixel source for a decoded PCM pixel window. */
function pcmPixelSourceFor(
  pcm: Extract<PcmData, { kind: 'pixels' }>,
  channel: number,
): PcmPixelSource {
  const d = pcm.data
  return {
    startFrame: pcm.startFrame,
    pixelCount: d.pixels,
    pixelAt: (i) => {
      if (i < 0 || i >= d.pixels) return null
      return [d.minima[channel][i], d.maxima[channel][i]]
    },
  }
}

/** One channel's deinterleaved sample source for a decoded PCM sample window. */
function sampleSourceFor(
  pcm: Extract<PcmData, { kind: 'samples' }>,
  channel: number,
): SampleSource {
  return {
    startFrame: pcm.startFrame,
    samples: pcm.channels[channel] ?? new Float32Array(0),
  }
}

/**
 * One stacked canvas layer. The canvas is allocated in device pixels and
 * handed to `register` as a 2D context pre-scaled to CSS pixels
 * (§12.4); null in environments without 2D canvas (jsdom tests stub it).
 */
function CanvasLayer({
  id,
  width,
  height,
  register,
  className,
}: {
  id: string
  width: number
  height: number
  register: (id: string, ctx: WaveformContext | null) => void
  className?: string
}) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const dpr = Math.max(1, Math.min(4, window.devicePixelRatio || 1))
    const w = Math.max(1, Math.round(width * dpr))
    const h = Math.max(1, Math.round(height * dpr))
    if (canvas.width !== w) canvas.width = w
    if (canvas.height !== h) canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      register(id, null)
      return
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    // The painters need only the structural subset; the wider DOM type
    // (fillStyle may be a gradient/pattern) is not.
    register(id, ctx as unknown as WaveformContext)
    return () => register(id, null)
  }, [id, width, height, register])

  return <canvas ref={ref} className={className} data-id={id} style={{ width, height }} />
}

type DragMode = 'maybe' | 'drag' | 'resize-start' | 'resize-end'

export function WaveformEditor({
  projectId,
  sourceAssetId,
  playheadFrame,
  onSeek,
}: WaveformEditorProps) {
  const [contentWidth, setContentWidth] = useState(0)
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  /** The width-free view; null until the duration and width are known. */
  const [view, setView] = useState<View | null>(null)
  /** Selection in source frames, `end` exclusive, start < end. */
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null)
  const [followPlayhead, setFollowPlayhead] = useState(true)
  const [amp, setAmp] = useState<AmpState>(() => readAmp(projectId) ?? { linked: true, scales: [] })
  const [pointerFrame, setPointerFrame] = useState<number | null>(null)
  const [scrollTop, setScrollTop] = useState(0)

  const contentRef = useRef<HTMLDivElement | null>(null)
  const hitRef = useRef<HTMLDivElement | null>(null)
  const ctxRef = useRef(new Map<string, WaveformContext>())
  const laneDragRef = useRef<{ mode: DragMode; downX: number; downFrame: number } | null>(null)
  const scrollDragRef = useRef<{ lastX: number } | null>(null)
  const overviewDragRef = useRef<{ lastX: number } | null>(null)

  /**
   * The full viewport for the data hook. Derived (not state) so its
   * identity changes only when the view or the measured width changes —
   * the hook's data effect keys on that identity.
   */
  const viewport: Viewport | null = useMemo(
    () => (view && contentWidth > 0 ? makeViewport(view.startFrame, view.fpp, contentWidth) : null),
    [view, contentWidth],
  )

  const { state, manifest, levels, pcm, overview, error, rebuild } = useWaveform(
    projectId,
    sourceAssetId,
    viewport,
  )

  const register = useCallback((id: string, ctx: WaveformContext | null) => {
    if (ctx) ctxRef.current.set(id, ctx)
    else ctxRef.current.delete(id)
  }, [])

  const duration = manifest?.frame_count ?? 0
  const sampleRate = manifest?.sample_rate ?? 0

  // Measure the content column (CSS px); every canvas row shares its width.
  useEffect(() => {
    if (state !== 'ready') return
    const el = contentRef.current
    if (!el) return
    if (typeof ResizeObserver === 'undefined') {
      setContentWidth(Math.floor(el.getBoundingClientRect().width))
      return
    }
    const ro = new ResizeObserver((entries) => {
      setContentWidth(Math.floor(entries[0]?.contentRect.width ?? 0))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [state])

  // Reset navigation state when the source changes.
  useEffect(() => {
    setView(null)
    setSelection(null)
    setFollowPlayhead(true)
    setPointerFrame(null)
  }, [projectId, sourceAssetId])

  // Fit the whole song once the duration and width are known.
  useEffect(() => {
    if (state === 'ready' && manifest && contentWidth > 0 && view === null) {
      setView({ startFrame: 0, fpp: manifest.frame_count / contentWidth })
    }
  }, [state, manifest, contentWidth, view])

  // Re-clamp the start frame when the width changes (zoom is preserved);
  // only writes state when the value actually changes.
  useEffect(() => {
    if (!view || !manifest || contentWidth <= 0) return
    const clamped = clampView(view, manifest.frame_count, contentWidth)
    if (clamped.startFrame !== view.startFrame) setView(clamped)
  }, [view, manifest, contentWidth])

  // Follow the playhead (§13.2.6): pan only when a position update lands
  // outside the visible range, so 60 Hz updates do not loop.
  useEffect(() => {
    if (!followPlayhead || !view || !manifest || contentWidth <= 0) return
    const visible = visibleFrames(view, contentWidth)
    if (playheadFrame >= view.startFrame && playheadFrame <= view.startFrame + visible) return
    setView(
      clampView(
        { startFrame: playheadFrame - visible / 2, fpp: view.fpp },
        manifest.frame_count,
        contentWidth,
      ),
    )
  }, [playheadFrame, followPlayhead, view, manifest, contentWidth])

  // Persist the amplitude state once the channel count is known.
  useEffect(() => {
    if (amp.scales.length === 0) return
    try {
      window.localStorage.setItem(ampKey(projectId), JSON.stringify(amp))
    } catch {
      // Storage unavailable: non-fatal.
    }
  }, [amp, projectId])

  const channelCount = manifest?.channel_count ?? 0
  const labels = useMemo(
    () => Array.from({ length: channelCount }, (_, i) => channelLabel(channelCount, i)),
    [channelCount],
  )
  const shownLanes = useMemo(
    () => labels.map((_, i) => i).filter((i) => !hidden.has(i)),
    [labels, hidden],
  )

  // Per-lane amplitude validated against the channel count (§13.3.6): a
  // length mismatch or out-of-range value resets to the 1× default.
  const scales = useMemo(() => {
    if (channelCount === 0) return []
    const ok =
      amp.scales.length === channelCount &&
      amp.scales.every((s) => typeof s === 'number' && s >= AMP_MIN && s <= AMP_MAX)
    return ok ? amp.scales : Array.from({ length: channelCount }, () => 1)
  }, [amp, channelCount])

  const linked = amp.linked
  const ampValue = scales[0] ?? 1

  const setLinked = useCallback((value: boolean) => {
    setAmp((prev) => ({ linked: value, scales: prev.scales }))
  }, [])

  const ampZoomAll = useCallback(
    (factor: number) => {
      setAmp({ linked: true, scales: scales.map((s) => clampScale(s * factor)) })
    },
    [scales],
  )

  const ampZoomLane = useCallback(
    (lane: number, factor: number) => {
      setAmp({
        linked: false,
        scales: scales.map((s, i) => (i === lane ? clampScale(s * factor) : s)),
      })
    },
    [scales],
  )

  const ampReset = useCallback(() => {
    setAmp({ linked: true, scales: Array.from({ length: scales.length }, () => 1) })
  }, [scales])

  const toggleHidden = useCallback((i: number) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }, [])

  // --- navigation actions (§13.1–13.2) -------------------------------------

  /** Apply a manual view change: suspends playhead follow (§13.2.6). */
  const commitView = useCallback((next: View) => {
    setView(next)
    setFollowPlayhead(false)
  }, [])

  const zoomAt = useCallback(
    (factor: number, anchorFrame: number) => {
      if (!view || !manifest || contentWidth <= 0) return
      commitView(zoomView(view, factor, anchorFrame, manifest.frame_count, contentWidth))
    },
    [view, manifest, contentWidth, commitView],
  )

  const centerOn = useCallback(
    (frame: number) => {
      if (!view || !manifest || contentWidth <= 0) return
      const visible = visibleFrames(view, contentWidth)
      setView(
        clampView(
          { startFrame: frame - visible / 2, fpp: view.fpp },
          manifest.frame_count,
          contentWidth,
        ),
      )
    },
    [view, manifest, contentWidth],
  )

  const zoomIn = useCallback(() => {
    if (!viewport) return
    zoomAt(0.5, xToFrame(viewport, contentWidth / 2))
  }, [viewport, contentWidth, zoomAt])

  const zoomOut = useCallback(() => {
    if (!viewport) return
    zoomAt(2, xToFrame(viewport, contentWidth / 2))
  }, [viewport, contentWidth, zoomAt])

  const fitSong = useCallback(() => {
    if (!manifest || contentWidth <= 0) return
    commitView({ startFrame: 0, fpp: manifest.frame_count / contentWidth })
  }, [manifest, contentWidth, commitView])

  const fitSelectionAction = useCallback(() => {
    if (!manifest || !selection || contentWidth <= 0) return
    commitView(
      clampView(
        fitRangeView(selection.start, selection.end, contentWidth),
        manifest.frame_count,
        contentWidth,
      ),
    )
  }, [manifest, selection, contentWidth, commitView])

  const returnToPlayhead = useCallback(() => {
    centerOn(playheadFrame)
    setFollowPlayhead(true)
  }, [centerOn, playheadFrame])

  const playheadOutside = useMemo(() => {
    if (!view || !manifest || contentWidth <= 0) return false
    const end = view.startFrame + visibleFrames(view, contentWidth)
    return playheadFrame < view.startFrame || playheadFrame > end
  }, [view, manifest, contentWidth, playheadFrame])

  // --- lane pointer interaction: click / drag / resize (§13.4) --------------

  const laneX = useCallback(
    (clientX: number) => {
      const el = hitRef.current
      if (!el) return 0
      const rect = el.getBoundingClientRect()
      return Math.max(0, Math.min(contentWidth, clientX - rect.left))
    },
    [contentWidth],
  )

  const onLanePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!viewport || !manifest) return
      e.preventDefault()
      const x = laneX(e.clientX)
      let mode: DragMode = 'maybe'
      if (selection) {
        const x0 = frameToX(viewport, selection.start)
        const x1 = frameToX(viewport, selection.end)
        if (Math.abs(x - x0) <= HANDLE_HIT_PX) mode = 'resize-start'
        else if (Math.abs(x - x1) <= HANDLE_HIT_PX) mode = 'resize-end'
      }
      laneDragRef.current = { mode, downX: x, downFrame: xToFrame(viewport, x) }
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        // No pointer capture (jsdom): the drag still works.
      }
    },
    [viewport, manifest, selection, laneX],
  )

  const onLanePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!viewport || !manifest) return
      const x = laneX(e.clientX)
      setPointerFrame(Math.round(xToFrame(viewport, x)))
      const drag = laneDragRef.current
      if (!drag) return
      const d = manifest.frame_count
      if (drag.mode === 'maybe' || drag.mode === 'drag') {
        if (drag.mode === 'maybe' && Math.abs(x - drag.downX) <= DRAG_THRESHOLD_PX) return
        drag.mode = 'drag'
        const a = Math.min(drag.downFrame, xToFrame(viewport, x))
        const b = Math.max(drag.downFrame, xToFrame(viewport, x))
        const start = Math.max(0, Math.floor(a))
        let end = Math.min(d, Math.ceil(b))
        if (end <= start) end = Math.min(d, start + 1)
        setSelection({ start, end })
        return
      }
      // Resize one boundary; the range never crosses (spec §13.4.8).
      const frame = Math.round(xToFrame(viewport, x))
      setSelection((prev) => {
        if (!prev) return prev
        if (drag.mode === 'resize-start') {
          return { start: Math.max(0, Math.min(frame, prev.end - 1)), end: prev.end }
        }
        return { start: prev.start, end: Math.min(d, Math.max(frame, prev.start + 1)) }
      })
    },
    [viewport, manifest, laneX],
  )

  const onLanePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = laneDragRef.current
      laneDragRef.current = null
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        // No pointer capture: nothing to release.
      }
      // A down/up pair below the drag threshold is a click: seek (§13.4.2).
      if (!drag || drag.mode !== 'maybe' || !viewport || !manifest) return
      const frame = Math.round(xToFrame(viewport, laneX(e.clientX)))
      onSeek?.(Math.max(0, Math.min(manifest.frame_count, frame)))
    },
    [viewport, manifest, laneX, onSeek],
  )

  const onLanePointerLeave = useCallback(() => {
    if (!laneDragRef.current) setPointerFrame(null)
  }, [])

  // Ctrl/Cmd-wheel zoom + Shift-wheel pan. Native non-passive listener:
  // React root wheel listeners are passive, so `preventDefault` must go
  // through the DOM (spec §13.1.6, §13.2.5).
  useEffect(() => {
    const el = hitRef.current
    if (!el || !viewport || !view || !manifest || contentWidth <= 0) return
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey) && !e.shiftKey) return
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const x = Math.max(0, Math.min(contentWidth, e.clientX - rect.left))
      const d = manifest.frame_count
      if (e.ctrlKey || e.metaKey) {
        const factor = e.deltaY < 0 ? 0.8 : 1.25
        setView(zoomView(view, factor, xToFrame(viewport, x), d, contentWidth))
      } else {
        const delta = (e.deltaX || e.deltaY) * viewport.framesPerCssPixel
        setView(panView(view, delta, d, contentWidth))
      }
      setFollowPlayhead(false)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [viewport, view, manifest, contentWidth])

  // Keyboard zoom + Escape (§13.1.5, §13.4.6).
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.key === 'Escape') {
        if (selection) {
          e.preventDefault()
          setSelection(null)
        }
        return
      }
      if (!viewport || !manifest) return
      if (e.key === '+' || e.key === '=') {
        e.preventDefault()
        zoomAt(0.5, Math.max(0, Math.min(manifest.frame_count, playheadFrame)))
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault()
        zoomAt(2, Math.max(0, Math.min(manifest.frame_count, playheadFrame)))
      }
    },
    [selection, viewport, manifest, playheadFrame, zoomAt],
  )

  // --- scrollbar (§13.2.4) ---------------------------------------------------

  const visible = viewport ? contentWidth * viewport.framesPerCssPixel : 0
  const thumbWidth =
    duration > 0 && contentWidth > 0
      ? Math.max(
          24,
          Math.min(contentWidth, (contentWidth * Math.min(visible, duration)) / duration),
        )
      : contentWidth
  const thumbLeft =
    viewport && duration > 0 && contentWidth > 0
      ? Math.min((viewport.startFrame / duration) * contentWidth, contentWidth - thumbWidth)
      : 0

  const onScrollPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!view || !manifest || contentWidth <= 0) return
      e.preventDefault()
      const rect = e.currentTarget.getBoundingClientRect()
      const x = Math.max(0, Math.min(contentWidth, e.clientX - rect.left))
      const d = manifest.frame_count
      const onThumb = x >= thumbLeft && x <= thumbLeft + thumbWidth
      if (!onThumb) {
        // Track click jumps the view so its center sits under the pointer.
        setView(
          clampView(
            { startFrame: (x / contentWidth) * d - visible / 2, fpp: view.fpp },
            d,
            contentWidth,
          ),
        )
      }
      scrollDragRef.current = { lastX: x }
      setFollowPlayhead(false)
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        // No pointer capture (jsdom): the drag still works.
      }
    },
    [view, manifest, contentWidth, thumbLeft, thumbWidth, visible],
  )

  const onScrollPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = scrollDragRef.current
      if (!drag || !view || !manifest || contentWidth <= 0) return
      const rect = e.currentTarget.getBoundingClientRect()
      const x = Math.max(0, Math.min(contentWidth, e.clientX - rect.left))
      const delta = ((x - drag.lastX) / contentWidth) * manifest.frame_count
      drag.lastX = x
      setView(panView(view, delta, manifest.frame_count, contentWidth))
    },
    [view, manifest, contentWidth],
  )

  const onScrollPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    scrollDragRef.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // No pointer capture: nothing to release.
    }
  }, [])

  // --- overview drag (§13.2.3) -----------------------------------------------

  const onOverviewPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!manifest || contentWidth <= 0) return
      e.preventDefault()
      const rect = e.currentTarget.getBoundingClientRect()
      overviewDragRef.current = { lastX: e.clientX - rect.left }
      setFollowPlayhead(false)
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        // No pointer capture (jsdom): the drag still works.
      }
    },
    [manifest, contentWidth],
  )

  const onOverviewPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = overviewDragRef.current
      if (!drag || !view || !manifest || contentWidth <= 0) return
      const rect = e.currentTarget.getBoundingClientRect()
      const x = e.clientX - rect.left
      const delta = (x - drag.lastX) * (manifest.frame_count / contentWidth)
      drag.lastX = x
      setView(panView(view, delta, manifest.frame_count, contentWidth))
    },
    [view, manifest, contentWidth],
  )

  const onOverviewPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    overviewDragRef.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // No pointer capture: nothing to release.
    }
  }, [])

  const level = levels[0] ?? null

  // Virtualized lane rows: draw only the lanes inside the scroll window.
  const firstIdx = Math.max(0, Math.floor(scrollTop / LANE_HEIGHT) - 1)
  const lastIdx = Math.min(
    shownLanes.length,
    Math.ceil((scrollTop + LANE_AREA_HEIGHT) / LANE_HEIGHT) + 1,
  )
  const drawnLanes = shownLanes.slice(firstIdx, lastIdx)
  const drawnKey = drawnLanes.join('|')

  // Overview strip + viewport window indicator, lane waveforms, lane grids.
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    const ovCtx = ctxRef.current.get('overview')
    if (ovCtx) {
      ovCtx.clearRect(0, 0, contentWidth, OVERVIEW_HEIGHT)
      if (overview) {
        drawOverview(
          ovCtx,
          labels.map((_, c) =>
            bucketSourceFor(overview, manifest.levels[overview.level].bucket_count, c),
          ),
          contentWidth,
          OVERVIEW_HEIGHT,
        )
      }
      if (duration > 0) {
        const ovFpp = duration / contentWidth
        const x0 = Math.max(0, viewport.startFrame / ovFpp)
        const x1 = Math.min(contentWidth, (viewport.startFrame + visible) / ovFpp)
        if (x1 > x0) drawOverviewWindow(ovCtx, x0, x1, OVERVIEW_HEIGHT)
      }
    }
    for (const ch of shownLanes) {
      const wctx = ctxRef.current.get(`lane:${ch}:waveform`)
      if (wctx) {
        wctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
        const laneOpts = { height: LANE_HEIGHT, amplitudeScale: scales[ch] ?? 1 }
        if (level) {
          drawLaneWaveform(
            wctx,
            bucketSourceFor(level, manifest.levels[level.level].bucket_count, ch),
            viewport,
            0,
            contentWidth,
            laneOpts,
          )
        } else if (pcm?.kind === 'pixels') {
          drawPcmWaveform(wctx, pcmPixelSourceFor(pcm, ch), viewport, 0, contentWidth, laneOpts)
        } else if (pcm?.kind === 'samples') {
          drawSamplePoints(wctx, sampleSourceFor(pcm, ch), viewport, 0, contentWidth, laneOpts)
        }
      }
      const gctx = ctxRef.current.get(`lane:${ch}:grid`)
      if (gctx) {
        gctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
        drawLaneGrid(gctx, contentWidth, LANE_HEIGHT)
      }
    }
  }, [
    state,
    viewport,
    manifest,
    level,
    pcm,
    overview,
    contentWidth,
    scales,
    shownLanes,
    drawnKey,
    duration,
    visible,
    labels,
  ])

  // Selection layer: the range plus a handle at each boundary (§13.4.7).
  useEffect(() => {
    if (state !== 'ready' || !viewport || contentWidth <= 0) return
    for (const ch of shownLanes) {
      const sctx = ctxRef.current.get(`lane:${ch}:selection`)
      if (!sctx) continue
      sctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
      if (selection) {
        const x0 = frameToX(viewport, selection.start)
        const x1 = frameToX(viewport, selection.end)
        if (x1 > 0 && x0 < contentWidth) {
          drawSelection(sctx, Math.max(0, x0), Math.min(contentWidth, x1), LANE_HEIGHT)
        }
      }
    }
  }, [state, viewport, selection, contentWidth, shownLanes, drawnKey])

  // Ruler (redrawn when the viewport changes).
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    const rctx = ctxRef.current.get('ruler')
    if (!rctx) return
    rctx.clearRect(0, 0, contentWidth, RULER_HEIGHT)
    drawRuler(rctx, viewport, contentWidth, {
      sampleRate: manifest.sample_rate,
      height: RULER_HEIGHT,
    })
  }, [state, viewport, manifest, contentWidth])

  // Playhead: redraw only the per-lane playhead layers on position changes.
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    const x = frameToX(viewport, Math.min(playheadFrame, manifest.frame_count))
    if (x < 0 || x > contentWidth) return
    for (const ch of shownLanes) {
      const pctx = ctxRef.current.get(`lane:${ch}:playhead`)
      if (!pctx) continue
      pctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
      drawPlayhead(pctx, x, LANE_HEIGHT)
    }
  }, [state, viewport, manifest, playheadFrame, contentWidth, shownLanes, drawnKey])

  // Non-ready states: a single overlay with the state-specific action.
  if (state !== 'ready') {
    return (
      <section className="waveform-editor waveform-editor--state" aria-label="Waveform editor">
        <p className="waveform-state-text">
          {state === 'empty' &&
            'No source imported yet. Import a file above to build its waveform.'}
          {state === 'decoding' && 'Building the waveform…'}
          {state === 'pending' &&
            'Waveform build queued. It will appear here when the build finishes.'}
          {state === 'missing' && 'The waveform data is missing. Rebuild it to recover.'}
        </p>
        {state === 'missing' && (
          <button type="button" onClick={rebuild} disabled={!sourceAssetId}>
            Rebuild waveform
          </button>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
      </section>
    )
  }

  return (
    <section
      className="waveform-editor"
      aria-label="Waveform editor"
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      {/* Overview strip: the whole source; drag to pan (§13.2.3). */}
      <div className="wave-row wave-overview-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div
          className="wave-content"
          ref={contentRef}
          onPointerDown={onOverviewPointerDown}
          onPointerMove={onOverviewPointerMove}
          onPointerUp={onOverviewPointerUp}
        >
          <CanvasLayer
            id="overview"
            width={contentWidth}
            height={OVERVIEW_HEIGHT}
            register={register}
            className="wave-canvas"
          />
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      {/* Time ruler. */}
      <div className="wave-row wave-ruler-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-content">
          <CanvasLayer
            id="ruler"
            width={contentWidth}
            height={RULER_HEIGHT}
            register={register}
            className="wave-canvas"
          />
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      {/* Lanes: five stacked canvas layers per channel + click/drag surface. */}
      <div className="wave-lane-row-wrap">
        <div
          className="wave-lane-area"
          style={{ height: LANE_AREA_HEIGHT }}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        >
          <div className="wave-lane-track" style={{ height: shownLanes.length * LANE_HEIGHT }}>
            {drawnLanes.map((ch, k) => (
              <div
                key={ch}
                className="wave-lane-row"
                style={{ top: (firstIdx + k) * LANE_HEIGHT }}
                data-channel={ch}
              >
                <span className="wave-lane-label">
                  {labels[ch]}
                  {!linked && (
                    <span className="wave-lane-amp">
                      <button
                        type="button"
                        className="wave-lane-amp-btn"
                        aria-label={`Decrease ${labels[ch]} amplitude`}
                        disabled={scales[ch] <= AMP_MIN}
                        onClick={() => ampZoomLane(ch, 0.5)}
                      >
                        −
                      </button>
                      <button
                        type="button"
                        className="wave-lane-amp-btn"
                        aria-label={`Increase ${labels[ch]} amplitude`}
                        disabled={scales[ch] >= AMP_MAX}
                        onClick={() => ampZoomLane(ch, 2)}
                      >
                        +
                      </button>
                    </span>
                  )}
                </span>
                <div className="wave-lane-stack">
                  {LAYERS.map((layer) => (
                    <CanvasLayer
                      key={layer}
                      id={`lane:${ch}:${layer}`}
                      width={contentWidth}
                      height={LANE_HEIGHT}
                      register={register}
                      className="wave-canvas"
                    />
                  ))}
                </div>
                <button
                  type="button"
                  className="wave-lane-collapse"
                  aria-label={`Hide ${labels[ch]}`}
                  onClick={() => toggleHidden(ch)}
                >
                  –
                </button>
              </div>
            ))}
            {/* Transparent hit surface over the lane canvases: click seeks,
                drag selects, boundary handles resize (§13.4). */}
            <div
              className="wave-lane-hitarea"
              ref={hitRef}
              onPointerDown={onLanePointerDown}
              onPointerMove={onLanePointerMove}
              onPointerUp={onLanePointerUp}
              onPointerLeave={onLanePointerLeave}
            />
          </div>
        </div>
        {pointerFrame !== null && sampleRate > 0 && (
          <div className="wave-frame-readout" aria-hidden="true">
            frame {pointerFrame} · {formatTime(pointerFrame, sampleRate)}
          </div>
        )}
      </div>

      {/* Marker lane (M1.11 renders the lane only; markers are M1.13). */}
      <div className="wave-row wave-marker-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-marker-lane" aria-label="Markers">
          <span className="muted">Markers</span>
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      {/* Selection readout: start – end · duration + actions (§13.4.9). */}
      <div className="wave-row wave-selection-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-selection-readout" aria-label="Selection">
          {selection && sampleRate > 0 ? (
            <>
              <span>
                {formatTime(selection.start, sampleRate)} – {formatTime(selection.end, sampleRate)}{' '}
                · {formatTime(selection.end - selection.start, sampleRate)}
              </span>
              <button type="button" onClick={() => onSeek?.(selection.start)}>
                Seek to selection start
              </button>
              <button type="button" onClick={() => setSelection(null)}>
                Clear
              </button>
            </>
          ) : (
            '—'
          )}
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      {/* Horizontal scrollbar: track click jumps, thumb drag pans. */}
      <div className="wave-row wave-scrollbar-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div
          className="wave-scrollbar"
          aria-label="Waveform scrollbar"
          onPointerDown={onScrollPointerDown}
          onPointerMove={onScrollPointerMove}
          onPointerUp={onScrollPointerUp}
        >
          <div
            className="wave-scrollbar-thumb"
            style={{ width: `${thumbWidth}px`, left: `${thumbLeft}px` }}
          />
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      <div className="wave-controls">
        {playheadOutside && (
          <button type="button" className="wave-return-playhead" onClick={returnToPlayhead}>
            Return to playhead
          </button>
        )}
        <fieldset className="wave-channel-controls">
          <legend>Channels</legend>
          {labels.map((label, i) => (
            <label key={i} className="wave-channel-toggle">
              <input
                type="checkbox"
                checked={!hidden.has(i)}
                onChange={() => toggleHidden(i)}
                aria-label={`Show ${label}`}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <fieldset className="wave-horizontal-controls">
          <legend>Horizontal zoom</legend>
          <button type="button" aria-label="Zoom in (horizontal)" onClick={zoomIn}>
            Zoom in
          </button>
          <button type="button" aria-label="Zoom out (horizontal)" onClick={zoomOut}>
            Zoom out
          </button>
          <button type="button" onClick={fitSong}>
            Fit song
          </button>
          <button type="button" onClick={fitSelectionAction} disabled={!selection}>
            Fit selection
          </button>
        </fieldset>
        <fieldset className="wave-amplitude-controls">
          <legend>Display amplitude</legend>
          <button
            type="button"
            onClick={() => ampZoomAll(2)}
            disabled={!linked || ampValue >= AMP_MAX}
          >
            Zoom in
          </button>
          <button
            type="button"
            onClick={() => ampZoomAll(0.5)}
            disabled={!linked || ampValue <= AMP_MIN}
          >
            Zoom out
          </button>
          <button type="button" onClick={ampReset} disabled={scales.every((s) => s === 1)}>
            Reset
          </button>
          <span className="wave-amplitude-value" aria-live="polite">
            {linked ? `${ampValue}×` : 'unlinked'}
          </span>
          <label className="wave-link-toggle">
            <input
              type="checkbox"
              checked={linked}
              onChange={(e) => setLinked(e.target.checked)}
              aria-label="Link channels"
            />
            Link channels
          </label>
        </fieldset>
      </div>

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
