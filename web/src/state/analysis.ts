import type { ChordRegion } from "./chords";

/** Analysis data the panels read; mirrors the job result contract from t17. */
export interface AnalysisSnapshot {
  bpb: number;
  bpm: number | null;
  key: string | null;
  chords: ChordRegion[];
  beats: number[];
  bars: number[];
  cached: boolean;
}

export type AnalysisJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface AnalysisJobState {
  id: string;
  status: AnalysisJobStatus;
  progress: number;
  message: string;
  error: string | null;
  snapshot: AnalysisSnapshot | null;
}

export interface AnalysisJobClient {
  start(projectId: string, bpb: number): Promise<AnalysisJobState>;
  status(jobId: string): Promise<AnalysisJobState>;
}

export interface AnalysisRunOptions {
  pollIntervalMs?: number;
  signal?: AbortSignal;
  onUpdate?: (state: AnalysisJobState) => void;
}

export class AnalysisError extends Error {
  readonly job: AnalysisJobState;

  constructor(message: string, job: AnalysisJobState) {
    super(message);
    this.name = "AnalysisError";
    this.job = job;
  }
}

export function isTerminalAnalysisStatus(status: AnalysisJobStatus): boolean {
  return (
    status === "succeeded" || status === "failed" || status === "cancelled"
  );
}

function abortError(): Error {
  const error = new Error("analysis job was aborted");
  error.name = "AbortError";
  return error;
}

function checkAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw abortError();
  }
}

function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    function onAbort(): void {
      clearTimeout(timer);
      reject(abortError());
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Starts an analysis job and polls it to a terminal state. The panel supplies
 * the client, so the UI is testable before the server endpoint exists.
 */
export async function runAnalysisJob(
  client: AnalysisJobClient,
  projectId: string,
  bpb: number,
  options: AnalysisRunOptions = {},
): Promise<AnalysisJobState> {
  const pollIntervalMs = options.pollIntervalMs ?? 750;
  checkAborted(options.signal);
  let job = await client.start(projectId, bpb);
  options.onUpdate?.(job);
  while (!isTerminalAnalysisStatus(job.status)) {
    checkAborted(options.signal);
    await delay(pollIntervalMs, options.signal);
    checkAborted(options.signal);
    job = await client.status(job.id);
    options.onUpdate?.(job);
  }
  if (job.status !== "succeeded") {
    throw new AnalysisError(job.error ?? job.message ?? "analysis failed", job);
  }
  return job;
}
