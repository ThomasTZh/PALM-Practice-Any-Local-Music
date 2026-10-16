/**
 * Track settings accessor (M2.8, spec §10.2).
 *
 * Merges the per-role mixer settings stored in `practice_state.tracks`
 * with display defaults so the UI never has to handle missing entries.
 * The role palette is the *displayed* initial color: the domain is
 * palette-agnostic (the server default is `#8fa3bf`).
 */

import type { PracticeState } from '../api/commands'
import type { components } from '../api/schema'

export type TrackSettings = components['schemas']['TrackSettings']

/** Displayed initial color per stem role (spec §10.2). */
export const ROLE_PALETTE: Record<string, string> = {
  vocals: '#e11d48',
  drums: '#f59e0b',
  bass: '#2563eb',
  other: '#8b5cf6',
  others: '#0d9488',
}

export const DEFAULT_TRACK_COLOR = '#8fa3bf'

export interface EffectiveTrack {
  role: string
  settings: TrackSettings
}

/** Per-role display defaults: palette color, 0 dB, center, visible, height 1. */
export function defaultSettingsFor(role: string): TrackSettings {
  return {
    gain: 1.0,
    mute: false,
    solo: false,
    balance: 0.0,
    visible: true,
    display_height: 1.0,
    color: ROLE_PALETTE[role] ?? DEFAULT_TRACK_COLOR,
  }
}

/**
 * Effective mixer settings for the given stem roles: stored entries win;
 * missing roles get the display defaults.
 */
export function effectiveTracks(
  practiceState: PracticeState | null,
  roles: string[],
): EffectiveTrack[] {
  const stored = practiceState?.tracks ?? {}
  return roles.map((role) => ({
    role,
    settings: stored[role] ?? defaultSettingsFor(role),
  }))
}
