/**
 * Viewport math for the shared ruler and waveform panes.
 *
 * A viewport is a window on the track: it starts at `startSeconds` and each
 * device pixel covers `secondsPerPixel`. Zooming and scrolling are pure
 * functions over that pair, so the ruler and every waveform lane stay aligned.
 */

export interface Viewport {
  startSeconds: number;
  secondsPerPixel: number;
}

export interface SelectionLike {
  startSeconds: number;
  endSeconds: number;
}

/** Finest zoom: half a millisecond per pixel. */
export const MIN_SECONDS_PER_PIXEL = 0.0005;

/** Span used when a track has no duration yet. */
export const EMPTY_SPAN_SECONDS = 0.25;

const EPSILON = 1e-9;

function safeWidth(widthPx: number): number {
  return Math.max(1, widthPx);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function sameViewport(a: Viewport, b: Viewport): boolean {
  return (
    a.startSeconds === b.startSeconds && a.secondsPerPixel === b.secondsPerPixel
  );
}

function maxSecondsPerPixel(durationSeconds: number, widthPx: number): number {
  const width = safeWidth(widthPx);
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : 0;
  const span = duration > 0 ? duration : EMPTY_SPAN_SECONDS;
  return Math.max(MIN_SECONDS_PER_PIXEL, span / width);
}

export function visibleEndSeconds(viewport: Viewport, widthPx: number): number {
  return viewport.startSeconds + safeWidth(widthPx) * viewport.secondsPerPixel;
}

export function timeToX(timeSeconds: number, viewport: Viewport): number {
  return (timeSeconds - viewport.startSeconds) / viewport.secondsPerPixel;
}

export function xToTime(x: number, viewport: Viewport): number {
  return viewport.startSeconds + x * viewport.secondsPerPixel;
}

export function clampViewport(
  viewport: Viewport,
  durationSeconds: number,
  widthPx: number,
): Viewport {
  const width = safeWidth(widthPx);
  const secondsPerPixel = clamp(
    viewport.secondsPerPixel,
    MIN_SECONDS_PER_PIXEL,
    maxSecondsPerPixel(durationSeconds, width),
  );
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : 0;
  const maxStart = Math.max(0, duration - width * secondsPerPixel);
  const startSeconds = clamp(viewport.startSeconds, 0, maxStart);
  const clamped = { startSeconds, secondsPerPixel };
  return sameViewport(clamped, viewport) ? viewport : clamped;
}

export function fitViewport(
  durationSeconds: number,
  widthPx: number,
): Viewport {
  const width = safeWidth(widthPx);
  const secondsPerPixel = maxSecondsPerPixel(durationSeconds, width);
  return { startSeconds: 0, secondsPerPixel };
}

export function zoomViewport(
  viewport: Viewport,
  durationSeconds: number,
  widthPx: number,
  factor: number,
  anchorPx: number,
): Viewport {
  if (!(factor > 0) || !Number.isFinite(factor)) {
    return viewport;
  }
  const width = safeWidth(widthPx);
  const anchor = clamp(anchorPx, 0, width);
  const anchorSeconds = xToTime(anchor, viewport);
  const secondsPerPixel = clamp(
    viewport.secondsPerPixel / factor,
    MIN_SECONDS_PER_PIXEL,
    maxSecondsPerPixel(durationSeconds, width),
  );
  const zoomed = clampViewport(
    { startSeconds: anchorSeconds - anchor * secondsPerPixel, secondsPerPixel },
    durationSeconds,
    width,
  );
  return sameViewport(zoomed, viewport) ? viewport : zoomed;
}

export function scrollViewport(
  viewport: Viewport,
  durationSeconds: number,
  widthPx: number,
  deltaPixels: number,
): Viewport {
  const scrolled = clampViewport(
    {
      startSeconds:
        viewport.startSeconds + deltaPixels * viewport.secondsPerPixel,
      secondsPerPixel: viewport.secondsPerPixel,
    },
    durationSeconds,
    widthPx,
  );
  return sameViewport(scrolled, viewport) ? viewport : scrolled;
}

export function zoomToSelection(
  selection: SelectionLike,
  durationSeconds: number,
  widthPx: number,
  paddingRatio = 0.08,
): Viewport {
  const span = Math.abs(selection.endSeconds - selection.startSeconds);
  if (!(span > EPSILON)) {
    return fitViewport(durationSeconds, widthPx);
  }
  const width = safeWidth(widthPx);
  const start = Math.min(selection.startSeconds, selection.endSeconds);
  const paddedSpan = span * (1 + 2 * paddingRatio);
  const secondsPerPixel = clamp(
    paddedSpan / width,
    MIN_SECONDS_PER_PIXEL,
    maxSecondsPerPixel(durationSeconds, width),
  );
  return clampViewport(
    { startSeconds: start - span * paddingRatio, secondsPerPixel },
    durationSeconds,
    width,
  );
}

/**
 * Paginated follow: while the playhead is inside the visible window and before
 * the 70 % page line, leave the viewport alone. Past that line (or when a loop
 * jumps back before the window), page so the playhead sits at 20 % of the span.
 */
export function followViewport(
  viewport: Viewport,
  positionSeconds: number,
  durationSeconds: number,
  widthPx: number,
  pageFraction = 0.7,
): Viewport {
  const width = safeWidth(widthPx);
  const span = width * viewport.secondsPerPixel;
  const leftEdge = viewport.startSeconds;
  const leftMargin = leftEdge + span * 0.05;
  const pageLine = leftEdge + span * clamp(pageFraction, 0.05, 0.95);
  if (
    positionSeconds >= leftMargin &&
    positionSeconds <= pageLine &&
    positionSeconds < leftEdge + span
  ) {
    return viewport;
  }
  const targetStart = positionSeconds - span * 0.2;
  const followed = clampViewport(
    { startSeconds: targetStart, secondsPerPixel: viewport.secondsPerPixel },
    durationSeconds,
    width,
  );
  return sameViewport(followed, viewport) ? viewport : followed;
}
