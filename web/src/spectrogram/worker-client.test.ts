import { describe, expect, it } from "vitest";

import type { SpectrogramComputeInput, SpectrogramImage } from "./stft";
import {
  createWorkerSpectrogramEngine,
  type WorkerPortLike,
} from "./worker-client";

class FakeWorker implements WorkerPortLike {
  readonly posted: Array<{ message: unknown; transfer?: Transferable[] }> = [];
  terminated = false;
  private listener: ((event: MessageEvent) => void) | null = null;

  postMessage(message: unknown, transfer?: Transferable[]): void {
    this.posted.push({ message, transfer });
  }

  addEventListener(
    _type: "message",
    listener: (event: MessageEvent) => void,
  ): void {
    this.listener = listener;
  }

  removeEventListener(
    _type: "message",
    _listener: (event: MessageEvent) => void,
  ): void {
    this.listener = null;
  }

  terminate(): void {
    this.terminated = true;
  }

  emit(data: unknown): void {
    this.listener?.({ data } as MessageEvent);
  }
}

const INPUT: SpectrogramComputeInput = {
  pcm: new Float32Array([0.1, 0.2, 0.3]),
  pcmStartSeconds: 0,
  sampleRate: 44100,
  startSeconds: 0,
  secondsPerPixel: 0.01,
  widthPx: 8,
  rows: 4,
  fftSize: 2048,
};

function image(): SpectrogramImage {
  return {
    width: 8,
    height: 4,
    pixels: new Uint8ClampedArray(8 * 4 * 4),
    floorDb: -100,
    ceilingDb: 0,
    fftSize: 2048,
    sampleRate: 44100,
    startSeconds: 0,
    secondsPerPixel: 0.01,
  };
}

describe("worker spectrogram engine", () => {
  it("posts the request with the PCM buffer transferred", async () => {
    const worker = new FakeWorker();
    const engine = createWorkerSpectrogramEngine(() => worker);

    const pending = engine.compute(INPUT);

    expect(worker.posted).toHaveLength(1);
    const { message, transfer } = worker.posted[0];
    expect(message).toMatchObject({
      type: "compute",
      requestId: 1,
      input: INPUT,
    });
    expect(transfer).toEqual([INPUT.pcm.buffer]);

    const result = image();
    worker.emit({ type: "result", requestId: 1, image: result });
    await expect(pending).resolves.toBe(result);
  });

  it("matches concurrent responses by request id", async () => {
    const worker = new FakeWorker();
    const engine = createWorkerSpectrogramEngine(() => worker);

    const first = engine.compute(INPUT);
    const second = engine.compute({ ...INPUT, startSeconds: 5 });
    const firstImage = image();
    const secondImage = { ...image(), startSeconds: 5 };

    worker.emit({ type: "result", requestId: 2, image: secondImage });
    worker.emit({ type: "result", requestId: 1, image: firstImage });

    await expect(first).resolves.toBe(firstImage);
    await expect(second).resolves.toBe(secondImage);
  });

  it("rejects a worker error with its message", async () => {
    const worker = new FakeWorker();
    const engine = createWorkerSpectrogramEngine(() => worker);

    const pending = engine.compute(INPUT);
    worker.emit({ type: "error", requestId: 1, message: "bad input" });

    await expect(pending).rejects.toThrow("bad input");
  });

  it("ignores responses for unknown requests", async () => {
    const worker = new FakeWorker();
    const engine = createWorkerSpectrogramEngine(() => worker);
    const pending = engine.compute(INPUT);

    worker.emit({ type: "result", requestId: 99, image: image() });
    worker.emit({ type: "result", requestId: 1, image: image() });

    await expect(pending).resolves.toBeDefined();
  });

  it("rejects pending work and terminates the worker on dispose", async () => {
    const worker = new FakeWorker();
    const engine = createWorkerSpectrogramEngine(() => worker);
    const pending = engine.compute(INPUT);

    engine.dispose();

    await expect(pending).rejects.toThrow(/disposed/);
    expect(worker.terminated).toBe(true);
    expect(worker.removeEventListener).toBeDefined();
  });

  it("uses the default worker factory shape outside tests", () => {
    // jsdom has no Worker; constructing the default engine must not throw.
    const engine = createWorkerSpectrogramEngine();
    expect(() => engine.dispose()).not.toThrow();
  });
});
