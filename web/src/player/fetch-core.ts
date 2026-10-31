/**
 * Ranged PCM fetch core (t2).
 *
 * Fetches one ranged chunk of interleaved f32le PCM for one source and
 * either writes it into the caller's SharedArrayBuffer ring (shared
 * path) or returns deinterleaved channel arrays for transfer to the
 * worklet (transfer path). Both paths are exercised by the tests; the
 * browser picks shared memory when available and falls back to transfer.
 *
 * Generation discipline: every fetch records the generation it started
 * under; a seek that bumps the generation makes the in-flight result
 * throw `StaleGenerationError`, so no stale audio can be enqueued after
 * a seek. Range responses are validated at the boundary (whole frames,
 * HTTP status, 416) before they reach the audio thread.
 */

import {
  BYTES_PER_SAMPLE,
  deinterleaveF32le,
  frameRangeToBytes,
  viewSharedRing,
  writeSharedRing,
  type SharedRing,
} from "./pcm";

export class StaleGenerationError extends Error {
  constructor() {
    super("fetch generation is stale");
    this.name = "StaleGenerationError";
  }
}

/** Byte fetcher: the inclusive end byte mirrors HTTP `Range`. */
export type FetchBytes = (
  url: string,
  startByte: number,
  endByteInclusive: number,
  signal?: AbortSignal,
) => Promise<ArrayBuffer>;

export interface FetchedChunk {
  /** Stream frame of the first returned frame. */
  startFrame: number;
  frames: number;
  /** Transfer path only; absent on the shared path (bytes went to the ring). */
  channels?: Float32Array[];
}

/**
 * Default `FetchBytes`: HTTP Range over the source URL. A 416 response
 * means the range lies outside the asset; other failures are plain
 * errors. No retries here — the transport owns prefetch policy.
 */
export const fetchBytesWithRange: FetchBytes = async (
  url,
  startByte,
  endByteInclusive,
  signal,
) => {
  const response = await fetch(url, {
    headers: { Range: `bytes=${startByte}-${endByteInclusive}` },
    ...(signal ? { signal } : {}),
  });
  if (response.status === 416) {
    throw new RangeError("the requested byte range is not satisfiable");
  }
  if (!response.ok) {
    throw new Error(`asset bytes failed (HTTP ${response.status})`);
  }
  return response.arrayBuffer();
};

export interface RangedPcmFetcherOptions {
  url: string;
  channelCount: number;
  fetchBytes?: FetchBytes;
}

/**
 * One source's ranged fetcher. `setGeneration` is the stale-audio
 * barrier; `attachShared` switches the destination to a SAB ring.
 */
export class RangedPcmFetcher {
  readonly url: string;
  readonly channelCount: number;
  readonly fetchBytes: FetchBytes;
  private ring: SharedRing | null = null;
  private generation = -1;

  constructor({
    url,
    channelCount,
    fetchBytes = fetchBytesWithRange,
  }: RangedPcmFetcherOptions) {
    if (!(channelCount >= 1)) throw new RangeError("channelCount must be >= 1");
    this.url = url;
    this.channelCount = channelCount;
    this.fetchBytes = fetchBytes;
  }

  get shared(): boolean {
    return this.ring !== null;
  }

  get ringView(): SharedRing | null {
    return this.ring;
  }

  attachShared(sab: SharedArrayBuffer): SharedRing {
    this.ring = viewSharedRing(sab, this.channelCount);
    return this.ring;
  }

  setGeneration(generation: number): void {
    this.generation = generation;
  }

  get currentGeneration(): number {
    return this.generation;
  }

  /**
   * Fetch `[startFrame, endFrame)` for the current generation.
   * On the shared path the bytes are copied into the ring and only the
   * written frame count is returned (0 means the ring is full: normal
   * backpressure, retry later).
   */
  async fetchRange(
    startFrame: number,
    endFrame: number,
  ): Promise<FetchedChunk> {
    const generation = this.generation;
    const start = Math.floor(startFrame);
    const end = Math.floor(endFrame);
    const { startByte, endByte } = frameRangeToBytes(
      start,
      end,
      this.channelCount,
    );
    const bytes = await this.fetchBytes(this.url, startByte, endByte);
    if (generation !== this.generation) throw new StaleGenerationError();
    const bytesPerFrame = BYTES_PER_SAMPLE * this.channelCount;
    if (bytes.byteLength % bytesPerFrame !== 0) {
      throw new RangeError("range response is not a whole number of frames");
    }
    if (this.ring) {
      const frames = writeSharedRing(this.ring, bytes);
      return { startFrame: start, frames };
    }
    const channels = deinterleaveF32le(bytes, this.channelCount);
    return {
      startFrame: start,
      frames: channels.length > 0 ? channels[0].length : 0,
      channels,
    };
  }
}
