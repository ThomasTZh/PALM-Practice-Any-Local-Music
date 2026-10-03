import { describe, expect, it } from 'vitest'
import {
  clampToDuration,
  deinterleaveF32le,
  formatTime,
  framesFromBytes,
  projectPosition,
} from '../src/playback/pcm'

function f32le(samples: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 4)
  new Float32Array(buffer).set(samples)
  return buffer
}

describe('deinterleaveF32le', () => {
  it('splits interleaved stereo into per-channel arrays', () => {
    // 3 frames: (0.1, 0.2), (0.3, 0.4), (0.5, 0.6)
    const channels = deinterleaveF32le(f32le([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]), 2)
    expect(channels).toHaveLength(2)
    expect(channels[0]).toEqual(new Float32Array([0.1, 0.3, 0.5]))
    expect(channels[1]).toEqual(new Float32Array([0.2, 0.4, 0.6]))
  })

  it('handles mono', () => {
    const channels = deinterleaveF32le(f32le([1, 2, 3]), 1)
    expect(channels).toHaveLength(1)
    expect(channels[0]).toEqual(new Float32Array([1, 2, 3]))
  })

  it('drops a trailing partial frame', () => {
    // 2 channels, 5 samples = 2 full frames + 1 leftover
    const channels = deinterleaveF32le(f32le([1, 2, 3, 4, 5]), 2)
    expect(channels[0]).toEqual(new Float32Array([1, 3]))
    expect(channels[1]).toEqual(new Float32Array([2, 4]))
  })

  it('rejects a non-positive channel count', () => {
    expect(() => deinterleaveF32le(f32le([1]), 0)).toThrow(RangeError)
  })
})

describe('projectPosition', () => {
  it('maps frames between rates', () => {
    // 1 second at 48000 playback = 44100 project frames
    expect(projectPosition(48000, 44100, 48000)).toBe(44100)
  })

  it('truncates toward zero', () => {
    expect(projectPosition(1, 44100, 48000)).toBe(0)
    expect(projectPosition(47999, 44100, 48000)).toBe(44099)
  })

  it('is the identity at equal rates', () => {
    expect(projectPosition(12345, 48000, 48000)).toBe(12345)
  })

  it('rejects a non-positive playback rate', () => {
    expect(() => projectPosition(10, 44100, 0)).toThrow(RangeError)
  })
})

describe('clampToDuration', () => {
  it('clamps below, above, and within range', () => {
    expect(clampToDuration(-5, 1000)).toBe(0)
    expect(clampToDuration(1500, 1000)).toBe(1000)
    expect(clampToDuration(42, 1000)).toBe(42)
  })

  it('floors fractional frames', () => {
    expect(clampToDuration(999.9, 1000)).toBe(999)
  })
})

describe('formatTime', () => {
  it('formats m:ss.mmm', () => {
    expect(formatTime(0, 44100)).toBe('0:00.000')
    expect(formatTime(44100, 44100)).toBe('0:01.000')
    expect(formatTime(61 * 44100 + 12345, 44100)).toBe('1:01.280')
  })

  it('clamps negative input to zero', () => {
    expect(formatTime(-10, 44100)).toBe('0:00.000')
  })

  it('rejects a non-positive rate', () => {
    expect(() => formatTime(10, 0)).toThrow(RangeError)
  })
})

describe('framesFromBytes', () => {
  it('computes interleaved frame count', () => {
    // 2 channels: 4 samples = 2 frames
    expect(framesFromBytes(16, 2)).toBe(2)
    expect(framesFromBytes(100, 2)).toBe(12)
  })

  it('rejects a non-positive channel count', () => {
    expect(() => framesFromBytes(16, 0)).toThrow(RangeError)
  })
})
