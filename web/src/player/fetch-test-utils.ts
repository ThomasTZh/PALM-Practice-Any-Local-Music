/**
 * Test-only helpers for the ranged PCM fetch suites (t2). A fake
 * dedicated worker that speaks the real `fetch-worker.ts` protocol on
 * top of the same `RangedPcmFetcher`, plus byte/ring readers.
 */

import {
  acknowledgeSharedFlush,
  interleaveF32le,
  type SharedRing,
} from "./pcm";
import { RangedPcmFetcher } from "./fetch-core";
import type { WorkerLike } from "./fetch-source";

export function makeSourceBytes(channels: Float32Array[]): ArrayBuffer {
  return interleaveF32le(channels);
}

/** HTTP `Range` semantics: inclusive end byte. */
export function applyRange(
  bytes: ArrayBuffer,
  startByte: number,
  endByte: number,
): ArrayBuffer {
  return bytes.slice(startByte, Math.min(endByte + 1, bytes.byteLength));
}

/** Read `count` interleaved frames from `ring` starting at slot `startSlot`. */
export function readRingChannel(
  ring: SharedRing,
  channel: number,
  startSlot: number,
  count: number,
): number[] {
  const data = new Float32Array(
    ring.data.buffer,
    ring.data.byteOffset,
    ring.data.byteLength / 4,
  );
  const out: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const slot = (startSlot + i) % ring.frameCapacity;
    out.push(data[slot * ring.channelCount + channel]);
  }
  return out;
}

export interface FakeWorkerOptions {
  /** Drop fetch replies (pending-fetch disposal test). */
  neverReply?: boolean;
}

/**
 * A synchronous-ish fake worker: every posted job is handled on a
 * microtask and answers with the same message shapes as the real
 * `fetch-worker.ts`.
 */
export function fakeWorker(
  bytes: ArrayBuffer,
  channelCount: number,
  ring: SharedRing | null,
  options: FakeWorkerOptions = {},
): WorkerLike & { messages: Record<string, unknown>[]; terminated: boolean } {
  const fetcher = new RangedPcmFetcher({
    url: "memory://source",
    channelCount,
    fetchBytes: async (_url, start, end) => applyRange(bytes, start, end),
  });
  if (ring) fetcher.attachShared(ring.sab);
  const worker = {
    messages: [] as Record<string, unknown>[],
    terminated: false,
    onmessage: null as ((event: { data: unknown }) => void) | null,
    terminate(): void {
      worker.terminated = true;
    },
    postMessage(message: unknown): void {
      const job = message as Record<string, unknown>;
      worker.messages.push(job);
      void handle(job);
    },
  };
  const reply = (
    message: Record<string, unknown>,
    transfer?: Transferable[],
  ): void => {
    worker.onmessage?.({ data: message });
    void transfer;
  };
  async function handle(job: Record<string, unknown>): Promise<void> {
    if (job.kind === "init") {
      reply({ kind: "ready", shared: Boolean(ring) });
      return;
    }
    if (job.kind === "generation") {
      fetcher.setGeneration(job.generation as number);
      return;
    }
    if (job.kind === "flush-ack") {
      fetcher.setGeneration(job.generation as number);
      if (ring)
        acknowledgeSharedFlush(
          ring,
          job.generation as number,
          job.baseFrame as number,
        );
      reply({ kind: "flushed", generation: job.generation });
      return;
    }
    if (job.kind === "stop") return;
    if (job.kind !== "fetch") return;
    if (options.neverReply) return;
    try {
      const chunk = await fetcher.fetchRange(
        job.startFrame as number,
        job.endFrame as number,
      );
      if (chunk.channels) {
        reply({
          id: job.id,
          kind: "chunk",
          ok: true,
          startFrame: chunk.startFrame,
          frames: chunk.frames,
          channels: chunk.channels,
        });
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
      reply({ id: job.id, kind: "error", ok: false, error: String(error) });
    }
  }
  return worker;
}
