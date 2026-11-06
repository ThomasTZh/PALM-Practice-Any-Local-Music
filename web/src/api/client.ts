import type {
  SeparationModel,
  SeparationModelMetrics,
  SeparationModelsResponse,
} from "./types";
import type {
  Asset,
  Grid,
  LibraryEntry,
  Meter,
  Project,
  Stem,
} from "../state/types";

/**
 * Typed client for the local studio server.
 *
 * Every response is parsed once, here, so the panels only ever see the domain
 * types from `state/types.ts`. A malformed response is a boundary failure and
 * becomes an `ApiError`, never an `undefined` that leaks into rendering.
 */

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface PeaksRequestOptions extends RequestOptions {
  /** One of PEAKS_BUCKET_OPTIONS; anything else falls back to 1024. */
  buckets?: number;
}

export interface StudioApi {
  listLibrary(options?: RequestOptions): Promise<LibraryEntry[]>;
  openProject(projectId: string, options?: RequestOptions): Promise<Project>;
  importRecording(file: File, options?: RequestOptions): Promise<LibraryEntry>;
  fetchPeaks(
    assetId: string,
    options?: PeaksRequestOptions,
  ): Promise<ArrayBuffer>;
  fetchStemPeaks(
    projectId: string,
    label: string,
    options?: PeaksRequestOptions,
  ): Promise<ArrayBuffer>;
  fetchSeparationModels(
    options?: RequestOptions,
  ): Promise<SeparationModelsResponse>;
}

export interface StudioApiOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

export const PEAKS_BUCKET_OPTIONS = [256, 1024, 4096, 16384] as const;
export const DEFAULT_PEAKS_BUCKETS = 1024;

/** A failed request or a response that does not match the contract. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type RawRecord = Record<string, unknown>;

function recordOrNull(value: unknown): RawRecord | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as RawRecord;
}

function asRecord(value: unknown, what: string): RawRecord {
  const record = recordOrNull(value);
  if (record === null) {
    throw new ApiError(0, `malformed ${what}: expected an object`);
  }
  return record;
}

function firstString(source: RawRecord | null, keys: string[]): string | null {
  if (!source) {
    return null;
  }
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return null;
}

function firstNumber(
  source: RawRecord | null,
  keys: string[],
  fallback: number,
): number {
  if (!source) {
    return fallback;
  }
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return fallback;
}

function firstPositiveInt(
  source: RawRecord | null,
  keys: string[],
  fallback: number,
): number {
  const value = firstNumber(source, keys, fallback);
  return value > 0 ? Math.round(value) : fallback;
}

function requireId(raw: RawRecord, what: string): string {
  const id = firstString(raw, ["id"]);
  if (id === null) {
    throw new ApiError(0, `malformed ${what}: missing id`);
  }
  return id;
}

function parseMeter(value: unknown): Meter {
  const raw = recordOrNull(value);
  return {
    numerator: firstPositiveInt(raw, ["numerator"], 4),
    denominator: firstPositiveInt(raw, ["denominator"], 4),
  };
}

/** A grid without a tempo is not usable, so it becomes absent instead. */
function parseGrid(value: unknown): Grid | null {
  const raw = recordOrNull(value);
  if (raw === null) {
    return null;
  }
  const bpm = firstNumber(raw, ["bpm"], Number.NaN);
  if (!(bpm > 0)) {
    return null;
  }
  return {
    bpm,
    meter: parseMeter(raw.meter),
    offsetSeconds: firstNumber(raw, ["offsetSeconds", "offset_seconds"], 0),
  };
}

export function parseLibraryEntry(value: unknown): LibraryEntry {
  const raw = asRecord(value, "library entry");
  return {
    id: requireId(raw, "library entry"),
    title: firstString(raw, ["title", "name"]) ?? "Untitled",
    durationSeconds: firstNumber(
      raw,
      ["durationSeconds", "duration_seconds"],
      0,
    ),
    sampleRate: firstPositiveInt(raw, ["sampleRate", "sample_rate"], 44100),
    channels: firstPositiveInt(raw, ["channels"], 2),
    importedAt: firstString(raw, ["importedAt", "imported_at"]) ?? "",
    projectId: firstString(raw, ["projectId", "project_id"]),
  };
}

function parseStem(value: unknown, index: number): Stem {
  const raw = asRecord(value, "stem");
  const id = requireId(raw, "stem");
  return {
    id,
    name: firstString(raw, ["name", "role"]) ?? `Stem ${index + 1}`,
    role: firstString(raw, ["role"]) ?? "other",
    peaksAssetId:
      firstString(raw, ["peaksAssetId", "assetId", "asset_id"]) ?? id,
    audioUrl: firstString(raw, ["audioUrl", "audio_url"]) ?? undefined,
  };
}

export function parseProject(value: unknown): Project {
  const raw = asRecord(value, "project");
  const id = requireId(raw, "project");
  const audio = recordOrNull(raw.audio);
  const assetSource = recordOrNull(raw.asset) ?? audio;
  const durationSeconds = firstNumber(
    raw,
    ["durationSeconds", "duration_seconds"],
    firstNumber(audio, ["duration_seconds"], 0),
  );
  const title =
    firstString(raw, ["title", "name"]) ??
    firstString(assetSource, ["title"]) ??
    "Untitled project";
  const asset: Asset = {
    id:
      firstString(assetSource, ["id", "asset_id"]) ??
      firstString(audio, ["asset_id"]) ??
      id,
    title: firstString(assetSource, ["title", "name"]) ?? title,
    durationSeconds: firstNumber(
      assetSource,
      ["durationSeconds", "duration_seconds"],
      durationSeconds,
    ),
    sampleRate: firstPositiveInt(
      assetSource,
      ["sampleRate", "sample_rate"],
      44100,
    ),
    channels: firstPositiveInt(assetSource, ["channels"], 2),
  };
  const stemsRaw = Array.isArray(raw.stems) ? raw.stems : [];
  return {
    id,
    title,
    durationSeconds,
    asset,
    grid: parseGrid(raw.grid),
    key: firstString(raw, ["key"]),
    stems: stemsRaw.map(parseStem),
  };
}

function parseModelMetrics(value: unknown): SeparationModelMetrics {
  const raw = recordOrNull(value);
  if (raw === null) {
    return {};
  }
  const metrics: SeparationModelMetrics = {};
  if (typeof raw.device === "string") metrics.device = raw.device;
  if (typeof raw.source === "string") metrics.source = raw.source;
  for (const key of [
    "fixture_seconds",
    "wall_seconds",
    "child_seconds",
    "peak_rss_mib",
  ] as const) {
    const number = raw[key];
    if (typeof number === "number" && Number.isFinite(number)) {
      metrics[key] = number;
    }
  }
  return metrics;
}

function parseSeparationModel(value: unknown): SeparationModel {
  const raw = recordOrNull(value);
  const id = firstString(raw, ["id"]);
  const name = firstString(raw, ["name"]);
  if (raw === null || id === null || name === null) {
    throw new ApiError(0, "malformed separation model: missing id or name");
  }
  const labels = Array.isArray(raw.labels)
    ? raw.labels.filter((label): label is string => typeof label === "string")
    : [];
  const status =
    raw.status === "installed" ||
    raw.status === "missing" ||
    raw.status === "hash-mismatch"
      ? raw.status
      : raw.installed === true
        ? "installed"
        : "missing";
  return {
    id,
    name,
    engine: firstString(raw, ["engine"]) ?? "demucs",
    engine_command: firstString(raw, ["engine_command"]) ?? "",
    labels,
    sample_rate: firstNumber(raw, ["sample_rate"], 44100),
    size_bytes: firstNumber(raw, ["size_bytes", "size"], 0),
    source_url: firstString(raw, ["source_url"]) ?? "",
    license: firstString(raw, ["license"]) ?? "",
    bundled: raw.bundled === true,
    install_dir: firstString(raw, ["install_dir"]) ?? "",
    install_command: firstString(raw, ["install_command"]) ?? "",
    checkpoint_manifest: firstString(raw, ["checkpoint_manifest"]),
    config_name: firstString(raw, ["config_name"]),
    status,
    installed: raw.installed === true || status === "installed",
    model_dir: firstString(raw, ["model_dir"]) ?? "",
    detail: firstString(raw, ["detail"]) ?? "",
    default: raw.default === true,
    metrics: parseModelMetrics(raw.metrics),
    file_states: Array.isArray(raw.file_states)
      ? raw.file_states.map((state) => recordOrNull(state) ?? {})
      : [],
  };
}

function parseSeparationModels(value: unknown): SeparationModelsResponse {
  const raw = recordOrNull(value);
  if (raw === null || !Array.isArray(raw.models)) {
    throw new ApiError(
      0,
      "malformed separation models: expected a models array",
    );
  }
  const models = raw.models.map(parseSeparationModel);
  return {
    default: firstString(raw, ["default"]),
    models,
  };
}

function normalizeBuckets(buckets: number | undefined): number {
  const requested = buckets ?? DEFAULT_PEAKS_BUCKETS;
  return PEAKS_BUCKET_OPTIONS.includes(
    requested as (typeof PEAKS_BUCKET_OPTIONS)[number],
  )
    ? requested
    : DEFAULT_PEAKS_BUCKETS;
}

async function httpError(response: Response): Promise<ApiError> {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.text();
    if (body.trim().length > 0) {
      try {
        const parsed = JSON.parse(body) as unknown;
        const record = recordOrNull(parsed);
        detail =
          firstString(record, ["detail", "message", "error"]) ?? body.trim();
      } catch {
        detail = body.trim();
      }
    }
  } catch {
    // The status alone is still a usable message.
  }
  return new ApiError(response.status, detail);
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

export function createStudioApi(options: StudioApiOptions = {}): StudioApi {
  const baseUrl = (options.baseUrl ?? "").replace(/\/+$/, "");
  const doFetch: FetchLike =
    options.fetchImpl ?? ((input, init) => fetch(input, init));

  async function call(path: string, init?: RequestInit): Promise<Response> {
    try {
      return await doFetch(`${baseUrl}${path}`, init);
    } catch (error) {
      if (isAbort(error)) {
        throw error;
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new ApiError(0, `cannot reach the studio server: ${message}`);
    }
  }

  async function requestJson(
    path: string,
    what: string,
    init?: RequestInit,
  ): Promise<unknown> {
    const response = await call(path, init);
    if (!response.ok) {
      throw await httpError(response);
    }
    try {
      return await response.json();
    } catch {
      throw new ApiError(
        response.status,
        `malformed ${what}: response was not JSON`,
      );
    }
  }

  return {
    async listLibrary(request: RequestOptions = {}) {
      const payload = await requestJson(
        "/api/library",
        "library",
        request.signal ? { signal: request.signal } : undefined,
      );
      const entries = Array.isArray(payload)
        ? payload
        : recordOrNull(payload)?.entries;
      if (!Array.isArray(entries)) {
        throw new ApiError(0, "malformed library: expected an entries array");
      }
      return entries.map(parseLibraryEntry);
    },

    async openProject(projectId: string, request: RequestOptions = {}) {
      const payload = await requestJson(
        `/api/projects/${encodeURIComponent(projectId)}`,
        "project",
        request.signal ? { signal: request.signal } : undefined,
      );
      const wrapped = recordOrNull(payload)?.project;
      return parseProject(wrapped ?? payload);
    },

    async importRecording(file: File, request: RequestOptions = {}) {
      const body = new FormData();
      body.append("file", file, file.name);
      const payload = await requestJson(
        "/api/library/import",
        "import response",
        {
          method: "POST",
          body,
          ...(request.signal ? { signal: request.signal } : {}),
        },
      );
      const entry = recordOrNull(payload)?.entry ?? payload;
      return parseLibraryEntry(entry);
    },

    async fetchPeaks(assetId: string, request: PeaksRequestOptions = {}) {
      const buckets = normalizeBuckets(request.buckets);
      const response = await call(
        `/api/assets/${encodeURIComponent(assetId)}/peaks?buckets=${buckets}`,
        request.signal ? { signal: request.signal } : undefined,
      );
      if (!response.ok) {
        throw await httpError(response);
      }
      return response.arrayBuffer();
    },

    async fetchSeparationModels(request: RequestOptions = {}) {
      const payload = await requestJson(
        "/api/separation/models",
        "separation models",
        request.signal ? { signal: request.signal } : undefined,
      );
      return parseSeparationModels(payload);
    },

    async fetchStemPeaks(
      projectId: string,
      label: string,
      request: PeaksRequestOptions = {},
    ) {
      const buckets = normalizeBuckets(request.buckets);
      const response = await call(
        `/api/projects/${encodeURIComponent(projectId)}/stems/${encodeURIComponent(label)}/peaks?buckets=${buckets}`,
        request.signal ? { signal: request.signal } : undefined,
      );
      if (!response.ok) {
        throw await httpError(response);
      }
      return response.arrayBuffer();
    },
  };
}
