/** Count-in settings (M3.15 §17.1). Presentational; caller sends one command. */

export interface CountInPatch {
  mode?: 'off' | 'one_bar' | 'two_bars'
  repetition?: 'once' | 'every_repeat'
}

export interface CountInPanelProps {
  mode: 'off' | 'one_bar' | 'two_bars'
  repetition: 'once' | 'every_repeat'
  onChange: (patch: CountInPatch) => void
}

export function CountInPanel({ mode, repetition, onChange }: CountInPanelProps) {
  return (
    <section className="count-in-panel" aria-label="Count-in settings">
      <label>
        Count-in
        <select
          value={mode}
          aria-label="Count-in length"
          onChange={(event) => onChange({ mode: event.target.value as CountInPatch['mode'] })}
        >
          <option value="off">Off</option>
          <option value="one_bar">One bar</option>
          <option value="two_bars">Two bars</option>
        </select>
      </label>
      <label>
        Repeats
        <select
          value={repetition}
          aria-label="Count-in repetition"
          onChange={(event) =>
            onChange({
              repetition: event.target.value as CountInPatch['repetition'],
            })
          }
        >
          <option value="once">Once at start</option>
          <option value="every_repeat">Before every loop</option>
        </select>
      </label>
    </section>
  )
}
