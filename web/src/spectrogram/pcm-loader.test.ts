import { describe, expect, it } from "vitest";

import {
  createRangedPcmLoader,
  PcmLoadError,
  type PcmChunk,
} from "./pcm-loader";

interface ResponseInit {
  status?: number;
  bytes?: ArrayBuffer;
  headers?: Record<string, string>;
  text?: string;
}

function response({
  status = 200,
  bytes = new ArrayBuffer(0),
  headers = {},
  text = "",
}: ResponseInit): Response {
  const normalised = Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]),
  );
  return {
    ok: status >= 200 && status < 300,
    status,
    arrayBuffer: async () => bytes,
    text: async () => text,
    headers: {
      get: (name: string) => normalised[name.toLowerCase()] ?? null,
    },
  } as unknown as Response;
}

function stereoBytes(samples: number[]): ArrayBuffer {
  return new Float32Array(samples).buffer;
}

function pcmResponse(
  samples: number[],
  frames: number,
  channels = 2,
): Response {
  return response({
    bytes: stereoBytes(samples),
    headers: {
      "x-sample-rate": "44100",
      "x-channels": String(channels),
      "x-frame-start": "0",
      "x-frame-end": String(frames),
      "x-frame-count": String(frames),
    },
  });
}

describe("createRangedPcmLoader", () => {
  it("requests a frame range and downmixes interleaved audio to mono", async () => {
    const calls: string[] = [];
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async (input) => {
        calls.push(String(input));
        return pcmResponse([1, 3, 0.5, -0.5], 2);
      },
    });

    const chunk: PcmChunk = await loader(100, 102);

    expect(calls).toEqual(["/api/projects/p1/pcm?start=100&end=102"]);
    expect(chunk.sampleRate).toBe(44100);
    expect(chunk.channels).toBe(2);
    expect(chunk.startFrame).toBe(100);
    expect(chunk.frames).toBe(2);
    expect(Array.from(chunk.samples)).toEqual([2, 0]);
  });

  it("passes a mono stream through unchanged", async () => {
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async () => pcmResponse([0.25, -0.25], 2, 1),
    });

    const chunk = await loader(0, 2);

    expect(Array.from(chunk.samples)).toEqual([0.25, -0.25]);
  });

  it("prefixes the API base URL", async () => {
    const calls: string[] = [];
    const loader = createRangedPcmLoader({
      projectId: "a b",
      baseUrl: "http://127.0.0.1:8765/",
      fetchImpl: async (input) => {
        calls.push(String(input));
        return pcmResponse([0, 0], 1);
      },
    });

    await loader(0, 1);

    expect(calls[0]).toBe(
      "http://127.0.0.1:8765/api/projects/a%20b/pcm?start=0&end=1",
    );
  });

  it("rejects a response without the PCM headers", async () => {
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async () => response({ bytes: new ArrayBuffer(8) }),
    });

    await expect(loader(0, 1)).rejects.toMatchObject({
      name: "PcmLoadError",
      status: 0,
    });
  });

  it("rejects truncated audio instead of returning a short buffer", async () => {
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async () =>
        response({
          bytes: new ArrayBuffer(4),
          headers: { "x-sample-rate": "44100", "x-channels": "2" },
        }),
    });

    await expect(loader(0, 2)).rejects.toBeInstanceOf(PcmLoadError);
  });

  it("reports an HTTP failure with the server detail", async () => {
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async () =>
        response({ status: 404, text: '{"detail":"PCM is missing"}' }),
    });

    await expect(loader(0, 10)).rejects.toMatchObject({
      status: 404,
      message: "PCM is missing",
    });
  });

  it("rethrows an abort instead of wrapping it", async () => {
    const abort = new Error("aborted");
    abort.name = "AbortError";
    const loader = createRangedPcmLoader({
      projectId: "p1",
      fetchImpl: async () => {
        throw abort;
      },
    });

    await expect(loader(0, 1)).rejects.toBe(abort);
  });
});
