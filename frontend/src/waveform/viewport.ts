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

// ---------------------------------------------------------------------------
// Interactive view math (M1.11, spec §13.1).
//
// A `View` is the width-free part of a viewport — the fractional start
// frame and the zoom. The component stores the `View` and derives the
// full `Viewport` with the measured content width, so window resizes do
// not disturb the user's zoom. Fractional coordinates are preserved
// throughout for smooth movement (§13.1.10).
// ---------------------------------------------------------------------------

/** Maximum zoom: eight CSS pixels per source frame (spec §13.1.8). */
export const MAX_PX_PER_FRAME = 8

/** Minimum frames-per-CSS-pixel (= 1 / MAX_PX_PER_FRAME). */
export const MIN_FPP = 1 / MAX_PX_PER_FRAME

export interface View {
  startFrame: number
  fpp: number
}

/** Clamp a zoom to the permitted range (spec §13.1.8). */
export function clampFpp(fpp: number): number {
  if (!(fpp > 0)) throw new RangeError('fpp must be > 0')
  return Math.max(MIN_FPP, fpp)
}

/** How many source frames the view spans at the given width. */
export function visibleFrames(view: View, widthCssPx: number): number {
  if (!(widthCssPx > 0)) throw new RangeError('widthCssPx must be > 0')
  return widthCssPx * view.fpp
}

/**
 * Clamp the start frame so the view stays inside the source
 * (spec §13.1.9). When the view spans at least the whole source the
 * start is pinned to zero.
 */
export function clampView(view: View, durationFrames: number, widthCssPx: number): View {
  if (durationFrames < 0) throw new RangeError('durationFrames must be >= 0')
  const visible = visibleFrames(view, widthCssPx)
  const maxStart = Math.max(0, durationFrames - visible)
  return { startFrame: Math.min(maxStart, Math.max(0, view.startFrame)), fpp: view.fpp }
}

/**
 * Zoom by `factor` while keeping `anchorFrame` at the same x position
 * (pointer-anchored zoom, spec §13.1.4; pass the playhead frame for
 * keyboard zoom, §13.1.5). The result is clamped.
 */
export function zoomView(
  view: View,
  factor: number,
  anchorFrame: number,
  durationFrames: number,
  widthCssPx: number,
): View {
  if (!(factor > 0)) throw new RangeError('factor must be > 0')
  const fpp = clampFpp(view.fpp * factor)
  const anchorX = (anchorFrame - view.startFrame) / view.fpp
  return clampView({ startFrame: anchorFrame - anchorX * fpp, fpp }, durationFrames, widthCssPx)
}

/** Pan by `deltaFrames`, clamped to the source (spec §13.2.4). */
export function panView(
  view: View,
  deltaFrames: number,
  durationFrames: number,
  widthCssPx: number,
): View {
  return clampView(
    { startFrame: view.startFrame + deltaFrames, fpp: view.fpp },
    durationFrames,
    widthCssPx,
  )
}

/**
 * View showing exactly `[startFrame, endFrame]` at the given width
 * (Fit Selection, spec §13.1.7). When the range is so small that it
 * would exceed the maximum zoom, the zoom is clamped and the range is
 * centered. The result is not duration-clamped; compose with
 * `clampView` when the duration is known.
 */
export function fitRangeView(startFrame: number, endFrame: number, widthCssPx: number): View {
  if (!(endFrame > startFrame)) throw new RangeError('endFrame must be > startFrame')
  if (!(widthCssPx > 0)) throw new RangeError('widthCssPx must be > 0')
  let fpp = (endFrame - startFrame) / widthCssPx
  let start = startFrame
  if (fpp < MIN_FPP) {
    fpp = MIN_FPP
    const visible = widthCssPx * fpp
    start = (startFrame + endFrame) / 2 - visible / 2
  }
  return { startFrame: start, fpp }
}
