/**
 * Pinned-loop cache (M2.12 §14.1.4, the M2.11 §13.5.3 hook).
 *
 * A practice loop that fits the configured byte budget is retained once
 * and served from memory on every later pass and every seek inside the
 * range — no network round trip. The pin is deliberately dumb: it owns
 * immutable per-source channel arrays for one source-frame range, tracks
 * which frames have already been retained (ordinary loop fetches fill
 * it over one or more passes), and copies frames out on demand.
 *
 * Budget rule (§14.1.5): the caller admits a pin only while its byte
 * size fits the remaining pin budget (`PINNED_BYTES_MAX`, shared across
 * the active group); releasing the pin frees the budget again. Bytes
 * are accounted here (`bytes`) and are excluded from the streaming
 * `bufferedBytes`/`budgetBytes` ledger.
 *
 * Audio-thread note: this runs on the main thread; the copy helpers are
 * plain `Float32Array` operations (no audio-thread work).
 */

import { writeSharedRing, type SharedRing } from './pcm-fetch'

/** M2.12 §14.1.5: group-wide pinned-loop byte budget (64 MiB). */
export const PINNED_BYTES_MAX = 64 * 1024 * 1024

export interface LoopPinSpec {
  /** First pinned source frame (inclusive). */
  startFrame: number
  /** Last pinned source frame (exclusive); must be > `startFrame`. */
  endFrame: number
  /** Channel count per source; the pin stores one array per channel. */
  channelCounts: number[]
}

/** Source-frame range pinned for one loop. */
export class LoopPin {
  readonly startFrame: number
  readonly endFrame: number
  /** Frames of the pinned range. */
  readonly frames: number
  /** [source][channel] immutable sample arrays. */
  private readonly data: Float32Array[][]
  /** [source] coverage bitset, one bit per pinned frame. */
  private readonly covered: Uint8Array[]
  private readonly coveredCount: number[]
  /** Interleave scratch for shared-mode serves (grown on demand). */
  private scratch = new Uint8Array(0)

  constructor(spec: LoopPinSpec) {
    if (!(spec.endFrame > spec.startFrame)) {
      throw new RangeError('loop pin needs a positive frame range')
    }
    if (spec.channelCounts.length === 0 || spec.channelCounts.some((c) => !(c >= 1))) {
      throw new RangeError('loop pin needs at least one channel per source')
    }
    this.startFrame = spec.startFrame
    this.endFrame = spec.endFrame
    this.frames = spec.endFrame - spec.startFrame
    this.data = spec.channelCounts.map((channelCount) =>
      Array.from({ length: channelCount }, () => new Float32Array(this.frames)),
    )
    const bitBytes = Math.ceil(this.frames / 8)
    this.covered = spec.channelCounts.map(() => new Uint8Array(bitBytes))
    this.coveredCount = spec.channelCounts.map(() => 0)
  }

  /** Retained bytes across the group (the §14.1.5 accounting figure). */
  get bytes(): number {
    return this.data.reduce((sum, perSource) => sum + perSource.length * this.frames * 4, 0)
  }

  /** True once every frame of every source has been retained. */
  get ready(): boolean {
    return this.coveredCount.every((count) => count === this.frames)
  }

  /** True when `[from, from + frames)` lies inside the pinned range. */
  covers(from: number, frames: number): boolean {
    return from >= this.startFrame && from + frames <= this.endFrame
  }

  /**
   * True while a fetched chunk for `source` starting at `from` would add
   * at least one missing frame (the shared path asks for payload
   * retention only then; the transfer path already has the data).
   */
  wantsChunk(source: number, from: number, frames: number): boolean {
    if (this.ready) return false
    const bits = this.covered[source]
    const first = Math.max(from, this.startFrame)
    const last = Math.min(from + frames, this.endFrame)
    for (let frame = first; frame < last; frame++) {
      const bit = bits[(frame - this.startFrame) >> 3] & (1 << ((frame - this.startFrame) & 7))
      if (bit === 0) return true
    }
    return false
  }

  /**
   * Retain the pinned part of a fetched chunk. `channels` holds `frames`
   * frames starting at source frame `from`; returns the frames retained.
   * The first pass may be partial (a loop entered mid-range): later
   * passes complete the pin, and only the final completion flips
   * `ready`.
   */
  retain(source: number, from: number, channels: Float32Array[]): number {
    if (this.ready || channels.length === 0) return 0
    const first = Math.max(from, this.startFrame)
    const last = Math.min(from + channels[0].length, this.endFrame)
    if (last <= first) return 0
    const perSource = this.data[source]
    if (!perSource) return 0
    const bits = this.covered[source]
    let retained = 0
    for (let frame = first; frame < last; frame++) {
      const index = frame - this.startFrame
      const mask = 1 << (index & 7)
      const byte = bits[index >> 3]
      if ((byte & mask) !== 0) continue
      for (let c = 0; c < perSource.length; c++) {
        perSource[c][index] = channels[c][frame - from]
      }
      bits[index >> 3] = byte | mask
      retained += 1
    }
    this.coveredCount[source] += retained
    return retained
  }

  /**
   * Transfer-mode serve: fresh channel arrays for `[from, from + count)`,
   * cloned from the pin so the originals stay intact when posted
   * (transferables detach).
   */
  copyChannels(source: number, from: number, count: number): Float32Array[] {
    if (!this.covers(from, count)) throw new RangeError('loop pin range not available')
    const perSource = this.data[source]
    const offset = from - this.startFrame
    return perSource.map((channel) => channel.slice(offset, offset + count))
  }

  /**
   * Shared-mode serve: copy `[from, from + count)` into the ring at the
   * current writer position (wrap-aware, same contract as the worker's
   * write: 0 frames when the ring is full).
   */
  writeShared(ring: SharedRing, source: number, from: number, count: number): number {
    if (!this.covers(from, count)) throw new RangeError('loop pin range not available')
    const perSource = this.data[source]
    const bytesPerFrame = 4 * perSource.length
    const needed = count * bytesPerFrame
    if (this.scratch.length < needed) this.scratch = new Uint8Array(needed)
    const view = new DataView(this.scratch.buffer, this.scratch.byteOffset, needed)
    const offset = from - this.startFrame
    for (let frame = 0; frame < count; frame++) {
      for (let c = 0; c < perSource.length; c++) {
        view.setFloat32((frame * perSource.length + c) * 4, perSource[c][offset + frame], true)
      }
    }
    return writeSharedRing(ring, this.scratch.subarray(0, needed))
  }
}
