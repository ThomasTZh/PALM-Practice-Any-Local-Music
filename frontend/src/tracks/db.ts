/**
 * Mixer gain/balance display math (M2.8, spec §10.3).
 *
 * Stored values are linear amplitude; the UI works in dB. `10^(dB/20)`
 * maps the two (spec §10.3.1). The slider spans −60…+12 dB; −60 dB
 * (≈0.001) is the practical floor — exact silence is `mute`, not gain.
 */

export const GAIN_DB_MIN = -60
export const GAIN_DB_MAX = 12

/** Linear gain → dB, clamped to the slider range (0 → the floor). */
export function gainToDb(gain: number): number {
  if (!Number.isFinite(gain) || gain <= 0) return GAIN_DB_MIN
  return Math.max(GAIN_DB_MIN, Math.min(GAIN_DB_MAX, 20 * Math.log10(gain)))
}

/** dB → linear gain (spec §10.3.1). */
export function dbToGain(db: number): number {
  return 10 ** (db / 20)
}

/** A linear peak (0…~1+) to a dBFS reading for a meter (null-safe). */
export function peakToDbFs(peak: number | null | undefined): number | null {
  if (peak == null || !Number.isFinite(peak) || peak <= 0) return null
  return 20 * Math.log10(peak)
}

/** A balance value (−1…1) to a short L/C/R label. */
export function balanceLabel(balance: number): string {
  if (balance <= -0.95) return 'L'
  if (balance >= 0.95) return 'R'
  if (balance < 0) return `L${Math.round(-balance * 100)}`
  if (balance > 0) return `R${Math.round(balance * 100)}`
  return 'C'
}
