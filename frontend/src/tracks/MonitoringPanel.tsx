/**
 * Monitoring panel (M2.8, spec §10.6).
 *
 * Master output peak meter (dBFS), the master monitoring gain, and the
 * limiter toggle (default on; state always visible). Monitoring-only:
 * nothing here touches the stored samples.
 */
import { dbToGain, gainToDb, GAIN_DB_MAX, GAIN_DB_MIN, peakToDbFs } from './db'

export interface MonitoringPanelProps {
  /** Master output peak (linear), from the transport meters. */
  masterPeak: number | null
  /** Master monitoring gain (linear, spec §10.3.8). */
  masterGain: number
  limiterEnabled: boolean
  onMasterGain: (linear: number) => void
  onLimiter: (enabled: boolean) => void
}

export function MonitoringPanel({
  masterPeak,
  masterGain,
  limiterEnabled,
  onMasterGain,
  onLimiter,
}: MonitoringPanelProps) {
  const gainDb = gainToDb(masterGain)
  const peakDb = peakToDbFs(masterPeak)
  const meterPct = peakDb == null ? 0 : Math.max(0, Math.min(100, ((peakDb + 60) / 60) * 100))

  return (
    <div className="monitoring-panel" role="group" aria-label="Monitoring">
      <div
        className="monitoring-master-peak"
        aria-label={`Master peak: ${peakDb == null ? 'silent' : `${peakDb.toFixed(1)} dBFS`}`}
      >
        <span className="monitoring-label">Out</span>
        <div className="mixer-peak-bar">
          <div className="mixer-peak-fill" style={{ width: `${meterPct}%` }} />
        </div>
        <span className="monitoring-peak-db">{peakDb == null ? '−∞' : peakDb.toFixed(1)}</span>
      </div>
      <label className="mixer-field">
        <span className="mixer-field-label">Master</span>
        <input
          type="range"
          className="monitoring-master-gain"
          min={GAIN_DB_MIN}
          max={GAIN_DB_MAX}
          step={0.5}
          value={gainDb}
          aria-label="Master gain"
          onChange={(e) => onMasterGain(dbToGain(Number(e.target.value)))}
        />
        <span className="mixer-field-value">{gainDb.toFixed(1)} dB</span>
      </label>
      <label className="mixer-field mixer-field-inline">
        <input
          type="checkbox"
          className="monitoring-limiter"
          checked={limiterEnabled}
          aria-label="Limiter"
          onChange={(e) => onLimiter(e.target.checked)}
        />
        <span>Limiter</span>
      </label>
    </div>
  )
}
