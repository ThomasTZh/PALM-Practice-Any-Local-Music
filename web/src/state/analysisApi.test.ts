import { describe, expect, it } from "vitest";

import {
  AnalysisApiError,
  createAnalysisJobClient,
  parseAnalysisSnapshot,
} from "./analysisApi";

interface Route {
  status?: number;
  json?: unknown;
  text?: string;
}

function response({ status = 200, json, text = "" }: Route): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (json === undefined) {
        throw new Error("no json");
      }
      return json;
    },
    text: async () => text,
  } as unknown as Response;
}

function server(routes: Record<string, Route>) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const route = routes[url];
    if (!route) {
      return response({ status: 404, text: "not found" });
    }
    return response(route);
  };
  return { fetchImpl, calls };
}

const JOB = {
  id: "job-1",
  kind: "analysis",
  state: "running",
  progress: 0.25,
  message: "chords",
  created_at: "2026-10-31T18:00:00Z",
  updated_at: "2026-10-31T18:00:01Z",
  result: null,
  error: null,
};

const RESULT = {
  cached: true,
  bpb: 4,
  bpm: 120.185,
  key: "C major",
  chords: [
    { start_seconds: 0, end_seconds: 2, label: "C:maj" },
    { start_seconds: 2, end_seconds: 4, label: "A:min7" },
  ],
  beats: [0, 0.5, 1, 1.5],
  bars: [0, 2],
};

describe("parseAnalysisSnapshot", () => {
  it("parses the job result contract", () => {
    expect(parseAnalysisSnapshot(RESULT)).toEqual({
      bpb: 4,
      bpm: 120.185,
      key: "C major",
      chords: [
        { startSeconds: 0, endSeconds: 2, label: "C:maj" },
        { startSeconds: 2, endSeconds: 4, label: "A:min7" },
      ],
      beats: [0, 0.5, 1, 1.5],
      bars: [0, 2],
      cached: true,
    });
  });

  it("accepts key_label and camelCase fields", () => {
    const snapshot = parseAnalysisSnapshot({
      cached: false,
      bpb: 3,
      bpm: 90,
      key_label: "A minor",
      chords: [{ startSeconds: 1, endSeconds: 3, label: "A:min" }],
      beats: [0.25, 0.75],
      bars: [0.25],
    });

    expect(snapshot).toMatchObject({ key: "A minor", cached: false, bpb: 3 });
    expect(snapshot?.chords[0]).toEqual({
      startSeconds: 1,
      endSeconds: 3,
      label: "A:min",
    });
  });

  it("returns null for an empty or malformed result", () => {
    expect(parseAnalysisSnapshot(null)).toBeNull();
    expect(parseAnalysisSnapshot({})).toBeNull();
    expect(parseAnalysisSnapshot({ bpb: 4, chords: "nope" })).toBeNull();
  });
});

describe("createAnalysisJobClient", () => {
  it("starts a job with the project and bpb", async () => {
    const { fetchImpl, calls } = server({ "/api/jobs": { json: JOB } });
    const client = createAnalysisJobClient({ fetchImpl });

    const state = await client.start("p1", 4);

    expect(state).toMatchObject({
      id: "job-1",
      status: "running",
      progress: 0.25,
      message: "chords",
      snapshot: null,
    });
    expect(calls[0].url).toBe("/api/jobs");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      kind: "analysis",
      params: { project_id: "p1", bpb: 4 },
    });
  });

  it("reads progress and the cached snapshot from the job", async () => {
    const { fetchImpl, calls } = server({
      "/api/jobs/job-1": {
        json: {
          ...JOB,
          state: "succeeded",
          progress: 1,
          message: "done",
          result: RESULT,
        },
      },
    });
    const client = createAnalysisJobClient({ fetchImpl });

    const state = await client.status("job-1");

    expect(calls[0].url).toBe("/api/jobs/job-1");
    expect(state.status).toBe("succeeded");
    expect(state.progress).toBe(1);
    expect(state.snapshot).toMatchObject({
      cached: true,
      key: "C major",
      bpm: 120.185,
    });
    expect(state.snapshot?.chords).toHaveLength(2);
  });

  it("exposes a failed job with its error message", async () => {
    const { fetchImpl } = server({
      "/api/jobs/job-1": {
        json: {
          ...JOB,
          state: "failed",
          progress: 0.4,
          message: "analysis failed",
          error: "piper exited 1",
        },
      },
    });

    const state = await createAnalysisJobClient({ fetchImpl }).status("job-1");

    expect(state).toMatchObject({
      status: "failed",
      message: "analysis failed",
      error: "piper exited 1",
    });
  });

  it("reports a server error with the response detail", async () => {
    const { fetchImpl } = server({
      "/api/jobs": {
        status: 400,
        text: JSON.stringify({ detail: "unknown job kind 'analysis'" }),
      },
    });

    await expect(
      createAnalysisJobClient({ fetchImpl }).start("p1", 4),
    ).rejects.toMatchObject({
      name: "AnalysisApiError",
      status: 400,
      message: "unknown job kind 'analysis'",
    });
  });

  it("rejects a malformed job payload", async () => {
    const { fetchImpl } = server({ "/api/jobs": { json: { nope: true } } });

    await expect(
      createAnalysisJobClient({ fetchImpl }).start("p1", 4),
    ).rejects.toBeInstanceOf(AnalysisApiError);
  });

  it("prefixes the API base URL", async () => {
    const { fetchImpl, calls } = server({
      "http://127.0.0.1:8765/api/jobs": { json: JOB },
    });

    await createAnalysisJobClient({
      baseUrl: "http://127.0.0.1:8765/",
      fetchImpl,
    }).start("p1", 4);

    expect(calls[0].url).toBe("http://127.0.0.1:8765/api/jobs");
  });
});
