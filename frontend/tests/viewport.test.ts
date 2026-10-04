import { describe, expect, it } from 'vitest'
import {
  fitViewport,
  frameToX,
  makeViewport,
  visibleFrameRange,
  xToFrame,
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
