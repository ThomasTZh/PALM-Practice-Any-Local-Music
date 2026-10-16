import { describe, expect, it } from 'vitest'
import type { PracticeState } from '../src/api/commands'
import {
  DEFAULT_TRACK_COLOR,
  defaultSettingsFor,
  effectiveTracks,
  ROLE_PALETTE,
  type TrackSettings,
} from '../src/projects/trackSettings'

function practiceState(tracks: Record<string, TrackSettings> = {}): PracticeState {
  return {
    loop_enabled: false,
    master_gain: 1.0,
    monitoring_limiter: true,
    playback_mode: 'original',
    playback_speed: 1.0,
    tracks,
  }
}

describe('defaultSettingsFor', () => {
  it('uses the role palette color and neutral mixer defaults', () => {
    expect(defaultSettingsFor('bass')).toEqual({
      gain: 1.0,
      mute: false,
      solo: false,
      balance: 0.0,
      visible: true,
      display_height: 1.0,
      color: ROLE_PALETTE['bass'],
    })
  })

  it('falls back to the default color for unknown roles', () => {
    expect(defaultSettingsFor('guitar').color).toBe(DEFAULT_TRACK_COLOR)
  })
})

describe('effectiveTracks', () => {
  it('returns display defaults when there is no practice state', () => {
    const tracks = effectiveTracks(null, ['bass', 'other'])
    expect(tracks.map((t) => t.role)).toEqual(['bass', 'other'])
    expect(tracks[0].settings.color).toBe(ROLE_PALETTE['bass'])
    expect(tracks[1].settings.color).toBe(ROLE_PALETTE['other'])
  })

  it('lets stored settings win over the defaults', () => {
    const state = practiceState({
      bass: { ...defaultSettingsFor('bass'), gain: 0.5, mute: true, color: '#112233' },
    })
    const tracks = effectiveTracks(state, ['bass', 'other'])
    expect(tracks[0].settings.gain).toBe(0.5)
    expect(tracks[0].settings.mute).toBe(true)
    expect(tracks[0].settings.color).toBe('#112233')
    // The unstored role keeps its display defaults.
    expect(tracks[1].settings.gain).toBe(1.0)
    expect(tracks[1].settings.mute).toBe(false)
  })

  it('returns one entry per requested role', () => {
    const roles = ['vocals', 'drums', 'bass', 'other', 'others']
    expect(effectiveTracks(practiceState(), roles)).toHaveLength(roles.length)
  })
})
