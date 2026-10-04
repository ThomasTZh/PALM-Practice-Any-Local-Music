/**
 * Type surface of `worklet-processor.js`. The file itself is plain JS so
 * the browser can load it as a self-contained Blob-URL worklet module
 * (no imports); this declaration is what the TypeScript build sees.
 * Only `ConsumptionState` is imported from the main thread.
 */

export interface ConsumptionOptions {
  sampleRate: number
  channelCount: number
  frameCount: number
  /** Anchor cadence in frames; defaults to 480 (10 ms at 48 kHz). */
  anchorEveryFrames?: number
}

export interface ProcessResult {
  /** Frames consumed from the buffer into this block. */
  consumed: number
  /** True once when the buffer emptied while data was expected. */
  underrun: boolean
  /** True once when the position reached the source endpoint. */
  ended: boolean
  /**
   * Position anchor: at context time `time` the position was `frame`, so
   * main-thread extrapolation is `frame + (now - time) * sampleRate`.
   */
  anchor: { frame: number; time: number } | null
}

export class ConsumptionState {
  constructor(opts: ConsumptionOptions)
  /** Next frame to consume (playback frames). */
  readonly position: number
  readonly ended: boolean
  /** Frames currently buffered (identical for every channel). */
  readonly available: number
  /**
   * Deinterleave f32le `buffer` into the rings.
   * @returns false if the ring would overflow (caller drops the chunk).
   */
  enqueue(buffer: ArrayBuffer): boolean
  /** Drop all buffered data and move to `frame` (the stale-audio barrier). */
  seek(frame: number): void
  /** Begin the ~5 ms output ramp; consumption stops, position preserved. */
  pause(): void
  /** Resume consumption exactly at the preserved position. */
  resume(): void
  /**
   * Fill the output channels deterministically using the actual block
   * length (`outputChannels[0].length`).
   */
  process(time: number, outputChannels: Float32Array[]): ProcessResult
}
