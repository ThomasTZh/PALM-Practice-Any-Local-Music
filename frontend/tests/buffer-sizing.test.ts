/**
 * M2.12 (spec §14.1) group buffer sizing: duration cap, byte cap, and
 * the group minimum. The transport passes the result to the worklet and
 * sizes the shared rings from it, so this policy is one pure function.
 */

import { describe, expect, it } from 'vitest'
import { sourceBufferCapacityFrames } from '../src/playback/transport'

describe('sourceBufferCapacityFrames', () => {
  it('uses the 24 s duration cap at ordinary rates', () => {
    expect(sourceBufferCapacityFrames([{ sampleRate: 48_000, channelCount: 2 }])).toBe(1_152_000)
    expect(sourceBufferCapacityFrames([{ sampleRate: 44_100, channelCount: 1 }])).toBe(1_058_400)
  })

  it('clamps to the 32 MiB byte cap at extreme widths', () => {
    // 192 kHz 8-channel: 32 B/frame → 1 048 576 frames (≈5.5 s).
    expect(sourceBufferCapacityFrames([{ sampleRate: 192_000, channelCount: 8 }])).toBe(1_048_576)
  })

  it('takes the group minimum across sources', () => {
    const stereo = { sampleRate: 48_000, channelCount: 2 }
    const wide = { sampleRate: 48_000, channelCount: 8 }
    // 48 kHz 8-channel: the byte cap (1 048 576) is tighter than 24 s.
    expect(sourceBufferCapacityFrames([stereo, wide])).toBe(1_048_576)
  })

  it('returns zero for an empty group', () => {
    expect(sourceBufferCapacityFrames([])).toBe(0)
  })
})
