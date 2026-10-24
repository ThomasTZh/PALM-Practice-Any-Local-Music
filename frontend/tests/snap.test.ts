import { describe, expect, it } from 'vitest'

import { effectiveSnapMode, radiusFrames, snapModeKinds, snapToCandidates } from '../src/music/snap'

describe('musical snapping geometry (M3.12)', () => {
  it('converts the CSS radius through the viewport scale', () => {
    expect(radiusFrames(100)).toBe(800)
    expect(radiusFrames(10)).toBe(80)
    expect(radiusFrames(0)).toBe(0)
  })

  it('snaps to the nearest candidate inside the radius and otherwise preserves position', () => {
    const candidates = [
      { frame: 2500, label: 'beat' },
      { frame: 5000, label: 'event' },
    ]
    const near = snapToCandidates(2400, candidates, 100)
    expect(near.snapped).toBe(true)
    expect(near.snappedFrame).toBe(2500)
    expect(near.label).toBe('beat')
    const far = snapToCandidates(2400, candidates, 10)
    expect(far.snapped).toBe(false)
    expect(far.snappedFrame).toBe(2400)
  })

  it('temporarily inverts snapping with the drag modifier', () => {
    expect(effectiveSnapMode('beat', true, 'beat')).toBe('off')
    expect(effectiveSnapMode('off', true, 'bar')).toBe('bar')
    expect(effectiveSnapMode('bar', false, 'beat')).toBe('bar')
  })

  it('lists eligible grid kinds per mode', () => {
    expect(snapModeKinds('beat')).toEqual(['primary'])
    expect(snapModeKinds('quarter_beat')).toContain('quarter_beat')
    expect(snapModeKinds('event')).toEqual([])
  })
})
