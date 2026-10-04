/**
 * Unit tests for the pure canvas painters (M1.10, plan §9).
 *
 * A `RecordingContext` stands in for the 2D context: it records every
 * call and property write, so the tests assert geometry (where fill
 * rectangles land) without a real canvas — jsdom has no 2D context.
 */
import { describe, expect, it } from 'vitest'
import {
  drawLaneGrid,
  drawLaneWaveform,
  drawOverview,
  drawPlayhead,
  drawPcmWaveform,
  drawRuler,
  drawSamplePoints,
  GRID_COLOR,
  PLAYHEAD_COLOR,
  RULER_COLOR,
  WAVEFORM_COLOR,
  type BucketSource,
  type WaveformContext,
} from '../src/waveform/render'
import { fitViewport, makeViewport } from '../src/waveform/viewport'

interface Call {
  fn: string
  args: (number | string)[]
}

class RecordingContext implements WaveformContext {
  calls: Call[] = []
  fillStyle = ''
  strokeStyle = ''
  lineWidth = 1
  font = ''
  textBaseline = ''

  record(fn: string, args: (number | string)[]): void {
    this.calls.push({ fn, args })
  }

  fillRect(x: number, y: number, w: number, h: number): void {
    this.record('fillRect', [x, y, w, h])
  }
  clearRect(x: number, y: number, w: number, h: number): void {
    this.record('clearRect', [x, y, w, h])
  }
  beginPath(): void {
    this.record('beginPath', [])
  }
  moveTo(x: number, y: number): void {
    this.record('moveTo', [x, y])
  }
  lineTo(x: number, y: number): void {
    this.record('lineTo', [x, y])
  }
  stroke(): void {
    this.record('stroke', [])
  }
  fill(): void {
    this.record('fill', [])
  }
  save(): void {
    this.record('save', [])
  }
  restore(): void {
    this.record('restore', [])
  }
  translate(x: number, y: number): void {
    this.record('translate', [x, y])
  }
  fillText(text: string, x: number, y: number): void {
    this.record('fillText', [x, y, text])
  }

  fillRects(): number[][] {
    return this.calls.filter((c) => c.fn === 'fillRect').map((c) => c.args as number[])
  }
}

/** A flat 16-bucket level where bucket `b` spans `[-0.5 + b/16, +0.5 + b/16]`-ish. */
function bucketSource(
  bfc: number,
  bucketCount: number,
  ext?: (b: number) => [number, number] | null,
): BucketSource {
  return {
    bucketFrameCount: bfc,
    bucketCount,
    bucketAt: (b) => ext?.(b) ?? [0.25, 0.75],
  }
}

describe('drawLaneWaveform', () => {
  it('lands fill columns at the x of the bucket frames (alignment)', () => {
    // 256 frames over 128 px -> 2 frames/px; bfc 2 -> exactly 1 bucket/px.
    const vp = fitViewport(256, 128)
    const ctx = new RecordingContext()
    drawLaneWaveform(ctx, bucketSource(2, 128), vp, 0, 128, { height: 64 })
    const rects = ctx.fillRects()
    // Bucket 5 covers frames [10, 12) -> x [10, 12) -> columns 10 and 11.
    const at10 = rects.find((r) => r[0] === 10 && r[2] === 1)
    const at11 = rects.find((r) => r[0] === 11 && r[2] === 1)
    expect(at10).toBeDefined()
    expect(at11).toBeDefined()
    // min 0.25 / max 0.75 at scale 1 in a 64 px lane:
    // yTop = 32 - 0.75*32 = 8, yBottom = 32 - 0.25*32 = 24.
    expect(at10![1]).toBe(8)
    expect(at10![3]).toBe(16)
  })

  it('leaves columns blank past the bucket data', () => {
    // 100 frames over 100 px, but only 10 buckets (20 frames) of data.
    const vp = fitViewport(100, 100)
    const ctx = new RecordingContext()
    drawLaneWaveform(ctx, bucketSource(2, 10), vp, 0, 100, { height: 32 })
    const xs = ctx.fillRects().map((r) => r[0])
    expect(xs).not.toContain(20)
    expect(xs).not.toContain(99)
    expect(xs).toContain(0)
  })

  it('draws a 1px zero line for silent pixels', () => {
    const vp = fitViewport(8, 8)
    const ctx = new RecordingContext()
    drawLaneWaveform(
      ctx,
      bucketSource(1, 8, () => [0, 0]),
      vp,
      0,
      8,
      { height: 40 },
    )
    const rect = ctx.fillRects()[0]
    expect(rect).toEqual([0, 20, 1, 1])
  })

  it('clamps beyond-scale extrema and marks clip ticks at the lane edge', () => {
    const vp = fitViewport(4, 4)
    const ctx = new RecordingContext()
    drawLaneWaveform(
      ctx,
      bucketSource(1, 4, () => [1, 1]),
      vp,
      0,
      4,
      {
        height: 40,
        amplitudeScale: 2,
      },
    )
    const rects = ctx.fillRects()
    // Main column clamps to the top edge (y 0), 1 px wide.
    const main = rects.find((r) => r[0] === 0 && r[1] === 0 && r[2] === 1 && r[3] > 1)
    expect(main).toBeDefined()
    // Clip tick: 2 px tall at the very top of the lane.
    const tick = rects.find((r) => r[0] === 0 && r[1] === 0 && r[3] === 2)
    expect(tick).toBeDefined()
  })

  it('marks a bottom clip tick for negative beyond-scale extrema', () => {
    const vp = fitViewport(2, 2)
    const ctx = new RecordingContext()
    drawLaneWaveform(
      ctx,
      bucketSource(1, 2, () => [-1, -1]),
      vp,
      0,
      2,
      {
        height: 40,
        amplitudeScale: 4,
      },
    )
    const tick = ctx.fillRects().find((r) => r[1] === 38 && r[3] === 2)
    expect(tick).toBeDefined()
  })

  it('applies the amplitude scale to column height', () => {
    const vp = fitViewport(2, 2)
    const ctx = new RecordingContext()
    drawLaneWaveform(
      ctx,
      bucketSource(1, 2, () => [0, 0.5]),
      vp,
      0,
      2,
      {
        height: 40,
        amplitudeScale: 2,
      },
    )
    // max 0.5 * scale 2 = 1.0 -> yTop = 0; min 0 -> yBottom = 20.
    const rect = ctx.fillRects()[0]
    expect(rect[1]).toBe(0)
    expect(rect[3]).toBe(20)
  })
})

describe('drawPcmWaveform', () => {
  it('aligns pixel p to x = p for a zero-offset source', () => {
    const vp = fitViewport(64, 64)
    const ctx = new RecordingContext()
    drawPcmWaveform(
      ctx,
      {
        startFrame: 0,
        pixelCount: 64,
        pixelAt: (p) => (p === 7 ? [0.2, 0.8] : [0, 0]),
      },
      vp,
      0,
      64,
      { height: 20 },
    )
    const rect = ctx.fillRects().find((r) => r[0] === 7)
    // min 0.2 / max 0.8 in a 20 px lane: yTop = 10 - 0.8*10 = 2, height 6.
    expect(rect).toEqual([7, 2, 1, 6])
  })

  it('skips pixels outside the source range', () => {
    const vp = fitViewport(64, 64)
    const ctx = new RecordingContext()
    drawPcmWaveform(ctx, { startFrame: 0, pixelCount: 10, pixelAt: () => [0.1, 0.1] }, vp, 0, 64, {
      height: 20,
    })
    const xs = ctx.fillRects().map((r) => r[0])
    expect(xs).toContain(0)
    expect(xs).toContain(9)
    expect(xs).not.toContain(10)
    expect(xs).not.toContain(63)
  })
})

describe('drawSamplePoints', () => {
  it('strokes one point per visible sample', () => {
    const vp = makeViewport(0, 0.5, 100) // 50 frames across 100 px
    const samples = new Float32Array([0, 0.5, -0.5, 1, 0])
    const ctx = new RecordingContext()
    drawSamplePoints(ctx, { startFrame: 0, samples }, vp, 0, 100, { height: 40 })
    const moves = ctx.calls.filter((c) => c.fn === 'moveTo')
    const lines = ctx.calls.filter((c) => c.fn === 'lineTo')
    expect(moves).toHaveLength(1)
    expect(lines).toHaveLength(4)
    expect(ctx.calls.filter((c) => c.fn === 'stroke')).toHaveLength(1)
    // Sample 0 (0) at frame 0 -> x 0, y = 20.
    expect(moves[0].args).toEqual([0, 20])
    // Sample 1 (0.5) at frame 1 -> x 2, y = 20 - 0.5*20 = 10.
    expect(lines[0].args).toEqual([2, 10])
  })

  it('draws nothing when no sample is in range', () => {
    const vp = makeViewport(1000, 0.5, 100)
    const ctx = new RecordingContext()
    drawSamplePoints(ctx, { startFrame: 0, samples: new Float32Array(10) }, vp, 0, 100, {
      height: 40,
    })
    expect(ctx.calls.filter((c) => c.fn === 'stroke')).toHaveLength(0)
  })
})

describe('drawRuler', () => {
  it('places ticks within the width with a nice step', () => {
    // 240000 frames (5 s @ 48 kHz) across 500 px -> 480 fpp.
    const vp = fitViewport(240_000, 500)
    const ctx = new RecordingContext()
    drawRuler(ctx, vp, 500, { sampleRate: 48000, height: 20 })
    // Step: 56 px * (480/48000 s) = 0.56 s -> nice step 1 s -> 6 ticks.
    const ticks = ctx.calls.filter((c) => c.fn === 'moveTo' && (c.args as number[])[1] === 14)
    expect(ticks).toHaveLength(6)
    const xs = ticks.map((c) => (c.args as number[])[0])
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(0)
      // 1px lines are half-pixel aligned; the end tick may sit half a
      // pixel past the right edge (clipped by the canvas).
      expect(x).toBeLessThanOrEqual(500.5)
    }
    // 1 s ticks at 100 px apart: 0.5, 100.5, ... 500.5.
    expect(xs[0]).toBe(0.5)
    expect(xs[1]).toBe(100.5)
  })

  it('keeps labels at least minLabelGap apart and uses ms for sub-second steps', () => {
    // 4800 frames (0.1 s) across 480 px -> 10 fpp -> 0.2 ms/px.
    const vp = fitViewport(4800, 480)
    const ctx = new RecordingContext()
    drawRuler(ctx, vp, 480, { sampleRate: 48000, height: 20, minLabelGap: 56 })
    // Target 56 px * (10/48000) s = 0.0117 s -> step 0.02 s (20 ms).
    const labels = ctx.calls.filter((c) => c.fn === 'fillText')
    expect(labels.length).toBeGreaterThan(2)
    const xs = labels.map((c) => (c.args as number[])[0])
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(56 - 1)
    }
    // Sub-second labels carry milliseconds: "0:00.020".
    const firstLabel = labels[0].args[2] as string
    expect(firstLabel).toMatch(/^0:\d{2}\.\d{3}$/)
  })

  it('throws for a non-positive sample rate', () => {
    const vp = fitViewport(1000, 100)
    expect(() => drawRuler(new RecordingContext(), vp, 100, { sampleRate: 0, height: 20 })).toThrow(
      RangeError,
    )
  })
})

describe('drawPlayhead', () => {
  it('strokes a 1px vertical line at the rounded x', () => {
    const ctx = new RecordingContext()
    drawPlayhead(ctx, 123.4, 64)
    expect(ctx.strokeStyle).toBe(PLAYHEAD_COLOR)
    const move = ctx.calls.find((c) => c.fn === 'moveTo')
    const line = ctx.calls.find((c) => c.fn === 'lineTo')
    expect(move?.args).toEqual([123.5, 0])
    expect(line?.args).toEqual([123.5, 64])
    expect(ctx.calls.filter((c) => c.fn === 'stroke')).toHaveLength(1)
  })
})

describe('drawLaneGrid', () => {
  it('strokes the zero line centered in the lane', () => {
    const ctx = new RecordingContext()
    drawLaneGrid(ctx, 200, 41)
    expect(ctx.strokeStyle).toBe(GRID_COLOR)
    const move = ctx.calls.find((c) => c.fn === 'moveTo')
    const line = ctx.calls.find((c) => c.fn === 'lineTo')
    // 41px lane: center 20.5 -> half-pixel line at 21.5.
    expect(move?.args).toEqual([0, 21.5])
    expect(line?.args).toEqual([200, 21.5])
  })
})

describe('drawOverview', () => {
  it('stacks one mini lane per channel with a translate per lane', () => {
    const ctx = new RecordingContext()
    const l = bucketSource(64, 100)
    drawOverview(ctx, [l, l], 200, 40)
    const translates = ctx.calls.filter((c) => c.fn === 'translate')
    expect(translates.map((c) => c.args)).toEqual([
      [0, 0],
      [0, 20],
    ])
    expect(ctx.calls.filter((c) => c.fn === 'save')).toHaveLength(2)
    expect(ctx.calls.filter((c) => c.fn === 'restore')).toHaveLength(2)
    // The mini lanes use the overview color.
    const fills = ctx.calls.filter((c) => c.fn === 'fillRect')
    expect(fills.length).toBeGreaterThan(0)
  })

  it('uses the waveform color by default on lanes', () => {
    const ctx = new RecordingContext()
    const vp = fitViewport(8, 8)
    drawLaneWaveform(ctx, bucketSource(1, 8), vp, 0, 8, { height: 32 })
    expect(ctx.fillStyle).toBe(WAVEFORM_COLOR)
    expect(RULER_COLOR).toBe('#9aa7b4')
  })
})
