/** Pure musical-ruler geometry and hit testing (M3.11 §13.2-§13.7, §13.9).
 *
 * Kept outside React and DOM so ruler primitives can be derived only for
 * the visible viewport and cached independently of playhead updates.
 */

export type GridEventKind = 'bar' | 'primary' | 'denominator' | 'half_beat' | 'quarter_beat'

export type RulerDetail = 'bars' | 'primary' | 'denominator' | 'half_beat' | 'quarter_beat'

export interface GridLikeEvent {
  kind: GridEventKind
  source_frame: number
  label: string
}

export type RulerHandleKind =
  'drag' | 'tempo_anchor' | 'meter_boundary' | 'pulse' | 'ruler' | 'waveform'

export interface RulerHandle {
  id: string
  kind: RulerHandleKind
  /** Viewport-space center in CSS pixels. */
  x: number
  /** Nominal handle width in CSS pixels. */
  width: number
}

const DETAIL_ORDER: RulerDetail[] = ['bars', 'primary', 'denominator', 'half_beat', 'quarter_beat']

const KIND_LEVEL: Record<GridEventKind, number> = {
  bar: 0,
  primary: 1,
  denominator: 2,
  half_beat: 3,
  quarter_beat: 4,
}

const HANDLE_PRIORITY: Record<RulerHandleKind, number> = {
  drag: 0,
  tempo_anchor: 1,
  meter_boundary: 2,
  pulse: 3,
  ruler: 4,
  waveform: 5,
}

/** Detail level for horizontal zoom in CSS pixels per quarter note. */
export function detailForZoom(pixelsPerQuarter: number): RulerDetail {
  if (!Number.isFinite(pixelsPerQuarter) || pixelsPerQuarter <= 0) {
    return 'bars'
  }
  if (pixelsPerQuarter < 12) return 'bars'
  if (pixelsPerQuarter < 48) return 'primary'
  if (pixelsPerQuarter < 120) return 'denominator'
  if (pixelsPerQuarter < 300) return 'half_beat'
  return 'quarter_beat'
}

function levelFor(detail: RulerDetail): number {
  return DETAIL_ORDER.indexOf(detail)
}

/** Events in a source-frame range at or below the requested detail, sorted. */
export function visibleGridEvents(
  events: GridLikeEvent[],
  startFrame: number,
  endFrame: number,
  detail: RulerDetail,
  marginFrames = 0,
): GridLikeEvent[] {
  if (endFrame < startFrame) return []
  const limit = levelFor(detail)
  const low = startFrame - marginFrames
  const high = endFrame + marginFrames

  let lowIndex = 0
  let highIndex = events.length
  while (lowIndex < highIndex) {
    const middle = (lowIndex + highIndex) >> 1
    if (events[middle].source_frame < low) lowIndex = middle + 1
    else highIndex = middle
  }
  const result: GridLikeEvent[] = []
  for (let index = lowIndex; index < events.length; index += 1) {
    const event = events[index]
    if (event.source_frame > high) break
    if (KIND_LEVEL[event.kind] <= limit) result.push(event)
  }
  return result
}

/**
 * Suppress labels whose viewport positions would overlap. Bar and meter
 * labels are retained first; lower-priority labels are dropped.
 */
export function suppressOverlappingLabels(
  events: GridLikeEvent[],
  pixelsPerFrame: number,
  minimumSpacingPx = 44,
): GridLikeEvent[] {
  if (!Number.isFinite(pixelsPerFrame) || pixelsPerFrame <= 0) return []
  const kept: GridLikeEvent[] = []
  const occupied: number[] = []
  for (const event of events) {
    const x = event.source_frame * pixelsPerFrame
    if (occupied.some((other) => Math.abs(other - x) < minimumSpacingPx)) {
      continue
    }
    kept.push(event)
    occupied.push(x)
  }
  return kept
}

/**
 * Viewport-space hit testing with a minimum practical handle width and the
 * documented priority order (§13.7).
 */
export function hitTestHandles(
  handles: RulerHandle[],
  x: number,
  minimumWidthPx = 8,
): RulerHandle | null {
  if (!Number.isFinite(x)) return null
  const ordered = [...handles].sort(
    (left, right) => HANDLE_PRIORITY[left.kind] - HANDLE_PRIORITY[right.kind],
  )
  for (const handle of ordered) {
    const halfWidth = Math.max(minimumWidthPx, handle.width) / 2
    if (Math.abs(handle.x - x) <= halfWidth) return handle
  }
  return null
}
