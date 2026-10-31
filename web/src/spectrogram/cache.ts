import type { SpectrogramImage } from "./stft";

/** Cache identity: a view is (start time, pixel width, FFT size). */
export function spectrogramCacheKey(
  startSeconds: number,
  widthPx: number,
  fftSize: number,
): string {
  return `${startSeconds}:${widthPx}:${fftSize}`;
}

/**
 * In-memory cache of in-flight and finished spectrogram images. Failed
 * computations evict themselves so the next view change can retry.
 */
export class SpectrogramCache {
  private readonly entries = new Map<string, Promise<SpectrogramImage>>();
  private readonly maxEntries: number;

  constructor(maxEntries = 12) {
    if (!Number.isInteger(maxEntries) || maxEntries < 1) {
      throw new RangeError(
        `spectrogram cache needs a positive entry limit, got ${maxEntries}`,
      );
    }
    this.maxEntries = maxEntries;
  }

  get(key: string): Promise<SpectrogramImage> | undefined {
    const entry = this.entries.get(key);
    if (entry !== undefined) {
      // Refresh recency: Map keeps insertion order, so the first key is the
      // least recently used one.
      this.entries.delete(key);
      this.entries.set(key, entry);
    }
    return entry;
  }

  set(key: string, image: Promise<SpectrogramImage>): void {
    // Attach the eviction handler to the stored promise itself: the rejection
    // stays observable for consumers while the cache does not hold a rejected
    // entry forever, and no unhandled rejection escapes.
    image.catch(() => {
      if (this.entries.get(key) === image) {
        this.entries.delete(key);
      }
    });
    this.entries.delete(key);
    this.entries.set(key, image);
    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) {
        break;
      }
      this.entries.delete(oldest);
    }
  }

  clear(): void {
    this.entries.clear();
  }

  get size(): number {
    return this.entries.size;
  }
}
