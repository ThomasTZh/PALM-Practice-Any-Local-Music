/**
 * PCM primitives for the playback core (t2): shared-memory ring, byte
 * range validation, deinterleaving, and control clamping.
 *
 * One implementation is used by the fetch worker, the main-thread
 * fallback (`fetch-source.ts`) and the correctness tests, so the ring
 * layout and the range arithmetic live here once.
 *
 * Ring layout (spec §15.1, ported from the legacy branch): a 16-byte
 * Int32 header `[generation, writerIdx, readerIdx, 0]` followed by
 * interleaved f32 data. The fetch worker is the sole writer (data and
 * writer index); the worklet is the sole reader (reader index). Atomics
 * order the index updates; nothing ever blocks.
 */

export const RING_HEADER_BYTES = 16;
export const BYTES_PER_SAMPLE = 4;

export const MIN_RATE = 0.25;
export const MAX_RATE = 2.0;
export const MIN_TRANSPOSE = -12;
export const MAX_TRANSPOSE = 12;

export interface SharedRing {
  sab: SharedArrayBuffer;
  header: Int32Array;
  data: Uint8Array;
  frameCapacity: number;
  channelCount: number;
}

/** Allocate a ring whose data region holds `capacityFrames`. */
export function createSharedRing(
  capacityFrames: number,
  channelCount: number,
): SharedRing {
  if (!Number.isFinite(capacityFrames) || capacityFrames < 1) {
    throw new RangeError("capacityFrames must be >= 1");
  }
  if (!Number.isFinite(channelCount) || channelCount < 1) {
    throw new RangeError("channelCount must be >= 1");
  }
  const byteLength =
    RING_HEADER_BYTES +
    Math.floor(capacityFrames) * channelCount * BYTES_PER_SAMPLE;
  return viewSharedRing(new SharedArrayBuffer(byteLength), channelCount);
}

/** View a ring over an existing SharedArrayBuffer (layout above). */
export function viewSharedRing(
  sab: SharedArrayBuffer,
  channelCount: number,
): SharedRing {
  if (!(sab instanceof SharedArrayBuffer))
    throw new TypeError("expected a SharedArrayBuffer");
  if (sab.byteLength <= RING_HEADER_BYTES)
    throw new RangeError("shared ring is too small");
  if (!(channelCount >= 1)) throw new RangeError("channelCount must be >= 1");
  const data = new Uint8Array(sab, RING_HEADER_BYTES);
  return {
    sab,
    header: new Int32Array(sab, 0, 4),
    data,
    frameCapacity: Math.floor(
      data.byteLength / (BYTES_PER_SAMPLE * channelCount),
    ),
    channelCount,
  };
}

/** Positive modulo for stream coordinates that may be negative. */
export function wrapIndex(value: number, length: number): number {
  return ((value % length) + length) % length;
}

/**
 * Copy interleaved f32le bytes into the ring at the current writer
 * position (wrap-aware). Returns the frames written, or 0 when the ring
 * cannot hold the chunk (normal flow control: the caller retries).
 */
export function writeSharedRing(
  ring: SharedRing,
  bytes: ArrayBuffer | ArrayBufferView,
): number {
  const writer = Atomics.load(ring.header, 1);
  const reader = Atomics.load(ring.header, 2);
  const bytesPerFrame = BYTES_PER_SAMPLE * ring.channelCount;
  const frames = Math.floor(bytes.byteLength / bytesPerFrame);
  if (frames <= 0) return 0;
  if (writer - reader + frames > ring.frameCapacity) return 0;
  const source =
    bytes instanceof ArrayBuffer
      ? new Uint8Array(bytes)
      : new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let frame = 0; frame < frames; frame += 1) {
    const slot = wrapIndex(writer + frame, ring.frameCapacity);
    ring.data.set(
      source.subarray(frame * bytesPerFrame, (frame + 1) * bytesPerFrame),
      slot * bytesPerFrame,
    );
  }
  Atomics.store(ring.header, 1, writer + frames);
  return frames;
}

/**
 * Writer-side flush acknowledgement: adopt the reader's new generation
 * and reposition the writer. Only called after the worklet acknowledged
 * its `seek`, so the reader index is already written.
 */
export function acknowledgeSharedFlush(
  ring: SharedRing,
  generation: number,
  baseFrame: number,
): void {
  Atomics.store(ring.header, 0, generation);
  Atomics.store(ring.header, 1, baseFrame);
}

/** Split interleaved f32le bytes into per-channel Float32Arrays. */
export function deinterleaveF32le(
  bytes: ArrayBuffer,
  channelCount: number,
): Float32Array[] {
  if (!(channelCount >= 1)) throw new RangeError("channelCount must be >= 1");
  const bytesPerFrame = BYTES_PER_SAMPLE * channelCount;
  if (bytes.byteLength % bytesPerFrame !== 0) {
    throw new RangeError("byte length is not a whole number of frames");
  }
  const frames = bytes.byteLength / bytesPerFrame;
  const channels = Array.from(
    { length: channelCount },
    () => new Float32Array(frames),
  );
  const view = new DataView(bytes);
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channelCount; channel += 1) {
      channels[channel][frame] = view.getFloat32(
        (frame * channelCount + channel) * 4,
        true,
      );
    }
  }
  return channels;
}

/** Interleave per-channel arrays into f32le bytes (tests and fixtures). */
export function interleaveF32le(
  channels: readonly Float32Array[],
): ArrayBuffer {
  if (channels.length === 0)
    throw new RangeError("at least one channel is required");
  const frames = channels[0].length;
  const buffer = new ArrayBuffer(frames * channels.length * BYTES_PER_SAMPLE);
  const view = new DataView(buffer);
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channels.length; channel += 1) {
      view.setFloat32(
        (frame * channels.length + channel) * 4,
        channels[channel][frame],
        true,
      );
    }
  }
  return buffer;
}

/** Byte range (inclusive end) for a half-open frame range. */
export function frameRangeToBytes(
  startFrame: number,
  endFrame: number,
  channelCount: number,
): { startByte: number; endByte: number } {
  const start = Math.floor(startFrame);
  const end = Math.floor(endFrame);
  if (!(end > start))
    throw new RangeError("endFrame must be greater than startFrame");
  if (!(channelCount >= 1)) throw new RangeError("channelCount must be >= 1");
  const bytesPerFrame = BYTES_PER_SAMPLE * channelCount;
  return { startByte: start * bytesPerFrame, endByte: end * bytesPerFrame - 1 };
}

/** Clamp a playback rate; NaN/non-finite falls back to 1× (never throws). */
export function clampRate(rate: number): number {
  if (!Number.isFinite(rate)) return 1;
  return Math.min(MAX_RATE, Math.max(MIN_RATE, rate));
}

/** Clamp a pitch shift; NaN/non-finite falls back to 0 semitones. */
export function clampTranspose(semitones: number): number {
  if (!Number.isFinite(semitones)) return 0;
  return Math.min(MAX_TRANSPOSE, Math.max(MIN_TRANSPOSE, semitones));
}
