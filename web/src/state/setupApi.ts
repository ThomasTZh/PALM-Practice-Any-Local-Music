import type { FetchLike } from "../api/client";
import type { SeparationModel } from "../api/types";
import type {
  SetupCheck,
  SetupClient,
  SetupEnvironment,
  SetupJobState,
  SetupJobStatus,
  SetupStatus,
  SetupTool,
} from "./setup";

export type SetupFetchLike = FetchLike;

export interface SetupApiOptions {
  baseUrl?: string;
  fetchImpl?: SetupFetchLike;
}

export class SetupApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "SetupApiError";
    this.status = status;
  }
}

type RawRecord = Record<string, unknown>;

const STATUSES: SetupJobStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];

function recordOrNull(value: unknown): RawRecord | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as RawRecord;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function firstText(source: RawRecord | null, keys: string[]): string | null {
  if (source === null) return null;
  for (const key of keys) {
    const value = text(source[key]);
    if (value !== null) return value;
  }
  return null;
}

function firstNumber(source: RawRecord | null, keys: string[]): number | null {
  if (source === null) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function bool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function recordMap(value: unknown): Record<string, RawRecord> {
  const raw = recordOrNull(value);
  const result: Record<string, RawRecord> = {};
  if (raw !== null) {
    for (const [key, entry] of Object.entries(raw)) {
      const record = recordOrNull(entry);
      if (record !== null) result[key] = record;
    }
  }
  return result;
}

function parseCheck(value: RawRecord): SetupCheck {
  return {
    ok: bool(value.ok),
    status:
      firstText(value, ["status"]) ?? (value.ok === true ? "ok" : "missing"),
    detail: firstText(value, ["detail"]) ?? "",
  };
}

function parseTool(value: RawRecord): SetupTool {
  return {
    installed: bool(value.installed),
    path: firstText(value, ["path"]) ?? "",
    license: firstText(value, ["license"]) ?? "",
  };
}

function parseEnvironment(value: RawRecord): SetupEnvironment {
  const variant = value.variant === "cuda" ? "cuda" : "cpu";
  return {
    variant,
    installed: bool(value.installed),
    path: firstText(value, ["path"]) ?? "",
    python: firstText(value, ["python"]) ?? "",
    project: firstText(value, ["project"]) ?? "",
    uv: firstText(value, ["uv"]) ?? "",
  };
}

function parseModel(value: RawRecord): SeparationModel {
  const id = firstText(value, ["id"]);
  const name = firstText(value, ["name"]);
  if (id === null || name === null) {
    throw new SetupApiError(0, "malformed setup model: missing id or name");
  }
  const status =
    value.status === "installed" ||
    value.status === "missing" ||
    value.status === "hash-mismatch"
      ? value.status
      : bool(value.installed)
        ? "installed"
        : "missing";
  return {
    id,
    name,
    engine: firstText(value, ["engine"]) ?? "demucs",
    engine_command: firstText(value, ["engine_command"]) ?? "",
    labels: stringList(value.labels),
    sample_rate: firstNumber(value, ["sample_rate"]) ?? 44100,
    size_bytes: firstNumber(value, ["size_bytes", "size"]) ?? 0,
    source_url: firstText(value, ["source_url"]) ?? "",
    license: firstText(value, ["license"]) ?? "",
    bundled: false,
    install_dir: firstText(value, ["install_dir"]) ?? "",
    install_command: firstText(value, ["install_command"]) ?? "",
    checkpoint_manifest: null,
    config_name: null,
    status,
    installed: bool(value.installed) || status === "installed",
    model_dir: firstText(value, ["model_dir"]) ?? "",
    detail: firstText(value, ["detail"]) ?? "",
    default: false,
    metrics: recordOrNull(value.metrics)
      ? (value.metrics as SeparationModel["metrics"])
      : {},
    file_states: Array.isArray(value.file_states)
      ? value.file_states.map((entry) => recordOrNull(entry) ?? {})
      : [],
  };
}

export function parseSetupStatus(value: unknown): SetupStatus {
  const raw = recordOrNull(value);
  if (raw === null) {
    throw new SetupApiError(0, "malformed setup status: expected an object");
  }
  const checks = Object.fromEntries(
    Object.entries(recordMap(raw.checks)).map(([key, entry]) => [
      key,
      parseCheck(entry),
    ]),
  );
  const tools = Object.fromEntries(
    Object.entries(recordMap(raw.tools)).map(([key, entry]) => [
      key,
      parseTool(entry),
    ]),
  );
  const environments = Object.fromEntries(
    Object.entries(recordMap(raw.environments)).map(([key, entry]) => [
      key,
      parseEnvironment(entry),
    ]),
  );
  const models = Array.isArray(raw.models)
    ? raw.models
        .map((entry) => recordOrNull(entry))
        .filter((entry): entry is RawRecord => entry !== null)
        .map(parseModel)
    : [];
  const readinessRaw = recordOrNull(raw.readiness);
  const checksOk =
    firstBoolean(readinessRaw, "checks_ok") ??
    Object.values(checks).every((check) => check.ok);
  const toolsReady =
    firstBoolean(readinessRaw, "tools_ready") ??
    Object.values(tools).every((tool) => tool.installed);
  const environmentReady =
    firstBoolean(readinessRaw, "environment_ready") ??
    Object.values(environments).some((environment) => environment.installed);
  const modelReady =
    firstBoolean(readinessRaw, "model_ready") ??
    models.some((model) => model.installed);
  return {
    mode: firstText(raw, ["mode"]) ?? "source",
    ready:
      firstBoolean(raw, "ready") ??
      (checksOk && environmentReady && modelReady && !bool(raw.skipped)),
    skipped: bool(raw.skipped) || bool(raw.skip),
    requiresModelChoice:
      firstBoolean(raw, "requires_model_choice") ?? !modelReady,
    roots: Object.fromEntries(
      Object.entries(recordOrNull(raw.roots) ?? {}).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    ),
    checks,
    tools,
    environments,
    models,
    readiness: {
      ready:
        firstBoolean(readinessRaw, "ready") ??
        (checksOk && environmentReady && modelReady && !bool(raw.skipped)),
      checks_ok: checksOk,
      tools_ready: toolsReady,
      environment_ready: environmentReady,
      model_ready: modelReady,
      requires_model_choice:
        firstBoolean(readinessRaw, "requires_model_choice") ?? !modelReady,
    },
    registryError: firstText(raw, ["registry_error"]),
    setupComplete: bool(raw.setup_complete),
  };
}

function firstBoolean(source: RawRecord | null, key: string): boolean | null {
  if (source === null) return null;
  const value = source[key];
  return typeof value === "boolean" ? value : null;
}

function parseJob(value: unknown): SetupJobState {
  const raw = recordOrNull(value);
  const id = firstText(raw, ["id"]);
  const rawStatus = raw?.state ?? raw?.status;
  const status = STATUSES.find((candidate) => candidate === rawStatus);
  if (raw === null || id === null || status === undefined) {
    throw new SetupApiError(0, "malformed setup job response");
  }
  return {
    id,
    status,
    progress: Math.min(1, Math.max(0, firstNumber(raw, ["progress"]) ?? 0)),
    message: firstText(raw, ["message"]) ?? status,
    error: firstText(raw, ["error"]),
  };
}

async function errorDetail(response: Response): Promise<string> {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.text();
    if (body.trim().length > 0) {
      try {
        const parsed = recordOrNull(JSON.parse(body));
        detail =
          firstText(parsed, ["detail", "message", "error"]) ?? body.trim();
      } catch {
        detail = body.trim();
      }
    }
  } catch {
    // Keep the status text.
  }
  return detail;
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

export function createSetupClient(options: SetupApiOptions = {}): SetupClient {
  const prefix = (options.baseUrl ?? "").replace(/\/+$/, "");
  const doFetch: FetchLike =
    options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await doFetch(`${prefix}${path}`, init);
    } catch (error) {
      if (isAbort(error)) throw error;
      const message = error instanceof Error ? error.message : String(error);
      throw new SetupApiError(0, `cannot reach the studio server: ${message}`);
    }
    if (!response.ok) {
      throw new SetupApiError(response.status, await errorDetail(response));
    }
    try {
      return await response.json();
    } catch {
      throw new SetupApiError(
        response.status,
        "malformed setup response: body was not JSON",
      );
    }
  }

  function post(path: string, body?: unknown): Promise<unknown> {
    return request(path, {
      method: "POST",
      ...(body === undefined
        ? {}
        : {
            headers: { "content-type": "application/json" },
            body: JSON.stringify(body),
          }),
    });
  }

  return {
    async status(requestOptions = {}) {
      return parseSetupStatus(
        await request(
          "/api/setup/status",
          requestOptions.signal ? { signal: requestOptions.signal } : undefined,
        ),
      );
    },
    async skip(skip = true) {
      return parseSetupStatus(await post("/api/setup/skip", { skip }));
    },
    async startTools(consent) {
      return parseJob(
        await post("/api/setup/tools", { accept_licenses: consent }),
      );
    },
    async startEnvironment(variant) {
      return parseJob(await post("/api/setup/environments", { variant }));
    },
    async startModels(modelIds, consent) {
      return parseJob(
        await post("/api/setup/models", {
          model_ids: modelIds,
          accept_licenses: consent,
        }),
      );
    },
    async job(jobId) {
      return parseJob(await request(`/api/jobs/${encodeURIComponent(jobId)}`));
    },
    async cancel(jobId) {
      return parseJob(
        await post(`/api/jobs/${encodeURIComponent(jobId)}/cancel`),
      );
    },
  };
}
