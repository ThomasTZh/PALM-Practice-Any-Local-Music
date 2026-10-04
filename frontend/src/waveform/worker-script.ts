/**
 * Worker body for the decode worker (M1.10, spec §11.5).
 *
 * Runs the pure `decode.ts` parsing off the main thread. Bundled by Vite
 * via `new Worker(new URL('./worker-script.ts', import.meta.url))`. The
 * unit tests exercise `decode.ts` directly; this script is the thin
 * message loop that forwards jobs to it.
 */

import { aggregatePcmToPixels, parsePeakTile, pcmSamples } from './decode'

type Job =
  | { kind: 'tile'; id: number; bytes: ArrayBuffer; channelCount: number; bucketCount: number }
  | {
      kind: 'pcm-pixels'
      id: number
      bytes: ArrayBuffer
      channelCount: number
      startFrame: number
      framesPerCssPixel: number
    }
  | { kind: 'pcm-samples'; id: number; bytes: ArrayBuffer; channelCount: number }

self.onmessage = (event: MessageEvent<Job>) => {
  const job = event.data
  try {
    let result: unknown
    if (job.kind === 'tile') {
      result = parsePeakTile(job.bytes, job.channelCount, job.bucketCount)
    } else if (job.kind === 'pcm-pixels') {
      result = aggregatePcmToPixels(
        job.bytes,
        job.channelCount,
        job.startFrame,
        job.framesPerCssPixel,
      )
    } else {
      result = pcmSamples(job.bytes, job.channelCount)
    }
    self.postMessage({ id: job.id, ok: true, result })
  } catch (e) {
    self.postMessage({ id: job.id, ok: false, error: e instanceof Error ? e.message : String(e) })
  }
}
