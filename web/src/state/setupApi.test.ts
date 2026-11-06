import { describe, expect, it } from "vitest";

import { createSetupClient } from "./setupApi";

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

const STATUS = {
  mode: "source",
  ready: false,
  skipped: false,
  requires_model_choice: true,
  roots: { app_root: "/studio", data_root: "/studio/data" },
  checks: {
    glibc: { ok: true, status: "ok", detail: "glibc 2.39" },
    ffmpeg: { ok: false, status: "missing", detail: "ffmpeg is not on PATH" },
  },
  tools: {
    sonic_visualiser: {
      installed: false,
      path: "/tools/sv",
      license: "GPL-2.0",
    },
  },
  environments: {
    cpu: {
      variant: "cpu",
      installed: false,
      path: "/env/cpu",
      python: "/env/cpu/bin/python",
      project: "/analysis-models",
      uv: "/uv",
    },
  },
  models: [
    {
      id: "htdemucs_ft",
      name: "Demucs htdemucs_ft",
      engine: "demucs",
      labels: ["drums", "bass", "other", "vocals"],
      size_bytes: 336565233,
      license: "MIT code; research weights",
      installed: false,
      status: "missing",
      install_command: "make models-install ID=htdemucs_ft",
    },
  ],
  readiness: {
    ready: false,
    checks_ok: false,
    tools_ready: false,
    environment_ready: false,
    model_ready: false,
    requires_model_choice: true,
  },
  registry_error: null,
  setup_complete: false,
};

const JOB = {
  id: "setup-1",
  state: "running",
  progress: 0.4,
  message: "working",
};

describe("setup client", () => {
  it("parses setup status, model cards and readiness", async () => {
    const { fetchImpl, calls } = server({
      "/api/setup/status": response(STATUS),
    });
    const status = await createSetupClient({ fetchImpl }).status();

    expect(calls[0]?.url).toBe("/api/setup/status");
    expect(status.ready).toBe(false);
    expect(status.skipped).toBe(false);
    expect(status.readiness.checks_ok).toBe(false);
    expect(status.checks.ffmpeg.detail).toBe("ffmpeg is not on PATH");
    expect(status.models[0]).toMatchObject({
      id: "htdemucs_ft",
      installed: false,
      status: "missing",
    });
  });

  it("sends skip, consent, environment choice and model ids", async () => {
    const { fetchImpl, calls } = server({
      "/api/setup/skip": response({ ...STATUS, skipped: true }),
      "/api/setup/tools": response(JOB, 202),
      "/api/setup/environments": response(JOB, 202),
      "/api/setup/models": response(JOB, 202),
      "/api/jobs/setup-1": response({
        ...JOB,
        state: "succeeded",
        progress: 1,
      }),
      "/api/jobs/setup-1/cancel": response({ ...JOB, state: "cancelled" }),
    });
    const client = createSetupClient({ fetchImpl });

    await client.skip(true);
    await client.startTools(true);
    await client.startEnvironment("cuda", true);
    await client.startModels(["htdemucs_ft", "scnet-xl-ihf"], ["htdemucs_ft"]);
    await client.job("setup-1");
    await client.cancel("setup-1");

    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ skip: true });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      accept_licenses: true,
    });
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({
      variant: "cuda",
      accept_licenses: true,
    });
    expect(JSON.parse(String(calls[3]?.init?.body))).toEqual({
      model_ids: ["htdemucs_ft", "scnet-xl-ihf"],
      accepted_model_ids: ["htdemucs_ft"],
      accept_licenses: true,
    });
    expect(calls[4]?.url).toBe("/api/jobs/setup-1");
    expect(calls[5]?.url).toBe("/api/jobs/setup-1/cancel");
  });

  it("surfaces server consent rejections with the backend detail", async () => {
    const { fetchImpl } = server({
      "/api/setup/environments": response(
        {
          detail:
            "licence acceptance is required before installing environments",
        },
        400,
      ),
    });
    const client = createSetupClient({ fetchImpl });

    await expect(client.startEnvironment("cpu", true)).rejects.toMatchObject({
      name: "SetupApiError",
      status: 400,
      message: "licence acceptance is required before installing environments",
    });
  });

  it("sends only per-model accepted ids and surfaces missing-consent errors", async () => {
    const { fetchImpl, calls } = server({
      "/api/setup/models": response(
        {
          detail:
            "licence acceptance is required for each requested model: scnet-xl-ihf",
        },
        400,
      ),
    });
    const client = createSetupClient({ fetchImpl });

    await expect(
      client.startModels(["htdemucs_ft", "scnet-xl-ihf"], ["htdemucs_ft"]),
    ).rejects.toMatchObject({
      status: 400,
      message:
        "licence acceptance is required for each requested model: scnet-xl-ihf",
    });
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      model_ids: ["htdemucs_ft", "scnet-xl-ihf"],
      accepted_model_ids: ["htdemucs_ft"],
      accept_licenses: true,
    });
  });
});
