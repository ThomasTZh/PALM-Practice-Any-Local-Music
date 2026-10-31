import type { Grid } from "./types";

/** Clock display for the ruler and the transport, e.g. `1:05` or `1:05.4`. */
export function formatClock(seconds: number, tenths = false): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const rounded = tenths ? Math.round(safe * 10) / 10 : Math.floor(safe + 1e-9);
  const whole = Math.floor(rounded);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  const restText = tenths
    ? `${String(rest).padStart(2, "0")}.${Math.round((rounded - whole) * 10)}`
    : String(rest).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${restText}`;
  }
  return `${minutes}:${restText}`;
}

/** Transport readout: tenths of a second, because practise is timing. */
export function formatPosition(seconds: number): string {
  return formatClock(seconds, true);
}

/** Speed label without trailing zeros: `1×`, `0.75×`. */
export function formatSpeed(speed: number): string {
  return `${Number(speed.toFixed(3))}×`;
}

/** Bar and beat for a position, or null when the grid is not known yet. */
export function formatBarBeat(
  positionSeconds: number,
  grid: Grid | null,
): string | null {
  if (!grid || !(grid.bpm > 0) || !(grid.meter.numerator > 0)) {
    return null;
  }
  const beatSeconds = 60 / grid.bpm;
  const relative = positionSeconds - grid.offsetSeconds;
  const beatIndex = Math.max(0, Math.floor(relative / beatSeconds + 1e-9));
  const bar = Math.floor(beatIndex / grid.meter.numerator) + 1;
  const beat = (beatIndex % grid.meter.numerator) + 1;
  return `bar ${bar} · beat ${beat}`;
}

/** Display name for a project or stem title. */
export function formatTitle(value: string | null | undefined): string {
  return value && value.trim().length > 0 ? value : "Untitled";
}
