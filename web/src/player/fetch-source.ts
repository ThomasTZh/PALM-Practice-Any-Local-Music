/**
 * Main-thread PCM source facade (t2).
 *
 * Two interchangeable implementations behind one interface:
 * - `WorkerPcmSource` posts range jobs to `fetch-worker.ts` (browsers).
 * - `DirectPcmSource` runs the identical `RangedPcmFetcher` on the main
 *   thread (Node tests, or any environment without `Worker`).
 *
 * The transport only sees frame ranges in, a frame count (shared path)
 * or channel arrays (transfer path) out. A seek bumps the generation;
 * in-flight work for the old generation resolves as stale and is
 * dropped, so no stale audio can reach the ring after a reposition.
 */

import { acknowledgeSharedFlush, type SharedRing } from "./pcm";
import {
  RangedPcmFetcher,
  StaleGenerationError,
  type FetchBytes,
  type FetchedChunk,
} from "./fetch-core";

export type PcmMode = "shared" | "transfer";

export interface PcmSource {
  readonly mode: PcmMode;
  /** Ring view on the shared path; null on transfer. */
  readonly ring: SharedRing | null;
  setGeneration(generation: number): void;
  fetchRange(startFrame: number, endFrame: number): Promise<FetchedChunk>;
  acknowledgeFlush(generation: number, baseFrame: number): Promise<void>;
  stop(): void;
  dispose(): void;
}

export interface WorkerLike {
  postMessage(message: unknown, transfer?: Transferable[]): void;
  onmessage: ((event: { data: unknown }) => void) | null;
  terminate(): void;
}

export interface PcmSourceOptions {
  url: string;
  channelCount: number;
  /** When present the source writes into this ring (shared path). */
  sab?: SharedArrayBuffer;
  fetchBytes?: FetchBytes;
  /** Injectable for tests; returning null selects the direct source. */
  workerFactory?: (() => WorkerLike | null) | null;
}

interface PendingFetch {
  resolve: (chunk: FetchedChunk) => void;
  reject: (error: unknown) => void;
}

function defaultWorkerFactory(): WorkerLike | null {
  if (typeof Worker === "undefined") return null;
  return new Worker(new URL("./fetch-worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WorkerLike;
}

/** Worker-backed source (browser production path). */
export class WorkerPcmSource implements PcmSource {
  readonly mode: PcmMode;
  readonly ring: SharedRing | null = null;
  private nextId = 0;
  private readonly pending = new Map<number, PendingFetch>();
  private ready: {
    resolve: () => void;
    reject: (error: unknown) => void;
  } | null = null;
  private flush: {
    resolve: () => void;
    reject: (error: unknown) => void;
  } | null = null;

  private constructor(
    private readonly worker: WorkerLike,
    shared: boolean,
  ) {
    this.mode = shared ? "shared" : "transfer";
    worker.onmessage = (event) => this.onMessage(event.data);
  }

  static async create(
    worker: WorkerLike,
    options: PcmSourceOptions,
    shared: boolean,
  ): Promise<WorkerPcmSource> {
    const source = new WorkerPcmSource(worker, shared);
    await source.init(options);
    return source;
  }

  private init(options: PcmSourceOptions): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ready = { resolve, reject };
      this.worker.postMessage({
        kind: "init",
        url: options.url,
        channelCount: options.channelCount,
        ...(options.sab ? { sab: options.sab } : {}),
      });
    });
  }

  setGeneration(generation: number): void {
    this.worker.postMessage({ kind: "generation", generation });
  }

  fetchRange(startFrame: number, endFrame: number): Promise<FetchedChunk> {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ kind: "fetch", id, startFrame, endFrame });
    });
  }

  acknowledgeFlush(generation: number, baseFrame: number): Promise<void> {
    return new Promise((resolve, reject) => {
      this.flush = { resolve, reject };
      this.worker.postMessage({ kind: "flush-ack", generation, baseFrame });
    });
  }

  private onMessage(data: unknown): void {
    const message = data as Record<string, unknown> | null;
    if (!message || typeof message !== "object") return;
    if (message.kind === "ready") {
      this.ready?.resolve();
      this.ready = null;
      return;
    }
    if (message.kind === "flushed") {
      this.flush?.resolve();
      this.flush = null;
      return;
    }
    const id = message.id;
    if (typeof id !== "number") return;
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    if (message.ok === false) {
      pending.reject(
        message.kind === "stale"
          ? new StaleGenerationError()
          : new Error(
              typeof message.error === "string"
                ? message.error
                : "fetch failed",
            ),
      );
      return;
    }
    pending.resolve({
      startFrame: message.startFrame as number,
      frames: message.frames as number,
      ...(Array.isArray(message.channels)
        ? { channels: message.channels as Float32Array[] }
        : {}),
    });
  }

  stop(): void {
    this.worker.postMessage({ kind: "stop" });
  }

  dispose(): void {
    this.stop();
    this.worker.terminate();
    for (const pending of this.pending.values())
      pending.reject(new Error("fetch source disposed"));
    this.pending.clear();
    this.ready?.reject(new Error("fetch source disposed"));
    this.ready = null;
    this.flush?.reject(new Error("fetch source disposed"));
    this.flush = null;
  }
}

/** Main-thread fallback: identical logic, no worker. */
export class DirectPcmSource implements PcmSource {
  readonly mode: PcmMode;
  readonly ring: SharedRing | null = null;
  private readonly fetcher: RangedPcmFetcher;

  constructor(options: PcmSourceOptions) {
    this.fetcher = new RangedPcmFetcher({
      url: options.url,
      channelCount: options.channelCount,
      ...(options.fetchBytes ? { fetchBytes: options.fetchBytes } : {}),
    });
    if (options.sab) {
      this.ring = this.fetcher.attachShared(options.sab);
      this.mode = "shared";
    } else {
      this.mode = "transfer";
    }
  }

  setGeneration(generation: number): void {
    this.fetcher.setGeneration(generation);
  }

  fetchRange(startFrame: number, endFrame: number): Promise<FetchedChunk> {
    return this.fetcher.fetchRange(startFrame, endFrame);
  }

  async acknowledgeFlush(generation: number, baseFrame: number): Promise<void> {
    this.fetcher.setGeneration(generation);
    if (this.ring) acknowledgeSharedFlush(this.ring, generation, baseFrame);
  }

  stop(): void {}

  dispose(): void {}
}

/**
 * Create the best available source. A worker is used when the runtime
 * provides one and the caller did not disable it; otherwise the direct
 * fallback runs the same code on the main thread.
 */
export async function createPcmSource(
  options: PcmSourceOptions,
): Promise<PcmSource> {
  const factory =
    options.workerFactory === undefined
      ? defaultWorkerFactory
      : options.workerFactory;
  const worker = factory ? factory() : null;
  if (worker) {
    return WorkerPcmSource.create(worker, options, Boolean(options.sab));
  }
  return new DirectPcmSource(options);
}
