/**
 * Musical ruler and rhythm lanes above the waveform (M3.11 §13).
 *
 * Read-only first slice: bar/beat/subdivision lines, bar labels, meter
 * labels, tempo-anchor handles, pulse markers, a playhead line, and click
 * seeking. It reads the shared editor view directly and updates only the
 * playhead transform per animation frame; static ruler layers re-render
 * only when the viewport/grid changes.
 */

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { fetchRhythmGrid, type RhythmGridData } from '../api/rhythm'
import {
  detailForZoom,
  suppressOverlappingLabels,
  visibleGridEvents,
  type GridLikeEvent,
} from '../music/ruler'
import { barBeatLabel, musicalAtSource, sourceAtMusical } from '../music/tempoGrid'
import type { PlayheadSource, SharedView, ViewSource } from '../waveform/WaveformEditor'

export interface RhythmLanesProps {
  projectId: string
  viewSource: ViewSource
  playheadSource?: PlayheadSource
  onSeek?: (frame: number) => void
  /** Changes when branch revision/project revision changes, forcing a refetch. */
  refreshKey?: number
}

function pixelsPerQuarter(data: RhythmGridData | null, fpp: number): number {
  if (!data || data.tempo_anchors.length < 2 || fpp <= 0) return 0
  const anchors = data.tempo_anchors
  for (let index = 0; index + 1 < anchors.length; index += 1) {
    const left = anchors[index]
    const right = anchors[index + 1]
    const leftQuarters = left.musical_position.numerator / left.musical_position.denominator
    const rightQuarters = right.musical_position.numerator / right.musical_position.denominator
    if (rightQuarters > leftQuarters) {
      const framesPerQuarter =
        (right.source_frame - left.source_frame) / (rightQuarters - leftQuarters)
      return framesPerQuarter / fpp
    }
  }
  return 0
}

function localBpm(data: RhythmGridData, sourceFrame: number): number | null {
  const anchors = [...data.tempo_anchors].sort(
    (left, right) => left.source_frame - right.source_frame,
  )
  for (let index = 0; index + 1 < anchors.length; index += 1) {
    const left = anchors[index]
    const right = anchors[index + 1]
    if (sourceFrame < left.source_frame || sourceFrame > right.source_frame) continue
    const frames = right.source_frame - left.source_frame
    if (frames <= 0) return null
    const quarters =
      right.musical_position.numerator / right.musical_position.denominator -
      left.musical_position.numerator / left.musical_position.denominator
    return (60 * quarters * data.source_sample_rate) / frames
  }
  return null
}

function barBeatForSource(data: RhythmGridData, sourceFrame: number): string | null {
  if (data.tempo_anchors.length < 2) return null
  try {
    const musical = musicalAtSource(
      data.tempo_anchors.map((anchor) => ({
        sourceFrame: anchor.source_frame,
        musical: anchor.musical_position,
      })),
      sourceFrame,
    )
    const label = barBeatLabel(
      data.meter_regions.map((region) => ({
        start: region.start,
        numerator: region.numerator,
        denominator: region.denominator,
        grouping: region.grouping,
      })),
      {
        firstNumberedBarPosition: data.bar_origin.first_numbered_bar_position,
        firstBarNumber: data.bar_origin.first_bar_number,
      },
      musical,
    )
    return label.label
  } catch {
    return null
  }
}

export function RhythmLanes({
  projectId,
  viewSource,
  playheadSource,
  onSeek,
  refreshKey = 0,
}: RhythmLanesProps) {
  const [view, setView] = useState<SharedView | null>(() => viewSource.get())
  const [data, setData] = useState<RhythmGridData | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selected, setSelected] = useState<{
    kind: 'pulse' | 'anchor' | 'meter'
    id: string
  } | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const playheadRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let frame = 0
    const tick = () => {
      const next = viewSource.get()
      if (next) {
        setView((current) =>
          current &&
          current.startFrame === next.startFrame &&
          current.fpp === next.fpp &&
          current.widthCssPx === next.widthCssPx
            ? current
            : next,
        )
        const playhead = playheadSource?.getPosition()
        if (playheadRef.current && playhead !== undefined) {
          const x = (playhead - next.startFrame) / next.fpp
          playheadRef.current.style.transform = `translateX(${x}px)`
          playheadRef.current.style.display = x >= 0 && x <= next.widthCssPx ? 'block' : 'none'
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [viewSource, playheadSource])

  const fpp = view?.fpp ?? 0
  const width = view?.widthCssPx ?? 0
  const startFrame = view?.startFrame ?? 0
  const estimatedPpq = pixelsPerQuarter(data, fpp) || 24_000 / Math.max(1, fpp)
  const detail = detailForZoom(estimatedPpq)

  useEffect(() => {
    if (!view || view.widthCssPx < 2 || view.fpp <= 0) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      const margin = view.widthCssPx * view.fpp * 0.25
      const start = Math.max(0, Math.floor(view.startFrame - margin))
      const end = Math.ceil(view.startFrame + view.widthCssPx * view.fpp + margin)
      fetchRhythmGrid(projectId, { startFrame: start, endFrame: end, detail }, controller.signal)
        .then((next) => {
          setData(next)
          setNotice(next ? null : 'No rhythm grid for this project')
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          setData(null)
          setNotice(error instanceof Error ? error.message : 'Rhythm grid unavailable')
        })
    }, 120)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [projectId, view, detail, refreshKey])

  const visibleEnd = startFrame + width * Math.max(1, fpp)
  const visible = useMemo(() => {
    if (!data) return []
    return visibleGridEvents(data.grid.events, startFrame, visibleEnd, detail, 0)
  }, [data, startFrame, visibleEnd, detail])
  const labelEvents = useMemo(
    () =>
      suppressOverlappingLabels(
        data
          ? visibleGridEvents(data.grid.events, startFrame, visibleEnd, detail, 0).filter(
              (event) => event.kind === 'bar',
            )
          : [],
        fpp > 0 ? 1 / fpp : 0,
        48,
      ),
    [data, startFrame, visibleEnd, detail, fpp],
  )
  const barLabels = useMemo(() => {
    if (!data) return []
    return labelEvents.map((event: GridLikeEvent) => ({
      label: event.label,
      x: (event.source_frame - startFrame) / fpp,
    }))
  }, [labelEvents, startFrame, fpp, data])

  if (!view) return null

  const selectOnKey =
    (kind: 'pulse' | 'anchor' | 'meter', id: string) => (event: KeyboardEvent<HTMLSpanElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        event.stopPropagation()
        setSelected({ kind, id })
      }
    }

  const handleClick = (clientX: number) => {
    if (!onSeek || !containerRef.current || fpp <= 0) return
    const rect = containerRef.current.getBoundingClientRect()
    const frame = Math.round(startFrame + (clientX - rect.left) * fpp)
    onSeek(frame)
  }

  const selectedPulse =
    selected?.kind === 'pulse' ? data?.pulses.find((pulse) => pulse.id === selected.id) : undefined
  const selectedAnchor =
    selected?.kind === 'anchor'
      ? data?.tempo_anchors.find((anchor) => anchor.id === selected.id)
      : undefined
  const selectedMeter =
    selected?.kind === 'meter'
      ? data?.meter_regions.find((region) => region.id === selected.id)
      : undefined
  const selectedSource = selectedPulse?.source_frame ?? selectedAnchor?.source_frame ?? null
  const inspection =
    data && selected ? (
      <div className="rhythm-inspector" aria-label="Rhythm selection inspector">
        <strong>
          {selectedPulse
            ? selectedPulse.role === 'downbeat'
              ? 'Downbeat pulse'
              : 'Beat pulse'
            : selectedAnchor
              ? 'Tempo anchor'
              : 'Meter region'}
        </strong>
        {selectedSource !== null ? (
          <span>
            frame {selectedSource} · bar {barBeatForSource(data, selectedSource) ?? '?'} · local{' '}
            {localBpm(data, selectedSource)?.toFixed(2) ?? '?'} BPM
          </span>
        ) : null}
        {selectedPulse ? (
          <>
            <span>
              {selectedPulse.acceptance} · {selectedPulse.origin} · review{' '}
              {selectedPulse.review_state}
            </span>
            <span>
              confidence {selectedPulse.confidence.kind} ·{' '}
              {selectedPulse.confidence.value?.toFixed(3) ?? 'n/a'} ·{' '}
              {selectedPulse.confidence.calibrated ? 'calibrated' : 'uncalibrated'}
            </span>
            <span>
              anchor {selectedPulse.tempo_anchor_id ?? 'none'} · parent {selectedPulse.parent_id}
            </span>
          </>
        ) : null}
        {selectedAnchor ? (
          <>
            <span>
              {selectedAnchor.origin} · {selectedAnchor.lock_state} · musical{' '}
              {selectedAnchor.musical_position.numerator}/
              {selectedAnchor.musical_position.denominator}
            </span>
            <span>
              pulse {selectedAnchor.pulse_id ?? 'none'} · confidence{' '}
              {selectedAnchor.confidence?.kind ?? 'none'}
            </span>
          </>
        ) : null}
        {selectedMeter ? (
          <>
            <span>
              {selectedMeter.numerator}/{selectedMeter.denominator} · grouping{' '}
              {selectedMeter.grouping.join('+')} · {selectedMeter.grid_validity}
            </span>
            <span>
              {selectedMeter.origin} · display unit {selectedMeter.display_tempo_unit} ·
              alternatives {selectedMeter.alternatives?.length ?? 0}
            </span>
          </>
        ) : null}
        <button type="button" onClick={() => setSelected(null)}>
          Clear
        </button>
      </div>
    ) : null

  return (
    <div className="rhythm-rhythm">
      <div
        ref={containerRef}
        className="rhythm-lanes"
        role="group"
        aria-label="Musical ruler and rhythm lanes"
        tabIndex={0}
        onClick={(event) => handleClick(event.clientX)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setSelected(null)
        }}
      >
        {!data ? (
          <div className="rhythm-lanes-empty">{notice ?? 'Rhythm grid unavailable'}</div>
        ) : (
          <>
            <div className="rhythm-lanes-bars" aria-hidden="true">
              {visible.map((event) => {
                const x = (event.source_frame - startFrame) / fpp
                return (
                  <span
                    key={`${event.kind}-${event.source_frame}-${event.label}`}
                    className={`rhythm-grid-line rhythm-grid-${event.kind}`}
                    style={{ left: `${x}px` }}
                  />
                )
              })}
            </div>
            <div className="rhythm-lanes-bar-labels" aria-hidden="true">
              {barLabels.map((bar) => (
                <span key={`bar-${bar.label}-${bar.x}`} style={{ left: `${bar.x}px` }}>
                  {bar.label}
                </span>
              ))}
            </div>
            <div className="rhythm-lanes-meter" aria-label="Meter regions">
              {data.meter_regions.map((region) => {
                const x =
                  (sourceAtMusical(
                    data.tempo_anchors.map((anchor) => ({
                      sourceFrame: anchor.source_frame,
                      musical: anchor.musical_position,
                    })),
                    region.start,
                  ).sourceFrame -
                    startFrame) /
                  fpp
                return (
                  <span
                    key={region.id}
                    className={`rhythm-meter-label meter-${region.grid_validity}`}
                    style={{ left: `${x}px` }}
                    title={`${region.numerator}/${region.denominator} (${region.grouping.join('+')})`}
                    role="button"
                    tabIndex={0}
                    onClick={(event) => {
                      event.stopPropagation()
                      setSelected({ kind: 'meter', id: region.id })
                    }}
                    onKeyDown={selectOnKey('meter', region.id)}
                  >
                    {region.numerator}/{region.denominator} ({region.grouping.join('+')})
                    {region.grid_validity === 'uncertain' ? ' ?' : ''}
                  </span>
                )
              })}
            </div>
            <div className="rhythm-lanes-tempo" aria-label="Tempo anchors">
              {data.tempo_anchors.map((anchor) => {
                const x = (anchor.source_frame - startFrame) / fpp
                return (
                  <span
                    key={anchor.id}
                    className={`rhythm-anchor ${anchor.lock_state === 'locked' ? 'locked' : ''}`}
                    style={{ left: `${x}px` }}
                    title={`Tempo anchor · ${anchor.origin}${anchor.lock_state === 'locked' ? ' · locked' : ''}`}
                    role="button"
                    tabIndex={0}
                    onClick={(event) => {
                      event.stopPropagation()
                      setSelected({ kind: 'anchor', id: anchor.id })
                    }}
                    onKeyDown={selectOnKey('anchor', anchor.id)}
                  >
                    {anchor.lock_state === 'locked' ? 'L' : ''}
                  </span>
                )
              })}
            </div>
            <div className="rhythm-lanes-pulses" aria-label="Pulses">
              {data.pulses.map((pulse) => {
                const x = (pulse.source_frame - startFrame) / fpp
                return (
                  <span
                    key={pulse.id}
                    className={[
                      'rhythm-pulse',
                      pulse.role === 'downbeat' ? 'downbeat' : '',
                      pulse.acceptance === 'candidate' ? 'candidate' : '',
                      pulse.origin === 'manual' ? 'manual' : '',
                    ].join(' ')}
                    style={{ left: `${x}px` }}
                    title={`${pulse.role} · ${pulse.origin} · ${pulse.review_state}`}
                    role="button"
                    tabIndex={0}
                    onClick={(event) => {
                      event.stopPropagation()
                      setSelected({ kind: 'pulse', id: pulse.id })
                    }}
                    onKeyDown={selectOnKey('pulse', pulse.id)}
                  />
                )
              })}
            </div>
            <div ref={playheadRef} className="rhythm-playhead" aria-hidden="true" />
          </>
        )}
      </div>
      {inspection}
    </div>
  )
}
