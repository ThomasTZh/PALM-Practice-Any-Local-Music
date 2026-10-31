/**
 * Ranged PCM loader for the spectrogram. The server exposes interleaved
 * little-endian float32 by frame index and reports the format in headers; this
 * module checks the response at the boundary and returns mono samples.
 */

export interface PcmChunk {
  samples: Float32Array;
  sampleRate: number;
  channels: number;
  startFrame: number;
  frames: number;
}

export type PcmLoader = (
  startFrame: number,
  endFrame: number,
  signal?: AbortSignal,
) => Promise<PcmChunk>;

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface RangedPcmLoaderOptions {
  projectId: string;
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

export class PcmLoadError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "PcmLoadError";
    this.status = status;
  }
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

function headerNumber(response: Response, name: string): number {
  const raw = response.headers.get(name);
  if (raw === null) {
    throw new PcmLoadError(0, `PCM response is missing the ${name} header`);
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new PcmLoadError(0, `PCM response has an invalid ${name}: ${raw}`);
  }
  return value;
}

async function httpError(response: Response): Promise<PcmLoadError> {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.text();
    if (body.trim().length > 0) {
      try {
        const parsed = JSON.parse(body) as unknown;
        if (
          typeof parsed === "object" &&
          parsed !== null &&
          typeof (parsed as { detail?: unknown }).detail === "string"
        ) {
          detail = (parsed as { detail: string }).detail;
        } else {
          detail = body.trim();
        }
      } catch {
        detail = body.trim();
      }
    }
  } catch {
    // The status alone is still a usable message.
  }
  return new PcmLoadError(response.status, detail);
}

export function createRangedPcmLoader({
  projectId,
  baseUrl = "",
  fetchImpl,
}: RangedPcmLoaderOptions): PcmLoader {
  const prefix = baseUrl.replace(/\/+$/, "");
  const doFetch: FetchLike = fetchImpl ?? ((input, init) => fetch(input, init));

  return async (startFrame, endFrame, signal) => {
    if (
      !Number.isInteger(startFrame) ||
      !Number.isInteger(endFrame) ||
      startFrame < 0 ||
      endFrame <= startFrame
    ) {
      throw new PcmLoadError(
        0,
        `invalid PCM frame range ${startFrame}..${endFrame}`,
      );
    }
    const url = `${prefix}/api/projects/${encodeURIComponent(projectId)}/pcm?start=${startFrame}&end=${endFrame}`;
    let response: Response;
    try {
      response = await doFetch(url, signal ? { signal } : undefined);
    } catch (error) {
      if (isAbort(error)) {
        throw error;
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new PcmLoadError(0, `cannot load PCM: ${message}`);
    }
    if (!response.ok) {
      throw await httpError(response);
    }

    const sampleRate = headerNumber(response, "x-sample-rate");
    const channels = headerNumber(response, "x-channels");
    const frames = endFrame - startFrame;
    const buffer = await response.arrayBuffer();
    const expectedBytes = frames * channels * 4;
    if (buffer.byteLength !== expectedBytes) {
      throw new PcmLoadError(
        0,
        `PCM response is truncated: expected ${expectedBytes} bytes, got ${buffer.byteLength}`,
      );
    }

    const view = new DataView(buffer);
    const samples = new Float32Array(frames);
    for (let frame = 0; frame < frames; frame += 1) {
      let sum = 0;
      for (let channel = 0; channel < channels; channel += 1) {
        sum += view.getFloat32((frame * channels + channel) * 4, true);
      }
      samples[frame] = sum / channels;
    }

    return {
      samples,
      sampleRate,
      channels,
      startFrame,
      frames,
    };
  };
}
