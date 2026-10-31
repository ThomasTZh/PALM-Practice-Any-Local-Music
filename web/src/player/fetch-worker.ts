/**
 * Ranged PCM fetch worker (t2).
 *
 * Thin dedicated-worker adapter over `RangedPcmFetcher`: the transport
 * posts range jobs and gets transferred channel arrays back (transfer
 * path) or gets a frame count for the SAB ring write (shared path).
 * Keeping the protocol logic in `fetch-core.ts` / `fetch-source.ts`
 * means the same code runs when `Worker` is unavailable (Node tests and
 * older browsers) — there is no second implementation to drift.
 *
 * Messages in:  init, generation, fetch, flush-ack, stop
 * Messages out: ready, chunk | stale | error, flushed
 */

import { acknowledgeSharedFlush } from "./pcm";
import { RangedPcmFetcher, StaleGenerationError } from "./fetch-core";

export type FetchWorkerJob =
  | { kind: "init"; url: string; channelCount: number; sab?: SharedArrayBuffer }
  | { kind: "generation"; generation: number }
  | { kind: "fetch"; id: number; startFrame: number; endFrame: number }
  | { kind: "flush-ack"; generation: number; baseFrame: number }
  | { kind: "stop" };

interface WorkerScope {
  postMessage(message: unknown, transfer?: Transferable[]): void;
  onmessage: ((event: { data: FetchWorkerJob }) => void) | null;
}

let fetcher: RangedPcmFetcher | null = null;

function reply(
  message: Record<string, unknown>,
  transfer?: Transferable[],
): void {
  const scope = self as unknown as WorkerScope;
  if (transfer && transfer.length > 0) scope.postMessage(message, transfer);
  else scope.postMessage(message);
}

async function handle(job: FetchWorkerJob): Promise<void> {
  if (job.kind === "init") {
    fetcher = new RangedPcmFetcher({
      url: job.url,
      channelCount: job.channelCount,
    });
    if (job.sab) fetcher.attachShared(job.sab);
    reply({ kind: "ready", shared: Boolean(job.sab) });
    return;
  }
  if (job.kind === "generation") {
    fetcher?.setGeneration(job.generation);
    return;
  }
  if (job.kind === "flush-ack") {
    fetcher?.setGeneration(job.generation);
    const ring = fetcher?.ringView;
    if (ring) acknowledgeSharedFlush(ring, job.generation, job.baseFrame);
    reply({ kind: "flushed", generation: job.generation });
    return;
  }
  if (job.kind === "stop") return;
  if (job.kind !== "fetch") return;
  if (!fetcher) {
    reply({
      id: job.id,
      kind: "error",
      ok: false,
      error: "fetch worker is not initialised",
    });
    return;
  }
  try {
    const chunk = await fetcher.fetchRange(job.startFrame, job.endFrame);
    if (chunk.channels) {
      reply(
        {
          id: job.id,
          kind: "chunk",
          ok: true,
          startFrame: chunk.startFrame,
          frames: chunk.frames,
          channels: chunk.channels,
        },
        chunk.channels.map((channel) => channel.buffer as ArrayBuffer),
      );
    } else {
      reply({
        id: job.id,
        kind: "shared-chunk",
        ok: true,
        startFrame: chunk.startFrame,
        frames: chunk.frames,
      });
    }
  } catch (error) {
    if (error instanceof StaleGenerationError) {
      reply({ id: job.id, kind: "stale", ok: false });
      return;
    }
    reply({
      id: job.id,
      kind: "error",
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

if (typeof self !== "undefined") {
  const scope = self as unknown as WorkerScope;
  scope.onmessage = (event) => {
    void handle(event.data);
  };
}
