// @vitest-environment node
/**
 * AudioWorklet adapter test (t2): loads `mix-processor.js` in a
 * faked worklet scope, instantiates the real stretch WASM from the
 * processor options, and plays a seek + channel chunk end to end.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { QUANTUM, RATE, rms, sine, stretchBytes } from "./test-utils";

interface PostedMessage {
  type: string;
  [key: string]: unknown;
}

interface ProcessorInstance {
  port: {
    postMessage(message: unknown): void;
    onmessage: ((event: { data: unknown }) => void) | null;
  };
  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean;
}

describe("player worklet adapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("instantiates the real engine and plays a seeked chunk", async () => {
    const posted: PostedMessage[] = [];
    vi.stubGlobal(
      "AudioWorkletProcessor",
      class {
        port: {
          postMessage: (message: unknown) => void;
          onmessage: ((event: { data: unknown }) => void) | null;
        };
        constructor() {
          this.port = {
            postMessage: (message: unknown) =>
              posted.push(message as PostedMessage),
            onmessage: null,
          };
        }
        process(): boolean {
          return true;
        }
      },
    );
    const register = vi.fn();
    vi.stubGlobal("registerProcessor", register);
    vi.resetModules();
    await import("./mix-processor.js");
    expect(register).toHaveBeenCalledTimes(1);
    const Processor = register.mock.calls[0][1] as new (options: {
      processorOptions: Record<string, unknown>;
    }) => ProcessorInstance;
    const processor = new Processor({
      processorOptions: {
        sampleRate: RATE,
        frameCount: 96_000,
        sources: [{ channelCount: 2 }],
        stretch: { wasmBytes: stretchBytes() },
        rate: 1,
        transpose: 0,
      },
    });
    expect(
      posted.find((message) => message.type === "stretch-ready"),
    ).toMatchObject({
      inputLatency: 2880,
      outputLatency: 2880,
    });
    processor.port.onmessage?.({
      data: { type: "seek", frame: 0, audibleFrame: 0, generation: 0 },
    });
    processor.port.onmessage?.({
      data: {
        type: "channels",
        source: 0,
        channels: [sine(96_000), sine(96_000)],
      },
    });
    const scope = globalThis as unknown as { currentTime?: number };
    let sawAudio = false;
    for (let q = 0; q < 400; q += 1) {
      const outL = new Float32Array(QUANTUM);
      const outR = new Float32Array(QUANTUM);
      scope.currentTime = (q * QUANTUM) / RATE;
      expect(processor.process([], [[outL, outR]])).toBe(true);
      if (rms(outL) > 0.1) sawAudio = true;
    }
    expect(sawAudio).toBe(true);
    expect(posted.some((message) => message.type === "anchor")).toBe(true);
  });
});
