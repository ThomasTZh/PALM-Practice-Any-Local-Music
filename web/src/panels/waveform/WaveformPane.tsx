import {
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import { buildColumnPath, decodePeaks } from "./peaks";
import {
  beginSelection,
  hasSelection,
  updateSelection,
  type Selection,
  type SelectionDrag,
} from "./selection";
import {
  fitViewport,
  followViewport,
  scrollViewport,
  timeToX,
  zoomToSelection,
  zoomViewport,
  type Viewport,
} from "./viewport";

export interface Lane {
  id: string;
  name: string;
  peaks: ArrayBuffer;
}

export interface WaveformPaneProps {
  lane: Lane;
  viewport: Viewport;
  durationSeconds: number;
  selection: Selection | null;
  positionSeconds: number;
  playing?: boolean;
  follow?: boolean;
  widthPx?: number;
  heightPx?: number;
  onViewportChange: (viewport: Viewport) => void;
  onSelectionChange: (selection: Selection | null) => void;
  onSeek: (seconds: number) => void;
  onTogglePlay: () => void;
  onToggleFollow: () => void;
}

const DEFAULT_WIDTH = 960;
const DEFAULT_HEIGHT = 96;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * One waveform lane. Zoom, scroll, selection drag, playhead and follow all
 * derive from the shared viewport, and the pure helpers do the math.
 */
export function WaveformPane({
  lane,
  viewport,
  durationSeconds,
  selection,
  positionSeconds,
  playing = false,
  follow = false,
  widthPx = DEFAULT_WIDTH,
  heightPx = DEFAULT_HEIGHT,
  onViewportChange,
  onSelectionChange,
  onSeek,
  onTogglePlay,
  onToggleFollow,
}: WaveformPaneProps) {
  const paneRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<SelectionDrag | null>(null);

  const peaks = useMemo(() => {
    try {
      return decodePeaks(lane.peaks);
    } catch {
      return null;
    }
  }, [lane.peaks]);

  const path = useMemo(
    () =>
      peaks === null ? "" : buildColumnPath(peaks, viewport, widthPx, heightPx),
    [peaks, viewport, widthPx, heightPx],
  );

  useEffect(() => {
    if (!follow || !playing) {
      return;
    }
    const next = followViewport(
      viewport,
      positionSeconds,
      durationSeconds,
      widthPx,
    );
    if (next !== viewport) {
      onViewportChange(next);
    }
  }, [
    follow,
    playing,
    viewport,
    positionSeconds,
    durationSeconds,
    widthPx,
    onViewportChange,
  ]);

  useEffect(() => {
    const element = paneRef.current;
    if (element === null) {
      return;
    }
    const pane: HTMLDivElement = element;
    function handleWheel(event: WheelEvent): void {
      const rect = pane.getBoundingClientRect();
      const width = rect.width > 0 ? rect.width : widthPx;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const anchor = clamp(event.clientX - rect.left, 0, width);
        const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2;
        onViewportChange(
          zoomViewport(viewport, durationSeconds, widthPx, factor, anchor),
        );
        return;
      }
      const horizontal = event.deltaX !== 0 ? event.deltaX : event.deltaY;
      if (Math.abs(horizontal) >= 1) {
        event.preventDefault();
        onViewportChange(
          scrollViewport(viewport, durationSeconds, widthPx, horizontal),
        );
      }
    }
    element.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      element.removeEventListener("wheel", handleWheel);
    };
  }, [viewport, durationSeconds, widthPx, onViewportChange]);

  function timeAtClientX(event: MouseEvent<HTMLElement>): number {
    const element = event.currentTarget;
    const rect = element.getBoundingClientRect();
    const width = rect.width > 0 ? rect.width : widthPx;
    const x = clamp(event.clientX - rect.left, 0, width);
    return (
      viewport.startSeconds + (x / width) * widthPx * viewport.secondsPerPixel
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const seekStep = event.shiftKey ? 5 : 1;
    switch (event.key) {
      case " ":
        event.preventDefault();
        onTogglePlay();
        break;
      case "+":
      case "=":
        onViewportChange(
          zoomViewport(viewport, durationSeconds, widthPx, 1.5, widthPx / 2),
        );
        break;
      case "-":
      case "_":
        onViewportChange(
          zoomViewport(
            viewport,
            durationSeconds,
            widthPx,
            1 / 1.5,
            widthPx / 2,
          ),
        );
        break;
      case "0":
        onViewportChange(fitViewport(durationSeconds, widthPx));
        break;
      case "z":
      case "Z":
        onViewportChange(
          selection !== null && hasSelection(selection)
            ? zoomToSelection(selection, durationSeconds, widthPx)
            : fitViewport(durationSeconds, widthPx),
        );
        break;
      case "f":
      case "F":
        onToggleFollow();
        break;
      case "ArrowRight":
        event.preventDefault();
        onSeek(clamp(positionSeconds + seekStep, 0, durationSeconds));
        break;
      case "ArrowLeft":
        event.preventDefault();
        onSeek(clamp(positionSeconds - seekStep, 0, durationSeconds));
        break;
      default:
        break;
    }
  }

  function handleMouseDown(event: MouseEvent<HTMLDivElement>): void {
    if (event.button !== 0) {
      return;
    }
    const nextDrag = beginSelection(timeAtClientX(event), durationSeconds);
    dragRef.current = nextDrag;
    onSelectionChange(updateSelection(nextDrag, nextDrag.anchorSeconds));
  }

  function handleMouseMove(event: MouseEvent<HTMLDivElement>): void {
    const activeDrag = dragRef.current;
    if (activeDrag === null) {
      return;
    }
    onSelectionChange(updateSelection(activeDrag, timeAtClientX(event)));
  }

  function handleMouseUp(event: MouseEvent<HTMLDivElement>): void {
    const activeDrag = dragRef.current;
    if (activeDrag === null) {
      return;
    }
    const next = updateSelection(activeDrag, timeAtClientX(event));
    dragRef.current = null;
    if (hasSelection(next)) {
      onSelectionChange(next);
      return;
    }
    onSelectionChange(null);
    onSeek(next.startSeconds);
  }

  const selectionRect =
    selection === null
      ? null
      : {
          x: timeToX(selection.startSeconds, viewport),
          width:
            (selection.endSeconds - selection.startSeconds) /
            viewport.secondsPerPixel,
        };

  return (
    <div
      className="waveform-pane"
      data-testid={`waveform-${lane.id}`}
      ref={paneRef}
      role="group"
      aria-label={`${lane.name} waveform pane`}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <div className="waveform-lane-header">
        <span className="waveform-lane-name">{lane.name}</span>
        {peaks === null && (
          <span className="waveform-error">Waveform unavailable</span>
        )}
      </div>
      <svg
        className="waveform-canvas"
        role="img"
        aria-label={`${lane.name} waveform`}
        width={widthPx}
        height={heightPx}
        viewBox={`0 0 ${widthPx} ${heightPx}`}
        preserveAspectRatio="none"
      >
        {peaks !== null && (
          <path
            className="waveform-path"
            data-testid={`waveform-path-${lane.id}`}
            d={path}
          />
        )}
        {selectionRect !== null && (
          <rect
            className="waveform-selection"
            data-testid={`waveform-selection-${lane.id}`}
            x={selectionRect.x}
            y={0}
            width={Math.max(0, selectionRect.width)}
            height={heightPx}
          />
        )}
        <line
          className="waveform-playhead"
          data-testid={`waveform-playhead-${lane.id}`}
          x1={timeToX(positionSeconds, viewport)}
          x2={timeToX(positionSeconds, viewport)}
          y1={0}
          y2={heightPx}
        />
      </svg>
    </div>
  );
}
