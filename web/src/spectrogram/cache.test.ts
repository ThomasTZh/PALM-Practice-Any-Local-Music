import { describe, expect, it } from "vitest";

import { SpectrogramCache, spectrogramCacheKey } from "./cache";
import type { SpectrogramImage } from "./stft";

function image(width = 4): SpectrogramImage {
  return {
    width,
    height: 2,
    pixels: new Uint8ClampedArray(width * 2 * 4),
    floorDb: -100,
    ceilingDb: 0,
    fftSize: 2048,
    sampleRate: 44100,
    startSeconds: 0,
    secondsPerPixel: 1,
  };
}

describe("spectrogramCacheKey", () => {
  it("is built from start, width and FFT size", () => {
    expect(spectrogramCacheKey(0, 1280, 2048)).toBe("0:1280:2048");
    expect(spectrogramCacheKey(12.5, 640, 1024)).toBe("12.5:640:1024");
  });

  it("keeps different views apart", () => {
    const keys = new Set([
      spectrogramCacheKey(0, 1280, 2048),
      spectrogramCacheKey(1, 1280, 2048),
      spectrogramCacheKey(0, 640, 2048),
      spectrogramCacheKey(0, 1280, 1024),
    ]);
    expect(keys.size).toBe(4);
  });
});

describe("SpectrogramCache", () => {
  it("returns the cached result for a repeated view", async () => {
    const cache = new SpectrogramCache();
    const result = image();
    cache.set("0:1280:2048", Promise.resolve(result));

    expect(cache.size).toBe(1);
    await expect(cache.get("0:1280:2048")).resolves.toBe(result);
    expect(cache.get("1:1280:2048")).toBeUndefined();
  });

  it("evicts a failed computation so the next view can retry", async () => {
    const cache = new SpectrogramCache();
    const failed = Promise.reject(new Error("worker crashed"));

    cache.set("0:1280:2048", failed);
    const cached = cache.get("0:1280:2048");
    expect(cached).toBeDefined();
    await expect(cached).rejects.toThrow("worker crashed");
    await Promise.resolve();

    expect(cache.size).toBe(0);
    expect(cache.get("0:1280:2048")).toBeUndefined();
  });

  it("clears every entry", () => {
    const cache = new SpectrogramCache();
    cache.set("a", Promise.resolve(image()));
    cache.set("b", Promise.resolve(image()));

    cache.clear();

    expect(cache.size).toBe(0);
  });

  it("bounds memory by evicting the least recently used view", async () => {
    const cache = new SpectrogramCache(2);
    const first = image();
    const second = image();
    const third = image();

    cache.set("first", Promise.resolve(first));
    cache.set("second", Promise.resolve(second));
    await expect(cache.get("first")).resolves.toBe(first);
    cache.set("third", Promise.resolve(third));

    expect(cache.size).toBe(2);
    expect(cache.get("second")).toBeUndefined();
    await expect(cache.get("first")).resolves.toBe(first);
    await expect(cache.get("third")).resolves.toBe(third);
  });

  it("rejects an unusable limit", () => {
    expect(() => new SpectrogramCache(0)).toThrow(RangeError);
    expect(() => new SpectrogramCache(1.5)).toThrow(RangeError);
  });
});
