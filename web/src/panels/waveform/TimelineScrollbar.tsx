import { useRef, useState } from "react";

import {
  clampViewport,
  visibleEndSeconds,
  type Viewport,
} from "./viewport";

export interface TimelineScrollbarProps {
  viewport: Viewport;
  durationSeconds: number;
  widthPx: number;
  onViewportChange: (viewport: Viewport) => void;
}

const MIN_THUMB_PX = 24;

/**
 * Horizontal scrollbar for a zoomed timeline. The thumb represents the visible
 * span, so it only appears when the view is narrower than the track.
 */
export function TimelineScrollbar({
  viewport,
  durationSeconds,
  widthPx,
  onViewportChange,
}: TimelineScrollbarProps) {
  const [drag, setDrag] = useState<{
    startX: number;
    startSeconds: number;
  } | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const width = Math.max(1, widthPx);
  const duration =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : 0;
  const visibleSpan = width * viewport.secondsPerPixel;
  if (duration <= 0 || visibleSpan >= duration - 1e-9) {
    return null;
  }

  const thumbWidth = Math.max(
    MIN_THUMB_PX,
    Math.min(width, (visibleSpan / duration) * width),
  );
  const maxLeft = Math.max(0, width - thumbWidth);
  const thumbLeft = Math.min(
    maxLeft,
    Math.max(0, (viewport.startSeconds / duration) * width),
  );

  function trackWidth(): number {
    const measured = trackRef.current?.getBoundingClientRect().width ?? 0;
    return measured > 0 ? measured : width;
  }

  function beginDrag(event: React.PointerEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setDrag({ startX: event.clientX, startSeconds: viewport.startSeconds });
    if (
      event.pointerId !== undefined &&
      typeof event.currentTarget.setPointerCapture === "function"
    ) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  }

  function moveDrag(event: React.PointerEvent<HTMLDivElement>): void {
    if (drag === null) {
      return;
    }
    const pixels = event.clientX - drag.startX;
    const nextStart =
      drag.startSeconds + (pixels / trackWidth()) * duration;
    onViewportChange(
      clampViewport(
        {
          startSeconds: nextStart,
          secondsPerPixel: viewport.secondsPerPixel,
        },
        duration,
        width,
      ),
    );
  }

  function endDrag(): void {
    setDrag(null);
  }

  return (
    <div
      className={`timeline-scrollbar${drag === null ? "" : " dragging"}`}
      data-testid="timeline-scrollbar"
      role="scrollbar"
      aria-label="Timeline scroll"
      aria-orientation="horizontal"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(viewport.startSeconds)}
      aria-valuetext={`${viewport.startSeconds.toFixed(1)} to ${visibleEndSeconds(
        viewport,
        width,
      ).toFixed(1)} seconds`}
      style={{ width }}
    >
      <div
        ref={trackRef}
        className="timeline-scrollbar-track"
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div
          className="timeline-scrollbar-thumb"
          data-testid="timeline-scrollbar-thumb"
          style={{ left: thumbLeft, width: thumbWidth }}
          onPointerDown={beginDrag}
        />
      </div>
    </div>
  );
}
