/**
 * Per-track mixer strip (M2.8, spec §10.2–§10.3).
 *
 * Mute / solo / gain / balance / visibility / color / height for one
 * stem. Values are stored linear (gain) and normalized (balance); the
 * strip works in dB and −1…1 and patches through `set_track_settings`.
 * Solo semantics live in the worklet, not here (spec §10.4).
 */
import type { TrackSettings } from '../projects/trackSettings'
import { balanceLabel, dbToGain, gainToDb, GAIN_DB_MAX, GAIN_DB_MIN, peakToDbFs } from './db'

export interface TrackSettingsPatch {
  gain?: number
  balance?: number
  mute?: boolean
  solo?: boolean
  visible?: boolean
  display_height?: number
  color?: string
}

export interface MixerStripProps {
  /** Track label (the stem's `display_name`), for control labels. */
  label: string
  /** Effective settings (stored or display defaults). */
  settings: TrackSettings
  /** This track's last peak (linear, from the transport meters). */
  peak?: number | null
  /** Patch one or more settings (sends `set_track_settings`). */
  onPatch: (patch: TrackSettingsPatch) => void
}

export function MixerStrip({ label, settings, peak, onPatch }: MixerStripProps) {
  const gainDb = gainToDb(settings.gain)
  const peakDb = peakToDbFs(peak)
  const meterPct = peakDb == null ? 0 : Math.max(0, Math.min(100, ((peakDb + 60) / 60) * 100))

  return (
    <div className="mixer-strip" role="group" aria-label={`${label} mixer`}>
      <div className="mixer-buttons">
        <button
          type="button"
          className={settings.mute ? 'mixer-btn active' : 'mixer-btn'}
          aria-pressed={settings.mute}
          aria-label={`Mute ${label}`}
          onClick={() => onPatch({ mute: !settings.mute })}
        >
          M
        </button>
        <button
          type="button"
          className={settings.solo ? 'mixer-btn active' : 'mixer-btn'}
          aria-pressed={settings.solo}
          aria-label={`Solo ${label}`}
          onClick={() => onPatch({ solo: !settings.solo })}
        >
          S
        </button>
      </div>

      <div
        className="mixer-peak"
        aria-label={`${label} peak: ${peakDb == null ? 'silent' : `${peakDb.toFixed(1)} dBFS`}`}
      >
        <div className="mixer-peak-bar">
          <div className="mixer-peak-fill" style={{ width: `${meterPct}%` }} />
        </div>
        <span className="mixer-peak-db">{peakDb == null ? '−∞' : peakDb.toFixed(1)}</span>
      </div>

      <label className="mixer-field">
        <span className="mixer-field-label">Gain</span>
        <input
          type="range"
          className="mixer-gain"
          min={GAIN_DB_MIN}
          max={GAIN_DB_MAX}
          step={0.5}
          value={gainDb}
          aria-label={`${label} gain`}
          onChange={(e) => onPatch({ gain: dbToGain(Number(e.target.value)) })}
        />
        <span className="mixer-field-value">{gainDb.toFixed(1)} dB</span>
      </label>

      <label className="mixer-field">
        <span className="mixer-field-label">Balance</span>
        <input
          type="range"
          className="mixer-balance"
          min={-1}
          max={1}
          step={0.05}
          value={settings.balance}
          aria-label={`${label} balance`}
          onChange={(e) => onPatch({ balance: Number(e.target.value) })}
        />
        <span className="mixer-field-value">{balanceLabel(settings.balance)}</span>
      </label>

      <label className="mixer-field mixer-field-inline">
        <input
          type="checkbox"
          className="mixer-visible"
          checked={settings.visible}
          aria-label={`Show ${label} waveform`}
          onChange={(e) => onPatch({ visible: e.target.checked })}
        />
        <span>Wave</span>
      </label>

      <label className="mixer-field mixer-field-inline">
        <input
          type="color"
          className="mixer-color"
          value={settings.color}
          aria-label={`${label} color`}
          onChange={(e) => onPatch({ color: e.target.value })}
        />
      </label>

      <label className="mixer-field">
        <span className="mixer-field-label">Height</span>
        <input
          type="range"
          className="mixer-height"
          min={0.25}
          max={2}
          step={0.05}
          value={settings.display_height}
          aria-label={`${label} height`}
          onChange={(e) => onPatch({ display_height: Number(e.target.value) })}
        />
        <span className="mixer-field-value">{settings.display_height.toFixed(2)}×</span>
      </label>
    </div>
  )
}
