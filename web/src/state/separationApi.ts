import type {
  SeparationJobClient,
  SeparationJobState,
  SeparationStatus,
} from "./separation";

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface SeparationApiOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

export class SeparationApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "SeparationApiError";
    this.status = status;
  }
}

type RawRecord = Record<string, unknown>;

const STATUSES: SeparationStatus[] = [
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
  if (source === null) {
    return null;
  }
  for (const key of keys) {
    const value = text(source[key]);
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function firstNumber(source: RawRecord | null, keys: string[]): number | null {
  if (source === null) {
    return null;
  }
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return null;
}

function parseJob(value: unknown): SeparationJobState {
  const record = recordOrNull(value);
  const id = firstText(record, ["id"]);
  const rawStatus = record?.state ?? record?.status;
  const status = STATUSES.find((candidate) => candidate === rawStatus);
  if (record === null || id === null || status === undefined) {
    throw new SeparationApiError(0, "malformed separation job response");
  }
  const result = recordOrNull(record.result);
  const stemsValue = result?.stems;
  return {
    id,
    status,
    progress: Math.min(1, Math.max(0, firstNumber(record, ["progress"]) ?? 0)),
    message: firstText(record, ["message"]) ?? status,
    error: firstText(record, ["error"]),
    stems: Array.isArray(stemsValue) ? stemsValue.length : null,
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
    // The status alone is still a usable message.
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

export function createSeparationJobClient(
  options: SeparationApiOptions = {},
): SeparationJobClient {
  const prefix = (options.baseUrl ?? "").replace(/\/+$/, "");
  const doFetch: FetchLike =
    options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await doFetch(`${prefix}${path}`, init);
    } catch (error) {
      if (isAbort(error)) {
        throw error;
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new SeparationApiError(
        0,
        `cannot reach the studio server: ${message}`,
      );
    }
    if (!response.ok) {
      throw new SeparationApiError(
        response.status,
        await errorDetail(response),
      );
    }
    try {
      return await response.json();
    } catch {
      throw new SeparationApiError(
        response.status,
        "malformed separation response: body was not JSON",
      );
    }
  }

  return {
    async start(projectId) {
      const payload = await request("/api/separate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
      });
      return parseJob(payload);
    },

    async status(jobId) {
      return parseJob(await request(`/api/jobs/${encodeURIComponent(jobId)}`));
    },

    async cancel(jobId) {
      return parseJob(
        await request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
          method: "POST",
        }),
      );
    },
  };
}
