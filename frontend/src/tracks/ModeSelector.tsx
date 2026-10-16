/**
 * Playback-mode selector (M2.8, spec §10.4.5–6).
 *
 * Original / Bass pair / Four stems. The original group and the stem
 * groups are mutually exclusive: a stem mode needs an active result
 * set, and choosing one without a set is a notice prompting selection
 * (the server 409 is the backstop). The set dropdown lists the
 * project's result sets; only `valid` ones are selectable.
 */
import type { components } from '../api/schema'
import type { ResultSetSummary } from '../api/result-sets'

export type PlaybackMode = components['schemas']['PlaybackMode']

export interface ModeSelectorProps {
  mode: PlaybackMode
  /** The project's result sets (null while loading). */
  sets: ResultSetSummary[] | null
  activeSetId: string | null
  onMode: (mode: PlaybackMode) => void
  onSelectSet: (resultSetId: string) => void
  /** One-line notice (e.g. the no-set prompt). */
  notice: string | null
}

export function ModeSelector({
  mode,
  sets,
  activeSetId,
  onMode,
  onSelectSet,
  notice,
}: ModeSelectorProps) {
  return (
    <div className="mode-selector" role="group" aria-label="Playback mode">
      <button
        type="button"
        className={mode === 'original' ? 'mode-btn active' : 'mode-btn'}
        aria-pressed={mode === 'original'}
        onClick={() => onMode('original')}
      >
        Original
      </button>
      <button
        type="button"
        className={mode === 'bass_pair' ? 'mode-btn active' : 'mode-btn'}
        aria-pressed={mode === 'bass_pair'}
        onClick={() => onMode('bass_pair')}
      >
        Bass pair
      </button>
      <button
        type="button"
        className={mode === 'four_stems' ? 'mode-btn active' : 'mode-btn'}
        aria-pressed={mode === 'four_stems'}
        onClick={() => onMode('four_stems')}
      >
        Four stems
      </button>
      <select
        className="mode-set-select"
        aria-label="Result set"
        value={activeSetId ?? ''}
        onChange={(e) => {
          if (e.target.value) onSelectSet(e.target.value)
        }}
      >
        <option value="" disabled>
          Select a result set…
        </option>
        {(sets ?? []).map((s) => (
          <option key={s.id} value={s.id} disabled={s.validationStatus !== 'valid'}>
            {s.validationStatus === 'valid' ? 'Valid' : s.validationStatus} ·{' '}
            {s.createdAt.slice(0, 10)}
          </option>
        ))}
      </select>
      {notice && (
        <p className="mode-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  )
}
