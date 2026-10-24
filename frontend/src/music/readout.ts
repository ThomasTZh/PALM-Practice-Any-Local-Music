/** Musical position readout (M3.16 §18.1-§18.4). */

import type { RhythmGridData } from '../api/rhythm'
import { barBeatPosition, musicalAtSource } from './tempoGrid'

export function musicalReadout(data: RhythmGridData | null, sourceFrame: number): string {
  if (!data) return 'No grid | — | —'
  try {
    const musical = musicalAtSource(
      data.tempo_anchors.map((anchor) => ({
        sourceFrame: anchor.source_frame,
        musical: anchor.musical_position,
      })),
      sourceFrame,
    )
    const beat = barBeatPosition(
      data.meter_regions.map((region) => ({
        start: region.start,
        numerator: region.numerator,
        denominator: region.denominator,
        grouping: region.grouping,
      })),
      {
        firstNumberedBarPosition: data.bar_origin.first_numbered_bar_position,
        firstBarNumber: data.bar_origin.first_bar_number,
      },
      musical,
    )
    const uncertainty = data.branch_validity === 'uncertain' ? ' ?' : ''
    if (beat.pickup) return `Pickup${uncertainty} | — | —`
    const fraction =
      beat.beatFraction == null
        ? ''
        : `.${Math.floor(beat.beatFraction * 100)
            .toString()
            .padStart(2, '0')}`
    return `Bar ${beat.barNumber} Beat ${beat.beat}${fraction}${uncertainty} | — | —`
  } catch {
    return 'No grid | — | —'
  }
}
