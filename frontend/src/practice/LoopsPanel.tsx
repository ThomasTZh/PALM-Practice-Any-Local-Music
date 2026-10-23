/**
 * Practice loops panel (M2.11, spec §13.2).
 *
 * The saved-loop list next to the mixer: create from the waveform
 * selection, select the active loop, inline rename, color cycle,
 * numeric boundaries in seconds (3 decimals, committed on Enter/blur),
 * duration + exact frame readout, repeat count (blank = infinite),
 * the boundary-fade toggle, duplicate/delete, and the looping toggle
 * (the `L` shortcut and the checkbox share this path through the App).
 *
 * The panel is presentational: every edit is reported through a
 * callback, which the caller turns into an undoable project command.
 * Invalid numeric entries are reverted locally and never sent
 * (spec §13.3.5: the interval is never expanded silently).
 */

import type { PracticeLoop } from '../api/commands'
import { formatTime } from '../playback/pcm'
import { LOOP_COLORS } from '../waveform/render'

/** One loop edit; `repeat_count: null` means infinite (explicit). */
export interface LoopPatch {
  name?: string
  color?: string
  start_frames?: number
  end_frames?: number
  repeat_count?: number | null
  boundary_fade?: boolean
}

/** Total-pass bounds and the repeatable minimum (spec §13.1, §13.3.3). */
export const MAX_LOOP_REPEAT = 9999
export const MIN_REPEATABLE_LOOP_SECONDS = 0.1

export const MAX_LOOP_NAME_LENGTH = 80

/** The next palette color after `color` (cycles when unknown). */
export function nextLoopColor(color: string): string {
  const i = (LOOP_COLORS as readonly string[]).indexOf(color)
  return LOOP_COLORS[(i + 1) % LOOP_COLORS.length]
}

export interface LoopsPanelProps {
  loops: PracticeLoop[]
  /** The active loop id (null → no active loop). */
  activeLoopId: string | null
  /** Whether repeated playback is enabled (practice state). */
  loopEnabled: boolean
  /** The live waveform selection, the source for "Create from selection". */
  selection: { start: number; end: number } | null
  /** Project sample rate (seconds display + entry); 0 → frames only. */
  sampleRate: number
  /** Source length in frames (numeric-entry bound). */
  durationFrames: number
  /** Notices (e.g. the 100 ms minimum explanation); null → none. */
  notice: string | null
  onCreateFromSelection: () => void
  onUpdate: (id: string, patch: LoopPatch) => void
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
  onSelectActive: (id: string) => void
  onSetEnabled: (enabled: boolean) => void
}

/** Seconds with 3 decimals, the numeric-entry display form (§13.2.2). */
function secondsOf(frames: number, sampleRate: number): string {
  return (frames / sampleRate).toFixed(3)
}

export function LoopsPanel({
  loops,
  activeLoopId,
  loopEnabled,
  selection,
  sampleRate,
  durationFrames,
  notice,
  onCreateFromSelection,
  onUpdate,
  onDuplicate,
  onDelete,
  onSelectActive,
  onSetEnabled,
}: LoopsPanelProps) {
  /** Commit a boundary entry; false → revert the input (invalid entry). */
  const commitBoundary = (loop: PracticeLoop, which: 'start' | 'end', raw: string): boolean => {
    const current = which === 'start' ? loop.start_frames : loop.end_frames
    const shown = secondsOf(current, sampleRate)
    const text = raw.trim()
    if (text === shown) return true // untouched
    const seconds = Number(text)
    if (text === '' || !Number.isFinite(seconds)) return false
    const frames = Math.round(seconds * sampleRate)
    if (frames === current) return true
    if (which === 'start') {
      if (frames < 0 || frames >= loop.end_frames) return false
      onUpdate(loop.id, { start_frames: frames })
    } else {
      if (frames <= loop.start_frames || (durationFrames > 0 && frames > durationFrames))
        return false
      onUpdate(loop.id, { end_frames: frames })
    }
    return true
  }

  /** Commit a repeat entry; false → revert (non-integer / out of range). */
  const commitRepeat = (loop: PracticeLoop, raw: string): boolean => {
    const shown = loop.repeat_count == null ? '' : String(loop.repeat_count)
    const text = raw.trim()
    if (text === shown) return true // untouched
    if (text === '') {
      // Blank = infinite (§13.1); explicit null (not absent).
      onUpdate(loop.id, { repeat_count: null })
      return true
    }
    const n = Number(text)
    if (!Number.isInteger(n) || n < 1 || n > MAX_LOOP_REPEAT) return false
    onUpdate(loop.id, { repeat_count: n })
    return true
  }

  const commitName = (loop: PracticeLoop, raw: string): void => {
    const name = raw.trim()
    if (!name || name === loop.name) return
    onUpdate(loop.id, { name: name.slice(0, MAX_LOOP_NAME_LENGTH) })
  }

  return (
    <section className="loops-panel" aria-label="Practice loops">
      <div className="loops-header">
        <span className="loops-title">Loops</span>
        <button
          type="button"
          className="loops-create"
          onClick={onCreateFromSelection}
          disabled={!selection}
          title={selection ? undefined : 'Select a range on the waveform first'}
        >
          Create from selection
        </button>
        <label className="loops-enable" title="Loops must be at least 100 ms to repeat">
          <input
            type="checkbox"
            checked={loopEnabled}
            disabled={!activeLoopId}
            aria-label="Looping"
            onChange={(e) => onSetEnabled(e.target.checked)}
          />
          Looping
        </label>
        <span className="loops-hint muted">Drag selects; grip moves loop; L toggles</span>
      </div>
      {notice && (
        <p className="loops-notice" role="alert">
          {notice}
        </p>
      )}
      {loops.length === 0 ? (
        <p className="loops-empty muted">
          No loops yet. Select a passage on the waveform, then create a loop from it.
        </p>
      ) : (
        <ul className="loops-list" aria-label="Loop list">
          {loops.map((loop) => {
            const length = loop.end_frames - loop.start_frames
            const tooShort = sampleRate > 0 && length < MIN_REPEATABLE_LOOP_SECONDS * sampleRate
            return (
              <li
                key={loop.id}
                className={loop.id === activeLoopId ? 'loops-item selected' : 'loops-item'}
                onClick={() => onSelectActive(loop.id)}
              >
                <button
                  type="button"
                  className="loop-swatch"
                  style={{ backgroundColor: loop.color }}
                  aria-label={`Loop color ${loop.color}`}
                  title="Cycle color"
                  onClick={(e) => {
                    e.stopPropagation()
                    onUpdate(loop.id, { color: nextLoopColor(loop.color) })
                  }}
                />
                <input
                  key={`name:${loop.id}:${loop.name}`}
                  className="loop-name"
                  defaultValue={loop.name}
                  maxLength={MAX_LOOP_NAME_LENGTH}
                  aria-label="Loop name"
                  onClick={(e) => e.stopPropagation()}
                  onBlur={(e) => commitName(loop, e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur()
                  }}
                />
                <input
                  key={`start:${loop.id}:${loop.start_frames}`}
                  className="loop-boundary"
                  type="number"
                  step="0.001"
                  min="0"
                  defaultValue={secondsOf(loop.start_frames, sampleRate)}
                  aria-label="Loop start (seconds)"
                  title="Loop start in seconds"
                  onClick={(e) => e.stopPropagation()}
                  onBlur={(e) => {
                    if (!commitBoundary(loop, 'start', e.currentTarget.value)) {
                      e.currentTarget.value = secondsOf(loop.start_frames, sampleRate)
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur()
                  }}
                />
                <span className="loop-dash">–</span>
                <input
                  key={`end:${loop.id}:${loop.end_frames}`}
                  className="loop-boundary"
                  type="number"
                  step="0.001"
                  min="0"
                  defaultValue={secondsOf(loop.end_frames, sampleRate)}
                  aria-label="Loop end (seconds)"
                  title="Loop end in seconds"
                  onClick={(e) => e.stopPropagation()}
                  onBlur={(e) => {
                    if (!commitBoundary(loop, 'end', e.currentTarget.value)) {
                      e.currentTarget.value = secondsOf(loop.end_frames, sampleRate)
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur()
                  }}
                />
                <span className="loop-duration" title="Loop duration">
                  {sampleRate > 0 ? formatTime(length, sampleRate) : `${length} fr`}
                </span>
                <span className="loop-frames" title="Exact source frames">
                  {loop.start_frames}–{loop.end_frames}
                </span>
                {tooShort && loop.id === activeLoopId && (
                  <span className="loop-too-short" role="status">
                    Shorter than 100 ms — cannot repeat
                  </span>
                )}
                <label className="loop-field" onClick={(e) => e.stopPropagation()}>
                  <span className="loop-field-label">Rep</span>
                  <input
                    key={`repeat:${loop.id}:${loop.repeat_count ?? 'inf'}`}
                    className="loop-repeat"
                    type="number"
                    min="1"
                    max={MAX_LOOP_REPEAT}
                    step="1"
                    placeholder="∞"
                    defaultValue={loop.repeat_count ?? ''}
                    aria-label="Repeat count"
                    title="Total passes; blank = infinite"
                    onBlur={(e) => {
                      if (!commitRepeat(loop, e.currentTarget.value)) {
                        e.currentTarget.value =
                          loop.repeat_count == null ? '' : String(loop.repeat_count)
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                    }}
                  />
                </label>
                <label className="loop-fade" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={loop.boundary_fade}
                    aria-label="Boundary fade"
                    title="5 ms fades at the loop join (off = exact boundary audition)"
                    onChange={(e) => onUpdate(loop.id, { boundary_fade: e.target.checked })}
                  />
                  Fade
                </label>
                <button
                  type="button"
                  className="loop-duplicate"
                  aria-label={`Duplicate loop ${loop.name}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onDuplicate(loop.id)
                  }}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="loop-delete"
                  aria-label={`Delete loop ${loop.name}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(loop.id)
                  }}
                >
                  Delete
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
