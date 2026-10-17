/**
 * Worklet-core tests for the practice loop (M2.11, spec §13).
 *
 * `MixState` renders the periodic loop stream fed by the transport: pass
 * counting, exact wrap anchors, the join fades (§13.6), the
 * finite-repeat stop (§13.4.6), enabling mid-stream without a re-seek
 * (§13.4.3), and the acceptance that the pass boundaries never drift at
 * 0.25×–2× (§13.7.5). The final block drives the `PcmProcessor` adapter
 * protocol (`seek` with a loop, the `loop` message, `loop-complete`).
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MixState } from '../src/playback/worklet-processor.js'
import { instantiateStretch, type StretchEngine } from '../src/playback/stretch/stretch-host'

const RATE = 48_000
const QUANTUM = 128
const PRE_ROLL = 12_288
const LOOP_START = 100_000
const LOOP_END = 104_800
const LOOP_LEN = LOOP_END - LOOP_START

// Vitest runs with the frontend/ directory as cwd.
const dist = path.resolve('src/playback/stretch/dist')
const scalarBytes = readFileSync(path.join(dist, 'stretch-scalar.wasm'))

/** A slow ramp: the sample value reads back the stream frame. */
function ramp(n: number, phase0 = 0): Float32Array {
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) out[i] = (phase0 + i) * 0.0005
  return out
}

interface Rig {
  mix: MixState
  outL: Float32Array
  outR: Float32Array
}

function makeRig(frameCount: number, engine = false): Rig {
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

function feedRamp(rig: Rig, frames: number, phase0 = 0): void {
  rig.mix.enqueueChannels(0, [ramp(frames, phase0), ramp(frames, phase0)])
}

function feedZeros(rig: Rig, frames: number): void {
  const zeros = new Float32Array(frames)
  rig.mix.enqueueChannels(0, [zeros, zeros])
}

interface LoopOverrides {
  start?: number
  end?: number
  repeatCount?: number | null
  fade?: boolean
}

function loopSpec(over: LoopOverrides = {}) {
  return { start: 0, end: 4800, repeatCount: null, fade: true, ...over }
}

/** Render `n` quanta; return the contiguous output and the anchors. */
function render(rig: Rig, n: number, time0 = 0) {
  const out = new Float32Array(n * QUANTUM)
  const anchors: NonNullable<ReturnType<MixState['process']>['anchor']>[] = []
  let completions = 0
  for (let q = 0; q < n; q++) {
    const res = rig.mix.process(time0 + q * (QUANTUM / RATE), [rig.outL, rig.outR])
    if (res.anchor) anchors.push(res.anchor)
    if (res.loopComplete) completions += 1
    out.set(rig.outL, q * QUANTUM)
  }
  return { out, anchors, completions }
}

describe('MixState practice loop (plain path)', () => {
  it('counts passes and anchors the exact crossing frames (§13.7.5)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, loopSpec())
    feedRamp(rig, 100_000)
    const { anchors } = render(rig, 200) // 25 600 frames
    const wraps = anchors.filter((a) => a.wrap === true)
    expect(wraps.map((a) => a.frame)).toEqual([4800, 9600, 14_400, 19_200, 24_000])
    expect(rig.mix.loopPasses).toBe(5)
    for (const a of wraps) expect(a.time).toBeCloseTo(a.frame / RATE, 9)
  })

  it('fades the join with a 5 ms notch and preserves duration (§13.6)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, loopSpec())
    feedRamp(rig, 100_000)
    expect(rig.mix.loopFadeFrames(1)).toBe(240)
    const { out } = render(rig, 60) // past the crossing at 4800
    const gainAt = (f: number) => out[f] / (f * 0.0005)
    expect(gainAt(4560)).toBeCloseTo(1, 5) // center − fade
    expect(gainAt(4680)).toBeCloseTo(0.5, 5) // center − fade/2
    expect(Math.abs(out[4800])).toBeLessThan(1e-9) // zero at the join
    expect(gainAt(4920)).toBeCloseTo(0.5, 5) // center + fade/2
    expect(gainAt(5040)).toBeCloseTo(1, 5) // center + fade
    // The pass length in output frames is exactly the loop length: the
    // join consumes no extra time and drops no samples.
    expect(out[4560]).toBeCloseTo(4560 * 0.0005, 5)
    expect(out[5040]).toBeCloseTo(5040 * 0.0005, 5)
  })

  it('leaves the audio untouched when the boundary fade is off (§13.6.4)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, loopSpec({ fade: false }))
    const content = ramp(100_000)
    rig.mix.enqueueChannels(0, [content, content])
    expect(rig.mix.loopFadeFrames(1)).toBe(0)
    const { out } = render(rig, 60)
    for (let f = 4700; f < 4900; f++) expect(out[f]).toBe(content[f])
  })

  it('caps the fade to a quarter of short loops (§13.6.2)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, loopSpec({ start: 0, end: 600 })) // 12.5 ms
    expect(rig.mix.loopFadeFrames(1)).toBe(150) // min(240, 600/4)
    expect(rig.mix.loopFadeFrames(2)).toBe(75) // min(240, 600/2/4)
    rig.mix.setLoop(loopSpec({ start: 0, end: 4800 }))
    expect(rig.mix.loopFadeFrames(1)).toBe(240) // 5 ms cap wins
    expect(rig.mix.loopFadeFrames(2)).toBe(240)
    rig.mix.setLoop(loopSpec({ fade: false }))
    expect(rig.mix.loopFadeFrames(1)).toBe(0)
  })

  it('stops exactly at the loop end after the configured passes (§13.4.6)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, loopSpec({ repeatCount: 3 }))
    feedRamp(rig, 100_000)
    const { out, anchors, completions } = render(rig, 200)
    // Two wrap anchors, then the completion anchor at the final pass end.
    const wraps = anchors.filter((a) => a.wrap === true)
    expect(wraps.map((a) => a.frame)).toEqual([4800, 9600])
    expect(completions).toBe(1)
    const finalAnchor = anchors.find((a) => a.frame === 14_400 && a.wrap !== true)
    expect(finalAnchor).toBeDefined()
    expect(finalAnchor!.time).toBeCloseTo(14_400 / RATE, 9)
    expect(rig.mix.loopComplete).toBe(true)
    expect(rig.mix.loopPasses).toBe(3)
    expect(rig.mix.position).toBe(14_400)
    // Silence after the boundary; the completion fires exactly once.
    for (let f = 14_400; f < out.length; f++) expect(out[f]).toBe(0)
  })

  it('counts a partial first pass (enabled mid-loop) as pass 1 (§13.4.2)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 2000, loopSpec({ repeatCount: 1 }))
    feedRamp(rig, 100_000, 2000)
    const { anchors, completions } = render(rig, 40)
    // The single pass ends at 4800 and is final: a completion anchor.
    expect(anchors.filter((a) => a.wrap === true)).toEqual([])
    const finalAnchor = anchors.find((a) => a.frame === 4800)
    expect(finalAnchor).toBeDefined()
    expect(completions).toBe(1)
    // The partial pass runs from the enable position to the loop end.
    expect(finalAnchor!.time).toBeCloseTo((4800 - 2000) / RATE, 9)
    expect(rig.mix.loopPasses).toBe(1)
  })

  it('enables mid-stream without a re-seek and resets on disable (§13.4.3)', () => {
    const rig = makeRig(200_000)
    rig.mix.seek(0, 0, 0, null) // linear playback
    feedRamp(rig, 100_000)
    for (let q = 0; q < 10; q++) {
      rig.mix.process(q * (QUANTUM / RATE), [rig.outL, rig.outR])
    }
    expect(rig.mix.position).toBe(1280)
    rig.mix.setLoop(loopSpec()) // enable inside [0, 4800)
    expect(rig.mix.loopPasses).toBe(0)
    const wraps: number[] = []
    for (let q = 10; q < 100; q++) {
      const res = rig.mix.process(q * (QUANTUM / RATE), [rig.outL, rig.outR])
      if (res.anchor?.wrap) wraps.push(res.anchor.frame)
    }
    expect(wraps).toEqual([4800, 9600])
    rig.mix.setLoop(null)
    expect(rig.mix.loopPasses).toBe(0)
    // The stream is linear again: no wrap anchor at the boundary.
    const before = rig.mix.position
    const res = rig.mix.process(100 * (QUANTUM / RATE), [rig.outL, rig.outR])
    expect(res.anchor?.wrap).not.toBe(true)
    expect(rig.mix.position).toBe(before + QUANTUM)
  })
})

describe('practice loop: no cumulative drift at 0.25x-2x (spec §13.7.5)', () => {
  for (const rate of [0.25, 0.5, 0.75, 1, 1.5, 2]) {
    it(`keeps pass boundaries exact at ${rate}x`, () => {
      const rig = makeRig(2_000_000, true)
      rig.mix.setRate(rate)
      rig.mix.seek(LOOP_START - PRE_ROLL, 0, LOOP_START, {
        start: LOOP_START,
        end: LOOP_END,
        repeatCount: null,
        fade: true,
      })
      feedZeros(rig, 300_000)
      const wraps: { frame: number; time: number }[] = []
      const QUANTA = 4000
      for (let q = 0; q < QUANTA; q++) {
        if (rig.mix.buffered < 200_000) feedZeros(rig, 300_000)
        const res = rig.mix.process(q * (QUANTUM / RATE), [rig.outL, rig.outR])
        if (res.anchor?.wrap) wraps.push(res.anchor)
      }
      expect(wraps.length).toBeGreaterThan(5)
      expect(rig.mix.loopPasses).toBe(wraps.length)
      // Exact crossing frames: LOOP_END + k * LOOP_LEN, never drifting.
      wraps.forEach((a, k) => expect(a.frame).toBe(LOOP_END + k * LOOP_LEN))
      // Exact cumulative duration: k passes take exactly
      // k * len / (rate * sampleRate) seconds — no per-iteration
      // rounding accumulates (the fractional remainder carries over).
      const perPass = LOOP_LEN / (rate * RATE)
      wraps.forEach((a, k) => {
        expect(a.time - wraps[0].time).toBeCloseTo(k * perPass, 9)
      })
    })
  }
})

describe('PcmProcessor loop protocol (worklet scope)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function bootProcessor(frameCount: number) {
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
        frameCount,
        sources: [{ channelCount: 2 }],
        stretch: { wasmBytes: scalarBytes },
      },
    })
    let q = 0
    const run = (n: number) => {
      for (let i = 0; i < n; i++) {
        ;(globalThis as { currentTime?: number }).currentTime = q * (QUANTUM / RATE)
        const o0 = new Float32Array(QUANTUM)
        const o1 = new Float32Array(QUANTUM)
        p.process([], [[o0, o1]])
        q += 1
      }
    }
    return { p, posted, run }
  }

  it('posts loop-complete with the exact pass end after the passes (§13.4.6)', async () => {
    const { p, posted, run } = await bootProcessor(200_000)
    p.port.onmessage({
      data: {
        type: 'seek',
        frame: 0,
        audibleFrame: 0,
        generation: 0,
        loop: { start: 0, end: 4800, repeatCount: 2, fade: true },
      },
    })
    p.port.onmessage({
      data: { type: 'channels', source: 0, channels: [ramp(200_000), ramp(200_000)] },
    })
    run(130)
    const completes = posted.filter((m) => m.type === 'loop-complete')
    expect(completes.length).toBe(1)
    expect(completes[0].frame).toBe(9600)
    expect(completes[0].time).toBeCloseTo(9600 / RATE, 9)
    // The wrap anchor at the first pass end is posted with the marker.
    const wraps = posted.filter((m) => m.type === 'anchor' && m.wrap === true)
    expect(wraps.map((m) => m.frame)).toEqual([4800])
    // The loop path never emits `ended`.
    expect(posted.some((m) => m.type === 'ended')).toBe(false)
  })

  it('enables and disables mid-stream through the loop message (§13.4.3)', async () => {
    const { p, posted, run } = await bootProcessor(200_000)
    p.port.onmessage({ data: { type: 'seek', frame: 0, audibleFrame: 0, generation: 0 } })
    p.port.onmessage({
      data: { type: 'channels', source: 0, channels: [ramp(200_000), ramp(200_000)] },
    })
    run(10)
    expect(p.core.loopPasses).toBe(0)
    // Enable inside the loop: the first (partial) pass ends at 4800.
    p.port.onmessage({
      data: { type: 'loop', loop: { start: 0, end: 4800, repeatCount: 1, fade: true } },
    })
    run(40)
    expect(p.core.loopComplete).toBe(true)
    const completes = posted.filter((m) => m.type === 'loop-complete')
    expect(completes.length).toBe(1)
    expect(completes[0].frame).toBe(4800)
    // Disabling clears the loop state; the linear stream continues.
    p.port.onmessage({ data: { type: 'loop', loop: null } })
    expect(p.core.loopComplete).toBe(false)
    const before = p.core.position
    run(5)
    expect(p.core.position).toBe(before + 5 * QUANTUM)
    expect(posted.filter((m) => m.type === 'loop-complete').length).toBe(1)
  })
})
