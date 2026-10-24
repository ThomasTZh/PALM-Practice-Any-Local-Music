import { describe, expect, it } from 'vitest'

import { MetronomeClickMixer } from '../src/playback/worklet-processor.js'

function channels(frames: number): Float32Array[] {
  return [new Float32Array(frames), new Float32Array(frames)]
}

describe('worklet metronome click mixer (M3.14 §16.3)', () => {
  it('renders a scheduled click at its render frame', () => {
    const mixer = new MetronomeClickMixer(48_000, 0.5)
    const output = channels(512)
    mixer.scheduleClicks([{ frame: 10, strength: 'downbeat' }], 0.5)
    mixer.render(output, 0, 512)
    expect(output[0][9]).toBe(0)
    expect(Math.abs(output[0][11])).toBeGreaterThan(0)
    expect(output[0][60]).not.toBe(0)
    expect(output[1][10]).toBe(output[0][10])
  })

  it('respects volume and silence when zero', () => {
    const mixer = new MetronomeClickMixer(48_000, 0)
    const output = channels(128)
    mixer.scheduleClicks([{ frame: 0, strength: 'beat' }], 0)
    mixer.render(output, 0, 128)
    expect(output[0].every((value) => value === 0)).toBe(true)
  })

  it('carries a click across block boundaries and skips stale frames', () => {
    const mixer = new MetronomeClickMixer(48_000, 0.5)
    const first = channels(256)
    mixer.scheduleClicks([{ frame: 500, strength: 'beat' }], 0.5)
    mixer.render(first, 0, 256)
    expect(first[0].every((value) => value === 0)).toBe(true)
    const second = channels(256)
    mixer.render(second, 256, 256)
    expect(Math.abs(second[0][245])).toBeGreaterThan(0)

    const stale = channels(64)
    mixer.scheduleClicks([{ frame: 5, strength: 'beat' }], 0.5)
    mixer.render(stale, 100, 64)
    expect(stale[0].every((value) => value === 0)).toBe(true)
  })
})
