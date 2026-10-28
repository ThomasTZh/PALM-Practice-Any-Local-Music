/**
 * Song Map section list and actions. All mutations are emitted to the
 * project command queue by App; this component owns no project state.
 */

import type { SongSection } from '../api/commands'

export interface SectionPanelProps {
  sections: SongSection[]
  sampleRate: number
  selection: { start: number; end: number } | null
  activeSectionId: string | null
  playheadFrame: number | null
  onAdd: () => void
  onUpdate: (sectionId: string, patch: Partial<Pick<SongSection, 'name' | 'color'>>) => void
  onDelete: (sectionId: string) => void
  onSplit: (sectionId: string, atFrame: number) => void
  onLoop: (sectionId: string) => void
  onSelect: (section: SongSection) => void
}

function seconds(frames: number, rate: number): string {
  return rate > 0 ? `${(frames / rate).toFixed(2)} s` : `${frames} fr`
}

export function SectionPanel({
  sections,
  sampleRate,
  selection,
  activeSectionId,
  playheadFrame,
  onAdd,
  onUpdate,
  onDelete,
  onSplit,
  onLoop,
  onSelect,
}: SectionPanelProps) {
  const active = sections.find((section) => section.id === activeSectionId) ?? null
  const splitFrame = playheadFrame ?? selection?.start ?? null
  return (
    <section className="section-panel" aria-label="Song sections">
      <h2>Song sections</h2>
      <div className="section-actions">
        <button type="button" onClick={onAdd} disabled={!selection}>
          Add section from selection
        </button>
        <button
          type="button"
          onClick={() => active && splitFrame !== null && onSplit(active.id, splitFrame)}
          disabled={!active || splitFrame === null}
        >
          Split at playhead
        </button>
      </div>
      {sections.length === 0 ? (
        <p className="muted">Select a range on the waveform to create the first section.</p>
      ) : (
        <ul className="section-list" aria-label="Section list">
          {sections.map((section) => (
            <li
              key={section.id}
              className={`section-item${section.id === activeSectionId ? ' selected' : ''}`}
            >
              <button
                type="button"
                className="section-select"
                onClick={() => onSelect(section)}
                aria-label={`Select section ${section.name}`}
              >
                {seconds(section.start_frames, sampleRate)} –{' '}
                {seconds(section.end_frames, sampleRate)}
              </button>
              <input
                className="section-name"
                aria-label="Section name"
                defaultValue={section.name}
                maxLength={80}
                onBlur={(event) => {
                  const name = event.currentTarget.value.trim()
                  if (name && name !== section.name) onUpdate(section.id, { name })
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') event.currentTarget.blur()
                }}
              />
              <input
                type="color"
                aria-label={`Section color ${section.name}`}
                value={section.color}
                onChange={(event) => onUpdate(section.id, { color: event.currentTarget.value })}
              />
              <button type="button" onClick={() => onLoop(section.id)}>
                Loop
              </button>
              <button type="button" onClick={() => onDelete(section.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
