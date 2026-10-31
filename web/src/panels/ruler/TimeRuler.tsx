import type { MouseEvent } from "react";

import type { Grid } from "../../state/types";
import {
  timeToX,
  visibleEndSeconds,
  type Viewport,
} from "../waveform/viewport";
import { barBeatTicks, chooseSecondsTicks } from "./ticks";

export interface TimeRulerProps {
  viewport: Viewport;
  widthPx: number;
  grid: Grid | null;
  positionSeconds: number;
  onSeek?: (seconds: number) => void;
}

/**
 * Shared time ruler: seconds on one strip, bars and beats on the next. Both
 * strips use the same viewport as the waveform lanes, so they cannot drift
 * apart.
 */
export function TimeRuler({
  viewport,
  widthPx,
  grid,
  positionSeconds,
  onSeek,
}: TimeRulerProps) {
  const secondsTicks = chooseSecondsTicks(viewport, widthPx);
  const pixelsPerSecond = 1 / viewport.secondsPerPixel;
  const barTicks =
    grid === null
      ? null
      : barBeatTicks(
          grid,
          viewport.startSeconds,
          visibleEndSeconds(viewport, widthPx),
          pixelsPerSecond,
        );

  function handleClick(event: MouseEvent<HTMLDivElement>): void {
    if (!onSeek) {
      return;
    }
    const element = event.currentTarget;
    const rect = element.getBoundingClientRect();
    const width = rect.width > 0 ? rect.width : widthPx;
    const x = Math.min(width, Math.max(0, event.clientX - rect.left));
    const visibleSpan = widthPx * viewport.secondsPerPixel;
    onSeek(viewport.startSeconds + (x / width) * visibleSpan);
  }

  return (
    <div
      className="ruler"
      data-testid="time-ruler"
      style={{ width: widthPx }}
      onClick={handleClick}
      title="Click to seek"
    >
      <div className="ruler-seconds" data-testid="ruler-seconds">
        {secondsTicks.map((tick) => (
          <span
            key={`second-${tick.time}`}
            className={
              tick.major
                ? "ruler-tick ruler-tick-major"
                : "ruler-tick ruler-tick-minor"
            }
            data-major={tick.major}
            style={{ left: timeToX(tick.time, viewport) }}
          >
            {tick.label !== null && <em>{tick.label}</em>}
          </span>
        ))}
      </div>
      {barTicks !== null && (
        <div className="ruler-bars" data-testid="ruler-bars">
          {barTicks.map((tick) => (
            <span
              key={`bar-${tick.bar}-${tick.beat}`}
              className={
                tick.downbeat ? "ruler-beat ruler-beat-downbeat" : "ruler-beat"
              }
              data-bar={tick.bar}
              data-beat={tick.beat}
              style={{ left: timeToX(tick.time, viewport) }}
            >
              {tick.label !== null && <em>{tick.label}</em>}
            </span>
          ))}
        </div>
      )}
      <div
        className="ruler-playhead"
        data-testid="ruler-playhead"
        style={{ left: timeToX(positionSeconds, viewport) }}
      />
    </div>
  );
}
