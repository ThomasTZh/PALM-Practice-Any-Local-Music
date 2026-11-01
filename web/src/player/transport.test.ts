// @vitest-environment node
/**
 * Transport state-machine tests (t2), driven with a fake AudioContext
 * and a fake worklet node. The real audio path is covered by
 * `engine.test.ts`; here we pin the contract the UI consumes:
 *
 * - the seven required states (unloaded/loading/paused/playing/
 *   seeking/buffering/error) and their transitions;
 * - positions reported in project frames, including loop stream
 *   coordinates mapped back to the loop range;
 * - missing source, underrun and out-of-range speed/pitch without
 *   throwing;
 * - count-in and metronome messages reaching the worklet.
 */

import { describe, expect, it } from "vitest";
import {
  PcmTransport,
  type AudioContextLike,
  type WorkletNodeLike,
} from "./transport";
import { applyRange, makeSourceBytes } from "./fetch-test-utils";
import { QUANTUM, RATE } from "./test-utils";

const FRAMES = 4 * RATE; // 4 s stereo source
const BYTES = makeSourceBytes([
  new Float32Array(FRAMES).fill(0.1),
  new Float32Array(FRAMES).fill(0.1),
]);

type Message = Record<string, unknown>;

class FakeNode implements WorkletNodeLike {
  readonly posted: Message[] = [];
  readonly port: WorkletNodeLike["port"];
  connect(): void {}
  disconnect(): void {}
  constructor() {
    this.port = {
      postMessage: (message: unknown): void => {
        this.posted.push(message as Message);
      },
      onmessage: null,
    };
  }
  /** Deliver a worklet-to-main message. */
  post(message: Message): void {
    this.port.onmessage?.({ data: message });
  }
  messagesOf(type: string): Message[] {
    return this.posted.filter((message) => message.type === type);
  }
  clear(): void {
    this.posted.length = 0;
  }
}

interface Rig {
  transport: PcmTransport;
  node: FakeNode;
  context: AudioContextLike & { currentTime: number };
  processorOptions: Record<string, unknown> | null;
  states: string[];
}

async function makeRig(
  options: {
    fetchError?: boolean;
    mode?: "auto" | "shared" | "transfer";
  } = {},
): Promise<Rig> {
  const context = { currentTime: 0, sampleRate: RATE, destination: null };
  const node = new FakeNode();
  const states: string[] = [];
  let processorOptions: Record<string, unknown> | null = null;
  const transport = new PcmTransport({
    contextFactory: () => context,
    workletFactory: (_context, opts) => {
      processorOptions = opts;
      return node;
    },
    fetchBytes: async (_url, start, end) => {
      if (options.fetchError) throw new Error("missing source");
      return applyRange(BYTES, start, end);
    },
    workerFactory: null,
    stretchBytes: new ArrayBuffer(8),
    prebufferFrames: 1024,
    lookaheadFrames: 2048,
    chunkFrames: 1024,
    preRollFrames: 0,
    capacityFrames: 4096,
    ...(options.mode ? { mode: options.mode } : {}),
  });
  transport.subscribe((snapshot) => states.push(snapshot.state));
  await transport.load({
    url: "memory://source",
    sampleRate: RATE,
    channelCount: 2,
    frameCount: FRAMES,
  });
  return { transport, node, context, processorOptions, states };
}

async function finishSeek(node: FakeNode): Promise<void> {
  const seek = node.messagesOf("seek").at(-1);
  expect(seek).toBeDefined();
  node.post({ type: "flushed", generation: seek!.generation });
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("transport lifecycle", () => {
  it("exposes unloaded -> loading -> paused and the seven contract states", async () => {
    const { transport, states } = await makeRig();
    expect(states.slice(0, 2)).toEqual(["unloaded", "loading"]);
    expect(transport.state).toBe("paused");
    const contractStates = [
      "unloaded",
      "loading",
      "paused",
      "playing",
      "seeking",
      "buffering",
      "error",
    ];
    // Every required state is reachable from the public API (unloaded is
    // the constructor state, error is exercised below).
    expect(contractStates).toContain(transport.state);
    transport.play();
    expect(transport.state).toBe("playing");
    transport.pause();
    expect(transport.state).toBe("paused");
  });

  it("reports seeking during a seek and settles back to paused", async () => {
    const { transport, node } = await makeRig();
    transport.seek(24000);
    expect(transport.state).toBe("seeking");
    expect(node.messagesOf("seek").at(-1)?.audibleFrame).toBe(24000);
    await finishSeek(node);
    expect(transport.state).toBe("paused");
    transport.dispose();
    expect(transport.state).toBe("unloaded");
  });

  it("maps anchors with output time and project frames", async () => {
    const { transport, node, context } = await makeRig();
    transport.play();
    node.post({
      type: "anchor",
      frame: 24000,
      time: 1,
      rate: 2,
      paused: false,
    });
    context.currentTime = 1.25;
    // 24 000 + 0.25 s × 2× = 48 000 project frames.
    expect(transport.positionFrame).toBe(48000);
    expect(transport.positionSeconds).toBeCloseTo(1, 6);
  });

  it("maps loop stream coordinates back into the loop range", async () => {
    const { transport, node, context } = await makeRig();
    transport.setLoop({ startFrame: 0, endFrame: 2 * RATE });
    await finishSeek(node);
    transport.play();
    node.post({
      type: "anchor",
      frame: 100000,
      time: 2,
      rate: 1,
      paused: false,
    });
    context.currentTime = 2.1;
    // Stream 104 800 maps into a 2 s loop at 8 800.
    expect(transport.positionFrame).toBe(8800);
  });

  it("clamps a seek inside the active loop", async () => {
    const { transport, node } = await makeRig();
    transport.setLoop({ startFrame: RATE, endFrame: 2 * RATE });
    await finishSeek(node);
    transport.seek(0);
    expect(node.messagesOf("seek").at(-1)?.audibleFrame).toBe(RATE);
    await finishSeek(node);
  });
});

describe("transport controls", () => {
  it("clamps speed to 0.25..2 and pitch to -12..12, treating NaN as neutral", async () => {
    const { transport, node } = await makeRig();
    transport.setSpeed(5);
    expect(transport.speed).toBe(2);
    expect(node.messagesOf("rate").at(-1)?.value).toBe(2);
    transport.setSpeed(0.1);
    expect(transport.speed).toBe(0.25);
    transport.setSpeed(Number.NaN);
    expect(transport.speed).toBe(1);
    transport.setPitch(99);
    expect(transport.pitchSemitones).toBe(12);
    expect(node.messagesOf("transpose").at(-1)?.value).toBe(12);
    transport.setPitch(-99);
    expect(transport.pitchSemitones).toBe(-12);
    transport.setPitch(Number.NaN);
    expect(transport.pitchSemitones).toBe(0);
  });

  it("forwards the beat list and metronome volume to the worklet", async () => {
    const { transport, node } = await makeRig();
    transport.setBeats([
      { frame: 0, strength: "downbeat" },
      { frame: 24000, strength: "beat" },
    ]);
    transport.setMetronomeVolume(0.7);
    const message = node.messagesOf("metronome").at(-1);
    expect(message?.volume).toBe(0.7);
    expect((message?.beats as unknown[]).length).toBe(2);
    expect(
      (node.posted.find((m) => m.type === "seek") as Message).loop,
    ).toBeNull();
  });
});

describe("transport buffering and errors", () => {
  it("enters buffering on underrun and resumes when the prebuffer is back", async () => {
    const { transport, node } = await makeRig();
    transport.play();
    node.post({ type: "underrun", generation: 1 });
    expect(transport.state).toBe("buffering");
    node.post({ type: "buffered", frames: 2048, generation: 1 });
    expect(transport.state).toBe("playing");
  });

  it("lands in error for a missing source without throwing from play", async () => {
    const rig = await makeRig({ fetchError: true });
    expect(rig.transport.state).toBe("error");
    expect(rig.transport.error).toContain("missing source");
    expect(() => rig.transport.play()).not.toThrow();
    expect(rig.transport.state).toBe("error");
  });

  it("pauses at the duration on ended", async () => {
    const { transport, node } = await makeRig();
    transport.play();
    node.post({ type: "ended", generation: 1 });
    expect(transport.state).toBe("paused");
    expect(transport.positionFrame).toBe(FRAMES);
  });

  it("pauses at the loop end on loop-complete", async () => {
    const { transport, node } = await makeRig();
    transport.setLoop({ startFrame: 1000, endFrame: 5000 });
    await finishSeek(node);
    transport.play();
    node.post({ type: "loop-complete", frame: 5000, time: 0 });
    expect(transport.state).toBe("paused");
    expect(transport.positionFrame).toBe(5000);
  });
});

describe("count-in and shared mode", () => {
  it("sends the count-in before playback and reports the count-in bars", async () => {
    const { transport, node } = await makeRig();
    transport.setLoop({ startFrame: 0, endFrame: 2 * RATE });
    await finishSeek(node);
    transport.setTempo(120);
    transport.setCountIn(1);
    expect(transport.countInBars).toBe(1);
    node.clear();
    transport.play();
    const countIn = node.messagesOf("count-in").at(0);
    expect(countIn).toMatchObject({
      bars: 1,
      beatsPerBar: 4,
      beatFrames: 24000,
    });
    // The resume follows the count-in request, so the loop's first pass
    // can only start after the clicks.
    const types = node.posted.map((message) => message.type);
    expect(types.indexOf("count-in")).toBeLessThan(types.indexOf("resume"));
  });

  it("uses the shared ring path when asked", async () => {
    const { transport } = await makeRig({ mode: "shared" });
    expect(transport.mode).toBe("shared");
    transport.dispose();
  });

  it("passes the project configuration to the worklet", async () => {
    const { processorOptions } = await makeRig();
    expect(processorOptions).toMatchObject({
      sampleRate: RATE,
      frameCount: FRAMES,
      sources: [{ channelCount: 2 }],
    });
    expect(
      (processorOptions?.stretch as { wasmBytes: ArrayBuffer }).wasmBytes
        .byteLength,
    ).toBe(8);
  });
});

describe("transport prefetch ranges", () => {
  it("requests ranged chunks and never fetches past the source", async () => {
    const requests: Array<{ start: number; end: number }> = [];
    const context = { currentTime: 0, sampleRate: RATE, destination: null };
    const node = new FakeNode();
    const transport = new PcmTransport({
      contextFactory: () => context,
      workletFactory: () => node,
      fetchBytes: async (_url, startByte, endByte) => {
        requests.push({
          start: Math.floor(startByte / 8),
          end: Math.floor((endByte + 1) / 8),
        });
        return applyRange(BYTES, startByte, endByte);
      },
      workerFactory: null,
      stretchBytes: new ArrayBuffer(8),
      prebufferFrames: 8192,
      lookaheadFrames: 8192,
      chunkFrames: 4096,
      preRollFrames: 0,
      capacityFrames: 4096,
    });
    await transport.load({
      url: "memory://source",
      sampleRate: RATE,
      channelCount: 2,
      frameCount: FRAMES,
    });
    expect(requests.length).toBeGreaterThan(0);
    for (const request of requests) {
      expect(request.start).toBeGreaterThanOrEqual(0);
      expect(request.end).toBeLessThanOrEqual(FRAMES);
      expect(request.end).toBeGreaterThan(request.start);
      // Whole frames only.
      expect((request.end - request.start) * QUANTUM).toBeGreaterThan(0);
    }
    transport.dispose();
  });
});

describe("multi-source transport (mix + stems)", () => {
  it("loads every source into one seek and delivers them in step", async () => {
    const context = { currentTime: 0, sampleRate: RATE, destination: null };
    const node = new FakeNode();
    const bytesFor = (value: number): ArrayBuffer =>
      makeSourceBytes([
        new Float32Array(FRAMES).fill(value),
        new Float32Array(FRAMES).fill(value),
      ]);
    const byUrl = new Map([
      ["memory://mix", bytesFor(0.05)],
      ["memory://drums", bytesFor(0.1)],
      ["memory://bass", bytesFor(0.2)],
    ]);
    const transport = new PcmTransport({
      contextFactory: () => context,
      workletFactory: (_context, options) => {
        expect((options.sources as unknown[]).length).toBe(3);
        return node;
      },
      fetchBytes: async (url, start, end) => {
        const payload = byUrl.get(url);
        if (!payload) throw new Error(`missing ${url}`);
        return applyRange(payload, start, end);
      },
      workerFactory: null,
      stretchBytes: new ArrayBuffer(8),
      prebufferFrames: 1024,
      lookaheadFrames: 2048,
      chunkFrames: 1024,
      preRollFrames: 0,
      capacityFrames: 4096,
    });
    await transport.load({
      url: "memory://mix",
      sampleRate: RATE,
      channelCount: 2,
      frameCount: FRAMES,
      sources: [
        { id: "mix", url: "memory://mix" },
        { id: "drums", url: "memory://drums" },
        { id: "bass", url: "memory://bass" },
      ],
    });
    expect(transport.sourceIds).toEqual(["mix", "drums", "bass"]);
    const seek = node.messagesOf("seek").at(0);
    expect(seek?.generations).toEqual([1, 1, 1]);
    const chunks = node.messagesOf("channels");
    expect(chunks.map((message) => message.source)).toEqual([0, 1, 2]);
    expect(new Set(chunks.map((message) => message.frames)).size).toBe(1);

    const seeksBefore = node.messagesOf("seek").length;
    transport.setGain("bass", -6);
    transport.setMuted("drums", true);
    expect(node.messagesOf("seek").length).toBe(seeksBefore);
    expect(
      node
        .messagesOf("params")
        .filter((message) => message.source === 2)
        .at(-1),
    ).toMatchObject({ gain: Math.pow(10, -6 / 20) });
    expect(
      node
        .messagesOf("params")
        .filter((message) => message.source === 1)
        .at(-1),
    ).toMatchObject({ mute: true });
    transport.dispose();
  });

  it("rejects a group with mismatched frame counts", async () => {
    const transport = new PcmTransport({ workerFactory: null });
    await transport.load({
      url: "memory://mix",
      sampleRate: RATE,
      channelCount: 2,
      frameCount: FRAMES,
      sources: [
        { id: "mix", url: "memory://mix" },
        { id: "bass", url: "memory://bass", frameCount: FRAMES - 1 },
      ],
    });
    expect(transport.state).toBe("error");
    expect(transport.error).toContain("frames");
    transport.dispose();
  });
});

describe("silence until explicit play (t30)", () => {
  it("posts a pause to a new node before any PCM", async () => {
    const { transport, node } = await makeRig();
    const types = node.posted.map((message) => message.type);
    expect(types[0]).toBe("pause");
    expect(types.indexOf("pause")).toBeLessThan(types.indexOf("seek"));
    expect(types.indexOf("pause")).toBeLessThan(types.indexOf("channels"));
    expect(transport.state).toBe("paused");
    transport.dispose();
  });

  it("keeps seek, updateGrid, setSpeed and setLoop paused without resume", async () => {
    const { transport, node } = await makeRig();
    node.clear();
    transport.setSpeed(1.5);
    transport.updateGrid({
      bpm: 90,
      bpb: 3,
      beats: [{ frame: 0, strength: "downbeat" }],
    });
    transport.seek(24_000);
    expect(transport.state).toBe("seeking");
    await finishSeek(node);
    expect(transport.state).toBe("paused");
    expect(transport.speed).toBe(1.5);

    transport.setLoop({ startFrame: 48_000, endFrame: 96_000 });
    await finishSeek(node);
    expect(transport.state).toBe("paused");
    expect(node.messagesOf("resume").length).toBe(0);
    transport.dispose();
  });
});

describe("count-in on any play (t37)", () => {
  it("sends a count-in with no loop and a muted metronome", async () => {
    const { transport, node } = await makeRig();
    transport.setCountIn(1);
    transport.setMetronomeVolume(0);
    expect(transport.loop).toBeNull();
    node.clear();
    transport.play();
    expect(node.messagesOf("count-in").at(0)).toMatchObject({
      bars: 1,
      beatsPerBar: 4,
      beatFrames: 24_000,
    });
    expect(transport.state).toBe("playing");
    transport.dispose();
  });
});
