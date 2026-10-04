/**
 * Unit tests for the AudioWorklet consumption core (M1.12, plan §5,
 * items 1–8). `worklet-processor.js` is imported directly as an ES
 * module; the `registerProcessor` call inside it is guarded by a
 * `typeof AudioWorkletProcessor` check, so loading it on the main
 * thread (jsdom) is safe.
 */

import { describe, expect, it } from 'vitest'
import { ConsumptionState } from '../src/playback/worklet-processor.js'

const RATE = 48_000
const CH = 2

/** Interleaved f32le buffer with `value(f, c)` per sample. */
function makeBuffer(frames: number, value: (f: number, c: number) => number): ArrayBuffer {
  const bytes = new ArrayBuffer(frames * CH * 4)
  const view = new DataView(bytes)
  for (let f = 0; f < frames; f++) {
    for (let c = 0; c < CH; c++) {
      view.setFloat32((f * CH + c) * 4, value(f, c), true)
    }
  }
  return bytes
}

function freshCore(
  frameCount = 48_000,
  opts: { rate?: number; ch?: number; anchorEvery?: number } = {},
): ConsumptionState {
  const rate = opts.rate ?? RATE
  const ch = opts.ch ?? CH
  return new ConsumptionState({
    sampleRate: rate,
    channelCount: ch,
    frameCount,
    ...(opts.anchorEvery !== undefined ? { anchorEveryFrames: opts.anchorEvery } : {}),
  })
}

function block(core: ConsumptionState, time: number, frames: number, ch = CH) {
  const output: Float32Array[] = []
  for (let c = 0; c < ch; c++) output.push(new Float32Array(frames))
  const res = core.process(time, output)
  return { output, res }
}

describe('ConsumptionState block handling', () => {
  it('fills the actual output-block length (128, 192, 186 frames)', () => {
    const core = freshCore()
    core.enqueue(makeBuffer(48_000, (f) => f * 0.001))
    let t = 0
    for (const frames of [128, 192, 186]) {
      const { output, res } = block(core, t, frames)
      expect(res.consumed).toBe(frames)
      for (let i = 0; i < frames; i++) {
        expect(output[0][i]).toBeCloseTo((i + core.position - frames) * 0.001, 5)
        expect(output[1][i]).toBeCloseTo((i + core.position - frames) * 0.001, 5)
      }
      t += frames / RATE
    }
    expect(core.position).toBe(128 + 192 + 186)
  })

  it('emits enqueued samples in order across blocks, per channel', () => {
    const core = freshCore()
    core.enqueue(makeBuffer(300, (f, c) => (f + c * 1000) * 0.001))
    const first = block(core, 0, 128)
    expect(first.output[0][0]).toBeCloseTo(0, 5)
    expect(first.output[1][0]).toBeCloseTo(1, 5)
    const second = block(core, 128 / RATE, 128)
    expect(second.output[0][0]).toBeCloseTo(0.128, 5)
    expect(second.output[1][127]).toBeCloseTo(1.255, 5)
    expect(core.position).toBe(256)
  })
})

describe('ConsumptionState underrun', () => {
  it('reports silence without an underrun while flushing (fresh or post-seek)', () => {
    const core = freshCore()
    expect(block(core, 0, 128).res.underrun).toBe(false)
    core.seek(0)
    expect(block(core, 0, 128).res.underrun).toBe(false)
  })

  it('reports one underrun when the buffer empties mid-stream, then stays quiet', () => {
    const core = freshCore()
    core.enqueue(makeBuffer(100, () => 0.5))
    const partial = block(core, 0, 128)
    expect(partial.res.consumed).toBe(100)
    expect(partial.res.underrun).toBe(true)
    expect(partial.output[0][100]).toBe(0)
    expect(partial.output[0][127]).toBe(0)
    // The next empty block must not re-report the same underrun.
    expect(block(core, 128 / RATE, 128).res.underrun).toBe(false)
  })
})

describe('ConsumptionState pause and resume', () => {
  it('ramps to silence over ~5 ms, preserves the position, and resumes exactly', () => {
    const core = freshCore()
    core.enqueue(makeBuffer(48_000, (f) => f * 0.001))
    block(core, 0, 128) // consume a block so the ramp has a level to hold
    const held = core.position
    expect(held).toBe(128)

    core.pause()
    const ramp1 = block(core, held / RATE, 128)
    // First ramp block: full level (240/240), the last consumed sample
    // (frame 127 of the f * 0.001 pattern).
    expect(ramp1.output[0][0]).toBeCloseTo(0.127, 5)
    expect(ramp1.res.consumed).toBe(0)
    const ramp2 = block(core, (held + 128) / RATE, 128)
    // Second ramp block: reduced level (112/240).
    expect(ramp2.output[0][0]).toBeCloseTo(0.127 * (112 / 240), 5)
    expect(ramp2.output[0][0]).toBeLessThan(ramp1.output[0][0])
    const ramp3 = block(core, (held + 256) / RATE, 128)
    expect(ramp3.output[0][0]).toBe(0)
    expect(core.position).toBe(held)

    core.resume()
    const after = block(core, (held + 384) / RATE, 128)
    expect(after.res.consumed).toBe(128)
    // Exact continuation: no sample skipped or repeated.
    expect(after.output[0][0]).toBeCloseTo(held * 0.001, 5)
    expect(after.output[1][127]).toBeCloseTo((held + 127) * 0.001, 5)
  })
})

describe('ConsumptionState seek', () => {
  it('clears the ring: stale data is never output after a seek', () => {
    const core = freshCore()
    core.enqueue(makeBuffer(1000, () => 1.0))
    core.seek(5_000)
    const stale = block(core, 0, 128)
    expect(stale.output[0][0]).toBe(0)
    expect(stale.output[1][127]).toBe(0)
    expect(stale.res.underrun).toBe(false)

    core.enqueue(makeBuffer(128, () => 2.0))
    const fresh = block(core, 128 / RATE, 128)
    expect(fresh.output[0][0]).toBeCloseTo(2.0, 5)
    expect(core.position).toBe(5_128)
  })

  it('clamps the seek target to the source bounds', () => {
    const core = freshCore(1_000)
    core.seek(-50)
    expect(core.position).toBe(0)
    core.seek(99_999)
    expect(core.position).toBe(1_000)
    expect(core.ended).toBe(true)
  })
})

describe('ConsumptionState end of source', () => {
  it('ends exactly at the endpoint with a final anchor, then stays silent', () => {
    const core = freshCore(300)
    core.enqueue(makeBuffer(300, () => 0.25))
    block(core, 0, 128)
    block(core, 128 / RATE, 128)
    const last = block(core, 256 / RATE, 44)
    expect(last.res.ended).toBe(true)
    expect(last.res.anchor).toEqual({ frame: 300, time: 256 / RATE })
    expect(last.output[0][43]).toBeCloseTo(0.25, 5)
    expect(core.position).toBe(300)
    // No repeated end notification; pure silence afterwards.
    const after = block(core, 300 / RATE, 128)
    expect(after.res.ended).toBe(false)
    expect(after.res.anchor).toBeNull()
    expect(after.output[0][0]).toBe(0)
  })
})

describe('ConsumptionState anchors', () => {
  it('emits an anchor every anchorEveryFrames with the block-start position', () => {
    const core = freshCore(10_000) // default cadence: 480 frames
    core.enqueue(makeBuffer(1_000, () => 0.5))
    const a1 = block(core, 0, 480)
    expect(a1.res.anchor).toEqual({ frame: 0, time: 0 })
    const a2 = block(core, 480 / RATE, 480)
    expect(a2.res.anchor).toEqual({ frame: 480, time: 480 / RATE })
    const a3 = block(core, 960 / RATE, 40)
    expect(a3.res.anchor).toBeNull()
  })
})

describe('ConsumptionState bounds', () => {
  it('rejects enqueue that would overflow the bounded ring', () => {
    // 1 kHz => 8 s ring = 8 000 frames, cheap to exercise.
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    const half = new ArrayBuffer(4_000 * 1 * 4)
    expect(core.enqueue(half)).toBe(true)
    expect(core.enqueue(half)).toBe(true)
    expect(core.available).toBe(8_000)
    expect(core.enqueue(new ArrayBuffer(4 * 1 * 4))).toBe(false)
    expect(core.available).toBe(8_000)
  })

  it('rejects data beyond the valid endpoint', () => {
    const core = freshCore(100, { rate: 1_000, ch: 1 })
    core.seek(99)
    // Only one frame is valid left.
    const two = new ArrayBuffer(2 * 1 * 4)
    expect(core.enqueue(two)).toBe(true)
    expect(core.available).toBe(1)
    expect(core.enqueue(two)).toBe(false)
  })

  it('validates constructor arguments', () => {
    expect(() => new ConsumptionState({ sampleRate: 0, channelCount: 2, frameCount: 10 })).toThrow(
      RangeError,
    )
    expect(
      () => new ConsumptionState({ sampleRate: 48_000, channelCount: 0, frameCount: 10 }),
    ).toThrow(RangeError)
  })
})
