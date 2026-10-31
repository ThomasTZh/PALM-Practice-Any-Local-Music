import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AnalysisJobClient } from "./state/analysis";
import { createFakeMixer } from "./state/fakeMixer";
import { createFakePlayer } from "./state/fakePlayer";
import { createFakePractice } from "./state/fakePractice";
import { makePeaksBuffer } from "./panels/waveform/peaksFixture";
import {
  parseStudioProject,
  type ShellApi,
  type ServerPracticeState,
  type StudioProject,
} from "./state/project";
import {
  createShellTransport,
  type StudioRuntime,
} from "./state/studioRuntime";
import { App } from "./App";

const BEATS = Array.from({ length: 16 }, (_, index) => index * 0.5);

function payload(options: { analysis?: boolean; stems?: boolean } = {}) {
  const analysis = options.analysis ?? true;
  const stems = options.stems ?? true;
  return {
    id: "p1",
    name: "Demo take",
    revision: 2,
    title: "Demo take",
    durationSeconds: 8,
    duration_seconds: 8,
    asset: {
      id: "a1",
      sampleRate: 44100,
      sample_rate: 44100,
      channels: 1,
      frames: 352800,
    },
    grid: analysis
      ? {
          bpm: 120,
          bpb: 4,
          meter: { numerator: 4, denominator: 4 },
          offsetSeconds: 0,
          beats: BEATS,
          bars: [0, 2, 4, 6],
        }
      : null,
    key: analysis ? "C major" : null,
    stems: stems
      ? ["drums", "bass", "other", "vocals"].map((label) => ({
          label,
          url: `/api/projects/p1/stems/${label}/pcm`,
          frames: 352800,
          channels: 1,
          sampleRate: 44100,
        }))
      : [],
    document: analysis
      ? {
          grid: {
            bpm: 120,
            bpb: 4,
            meter: { numerator: 4, denominator: 4 },
            offsetSeconds: 0,
            beats: BEATS,
            bars: [0, 2, 4, 6],
          },
          key: "C major",
          chords: [
            { start_seconds: 0, end_seconds: 2, label: "C:maj" },
            { start_seconds: 2, end_seconds: 4, label: "A:min7" },
            { start_seconds: 4, end_seconds: 5, label: "N" },
          ],
          analysis: { bpb: 4, bpm: 120, key: "C major", cached: true },
        }
      : {},
  };
}

const PROJECT = parseStudioProject(payload());
const PROJECT_WITHOUT_ANALYSIS = parseStudioProject(
  payload({ analysis: false }),
);

interface Rig {
  player: ReturnType<typeof createFakePlayer>;
  mixer: ReturnType<typeof createFakeMixer>;
  practice: ReturnType<typeof createFakePractice>;
  runtime: StudioRuntime;
}

function makeRig(project: StudioProject, notice: string | null = null): Rig {
  const ids = ["mix", ...project.stems.map((stem) => stem.id)];
  const player = createFakePlayer({ durationSeconds: project.durationSeconds });
  const mixer = createFakeMixer(ids);
  const practice = createFakePractice();
  return {
    player,
    mixer,
    practice,
    runtime: {
      player,
      mixer,
      practice,
      ready: Promise.resolve(),
      getNotice: () => notice,
      subscribeNotice(listener) {
        listener(notice);
        return () => {};
      },
      dispose: vi.fn(),
    },
  };
}

function makeApi(
  project: StudioProject,
  options: {
    failOpen?: boolean;
    analysis?: StudioProject;
  } = {},
): ShellApi & { calls: string[]; saved: ServerPracticeState[] } {
  const calls: string[] = [];
  const saved: ServerPracticeState[] = [];
  let revision = project.revision;
  return {
    calls,
    saved,
    async listLibrary() {
      calls.push("listLibrary");
      return [
        {
          id: "p1",
          title: "Demo take",
          durationSeconds: 8,
          sampleRate: 44100,
          channels: 1,
          importedAt: "2026-10-31T18:00:00Z",
          projectId: "p1",
        },
      ];
    },
    async openProject(projectId) {
      calls.push(`open:${projectId}`);
      if (options.failOpen) {
        throw new Error("server exploded");
      }
      return options.analysis ?? project;
    },
    async importRecording() {
      calls.push("import");
      const entry = await this.listLibrary();
      return entry[0];
    },
    async fetchPeaks(assetId) {
      calls.push(`peaks:${assetId}`);
      return makePeaksBuffer({
        buckets: 64,
        sampleRate: 8000,
        samplesPerBucket: 1000,
      });
    },
    async saveState(projectId, state) {
      calls.push(`save:${projectId}:${state.sections.length}`);
      saved.push(state);
      revision += 1;
      return revision;
    },
  };
}

function analysisClient(): AnalysisJobClient {
  return {
    start: vi.fn(async () => ({
      id: "job-1",
      status: "running" as const,
      progress: 0.5,
      message: "chords",
      error: null,
      snapshot: null,
    })),
    status: vi.fn(async () => ({
      id: "job-1",
      status: "succeeded" as const,
      progress: 1,
      message: "done",
      error: null,
      snapshot: null,
    })),
  };
}

function setup(
  options: {
    project?: StudioProject;
    failOpen?: boolean;
    notice?: string | null;
    autosaveDelayMs?: number;
  } = {},
) {
  const project = options.project ?? PROJECT;
  const api = makeApi(project, { failOpen: options.failOpen });
  const rig = makeRig(project, options.notice ?? null);
  const transport = createShellTransport(() => rig.runtime);
  const client = analysisClient();
  const view = render(
    <App
      api={api}
      transport={transport}
      analysisClient={client}
      createPcmLoader={() => async (startFrame: number, endFrame: number) => ({
        samples: new Float32Array(2048),
        sampleRate: 44100,
        channels: 1,
        startFrame,
        frames: endFrame - startFrame,
      })}
      autosaveDelayMs={options.autosaveDelayMs ?? 0}
    />,
  );
  return { api, rig, client, view, project };
}

async function openProject() {
  await screen.findByRole("button", { name: "Open Demo take" });
  await userEvent.click(screen.getByRole("button", { name: "Open Demo take" }));
  await waitFor(() =>
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      "Loaded Demo take",
    ),
  );
}

describe("App integration", () => {
  it("mounts the chord ribbon, sections, mixer, practice, analysis and spectrogram", async () => {
    setup();
    await openProject();

    expect(screen.getByTestId("chord-ribbon")).toBeInTheDocument();
    expect(screen.getByTestId("section-lane")).toBeInTheDocument();
    expect(screen.getByTestId("mixer")).toBeInTheDocument();
    expect(screen.getByTestId("practice")).toBeInTheDocument();
    expect(screen.getByTestId("analysis")).toBeInTheDocument();
    expect(screen.getByTestId("spectrogram")).toBeInTheDocument();
    expect(screen.getByTestId("waveform-a1")).toBeInTheDocument();

    expect(screen.getByText("Bass")).toBeInTheDocument();
    expect(screen.getByText("Drums")).toBeInTheDocument();
    expect(screen.getByTestId("chord-block-0")).toHaveTextContent("C");
    expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
      "Cached",
    );
  });

  it("shows the analysed key, tempo and chord ribbon", async () => {
    setup();
    await openProject();

    expect(screen.getByTestId("key-readout")).toHaveTextContent("C major");
    expect(screen.getByTestId("bpm-readout")).toHaveTextContent("120 · 4/4");
    expect(screen.getByText("Am7")).toBeInTheDocument();
    expect(screen.getByText("N.C.")).toBeInTheDocument();
  });

  it("keeps transport shortcuts, ruler seeking and follow working", async () => {
    const { rig } = setup();
    await openProject();
    const pane = screen.getByTestId("waveform-a1");

    fireEvent.keyDown(pane, { key: " " });
    expect(rig.player.calls).toContain("toggle");

    fireEvent.click(screen.getByTestId("time-ruler"), { clientX: 470 });
    expect(rig.player.calls).toContain("seek:4");

    const follow = screen.getByRole("button", { name: "Follow playhead" });
    expect(follow).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(follow);
    expect(follow).toHaveAttribute("aria-pressed", "false");
  });

  it("adds a bar-snapped section and loops it through the player", async () => {
    const { rig } = setup();
    await openProject();

    await userEvent.click(screen.getByRole("button", { name: "Add section" }));
    expect(await screen.findByText("Section 1")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Loop Section 1" }),
    );
    expect(rig.player.calls).toContain(
      'setLoopRange:{"startSeconds":0,"endSeconds":2}',
    );
    expect(rig.player.calls).toContain("setLoopEnabled:true");
    expect(screen.getByLabelText("Section name section-1")).toBeInTheDocument();
  });

  it("runs analysis from the panel and updates the ribbon and readout", async () => {
    const { client } = setup({
      project: PROJECT_WITHOUT_ANALYSIS,
      autosaveDelayMs: 0,
    });
    await openProject();

    expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
      "Not analysed",
    );
    const start = vi.mocked(client.start);
    const status = vi.mocked(client.status);
    start.mockResolvedValue({
      id: "job-1",
      status: "running",
      progress: 0.5,
      message: "chords",
      error: null,
      snapshot: null,
    });
    const snapshot = {
      bpb: 4,
      bpm: 100,
      key: "G major",
      chords: [{ startSeconds: 0, endSeconds: 4, label: "G:maj" }],
      beats: [0, 0.6, 1.2, 1.8],
      bars: [0, 2.4],
      cached: true,
    };
    status.mockResolvedValue({
      id: "job-1",
      status: "succeeded",
      progress: 1,
      message: "done",
      error: null,
      snapshot,
    });

    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    await waitFor(() =>
      expect(screen.getByTestId("status-line")).toHaveTextContent(
        "Analysis complete",
      ),
    );
    expect(screen.getByTestId("key-readout")).toHaveTextContent("G major");
    expect(screen.getByText("G")).toBeInTheDocument();
    expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
      "Cached",
    );
  });

  it("autosaves section changes", async () => {
    const { api } = setup({ autosaveDelayMs: 5 });
    await openProject();

    await userEvent.click(screen.getByRole("button", { name: "Add section" }));

    await waitFor(() =>
      expect(api.saved.some((state) => state.sections.length > 0)).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByTestId("save-status")).toHaveTextContent("saved"),
    );
  });

  it("shows the engine's fallback notice", async () => {
    setup({ notice: "Stems unavailable; playing the mix." });
    await openProject();

    expect(screen.getByTestId("transport-notice")).toHaveTextContent(
      "Stems unavailable; playing the mix.",
    );
  });

  it("reports a failed project open without leaving the shell broken", async () => {
    setup({ failOpen: true });
    await screen.findByRole("button", { name: "Open Demo take" });
    await userEvent.click(
      screen.getByRole("button", { name: "Open Demo take" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "server exploded",
    );
    expect(
      screen.getByText("Open a recording to see its waveform."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("chord-ribbon")).not.toBeInTheDocument();
  });
});
