import type { SeparationModel } from "../api/types";

export type SetupJobStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface SetupJobState {
  id: string;
  status: SetupJobStatus;
  progress: number;
  message: string;
  error: string | null;
}

export interface SetupCheck {
  ok: boolean;
  status: string;
  detail: string;
}

export interface SetupTool {
  installed: boolean;
  path: string;
  license: string;
}

export interface SetupEnvironment {
  variant: "cpu" | "cuda";
  installed: boolean;
  path: string;
  python: string;
  project: string;
  uv: string;
}

export interface SetupReadiness {
  ready: boolean;
  checks_ok: boolean;
  tools_ready: boolean;
  environment_ready: boolean;
  model_ready: boolean;
  requires_model_choice: boolean;
}

export interface SetupStatus {
  mode: string;
  ready: boolean;
  skipped: boolean;
  requiresModelChoice: boolean;
  roots: Record<string, string>;
  checks: Record<string, SetupCheck>;
  tools: Record<string, SetupTool>;
  environments: Record<string, SetupEnvironment>;
  models: SeparationModel[];
  readiness: SetupReadiness;
  registryError: string | null;
  setupComplete: boolean;
}

export interface SetupClient {
  status(options?: { signal?: AbortSignal }): Promise<SetupStatus>;
  skip(skip?: boolean): Promise<SetupStatus>;
  startTools(consent: boolean): Promise<SetupJobState>;
  startEnvironment(
    variant: "cpu" | "cuda",
    consent?: boolean,
  ): Promise<SetupJobState>;
  startModels(
    modelIds: string[],
    acceptedModelIds: string[] | boolean,
  ): Promise<SetupJobState>;
  job(jobId: string): Promise<SetupJobState>;
  cancel(jobId: string): Promise<SetupJobState>;
}

export interface SetupGates {
  canImport: boolean;
  canAnalyze: boolean;
  canSeparate: boolean;
  importReason: string | null;
  analyzeReason: string | null;
  separateReason: string | null;
}

const ENVIRONMENT_ESTIMATES: Record<"cpu" | "cuda", string> = {
  cpu: "~500 MB download",
  cuda: "~3.5 GB download",
};

export function environmentEstimate(variant: "cpu" | "cuda"): string {
  return ENVIRONMENT_ESTIMATES[variant];
}

/**
 * The server exposes readiness booleans; the UI derives per-operation gates so
 * optional tools do not block importing, while analysis needs the Vamp tools
 * and separation additionally needs an installed model.
 */
export function setupGates(status: SetupStatus | null): SetupGates {
  if (status === null) {
    return {
      canImport: false,
      canAnalyze: false,
      canSeparate: false,
      importReason: "Checking studio setup…",
      analyzeReason: "Checking studio setup…",
      separateReason: "Checking studio setup…",
    };
  }
  const checksOk = status.readiness.checks_ok;
  const toolsReady = status.readiness.tools_ready;
  const environmentReady = status.readiness.environment_ready;
  const modelReady = status.readiness.model_ready;
  const canImport = checksOk;
  const canAnalyze = checksOk && toolsReady && environmentReady;
  const canSeparate = canAnalyze && modelReady;
  return {
    canImport,
    canAnalyze,
    canSeparate,
    importReason: canImport
      ? null
      : "Importing needs the system checks to pass. Open Setup to see what is missing.",
    analyzeReason: canAnalyze
      ? null
      : !checksOk
        ? "Analysis needs the system checks to pass. Open Setup to get the studio ready."
        : !toolsReady
          ? "Analysis needs the optional GPL tools (Sonic Visualiser and the Vamp plugin pack). Open Setup to install them."
          : "Analysis needs the CPU or CUDA inference environment. Open Setup to create it.",
    separateReason: canSeparate
      ? null
      : !environmentReady
        ? "Stem separation needs the CPU or CUDA inference environment. Open Setup to create it."
        : !modelReady
          ? "Stem separation needs a separation model. Open Setup to install one."
          : "Stem separation needs the system checks to pass. Open Setup to see what is missing.",
  };
}

export function installedSetupModels(
  status: SetupStatus | null,
): SeparationModel[] {
  return (status?.models ?? []).filter((model) => model.installed);
}
