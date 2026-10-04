/**
 * Viewport model and coordinate transforms (M1.10, spec §12.2).
 *
 * A viewport is the horizontal window over the source:
 * - `startFrame` — the source frame at x = 0 (fractional).
 * - `framesPerCssPixel` (fpp) — the horizontal zoom.
 * - `widthCssPx` — viewport width in CSS pixels.
 *
 * Every mapping in the editor (ruler labels, markers, selections,
 * playhead) goes through the two transforms below. Fractional
 * coordinates are preserved for smooth movement (spec §13.1.10).
 *
 * This module is pure — no DOM. Interactive viewport changes land in
 * M1.11; M1.10 uses only `fitViewport`.
 */

export interface Viewport {
  startFrame: number
  framesPerCssPixel: number
  widthCssPx: number
}

export function makeViewport(
  startFrame: number,
  framesPerCssPixel: number,
  widthCssPx: number,
): Viewport {
  if (startFrame < 0) throw new RangeError('startFrame must be >= 0')
  if (!(framesPerCssPixel > 0)) throw new RangeError('framesPerCssPixel must be > 0')
  if (!(widthCssPx > 0)) throw new RangeError('widthCssPx must be > 0')
  return { startFrame, framesPerCssPixel, widthCssPx }
}

/** Fit the whole source into the viewport width (M1.10's only view). */
export function fitViewport(durationFrames: number, widthCssPx: number): Viewport {
  if (!(durationFrames > 0)) throw new RangeError('durationFrames must be > 0')
  if (!(widthCssPx > 0)) throw new RangeError('widthCssPx must be > 0')
  return makeViewport(0, durationFrames / widthCssPx, widthCssPx)
}

/** `x = (frame - start_frame) / frames_per_css_pixel` (spec §12.2). */
export function frameToX(viewport: Viewport, frame: number): number {
  return (frame - viewport.startFrame) / viewport.framesPerCssPixel
}

/** `frame = start_frame + x * frames_per_css_pixel` (spec §12.2). */
export function xToFrame(viewport: Viewport, x: number): number {
  return viewport.startFrame + x * viewport.framesPerCssPixel
}

/**
 * Inclusive source-frame range intersecting the viewport, clamped to
 * `[0, durationFrames]`.
 */
export function visibleFrameRange(viewport: Viewport, durationFrames: number): [number, number] {
  if (durationFrames < 0) throw new RangeError('durationFrames must be >= 0')
  const first = Math.max(0, Math.floor(viewport.startFrame))
  const last = Math.min(durationFrames, Math.ceil(xToFrame(viewport, viewport.widthCssPx)))
  return [first, last]
}
