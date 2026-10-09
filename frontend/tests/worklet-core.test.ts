/**
 * Unit tests for the AudioWorklet consumption core (M1.12/M1.13, plan §8,
 * items 3–7). `worklet-processor.js` is imported directly as an ES
 * module; the `registerProcessor` call inside it is guarded by a
 * `typeof AudioWorkletProcessor` check, so loading it on the main
 * thread (jsdom) is safe. Node provides `SharedArrayBuffer`, so the
 * shared path is exercised with real SABs.
 */

import { describe, expect, it } from 'vitest'
import {
  acknowledgeSharedFlush,
  createSharedRing,
  writeSharedRing,
  type SharedRing,
} from '../src/playback/pcm-fetch'
import { ConsumptionState } from '../src/playback/worklet-processor.js'

const RATE = 48_000
const CH = 2

/** Interleaved f32le buffer with `value(f, c)` per sample. */
function makeBuffer(frames: number, value: (f: number, c: number) => number, ch = CH): ArrayBuffer {
  const bytes = new ArrayBuffer(frames * ch * 4)
  const view = new DataView(bytes)
  for (let f = 0; f < frames; f++) {
    for (let c = 0; c < ch; c++) {
      view.setFloat32((f * ch + c) * 4, value(f, c), true)
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

/** Attach a fresh shared ring to the core and return the writer-side view. */
function attachShared(core: ConsumptionState, capacityFrames: number): SharedRing {
  const ring = createSharedRing(16 + capacityFrames * core.channelCount * 4, core.channelCount)
  core.attachShared(ring.sab)
  return ring
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
    core.enqueue(makeBuffer(1_000, () => 1.0))
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
    expect(last.res.anchor).toEqual({ frame: 300, time: 256 / RATE, paused: false })
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
    const core = freshCore(10_000, { anchorEvery: 480 })
    core.enqueue(makeBuffer(1_000, () => 0.5))
    const a1 = block(core, 0, 480)
    expect(a1.res.anchor).toEqual({ frame: 0, time: 0, paused: false })
    const a2 = block(core, 480 / RATE, 480)
    expect(a2.res.anchor).toEqual({ frame: 480, time: 480 / RATE, paused: false })
    const a3 = block(core, 960 / RATE, 40)
    expect(a3.res.anchor).toBeNull()
  })

  it('defaults to ~20 Hz anchors (rate/20 frames)', () => {
    const core = freshCore(10_000) // 48 kHz default cadence: 2400 frames
    core.enqueue(makeBuffer(5_000, () => 0.5))
    const anchors: NonNullable<ReturnType<typeof block>['res']['anchor']>[] = []
    for (let start = 0; start < 5_000; start += 128) {
      const r = block(core, start / RATE, 128)
      if (r.res.anchor) anchors.push(r.res.anchor)
    }
    // Second crossing: position 2432 + 2400 = 4832, reached by the block
    // that starts at 4736 (the next 128-frame boundary).
    expect(anchors).toEqual([
      { frame: 0, time: 2_304 / RATE, paused: false },
      { frame: 2_432, time: 4_736 / RATE, paused: false },
    ])
  })

  it('emits one final anchor with paused=true when the pause ramp completes', () => {
    const core = freshCore(10_000, { anchorEvery: 4_000 })
    core.enqueue(makeBuffer(5_000, () => 0.5))
    block(core, 0, 128)
    core.pause() // ramp: 5 ms = 240 frames at 48 kHz
    const r1 = block(core, 128 / RATE, 128)
    expect(r1.res.anchor).toBeNull() // ramp still running (240 → 112)
    const r2 = block(core, 256 / RATE, 128)
    expect(r2.res.anchor).toEqual({ frame: 128, time: 256 / RATE, paused: true })
    const r3 = block(core, 384 / RATE, 128)
    expect(r3.res.anchor).toBeNull() // one final anchor per pause episode
    core.resume()
    core.pause()
    const r4 = block(core, 512 / RATE, 240)
    expect(r4.res.anchor).toEqual({ frame: 128, time: 512 / RATE, paused: true })
  })
})

describe('ConsumptionState bounds', () => {
  it('rejects enqueue that would overflow the 12 s budget', () => {
    // 1 kHz => 12 s budget = 12 000 frames, cheap to exercise.
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    const half = new ArrayBuffer(6_000 * 1 * 4)
    expect(core.enqueue(half)).toBe(true)
    expect(core.enqueue(half)).toBe(true)
    expect(core.buffered).toBe(12_000)
    expect(core.enqueue(new ArrayBuffer(4 * 1 * 4))).toBe(false)
    expect(core.buffered).toBe(12_000)
  })

  it('rejects data beyond the valid endpoint', () => {
    const core = freshCore(100, { rate: 1_000, ch: 1 })
    core.seek(99)
    // Only one frame is valid left.
    const two = new ArrayBuffer(2 * 1 * 4)
    expect(core.enqueue(two)).toBe(true)
    expect(core.buffered).toBe(1)
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

describe('ConsumptionState transfer queue', () => {
  it('enqueueChannels: in-order stereo output through the queue', () => {
    const core = freshCore()
    const left = new Float32Array(300)
    const right = new Float32Array(300)
    for (let f = 0; f < 300; f++) {
      left[f] = f * 0.001
      right[f] = (f + 1_000) * 0.001
    }
    expect(core.enqueueChannels([left, right])).toBe(true)
    expect(core.queued).toBe(300)
    expect(core.buffered).toBe(300)
    const first = block(core, 0, 128)
    expect(first.res.consumed).toBe(128)
    expect(first.output[0][0]).toBeCloseTo(0, 5)
    expect(first.output[1][0]).toBeCloseTo(1, 5)
    const second = block(core, 128 / RATE, 128)
    expect(second.output[0][0]).toBeCloseTo(0.128, 5)
    // The chunk fit, so it drained straight into the ring; 300 - 256 = 44
    // frames remain there.
    expect(core.queued).toBe(0)
    expect(core.available).toBe(44)
    expect(core.buffered).toBe(44)
    expect(core.position).toBe(256)
  })

  it('rejects a chunk that would exceed the 12 s budget (ring + queue)', () => {
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    expect(core.enqueueChannels([new Float32Array(12_000)])).toBe(true)
    expect(core.buffered).toBe(12_000)
    expect(core.enqueueChannels([new Float32Array(1)])).toBe(false)
  })

  it('clamps queued chunks to the valid endpoint', () => {
    const core = freshCore(100, { rate: 1_000, ch: 1 })
    core.seek(99)
    expect(core.enqueueChannels([new Float32Array(10)])).toBe(true)
    expect(core.buffered).toBe(1)
    expect(core.enqueueChannels([new Float32Array(1)])).toBe(false)
  })

  it('clears the queue on seek: stale chunks are never output', () => {
    const core = freshCore()
    const chunk = [new Float32Array(1_000).fill(1), new Float32Array(1_000).fill(1)]
    expect(core.enqueueChannels(chunk)).toBe(true)
    core.seek(5_000, 2)
    expect(core.queued).toBe(0)
    expect(core.buffered).toBe(0)
    const stale = block(core, 0, 128)
    expect(stale.output[0][0]).toBe(0)
    expect(stale.res.underrun).toBe(false)
  })

  it('reports buffered frames in the process result', () => {
    const core = freshCore()
    expect(
      core.enqueueChannels([new Float32Array(500).fill(0.5), new Float32Array(500).fill(0.5)]),
    ).toBe(true)
    const { res } = block(core, 0, 128)
    expect(res.consumed).toBe(128)
    expect(res.buffered).toBe(500 - 128)
  })
})

describe('ConsumptionState shared ring', () => {
  it('consumes shared frames in order, across the ring wrap (SPSC)', () => {
    const core = freshCore(100_000, { rate: 1_000, ch: 2 })
    const ring = attachShared(core, 2_000)
    core.seek(0, 1)
    acknowledgeSharedFlush(ring, 1, 0)

    // Interleave writer chunks and reader consumption so the 2 000-frame
    // ring wraps several times (SPSC: the writer cannot pass the reader).
    let nextFrame = 0
    while (nextFrame < 5_000) {
      const n = Math.min(1_000, 5_000 - nextFrame)
      const bytes = makeBuffer(n, (f, c) => (nextFrame + f + c * 10_000) * 0.001, 2)
      // Write once; when the ring is full, consume until it fits.
      let written = writeSharedRing(ring, bytes)
      while (written === 0) {
        const { res } = block(core, core.position / 1_000, 1_000)
        expect(res.consumed).toBe(1_000)
        written = writeSharedRing(ring, bytes)
      }
      expect(written).toBe(n)
      nextFrame += n
    }
    while (core.position < 5_000) {
      const start = core.position
      const { output, res } = block(core, start / 1_000, 1_000)
      expect(res.consumed).toBe(1_000)
      for (const i of [0, 499, 999]) {
        expect(output[0][i]).toBeCloseTo((start + i) * 0.001, 5)
        expect(output[1][i]).toBeCloseTo((start + i + 10_000) * 0.001, 5)
      }
    }
    expect(core.position).toBe(5_000)
    expect(core.buffered).toBe(0)
  })

  it('ignores the ring while the generation mismatches (flush barrier)', () => {
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    const ring = attachShared(core, 2_000)
    core.seek(0, 1)
    acknowledgeSharedFlush(ring, 1, 0)
    expect(
      writeSharedRing(
        ring,
        makeBuffer(1_000, (f) => f * 0.001, 1),
      ),
    ).toBe(1_000)

    // Seek to generation 2 while the worker has not acknowledged: the
    // generation-1 data in the ring must not be output.
    core.seek(1_000, 2)
    const stale = block(core, 1, 1_000)
    expect(stale.res.consumed).toBe(0)
    expect(stale.output[0][0]).toBe(0)
    expect(stale.res.underrun).toBe(false) // still flushing

    // The worker acknowledges the flush: generation + writer reset.
    acknowledgeSharedFlush(ring, 2, 1_000)
    const fresh = makeBuffer(1_000, (f) => (1_000 + f) * 0.001, 1)
    expect(writeSharedRing(ring, fresh)).toBe(1_000)
    const out = block(core, 2, 1_000)
    expect(out.res.consumed).toBe(1_000)
    expect(out.output[0][0]).toBeCloseTo(1, 5)
    expect(out.output[0][999]).toBeCloseTo(1.999, 5)
    expect(core.position).toBe(2_000)
  })

  it('ends exactly at the endpoint on the shared path', () => {
    const core = freshCore(3_000, { rate: 1_000, ch: 1 })
    const ring = attachShared(core, 2_000)
    core.seek(0, 1)
    acknowledgeSharedFlush(ring, 1, 0)
    expect(
      writeSharedRing(
        ring,
        makeBuffer(2_000, () => 0.5, 1),
      ),
    ).toBe(2_000)
    const a = block(core, 0, 1_000)
    expect(a.res.consumed).toBe(1_000)
    expect(
      writeSharedRing(
        ring,
        makeBuffer(1_000, () => 0.5, 1),
      ),
    ).toBe(1_000)
    const b = block(core, 1, 1_000)
    expect(b.res.consumed).toBe(1_000)
    const last = block(core, 2, 1_000)
    expect(last.res.consumed).toBe(1_000)
    expect(last.res.ended).toBe(true)
    expect(core.position).toBe(3_000)
    expect(core.buffered).toBe(0)
  })

  it('holds the last shared samples during the pause ramp', () => {
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    const ring = attachShared(core, 2_000)
    core.seek(0, 1)
    acknowledgeSharedFlush(ring, 1, 0)
    expect(
      writeSharedRing(
        ring,
        makeBuffer(1_000, (f) => f * 0.001, 1),
      ),
    ).toBe(1_000)
    const first = block(core, 0, 1_000)
    expect(first.res.consumed).toBe(1_000)
    const held = core.position
    expect(held).toBe(1_000)

    core.pause()
    // The ramp is ~5 frames at 1 kHz; use small blocks to step through it.
    const ramp1 = block(core, held / 1_000, 2)
    expect(ramp1.res.consumed).toBe(0)
    // Full level (5/5) on the last consumed sample (frame 999 * 0.001).
    expect(ramp1.output[0][0]).toBeCloseTo(0.999, 5)
    const ramp2 = block(core, (held + 2) / 1_000, 2)
    // Reduced level (3/5).
    expect(ramp2.output[0][0]).toBeCloseTo(0.999 * (3 / 5), 5)
    expect(ramp2.output[0][0]).toBeLessThan(ramp1.output[0][0])
    const ramp3 = block(core, (held + 4) / 1_000, 2)
    // Level (1/5).
    expect(ramp3.output[0][0]).toBeCloseTo(0.999 * (1 / 5), 5)
    const ramp4 = block(core, (held + 6) / 1_000, 2)
    expect(ramp4.output[0][0]).toBe(0)
    expect(core.position).toBe(held)
  })

  it('reports the shared availability as buffered', () => {
    const core = freshCore(100_000, { rate: 1_000, ch: 1 })
    const ring = attachShared(core, 2_000)
    core.seek(0, 1)
    acknowledgeSharedFlush(ring, 1, 0)
    expect(core.buffered).toBe(0)
    expect(
      writeSharedRing(
        ring,
        makeBuffer(750, () => 0.25, 1),
      ),
    ).toBe(750)
    expect(core.buffered).toBe(750)
  })
})
