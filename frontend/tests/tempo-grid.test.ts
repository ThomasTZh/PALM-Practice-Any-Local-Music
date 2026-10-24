import { describe, expect, it } from 'vitest'

import fixture from './golden/rhythm-grid.json'
import {
  barBeatLabel,
  musicalAtSource,
  roundHalfUp,
  sourceAtMusical,
  type BarOrigin,
  type Fraction,
  type MeterRegion,
} from '../src/music/tempoGrid'

interface FixtureShape {
  tempoAnchors: { sourceFrame: number; musical: Fraction }[]
  meterRegions: MeterRegion[]
  barOrigin: BarOrigin
  mappingQueries: {
    musical: Fraction
    sourceFraction: Fraction
    sourceFrame: number
  }[]
  inverseQueries: { sourceFrame: number; musical: Fraction }[]
  labelQueries: {
    musical: Fraction
    barNumber: number
    beat: number
    label: string
    pickup: boolean
  }[]
}

const data = fixture as FixtureShape

describe('shared tempo/grid golden vectors (M3.9 §11.3)', () => {
  it('maps musical positions to exact fractional sources and rounded frames', () => {
    for (const query of data.mappingQueries) {
      const mapped = sourceAtMusical(data.tempoAnchors, query.musical)
      expect(mapped.fraction).toEqual(query.sourceFraction)
      expect(mapped.sourceFrame).toBe(query.sourceFrame)
    }
  })

  it('rounds half-up once', () => {
    expect(roundHalfUp({ numerator: 2500, denominator: 1 })).toBe(2500)
    expect(roundHalfUp({ numerator: 5001, denominator: 2 })).toBe(2501)
    expect(roundHalfUp({ numerator: 3, denominator: 2 })).toBe(2)
  })

  it('maps source frames back to exact musical positions', () => {
    for (const query of data.inverseQueries) {
      expect(musicalAtSource(data.tempoAnchors, query.sourceFrame)).toEqual(query.musical)
    }
  })

  it('labels bars and beats identically to Python', () => {
    for (const query of data.labelQueries) {
      const label = barBeatLabel(data.meterRegions, data.barOrigin, query.musical)
      expect(label.barNumber).toBe(query.barNumber)
      expect(label.beat).toBe(query.beat)
      expect(label.label).toBe(query.label)
      expect(label.pickup).toBe(query.pickup)
    }
  })
})
