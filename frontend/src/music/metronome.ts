/** Metronome render-position math (M3.14 §16.4-§16.9).
 *
 * Clicks are musical/source events; the transport maps them to output
 * render frames after stretching. Per-click integer rounding keeps
 * repetition and loop passes free of cumulative drift.
 */

export type ClickStrength = 'downbeat' | 'beat' | 'grouping' | 'subdivision'

export interface ScheduledClick {
  source_frame: number
  strength: ClickStrength
}

export interface RenderClick {
  renderFrame: number
  sourceFrame: number
  strength: ClickStrength
  loopIteration?: number
}

export function mapClicksToRender(
  clicks: ScheduledClick[],
  sourceStart: number,
  outputStartFrame: number,
  rate = 1,
): RenderClick[] {
  if (!(rate > 0)) throw new Error('playback rate must be positive')
  return clicks
    .filter((click) => click.source_frame >= sourceStart)
    .map((click) => ({
      renderFrame: Math.max(
        0,
        Math.round(outputStartFrame + (click.source_frame - sourceStart) / rate),
      ),
      sourceFrame: click.source_frame,
      strength: click.strength,
    }))
}

export function repeatLoopClicks(
  clicks: ScheduledClick[],
  loopStart: number,
  loopEnd: number,
  outputStartFrame: number,
  passes: number,
  rate = 1,
): RenderClick[] {
  if (loopEnd <= loopStart) throw new Error('loop end must be after start')
  if (passes < 1) throw new Error('passes must be positive')
  if (!(rate > 0)) throw new Error('playback rate must be positive')
  const internal = clicks.filter(
    (click) => click.source_frame >= loopStart && click.source_frame < loopEnd,
  )
  const span = loopEnd - loopStart
  const result: RenderClick[] = []
  for (let iteration = 1; iteration <= passes; iteration += 1) {
    const base = outputStartFrame + Math.round(((iteration - 1) * span) / rate)
    for (const click of internal) {
      result.push({
        renderFrame: Math.max(0, base + Math.round((click.source_frame - loopStart) / rate)),
        sourceFrame: click.source_frame,
        strength: click.strength,
        loopIteration: iteration,
      })
    }
  }
  return result
}
