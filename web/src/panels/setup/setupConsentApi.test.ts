import { describe, expect, it } from "vitest";

import { createSetupClient } from "../../state/setupApi";

interface Call {
  url: string;
  init?: RequestInit;
}

function response(json: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => json,
    text: async () => JSON.stringify(json),
  } as unknown as Response;
}

function server(routes: Record<string, Response>): {
  fetchImpl: (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>;
  calls: Call[];
} {
  const calls: Call[] = [];
  return {
    calls,
    fetchImpl: async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      return routes[url] ?? response({ detail: "not found" }, 404);
    },
  };
}

const JOB = { id: "setup-1", state: "running", progress: 0.4 };

describe("setup consent requests", () => {
  it("sends environment and media consent plus accepted model ids", async () => {
    const { fetchImpl, calls } = server({
      "/api/setup/media-tools": response(JOB, 202),
      "/api/setup/environments": response(JOB, 202),
      "/api/setup/models": response(JOB, 202),
    });
    const client = createSetupClient({ fetchImpl });

    await client.startMediaTools(true);
    await client.startEnvironment("cpu", true);
    await client.startModels(["htdemucs_ft", "scnet-xl-ihf"], ["htdemucs_ft"]);

    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      accept_licenses: true,
    });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      variant: "cpu",
      accept_licenses: true,
    });
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({
      model_ids: ["htdemucs_ft", "scnet-xl-ihf"],
      accepted_model_ids: ["htdemucs_ft"],
      accept_licenses: true,
    });
  });

  it("surfaces 400 consent details instead of retrying", async () => {
    const { fetchImpl } = server({
      "/api/setup/media-tools": response(
        {
          detail:
            "licence acceptance is required before installing media tools",
        },
        400,
      ),
    });
    const client = createSetupClient({ fetchImpl });

    await expect(client.startMediaTools(true)).rejects.toMatchObject({
      name: "SetupApiError",
      status: 400,
      message: "licence acceptance is required before installing media tools",
    });
  });
});
