import { describe, expect, it } from 'vitest'

import golden from '../../tests/fixtures/golden-mapping.json'
import { musicalAtSource, sourceAtMusical } from '../src/music/tempoGrid'

describe('shared rhythm golden mapping fixture (M3.19 §21.2)', () => {
  it('maps every anchor and sample through the TypeScript port', () => {
    const anchors = golden.anchors.map((anchor) => ({
      sourceFrame: anchor.source_frame,
      musical: anchor.musical_position,
    }))
    for (const anchor of golden.anchors) {
      const musical = musicalAtSource(anchors, anchor.source_frame)
      expect(musical).toEqual(anchor.musical_position)
    }
    for (const sample of golden.samples) {
      const musical = musicalAtSource(anchors, sample.source_frame)
      expect(musical).toEqual(sample.musical_position)
      expect(sourceAtMusical(anchors, sample.musical_position).sourceFrame).toBe(
        sample.back_to_source,
      )
    }
  })

  it('records the corpus size and first bar metadata', () => {
    expect(golden.sample_rate).toBe(48_000)
    expect(golden.first_bar.numerator).toBe(4)
    expect(golden.pulse_count).toBeGreaterThan(0)
  })
})
