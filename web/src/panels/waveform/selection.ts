/**
 * Pointer selection for the waveform pane, kept pure so drag direction,
 * clamping and the minimum span are testable without a browser.
 */

export interface Selection {
  startSeconds: number;
  endSeconds: number;
}

export interface SelectionDrag {
  anchorSeconds: number;
  durationSeconds: number;
}

/** Shorter spans are clicks, not selections. */
export const MIN_SELECTION_SECONDS = 0.05;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function selectionBetween(a: number, b: number): Selection {
  return {
    startSeconds: Math.min(a, b),
    endSeconds: Math.max(a, b),
  };
}

export function beginSelection(
  timeSeconds: number,
  durationSeconds: number,
): SelectionDrag {
  const duration = Number.isFinite(durationSeconds)
    ? Math.max(0, durationSeconds)
    : 0;
  return {
    anchorSeconds: clamp(timeSeconds, 0, duration),
    durationSeconds: duration,
  };
}

export function updateSelection(
  drag: SelectionDrag,
  timeSeconds: number,
): Selection {
  const current = clamp(timeSeconds, 0, drag.durationSeconds);
  return selectionBetween(drag.anchorSeconds, current);
}

export function selectionSpan(selection: Selection): number {
  return Math.abs(selection.endSeconds - selection.startSeconds);
}

export function hasSelection(selection: Selection | null): boolean {
  return (
    selection !== null && selectionSpan(selection) >= MIN_SELECTION_SECONDS
  );
}
