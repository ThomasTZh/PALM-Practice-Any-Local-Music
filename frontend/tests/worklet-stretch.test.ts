/**
 * Worklet-core tests for the stretch integration (M2.9, plan Phase 5).
 *
 * `MixState` driven with the REAL WASM engine: priming, consumption
 * ratios at 0.5x/2x, rate-ramp smoothness, consumed-frame bookkeeping
 * (anchors), seek re-priming, underrun under variable demand, the
 * end-of-source tail, pause/resume, and the master gain after the
 * stretcher (§11.1 order). The final block loads the worklet module in
 * a faked worklet scope and drives the `PcmProcessor` adapter end to
 * end (engine instantiation from `processorOptions.stretch.wasmBytes`).
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MixState } from '../src/playback/worklet-processor.js'
import { instantiateStretch, type StretchEngine } from '../src/playback/stretch/stretch-host'

const RATE = 48_000
const QUANTUM = 128
const SEEK_1X = 5760 // inputLatency + 1x * outputLatency @48k

// Vitest runs with the frontend/ directory as cwd.
const dist = path.resolve('src/playback/stretch/dist')
const scalarBytes = readFileSync(path.join(dist, 'stretch-scalar.wasm'))

function sine(n: number, phase0 = 0, amp = 0.5, ph = 0): Float32Array {
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    out[i] = amp * Math.sin((2 * Math.PI * 440 * (phase0 + i)) / RATE + ph)
  }
  return out
}

function rms(ch: Float32Array): number {
  let s = 0
  for (let i = 0; i < ch.length; i++) s += ch[i] * ch[i]
  return Math.sqrt(s / ch.length)
}

interface Rig {
  mix: MixState
  outL: Float32Array
  outR: Float32Array
}

function makeRig(frameCount: number, rate = 1): Rig {
  const engine: StretchEngine = instantiateStretch(scalarBytes)
  engine.configure(RATE)
  const mix = new MixState({
    sampleRate: RATE,
    frameCount,
    sources: [{ channelCount: 2 }],
    engine,
  })
  if (rate !== 1) mix.setRate(rate)
  return { mix, outL: new Float32Array(QUANTUM), outR: new Float32Array(QUANTUM) }
}

function feed(rig: Rig, frames: number, phase0 = 0): void {
  rig.mix.enqueueChannels(0, [sine(frames, phase0), sine(frames, phase0, 0.5, 0.5)])
}

describe('MixState + stretch engine (real WASM)', () => {
  it('primes from seekLength frames and consumes 1:1 at 1x', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    const r0 = rig.mix.process(0, [rig.outL, rig.outR])
    // First quantum: prime (seekLength) + one demanded quantum.
    expect(r0.consumed).toBe(QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.15)
    expect(rig.mix.position).toBe(SEEK_1X + QUANTUM)
    for (let q = 1; q < 32; q++) rig.mix.process(q, [rig.outL, rig.outR])
    expect(rig.mix.position).toBe(SEEK_1X + 32 * QUANTUM)
  })

  it('consumes ≈2x source frames at 2x', () => {
    const rig = makeRig(120_000, 2)
    feed(rig, 120_000)
    let consumed = 0
    for (let q = 0; q < 375; q++) {
      consumed += rig.mix.process(q, [rig.outL, rig.outR]).consumed
    }
    const ratio = consumed / (375 * QUANTUM)
    expect(ratio).toBeGreaterThan(1.9)
    expect(ratio).toBeLessThan(2.05)
    expect(rms(rig.outL)).toBeGreaterThan(0.15)
  })

  it('consumes ≈0.5x source frames at 0.5x', () => {
    const rig = makeRig(48_000, 0.5)
    feed(rig, 48_000)
    let consumed = 0
    for (let q = 0; q < 375; q++) {
      consumed += rig.mix.process(q, [rig.outL, rig.outR]).consumed
    }
    const ratio = consumed / (375 * QUANTUM)
    expect(ratio).toBeGreaterThan(0.45)
    expect(ratio).toBeLessThan(0.58)
    expect(rms(rig.outL)).toBeGreaterThan(0.15)
  })

  it('ramps the rate smoothly (no silent quantum during the ramp)', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    for (let q = 0; q < 32; q++) rig.mix.process(q, [rig.outL, rig.outR])
    rig.mix.setRate(2)
    let minRms = Infinity
    for (let q = 32; q < 72; q++) {
      const r = rig.mix.process(q, [rig.outL, rig.outR])
      expect(r.consumed).toBeGreaterThan(0)
      minRms = Math.min(minRms, rms(rig.outL))
    }
    expect(minRms).toBeGreaterThan(0.1)
  })

  it('tracks consumed frames and anchors across rate changes', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    const anchors: number[] = []
    let total = 0
    for (let q = 0; q < 64; q++) {
      const r = rig.mix.process(q, [rig.outL, rig.outR])
      total += r.consumed
      if (r.anchor) anchors.push(r.anchor.frame)
    }
    // The first anchor reports the seek target (0), not the primed
    // cursor; subsequent anchors are strictly increasing.
    expect(anchors.length).toBeGreaterThan(1)
    expect(anchors[0]).toBe(0)
    for (let i = 1; i < anchors.length; i++) {
      expect(anchors[i]).toBeGreaterThan(anchors[i - 1])
    }
    expect(rig.mix.position).toBe(SEEK_1X + total)
  })

  it('re-primes after a seek and anchors the new target', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    for (let q = 0; q < 16; q++) rig.mix.process(q, [rig.outL, rig.outR])
    rig.mix.seek(24_000)
    // No data buffered yet: prime-wait silence, NOT an underrun.
    const r0 = rig.mix.process(16, [rig.outL, rig.outR])
    expect(r0.consumed).toBe(0)
    expect(r0.underrun).toBe(false)
    expect(rig.outL.every((v) => v === 0)).toBe(true)
    expect(rig.mix.position).toBe(24_000)
    // Refeed from the seek position: primes and plays in one quantum.
    feed(rig, 72_000, 24_000)
    const r1 = rig.mix.process(17, [rig.outL, rig.outR])
    expect(r1.consumed).toBe(QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.15)
    expect(r1.anchor?.frame).toBe(24_000)
    expect(rig.mix.position).toBe(24_000 + SEEK_1X + QUANTUM)
  })

  it('takes the underrun path when the demand is not met (2x)', () => {
    const rig = makeRig(96_000, 2)
    feed(rig, 100)
    const r0 = rig.mix.process(0, [rig.outL, rig.outR])
    expect(r0.consumed).toBe(0)
    expect(r0.underrun).toBe(true)
    expect(rig.mix.position).toBe(0)
    expect(rig.outL.every((v) => v === 0)).toBe(true)
    // Enough data: primes at the CURRENT effective rate (1x, since the
    // ramp only advances on process() calls → seekLength 5760), then
    // one demanded quantum.
    feed(rig, 90_000, 100)
    const r1 = rig.mix.process(1, [rig.outL, rig.outR])
    expect(r1.consumed).toBe(QUANTUM)
    expect(rig.mix.position).toBe(SEEK_1X + QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.1)
  })

  it('plays the synthesis tail after the source ends, then silence', () => {
    const rig = makeRig(6_000)
    feed(rig, 6_000)
    let endedCount = 0
    let firstTailRms = 0
    let silenceAt = -1
    for (let q = 0; q < 200; q++) {
      const r = rig.mix.process(q, [rig.outL, rig.outR])
      if (r.ended) endedCount++
      if (silenceAt < 0 && rig.mix.ended && q > 1) {
        if (q === 2) firstTailRms = rms(rig.outL)
        if (rms(rig.outL) < 1e-9) silenceAt = q
      }
    }
    expect(endedCount).toBe(1)
    expect(firstTailRms).toBeGreaterThan(0.05)
    expect(silenceAt).toBeGreaterThan(2)
    expect(silenceAt).toBeLessThan(200)
    // Stays silent once the tail is drained.
    rig.mix.process(200, [rig.outL, rig.outR])
    expect(rig.outL.every((v) => v === 0)).toBe(true)
  })

  it('primes with silence padding when the seek lands near the endpoint', () => {
    // seekLength (5760) > the 3000 frames left after the seek.
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    for (let q = 0; q < 16; q++) rig.mix.process(q, [rig.outL, rig.outR])
    rig.mix.seek(93_000)
    feed(rig, 3_000, 93_000)
    const r0 = rig.mix.process(16, [rig.outL, rig.outR])
    // Prime (3000 real + 2760 silence) + one padded quantum at the end.
    expect(r0.ended).toBe(true)
    expect(rig.mix.position).toBe(96_000)
    // Tail plays, then silence.
    let silence = false
    for (let q = 17; q < 200 && !silence; q++) {
      rig.mix.process(q, [rig.outL, rig.outR])
      if (rms(rig.outL) < 1e-9) silence = true
    }
    expect(silence).toBe(true)
  })

  it('pauses and resumes without re-priming', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    for (let q = 0; q < 8; q++) rig.mix.process(q, [rig.outL, rig.outR])
    const posBefore = rig.mix.position
    rig.mix.pause()
    for (let q = 8; q < 12; q++) {
      const r = rig.mix.process(q, [rig.outL, rig.outR])
      expect(r.consumed).toBe(0)
    }
    expect(rig.mix.position).toBe(posBefore)
    rig.mix.resume()
    const rR = rig.mix.process(12, [rig.outL, rig.outR])
    expect(rR.consumed).toBe(QUANTUM)
    expect(rig.mix.position).toBe(posBefore + QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.15)
  })

  it('applies the master gain after the stretcher (§11.1)', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000)
    for (let q = 0; q < 8; q++) rig.mix.process(q, [rig.outL, rig.outR])
    const rms1 = rms(rig.outL)
    rig.mix.setMasterGain(0.5)
    for (let q = 8; q < 13; q++) rig.mix.process(q, [rig.outL, rig.outR])
    const rms2 = rms(rig.outL)
    expect(rms2 / rms1).toBeGreaterThan(0.45)
    expect(rms2 / rms1).toBeLessThan(0.55)
  })
})

describe('PcmProcessor adapter (worklet scope)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('instantiates the engine, posts stretch-ready, and plays audio', async () => {
    const posted: Array<Record<string, unknown>> = []
    vi.stubGlobal(
      'AudioWorkletProcessor',
      class {
        port: {
          postMessage: (m: unknown) => void
          onmessage: ((e: { data: unknown }) => void) | null
        }
        constructor() {
          this.port = {
            postMessage: (m: unknown) => posted.push(m as Record<string, unknown>),
            onmessage: null,
          }
        }
        process(): boolean {
          return true
        }
      },
    )
    const reg = vi.fn()
    vi.stubGlobal('registerProcessor', reg)
    vi.resetModules()
    await import('../src/playback/worklet-processor.js')
    expect(reg).toHaveBeenCalledTimes(1)
    const Ctor = reg.mock.calls[0][1] as new (opts: {
      processorOptions: Record<string, unknown>
    }) => {
      port: { postMessage: (m: unknown) => void; onmessage: (e: { data: unknown }) => void }
      core: MixState
      process(time: number, input: unknown, output: Float32Array[]): boolean
    }
    const p = new Ctor({
      processorOptions: {
        sampleRate: RATE,
        frameCount: 96_000,
        sources: [{ channelCount: 2 }],
        stretch: { wasmBytes: scalarBytes },
      },
    })
    const ready = posted.find((m) => m.type === 'stretch-ready')
    expect(ready).toMatchObject({ inputLatency: 2880, outputLatency: 2880 })
    p.port.onmessage({
      data: { type: 'channels', source: 0, channels: [sine(96_000), sine(96_000, 0, 0.5, 0.5)] },
    })
    p.port.onmessage({ data: { type: 'rate', value: 2 } })
    let sawAudio = false
    for (let q = 0; q < 64; q++) {
      const o0 = new Float32Array(QUANTUM)
      const o1 = new Float32Array(QUANTUM)
      p.process(q, null, [o0, o1])
      if (rms(o0) > 0.1) sawAudio = true
    }
    expect(sawAudio).toBe(true)
    expect(p.core.position).toBeGreaterThan(9_000)
  })
})
