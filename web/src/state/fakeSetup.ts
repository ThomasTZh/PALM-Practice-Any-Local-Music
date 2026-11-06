import type { SeparationModel } from "../api/types";
import type { SetupClient, SetupJobState, SetupStatus } from "./setup";
import { HTDEMUCS_MODEL } from "./separationModels";

const SC = {
  ...HTDEMUCS_MODEL,
  id: "scnet-xl-ihf",
  name: "SCNet XL IHF",
  engine: "msst",
  installed: false,
  status: "missing" as const,
  default: false,
  size_bytes: 214069684,
  license: "MIT code; weights by MSST",
  install_command: "make models-install ID=scnet-xl-ihf",
  labels: ["drums", "bass", "other", "vocals"],
  metrics: {
    device: "cpu",
    fixture_seconds: 8,
    wall_seconds: 58.2,
    child_seconds: 55.32,
  },
};

const BS = {
  ...SC,
  id: "bs-roformer-sw",
  name: "BS-RoFormer-SW",
  size_bytes: 699416765,
  license: "Unknown weight licence; MSST code MIT",
  install_command: "make models-install ID=bs-roformer-sw",
  labels: ["bass", "drums", "other", "vocals", "guitar", "piano"],
  metrics: {
    device: "cpu",
    fixture_seconds: 8,
    wall_seconds: 67.35,
    child_seconds: 65.97,
  },
};

const MODELS: SeparationModel[] = [
  { ...HTDEMUCS_MODEL, license: "MIT code; research-use weights" },
  SC,
  BS,
];

export function readySetupStatus(
  overrides: Partial<SetupStatus> = {},
): SetupStatus {
  const models =
    overrides.models ??
    MODELS.map((model) => ({
      ...model,
      installed: true,
      status: "installed" as const,
    }));
  return {
    mode: "source",
    ready: true,
    skipped: false,
    requiresModelChoice: false,
    roots: { app_root: "/studio", data_root: "/studio/data" },
    checks: {
      glibc: { ok: true, status: "ok", detail: "glibc 2.39" },
      disk: {
        ok: true,
        status: "ok",
        detail: "100000 MiB free; 5120 MiB required",
      },
      ffmpeg: { ok: true, status: "ok", detail: "/usr/bin/ffmpeg" },
    },
    tools: {
      sonic_visualiser: {
        installed: true,
        path: "/studio/tools/sv",
        license: "GPL-2.0-or-later",
      },
      vamp_plugin_pack: {
        installed: true,
        path: "/studio/tools/vamp",
        license: "AGPL-3.0",
      },
    },
    environments: {
      cpu: {
        variant: "cpu",
        installed: true,
        path: "/studio/env/cpu",
        python: "/studio/env/cpu/bin/python",
        project: "/studio/analysis-models",
        uv: "/studio/uv",
      },
      cuda: {
        variant: "cuda",
        installed: false,
        path: "/studio/env/cuda",
        python: "/studio/env/cuda/bin/python",
        project: "/studio/analysis-models",
        uv: "/studio/uv",
      },
    },
    models,
    readiness: {
      ready: true,
      checks_ok: true,
      tools_ready: true,
      environment_ready: true,
      model_ready: true,
      requires_model_choice: false,
    },
    registryError: null,
    setupComplete: true,
    ...overrides,
  };
}

export function incompleteSetupStatus(): SetupStatus {
  const base = readySetupStatus();
  const models = MODELS.map((model) => ({
    ...model,
    installed: false,
    status: "missing" as const,
  }));
  return {
    ...base,
    ready: false,
    skipped: false,
    requiresModelChoice: true,
    checks: {
      ...base.checks,
      ffmpeg: { ok: false, status: "missing", detail: "ffmpeg is not on PATH" },
    },
    tools: {
      sonic_visualiser: {
        installed: false,
        path: "/studio/tools/sv",
        license: "GPL-2.0-or-later",
      },
      vamp_plugin_pack: {
        installed: false,
        path: "/studio/tools/vamp",
        license: "AGPL-3.0",
      },
    },
    environments: {
      cpu: { ...base.environments.cpu, installed: false },
      cuda: { ...base.environments.cuda, installed: false },
    },
    models,
    readiness: {
      ready: false,
      checks_ok: false,
      tools_ready: false,
      environment_ready: false,
      model_ready: false,
      requires_model_choice: true,
    },
    setupComplete: false,
  };
}

function job(
  status: SetupJobState["status"],
  progress: number,
  overrides: Partial<SetupJobState> = {},
): SetupJobState {
  return {
    id: "setup-job-1",
    status,
    progress,
    message: status,
    error: null,
    ...overrides,
  };
}

export interface FakeSetupClient extends SetupClient {
  readonly calls: string[];
  setStatus(status: SetupStatus): void;
  getStatus(): SetupStatus;
  enqueueJob(state: SetupJobState): void;
}

export function createFakeSetupClient(
  initial: SetupStatus = readySetupStatus(),
): FakeSetupClient {
  let current = initial;
  const calls: string[] = [];
  const jobs: SetupJobState[] = [];
  return {
    calls,
    setStatus(status) {
      current = status;
    },
    getStatus() {
      return current;
    },
    enqueueJob(state) {
      jobs.push(state);
    },
    async status() {
      calls.push("status");
      return current;
    },
    async skip(skip = true) {
      calls.push(`skip:${skip}`);
      current = { ...current, skipped: skip, ready: false };
      return current;
    },
    async startTools(consent) {
      calls.push(`tools:${consent}`);
      return job("queued", 0, { id: `job-${calls.length}` });
    },
    async startEnvironment(variant) {
      calls.push(`environment:${variant}`);
      return job("queued", 0, { id: `job-${calls.length}` });
    },
    async startModels(modelIds, consent) {
      calls.push(`models:${modelIds.join(",")}:${consent}`);
      return job("queued", 0, { id: `job-${calls.length}` });
    },
    async job(jobId) {
      calls.push(`job:${jobId}`);
      return jobs.shift() ?? job("succeeded", 1, { id: jobId });
    },
    async cancel(jobId) {
      calls.push(`cancel:${jobId}`);
      return job("cancelled", 0, { id: jobId });
    },
  };
}
