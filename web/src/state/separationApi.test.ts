import { describe, expect, it } from "vitest";

import { createSeparationJobClient, SeparationApiError } from "./separationApi";

function response(json: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => json,
    text: async () => JSON.stringify(json),
  } as unknown as Response;
}

const JOB = {
  id: "sep-1",
  kind: "separate",
  state: "running",
  progress: 0.35,
  message: "separating window 2/4",
  result: null,
  error: null,
};

function server(routes: Record<string, Response>) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    return routes[url] ?? response({ detail: "not found" }, 404);
  };
  return { fetchImpl, calls };
}

describe("createSeparationJobClient", () => {
  it("starts separation through POST /api/separate", async () => {
    const { fetchImpl, calls } = server({ "/api/separate": response(JOB) });
    const client = createSeparationJobClient({ fetchImpl });

    const state = await client.start("p1");

    expect(state).toMatchObject({
      id: "sep-1",
      status: "running",
      progress: 0.35,
      message: "separating window 2/4",
    });
    expect(calls[0].url).toBe("/api/separate");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      project_id: "p1",
    });
  });

  it("sends the selected model_id when one is given", async () => {
    const { fetchImpl, calls } = server({ "/api/separate": response(JOB) });
    const client = createSeparationJobClient({ fetchImpl });

    await client.start("p1", "bs-roformer-sw");

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      project_id: "p1",
      model_id: "bs-roformer-sw",
    });
  });

  it("reads progress and ignores the result payload beyond the stem count", async () => {
    const { fetchImpl } = server({
      "/api/jobs/sep-1": response({
        ...JOB,
        state: "succeeded",
        progress: 1,
        result: {
          stems: [
            { label: "drums" },
            { label: "bass" },
            { label: "other" },
            { label: "vocals" },
          ],
        },
      }),
    });

    const state = await createSeparationJobClient({ fetchImpl }).status(
      "sep-1",
    );

    expect(state).toMatchObject({ status: "succeeded", stems: 4, progress: 1 });
  });

  it("cancels with POST /api/jobs/{id}/cancel", async () => {
    const { fetchImpl, calls } = server({
      "/api/jobs/sep-1/cancel": response({
        ...JOB,
        state: "cancelled",
        message: "cancellation requested",
      }),
    });

    const state = await createSeparationJobClient({ fetchImpl }).cancel(
      "sep-1",
    );

    expect(calls[0].url).toBe("/api/jobs/sep-1/cancel");
    expect(calls[0].init?.method).toBe("POST");
    expect(state.status).toBe("cancelled");
  });

  it("reports a server failure with the plain-language detail", async () => {
    const { fetchImpl } = server({
      "/api/separate": response(
        { detail: "the separate job is not installed" },
        400,
      ),
    });

    await expect(
      createSeparationJobClient({ fetchImpl }).start("p1"),
    ).rejects.toMatchObject({
      name: "SeparationApiError",
      status: 400,
      message: "the separate job is not installed",
    });
  });

  it("rejects a malformed job payload", async () => {
    const { fetchImpl } = server({ "/api/separate": response({ nope: true }) });

    await expect(
      createSeparationJobClient({ fetchImpl }).start("p1"),
    ).rejects.toBeInstanceOf(SeparationApiError);
  });
});
