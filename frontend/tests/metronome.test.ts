import { describe, expect, it } from 'vitest'

import { mapClicksToRender, repeatLoopClicks, type ScheduledClick } from '../src/music/metronome'

const clicks: ScheduledClick[] = [
  { source_frame: 0, strength: 'downbeat' },
  { source_frame: 24_000, strength: 'beat' },
  { source_frame: 48_000, strength: 'beat' },
]

describe('metronome render scheduling (M3.14)', () => {
  it('maps source clicks to output frames at a rate', () => {
    expect(mapClicksToRender(clicks, 0, 0, 1).map((c) => c.renderFrame)).toEqual([
      0, 24_000, 48_000,
    ])
    expect(mapClicksToRender(clicks, 0, 0, 0.5).map((c) => c.renderFrame)).toEqual([
      0, 48_000, 96_000,
    ])
    expect(mapClicksToRender(clicks, 24_000, 100, 1).map((c) => c.renderFrame)).toEqual([
      100, 24_100,
    ])
  })

  it('repeats loop clicks with exact per-pass bases', () => {
    const loopClicks = [
      { source_frame: 0, strength: 'downbeat' as const },
      { source_frame: 12_000, strength: 'beat' as const },
    ]
    const rendered = repeatLoopClicks(loopClicks, 0, 24_000, 0, 3)
    const first = rendered.filter((c) => c.loopIteration === 1)
    const second = rendered.filter((c) => c.loopIteration === 2)
    expect(second.map((c) => c.renderFrame)).toEqual(first.map((c) => c.renderFrame + 24_000))
    expect(rendered.every((c) => c.sourceFrame < 24_000)).toBe(true)
  })

  it('rejects invalid rates and loop spans', () => {
    expect(() => mapClicksToRender(clicks, 0, 0, 0)).toThrow()
    expect(() => repeatLoopClicks(clicks, 10, 10, 0, 2)).toThrow()
  })
})
