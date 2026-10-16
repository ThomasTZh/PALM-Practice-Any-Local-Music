/**
 * Playback speed control (M2.9, spec §11.6).
 *
 * Pitch-preserving speed 0.25×…2.0×: a slider (step 0.01), a numeric
 * entry, presets (0.25 / 0.5 / 0.75 / 1.0 / 1.25 / 1.5 / 2.0), and a
 * "1×" reset. Gesture coalescing (§11.7.8): dragging the slider updates
 * only the local display; one op is committed on release (pointer-up,
 * key-up, blur) — the same for Enter in the numeric entry, a preset
 * click, and the reset. Invalid numeric input is clamped and the
 * current value is preserved (§11.6).
 */
import { useState } from 'react'

export const SPEED_MIN = 0.25
export const SPEED_MAX = 2.0
export const SPEED_STEP = 0.01
export const SPEED_PRESETS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

/** Clamp to the spec range; non-finite input falls back to 1×. */
export function clampSpeed(value: number): number {
  if (!Number.isFinite(value)) return 1.0
  return Math.max(SPEED_MIN, Math.min(SPEED_MAX, value))
}

export interface SpeedControlProps {
  /** The committed speed (from the practice state). */
  speed: number
  /** Commit a speed (sends `set_playback_speed`). */
  onCommit: (speed: number) => void
}

export function SpeedControl({ speed, onCommit }: SpeedControlProps) {
  // Local display value while a gesture is in flight (coalescing, §11.7.8).
  const [draft, setDraft] = useState<number | null>(null)
  // Raw numeric-entry text (null when not editing).
  const [entry, setEntry] = useState<string | null>(null)
  const shown = draft ?? speed

  const commit = (value: number) => {
    setDraft(null)
    onCommit(clampSpeed(value))
  }

  const release = () => {
    if (draft !== null) commit(draft)
  }

  const commitEntry = () => {
    if (entry === null) return
    const text = entry.trim()
    setEntry(null)
    if (text === '') return // empty entry: preserve the current value
    const parsed = Number(text)
    if (Number.isFinite(parsed)) commit(parsed)
    // else: invalid input — preserve the current value.
  }

  return (
    <div className="speed-control" role="group" aria-label="Playback speed">
      <label className="mixer-field">
        <span className="mixer-field-label">Speed</span>
        <input
          type="range"
          className="speed-slider"
          min={SPEED_MIN}
          max={SPEED_MAX}
          step={SPEED_STEP}
          value={shown}
          aria-label="Playback speed slider"
          onChange={(e) => setDraft(Number(e.currentTarget.value))}
          onPointerUp={release}
          onKeyUp={release}
          onBlur={release}
        />
        <span className="mixer-field-value">{shown.toFixed(2)}×</span>
      </label>
      <input
        type="number"
        className="speed-entry"
        min={SPEED_MIN}
        max={SPEED_MAX}
        step={SPEED_STEP}
        value={entry ?? shown.toFixed(2)}
        aria-label="Playback speed value"
        onChange={(e) => setEntry(e.currentTarget.value)}
        onBlur={commitEntry}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitEntry()
        }}
      />
      <div className="speed-presets">
        {SPEED_PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            className={p === speed ? 'speed-preset active' : 'speed-preset'}
            onClick={() => commit(p)}
          >
            {p}×
          </button>
        ))}
        <button
          type="button"
          className="speed-reset"
          aria-label="Reset speed to 1×"
          onClick={() => commit(1.0)}
        >
          1×
        </button>
      </div>
    </div>
  )
}
