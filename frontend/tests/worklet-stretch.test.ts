/**
 * Worklet-core tests for the stretch integration (M2.10, spec §12).
 *
 * `MixState` driven with the REAL WASM engine and the rolling-seek
 * model: the exact 1× dry bypass (§12.4), the silent wet warm-up
 * (§12.3), aligned dry/wet crossfades, rate ramps, exact anchors, the
 * underrun path, EOF without an extra blank, pause/resume, and the
 * master gain after the stretcher (§11.1/§12.5). The final block loads
 * the worklet module in a faked worklet scope and drives the
 * `PcmProcessor` adapter end to end.
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MixState } from '../src/playback/worklet-processor.js'
import { instantiateStretch, type StretchEngine } from '../src/playback/stretch/stretch-host'

const RATE = 48_000
const QUANTUM = 128

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

/** A slow ramp: the sample value reads back the source frame. */
function ramp(n: number, phase0 = 0): Float32Array {
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) out[i] = (phase0 + i) * 0.0005
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

function makeRig(frameCount: number, engine = true): Rig {
  let stretch: StretchEngine | undefined
  if (engine) {
    stretch = instantiateStretch(scalarBytes)
    stretch.configure(RATE)
  }
  const mix = new MixState({
    sampleRate: RATE,
    frameCount,
    sources: [{ channelCount: 2 }],
    ...(stretch ? { engine: stretch } : {}),
  })
  return { mix, outL: new Float32Array(QUANTUM), outR: new Float32Array(QUANTUM) }
}

function feed(rig: Rig, frames: number, phase0 = 0, kind: 'sine' | 'ramp' = 'sine'): void {
  const make = kind === 'ramp' ? ramp : sine
  rig.mix.enqueueChannels(0, [make(frames, phase0), make(frames, phase0, 0.5, 0.5)])
}

/** Process `n` quanta; return the per-quantum output RMS trail. */
function runQuanta(rig: Rig, n: number, time0 = 0): number[] {
  const trail: number[] = []
  for (let q = 0; q < n; q++) {
    rig.mix.process(time0 + q * (QUANTUM / RATE), [rig.outL, rig.outR])
    trail.push(rms(rig.outL))
  }
  return trail
}

describe('MixState + stretch engine (real WASM, rolling model)', () => {
  it('bypasses bit-exactly at 1x: the engine rig equals the plain mixer (§12.4)', () => {
    const withEngine = makeRig(96_000)
    const plain = makeRig(96_000, false)
    feed(withEngine, 96_000, 0, 'ramp')
    feed(plain, 96_000, 0, 'ramp')
    for (let q = 0; q < 40; q++) {
      const t = q * (QUANTUM / RATE)
      withEngine.mix.process(t, [withEngine.outL, withEngine.outR])
      plain.mix.process(t, [plain.outL, plain.outR])
      expect(Array.from(withEngine.outL)).toEqual(Array.from(plain.outL))
      expect(Array.from(withEngine.outR)).toEqual(Array.from(plain.outR))
    }
    // The audible cursor is exact at 1×: 128 frames per quantum.
    expect(withEngine.mix.position).toBe(40 * QUANTUM)
    expect(plain.mix.position).toBe(40 * QUANTUM)
  })

  it('plays source frame 0 at the first quantum at 1x', () => {
    const rig = makeRig(96_000)
    feed(rig, 96_000, 0, 'ramp')
    rig.mix.process(0, [rig.outL, rig.outR])
    // The rig feeds a stereo source: center pan passes it through at gain 1.
    for (const i of [0, 1, 64, 127]) {
      expect(rig.outL[i]).toBeCloseTo(i * 0.0005, 6)
    }
  })

  it('warms a wet start inaudibly, then plays at full level (2x)', () => {
    const rig = makeRig(120_000)
    rig.mix.setRate(2)
    rig.mix.seek(0, 0, 24_000)
    feed(rig, 120_000)
    // The pre-roll fills the engine in ≤ 8-quantum batches: silent, and
    // the audible cursor does not move.
    for (let q = 0; q < 6; q++) {
      rig.mix.process(q, [rig.outL, rig.outR])
      expect(rms(rig.outL)).toBe(0)
      expect(rig.mix.position).toBe(24_000)
    }
    // Warm: audio at full level, cursor advancing at 2×.
    rig.mix.process(6, [rig.outL, rig.outR])
    expect(rms(rig.outL)).toBeGreaterThan(0.25)
    const pos = rig.mix.position
    rig.mix.process(7, [rig.outL, rig.outR])
    expect(rig.mix.position - pos).toBe(2 * QUANTUM)
  })

  it('keeps steady wet output and rate-correct cursors (2x and 0.5x)', () => {
    for (const rate of [2, 0.5]) {
      const rig = makeRig(120_000)
      rig.mix.setRate(rate)
      rig.mix.seek(0, 0, 24_000)
      feed(rig, 120_000)
      const trail = runQuanta(rig, 120)
      // After the warm-up, the sine stays at RMS ≈ 0.5/√2 × center.
      const steady = trail.slice(60)
      for (const v of steady) {
        expect(v).toBeGreaterThan(0.25)
        expect(v).toBeLessThan(0.45)
      }
      // Cursor advance per quantum equals the rate.
      const before = rig.mix.position
      rig.mix.process(200, [rig.outL, rig.outR])
      expect(rig.mix.position - before).toBe(Math.round(rate * QUANTUM))
    }
  })

  it('crossfades dry→wet at exactly 1x, then ramps (aligned transition, §12.4)', () => {
    const rig = makeRig(120_000)
    feed(rig, 120_000)
    const trail = runQuanta(rig, 40)
    const steady = trail[39]
    expect(steady).toBeGreaterThan(0.25)
    rig.mix.setRate(2)
    // The crossfade runs while the rate is still 1×: the dry and wet taps
    // carry the same signal, so the level holds (no combing).
    for (let q = 40; q < 43; q++) {
      rig.mix.process(q, [rig.outL, rig.outR])
      expect(rig.mix.rateCurrent).toBe(1)
      expect(rms(rig.outL)).toBeGreaterThan(0.8 * steady)
      expect(rms(rig.outL)).toBeLessThan(1.2 * steady)
    }
    // Then the rate ramps to 2× with no dropout.
    const rampTrail = runQuanta(rig, 40, 43)
    for (const v of rampTrail) {
      expect(v).toBeGreaterThan(0.15)
    }
    expect(rig.mix.rateCurrent).toBe(2)
    const before = rig.mix.position
    rig.mix.process(100, [rig.outL, rig.outR])
    expect(rig.mix.position - before).toBe(2 * QUANTUM)
  })

  it('ramps back to 1x before crossfading to dry (wet→dry)', () => {
    const rig = makeRig(120_000)
    rig.mix.setRate(2)
    rig.mix.seek(0, 0, 24_000)
    feed(rig, 120_000)
    const trail = runQuanta(rig, 100)
    const steady = trail[99]
    expect(steady).toBeGreaterThan(0.25)
    rig.mix.setRate(1)
    // The rate ramps to 1× first (~19 quanta for 50 ms); the output stays
    // wet and steady throughout.
    let q = 100
    while (rig.mix.rateCurrent > 1 && q < 140) {
      rig.mix.process(q++, [rig.outL, rig.outR])
      expect(rig.mix.wetGain).toBe(1)
      expect(rms(rig.outL)).toBeGreaterThan(0.8 * steady)
    }
    expect(rig.mix.rateCurrent).toBe(1)
    // Then the crossfade to dry; afterwards the 1× bypass is exact.
    while (rig.mix.dryGain < 1 && q < 150) {
      rig.mix.process(q++, [rig.outL, rig.outR])
    }
    expect(rig.mix.dryGain).toBe(1)
    expect(rig.mix.wetGain).toBe(0)
    const before = rig.mix.position
    rig.mix.process(q, [rig.outL, rig.outR])
    expect(rig.mix.position - before).toBe(QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.25)
  })

  it('anchors exact (frame, time) pairs with the ramped rate (§12.7)', () => {
    const rig = makeRig(120_000)
    rig.mix.setRate(2)
    rig.mix.seek(0, 0, 24_000)
    feed(rig, 120_000)
    const anchors: Array<{ frame: number; time: number; rate: number }> = []
    for (let q = 0; q < 80; q++) {
      const t = q * (QUANTUM / RATE)
      const r = rig.mix.process(t, [rig.outL, rig.outR])
      if (r.anchor) anchors.push(r.anchor)
    }
    expect(anchors.length).toBeGreaterThan(2)
    for (const a of anchors) {
      expect(a.rate).toBeGreaterThan(1.9)
      expect(a.frame).toBeGreaterThanOrEqual(24_000)
    }
    // Exact pairs: consecutive anchors advance at rate × elapsed time.
    for (let i = 1; i < anchors.length; i++) {
      const frames = anchors[i].frame - anchors[i - 1].frame
      const seconds = anchors[i].time - anchors[i - 1].time
      expect(frames).toBeCloseTo(seconds * RATE * anchors[i].rate, 0)
    }
  })

  it('takes the underrun path when the context window cannot be filled', () => {
    const rig = makeRig(96_000)
    feed(rig, 100)
    const r0 = rig.mix.process(0, [rig.outL, rig.outR])
    expect(r0.underrun).toBe(true)
    expect(rig.mix.position).toBe(0)
    expect(rig.outL.every((v) => v === 0)).toBe(true)
    // Enough data: the window fills and playback starts at 1× exactly.
    feed(rig, 96_000, 100)
    const r1 = rig.mix.process(1, [rig.outL, rig.outR])
    expect(r1.underrun).toBe(false)
    expect(rig.mix.position).toBe(QUANTUM)
    expect(rms(rig.outL)).toBeGreaterThan(0.25)
  })

  it('ends at the endpoint without an extra blank (EOF, §12.6)', () => {
    const rig = makeRig(6_000)
    feed(rig, 6_000)
    let endedCount = 0
    const trail: number[] = []
    for (let q = 0; q < 60; q++) {
      const r = rig.mix.process(q, [rig.outL, rig.outR])
      if (r.ended) endedCount++
      trail.push(rms(rig.outL))
    }
    expect(endedCount).toBe(1)
    // Every quantum up to the end carries audio; then silence.
    expect(trail[45]).toBeGreaterThan(0.25)
    expect(trail[47]).toBeLessThan(1e-9)
    expect(rig.mix.position).toBe(6_000)
    // No extra blank: silence stays silence.
    rig.mix.process(60, [rig.outL, rig.outR])
    expect(rig.outL.every((v) => v === 0)).toBe(true)
  })

  it('pauses and resumes without re-warming (wet)', () => {
    const rig = makeRig(120_000)
    rig.mix.setRate(2)
    rig.mix.seek(0, 0, 24_000)
    feed(rig, 120_000)
    runQuanta(rig, 60)
    const posBefore = rig.mix.position
    rig.mix.pause()
    for (let q = 60; q < 64; q++) rig.mix.process(q, [rig.outL, rig.outR])
    expect(rig.mix.position).toBe(posBefore)
    rig.mix.resume()
    const trail = runQuanta(rig, 8, 64)
    // The engine stayed warm: audio resumes immediately at full level.
    expect(trail[1]).toBeGreaterThan(0.25)
    expect(rig.mix.position).toBeGreaterThan(posBefore)
  })

  it('applies the master gain after the stretcher at 2x (§11.1/§12.5)', () => {
    const rig = makeRig(120_000)
    rig.mix.setRate(2)
    rig.mix.seek(0, 0, 24_000)
    feed(rig, 120_000)
    runQuanta(rig, 80)
    const steady = rms(rig.outL)
    rig.mix.setMasterGain(0.5)
    runQuanta(rig, 5, 80)
    const quieter = rms(rig.outL)
    expect(quieter / steady).toBeGreaterThan(0.45)
    expect(quieter / steady).toBeLessThan(0.55)
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
      process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean
    }
    const p = new Ctor({
      processorOptions: {
        sampleRate: RATE,
        frameCount: 120_000,
        sources: [{ channelCount: 2 }],
        stretch: { wasmBytes: scalarBytes },
      },
    })
    const ready = posted.find((m) => m.type === 'stretch-ready')
    expect(ready).toMatchObject({ inputLatency: 2880, outputLatency: 2880 })
    p.port.onmessage({ data: { type: 'rate', value: 2 } })
    p.port.onmessage({ data: { type: 'seek', frame: 0, audibleFrame: 24_000, generation: 0 } })
    p.port.onmessage({
      data: { type: 'channels', source: 0, channels: [sine(120_000), sine(120_000, 0, 0.5, 0.5)] },
    })
    let sawAudio = false
    for (let q = 0; q < 80; q++) {
      const o0 = new Float32Array(QUANTUM)
      const o1 = new Float32Array(QUANTUM)
      ;(globalThis as { currentTime?: number }).currentTime = q
      p.process([], [[o0, o1]])
      if (rms(o0) > 0.1) sawAudio = true
    }
    expect(sawAudio).toBe(true)
    expect(p.core.position).toBeGreaterThan(24_000 + 9_000)
    // Anchors carry the ramped rate (§12.7).
    const anchors = posted.filter((m) => m.type === 'anchor')
    expect(anchors.length).toBeGreaterThan(0)
    for (const a of anchors) {
      expect(a.rate).toBeGreaterThan(1)
    }
    // The pre-roll was fed (the seek message is the audible boundary).
    expect(p.core.position).toBeLessThan(120_000)
  })
})
