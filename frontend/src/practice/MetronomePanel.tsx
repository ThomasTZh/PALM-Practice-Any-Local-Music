/** Metronome settings panel (M3.14 §16.11). Presentational; edits are
 * reported as one project command through the caller. */

export interface MetronomePatch {
  enabled?: boolean
  volume?: number
  accent_downbeats?: boolean
  subdivision?: 'primary' | 'denominator' | 'half_beat' | 'quarter_beat'
}

export interface MetronomePanelProps {
  enabled: boolean
  volume: number
  accentDownbeats: boolean
  subdivision: MetronomePatch['subdivision']
  onChange: (patch: MetronomePatch) => void
}

export function MetronomePanel({
  enabled,
  volume,
  accentDownbeats,
  subdivision,
  onChange,
}: MetronomePanelProps) {
  return (
    <section className="metronome-panel" aria-label="Metronome settings">
      <label className="metronome-enable">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
        />
        Metronome
      </label>
      <label className="metronome-volume">
        Volume
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          aria-label="Metronome volume"
          onChange={(event) => onChange({ volume: Number(event.target.value) })}
        />
      </label>
      <label className="metronome-subdivision">
        Clicks
        <select
          value={subdivision ?? 'primary'}
          aria-label="Metronome subdivision"
          onChange={(event) =>
            onChange({
              subdivision: event.target.value as NonNullable<MetronomePatch['subdivision']>,
            })
          }
        >
          <option value="primary">Primary beats</option>
          <option value="denominator">Denominator units</option>
          <option value="half_beat">Half beats</option>
          <option value="quarter_beat">Quarter beats</option>
        </select>
      </label>
      <label className="metronome-accent">
        <input
          type="checkbox"
          checked={accentDownbeats}
          onChange={(event) => onChange({ accent_downbeats: event.target.checked })}
        />
        Accent downbeats
      </label>
    </section>
  )
}
