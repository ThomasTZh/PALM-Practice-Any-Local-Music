import { describe, expect, it } from "vitest";

import { ApiError, createStudioApi } from "./client";

interface FakeRoute {
  status?: number;
  json?: unknown;
  text?: string;
  bytes?: ArrayBuffer;
}

interface Call {
  url: string;
  init?: RequestInit;
}

function makeResponse(route: FakeRoute): Response {
  const status = route.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (route.json === undefined) {
        throw new Error("no json body");
      }
      return route.json;
    },
    text: async () => route.text ?? JSON.stringify(route.json ?? ""),
    arrayBuffer: async () => route.bytes ?? new ArrayBuffer(0),
  } as unknown as Response;
}

function fakeServer(routes: Record<string, FakeRoute>) {
  const calls: Call[] = [];
  const fetchImpl = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url = String(input);
    calls.push({ url, init });
    const route = routes[url];
    if (!route) {
      return makeResponse({ status: 404, text: "not found" });
    }
    return makeResponse(route);
  };
  return { fetchImpl, calls };
}

const ENTRY = {
  id: "p1",
  title: "Demo take",
  durationSeconds: 8,
  sampleRate: 44100,
  channels: 1,
  importedAt: "2026-10-31T18:00:00Z",
  projectId: "p1",
};

const PROJECT = {
  id: "p1",
  title: "Demo take",
  durationSeconds: 8,
  asset: {
    id: "a1",
    title: "Demo take",
    durationSeconds: 8,
    sampleRate: 44100,
    channels: 1,
  },
  grid: {
    bpm: 120,
    meter: { numerator: 4, denominator: 4 },
    offsetSeconds: 0.25,
  },
  key: "C major",
  stems: [{ id: "s1", name: "Bass", role: "bass", peaksAssetId: "a2" }],
};

describe("listLibrary", () => {
  it("parses the entries envelope", async () => {
    const { fetchImpl } = fakeServer({
      "/api/library": { json: { entries: [ENTRY] } },
    });
    const api = createStudioApi({ fetchImpl });

    await expect(api.listLibrary()).resolves.toEqual([ENTRY]);
  });

  it("also accepts a bare array", async () => {
    const { fetchImpl } = fakeServer({
      "/api/library": { json: [ENTRY] },
    });

    const entries = await createStudioApi({ fetchImpl }).listLibrary();

    expect(entries.map((entry) => entry.id)).toEqual(["p1"]);
  });

  it("fills optional display fields instead of rejecting the list", async () => {
    const { fetchImpl } = fakeServer({
      "/api/library": {
        json: { entries: [{ id: "p1", durationSeconds: 2 }] },
      },
    });

    const [entry] = await createStudioApi({ fetchImpl }).listLibrary();

    expect(entry).toMatchObject({
      id: "p1",
      title: "Untitled",
      sampleRate: 44100,
      channels: 2,
      projectId: null,
    });
  });

  it("reports an HTTP failure with the server detail", async () => {
    const { fetchImpl } = fakeServer({
      "/api/library": {
        status: 500,
        text: JSON.stringify({ detail: "database is busy" }),
      },
    });

    const failure = createStudioApi({ fetchImpl }).listLibrary();

    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 500,
      message: "database is busy",
    });
  });

  it("rejects a malformed entry at the boundary", async () => {
    const { fetchImpl } = fakeServer({
      "/api/library": { json: { entries: [{ title: "no id" }] } },
    });

    await expect(createStudioApi({ fetchImpl }).listLibrary()).rejects.toThrow(
      /missing id/,
    );
  });
});

describe("openProject", () => {
  it("parses the UI aliases, grid and stems", async () => {
    const { fetchImpl, calls } = fakeServer({
      "/api/projects/p1": { json: PROJECT },
    });

    const project = await createStudioApi({ fetchImpl }).openProject("p1");

    expect(calls[0].url).toBe("/api/projects/p1");
    expect(project).toMatchObject({
      id: "p1",
      title: "Demo take",
      durationSeconds: 8,
      key: "C major",
      grid: {
        bpm: 120,
        meter: { numerator: 4, denominator: 4 },
        offsetSeconds: 0.25,
      },
    });
    expect(project.stems).toEqual(PROJECT.stems);
    expect(project.asset.id).toBe("a1");
  });

  it("reads the snake_case superset the server also emits", async () => {
    const { fetchImpl } = fakeServer({
      "/api/projects/p2": {
        json: {
          id: "p2",
          name: "Snake take",
          duration_seconds: 9,
          audio: {
            asset_id: "a9",
            sample_rate: 48000,
            channels: 2,
            duration_seconds: 9,
          },
          grid: null,
          key: null,
          stems: [],
        },
      },
    });

    const project = await createStudioApi({ fetchImpl }).openProject("p2");

    expect(project).toMatchObject({
      title: "Snake take",
      durationSeconds: 9,
      grid: null,
      key: null,
      stems: [],
      asset: { id: "a9", sampleRate: 48000, channels: 2 },
    });
  });

  it("defaults missing grid and stems", async () => {
    const { fetchImpl } = fakeServer({
      "/api/projects/p1": {
        json: { id: "p1", title: "Bare", durationSeconds: 4 },
      },
    });

    const project = await createStudioApi({ fetchImpl }).openProject("p1");

    expect(project.grid).toBeNull();
    expect(project.stems).toEqual([]);
    expect(project.asset.id).toBe("p1");
  });

  it("treats an unusable grid as absent", async () => {
    const { fetchImpl } = fakeServer({
      "/api/projects/p1": {
        json: { ...PROJECT, grid: { bpm: 0, meter: { numerator: 4 } } },
      },
    });

    const project = await createStudioApi({ fetchImpl }).openProject("p1");

    expect(project.grid).toBeNull();
  });
});

describe("fetchPeaks", () => {
  it("requests the default bucket count and returns the bytes", async () => {
    const bytes = new Uint8Array([66, 83, 80, 75]).buffer;
    const { fetchImpl, calls } = fakeServer({
      "/api/assets/a1/peaks?buckets=1024": { bytes },
    });

    const peaks = await createStudioApi({ fetchImpl }).fetchPeaks("a1");

    expect(calls[0].url).toBe("/api/assets/a1/peaks?buckets=1024");
    expect(peaks.byteLength).toBe(4);
  });

  it("accepts the supported higher resolutions", async () => {
    const { fetchImpl, calls } = fakeServer({
      "/api/assets/a1/peaks?buckets=4096": { bytes: new ArrayBuffer(20) },
    });

    await createStudioApi({ fetchImpl }).fetchPeaks("a1", { buckets: 4096 });

    expect(calls[0].url).toBe("/api/assets/a1/peaks?buckets=4096");
  });

  it("falls back to the default when asked for an unsupported size", async () => {
    const { fetchImpl, calls } = fakeServer({
      "/api/assets/a1/peaks?buckets=1024": { bytes: new ArrayBuffer(20) },
    });

    await createStudioApi({ fetchImpl }).fetchPeaks("a1", { buckets: 999 });

    expect(calls[0].url).toBe("/api/assets/a1/peaks?buckets=1024");
  });

  it("reports a failure instead of returning empty bytes", async () => {
    const { fetchImpl } = fakeServer({
      "/api/assets/a1/peaks?buckets=1024": {
        status: 404,
        text: "asset not found",
      },
    });

    await expect(
      createStudioApi({ fetchImpl }).fetchPeaks("a1"),
    ).rejects.toMatchObject({ status: 404, message: "asset not found" });
  });
});

describe("fetchStemPeaks", () => {
  it("requests a stem's peaks by project and label", async () => {
    const { fetchImpl, calls } = fakeServer({
      "/api/projects/p1/stems/vocals/peaks?buckets=4096": {
        bytes: new ArrayBuffer(20),
      },
    });

    const peaks = await createStudioApi({ fetchImpl }).fetchStemPeaks(
      "p1",
      "vocals",
      { buckets: 4096 },
    );

    expect(calls[0].url).toBe(
      "/api/projects/p1/stems/vocals/peaks?buckets=4096",
    );
    expect(peaks.byteLength).toBe(20);
  });

  it("reports a missing stem cache instead of returning empty bytes", async () => {
    const { fetchImpl } = fakeServer({
      "/api/projects/p1/stems/bass/peaks?buckets=1024": {
        status: 404,
        text: "stem peaks not found",
      },
    });

    await expect(
      createStudioApi({ fetchImpl }).fetchStemPeaks("p1", "bass"),
    ).rejects.toMatchObject({ status: 404, message: "stem peaks not found" });
  });
});

describe("importRecording", () => {
  it("posts the file as multipart form data", async () => {
    const { fetchImpl, calls } = fakeServer({
      "/api/library/import": { status: 201, json: { entry: ENTRY } },
    });
    const file = new File([new Uint8Array([1, 2, 3])], "take.wav", {
      type: "audio/wav",
    });

    const entry = await createStudioApi({ fetchImpl }).importRecording(file);

    expect(entry.id).toBe("p1");
    const init = calls[0].init;
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    const sent = (init?.body as FormData).get("file");
    expect(sent).toBeInstanceOf(File);
    expect((sent as File).name).toBe("take.wav");
  });
});

describe("base URL", () => {
  it("prefixes every request when the API lives on another origin", async () => {
    const { fetchImpl, calls } = fakeServer({
      "http://127.0.0.1:8765/api/library": { json: [] },
    });

    await createStudioApi({
      baseUrl: "http://127.0.0.1:8765",
      fetchImpl,
    }).listLibrary();

    expect(calls[0].url).toBe("http://127.0.0.1:8765/api/library");
  });
});
