// @vitest-environment node
/**
 * StudioPlayer adapter tests (t9): load the mix + four stems as one aligned
 * group, map the engine states onto the UI seam, and drive the fixed
 * MixerController / PracticeController surfaces with a fake worklet.
 *
 * The real audio path is covered by the engine tests; here the fake node
 * lets us script anchors, underruns, ends and seeks deterministically.
 */

import { describe, expect, it } from "vitest";
import {
  createStudioPlayer,
  STEM_LABELS,
  studioPlayerOptionsFromProject,
  type StudioEngine,
} from "./studio-player";
import { applyRange, makeSourceBytes } from "./fetch-test-utils";
import type {
  AudioContextLike,
  TransportOptions,
  WorkletNodeLike,
} from "./transport";

const RATE = 48_000;
const FRAMES = 4 * RATE;
const DURATION = FRAMES / RATE;

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
  engine: StudioEngine;
  node: FakeNode;
  context: AudioContextLike & { currentTime: number };
  processorOptions: Record<string, unknown> | null;
}

function sourceBytes(value: number): ArrayBuffer {
  return makeSourceBytes([
    new Float32Array(FRAMES).fill(value),
    new Float32Array(FRAMES).fill(value),
  ]);
}

async function makeRig(
  options: {
    stems?: boolean;
    missingStems?: boolean;
    autoLoad?: boolean;
    grid?: { bpm: number; bpb: number; beatsSeconds: number[] };
  } = {},
): Promise<Rig> {
  const node = new FakeNode();
  const context = { currentTime: 0, sampleRate: RATE, destination: null };
  let processorOptions: Record<string, unknown> | null = null;
  const bytes = new Map<string, ArrayBuffer>([
    ["memory://mix", sourceBytes(0.05)],
  ]);
  for (const label of STEM_LABELS) {
    bytes.set(`memory://${label}`, sourceBytes(0.1));
  }
  const fetchBytes = async (
    url: string,
    startByte: number,
    endByte: number,
  ): Promise<ArrayBuffer> => {
    if (
      options.missingStems &&
      url.startsWith("memory://") &&
      url !== "memory://mix"
    ) {
      throw new Error("stem cache is missing");
    }
    const payload = bytes.get(url);
    if (!payload) throw new Error(`missing test source ${url}`);
    return applyRange(payload, startByte, endByte);
  };
  const transportOptions: TransportOptions = {
    contextFactory: () => context,
    workletFactory: (_context, opts) => {
      processorOptions = opts;
      return node;
    },
    fetchBytes,
    workerFactory: null,
    stretchBytes: new ArrayBuffer(8),
    prebufferFrames: 1024,
    lookaheadFrames: 2048,
    chunkFrames: 1024,
    preRollFrames: 0,
    capacityFrames: 4096,
  };
  const engine = createStudioPlayer({
    projectId: "project-1",
    sampleRate: RATE,
    channelCount: 2,
    frameCount: FRAMES,
    durationSeconds: DURATION,
    mixUrl: "memory://mix",
    stems:
      options.stems === false
        ? []
        : STEM_LABELS.map((label) => ({ id: label, url: `memory://${label}` })),
    grid: options.grid ?? { bpm: 120, bpb: 4, beatsSeconds: [] },
    transportOptions,
    ...(options.autoLoad === false ? { autoLoad: false } : {}),
  });
  if (options.autoLoad !== false) await engine.ready;
  return { engine, node, context, processorOptions };
}

async function finishSeek(node: FakeNode): Promise<void> {
  const seek = node.messagesOf("seek").at(-1);
  expect(seek).toBeDefined();
  node.post({ type: "flushed", generation: seek!.generation });
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("project loading and stem alignment", () => {
  it("loads the mix and four stems as one group", async () => {
    const { engine, processorOptions } = await makeRig();
    expect(engine.player.getState().status).toBe("paused");
    expect(engine.transport.sourceIds).toEqual(["mix", ...STEM_LABELS]);
    expect(processorOptions?.sources).toEqual(
      Array.from({ length: 5 }, () => ({ channelCount: 2 })),
    );
    // The canonical mix is muted by default so the same performance is not
    // heard twice; the four stems remain audible.
    const mixer = engine.mixer.getState();
    expect(mixer.mix.muted).toBe(true);
    for (const label of STEM_LABELS) {
      expect(mixer[label]).toEqual({
        gainDb: 0,
        pan: 0,
        muted: false,
        soloed: false,
      });
    }
    expect(engine.player.getState().durationSeconds).toBe(DURATION);
    engine.dispose();
  });

  it("falls back to the mix with a user-visible notice when stems are missing", async () => {
    const { engine } = await makeRig({ missingStems: true });
    expect(engine.player.getState().error).toBeNull();
    expect(engine.transport.sourceIds).toEqual(["mix"]);
    expect(engine.getNotice()).toContain("Stems unavailable");
    expect(engine.mixer.getState().mix.muted).toBe(false);
    expect(engine.player.getState().status).toBe("paused");
    engine.dispose();
  });

  it("plays the mix only for an analysis-free project", async () => {
    const { engine } = await makeRig({ stems: false });
    expect(engine.transport.sourceIds).toEqual(["mix"]);
    expect(engine.getNotice()).toBeNull();
    engine.dispose();
  });

  it("builds options from a project and keeps the four server labels", () => {
    const options = studioPlayerOptionsFromProject({
      id: "p1",
      durationSeconds: 10,
      asset: { sampleRate: 44_100, channels: 2 },
      stems: STEM_LABELS.map((label) => ({
        id: `stem-${label}`,
        role: label,
      })),
      grid: { bpm: 100, meter: { numerator: 3 } },
    });
    expect(options.stems?.map((stem) => stem.id)).toEqual([...STEM_LABELS]);
    expect(options.stems?.[0].url).toBe("/api/projects/p1/stems/drums/pcm");
    expect(options.grid).toMatchObject({ bpm: 100, bpb: 3 });
    expect(options.frameCount).toBe(441_000);
  });
});

describe("StudioPlayer state mapping", () => {
  it("maps the seven engine states and only ends after a natural end", async () => {
    const { engine, node } = await makeRig();
    const player = engine.player;
    expect(player.getState().status).toBe("paused");
    player.play();
    expect(player.getState().status).toBe("playing");
    node.post({ type: "ended", generation: 1 });
    expect(player.getState().status).toBe("ended");
    expect(player.getState().positionSeconds).toBe(DURATION);
    player.pause();
    expect(player.getState().status).toBe("ended");

    // A manual seek to the end is not EOF: while seeking it is loading, and
    // once settled it stays paused rather than ended.
    player.seek(DURATION);
    expect(player.getState().status).toBe("loading");
    await finishSeek(node);
    expect(player.getState().status).toBe("paused");
    expect(player.getState().positionSeconds).toBe(DURATION);
    engine.dispose();
  });

  it("does not end an infinite loop while paused mid-loop", async () => {
    const { engine, node } = await makeRig();
    engine.player.setLoopRange({ startSeconds: 1, endSeconds: 2 });
    engine.practice.setLoopEnabled(true);
    await finishSeek(node);
    engine.player.play();
    node.post({
      type: "anchor",
      frame: 90_000,
      time: 1,
      rate: 1,
      paused: true,
    });
    engine.player.pause();
    expect(engine.player.getState().status).toBe("paused");
    expect(engine.player.getState().loopEnabled).toBe(true);
    engine.dispose();
  });

  it("maps speed, pitch, loop seconds and duration onto the engine", async () => {
    const { engine, node } = await makeRig();
    engine.player.setSpeed(1.5);
    expect(engine.practice.getState().speed).toBe(1.5);
    expect(engine.transport.speed).toBe(1.5);
    engine.player.setPitchSemitones(3);
    expect(engine.practice.getState().pitchSemitones).toBe(3);
    expect(engine.transport.pitchSemitones).toBe(3);

    engine.player.setLoopRange({ startSeconds: 1, endSeconds: 2 });
    engine.player.setLoopEnabled(true);
    await finishSeek(node);
    expect(engine.transport.loop).toMatchObject({
      startFrame: RATE,
      endFrame: 2 * RATE,
    });
    expect(engine.player.getState().loopRange).toEqual({
      startSeconds: 1,
      endSeconds: 2,
    });

    engine.player.setDuration(99);
    expect(engine.player.getState().durationSeconds).toBe(DURATION);
    engine.dispose();
  });

  it("seeks and reports a position within 30 ms of the audio anchor", async () => {
    const { engine, node, context } = await makeRig();
    engine.player.play();
    engine.player.seek(1);
    await finishSeek(node);
    node.post({
      type: "anchor",
      frame: 48_000,
      time: 1,
      rate: 1,
      paused: false,
    });
    context.currentTime = 1.01;
    expect(
      Math.abs(engine.player.getState().positionSeconds - 1.01),
    ).toBeLessThanOrEqual(0.03);
    engine.dispose();
  });

  it("changes speed while playing without resetting the position", async () => {
    const { engine, node, context } = await makeRig();
    engine.player.play();
    node.post({
      type: "anchor",
      frame: 96_000,
      time: 1,
      rate: 1,
      paused: false,
    });
    context.currentTime = 1;
    const before = engine.player.getState().positionSeconds;
    const seeksBefore = node.messagesOf("seek").length;
    engine.player.setSpeed(1.5);
    expect(node.messagesOf("seek").length).toBe(seeksBefore);
    node.post({
      type: "anchor",
      frame: 99_600,
      time: 1.05,
      rate: 1.5,
      paused: false,
    });
    context.currentTime = 1.1;
    // The adapter refreshes at the UI tick (50 ms); the anchor itself is
    // exact, so one tick is enough to observe the extrapolated position.
    await new Promise((resolve) => setTimeout(resolve, 120));
    const after = engine.player.getState().positionSeconds;
    expect(after).toBeGreaterThan(before);
    // 0.05 s × 1.5× = 0.075 s of source after the 2.075 s anchor.
    expect(after).toBeCloseTo(2.15, 3);
    engine.dispose();
  });
});

describe("MixerController", () => {
  it("applies gain, pan, mute and solo without a seek", async () => {
    const { engine, node } = await makeRig();
    const seeksBefore = node.messagesOf("seek").length;
    engine.mixer.setGain("bass", -6);
    engine.mixer.setPan("bass", 0.5);
    engine.mixer.setMuted("drums", true);
    engine.mixer.setSoloed("vocals", true);
    const state = engine.mixer.getState();
    expect(state.bass.gainDb).toBe(-6);
    expect(state.bass.pan).toBe(0.5);
    expect(state.drums.muted).toBe(true);
    expect(state.vocals.soloed).toBe(true);
    expect(node.messagesOf("seek").length).toBe(seeksBefore);
    const params = node.messagesOf("params");
    const bass = params.filter((message) => message.source === 2).at(-1);
    expect(bass).toMatchObject({ balance: 0.5, mute: false, solo: false });
    expect(bass?.gain).toBeCloseTo(Math.pow(10, -6 / 20), 6);
    expect(
      params.filter((message) => message.source === 1).at(-1),
    ).toMatchObject({
      mute: true,
    });
    expect(
      params.filter((message) => message.source === 4).at(-1),
    ).toMatchObject({
      solo: true,
    });
    engine.dispose();
  });

  it("keeps a stable snapshot and notifies subscribers", async () => {
    const { engine } = await makeRig();
    const seen: string[] = [];
    const unsubscribe = engine.mixer.subscribe((state) => {
      seen.push(Object.keys(state).join(","));
    });
    const first = engine.mixer.getState();
    expect(engine.mixer.getState()).toBe(first);
    engine.mixer.setMuted("bass", true);
    expect(seen.length).toBeGreaterThan(1);
    unsubscribe();
    engine.dispose();
  });
});

describe("PracticeController", () => {
  it("maps tempo, count-in and metronome beats with the bar accent", async () => {
    const { engine, node } = await makeRig();
    engine.practice.setCountInBars(1);
    engine.practice.setMetronomeEnabled(true);
    engine.practice.setMetronomeVolume(0.7);
    const metronome = node.messagesOf("metronome").at(-1);
    expect(metronome).toMatchObject({ volume: 0.7 });
    const beats = metronome?.beats as Array<{
      frame: number;
      strength: string;
    }>;
    expect(beats.length).toBeGreaterThan(4);
    expect(beats[0].strength).toBe("downbeat");
    expect(beats[1].strength).toBe("beat");
    expect(beats[4].strength).toBe("downbeat");

    engine.practice.setAccentDownbeat(false);
    const flat = node.messagesOf("metronome").at(-1)?.beats as Array<{
      strength: string;
    }>;
    expect(flat.every((beat) => beat.strength === "beat")).toBe(true);
    engine.dispose();
  });

  it("starts a count-in before the first loop pass", async () => {
    const { engine, node } = await makeRig();
    engine.player.setLoopRange({ startSeconds: 0, endSeconds: 2 });
    engine.practice.setLoopEnabled(true);
    await finishSeek(node);
    engine.practice.setCountInBars(1);
    node.clear();
    engine.player.play();
    expect(node.messagesOf("count-in").at(0)).toMatchObject({
      bars: 1,
      beatsPerBar: 4,
      beatFrames: 24_000,
    });
    const types = node.posted.map((message) => message.type);
    expect(types.indexOf("count-in")).toBeLessThan(types.indexOf("resume"));
    engine.dispose();
  });
});

describe("diagnostics and notices", () => {
  it("reports underruns and a user-visible rebuffering notice", async () => {
    const { engine, node } = await makeRig();
    engine.player.play();
    node.post({ type: "underrun", generation: 1 });
    expect(engine.player.getState().status).toBe("loading");
    expect(engine.getNotice()).toBe("Buffering audio…");
    expect(engine.diagnostics().underruns).toBe(1);
    node.post({ type: "buffered", frames: 4096, generation: 1 });
    expect(engine.player.getState().status).toBe("playing");
    engine.dispose();
  });

  it("reports bounded decoder latency and source ids", async () => {
    const { engine, node } = await makeRig();
    node.post({
      type: "stretch-ready",
      inputLatency: 2880,
      outputLatency: 2880,
    });
    const diagnostics = engine.diagnostics();
    expect(diagnostics.latencySeconds).toBeCloseTo((2880 * 2) / RATE, 6);
    expect(diagnostics.sourceIds).toEqual(["mix", ...STEM_LABELS]);
    expect(diagnostics.capacityFrames).toBe(4096);
    engine.dispose();
  });
});
