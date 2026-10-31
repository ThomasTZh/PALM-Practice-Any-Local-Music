import { describe, expect, it, vi } from "vitest";

import {
  AnalysisError,
  isTerminalAnalysisStatus,
  runAnalysisJob,
  type AnalysisJobClient,
  type AnalysisJobState,
  type AnalysisSnapshot,
} from "./analysis";

const SNAPSHOT: AnalysisSnapshot = {
  bpb: 4,
  bpm: 120,
  key: "C major",
  chords: [{ startSeconds: 0, endSeconds: 2, label: "C:maj" }],
  beats: [0, 0.5, 1, 1.5],
  bars: [0, 2],
  cached: true,
};

function job(
  status: AnalysisJobState["status"],
  progress: number,
  options: { snapshot?: AnalysisSnapshot | null; message?: string; error?: string | null } = {},
): AnalysisJobState {
  return {
    id: "job-1",
    status,
    progress,
    message: options.message ?? status,
    error: options.error ?? null,
    snapshot: options.snapshot ?? null,
  };
}

function fakeClient(states: AnalysisJobState[]): {
  client: AnalysisJobClient;
  start: ReturnType<typeof vi.fn>;
  status: ReturnType<typeof vi.fn>;
} {
  const queue = [...states];
  const start = vi.fn(async () => queue.shift() ?? states[states.length - 1]);
  const status = vi.fn(async () => queue.shift() ?? states[states.length - 1]);
  return {
    client: { start, status },
    start,
    status,
  };
}

describe("isTerminalAnalysisStatus", () => {
  it("recognises every terminal state", () => {
    expect(isTerminalAnalysisStatus("queued")).toBe(false);
    expect(isTerminalAnalysisStatus("running")).toBe(false);
    expect(isTerminalAnalysisStatus("succeeded")).toBe(true);
    expect(isTerminalAnalysisStatus("failed")).toBe(true);
    expect(isTerminalAnalysisStatus("cancelled")).toBe(true);
  });
});

describe("runAnalysisJob", () => {
  it("polls until success and reports progress", async () => {
    const updates: AnalysisJobState[] = [];
    const { client, start, status } = fakeClient([
      job("running", 0.1),
      job("running", 0.6),
      job("succeeded", 1, { snapshot: SNAPSHOT }),
    ]);

    const result = await runAnalysisJob(client, "p1", 4, {
      pollIntervalMs: 1,
      onUpdate: (state) => updates.push(state),
    });

    expect(start).toHaveBeenCalledWith("p1", 4);
    expect(status).toHaveBeenCalledWith("job-1");
    expect(updates.map((state) => state.progress)).toEqual([0.1, 0.6, 1]);
    expect(result.status).toBe("succeeded");
    expect(result.snapshot).toEqual(SNAPSHOT);
  });

  it("fails with the job message and the last state", async () => {
    const { client } = fakeClient([
      job("running", 0.2),
      job("failed", 0.4, { message: "piper crashed", error: "piper crashed" }),
    ]);

    const failure = runAnalysisJob(client, "p1", 4, { pollIntervalMs: 1 });

    await expect(failure).rejects.toBeInstanceOf(AnalysisError);
    await expect(failure).rejects.toMatchObject({
      message: "piper crashed",
      job: expect.objectContaining({ status: "failed" }),
    });
  });

  it("fails on cancellation", async () => {
    const { client } = fakeClient([
      job("running", 0.2),
      job("cancelled", 0.2, { message: "cancelled" }),
    ]);

    await expect(
      runAnalysisJob(client, "p1", 4, { pollIntervalMs: 1 }),
    ).rejects.toMatchObject({ message: "cancelled" });
  });

  it("stops polling when aborted", async () => {
    const controller = new AbortController();
    const { client, status } = fakeClient([job("running", 0.2)]);
    status.mockImplementation(
      () =>
        new Promise((resolve) => {
          controller.abort();
          resolve(job("running", 0.4));
        }),
    );

    const failure = runAnalysisJob(client, "p1", 4, {
      pollIntervalMs: 1,
      signal: controller.signal,
    });

    await expect(failure).rejects.toMatchObject({ name: "AbortError" });
  });

  it("returns the snapshot even when the job carries none", async () => {
    const { client } = fakeClient([job("succeeded", 1)]);
    const result = await runAnalysisJob(client, "p1", 4, { pollIntervalMs: 1 });
    expect(result.snapshot).toBeNull();
  });
});
