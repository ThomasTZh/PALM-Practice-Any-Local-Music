/**
 * M2.12 §14.1.4 pinned-loop cache: retention across partial passes,
 * readiness, clipping, serve copies, and the shared-ring write
 * contract.
 */

import { describe, expect, it } from 'vitest'
import { LoopPin, PINNED_BYTES_MAX } from '../src/playback/loop-pin'
import { viewSharedRing } from '../src/playback/pcm-fetch'

/** Two channels of deterministic samples representing frames `base…`. */
function channels(frames: number, base: number): Float32Array[] {
  return [
    Float32Array.from({ length: frames }, (_, i) => base + i),
    Float32Array.from({ length: frames }, (_, i) => -base - i),
  ]
}

describe('LoopPin', () => {
  it('exposes the group-wide byte budget constant', () => {
    expect(PINNED_BYTES_MAX).toBe(64 * 1024 * 1024)
  })

  it('rejects invalid ranges and channel counts', () => {
    expect(() => new LoopPin({ startFrame: 5, endFrame: 5, channelCounts: [2] })).toThrow(
      RangeError,
    )
    expect(() => new LoopPin({ startFrame: 0, endFrame: 5, channelCounts: [] })).toThrow(RangeError)
    expect(() => new LoopPin({ startFrame: 0, endFrame: 5, channelCounts: [0] })).toThrow(
      RangeError,
    )
  })

  it('retains partial passes, ignores duplicates and outside chunks, then is ready', () => {
    const pin = new LoopPin({ startFrame: 100, endFrame: 110, channelCounts: [2] })
    expect(pin.frames).toBe(10)
    expect(pin.bytes).toBe(10 * 2 * 4)
    expect(pin.ready).toBe(false)
    expect(pin.covers(100, 10)).toBe(true)
    expect(pin.covers(99, 5)).toBe(false)
    expect(pin.covers(105, 6)).toBe(false)

    // A chunk outside the pin retains nothing.
    expect(pin.retain(0, 0, channels(5, 1000))).toBe(0)
    // A partial pass from the middle to the loop end.
    const tail = channels(6, 105)
    expect(pin.retain(0, 105, tail)).toBe(5)
    expect(pin.ready).toBe(false)
    expect(pin.wantsChunk(0, 100, 5)).toBe(true)
    // Re-fetching the same frames retains nothing new.
    expect(pin.retain(0, 105, tail)).toBe(0)
    // The head completes the pin.
    expect(pin.retain(0, 100, channels(5, 100))).toBe(5)
    expect(pin.ready).toBe(true)
    expect(pin.wantsChunk(0, 100, 10)).toBe(false)

    // Served frames match what was retained, without touching the pin.
    const served = pin.copyChannels(0, 104, 3)
    expect(Array.from(served[0])).toEqual([104, 105, 106])
    expect(Array.from(served[1])).toEqual([-104, -105, -106])
    served[0][0] = 9999
    expect(pin.copyChannels(0, 104, 1)[0][0]).toBe(104)
    expect(() => pin.copyChannels(0, 105, 10)).toThrow(RangeError)
  })

  it('clips retained chunks at the loop boundaries', () => {
    const pin = new LoopPin({ startFrame: 10, endFrame: 20, channelCounts: [1] })
    // Frames 5..15: only 10..15 fall inside.
    expect(pin.retain(0, 5, channels(10, 100))).toBe(5)
    expect(pin.ready).toBe(false)
    // Frames 18..28: only 18..20 fall inside.
    expect(pin.retain(0, 18, channels(10, 200))).toBe(2)
    expect(pin.ready).toBe(false)
    // Frames 15..18 complete the pin.
    expect(pin.retain(0, 15, channels(3, 300))).toBe(3)
    expect(pin.ready).toBe(true)
  })

  it('reports multiple sources and needs every one before ready', () => {
    const pin = new LoopPin({ startFrame: 0, endFrame: 4, channelCounts: [2, 1] })
    expect(pin.retain(0, 0, channels(4, 0))).toBe(4)
    expect(pin.ready).toBe(false)
    expect(pin.retain(1, 0, channels(4, 0))).toBe(4)
    expect(pin.ready).toBe(true)
    expect(pin.bytes).toBe(4 * (2 + 1) * 4)
  })

  it('writes served frames into a shared ring, wrap-aware, 0 when full', () => {
    const pin = new LoopPin({ startFrame: 0, endFrame: 4, channelCounts: [2] })
    pin.retain(0, 0, channels(4, 1))
    expect(pin.ready).toBe(true)
    const ring = viewSharedRing(new SharedArrayBuffer(16 + 4 * 2 * 4), 2)
    expect(pin.writeShared(ring, 0, 0, 4)).toBe(4)
    const interleaved = new Float32Array(ring.data.buffer, 16, 8)
    expect(Array.from(interleaved)).toEqual([1, -1, 2, -2, 3, -3, 4, -4])
    // The ring holds exactly one serve: the next write is flow-controlled.
    expect(pin.writeShared(ring, 0, 0, 4)).toBe(0)
    expect(() => pin.writeShared(ring, 0, 2, 4)).toThrow(RangeError)
  })
})
