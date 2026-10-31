import { beatMarks } from "../../state/sections";
import {
  timeToX,
  visibleEndSeconds,
  type Viewport,
} from "../waveform/viewport";

export interface BarBeatOverlayProps {
  beats: number[];
  bpb: number;
  viewport: Viewport;
  widthPx: number;
}

/**
 * Bar and beat ticks on the shared timeline, derived from the detected beat
 * list and the chosen beats-per-bar. Downbeats carry the bar number.
 */
export function BarBeatOverlay({
  beats,
  bpb,
  viewport,
  widthPx,
}: BarBeatOverlayProps) {
  const visibleEnd = visibleEndSeconds(viewport, widthPx);
  const marks = beatMarks(beats, bpb).filter(
    (mark) =>
      mark.timeSeconds >= viewport.startSeconds &&
      mark.timeSeconds <= visibleEnd,
  );

  return (
    <div
      className="bar-beat-overlay"
      data-testid="bar-beat-overlay"
      aria-label="Bar and beat grid"
      style={{ width: widthPx }}
    >
      {marks.length === 0 ? (
        <span className="panel-empty">No beat grid yet.</span>
      ) : (
        marks.map((mark) => (
          <span
            key={`${mark.bar}-${mark.beat}`}
            className={
              mark.downbeat
                ? "bar-beat-tick bar-beat-downbeat"
                : "bar-beat-tick"
            }
            data-testid={`beat-${mark.bar}-${mark.beat}`}
            data-downbeat={mark.downbeat}
            style={{ left: timeToX(mark.timeSeconds, viewport) }}
          >
            {mark.downbeat && <em>{mark.bar}</em>}
          </span>
        ))
      )}
    </div>
  );
}
