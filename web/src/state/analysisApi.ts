import type {
  AnalysisJobClient,
  AnalysisJobState,
  AnalysisJobStatus,
  AnalysisSnapshot,
} from "./analysis";
import type { ChordRegion } from "./chords";

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface AnalysisApiOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

export class AnalysisApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "AnalysisApiError";
    this.status = status;
  }
}

type RawRecord = Record<string, unknown>;

const STATUSES: AnalysisJobStatus[] = [
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

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstText(source: RawRecord | null, keys: string[]): string | null {
  if (!source) {
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
  if (!source) {
    return null;
  }
  for (const key of keys) {
    const value = numberOrNull(source[key]);
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function parseTimes(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const times: number[] = [];
  for (const entry of value) {
    if (typeof entry === "number" && Number.isFinite(entry)) {
      times.push(entry);
      continue;
    }
    const record = recordOrNull(entry);
    const time = firstNumber(record, [
      "time_seconds",
      "timeSeconds",
      "seconds",
    ]);
    if (time !== null) {
      times.push(time);
    }
  }
  return times;
}

function parseChords(value: unknown): ChordRegion[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const chords: ChordRegion[] = [];
  for (const entry of value) {
    const record = recordOrNull(entry);
    const start = firstNumber(record, ["start_seconds", "startSeconds"]);
    const end = firstNumber(record, ["end_seconds", "endSeconds"]);
    const label = firstText(record, ["label"]);
    if (record === null || start === null || end === null || label === null) {
      continue;
    }
    chords.push({ startSeconds: start, endSeconds: end, label });
  }
  return chords;
}

/** Parses the t17 job result; snake_case and camelCase are both accepted. */
export function parseAnalysisSnapshot(value: unknown): AnalysisSnapshot | null {
  const outer = recordOrNull(value);
  if (outer === null) {
    return null;
  }
  const inner =
    recordOrNull(outer.analysis) ?? recordOrNull(outer.snapshot) ?? outer;
  const bpb = firstNumber(inner, ["bpb", "beatsPerBar", "beats_per_bar"]);
  if (bpb === null || !(bpb > 0)) {
    return null;
  }
  const chords = parseChords(inner.chords);
  if (chords === null) {
    return null;
  }
  const key =
    firstText(inner, ["key", "key_label"]) ??
    firstText(outer, ["key", "key_label"]);
  const cached =
    typeof outer.cached === "boolean"
      ? outer.cached
      : typeof inner.cached === "boolean"
        ? inner.cached
        : false;
  return {
    bpb,
    bpm: firstNumber(inner, ["bpm", "tempo"]),
    key,
    chords,
    beats: parseTimes(inner.beats),
    bars: parseTimes(inner.bars),
    cached,
  };
}

function parseJob(value: unknown): AnalysisJobState {
  const record = recordOrNull(value);
  const id = firstText(record, ["id"]);
  const rawStatus = record?.state ?? record?.status;
  const status = STATUSES.find((candidate) => candidate === rawStatus);
  if (record === null || id === null || status === undefined) {
    throw new AnalysisApiError(0, "malformed analysis job response");
  }
  const progress = firstNumber(record, ["progress"]) ?? 0;
  return {
    id,
    status,
    progress: Math.min(1, Math.max(0, progress)),
    message: firstText(record, ["message"]) ?? status,
    error: firstText(record, ["error"]),
    snapshot: parseAnalysisSnapshot(record.result),
  };
}

async function errorDetail(response: Response): Promise<string> {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.text();
    if (body.trim().length > 0) {
      try {
        const parsed = recordOrNull(JSON.parse(body));
        detail = firstText(parsed, ["detail", "message", "error"]) ?? body.trim();
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

export function createAnalysisJobClient(
  options: AnalysisApiOptions = {},
): AnalysisJobClient {
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
      throw new AnalysisApiError(0, `cannot reach the studio server: ${message}`);
    }
    if (!response.ok) {
      throw new AnalysisApiError(response.status, await errorDetail(response));
    }
    try {
      return await response.json();
    } catch {
      throw new AnalysisApiError(
        response.status,
        "malformed analysis response: body was not JSON",
      );
    }
  }

  return {
    async start(projectId: string, bpb: number) {
      const payload = await request("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: "analysis",
          params: { project_id: projectId, bpb },
        }),
      });
      return parseJob(payload);
    },

    async status(jobId: string) {
      const payload = await request(`/api/jobs/${encodeURIComponent(jobId)}`);
      return parseJob(payload);
    },
  };
}
