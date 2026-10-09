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
  /** Total frames buffered on the active path after this block. */
  buffered: number
}

export class ConsumptionState {
  constructor(opts: ConsumptionOptions)
  /** Next frame to consume (playback frames). */
  readonly position: number
  readonly ended: boolean
  readonly sampleRate: number
  readonly channelCount: number
  /** Ring capacity in frames (12 s at the source rate). */
  readonly capacity: number
  /** Frames currently in the rings (transfer path). */
  readonly available: number
  /** Total buffered frames on the active path (ring + queue, or shared avail). */
  readonly buffered: number
  /** Frames in the transfer queue (0 on the shared path). */
  readonly queued: number
  /**
   * Deinterleave f32le `buffer` into the queue.
   * @returns false if the budget would overflow (caller drops the chunk).
   */
  enqueue(buffer: ArrayBuffer): boolean
  /**
   * Queue pre-deinterleaved per-channel arrays (transfer path).
   * @returns false if the budget would overflow (caller drops the chunk).
   */
  enqueueChannels(channels: Float32Array[]): boolean
  /**
   * Bind the shared ring (shared path): 16-byte Int32 header
   * `[generation, writerIdx, readerIdx, 0]` + interleaved f32 data.
   */
  attachShared(sab: SharedArrayBuffer): void
  /**
   * Drop all buffered data and move to `frame` (the stale-audio
   * barrier). On the shared path this also stores the reader index and
   * adopts `generation`; the writer index resets only on the worker's
   * flush acknowledgment.
   */
  seek(frame: number, generation?: number): void
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
