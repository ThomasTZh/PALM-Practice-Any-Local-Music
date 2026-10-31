import { describe, expect, it, vi } from "vitest";

import {
  isTerminalSeparationStatus,
  runSeparationJob,
  SeparationError,
  type SeparationJobClient,
  type SeparationJobState,
} from "./separation";

function job(
  status: SeparationJobState["status"],
  progress: number,
  overrides: Partial<SeparationJobState> = {},
): SeparationJobState {
  return {
    id: "job-1",
    status,
    progress,
    message: status,
    error: null,
    stems: null,
    ...overrides,
  };
}

function fakeClient(states: SeparationJobState[]): {
  client: SeparationJobClient;
  start: ReturnType<typeof vi.fn>;
  status: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
} {
  const queue = [...states];
  const start = vi.fn(async () => queue.shift() ?? states[0]);
  const status = vi.fn(async () => queue.shift() ?? states[states.length - 1]);
  const cancel = vi.fn(async () => job("cancelled", 0));
  return { client: { start, status, cancel }, start, status, cancel };
}

describe("isTerminalSeparationStatus", () => {
  it("treats only finished states as terminal", () => {
    expect(isTerminalSeparationStatus("queued")).toBe(false);
    expect(isTerminalSeparationStatus("running")).toBe(false);
    expect(isTerminalSeparationStatus("succeeded")).toBe(true);
    expect(isTerminalSeparationStatus("failed")).toBe(true);
    expect(isTerminalSeparationStatus("cancelled")).toBe(true);
  });
});

describe("runSeparationJob", () => {
  it("polls progress and stage until success", async () => {
    const updates: SeparationJobState[] = [];
    const { client, start, status } = fakeClient([
      job("queued", 0, { message: "queued" }),
      job("running", 0.2, { message: "loading model" }),
      job("running", 0.8, { message: "separating window 3/4" }),
      job("succeeded", 1, { message: "stems ready", stems: 4 }),
    ]);

    const result = await runSeparationJob(client, "p1", {
      pollIntervalMs: 1,
      onUpdate: (state) => updates.push(state),
    });

    expect(start).toHaveBeenCalledWith("p1");
    expect(updates.map((state) => state.progress)).toEqual([0, 0.2, 0.8, 1]);
    expect(updates.map((state) => state.message)).toContain(
      "separating window 3/4",
    );
    expect(result.status).toBe("succeeded");
    expect(result.stems).toBe(4);
    expect(status).toHaveBeenCalledWith("job-1");
  });

  it("fails with the server's plain-language message", async () => {
    const { client } = fakeClient([
      job("running", 0.1),
      job("failed", 0.1, {
        message: "Demucs model bundle is missing",
        error: "Demucs model bundle is missing",
      }),
    ]);

    await expect(
      runSeparationJob(client, "p1", { pollIntervalMs: 1 }),
    ).rejects.toMatchObject({
      name: "SeparationError",
      message: "Demucs model bundle is missing",
    });
  });

  it("fails when the job is cancelled", async () => {
    const { client } = fakeClient([
      job("running", 0.3),
      job("cancelled", 0.3, { message: "cancelled" }),
    ]);

    await expect(
      runSeparationJob(client, "p1", { pollIntervalMs: 1 }),
    ).rejects.toBeInstanceOf(SeparationError);
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

    await expect(
      runSeparationJob(client, "p1", {
        pollIntervalMs: 1,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
