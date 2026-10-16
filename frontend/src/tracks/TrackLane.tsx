/**
 * One stem lane in the track stack (M2.8, spec §10.1).
 *
 * A lane follows the editor's shared view (one zoom/pan drives every
 * lane, §10.1.4), fetches only the visible tiles through `useWaveform`,
 * and draws with the Milestone 1 painters. Each lane keeps its own
 * height and amplitude scale (§10.1.5) and a playhead line.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { TILE_BUCKETS } from '../waveform/levels'
import {
  drawLaneWaveform,
  drawPcmWaveform,
  drawPlayhead,
  drawSamplePoints,
  type BucketSource,
  type PcmPixelSource,
  type SampleSource,
  type WaveformContext,
} from '../waveform/render'
import { frameToX, makeViewport, type Viewport } from '../waveform/viewport'
import { useWaveform, type PcmData, type WaveformLevelData } from '../waveform/useWaveform'
import type { PlayheadSource, SharedView, ViewSource } from '../waveform/WaveformEditor'

export interface TrackLaneProps {
  projectId: string
  assetId: string | null
  /** The editor's shared view; the lane follows it at display rate. */
  viewSource: ViewSource | null
  /** Audible playhead; absent → no playhead line. */
  playheadSource?: PlayheadSource
  /** Final lane height in CSS px (base × `display_height`). */
  height: number
  /** Display amplitude multiplier (per-lane zoom, §10.1.5). */
  amplitudeScale: number
  /** Waveform fill color (the track's `color`). */
  color: string
  /** Track label (the stem's `display_name`). */
  label: string
  /** Provenance line (model + engine version, §10.1.6). */
  provenance?: string | null
  /** True while the waveform is hidden (never mutes audio, §10.1.9). */
  hidden?: boolean
}

/** One channel's per-bucket source for a peak level (mirrors the editor). */
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

function sampleSourceFor(
  pcm: Extract<PcmData, { kind: 'samples' }>,
  channel: number,
): SampleSource {
  return {
    startFrame: pcm.startFrame,
    samples: pcm.channels[channel] ?? new Float32Array(0),
  }
}

function sameView(a: SharedView | null, b: SharedView | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return a.startFrame === b.startFrame && a.fpp === b.fpp && a.widthCssPx === b.widthCssPx
}

/**
 * One lane canvas, allocated in device pixels and handed out as a 2D
 * context pre-scaled to CSS pixels (mirrors the editor's `CanvasLayer`;
 * null in environments without 2D canvas).
 */
function LaneCanvas({
  id,
  width,
  height,
  onContext,
}: {
  id: string
  width: number
  height: number
  onContext: (id: string, ctx: WaveformContext | null) => void
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
    canvas.style.width = `${Math.max(1, width)}px`
    canvas.style.height = `${Math.max(1, height)}px`
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      onContext(id, ctx)
    } else {
      onContext(id, null)
    }
    return () => onContext(id, null)
  }, [id, width, height, onContext])

  return <canvas ref={ref} aria-hidden="true" />
}

const STATE_TEXT: Record<string, string> = {
  decoding: 'Building waveform…',
  pending: 'Waveform queued…',
  missing: 'Waveform missing',
  empty: 'No source',
}

export function TrackLane({
  projectId,
  assetId,
  viewSource,
  playheadSource,
  height,
  amplitudeScale,
  color,
  label,
  provenance,
  hidden = false,
}: TrackLaneProps) {
  // Follow the shared view at display rate; skip the render when the
  // view is unchanged (pan/zoom settle between frames).
  const [view, setView] = useState<SharedView | null>(null)
  const latestViewRef = useRef<SharedView | null>(null)
  latestViewRef.current = view
  useEffect(() => {
    if (!viewSource) {
      setView(null)
      return
    }
    let raf = 0
    let last = viewSource.get()
    setView(last)
    const tick = () => {
      const v = viewSource.get()
      if (!sameView(v, last)) {
        last = v
        setView(v)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [viewSource])

  const viewport: Viewport | null = useMemo(
    () => (view ? makeViewport(view.startFrame, view.fpp, view.widthCssPx) : null),
    [view],
  )

  const { state, manifest, levels, pcm } = useWaveform(projectId, assetId, viewport)

  const width = view?.widthCssPx ?? 0
  const waveCtxRef = useRef<WaveformContext | null>(null)
  const phCtxRef = useRef<WaveformContext | null>(null)
  const handleContext = (id: string, ctx: WaveformContext | null) => {
    if (id === 'wave') waveCtxRef.current = ctx
    else phCtxRef.current = ctx
  }

  // Waveform layer: redraw only when the data, view, or style changes.
  const level = levels[0] ?? null
  useEffect(() => {
    const ctx = waveCtxRef.current
    if (!ctx) return
    ctx.clearRect(0, 0, Math.max(1, width), Math.max(1, height))
    if (state !== 'ready' || !viewport || !manifest) return
    const opts = { height, amplitudeScale, color }
    const bucketCount = level ? manifest.levels[level.level].bucket_count : 0
    if (level) {
      drawLaneWaveform(ctx, bucketSourceFor(level, bucketCount, 0), viewport, 0, width, opts)
    } else if (pcm?.kind === 'pixels') {
      drawPcmWaveform(ctx, pcmPixelSourceFor(pcm, 0), viewport, 0, width, opts)
    } else if (pcm?.kind === 'samples') {
      drawSamplePoints(ctx, sampleSourceFor(pcm, 0), viewport, 0, width, opts)
    }
  }, [state, manifest, level, pcm, viewport, width, height, amplitudeScale, color])

  // Playhead layer: redraw only while the playhead moves.
  useEffect(() => {
    if (!playheadSource) return
    let raf = 0
    let lastX = -1
    const tick = () => {
      const vp = latestViewRef.current
      const ctx = phCtxRef.current
      if (vp && ctx) {
        const frame = Math.max(
          0,
          Math.min(manifest?.frame_count ?? 0, playheadSource.getPosition()),
        )
        const x = frameToX(makeViewport(vp.startFrame, vp.fpp, vp.widthCssPx), frame)
        if (x >= 0 && x <= vp.widthCssPx && (lastX < 0 || Math.abs(x - lastX) >= 0.5)) {
          lastX = x
          ctx.clearRect(0, 0, vp.widthCssPx, height)
          drawPlayhead(ctx, x, height)
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playheadSource, height, manifest])

  return (
    <div className="track-lane" style={{ height }} aria-label={`${label} waveform`}>
      {hidden ? (
        <div className="track-lane-hidden">Hidden (audio still plays)</div>
      ) : (
        <div className="track-lane-canvases">
          <LaneCanvas id="wave" width={width} height={height} onContext={handleContext} />
          <LaneCanvas id="ph" width={width} height={height} onContext={handleContext} />
          {state !== 'ready' && (
            <div className="track-lane-state" role="status">
              {STATE_TEXT[state] ?? '…'}
            </div>
          )}
        </div>
      )}
      {provenance && <div className="track-lane-provenance">{provenance}</div>}
    </div>
  )
}
