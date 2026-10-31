// @vitest-environment node
/**
 * Ranged PCM fetch tests (t2): frame/byte range validation, the
 * transfer path, the SharedArrayBuffer ring path, stale-generation
 * rejection, the worker adapter and the main-thread fallback.
 */

import { describe, expect, it, vi } from "vitest";
import {
  applyRange,
  fakeWorker,
  makeSourceBytes,
  readRingChannel,
} from "./fetch-test-utils";
import {
  createSharedRing,
  deinterleaveF32le,
  frameRangeToBytes,
  interleaveF32le,
  viewSharedRing,
  writeSharedRing,
} from "./pcm";
import {
  fetchBytesWithRange,
  RangedPcmFetcher,
  StaleGenerationError,
} from "./fetch-core";
import {
  createPcmSource,
  DirectPcmSource,
  WorkerPcmSource,
} from "./fetch-source";

const FRAMES = 1000;
const CHANNELS = 2;

function stereoRamp(): Float32Array[] {
  const left = new Float32Array(FRAMES);
  const right = new Float32Array(FRAMES);
  for (let i = 0; i < FRAMES; i += 1) {
    left[i] = i / FRAMES;
    right[i] = -i / FRAMES;
  }
  return [left, right];
}

describe("PCM range and ring primitives", () => {
  it("converts a half-open frame range to inclusive bytes", () => {
    expect(frameRangeToBytes(10, 20, 2)).toEqual({
      startByte: 80,
      endByte: 159,
    });
    expect(() => frameRangeToBytes(20, 20, 2)).toThrow(RangeError);
    expect(() => frameRangeToBytes(0, 10, 0)).toThrow(RangeError);
  });

  it("interleaves and deinterleaves losslessly", () => {
    const channels = stereoRamp();
    const bytes = interleaveF32le(channels);
    const roundTrip = deinterleaveF32le(bytes, 2);
    expect(roundTrip[0]).toEqual(channels[0]);
    expect(roundTrip[1]).toEqual(channels[1]);
    expect(() => deinterleaveF32le(new ArrayBuffer(6), 2)).toThrow(RangeError);
  });

  it("writes and wraps the shared ring, refusing overflow", () => {
    const ring = createSharedRing(8, 2);
    expect(ring.frameCapacity).toBe(8);
    expect(Atomics.load(ring.header, 1)).toBe(0);
    const bytes = interleaveF32le(
      stereoRamp().map((channel) => channel.slice(0, 6)),
    );
    expect(writeSharedRing(ring, bytes)).toBe(6);
    expect(Atomics.load(ring.header, 1)).toBe(6);
    // The reader consumed five frames; three more wrap slots 6, 7, 0.
    Atomics.store(ring.header, 2, 5);
    const tail = interleaveF32le([
      new Float32Array([9, 10, 11]),
      new Float32Array([19, 20, 21]),
    ]);
    expect(writeSharedRing(ring, tail)).toBe(3);
    expect(Atomics.load(ring.header, 1)).toBe(9);
    const data = new Float32Array(ring.data.buffer, 16, 16);
    expect(Array.from(data.slice(12, 16))).toEqual([9, 19, 10, 20]);
    expect(Array.from(data.slice(0, 2))).toEqual([11, 21]);
    // The ring is full (writer - reader = 4 < capacity but the next write
    // would exceed it after the reader stops), so no write.
    Atomics.store(ring.header, 2, 1);
    expect(writeSharedRing(ring, tail)).toBe(0);
  });

  it("views an existing SAB with the same layout", () => {
    const ring = createSharedRing(16, 1);
    const view = viewSharedRing(ring.sab, 1);
    expect(view.frameCapacity).toBe(16);
    expect(() =>
      viewSharedRing(new ArrayBuffer(64) as unknown as SharedArrayBuffer, 1),
    ).toThrow(TypeError);
  });
});

describe("RangedPcmFetcher: transfer path", () => {
  const bytes = makeSourceBytes(stereoRamp());

  it("fetches exactly the requested frame range", async () => {
    const fetcher = new RangedPcmFetcher({
      url: "memory://source",
      channelCount: CHANNELS,
      fetchBytes: async (_url, start, end) => applyRange(bytes, start, end),
    });
    fetcher.setGeneration(3);
    const chunk = await fetcher.fetchRange(100, 200);
    expect(chunk.startFrame).toBe(100);
    expect(chunk.frames).toBe(100);
    expect(Array.from(chunk.channels![0].slice(0, 3))).toEqual(
      Array.from(stereoRamp()[0].slice(100, 103)),
    );
  });

  it("rejects a stale fetch after a generation bump", async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetcher = new RangedPcmFetcher({
      url: "memory://source",
      channelCount: CHANNELS,
      fetchBytes: async (_url, start, end) => {
        await gate;
        return applyRange(bytes, start, end);
      },
    });
    fetcher.setGeneration(1);
    const pending = fetcher.fetchRange(0, 100);
    fetcher.setGeneration(2);
    release!();
    await expect(pending).rejects.toBeInstanceOf(StaleGenerationError);
  });
});

describe("RangedPcmFetcher: shared ring path", () => {
  const bytes = makeSourceBytes(stereoRamp());

  it("writes into the ring at the writer index and reports frames", async () => {
    const ring = createSharedRing(256, CHANNELS);
    const fetcher = new RangedPcmFetcher({
      url: "memory://source",
      channelCount: CHANNELS,
      fetchBytes: async (_url, start, end) => applyRange(bytes, start, end),
    });
    fetcher.attachShared(ring.sab);
    fetcher.setGeneration(1);
    Atomics.store(ring.header, 2, 0);
    Atomics.store(ring.header, 1, 0);
    const chunk = await fetcher.fetchRange(10, 42);
    expect(chunk.frames).toBe(32);
    expect(chunk.channels).toBeUndefined();
    expect(Atomics.load(ring.header, 1)).toBe(32);
    const written = readRingChannel(ring, 0, 0, 3);
    for (let i = 0; i < 3; i += 1)
      expect(written[i]).toBeCloseTo((10 + i) / FRAMES, 6);
  });
});

describe("HTTP range boundary", () => {
  it("sends a Range header and returns bytes", async () => {
    const captured: Array<{ url: string; headers: Record<string, string> }> =
      [];
    const payload = new Uint8Array([1, 2, 3, 4]);
    vi.stubGlobal(
      "fetch",
      async (url: string, init: { headers: Record<string, string> }) => {
        captured.push({ url, headers: init.headers });
        return new Response(payload, { status: 206 });
      },
    );
    const bytes = await fetchBytesWithRange("http://local/asset", 8, 11);
    expect(Array.from(new Uint8Array(bytes))).toEqual([1, 2, 3, 4]);
    expect(captured[0].headers.Range).toBe("bytes=8-11");
    vi.unstubAllGlobals();
  });

  it("maps 416 to RangeError and other failures to Error", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 416 }));
    await expect(
      fetchBytesWithRange("http://local/asset", 0, 3),
    ).rejects.toBeInstanceOf(RangeError);
    vi.stubGlobal("fetch", async () => new Response(null, { status: 500 }));
    await expect(
      fetchBytesWithRange("http://local/asset", 0, 3),
    ).rejects.toThrow("HTTP 500");
    vi.unstubAllGlobals();
  });
});

describe("PcmSource implementations", () => {
  const bytes = makeSourceBytes(stereoRamp());

  it("falls back to the direct source when no worker exists", async () => {
    const source = await createPcmSource({
      url: "memory://source",
      channelCount: CHANNELS,
      fetchBytes: async (_url, start, end) => applyRange(bytes, start, end),
      workerFactory: () => null,
    });
    expect(source).toBeInstanceOf(DirectPcmSource);
    expect(source.mode).toBe("transfer");
    source.setGeneration(1);
    const chunk = await source.fetchRange(0, 64);
    expect(chunk.frames).toBe(64);
  });

  it("drives the worker adapter on the transfer path", async () => {
    const worker = fakeWorker(bytes, CHANNELS, null);
    const source = await WorkerPcmSource.create(
      worker,
      {
        url: "memory://source",
        channelCount: CHANNELS,
      },
      false,
    );
    expect(source.mode).toBe("transfer");
    source.setGeneration(1);
    const chunk = await source.fetchRange(0, 100);
    expect(chunk.frames).toBe(100);
    expect(chunk.channels![0].length).toBe(100);
    source.dispose();
    expect(worker.terminated).toBe(true);
  });

  it("drives the worker adapter on the shared path", async () => {
    const ring = createSharedRing(256, CHANNELS);
    const worker = fakeWorker(bytes, CHANNELS, ring);
    const source = await WorkerPcmSource.create(
      worker,
      { url: "memory://source", channelCount: CHANNELS, sab: ring.sab },
      true,
    );
    expect(source.mode).toBe("shared");
    source.setGeneration(2);
    await source.acknowledgeFlush(2, 16);
    const chunk = await source.fetchRange(0, 32);
    expect(chunk.frames).toBe(32);
    expect(Atomics.load(ring.header, 1)).toBe(48);
  });

  it("rejects pending fetches when disposed", async () => {
    const worker = fakeWorker(bytes, CHANNELS, null, { neverReply: true });
    const source = await WorkerPcmSource.create(
      worker,
      { url: "memory://source", channelCount: CHANNELS },
      false,
    );
    const pending = source.fetchRange(0, 32);
    source.dispose();
    await expect(pending).rejects.toThrow("fetch source disposed");
  });
});
