import { describe, expect, it } from 'vitest'

import type { RhythmGridData } from '../src/api/rhythm'
import { musicalReadout } from '../src/music/readout'

function grid(): RhythmGridData {
  return {
    branch_validity: 'valid',
    tempo_anchors: [
      {
        source_frame: 0,
        musical_position: { numerator: 0, denominator: 1 },
      },
      {
        source_frame: 48_000,
        musical_position: { numerator: 4, denominator: 1 },
      },
    ],
    meter_regions: [
      {
        start: { numerator: 0, denominator: 1 },
        numerator: 4,
        denominator: 4,
        grouping: [1, 1, 1, 1],
      },
    ],
    bar_origin: {
      first_numbered_bar_position: { numerator: 0, denominator: 1 },
      first_bar_number: 1,
    },
  } as unknown as RhythmGridData
}

describe('musical readout (M3.16 §18.1-§18.4)', () => {
  it('shows bar, beat, and fractional beat', () => {
    expect(musicalReadout(grid(), 0)).toBe('Bar 1 Beat 1.00 | — | —')
    expect(musicalReadout(grid(), 18_000)).toBe('Bar 1 Beat 2.50 | — | —')
  })

  it('marks pickups and uncertainty, and uses no-grid placeholders', () => {
    const pickup = grid()
    pickup.bar_origin.first_numbered_bar_position = { numerator: 4, denominator: 1 }
    expect(musicalReadout(pickup, 0)).toBe('Pickup | — | —')
    const uncertain = grid()
    uncertain.branch_validity = 'uncertain'
    expect(musicalReadout(uncertain, 0)).toContain('?')
    expect(musicalReadout(null, 0)).toBe('No grid | — | —')
  })
})
