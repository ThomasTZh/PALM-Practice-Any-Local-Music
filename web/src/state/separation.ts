/** Stem separation job state and polling, mirroring the analysis runner. */

export type SeparationStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface SeparationJobState {
  id: string;
  status: SeparationStatus;
  progress: number;
  message: string;
  error: string | null;
  stems: number | null;
}

export interface SeparationJobClient {
  start(projectId: string, modelId?: string): Promise<SeparationJobState>;
  status(jobId: string): Promise<SeparationJobState>;
  cancel(jobId: string): Promise<SeparationJobState>;
}

export interface SeparationRunOptions {
  pollIntervalMs?: number;
  modelId?: string;
  signal?: AbortSignal;
  onUpdate?: (state: SeparationJobState) => void;
}

export class SeparationError extends Error {
  readonly job: SeparationJobState;

  constructor(message: string, job: SeparationJobState) {
    super(message);
    this.name = "SeparationError";
    this.job = job;
  }
}

export function isTerminalSeparationStatus(status: SeparationStatus): boolean {
  return (
    status === "succeeded" || status === "failed" || status === "cancelled"
  );
}

function abortError(): Error {
  const error = new Error("stem separation was aborted");
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

/** Starts a separation job and polls until a terminal state. */
export async function runSeparationJob(
  client: SeparationJobClient,
  projectId: string,
  options: SeparationRunOptions = {},
): Promise<SeparationJobState> {
  const pollIntervalMs = options.pollIntervalMs ?? 400;
  checkAborted(options.signal);
  let job =
    options.modelId === undefined
      ? await client.start(projectId)
      : await client.start(projectId, options.modelId);
  options.onUpdate?.(job);
  while (!isTerminalSeparationStatus(job.status)) {
    checkAborted(options.signal);
    await delay(pollIntervalMs, options.signal);
    checkAborted(options.signal);
    job = await client.status(job.id);
    checkAborted(options.signal);
    options.onUpdate?.(job);
  }
  if (job.status !== "succeeded") {
    throw new SeparationError(
      job.error ?? job.message ?? "stem separation failed",
      job,
    );
  }
  return job;
}
