/**
 * Tests for the stretch host API against the real WASM artifacts
 * (M2.9, spec §11.3.11; rolling-seek playback model in M2.10 §12.3).
 *
 * The bundled artifacts (`dist/stretch-{scalar,simd}.wasm`, built by
 * `build.mjs` — see `BUILD.md`) are read with `readFileSync` and
 * instantiated directly: no compiler, no emscripten glue.
 *
 * The rolling recipe (one render quantum, the worklet's data path):
 *
 *     windowEnd = round(S + rate*outLat + inLat)
 *     fill inL/inR with source frames [windowEnd - windowLength, windowEnd)
 *     seek(windowLength, rate); process(0, 128)
 *     S += rate * 128
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  instantiateStretch,
  simdSupported,
  STRETCH_CHANNELS,
  STRETCH_MAX_FRAMES,
  STRETCH_MEMORY_BYTES,
  type StretchEngine,
} from '../src/playback/stretch/stretch-host'
import { measureLatencies, STRETCH_PROFILE } from '../src/playback/stretch/stretch-profile'

// Vitest runs with the frontend/ directory as cwd.
const dist = path.resolve('src/playback/stretch/dist')
const scalarBytes = readFileSync(path.join(dist, 'stretch-scalar.wasm'))
const simdBytes = readFileSync(path.join(dist, 'stretch-simd.wasm'))

const RATE = 48000
const QUANTUM = 128
const OUT_LAT = 2880
const IN_LAT = 2880

function sine(ch: Float32Array, from: number, count: number, ph = 0): void {
  for (let i = 0; i < count; i++) {
    ch[i] = 0.5 * Math.sin((2 * Math.PI * 440 * (from + i)) / RATE + ph)
  }
}

function makeEngine(bytes = scalarBytes): StretchEngine {
  const eng = instantiateStretch(bytes)
  eng.configure(RATE)
  return eng
}

/**
 * Fill the context window for the quantum at audible cursor `S` and run
 * the rolling seek. Returns the output RMS of the quantum.
 */
function rollQuantum(eng: StretchEngine, s: number, rate: number): number {
  const end = Math.round(s + rate * OUT_LAT + IN_LAT)
  const from = end - eng.windowLength()
  sine(eng.inL, from, eng.windowLength())
  sine(eng.inR, from, eng.windowLength(), 0.5)
  eng.seek(eng.windowLength(), rate)
  eng.process(0, QUANTUM)
  let sum = 0
  for (let i = 0; i < QUANTUM; i++) sum += eng.outL[i] * eng.outL[i]
  return Math.sqrt(sum / QUANTUM)
}

/** Roll `quanta` quanta from `startFrame` at `rate`; return the RMS trail. */
function roll(eng: StretchEngine, quanta: number, startFrame: number, rate = 1): number[] {
  const trail: number[] = []
  let s = startFrame
  for (let q = 0; q < quanta; q++) {
    trail.push(rollQuantum(eng, s, rate))
    s += rate * QUANTUM
  }
  return trail
}

/** Zero-crossing frequency estimate over `quanta` quanta (after a warm-up). */
function outputFrequency(eng: StretchEngine, s: number, rate: number, quanta = 64): number {
  roll(eng, 64, s, rate) // silent pre-roll; the measurement starts warm
  let start = s + 64 * rate * QUANTUM
  let crossings = 0
  let prev = 0
  for (let q = 0; q < quanta; q++) {
    rollQuantum(eng, start, rate)
    for (let i = 0; i < QUANTUM; i++) {
      const v = eng.outL[i]
      if (prev <= 0 && v > 0) crossings++
      prev = v
    }
    start += rate * QUANTUM
  }
  return crossings / ((quanta * QUANTUM) / RATE)
}

describe('stretch-host (real WASM artifacts)', () => {
  it('instantiates both variants with the fixed 2 MiB memory', () => {
    for (const bytes of [scalarBytes, simdBytes]) {
      const e = instantiateStretch(bytes)
      e.configure(RATE)
      // Input regions hold a full context window (7200 @48k).
      expect(e.inL.length).toBe(7200)
      expect(e.inL.length).toBe(e.inR.length)
      expect(e.outL.length).toBe(STRETCH_MAX_FRAMES)
      expect(e.outL.length).toBe(e.outR.length)
    }
  })

  it('exposes the SIMD capability probe', () => {
    expect(typeof simdSupported()).toBe('boolean')
  })

  it('reports the pinned latencies at 48k and 44.1k', () => {
    const e = instantiateStretch(scalarBytes)
    expect(measureLatencies(e, 48000)).toEqual({ inputFrames: 2880, outputFrames: 2880 })
    const e2 = instantiateStretch(scalarBytes)
    expect(measureLatencies(e2, 44100)).toEqual({ inputFrames: 2646, outputFrames: 2646 })
  })

  it('reports the window geometry the rolling recipe needs', () => {
    const e = makeEngine()
    expect(e.latencies()).toEqual({ inputFrames: IN_LAT, outputFrames: OUT_LAT })
    expect(e.windowLength()).toBe(7200)
    // The window covers the upstream live-playback buffer (in + out
    // latency) plus one STFT interval.
    expect(e.windowLength()).toBeGreaterThanOrEqual(IN_LAT + OUT_LAT)
  })

  it.each([1, 2, 0.5])('produces steady output through the rolling seek at %sx', (rate) => {
    const e = makeEngine()
    const trail = roll(e, 200, 20_000, rate)
    // After the silent pre-roll (5760 output frames ≈ 45 quanta), the
    // 440 Hz sine at amplitude 0.5 is steady at RMS ≈ 0.354.
    for (let q = 64; q < trail.length; q++) {
      expect(trail[q]).toBeGreaterThan(0.3)
      expect(trail[q]).toBeLessThan(0.4)
    }
  })

  it.each([1, 2, 0.5])('preserves pitch at %sx', (rate) => {
    const e = makeEngine()
    expect(outputFrequency(e, 20_000, rate)).toBeGreaterThan(420)
    expect(outputFrequency(e, 20_000, rate)).toBeLessThan(460)
  })

  it('is deterministic for the fixed seed', () => {
    const a = makeEngine()
    const b = makeEngine()
    let sa = 20_000
    let sb = 20_000
    for (let q = 0; q < 64; q++) {
      rollQuantum(a, sa, 1)
      rollQuantum(b, sb, 1)
      expect(Array.from(a.outL)).toEqual(Array.from(b.outL))
      sa += QUANTUM
      sb += QUANTUM
    }
  })

  it('matches scalar and SIMD within tolerance', () => {
    const a = makeEngine(scalarBytes)
    const b = makeEngine(simdBytes)
    let sa = 20_000
    let sb = 20_000
    let maxDiff = 0
    for (let q = 0; q < 64; q++) {
      rollQuantum(a, sa, 1)
      rollQuantum(b, sb, 1)
      for (let i = 0; i < QUANTUM; i++) {
        maxDiff = Math.max(maxDiff, Math.abs(a.outL[i] - b.outL[i]))
      }
      sa += QUANTUM
      sb += QUANTUM
    }
    expect(maxDiff).toBeLessThan(1e-3)
  })

  it('reset + re-seek resumes output at the new position', () => {
    const e = makeEngine()
    const before = roll(e, 64, 20_000, 1)
    expect(before[63]).toBeGreaterThan(0.3)
    e.reset()
    const after = roll(e, 64, 100_000, 1)
    expect(after[63]).toBeGreaterThan(0.3)
  })

  it('ramps plain setRate and jumps setRateNow', () => {
    const e = makeEngine()
    e.setRate(2)
    // Only the target is recorded; the effective rate ramps over ≈50 ms
    // of rendered output, so it is still 1× before any output.
    expect(e.effectiveRate()).toBe(1)
    roll(e, 4, 20_000, 1)
    expect(e.effectiveRate()).toBeGreaterThan(1)
    expect(e.effectiveRate()).toBeLessThan(2)
    e.setRateNow(2)
    expect(e.effectiveRate()).toBe(2)
  })
})

describe('stretch-profile', () => {
  it('records the spec §11.5 configuration', () => {
    expect(STRETCH_PROFILE.qualityPreset).toBe('default')
    expect(STRETCH_PROFILE.pitchShiftSemitones).toBe(0)
    expect(STRETCH_PROFILE.formant).toBe(false)
    expect(STRETCH_PROFILE.channels).toBe(STRETCH_CHANNELS)
    expect(STRETCH_PROFILE.maxOutputFrames).toBe(STRETCH_MAX_FRAMES)
    expect(STRETCH_PROFILE.memoryBytes).toBe(STRETCH_MEMORY_BYTES)
    expect(STRETCH_PROFILE.rateRange).toEqual({ min: 0.25, max: 2.0 })
    expect(STRETCH_PROFILE.rateRampSeconds).toBeCloseTo(0.05)
  })
})
