/**
 * Wire types for the local studio API (t3 foundation).
 *
 * The server returns snake_case canonical fields plus camelCase aliases for the
 * UI. Parsers should accept both spellings; these types describe the canonical
 * document and the aliases that the API guarantees.
 *
 * Peaks binary format (little endian), shared with `peaks.py`:
 *   0..3   "BSPK"
 *   4      u8   version (1)
 *   5      u8   channels
 *   6..7   u16  reserved (0)
 *   8..11  u32  sample rate
 *   12..15 u32  bucket count
 *   16..19 u32  samples per bucket
 *   then per bucket, per channel: int16 min, int16 max, scaled by 1/32767.
 */

export const PEAK_MAGIC = "BSPK";
export const PEAK_VERSION = 1;
export const PEAK_HEADER_SIZE = 20;
export const PEAK_BUCKET_SIZES = [256, 1024, 4096, 16384] as const;
export const DEFAULT_PEAK_BUCKETS = 1024;
export const PCM_MEDIA_TYPE = "application/octet-stream";

export type PeakBucketSize = (typeof PEAK_BUCKET_SIZES)[number];

export interface PeakInfo {
  bucket_size: number;
  count: number;
  channels: number;
  frames: number;
  byte_size: number;
}

export interface AudioInfo {
  asset_id: string;
  sample_rate: number;
  channels: number;
  frames: number;
  duration_seconds: number;
  content_sha256: string;
  source_name: string;
  source_format: string;
  codec: string;
  peaks: Record<string, PeakInfo>;
}

export interface ProjectDocument {
  grid?: unknown;
  key?: string | null;
  stems?: StemInfo[];
  stemCacheKey?: string | null;
  stemModel?: string | null;
  [key: string]: unknown;
}

export interface Project {
  schema_version: number;
  id: string;
  name: string;
  title: string;
  created_at: string;
  updated_at: string;
  revision: number;
  duration_seconds: number;
  durationSeconds: number;
  audio: AudioInfo;
  asset: {
    id: string;
    title: string;
    durationSeconds: number;
    duration_seconds: number;
    sampleRate: number;
    sample_rate: number;
    channels: number;
    frames: number;
    peaks: Record<string, PeakInfo>;
  };
  document: ProjectDocument;
  grid: unknown | null;
  key: string | null;
  stems: unknown[];
}

export interface LibraryEntry {
  id: string;
  title: string;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  importedAt: string;
  projectId: string;
}

export interface LibraryResponse {
  entries: LibraryEntry[];
}

export interface ImportPathRequest {
  path: string;
  name?: string | null;
  sample_rate?: number | null;
}

export interface ProjectUpdateRequest {
  document?: ProjectDocument | null;
  name?: string | null;
  revision?: number | null;
}

export type JobState =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  kind: string;
  state: JobState;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  result: unknown;
  error: string | null;
}

export interface JobCreateRequest {
  kind: string;
  params?: Record<string, unknown>;
}

export interface JobsResponse {
  jobs: Job[];
}

/** SSE frame names used by `/api/jobs/{id}/events`. */
export type JobSseEvent = "progress" | "done";

export interface HealthResponse {
  status: "ok";
  version: string;
  data_root: string;
  ui: boolean;
}

export interface CapabilitiesResponse {
  sample_rates: number[];
  default_sample_rate: number;
  peak_bucket_sizes: PeakBucketSize[];
  max_upload_bytes: number;
  channels: number[];
  pcm_format: string;
}

export interface ApiErrorBody {
  detail: string | Array<Record<string, unknown>>;
}

/** Frame headers returned by the ranged PCM endpoint. */
export interface PcmFrameHeaders {
  frameStart: number;
  frameEnd: number;
  frameCount: number;
  sampleRate: number;
  channels: number;
  totalFrames: number;
}

/** One entry from GET /api/separation/models (local registry + install state). */
export interface SeparationModel {
  id: string;
  name: string;
  engine: "demucs" | "msst" | string;
  engine_command: string;
  labels: string[];
  sample_rate: number;
  size_bytes: number;
  source_url: string;
  license: string;
  bundled: boolean;
  install_dir: string;
  install_command: string;
  checkpoint_manifest: string | null;
  config_name: string | null;
  status: "installed" | "missing" | "hash-mismatch";
  installed: boolean;
  model_dir: string;
  detail: string;
  default: boolean;
  /** Locally measured cost on the 8 s fixture; may be empty for other models. */
  metrics: Record<string, unknown>;
  file_states: Array<Record<string, unknown>>;
}

export interface SeparationModelsResponse {
  default: string;
  models: SeparationModel[];
}

/** Request body for POST /api/separate. */
export interface SeparateRequest {
  project_id: string;
  model_id?: string;
  device?: "auto" | "cpu" | "cuda";
  force?: boolean;
}

/** One stem descriptor persisted in project.document.stems. */
export interface StemInfo {
  label: string;
  frames: number;
  channels: number;
  sampleRate: number;
  sample_rate?: number;
  key: string;
  model?: string | null;
  model_id?: string | null;
  path?: string;
  cache_key?: string;
  url?: string;
}

export interface ProjectStemsResponse {
  project_id: string;
  key: string | null;
  /** Active model id, or null for a project without a stem set. */
  model: string | null;
  model_id: string | null;
  stems: StemInfo[];
}
