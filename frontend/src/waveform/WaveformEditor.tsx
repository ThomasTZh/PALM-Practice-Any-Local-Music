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
 *   overview-window drag, page-follow (M1.14 §16.4: 80 % trigger /
 *   20 % landing, manual navigation suspends, persisted visible
 *   control) with a Return-to-playhead button.
 * - Playhead (M1.14 §16.5): one rAF loop reads the audible
 *   `playheadSource` and redraws the per-lane playhead canvases only
 *   on ≥ 0.5 px movement — no per-update React state.
 * - Selection (§13.4): click seeks (3 px click/drag threshold), drag
 *   selects, boundary handles, Escape clears, start/end/duration readout.
 * - Vertical zoom (§13.3): per-lane amplitude, linked scaling, reset,
 *   localStorage persistence.
 * - Position readout (§13.5.5): `frame N · m:ss.mmm` chip over the lanes.
 *
 * The component stores a width-free `View` (start frame + fpp); the full
 * `Viewport` is derived with `useMemo` (stable identity) and passed to
 * `useWaveform`, which fetches and decodes exactly that window. Manual
 * zoom/pan suspends playhead follow (the rAF loop re-pans at the 80 %
 * trigger while following; state changes only when needed, so 60 Hz
 * playhead updates do not cause render loops).
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
import type { Marker } from '../api/commands'
import { formatTime } from '../playback/pcm'
import {
  drawLaneGrid,
  drawLaneWaveform,
  drawLoop,
  drawMarkerFlag,
  drawMarkerTick,
  drawOverview,
  drawOverviewWindow,
  drawPcmWaveform,
  drawPlayhead,
  drawRuler,
  drawSamplePoints,
  drawSelection,
  MARKER_COLORS,
  MARKER_FLAG_WIDTH,
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

/**
 * Audible playhead source (M1.14 §16.5): display-only reads. The loop
 * never calls into the transport for control.
 */
export interface PlayheadSource {
  /** Current playhead position in project frames (interpolated). */
  getPosition: () => number
  /** True while playback is active (playing / seeking). */
  isPlaying: () => boolean
}

/**
 * The shared timeline view (M2.8, spec §10.1.4): the width-free zoom/pan
 * state plus the measured content width. One instance drives every lane.
 */
export interface SharedView {
  startFrame: number
  fpp: number
  widthCssPx: number
}

/** Read-only getter over the editor's current shared view (null pre-ready). */
export interface ViewSource {
  get: () => SharedView | null
}

/** Channel display state (M1.15 §17.4): link + per-channel scales. */
export interface ChannelDisplay {
  linked: boolean
  scales: number[]
}

/** The practice loop drawn on the lanes (M2.11 §13.2.3–4), source frames. */
export interface LoopRange {
  /** Start source frame (inclusive). */
  start: number
  /** End source frame (exclusive). */
  end: number
  /** Loop color (hex). */
  color: string
}

export interface WaveformEditorProps {
  projectId: string
  /** Canonical source asset; null when no source has been imported. */
  sourceAssetId: string | null
  /** Audible playhead (M1.14); absent → no playhead, no follow. */
  playheadSource?: PlayheadSource
  /** Seek the transport to a project frame (M1.11 click / selection). */
  onSeek?: (projectFrame: number) => void
  /**
   * Register a getter over the editor's shared view (M2.8, spec §10.1.4)
   * so sibling lanes (the stem track stack) follow the same zoom/pan.
   * Called once with a source on mount, and with null on unmount.
   */
  registerView?: (source: ViewSource | null) => void
  /**
   * Restored working state (M1.15 §17.6). Each is applied once, when the
   * editor first becomes ready; null → the legacy behavior (fit view, no
   * selection, localStorage amplitude, legacy follow preference).
   */
  initialViewport?: View | null
  initialSelection?: { start: number; end: number } | null
  initialChannelDisplay?: ChannelDisplay | null
  initialFollow?: boolean | null
  /**
   * Autosave callbacks (M1.15 §17.5): fire on committed changes after the
   * restored values have been applied; the caller debounces and sends.
   */
  onViewportChange?: (view: View) => void
  onSelectionChange?: (selection: { start: number; end: number } | null) => void
  onChannelDisplayChange?: (display: ChannelDisplay) => void
  onFollowChange?: (follow: boolean) => void
  /**
   * The active practice loop to draw and drag (M2.11 §13.2.3–4); null →
   * no overlay. The boundary handles resize and a body drag moves the
   * interval; Shift+drag inside the loop keeps the selection gesture.
   */
  loop?: LoopRange | null
  /** Commit a loop range edit on drag end (exactly one per gesture). */
  onLoopRangeChange?: (start: number, end: number) => void
  /**
   * Marker state (M1.15 §17.2). All optional: absent → the marker row
   * renders its empty state (no flags, no list, no add/prev/next).
   */
  markers?: Marker[]
  selectedMarkerId?: string | null
  /** Add at the playhead (§17.2.1) or at a ruler frame (§17.2.2). */
  onAddMarker?: (frame: number) => void
  /** Drag commit: exactly one move per gesture (§17.2.4/§17.4.7). */
  onMoveMarker?: (id: string, frame: number) => void
  /** List edits: label / color / exact frame (§17.2.3/§17.2.5/§17.2.6). */
  onUpdateMarker?: (
    id: string,
    patch: { label?: string; color?: string; positionFrames?: number },
  ) => void
  onDeleteMarker?: (id: string) => void
  /** Select without seeking (§17.2.9); null clears the selection. */
  onSelectMarker?: (id: string | null) => void
  /** Double-click a flag: seek + select (§17.2.10). */
  onSeekToMarker?: (frame: number) => void
  onUndo?: () => void
  onRedo?: () => void
  canUndo?: boolean
  canRedo?: boolean
}

/** Layout constants (CSS px). */
const LANE_HEIGHT = 48
const OVERVIEW_HEIGHT = 44
const RULER_HEIGHT = 24
const MARKER_ROW_HEIGHT = 24
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

/** Follow-playhead preference key (global, M1.14 §16.4). */
const FOLLOW_KEY = 'basseparate.playheadFollow'

/** Read the persisted follow preference; on (default) when absent. */
function readFollowPref(): boolean {
  try {
    const raw = window.localStorage.getItem(FOLLOW_KEY)
    return raw === null ? true : raw === 'true'
  } catch {
    return true
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

type DragMode =
  'maybe' | 'drag' | 'resize-start' | 'resize-end' | 'loop-start' | 'loop-end' | 'loop-move'

export function WaveformEditor({
  projectId,
  sourceAssetId,
  playheadSource,
  onSeek,
  registerView,
  initialViewport,
  initialSelection,
  initialChannelDisplay,
  initialFollow,
  onViewportChange,
  onSelectionChange,
  onChannelDisplayChange,
  onFollowChange,
  loop,
  onLoopRangeChange,
  markers,
  selectedMarkerId,
  onAddMarker,
  onMoveMarker,
  onUpdateMarker,
  onDeleteMarker,
  onSelectMarker,
  onSeekToMarker,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: WaveformEditorProps) {
  const [contentWidth, setContentWidth] = useState(0)
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  /** The width-free view; null until the duration and width are known. */
  const [view, setView] = useState<View | null>(null)
  /** Selection in source frames, `end` exclusive, start < end. */
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null)
  /** Page-follow (M1.14 §16.4); the persisted preference wins on mount. */
  const [followPlayhead, setFollowPlayhead] = useState(readFollowPref)
  /** Playhead outside the viewport (drives Return-to-playhead). */
  const [playheadOutside, setPlayheadOutside] = useState(false)
  const [amp, setAmp] = useState<AmpState>(() => readAmp(projectId) ?? { linked: true, scales: [] })
  const [pointerFrame, setPointerFrame] = useState<number | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  /** Marker being dragged: local preview until pointer-up commits (§17.2.4). */
  const [markerDrag, setMarkerDrag] = useState<{ id: string; frame: number } | null>(null)
  /** Loop being dragged: local preview until pointer-up commits (§13.2.3–4). */
  const [loopDrag, setLoopDrag] = useState<{ start: number; end: number } | null>(null)

  const contentRef = useRef<HTMLDivElement | null>(null)
  const hitRef = useRef<HTMLDivElement | null>(null)
  const ctxRef = useRef(new Map<string, WaveformContext>())
  const laneDragRef = useRef<{
    mode: DragMode
    downX: number
    downFrame: number
    /** The loop bounds the gesture started from (loop drags only). */
    loopStart?: number
    loopEnd?: number
  } | null>(null)
  /** Latest loop drag preview (read on pointer-up to commit once). */
  const loopDraftRef = useRef<{ start: number; end: number } | null>(null)
  const scrollDragRef = useRef<{ lastX: number } | null>(null)
  const overviewDragRef = useRef<{ lastX: number } | null>(null)
  const markerHitRef = useRef<HTMLDivElement | null>(null)
  const markerDragRef = useRef<{ id: string; downX: number; moved: boolean } | null>(null)
  /** True once the restored working state has been applied (§17.6). */
  const restoreAppliedRef = useRef(false)
  /**
   * Skip flags for the autosave callbacks: the first report after a
   * restore (or the initial null selection) echoes state the server
   * already knows, so it is consumed without sending.
   */
  const skipReportRef = useRef({ view: false, selection: true, display: false })

  /**
   * The full viewport for the data hook. Derived (not state) so its
   * identity changes only when the view or the measured width changes —
   * the hook's data effect keys on that identity.
   */
  const viewport: Viewport | null = useMemo(
    () => (view && contentWidth > 0 ? makeViewport(view.startFrame, view.fpp, contentWidth) : null),
    [view, contentWidth],
  )

  // Shared-view source for sibling lanes (M2.8, spec §10.1.4): a stable
  // getter over the latest view, read at display rate by the track stack.
  const sharedViewRef = useRef<SharedView | null>(null)
  sharedViewRef.current =
    view && contentWidth > 0
      ? { startFrame: view.startFrame, fpp: view.fpp, widthCssPx: contentWidth }
      : null
  useEffect(() => {
    if (!registerView) return
    registerView({ get: () => sharedViewRef.current })
    return () => registerView(null)
  }, [registerView])

  const { state, manifest, levels, pcm, overview, error, rebuild } = useWaveform(
    projectId,
    sourceAssetId,
    viewport,
  )

  const register = useCallback((id: string, ctx: WaveformContext | null) => {
    if (ctx) ctxRef.current.set(id, ctx)
    else ctxRef.current.delete(id)
  }, [])

  /**
   * Follow from an explicit user action: apply, persist (§16.4), and
   * report for autosave (M1.15 §17.5). Passive suspension from manual
   * navigation stays in memory only.
   */
  const setFollow = useCallback(
    (on: boolean) => {
      setFollowPlayhead(on)
      try {
        window.localStorage.setItem(FOLLOW_KEY, on ? 'true' : 'false')
      } catch {
        // Storage unavailable: non-fatal.
      }
      onFollowChange?.(on)
    },
    [onFollowChange],
  )

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
    setFollowPlayhead(readFollowPref())
    setPlayheadOutside(false)
    setPointerFrame(null)
    setLoopDrag(null)
    loopDraftRef.current = null
    restoreAppliedRef.current = false
    skipReportRef.current = { view: false, selection: true, display: false }
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

  // Apply the restored working state once, when the editor is ready and
  // the initial values have arrived (M1.15 §17.6). Undefined props mean
  // "not loaded yet"; null props keep the legacy behavior.
  const hasInitials =
    initialViewport !== undefined ||
    initialSelection !== undefined ||
    initialChannelDisplay !== undefined ||
    initialFollow !== undefined
  useEffect(() => {
    if (state !== 'ready' || !manifest || contentWidth <= 0) return
    if (restoreAppliedRef.current || !hasInitials) return
    restoreAppliedRef.current = true
    if (initialViewport) {
      setView(clampView(initialViewport, manifest.frame_count, contentWidth))
      skipReportRef.current.view = true
    }
    if (initialSelection) {
      setSelection(initialSelection)
      skipReportRef.current.selection = true
    }
    if (initialFollow !== undefined && initialFollow !== null) {
      setFollowPlayhead(initialFollow)
    }
    if (initialChannelDisplay && initialChannelDisplay.scales.length === manifest.channel_count) {
      setAmp({
        linked: initialChannelDisplay.linked,
        scales: initialChannelDisplay.scales.map(clampScale),
      })
      skipReportRef.current.display = true
    }
  }, [
    state,
    manifest,
    contentWidth,
    hasInitials,
    initialViewport,
    initialSelection,
    initialFollow,
    initialChannelDisplay,
  ])

  const channelCount = manifest?.channel_count ?? 0

  // Persist the amplitude state once the channel count is known.
  useEffect(() => {
    if (amp.scales.length === 0) return
    try {
      window.localStorage.setItem(ampKey(projectId), JSON.stringify(amp))
    } catch {
      // Storage unavailable: non-fatal.
    }
  }, [amp, projectId])

  // Autosave the viewport (M1.15 §17.5.2): fire on committed view changes
  // after the restored value has been applied (the caller debounces).
  useEffect(() => {
    if (!view) return
    if (skipReportRef.current.view) {
      skipReportRef.current.view = false
      return
    }
    onViewportChange?.(view)
  }, [view, onViewportChange])

  // Autosave the selection; the initial null is consumed, so only real
  // changes (create / resize / clear) are reported.
  useEffect(() => {
    if (skipReportRef.current.selection) {
      skipReportRef.current.selection = false
      return
    }
    onSelectionChange?.(selection)
  }, [selection, onSelectionChange])

  // Autosave the channel display once it has per-channel scales; the
  // restored display is consumed without echoing it back.
  useEffect(() => {
    if (amp.scales.length !== channelCount || channelCount === 0) return
    if (skipReportRef.current.display) {
      skipReportRef.current.display = false
      return
    }
    onChannelDisplayChange?.(amp)
  }, [amp, channelCount, onChannelDisplayChange])

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

  /**
   * Apply a manual view change: suspends follow in memory only (§16.4) —
   * the persisted preference (the checkbox) is untouched.
   */
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

  /** Center on the playhead and re-enable (persist) follow (§16.4). */
  const returnToPlayhead = useCallback(() => {
    if (!playheadSource) return
    centerOn(playheadSource.getPosition())
    setFollow(true)
  }, [centerOn, setFollow, playheadSource])

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
      let loopStart: number | undefined
      let loopEnd: number | undefined
      // The loop overlay owns the pointer inside its range (§13.2.3–4):
      // boundary handles resize, the body moves. Shift+drag bypasses it
      // so a selection can still start inside the loop.
      if (loop && !e.shiftKey) {
        const x0 = frameToX(viewport, loop.start)
        const x1 = frameToX(viewport, loop.end)
        loopStart = loop.start
        loopEnd = loop.end
        if (Math.abs(x - x0) <= HANDLE_HIT_PX) mode = 'loop-start'
        else if (Math.abs(x - x1) <= HANDLE_HIT_PX) mode = 'loop-end'
        else if (x > x0 && x < x1) mode = 'loop-move'
      }
      if (mode === 'maybe' && selection) {
        const x0 = frameToX(viewport, selection.start)
        const x1 = frameToX(viewport, selection.end)
        if (Math.abs(x - x0) <= HANDLE_HIT_PX) mode = 'resize-start'
        else if (Math.abs(x - x1) <= HANDLE_HIT_PX) mode = 'resize-end'
      }
      laneDragRef.current = { mode, downX: x, downFrame: xToFrame(viewport, x), loopStart, loopEnd }
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        // No pointer capture (jsdom): the drag still works.
      }
    },
    [viewport, manifest, selection, laneX, loop],
  )

  const onLanePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!viewport || !manifest) return
      const x = laneX(e.clientX)
      setPointerFrame(Math.round(xToFrame(viewport, x)))
      const drag = laneDragRef.current
      if (!drag) return
      const d = manifest.frame_count
      if (drag.mode === 'loop-start' || drag.mode === 'loop-end' || drag.mode === 'loop-move') {
        const lstart = drag.loopStart ?? 0
        const lend = drag.loopEnd ?? d
        // Body moves need the drag threshold; boundary handles do not
        // (they mirror the selection resizes above).
        if (
          drag.mode === 'loop-move' &&
          !loopDraftRef.current &&
          Math.abs(x - drag.downX) <= DRAG_THRESHOLD_PX
        ) {
          return
        }
        const frame = Math.round(xToFrame(viewport, x))
        let next: { start: number; end: number }
        if (drag.mode === 'loop-start') {
          next = { start: Math.max(0, Math.min(frame, lend - 1)), end: lend }
        } else if (drag.mode === 'loop-end') {
          next = { start: lstart, end: Math.min(d, Math.max(frame, lstart + 1)) }
        } else {
          // Move preserves the exact length (§13.3.5–6): never expand.
          const len = lend - lstart
          const start = Math.max(0, Math.min(lstart + (frame - drag.downFrame), d - len))
          next = { start, end: start + len }
        }
        loopDraftRef.current = next
        setLoopDrag(next)
        return
      }
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
      if (!drag || !viewport || !manifest) return
      if (drag.mode === 'loop-start' || drag.mode === 'loop-end' || drag.mode === 'loop-move') {
        const draft = loopDraftRef.current
        loopDraftRef.current = null
        setLoopDrag(null)
        const changed =
          draft !== null && (draft.start !== drag.loopStart || draft.end !== drag.loopEnd)
        if (changed && draft) {
          // One commit per gesture (§13.8): the drag end is the edit.
          onLoopRangeChange?.(draft.start, draft.end)
          return
        }
        if (drag.mode === 'loop-move') {
          // A sub-threshold body press is a click: seek, as elsewhere.
          const frame = Math.round(xToFrame(viewport, laneX(e.clientX)))
          onSeek?.(Math.max(0, Math.min(manifest.frame_count, frame)))
        }
        return
      }
      // A down/up pair below the drag threshold is a click: seek (§13.4.2).
      if (drag.mode !== 'maybe') return
      const frame = Math.round(xToFrame(viewport, laneX(e.clientX)))
      onSeek?.(Math.max(0, Math.min(manifest.frame_count, frame)))
    },
    [viewport, manifest, laneX, onSeek, onLoopRangeChange],
  )

  const onLanePointerLeave = useCallback(() => {
    if (!laneDragRef.current) setPointerFrame(null)
  }, [])

  // --- marker interaction (M1.15 §17.2) ---------------------------------------

  /** CSS px within the marker hit surface. */
  const markerX = useCallback(
    (clientX: number) => {
      const el = markerHitRef.current
      if (!el) return 0
      const rect = el.getBoundingClientRect()
      return Math.max(0, Math.min(contentWidth, clientX - rect.left))
    },
    [contentWidth],
  )

  /** The marker under `x` (flag body + stem), if any. */
  const markerAt = useCallback(
    (x: number): Marker | null => {
      if (!viewport) return null
      const list = markers ?? []
      for (const mk of list) {
        const frame = markerDrag?.id === mk.id ? markerDrag.frame : mk.position_frames
        const fx = frameToX(viewport, frame)
        if (x >= fx - 2 && x <= fx + MARKER_FLAG_WIDTH) return mk
      }
      return null
    },
    [viewport, markers, markerDrag],
  )

  const onMarkerPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!viewport) return
      e.preventDefault()
      const mk = markerAt(markerX(e.clientX))
      if (!mk) {
        // Empty space: clear the selection (§17.2.9).
        onSelectMarker?.(null)
        return
      }
      markerDragRef.current = { id: mk.id, downX: markerX(e.clientX), moved: false }
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        // No pointer capture (jsdom): the drag still works.
      }
    },
    [viewport, markerAt, markerX, onSelectMarker],
  )

  const onMarkerPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = markerDragRef.current
      if (!drag || !viewport || !manifest) return
      const x = markerX(e.clientX)
      if (!drag.moved && Math.abs(x - drag.downX) <= DRAG_THRESHOLD_PX) return
      drag.moved = true
      const frame = Math.max(0, Math.min(manifest.frame_count, Math.round(xToFrame(viewport, x))))
      setMarkerDrag({ id: drag.id, frame })
    },
    [viewport, manifest, markerX],
  )

  const onMarkerPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = markerDragRef.current
      markerDragRef.current = null
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        // No pointer capture: nothing to release.
      }
      if (!drag) return
      if (drag.moved && viewport && manifest) {
        // One move per gesture (§17.2.4/§17.4.7).
        const frame = Math.max(
          0,
          Math.min(manifest.frame_count, Math.round(xToFrame(viewport, markerX(e.clientX)))),
        )
        setMarkerDrag(null)
        onMoveMarker?.(drag.id, frame)
      } else {
        // A sub-threshold down/up pair is a click: select, no seek (§17.2.9).
        onSelectMarker?.(drag.id)
      }
    },
    [viewport, manifest, markerX, onMoveMarker, onSelectMarker],
  )

  const onMarkerDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const mk = markerAt(markerX(e.clientX))
      if (!mk) return
      onSelectMarker?.(mk.id)
      onSeekToMarker?.(mk.position_frames)
    },
    [markerAt, markerX, onSelectMarker, onSeekToMarker],
  )

  /** Double-click the ruler: add at the pointer frame (§17.2.2). */
  const onRulerDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!viewport || !manifest) return
      const rect = e.currentTarget.getBoundingClientRect()
      const x = Math.max(0, Math.min(contentWidth, e.clientX - rect.left))
      const frame = Math.max(0, Math.min(manifest.frame_count, Math.round(xToFrame(viewport, x))))
      onAddMarker?.(frame)
    },
    [viewport, manifest, contentWidth, onAddMarker],
  )

  /** Add at the playhead (§17.2.1). */
  const addMarkerAtPlayhead = useCallback(() => {
    if (!playheadSource) return
    onAddMarker?.(Math.round(playheadSource.getPosition()))
  }, [playheadSource, onAddMarker])

  /** Prev/next: seek to the nearest marker before/after the playhead (§17.2.8). */
  const seekRelativeMarker = useCallback(
    (dir: -1 | 1) => {
      if (!playheadSource) return
      const pos = playheadSource.getPosition()
      let best: Marker | null = null
      for (const mk of markers ?? []) {
        const before = dir === -1 ? mk.position_frames < pos : mk.position_frames > pos
        if (!before) continue
        if (
          !best ||
          (dir === -1
            ? mk.position_frames > best.position_frames
            : mk.position_frames < best.position_frames)
        ) {
          best = mk
        }
      }
      if (!best) return
      onSeekToMarker?.(best.position_frames)
      onSelectMarker?.(best.id)
    },
    [markers, playheadSource, onSeekToMarker, onSelectMarker],
  )

  /** Cycle the swatch through the 6-color palette (§17.2.6). */
  const cycleMarkerColor = useCallback(
    (mk: Marker) => {
      const i = (MARKER_COLORS as readonly string[]).indexOf(mk.color)
      const next = MARKER_COLORS[(i + 1) % MARKER_COLORS.length]
      onUpdateMarker?.(mk.id, { color: next })
    },
    [onUpdateMarker],
  )

  const commitMarkerLabel = useCallback(
    (mk: Marker, value: string) => {
      const label = value.trim()
      if (!label || label === mk.label) return
      onUpdateMarker?.(mk.id, { label })
    },
    [onUpdateMarker],
  )

  const commitMarkerFrame = useCallback(
    (mk: Marker, value: string) => {
      const n = Number(value)
      if (!Number.isFinite(n)) return
      const max = manifest?.frame_count ?? n
      const frame = Math.max(0, Math.min(max, Math.round(n)))
      if (frame === mk.position_frames) return
      onUpdateMarker?.(mk.id, { positionFrames: frame })
    },
    [manifest, onUpdateMarker],
  )

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
        const anchor = playheadSource ? playheadSource.getPosition() : 0
        zoomAt(0.5, Math.max(0, Math.min(manifest.frame_count, anchor)))
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault()
        const anchor = playheadSource ? playheadSource.getPosition() : 0
        zoomAt(2, Math.max(0, Math.min(manifest.frame_count, anchor)))
      }
    },
    [selection, viewport, manifest, playheadSource, zoomAt],
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

  // Marker UI derived state (M1.15 §17.2).
  const markerList = markers ?? []
  const playheadPos = playheadSource ? playheadSource.getPosition() : null
  const hasPrevMarker =
    playheadPos != null && markerList.some((m) => m.position_frames < playheadPos)
  const hasNextMarker =
    playheadPos != null && markerList.some((m) => m.position_frames > playheadPos)

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

  // Selection layer: the loop overlay under the selection range, each
  // boundary with a handle (§13.4.7, §13.2.3–4). A loop drag previews
  // locally until pointer-up commits it.
  useEffect(() => {
    if (state !== 'ready' || !viewport || contentWidth <= 0) return
    const loopRange = loopDrag ?? loop ?? null
    for (const ch of shownLanes) {
      const sctx = ctxRef.current.get(`lane:${ch}:selection`)
      if (!sctx) continue
      sctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
      if (loopRange) {
        const x0 = frameToX(viewport, loopRange.start)
        const x1 = frameToX(viewport, loopRange.end)
        if (x1 > 0 && x0 < contentWidth) {
          drawLoop(sctx, Math.max(0, x0), Math.min(contentWidth, x1), LANE_HEIGHT, {
            color: loop?.color,
          })
        }
      }
      if (selection) {
        const x0 = frameToX(viewport, selection.start)
        const x1 = frameToX(viewport, selection.end)
        if (x1 > 0 && x0 < contentWidth) {
          drawSelection(sctx, Math.max(0, x0), Math.min(contentWidth, x1), LANE_HEIGHT)
        }
      }
    }
  }, [state, viewport, selection, contentWidth, shownLanes, drawnKey, loop, loopDrag])

  // Marker layers (M1.15 §17.2): row flags plus one 1 px tick per lane,
  // the dragged marker drawn at its preview position.
  useEffect(() => {
    if (state !== 'ready' || !viewport || contentWidth <= 0) return
    const list = markers ?? []
    const mctx = ctxRef.current.get('marker-row')
    if (mctx) {
      mctx.clearRect(0, 0, contentWidth, MARKER_ROW_HEIGHT)
      for (const mk of list) {
        const frame = markerDrag?.id === mk.id ? markerDrag.frame : mk.position_frames
        const x = frameToX(viewport, frame)
        if (x > contentWidth + 2 || x < -MARKER_FLAG_WIDTH - 2) continue
        drawMarkerFlag(mctx, x, mk.label, MARKER_ROW_HEIGHT, {
          color: mk.color,
          selected: mk.id === selectedMarkerId,
        })
      }
    }
    for (const ch of shownLanes) {
      const kctx = ctxRef.current.get(`lane:${ch}:markers`)
      if (!kctx) continue
      kctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
      for (const mk of list) {
        const frame = markerDrag?.id === mk.id ? markerDrag.frame : mk.position_frames
        const x = frameToX(viewport, frame)
        if (x < -1 || x > contentWidth + 1) continue
        drawMarkerTick(kctx, x, LANE_HEIGHT, mk.color)
      }
    }
  }, [state, viewport, contentWidth, shownLanes, drawnKey, markers, selectedMarkerId, markerDrag])

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

  // Playhead rAF loop (M1.14 §16.5): while ready, every frame reads the
  // audible position, redraws the per-lane playhead layers only on a
  // ≥ 0.5 px movement, and runs the 80 % / 20 % page follow. No
  // per-update React state (`playheadOutside` writes only on change).
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    if (!playheadSource) return
    let raf = 0
    let lastX = -1
    const tick = () => {
      const frame = Math.max(0, Math.min(manifest.frame_count, playheadSource.getPosition()))
      const x = frameToX(viewport, frame)
      if (x >= 0 && x <= contentWidth && (lastX < 0 || Math.abs(x - lastX) >= 0.5)) {
        lastX = x
        for (const ch of shownLanes) {
          const pctx = ctxRef.current.get(`lane:${ch}:playhead`)
          if (!pctx) continue
          pctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
          drawPlayhead(pctx, x, LANE_HEIGHT)
        }
      }
      setPlayheadOutside(x < 0 || x > contentWidth)
      // Page follow (§16.4): 80 % trigger, 20 % landing. Programmatic —
      // it must not suspend follow (only manual navigation does).
      if (followPlayhead && playheadSource.isPlaying() && x >= contentWidth * 0.8) {
        const visible = contentWidth * viewport.framesPerCssPixel
        const next = clampView(
          { startFrame: frame - 0.2 * visible, fpp: viewport.framesPerCssPixel },
          manifest.frame_count,
          contentWidth,
        )
        if (next.startFrame !== viewport.startFrame) setView(next)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [
    state,
    viewport,
    manifest,
    contentWidth,
    shownLanes,
    drawnKey,
    playheadSource,
    followPlayhead,
  ])

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
        <div className="wave-content" onDoubleClick={onRulerDoubleClick}>
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

      {/* Marker row (M1.15 §17.2): flag canvas, hit surface, toolbar, list. */}
      <div className="wave-row wave-marker-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-marker-lane" aria-label="Markers">
          <div className="wave-content wave-marker-canvas-wrap">
            <CanvasLayer
              id="marker-row"
              width={contentWidth}
              height={MARKER_ROW_HEIGHT}
              register={register}
              className="wave-canvas"
            />
            <div
              className="wave-marker-hitarea"
              ref={markerHitRef}
              onPointerDown={onMarkerPointerDown}
              onPointerMove={onMarkerPointerMove}
              onPointerUp={onMarkerPointerUp}
              onPointerCancel={onMarkerPointerUp}
              onDoubleClick={onMarkerDoubleClick}
            />
          </div>
          <div className="wave-marker-toolbar">
            <button type="button" onClick={addMarkerAtPlayhead} disabled={!playheadSource}>
              Add marker
            </button>
            <button type="button" onClick={() => seekRelativeMarker(-1)} disabled={!hasPrevMarker}>
              Prev
            </button>
            <button type="button" onClick={() => seekRelativeMarker(1)} disabled={!hasNextMarker}>
              Next
            </button>
          </div>
          {markerList.length > 0 && (
            <ul className="wave-marker-list" aria-label="Marker list">
              {markerList.map((mk) => (
                <li
                  key={mk.id}
                  className={
                    mk.id === selectedMarkerId ? 'wave-marker-item selected' : 'wave-marker-item'
                  }
                  onClick={() => onSelectMarker?.(mk.id)}
                >
                  <button
                    type="button"
                    className="wave-marker-swatch"
                    style={{ backgroundColor: mk.color }}
                    aria-label={`Marker color ${mk.color}`}
                    title="Cycle color"
                    onClick={() => cycleMarkerColor(mk)}
                  />
                  <input
                    key={`label:${mk.id}:${mk.label}`}
                    className="wave-marker-label"
                    defaultValue={mk.label}
                    aria-label="Marker label"
                    maxLength={80}
                    onBlur={(e) => commitMarkerLabel(mk, e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                    }}
                  />
                  <input
                    key={`frame:${mk.id}:${mk.position_frames}`}
                    className="wave-marker-frame"
                    type="number"
                    defaultValue={mk.position_frames}
                    aria-label="Marker frame"
                    onBlur={(e) => commitMarkerFrame(mk, e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                    }}
                  />
                  {sampleRate > 0 && (
                    <span className="wave-marker-time">
                      {formatTime(mk.position_frames, sampleRate)}
                    </span>
                  )}
                  <button
                    type="button"
                    className="wave-marker-delete"
                    aria-label={`Delete marker ${mk.label}`}
                    onClick={() => onDeleteMarker?.(mk.id)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
          {markerList.length === 0 && <span className="muted">Markers</span>}
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
        {playheadSource && (
          <label className="wave-follow-toggle">
            <input
              type="checkbox"
              checked={followPlayhead}
              onChange={(e) => setFollow(e.target.checked)}
              aria-label="Follow playhead"
            />
            Follow playhead
          </label>
        )}
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
        <fieldset className="wave-history-controls">
          <legend>History</legend>
          <button type="button" aria-label="Undo" onClick={onUndo} disabled={!canUndo}>
            Undo
          </button>
          <button type="button" aria-label="Redo" onClick={onRedo} disabled={!canRedo}>
            Redo
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
