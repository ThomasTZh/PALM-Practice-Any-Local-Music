/**
 * Tests for the stretch host API against the real WASM artifacts
 * (M2.9, spec §11.3.11, plan Phase 4).
 *
 * The bundled artifacts (`dist/stretch-{scalar,simd}.wasm`, built by
 * `build.mjs` — see `BUILD.md`) are read with `readFileSync` and
 * instantiated directly: no compiler, no emscripten glue.
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
/** Seek length at 1x/48k: inputLatency + outputLatency = 5760. */
const SEEK = 5760

function sine(ch: Float32Array, n: number, phase0: number, ph = 0): void {
  for (let i = 0; i < n; i++) {
    ch[i] = 0.5 * Math.sin((2 * Math.PI * 440 * (phase0 + i)) / RATE + ph)
  }
}

/** Prime the engine from a 440 Hz sine at `phase0`; returns the seek length. */
function prime(e: StretchEngine, phase0 = 0): number {
  const sl = e.seekLength()
  sine(e.inL, sl, phase0)
  sine(e.inR, sl, phase0, 0.5)
  e.outputSeek(sl)
  return sl
}

/** Feed `quanta` render quanta of the continuing sine; report consumption. */
function runSine(
  e: StretchEngine,
  quanta: number,
  phase0: number,
  rate?: number,
): { consumed: number; out: number; lastRms: number } {
  if (rate !== undefined) e.setRate(rate)
  let phase = phase0
  let consumed = 0
  let lastRms = 0
  for (let c = 0; c < quanta; c++) {
    const d = e.inputDemand(128)
    sine(e.inL, d, phase)
    sine(e.inR, d, phase, 0.5)
    phase += d
    consumed += e.process(d, 128)
    if (c === quanta - 1) {
      let s = 0
      for (let i = 0; i < 128; i++) s += e.outL[i] * e.outL[i]
      lastRms = Math.sqrt(s / 128)
    }
  }
  return { consumed, out: quanta * 128, lastRms }
}

describe('stretch-host (real WASM artifacts)', () => {
  it('instantiates both variants with the fixed 2 MiB memory', () => {
    for (const bytes of [scalarBytes, simdBytes]) {
      const e = instantiateStretch(bytes)
      e.configure(RATE)
      // Input regions hold a full priming buffer at 2x (> maxFrames);
      // output regions are exactly maxFrames.
      expect(e.inL.length).toBeGreaterThan(STRETCH_MAX_FRAMES)
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

  it('primes so an impulse stays near the start (no full-window delay)', () => {
    const e = instantiateStretch(scalarBytes)
    e.configure(RATE)
    const sl = e.seekLength()
    e.inL.fill(0)
    e.inR.fill(0)
    e.inL[0] = 1
    e.inR[0] = 1
    e.outputSeek(sl)
    let peak = 0
    let peakPos = -1
    let n = 0
    for (let c = 0; c < 64; c++) {
      const d = e.inputDemand(128)
      e.inL.fill(0, 0, d)
      e.inR.fill(0, 0, d)
      e.process(d, 128)
      for (let i = 0; i < 128; i++) {
        const v = Math.abs(e.outL[i])
        if (v > peak) {
          peak = v
          peakPos = n + i
        }
        n++
      }
      if (peak > 0.1 && c > 2) break
    }
    expect(peak).toBeGreaterThan(0.05)
    expect(peakPos).toBeLessThan(2 * 2880)
  })

  it('consumes input at the target rate (2x and 0.5x)', () => {
    for (const target of [2.0, 0.5]) {
      const e = instantiateStretch(scalarBytes)
      e.configure(RATE)
      prime(e)
      const r = runSine(e, 48000 / 128, SEEK, target)
      expect(Math.abs(r.consumed / r.out - target)).toBeLessThan(0.05)
      expect(r.lastRms).toBeGreaterThan(0.15)
    }
  })

  it('produces steady output immediately after priming', () => {
    const e = instantiateStretch(scalarBytes)
    e.configure(RATE)
    prime(e)
    let firstNZ = -1
    let phase = SEEK
    for (let c = 0; c < 32 && firstNZ < 0; c++) {
      const d = e.inputDemand(128)
      sine(e.inL, d, phase)
      sine(e.inR, d, phase, 0.5)
      phase += d
      e.process(d, 128)
      for (let i = 0; i < 128; i++) {
        if (Math.abs(e.outL[i]) > 1e-6) {
          firstNZ = c * 128 + i
          break
        }
      }
    }
    expect(firstNZ).toBeGreaterThanOrEqual(0)
    expect(firstNZ).toBeLessThan(128)
  })

  it('is deterministic for the fixed seed', () => {
    const a = instantiateStretch(scalarBytes)
    const b = instantiateStretch(scalarBytes)
    a.configure(RATE)
    b.configure(RATE)
    prime(a)
    prime(b)
    let phaseA = SEEK
    let phaseB = SEEK
    for (let c = 0; c < 64; c++) {
      const dA = a.inputDemand(128)
      const dB = b.inputDemand(128)
      sine(a.inL, dA, phaseA)
      sine(a.inR, dA, phaseA, 0.5)
      sine(b.inL, dB, phaseB)
      sine(b.inR, dB, phaseB, 0.5)
      phaseA += dA
      phaseB += dB
      a.process(dA, 128)
      b.process(dB, 128)
      expect(Array.from(a.outL)).toEqual(Array.from(b.outL))
    }
  })

  it('matches scalar and SIMD within tolerance', () => {
    const a = instantiateStretch(scalarBytes)
    const b = instantiateStretch(simdBytes)
    a.configure(RATE)
    b.configure(RATE)
    prime(a)
    prime(b)
    let phaseA = SEEK
    let phaseB = SEEK
    let maxDiff = 0
    for (let c = 0; c < 64; c++) {
      const dA = a.inputDemand(128)
      const dB = b.inputDemand(128)
      sine(a.inL, dA, phaseA)
      sine(a.inR, dA, phaseA, 0.5)
      sine(b.inL, dB, phaseB)
      sine(b.inR, dB, phaseB, 0.5)
      phaseA += dA
      phaseB += dB
      a.process(dA, 128)
      b.process(dB, 128)
      for (let i = 0; i < 128; i++) {
        maxDiff = Math.max(
          maxDiff,
          Math.abs(a.outL[i] - b.outL[i]),
          Math.abs(a.outR[i] - b.outR[i]),
        )
      }
    }
    expect(maxDiff).toBeLessThan(1e-3)
  })

  it('reset + re-seek resumes output at the new position', () => {
    const e = instantiateStretch(scalarBytes)
    e.configure(RATE)
    prime(e)
    runSine(e, 32, SEEK)
    const newPhase = 100000
    const sl = e.seekLength()
    sine(e.inL, sl, newPhase)
    sine(e.inR, sl, newPhase, 0.5)
    e.outputSeek(sl)
    const r = runSine(e, 32, newPhase + sl)
    expect(r.lastRms).toBeGreaterThan(0.15)
  })

  it('flushes a decaying tail, then silence', () => {
    const e = instantiateStretch(scalarBytes)
    e.configure(RATE)
    prime(e)
    let phase = SEEK
    for (let c = 0; c < 32; c++) {
      const d = e.inputDemand(128)
      sine(e.inL, d, phase)
      sine(e.inR, d, phase, 0.5)
      phase += d
      e.process(d, 128)
    }
    const n1 = e.flushTail(4096)
    let nz1 = 0
    for (let i = 0; i < n1; i++) {
      if (Math.abs(e.outL[i]) > 1e-6) nz1++
    }
    expect(nz1).toBeGreaterThan(100)
    const n2 = e.flushTail(4096)
    let max2 = 0
    for (let i = 0; i < n2; i++) {
      max2 = Math.max(max2, Math.abs(e.outL[i]))
    }
    expect(max2).toBeLessThan(1e-6)
  })

  it('reports monotonic input demand', () => {
    const e = instantiateStretch(scalarBytes)
    e.configure(RATE)
    prime(e)
    for (let f = 0; f <= STRETCH_MAX_FRAMES; f += 16) {
      expect(e.inputDemand(f) + 1).toBeGreaterThanOrEqual(e.inputDemand(f + 1))
    }
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
