import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makePeaksBuffer } from "./panels/waveform/peaksFixture";
import { createStudioPlayer, type StudioEngine } from "./player/studio-player";
import type {
  AudioContextLike,
  TransportOptions,
  WorkletNodeLike,
} from "./player/transport";
import { applyRange, makeSourceBytes } from "./player/fetch-test-utils";
import type {
  AnalysisJobClient,
  AnalysisJobState,
  AnalysisSnapshot,
} from "./state/analysis";
import {
  parseStudioProject,
  type ShellApi,
  type StudioProject,
} from "./state/project";
import { createShellTransport } from "./state/studioRuntime";
import { App } from "./App";

// The shell falls back to measuring the window in jsdom; 1300 px leaves
// the same 940 px stage the fixed-width tests used for pointer coordinates.
Object.defineProperty(window, "innerWidth", {
  configurable: true,
  writable: true,
  value: 1300,
});

const RATE = 48_000;
const FRAMES = 4 * RATE;
const DURATION = FRAMES / RATE;

const ENGINES: StudioEngine[] = [];

afterEach(() => {
  for (const engine of ENGINES.splice(0)) {
    engine.dispose();
  }
});

const PROJECT = parseStudioProject({
  id: "p1",
  name: "Real engine take",
  revision: 1,
  durationSeconds: DURATION,
  asset: {
    id: "a1",
    sampleRate: RATE,
    channels: 2,
    frames: FRAMES,
  },
  grid: {
    bpm: 120,
    bpb: 4,
    meter: { numerator: 4, denominator: 4 },
    offsetSeconds: 0,
    beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
    bars: [0, 2],
  },
  key: "C major",
  stems: [],
  document: {
    grid: {
      bpm: 120,
      bpb: 4,
      meter: { numerator: 4, denominator: 4 },
      offsetSeconds: 0,
      beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
      bars: [0, 2],
    },
    key: "C major",
    chords: [{ start_seconds: 0, end_seconds: 2, label: "C:maj" }],
    analysis: { bpb: 4, bpm: 120, key: "C major", cached: false },
  },
});

const PROJECT_NO_ANALYSIS = parseStudioProject({
  id: "p1",
  name: "Live analysis take",
  revision: 1,
  durationSeconds: DURATION,
  asset: {
    id: "a1",
    sampleRate: RATE,
    channels: 2,
    frames: FRAMES,
  },
  grid: null,
  key: null,
  stems: [],
  document: {},
});

class FakeNode implements WorkletNodeLike {
  readonly port: WorkletNodeLike["port"];
  readonly messages: Array<Record<string, unknown>> = [];
  constructor() {
    const node = this;
    this.port = {
      onmessage: null,
      postMessage: (message: unknown) => {
        const record = message as Record<string, unknown>;
        node.messages.push(record);
        const seek = record as { type?: string; generation?: number };
        if (seek.type === "seek") {
          setTimeout(() => {
            node.port.onmessage?.({
              data: { type: "flushed", generation: seek.generation },
            });
          }, 0);
        }
      },
    };
  }
  messagesOf(type: string): Array<Record<string, unknown>> {
    return this.messages.filter((message) => message.type === type);
  }
  last(type: string): Record<string, unknown> | undefined {
    return this.messagesOf(type).at(-1);
  }
  connect(): void {}
  disconnect(): void {}
}

function realEngine(project: StudioProject): {
  engine: StudioEngine;
  node: FakeNode;
} {
  const bytes = makeSourceBytes([
    new Float32Array(FRAMES).fill(0.05),
    new Float32Array(FRAMES).fill(0.05),
  ]);
  const context: AudioContextLike & { currentTime: number } = {
    currentTime: 0,
    sampleRate: RATE,
    destination: null,
  };
  const node = new FakeNode();
  const transportOptions: TransportOptions = {
    contextFactory: () => context,
    workletFactory: () => node,
    fetchBytes: async (_url, startByte, endByte) =>
      applyRange(bytes, startByte, endByte),
    workerFactory: null,
    stretchBytes: new ArrayBuffer(8),
    prebufferFrames: 1024,
    lookaheadFrames: 2048,
    chunkFrames: 1024,
    preRollFrames: 0,
    capacityFrames: 4096,
  };
  const analysis = project.analysis;
  const grid =
    analysis !== null
      ? {
          bpm: analysis.bpm ?? 120,
          bpb: analysis.bpb,
          beatsSeconds: analysis.beats,
          offsetSeconds: analysis.beats[0] ?? 0,
        }
      : {
          bpm: project.grid?.bpm ?? 120,
          bpb: project.grid?.meter.numerator ?? 4,
          beatsSeconds: [],
        };
  const engine = createStudioPlayer({
    projectId: "p1",
    sampleRate: RATE,
    channelCount: 2,
    frameCount: FRAMES,
    durationSeconds: DURATION,
    mixUrl: "memory://mix",
    stems: [],
    grid,
    transportOptions,
  });
  ENGINES.push(engine);
  return { engine, node };
}

function shellApi(project: StudioProject): ShellApi {
  return {
    async listLibrary() {
      return [
        {
          id: "p1",
          title: project.title,
          durationSeconds: DURATION,
          sampleRate: RATE,
          channels: 2,
          importedAt: "2026-10-31T18:00:00Z",
          projectId: "p1",
        },
      ];
    },
    async openProject() {
      return project;
    },
    async importRecording() {
      throw new Error("not used");
    },
    async fetchPeaks() {
      return makePeaksBuffer({
        buckets: 64,
        sampleRate: 8000,
        samplesPerBucket: 1000,
      });
    },
    async fetchStemPeaks() {
      return makePeaksBuffer({
        buckets: 64,
        sampleRate: 8000,
        samplesPerBucket: 1000,
      });
    },
    async saveState() {
      return 2;
    },
  };
}

function analysisClient(): AnalysisJobClient {
  return {
    start: vi.fn(),
    status: vi.fn(),
  };
}

function liveAnalysisClient(snapshot: AnalysisSnapshot): AnalysisJobClient {
  const running: AnalysisJobState = {
    id: "job-live",
    status: "running",
    progress: 0.4,
    message: "chords",
    error: null,
    snapshot: null,
  };
  const succeeded: AnalysisJobState = {
    id: "job-live",
    status: "succeeded",
    progress: 1,
    message: "done",
    error: null,
    snapshot,
  };
  return {
    start: vi.fn(async () => running),
    status: vi.fn(async () => succeeded),
  };
}

async function renderRealStudio(
  project: StudioProject = PROJECT,
  client: AnalysisJobClient = analysisClient(),
) {
  let creations = 0;
  let node: FakeNode | null = null;
  let engine: StudioEngine | null = null;
  const transport = createShellTransport(async () => {
    creations += 1;
    const rig = realEngine(project);
    engine = rig.engine;
    node = rig.node;
    await rig.engine.ready;
    return {
      player: rig.engine.player,
      mixer: rig.engine.mixer,
      practice: rig.engine.practice,
      ready: rig.engine.ready,
      getNotice: rig.engine.getNotice,
      subscribeNotice: rig.engine.subscribeNotice,
      diagnostics: rig.engine.diagnostics,
      dispose: rig.engine.dispose,
    };
  });
  render(
    <App
      api={shellApi(project)}
      transport={transport}
      analysisClient={client}
      createPcmLoader={() => async (startFrame, endFrame) => ({
        samples: new Float32Array(2048),
        sampleRate: RATE,
        channels: 2,
        startFrame,
        frames: endFrame - startFrame,
      })}
      autosaveDelayMs={0}
    />,
  );
  await screen.findByRole("button", { name: `Open ${project.title}` });
  await userEvent.click(
    screen.getByRole("button", { name: `Open ${project.title}` }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      `Loaded ${project.title}`,
    ),
  );
  return {
    engine: engine as unknown as StudioEngine,
    node: node as unknown as FakeNode,
    creations: () => creations,
  };
}

describe("App with the real transport adapter", () => {
  it("satisfies StudioPlayer and drives the real transport from the panels", async () => {
    const { engine } = await renderRealStudio();

    expect(engine.player.getState()).toMatchObject({
      status: "paused",
      durationSeconds: DURATION,
      speed: 1,
      loopRange: null,
    });
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(screen.getByTestId("transport-status")).not.toHaveTextContent(
      "Playing",
    );

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() =>
      expect(engine.player.getState().status).toBe("playing"),
    );
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Practice speed"), {
      target: { value: "0.75" },
    });
    await waitFor(() => expect(engine.player.getState().speed).toBe(0.75));
    expect(engine.practice.getState().speed).toBe(0.75);

    const pane = screen.getByTestId("waveform-a1");
    fireEvent.mouseDown(pane, { clientX: 235, button: 0 });
    fireEvent.mouseMove(pane, { clientX: 470 });
    fireEvent.mouseUp(pane, { clientX: 470 });
    fireEvent.click(screen.getByRole("button", { name: "Loop" }));
    await waitFor(() => {
      const loop = engine.player.getState().loopRange;
      expect(loop).not.toBeNull();
      expect(loop?.startSeconds).toBeCloseTo(1);
      expect(loop?.endSeconds).toBeCloseTo(2);
    });
    expect(engine.player.getState().loopEnabled).toBe(true);

    // Clear the transport selection so Add uses the four-bar default.
    fireEvent.mouseDown(pane, { clientX: 470, button: 0 });
    fireEvent.mouseUp(pane, { clientX: 470 });
    await waitFor(() =>
      expect(engine.player.getState().positionSeconds).toBeCloseTo(2),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add section" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Loop Section 1" }),
    );
    await waitFor(() =>
      expect(engine.player.getState().loopRange).toEqual({
        startSeconds: 0,
        endSeconds: 2,
      }),
    );
    expect(engine.player.getState().loopEnabled).toBe(true);

    const follow = screen.getByRole("button", { name: "Follow playhead" });
    await userEvent.click(follow);
    expect(follow).toHaveAttribute("aria-pressed", "false");

    fireEvent.keyDown(screen.getByTestId("waveform-a1"), { key: " " });
    await waitFor(() => expect(engine.player.getState().status).toBe("paused"));
  });

  it("applies completed analysis to the live engine without reopening", async () => {
    const snapshot: AnalysisSnapshot = {
      bpb: 3,
      bpm: 100,
      key: "G major",
      chords: [{ startSeconds: 0, endSeconds: 4, label: "G:maj" }],
      beats: [0, 0.6, 1.2, 1.8, 2.4, 3.0, 3.6],
      bars: [0, 1.8, 3.6],
      cached: false,
    };
    const { engine, node, creations } = await renderRealStudio(
      PROJECT_NO_ANALYSIS,
      liveAnalysisClient(snapshot),
    );

    fireEvent.change(screen.getByLabelText("Count-in"), {
      target: { value: "1" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Add section" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Loop Section 1" }),
    );
    await waitFor(() =>
      expect(engine.player.getState().loopRange).toEqual({
        startSeconds: 0,
        endSeconds: 4,
      }),
    );
    await waitFor(() => expect(engine.player.getState().status).toBe("paused"));

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() =>
      expect(engine.player.getState().status).toBe("playing"),
    );
    // Before analysis the engine runs the 120 BPM / 4/4 fallback.
    expect(node.last("count-in")).toMatchObject({
      bars: 1,
      beatsPerBar: 4,
      beatFrames: 24000,
    });

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(
      () =>
        expect(screen.getByTestId("status-line")).toHaveTextContent(
          "Analysis complete",
        ),
      { timeout: 4000 },
    );

    // The same engine instance keeps playing; a reopen would create a second
    // runtime and lose this state.
    expect(creations()).toBe(1);
    expect(engine.player.getState().status).toBe("playing");
    expect(engine.player.getState().loopRange).toEqual({
      startSeconds: 0,
      endSeconds: 4,
    });
    expect(engine.player.getState().loopEnabled).toBe(true);

    const metronome = node.last("metronome") as {
      beats?: Array<Record<string, unknown>>;
    };
    expect(metronome.beats).toEqual([
      { frame: 0, strength: "downbeat" },
      { frame: 28800, strength: "beat" },
      { frame: 57600, strength: "beat" },
      { frame: 86400, strength: "downbeat" },
      { frame: 115200, strength: "beat" },
      { frame: 144000, strength: "beat" },
      { frame: 172800, strength: "downbeat" },
    ]);

    expect(screen.getByTestId("key-readout")).toHaveTextContent("G major");
    expect(screen.getByTestId("chord-block-0")).toHaveTextContent("G");
    expect(screen.getByLabelText("Section name section-1")).toBeInTheDocument();

    // Replaying after the live update uses the detected bpb and tempo.
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(engine.player.getState().status).toBe("paused"));
    fireEvent.click(screen.getByRole("button", { name: "Return to start" }));
    await waitFor(() => expect(engine.player.getState().status).toBe("paused"));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() =>
      expect(engine.player.getState().status).toBe("playing"),
    );
    expect(node.last("count-in")).toMatchObject({
      bars: 1,
      beatsPerBar: 3,
      beatFrames: 28800,
    });

    // The section already ends at the playhead (0 s), so the new end-at-
    // playhead Add has no room and must report it without creating anything.
    await userEvent.click(screen.getByRole("button", { name: "Add section" }));
    await waitFor(() =>
      expect(screen.getByTestId("status-line")).toHaveTextContent("No room"),
    );
    expect(
      screen.queryByLabelText("Section end section-2"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Section name section-1")).toBeInTheDocument();
  });

  it("follows the playhead while the real engine runs", async () => {
    const { engine } = await renderRealStudio();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() =>
      expect(engine.player.getState().status).toBe("playing"),
    );
    fireEvent.keyDown(screen.getByTestId("waveform-a1"), { key: "f" });
    expect(
      screen.getByRole("button", { name: "Follow playhead" }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
