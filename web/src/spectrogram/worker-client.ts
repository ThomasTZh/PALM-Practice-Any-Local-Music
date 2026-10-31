import type {
  SpectrogramWorkerRequest,
  SpectrogramWorkerResponse,
} from "./protocol";
import type { SpectrogramComputeInput, SpectrogramImage } from "./stft";

export interface SpectrogramEngine {
  compute(input: SpectrogramComputeInput): Promise<SpectrogramImage>;
  dispose(): void;
}

/** The subset of `Worker` this module uses, so tests can substitute it. */
export interface WorkerPortLike {
  postMessage(message: unknown, transfer?: Transferable[]): void;
  addEventListener(
    type: "message",
    listener: (event: MessageEvent) => void,
  ): void;
  removeEventListener(
    type: "message",
    listener: (event: MessageEvent) => void,
  ): void;
  terminate?(): void;
}

function defaultWorkerPort(): WorkerPortLike {
  if (typeof Worker === "undefined") {
    throw new Error("Web Workers are unavailable in this environment");
  }
  return new Worker(new URL("./spectrogram.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WorkerPortLike;
}

interface Pending {
  resolve: (image: SpectrogramImage) => void;
  reject: (error: Error) => void;
}

/**
 * Main-thread side of the spectrogram worker. The worker is created on first
 * use (not at import time) so server-side rendering and tests that never ask
 * for a spectrogram do not pay for it.
 */
export function createWorkerSpectrogramEngine(
  createPort: () => WorkerPortLike = defaultWorkerPort,
): SpectrogramEngine {
  let port: WorkerPortLike | null = null;
  let disposed = false;
  let nextRequestId = 1;
  const pending = new Map<number, Pending>();

  function handleMessage(event: MessageEvent): void {
    const response = event.data as SpectrogramWorkerResponse | null;
    if (response === null || typeof response !== "object") {
      return;
    }
    const request = pending.get(response.requestId);
    if (request === undefined) {
      return;
    }
    pending.delete(response.requestId);
    if (response.type === "result") {
      request.resolve(response.image);
    } else {
      request.reject(new Error(response.message));
    }
  }

  function ensurePort(): WorkerPortLike {
    if (disposed) {
      throw new Error("spectrogram worker engine was disposed");
    }
    if (port === null) {
      port = createPort();
      port.addEventListener("message", handleMessage);
    }
    return port;
  }

  return {
    compute(input) {
      if (disposed) {
        return Promise.reject(
          new Error("spectrogram worker engine was disposed"),
        );
      }
      let worker: WorkerPortLike;
      try {
        worker = ensurePort();
      } catch (error) {
        return Promise.reject(
          error instanceof Error ? error : new Error(String(error)),
        );
      }
      const requestId = nextRequestId;
      nextRequestId += 1;
      const request: SpectrogramWorkerRequest = {
        type: "compute",
        requestId,
        input,
      };
      return new Promise<SpectrogramImage>((resolve, reject) => {
        pending.set(requestId, { resolve, reject });
        const buffer = input.pcm.buffer;
        const transfer = buffer instanceof ArrayBuffer ? [buffer] : [];
        worker.postMessage(request, transfer);
      });
    },

    dispose() {
      disposed = true;
      for (const request of pending.values()) {
        request.reject(new Error("spectrogram worker engine was disposed"));
      }
      pending.clear();
      if (port !== null) {
        port.removeEventListener("message", handleMessage);
        port.terminate?.();
        port = null;
      }
    },
  };
}
