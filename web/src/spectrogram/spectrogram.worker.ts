import type {
  SpectrogramWorkerRequest,
  SpectrogramWorkerResponse,
} from "./protocol";
import { computeSpectrogram } from "./stft";

/**
 * Worker entry point. It owns the CPU-heavy STFT so the UI thread never runs
 * it; the pixel buffer is transferred back, not copied.
 */
interface WorkerScope {
  postMessage(
    message: SpectrogramWorkerResponse,
    transfer?: Transferable[],
  ): void;
  addEventListener(
    type: "message",
    listener: (event: MessageEvent<SpectrogramWorkerRequest>) => void,
  ): void;
}

const scope = self as unknown as WorkerScope;

scope.addEventListener("message", (event) => {
  const request = event.data;
  if (request === null || request.type !== "compute") {
    return;
  }
  try {
    const image = computeSpectrogram(request.input);
    scope.postMessage({ type: "result", requestId: request.requestId, image }, [
      image.pixels.buffer as ArrayBuffer,
    ]);
  } catch (error) {
    scope.postMessage({
      type: "error",
      requestId: request.requestId,
      message: error instanceof Error ? error.message : String(error),
    });
  }
});
