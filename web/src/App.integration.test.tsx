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
import type { AnalysisJobClient } from "./state/analysis";
import { parseStudioProject, type ShellApi } from "./state/project";
import {
  createShellTransport,
  type StudioRuntime,
} from "./state/studioRuntime";
import { App } from "./App";

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

class FakeNode implements WorkletNodeLike {
  readonly port: WorkletNodeLike["port"];
  constructor() {
    const node = this;
    this.port = {
      onmessage: null,
      postMessage: (message: unknown) => {
        const seek = message as { type?: string; generation?: number };
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
  connect(): void {}
  disconnect(): void {}
}

function realEngine(): StudioEngine {
  const bytes = makeSourceBytes([
    new Float32Array(FRAMES).fill(0.05),
    new Float32Array(FRAMES).fill(0.05),
  ]);
  const context: AudioContextLike & { currentTime: number } = {
    currentTime: 0,
    sampleRate: RATE,
    destination: null,
  };
  const transportOptions: TransportOptions = {
    contextFactory: () => context,
    workletFactory: () => new FakeNode(),
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
  const engine = createStudioPlayer({
    projectId: "p1",
    sampleRate: RATE,
    channelCount: 2,
    frameCount: FRAMES,
    durationSeconds: DURATION,
    mixUrl: "memory://mix",
    stems: [],
    grid: { bpm: 120, bpb: 4, beatsSeconds: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5] },
    transportOptions,
  });
  ENGINES.push(engine);
  return engine;
}

function shellApi(): ShellApi {
  return {
    async listLibrary() {
      return [
        {
          id: "p1",
          title: "Real engine take",
          durationSeconds: DURATION,
          sampleRate: RATE,
          channels: 2,
          importedAt: "2026-10-31T18:00:00Z",
          projectId: "p1",
        },
      ];
    },
    async openProject() {
      return PROJECT;
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

async function renderRealStudio() {
  const engine = realEngine();
  await engine.ready;
  const runtime: StudioRuntime = {
    player: engine.player,
    mixer: engine.mixer,
    practice: engine.practice,
    ready: engine.ready,
    getNotice: engine.getNotice,
    subscribeNotice: engine.subscribeNotice,
    diagnostics: engine.diagnostics,
    dispose: engine.dispose,
  };
  const transport = createShellTransport(() => runtime);
  render(
    <App
      api={shellApi()}
      transport={transport}
      analysisClient={analysisClient()}
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
  await screen.findByRole("button", { name: "Open Real engine take" });
  await userEvent.click(
    screen.getByRole("button", { name: "Open Real engine take" }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      "Loaded Real engine take",
    ),
  );
  return { engine };
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

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() =>
      expect(engine.player.getState().status).toBe("playing"),
    );
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Speed" }), {
      target: { value: "0.75" },
    });
    await waitFor(() => expect(engine.player.getState().speed).toBe(0.75));
    expect(engine.practice.getState().speed).toBe(0.75);

    fireEvent.change(screen.getByLabelText("Pitch"), {
      target: { value: "2" },
    });
    await waitFor(() =>
      expect(engine.player.getState().pitchSemitones).toBe(2),
    );
    expect(engine.practice.getState().pitchSemitones).toBe(2);

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
