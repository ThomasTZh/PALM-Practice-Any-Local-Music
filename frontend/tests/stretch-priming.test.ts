/**
 * M2.10 §12.3 rolling-seek probes against the REAL bundled artifact.
 *
 * These pin the alignment contract the worklet and transport rely on:
 *
 * - the window law `windowEnd = round(S + rate*outLat + inLat)` keeps
 *   every content feature (an impulse train — the spec's own §12.3.6
 *   probe) within ±200 output frames of its mapped position at every
 *   rate (0.25×…2×), with no drift over long runs;
 * - a wet start is silent until the engine's overlap-add accumulator
 *   fills: ~5760 output frames of silent pre-roll (the worklet's
 *   `WARMUP_OUT_FRAMES`) bring the first audible quantum to full level;
 * - `reset()` isolates a hard re-position: no old content leaks past
 *   the new boundary;
 * - the source boundary zero-pads the context window (head and tail)
 *   instead of reading outside it;
 * - the requested boundary itself maps to the first audible frame —
 *   there is no second latency compensation (§12.3.6).
 *
 * The rolling recipe under test (one render quantum):
 *
 *     windowEnd = round(S + rate*outLat + inLat)
 *     fill inL/inR with source frames [windowEnd - windowLength, windowEnd)
 *     seek(windowLength, rate); process(0, 128)
 *     S += rate * 128
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { instantiateStretch, type StretchEngine } from '../src/playback/stretch/stretch-host'

const RATE = 48_000
const QUANTUM = 128
/** Measured @48k (asserted below before anything else relies on it). */
const IN_LAT = 2880
const OUT_LAT = 2880
const WINDOW = 7200
/** Impulse spacing in source frames (0.1 s): sparse, unambiguous markers. */
const IMPULSE_SPACING = 4800

const dist = path.resolve('src/playback/stretch/dist')
const scalarBytes = readFileSync(path.join(dist, 'stretch-scalar.wasm'))

function makeEngine(): StretchEngine {
  const eng = instantiateStretch(scalarBytes)
  eng.configure(RATE)
  return eng
}

/** One rolling quantum at audible cursor `S`; optionally record output. */
function quantum(
  eng: StretchEngine,
  s: number,
  rate: number,
  content: (frame: number) => number,
  record: boolean,
): number[] | null {
  const end = Math.round(s + rate * OUT_LAT + IN_LAT)
  const start = end - eng.windowLength()
  for (let i = 0; i < eng.windowLength(); i++) {
    const v = content(start + i)
    eng.inL[i] = v
    eng.inR[i] = v
  }
  eng.seek(eng.windowLength(), rate)
  eng.process(0, QUANTUM)
  if (!record) return null
  const out: number[] = []
  for (let k = 0; k < QUANTUM; k++) out.push(eng.outL[k])
  return out
}

/**
 * Play from audible boundary `A0` at `rate`: reset, run `warm` output
 * frames of silent pre-roll (from `A0 - warm*rate`), then record
 * `quanta` quanta starting exactly at `A0`.
 */
function rollingRun(opts: {
  rate: number
  a0: number
  warm: number
  quanta: number
  content: (frame: number) => number
}): number[] {
  const { rate, a0, warm, quanta, content } = opts
  const eng = makeEngine()
  eng.reset()
  let s = a0 - warm * rate
  for (let w = 0; w < warm; w += QUANTUM) {
    quantum(eng, s, rate, content, false)
    s += rate * QUANTUM
  }
  const out: number[] = []
  for (let q = 0; q < quanta; q++) {
    out.push(...(quantum(eng, s, rate, content, true) as number[]))
    s += rate * QUANTUM
  }
  return out
}

/** Low-level tone keeps the engine out of its silence pass-through. */
function background(frame: number): number {
  return 0.05 * Math.sin((2 * Math.PI * 200 * frame) / RATE)
}

/** Impulses every `IMPULSE_SPACING` source frames on the tone. */
function impulses(frame: number): number {
  return frame % IMPULSE_SPACING === 0 ? background(frame) + 1 : background(frame)
}

/**
 * For each impulse in the run, the output index of its peak vs the
 * mapped index `(impulse - a0)/rate`. Returns residuals in output frames.
 */
function impulseResiduals(out: number[], a0: number, rate: number): number[] {
  const res: number[] = []
  const span = 600
  const first = Math.ceil((a0 + 1) / IMPULSE_SPACING)
  for (let m = first; ; m++) {
    const expect = (m * IMPULSE_SPACING - a0) / rate
    if (expect >= out.length) break
    let peak = 0
    let peakIndex = -1
    for (
      let i = Math.max(1, Math.floor(expect - span));
      i < Math.min(out.length, expect + span);
      i++
    ) {
      const a = Math.abs(out[i])
      if (a > peak) {
        peak = a
        peakIndex = i
      }
    }
    if (peakIndex >= 0 && peak > 0.15) res.push(peakIndex - expect)
  }
  return res
}

function mean(values: number[]): number {
  return values.reduce((a, b) => a + b, 0) / values.length
}

describe('stretch priming probes (M2.10 §12.3)', () => {
  it('reports the geometry and rolling law this file assumes', () => {
    const eng = makeEngine()
    expect(eng.latencies()).toEqual({ inputFrames: IN_LAT, outputFrames: OUT_LAT })
    expect(eng.windowLength()).toBe(WINDOW)
    // The upstream live-playback buffer: input + output latency.
    expect(IN_LAT + OUT_LAT).toBe(5760)
  })

  it.each([1, 2, 0.5, 0.25])(
    'maps an impulse train within ±200 output frames of the cursor at %sx',
    (rate) => {
      const a0 = 50_000
      const out = rollingRun({ rate, a0, warm: 5760, quanta: 300, content: impulses })
      const res = impulseResiduals(out, a0, rate)
      expect(res.length).toBeGreaterThanOrEqual(rate === 0.25 ? 2 : 4)
      expect(Math.max(...res.map(Math.abs))).toBeLessThanOrEqual(200)
    },
  )

  it.each([1, 2, 0.5])('does not drift over 600 quanta at %sx', (rate) => {
    const a0 = 50_000
    const out = rollingRun({ rate, a0, warm: 5760, quanta: 600, content: impulses })
    const res = impulseResiduals(out, a0, rate)
    const third = Math.floor(res.length / 3)
    const early = mean(res.slice(0, third))
    const late = mean(res.slice(2 * third))
    expect(Math.abs(late - early)).toBeLessThanOrEqual(120)
  })

  it.each([1, 2, 0.5])(
    'starts silent without a warm-up and at full level after 5760 output frames (%sx)',
    (rate) => {
      const a0 = 500
      const flat = () => 0.1
      const cold = rollingRun({ rate, a0, warm: 0, quanta: 1, content: flat })
      const coldMean = mean(cold)
      expect(Math.abs(coldMean)).toBeLessThan(0.01)
      const warm = rollingRun({ rate, a0, warm: 5760, quanta: 12, content: flat })
      const firstMean = mean(warm.slice(0, QUANTUM))
      expect(firstMean).toBeGreaterThan(0.09)
      expect(firstMean).toBeLessThan(0.11)
      // Steady afterwards: no envelope ripple beyond a few percent.
      for (let q = 1; q < 12; q++) {
        expect(Math.abs(mean(warm.slice(q * QUANTUM, (q + 1) * QUANTUM)) - 0.1)).toBeLessThan(0.01)
      }
    },
  )

  it('isolates a hard re-seek: no old content leaks past the new boundary', () => {
    const eng = makeEngine()
    eng.reset()
    // Content A at the old position...
    let s = 50_000
    for (let q = 0; q < 64; q++) {
      quantum(eng, s, 1, () => 0.1, false)
      s += QUANTUM
    }
    // ...then a hard re-seek to content B with the silent pre-roll.
    eng.reset()
    const b0 = 90_000
    s = b0 - 5760
    for (let w = 0; w < 5760; w += QUANTUM) {
      quantum(eng, s, 1, () => 0.2, false)
      s += QUANTUM
    }
    const out = quantum(eng, s, 1, () => 0.2, true) as number[]
    expect(mean(out)).toBeGreaterThan(0.19)
    expect(mean(out)).toBeLessThan(0.21)
  })

  it('zero-pads the head when the boundary is below the input latency', () => {
    // Boundary 1000: the earliest context window starts before frame 0,
    // so the head is padded; the mapping must still hold at 1× and 2×.
    for (const rate of [1, 2]) {
      const a0 = 1000
      const out = rollingRun({ rate, a0, warm: 5760, quanta: 300, content: impulses })
      const res = impulseResiduals(out, a0, rate)
      expect(res.length).toBeGreaterThanOrEqual(2)
      expect(Math.max(...res.map(Math.abs))).toBeLessThanOrEqual(200)
    }
  })

  it('fades the tail after the source end without an extra blank', () => {
    const end = 60_000
    const a0 = end - 4 * QUANTUM
    const content = (frame: number) => (frame < end ? 0.1 : 0)
    const out = rollingRun({ rate: 1, a0, warm: 5760, quanta: 10, content })
    const means: number[] = []
    for (let q = 0; q < 10; q++) means.push(mean(out.slice(q * QUANTUM, (q + 1) * QUANTUM)))
    // Inside: full level (no premature blank)...
    for (let q = 0; q < 3; q++) {
      expect(Math.abs(means[q] - 0.1)).toBeLessThan(0.02)
    }
    // ...then a natural window fade: partial, then silence within 3 quanta.
    expect(means[3]).toBeGreaterThan(0.02)
    for (let q = 6; q < 10; q++) {
      expect(Math.abs(means[q])).toBeLessThan(0.01)
    }
  })
})
