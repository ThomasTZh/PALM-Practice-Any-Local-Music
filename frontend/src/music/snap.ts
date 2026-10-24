/** Edit-time musical snapping geometry (M3.12 §14).
 *
 * Mirrors the backend radius semantics: convert the CSS-pixel radius
 * through the current viewport scale, consider nearby candidates only,
 * and preserve the unsnapped position when none is inside the radius.
 */

export type SnapMode = 'off' | 'beat' | 'half_beat' | 'quarter_beat' | 'bar' | 'event'

export interface SnapCandidate {
  frame: number
  label?: string
}

export interface SnapDecision {
  mode: SnapMode
  position: number
  snappedFrame: number
  snapped: boolean
  label?: string
  distanceFrames: number
  radiusFrames: number
}

export const SNAP_RADIUS_CSS_PX = 8

export function radiusFrames(framesPerPixel: number, radiusCssPx = SNAP_RADIUS_CSS_PX): number {
  if (!Number.isFinite(framesPerPixel) || framesPerPixel <= 0) return 0
  return Math.max(0, framesPerPixel * Math.max(0, radiusCssPx))
}

export function effectiveSnapMode(
  mode: SnapMode,
  modifierPressed: boolean,
  lastNonOff: SnapMode,
): SnapMode {
  if (!modifierPressed) return mode
  if (mode === 'off') return lastNonOff === 'off' ? 'beat' : lastNonOff
  return 'off'
}

/** Filter already-derived grid events to the targets a mode may use. */
export function snapModeKinds(mode: SnapMode): string[] {
  if (mode === 'bar') return ['bar']
  if (mode === 'beat') return ['primary']
  if (mode === 'half_beat') return ['primary', 'half_beat']
  if (mode === 'quarter_beat') return ['primary', 'half_beat', 'quarter_beat']
  return []
}

export function snapToCandidates(
  position: number,
  candidates: SnapCandidate[],
  framesPerPixel: number,
  radiusCssPx = SNAP_RADIUS_CSS_PX,
): SnapDecision {
  const radius = radiusFrames(framesPerPixel, radiusCssPx)
  let best: SnapCandidate | null = null
  for (const candidate of candidates) {
    const distance = Math.abs(candidate.frame - position)
    if (distance > radius) continue
    if (
      best === null ||
      distance < Math.abs(best.frame - position) ||
      (distance === Math.abs(best.frame - position) && candidate.frame < best.frame)
    ) {
      best = candidate
    }
  }
  return {
    mode: 'event',
    position,
    snappedFrame: best ? best.frame : position,
    snapped: best !== null,
    label: best?.label,
    distanceFrames: best ? Math.abs(best.frame - position) : 0,
    radiusFrames: radius,
  }
}
