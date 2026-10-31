import type { SpectrogramComputeInput, SpectrogramImage } from "./stft";

/** Messages exchanged with the spectrogram Web Worker. */
export interface SpectrogramWorkerRequest {
  type: "compute";
  requestId: number;
  input: SpectrogramComputeInput;
}

export interface SpectrogramWorkerResult {
  type: "result";
  requestId: number;
  image: SpectrogramImage;
}

export interface SpectrogramWorkerError {
  type: "error";
  requestId: number;
  message: string;
}

export type SpectrogramWorkerResponse =
  SpectrogramWorkerResult | SpectrogramWorkerError;
