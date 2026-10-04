import { describe, expect, it } from 'vitest'
import {
  clampFpp,
  clampView,
  fitRangeView,
  fitViewport,
  frameToX,
  makeViewport,
  MIN_FPP,
  panView,
  visibleFrameRange,
  visibleFrames,
  xToFrame,
  zoomView,
} from '../src/waveform/viewport'

describe('makeViewport', () => {
  it('stores the three coordinates', () => {
    const v = makeViewport(100.5, 0.25, 400)
    expect(v).toEqual({ startFrame: 100.5, framesPerCssPixel: 0.25, widthCssPx: 400 })
  })

  it('rejects invalid coordinates', () => {
    expect(() => makeViewport(-1, 1, 100)).toThrow(RangeError)
    expect(() => makeViewport(0, 0, 100)).toThrow(RangeError)
    expect(() => makeViewport(0, -1, 100)).toThrow(RangeError)
    expect(() => makeViewport(0, 1, 0)).toThrow(RangeError)
  })
})

describe('fitViewport', () => {
  it('fits the whole source into the width', () => {
    const v = fitViewport(48000, 800)
    expect(v.startFrame).toBe(0)
    expect(v.framesPerCssPixel).toBe(60)
    expect(v.widthCssPx).toBe(800)
  })

  it('keeps fractional frames-per-pixel', () => {
    const v = fitViewport(100, 3)
    expect(v.framesPerCssPixel).toBeCloseTo(100 / 3)
  })

  it('rejects empty inputs', () => {
    expect(() => fitViewport(0, 100)).toThrow(RangeError)
    expect(() => fitViewport(100, 0)).toThrow(RangeError)
  })
})

describe('frameToX / xToFrame', () => {
  const v = makeViewport(100.5, 0.25, 400)

  it('maps the start frame to x = 0', () => {
    expect(frameToX(v, 100.5)).toBe(0)
  })

  it('maps frames to CSS pixels (x = (frame - start) / fpp)', () => {
    expect(frameToX(v, 101)).toBe(2)
    expect(frameToX(v, 102.5)).toBe(8)
  })

  it('maps pixels back to frames (frame = start + x * fpp)', () => {
    expect(xToFrame(v, 0)).toBe(100.5)
    expect(xToFrame(v, 2)).toBe(101)
    expect(xToFrame(v, 400)).toBe(200.5)
  })

  it('round-trips fractional coordinates', () => {
    for (const frame of [100.5, 150.25, 199.999]) {
      expect(xToFrame(v, frameToX(v, frame))).toBeCloseTo(frame)
    }
  })
})

describe('visibleFrameRange', () => {
  it('covers the viewport with whole frames', () => {
    const v = makeViewport(100.5, 0.25, 400)
    expect(visibleFrameRange(v, 10000)).toEqual([100, 201])
  })

  it('clamps to the source duration', () => {
    const v = makeViewport(100.5, 0.25, 400)
    expect(visibleFrameRange(v, 150)).toEqual([100, 150])
  })

  it('clamps to frame zero at the start', () => {
    const v = fitViewport(48000, 800)
    expect(visibleFrameRange(v, 48000)).toEqual([0, 48000])
  })
})

describe('clampFpp (M1.11)', () => {
  it('floors at the maximum zoom of 8 px/frame', () => {
    expect(MIN_FPP).toBeCloseTo(0.125)
    expect(clampFpp(0.01)).toBeCloseTo(0.125)
    expect(clampFpp(0.125)).toBeCloseTo(0.125)
  })

  it('passes higher zooms through unchanged', () => {
    expect(clampFpp(1)).toBe(1)
    expect(clampFpp(60)).toBe(60)
  })

  it('rejects non-positive zoom', () => {
    expect(() => clampFpp(0)).toThrow(RangeError)
    expect(() => clampFpp(-2)).toThrow(RangeError)
  })
})

describe('visibleFrames (M1.11)', () => {
  it('is width times the zoom', () => {
    expect(visibleFrames({ startFrame: 0, fpp: 60 }, 800)).toBe(48000)
    expect(visibleFrames({ startFrame: 10, fpp: 0.5 }, 100)).toBe(50)
  })

  it('rejects a zero width', () => {
    expect(() => visibleFrames({ startFrame: 0, fpp: 1 }, 0)).toThrow(RangeError)
  })
})

describe('clampView (M1.11)', () => {
  it('pins the start to zero when the view spans the whole source', () => {
    const v = clampView({ startFrame: 500, fpp: 60 }, 48000, 800)
    expect(v.startFrame).toBe(0)
    expect(v.fpp).toBe(60)
  })

  it('clamps the start to the left and right boundaries', () => {
    // 100 px window at 4 fpp spans 400 frames of a 48000-frame source.
    expect(clampView({ startFrame: -10, fpp: 4 }, 48000, 100).startFrame).toBe(0)
    expect(clampView({ startFrame: 47999.5, fpp: 4 }, 48000, 100).startFrame).toBeCloseTo(47600)
  })

  it('leaves an in-bounds start untouched', () => {
    expect(clampView({ startFrame: 2000, fpp: 4 }, 48000, 100).startFrame).toBe(2000)
  })
})

describe('zoomView (M1.11)', () => {
  const width = 800
  const duration = 48000

  it('keeps the anchor frame at the same x', () => {
    // 800 px at 30 fpp spans 24000 frames: window [12000, 36000].
    const before = { startFrame: 12000, fpp: 30 }
    const after = zoomView(before, 2, 24000, duration, width)
    // Anchor x before: (24000 - 12000) / 30 = 400. After: (24000 - 0) / 60.
    expect(after.fpp).toBe(60)
    expect(after.startFrame).toBeCloseTo(0)
    expect((24000 - after.startFrame) / after.fpp).toBeCloseTo(400)
  })

  it('floors the zoom at 8 px/frame', () => {
    const after = zoomView({ startFrame: 0, fpp: 1 }, 0.001, 0, duration, width)
    expect(after.fpp).toBeCloseTo(0.125)
  })

  it('clamps the start when zooming in at the right edge', () => {
    // 100 px at 4 fpp spans 400 frames; the view sits flush at the end.
    const before = { startFrame: 47600, fpp: 4 }
    const after = zoomView(before, 2, 47999, duration, 100)
    expect(after.startFrame + visibleFrames(after, 100)).toBeLessThanOrEqual(duration + 1e-9)
  })

  it('rejects a non-positive factor', () => {
    expect(() => zoomView({ startFrame: 0, fpp: 1 }, 0, 0, duration, width)).toThrow(RangeError)
  })
})

describe('panView (M1.11)', () => {
  it('pans by the given frames', () => {
    const after = panView({ startFrame: 100, fpp: 4 }, 50.5, 48000, 100)
    expect(after.startFrame).toBeCloseTo(150.5)
    expect(after.fpp).toBe(4)
  })

  it('clamps at both source boundaries', () => {
    expect(panView({ startFrame: 0, fpp: 4 }, -100, 48000, 100).startFrame).toBe(0)
    expect(panView({ startFrame: 47600, fpp: 4 }, 1000, 48000, 100).startFrame).toBeCloseTo(47600)
  })
})

describe('fitRangeView (M1.11)', () => {
  it('fits the range exactly into the width', () => {
    const v = fitRangeView(1000, 2000, 1000)
    expect(v.fpp).toBeCloseTo(1)
    expect(v.startFrame).toBeCloseTo(1000)
  })

  it('clamps and centers when the range is smaller than the max zoom allows', () => {
    // 10 frames in 400 px is 0.025 fpp, below the 0.125 floor.
    const v = fitRangeView(100, 110, 400)
    expect(v.fpp).toBeCloseTo(0.125)
    // Visible = 400 * 0.125 = 50 frames, centered on 105.
    expect(v.startFrame).toBeCloseTo(80)
  })

  it('rejects an empty or inverted range', () => {
    expect(() => fitRangeView(100, 100, 400)).toThrow(RangeError)
    expect(() => fitRangeView(200, 100, 400)).toThrow(RangeError)
    expect(() => fitRangeView(100, 200, 0)).toThrow(RangeError)
  })
})
