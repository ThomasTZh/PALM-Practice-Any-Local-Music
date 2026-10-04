/**
 * Waveform editor component (M1.10, plan §8, spec §12).
 *
 * Renders the full §12.1 layout for the fit-to-song viewport: overview
 * strip, time ruler, per-channel lanes (five stacked canvas layers each),
 * marker lane and selection readout (both empty in M1.10), a static
 * horizontal scrollbar, channel visibility controls, and the display
 * amplitude controls (0.25×–16×).
 *
 * Canvas layers (§12.3): waveform / grid / selection / markers / playhead.
 * Only the playhead canvases are redrawn on position updates. Each canvas
 * is allocated in device pixels (`css × devicePixelRatio`) and drawn in
 * CSS pixels after a DPR transform (§12.4).
 *
 * States (§12.8): `empty` / `decoding` / `pending` / `missing` render an
 * overlay (with a rebuild button for `missing`); `ready` renders the
 * layout. A `ready` editor whose tiles are still building draws the
 * available tiles and leaves the rest blank (progressive). Silent audio
 * draws a flat center line — no special state.
 *
 * M1.10 is static: no zoom/pan/selection interaction (M1.11).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  drawLaneGrid,
  drawLaneWaveform,
  drawOverview,
  drawPcmWaveform,
  drawPlayhead,
  drawRuler,
  drawSamplePoints,
  type BucketSource,
  type PcmPixelSource,
  type SampleSource,
  type WaveformContext,
} from './render'
import { frameToX } from './viewport'
import { useWaveform, type PcmData, type WaveformLevelData } from './useWaveform'
import { TILE_BUCKETS } from './levels'

export interface WaveformEditorProps {
  projectId: string
  /** Canonical source asset; null when no source has been imported. */
  sourceAssetId: string | null
  /** Playhead position in project frames (canonical rate). */
  playheadFrame: number
}

/** Layout constants (CSS px). */
const LANE_HEIGHT = 48
const OVERVIEW_HEIGHT = 44
const RULER_HEIGHT = 24
const LANE_AREA_HEIGHT = 240

/** The five stacked layers of a lane (spec §12.3), bottom → top. */
const LAYERS = ['waveform', 'grid', 'selection', 'markers', 'playhead'] as const

const AMP_MIN = 0.25
const AMP_MAX = 16

/** Derived lane labels (layout-aware labels are an M1.11 polish). */
function channelLabel(count: number, i: number): string {
  if (count === 1) return 'Mono'
  if (count === 2) return i === 0 ? 'L' : 'R'
  return `Ch ${i}`
}

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
    bucketAt: (b) => {
      if (b < 0 || b >= bucketCount) return null
      const tile = tiles.get(Math.floor(b / TILE_BUCKETS))
      if (!tile) return null
      const within = b - Math.floor(b / TILE_BUCKETS) * TILE_BUCKETS
      if (within >= tile.minima[channel].length) return null
      return [tile.minima[channel][within], tile.maxima[channel][within]]
    },
  }
}

function pcmPixelSourceFor(
  pcm: Extract<PcmData, { kind: 'pixels' }>,
  channel: number,
): PcmPixelSource {
  const d = pcm.data
  return {
    startFrame: d.startFrame,
    pixelCount: d.pixels,
    pixelAt: (p) => (p < 0 || p >= d.pixels ? null : [d.minima[channel][p], d.maxima[channel][p]]),
  }
}

function sampleSourceFor(
  pcm: Extract<PcmData, { kind: 'samples' }>,
  channel: number,
): SampleSource {
  return { startFrame: pcm.startFrame, samples: pcm.channels[channel] }
}

/**
 * One DPR-sized canvas. Registers its 2D context (CSS-pixel space) with
 * the parent so the draw effects can paint it; unregistration happens on
 * unmount. A null context (no 2D support) simply means the layer is not
 * painted.
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
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.round(width * dpr))
    canvas.height = Math.max(1, Math.round(height * dpr))
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      // The painters use a minimal structural context; the real 2D context
      // satisfies it at runtime (styles are always plain strings here).
      register(id, ctx as unknown as WaveformContext)
    } else {
      register(id, null)
    }
    return () => register(id, null)
  }, [id, width, height, register])
  return (
    <canvas
      ref={ref}
      data-id={id}
      className={className}
      style={{ display: 'block', width: `${Math.max(0, width)}px`, height: `${height}px` }}
    />
  )
}

export function WaveformEditor({ projectId, sourceAssetId, playheadFrame }: WaveformEditorProps) {
  const [contentWidth, setContentWidth] = useState(0)
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const [amplitudeScale, setAmplitudeScale] = useState(1)
  const [scrollTop, setScrollTop] = useState(0)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const ctxRef = useRef(new Map<string, WaveformContext>())

  const { state, manifest, levels, pcm, viewport, error, rebuild } = useWaveform(
    projectId,
    sourceAssetId,
    contentWidth,
  )

  const register = useCallback((id: string, ctx: WaveformContext | null) => {
    if (ctx) ctxRef.current.set(id, ctx)
    else ctxRef.current.delete(id)
  }, [])

  // Measure the content column (CSS px); all canvases share its width so
  // the ruler, overview, and lanes stay aligned (§12.2, acceptance).
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

  const channelCount = manifest?.channel_count ?? 0
  const labels = useMemo(
    () => Array.from({ length: channelCount }, (_, i) => channelLabel(channelCount, i)),
    [channelCount],
  )

  const shownLanes = useMemo(
    () => labels.map((_, i) => i).filter((i) => !hidden.has(i)),
    [labels, hidden],
  )

  // Vertical virtualization: only lanes intersecting the scroll window
  // (±1 row buffer) are mounted (§12.6).
  const firstIdx = Math.max(0, Math.floor(scrollTop / LANE_HEIGHT) - 1)
  const lastIdx = Math.min(
    shownLanes.length,
    Math.ceil((scrollTop + LANE_AREA_HEIGHT) / LANE_HEIGHT) + 1,
  )
  const drawnLanes = shownLanes.slice(firstIdx, lastIdx)
  const drawnKey = drawnLanes.join('|')

  const toggleHidden = useCallback((i: number) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }, [])

  const zoomIn = useCallback(() => setAmplitudeScale((s) => Math.min(AMP_MAX, s * 2)), [])
  const zoomOut = useCallback(() => setAmplitudeScale((s) => Math.max(AMP_MIN, s / 2)), [])
  const resetAmplitude = useCallback(() => setAmplitudeScale(1), [])

  const level = levels[0] ?? null

  // Waveform + grid + overview paint (redraws when the data, scale, or the
  // mounted lane set changes).
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    const opts = { height: LANE_HEIGHT, amplitudeScale }
    const ovCtx = ctxRef.current.get('overview')
    if (ovCtx) {
      ovCtx.clearRect(0, 0, contentWidth, OVERVIEW_HEIGHT)
      if (level) {
        drawOverview(
          ovCtx,
          labels.map((_, c) =>
            bucketSourceFor(level, manifest.levels[level.level].bucket_count, c),
          ),
          contentWidth,
          OVERVIEW_HEIGHT,
        )
      } else if (pcm?.kind === 'pixels') {
        drawOverview(
          ovCtx,
          labels.map((_, c) => ({
            bucketFrameCount: viewport.framesPerCssPixel,
            bucketCount: pcm.data.pixels,
            bucketAt: (p: number) =>
              p < 0 || p >= pcm.data.pixels ? null : [pcm.data.minima[c][p], pcm.data.maxima[c][p]],
          })),
          contentWidth,
          OVERVIEW_HEIGHT,
        )
      }
    }
    for (const ch of shownLanes) {
      const wctx = ctxRef.current.get(`lane:${ch}:waveform`)
      if (wctx) {
        wctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
        if (level) {
          drawLaneWaveform(
            wctx,
            bucketSourceFor(level, manifest.levels[level.level].bucket_count, ch),
            viewport,
            0,
            contentWidth,
            opts,
          )
        } else if (pcm?.kind === 'pixels') {
          drawPcmWaveform(wctx, pcmPixelSourceFor(pcm, ch), viewport, 0, contentWidth, opts)
        } else if (pcm?.kind === 'samples') {
          drawSamplePoints(wctx, sampleSourceFor(pcm, ch), viewport, 0, contentWidth, opts)
        }
      }
      const gctx = ctxRef.current.get(`lane:${ch}:grid`)
      if (gctx) {
        gctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
        drawLaneGrid(gctx, contentWidth, LANE_HEIGHT)
      }
    }
  }, [state, viewport, manifest, level, pcm, contentWidth, amplitudeScale, shownLanes, drawnKey])

  // Ruler paint (static in M1.10).
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

  // Playhead paint — the only effect run on position updates (§12.3).
  useEffect(() => {
    if (state !== 'ready' || !viewport || !manifest || contentWidth <= 0) return
    const x = frameToX(viewport, Math.min(playheadFrame, manifest.frame_count))
    for (const ch of shownLanes) {
      const pctx = ctxRef.current.get(`lane:${ch}:playhead`)
      if (!pctx) continue
      pctx.clearRect(0, 0, contentWidth, LANE_HEIGHT)
      if (x >= 0 && x <= contentWidth) drawPlayhead(pctx, x, LANE_HEIGHT)
    }
  }, [state, viewport, manifest, playheadFrame, contentWidth, shownLanes, drawnKey])

  if (state !== 'ready') {
    return (
      <section className="waveform-editor" aria-label="Waveform editor">
        <div className="wave-state" role="status">
          {state === 'empty' && <p>No source imported.</p>}
          {state === 'decoding' && <p>Decoding audio…</p>}
          {state === 'pending' && <p>Building waveform…</p>}
          {state === 'missing' && (
            <>
              <p>Waveform unavailable.</p>
              <button type="button" onClick={rebuild}>
                Build waveform
              </button>
            </>
          )}
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="waveform-editor" aria-label="Waveform editor">
      <div className="wave-row wave-overview-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-content" ref={contentRef}>
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
                <span className="wave-lane-label">{labels[ch]}</span>
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
          </div>
        </div>
      </div>

      <div className="wave-row wave-marker-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-marker-lane" aria-label="Markers">
          <span className="muted">Markers</span>
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      <div className="wave-row wave-selection-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-selection-readout" aria-label="Selection">
          —
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      <div className="wave-row wave-scrollbar-row">
        <span className="wave-col-label" aria-hidden="true" />
        <div className="wave-scrollbar" aria-hidden="true">
          <div className="wave-scrollbar-thumb" />
        </div>
        <span className="wave-col-action" aria-hidden="true" />
      </div>

      <div className="wave-controls">
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
        <fieldset className="wave-amplitude-controls">
          <legend>Display amplitude</legend>
          <button type="button" onClick={zoomIn} disabled={amplitudeScale >= AMP_MAX}>
            Zoom in
          </button>
          <button type="button" onClick={zoomOut} disabled={amplitudeScale <= AMP_MIN}>
            Zoom out
          </button>
          <button type="button" onClick={resetAmplitude} disabled={amplitudeScale === 1}>
            Reset
          </button>
          <span className="wave-amplitude-value" aria-live="polite">
            {amplitudeScale}×
          </span>
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
