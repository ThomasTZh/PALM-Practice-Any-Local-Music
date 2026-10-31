import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LibraryEntry, Project } from "./state/types";
import { createFakeApi } from "./state/fakeApi";
import { createFakePlayer } from "./state/fakePlayer";
import { App } from "./App";

const ENTRY: LibraryEntry = {
  id: "p1",
  title: "Demo take",
  durationSeconds: 8,
  sampleRate: 44100,
  channels: 1,
  importedAt: "2026-10-31T18:00:00Z",
  projectId: "p1",
};

const PROJECT: Project = {
  id: "p1",
  title: "Demo take",
  durationSeconds: 8,
  asset: {
    id: "a1",
    title: "Demo take",
    durationSeconds: 8,
    sampleRate: 44100,
    channels: 1,
  },
  grid: { bpm: 120, meter: { numerator: 4, denominator: 4 }, offsetSeconds: 0 },
  key: "C major",
  stems: [],
};

const PROJECT_WITH_STEMS: Project = {
  ...PROJECT,
  stems: [
    { id: "s1", name: "Bass", role: "bass", peaksAssetId: "a2" },
    { id: "s2", name: "Drums", role: "drums", peaksAssetId: "a3" },
  ],
};

async function renderStudio(
  project: Project = PROJECT,
  options: { failOpen?: boolean } = {},
) {
  const api = createFakeApi({
    listLibrary: async () => [ENTRY],
    openProject: async () => {
      if (options.failOpen) {
        throw new Error("server exploded");
      }
      return project;
    },
    fetchPeaks: async () => new ArrayBuffer(20),
  });
  const player = createFakePlayer({ durationSeconds: project.durationSeconds });
  render(<App api={api} player={player} />);
  return { api, player };
}

async function openFirstProject() {
  await screen.findByText("Demo take");
  await userEvent.click(screen.getByRole("button", { name: "Open Demo take" }));
}

describe("App shell", () => {
  it("opens a library recording into a waveform lane and readouts", async () => {
    const { player } = await renderStudio();

    expect(
      screen.getByText("Open a recording to see its waveform."),
    ).toBeInTheDocument();
    await openFirstProject();

    await waitFor(() =>
      expect(screen.getByTestId("status-line")).toHaveTextContent(
        "Loaded Demo take",
      ),
    );
    expect(screen.getByTestId("project-title")).toHaveTextContent("Demo take");
    expect(screen.getByTestId("key-readout")).toHaveTextContent("C major");
    expect(screen.getByTestId("bpm-readout")).toHaveTextContent("120 4/4");
    expect(screen.getByTestId("waveform-a1")).toBeInTheDocument();
    expect(player.calls).toContain("setDuration:8");
  });

  it("renders one lane per stem when the project has stems", async () => {
    const { api } = await renderStudio(PROJECT_WITH_STEMS);

    await openFirstProject();

    expect(await screen.findByTestId("waveform-s1")).toBeInTheDocument();
    expect(screen.getByTestId("waveform-s2")).toBeInTheDocument();
    expect(screen.getByText("Bass")).toBeInTheDocument();
    expect(screen.getByText("Drums")).toBeInTheDocument();
    expect(api.calls).toEqual(
      expect.arrayContaining(["fetchPeaks:a2", "fetchPeaks:a3"]),
    );
  });

  it("reports a failed project open without losing the shell", async () => {
    await renderStudio(PROJECT, { failOpen: true });

    await openFirstProject();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "server exploded",
    );
    expect(
      screen.getByText("Open a recording to see its waveform."),
    ).toBeInTheDocument();
  });

  it("wires transport shortcuts, ruler clicks and the follow toggle", async () => {
    const { player } = await renderStudio();
    await openFirstProject();
    await screen.findByTestId("waveform-a1");

    fireEvent.keyDown(screen.getByTestId("waveform-a1"), { key: " " });
    expect(player.calls).toContain("toggle");

    fireEvent.click(screen.getByTestId("time-ruler"), { clientX: 480 });
    expect(player.calls).toContain("seek:4");

    const follow = screen.getByRole("button", { name: "Follow playhead" });
    expect(follow).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(follow);
    expect(follow).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the dragged selection in the status line", async () => {
    await renderStudio();
    await openFirstProject();
    const pane = await screen.findByTestId("waveform-a1");

    fireEvent.mouseDown(pane, { clientX: 120, button: 0 });
    fireEvent.mouseMove(pane, { clientX: 360 });
    fireEvent.mouseUp(pane, { clientX: 360 });

    await waitFor(() =>
      expect(screen.getByTestId("status-detail")).toHaveTextContent(
        "selection 0:01.0–0:03.0",
      ),
    );
  });

  it("zooms to the selection from the toolbar", async () => {
    await renderStudio();
    await openFirstProject();
    const pane = await screen.findByTestId("waveform-a1");
    fireEvent.mouseDown(pane, { clientX: 120, button: 0 });
    fireEvent.mouseMove(pane, { clientX: 360 });

    const zoomSelection = screen.getByRole("button", {
      name: "Zoom to selection",
    });
    expect(zoomSelection).toBeEnabled();
    await userEvent.click(zoomSelection);

    expect(screen.getByTestId("status-detail")).toHaveTextContent(/zoom \d/);
  });

  it("does not call the API before the user asks for a project", async () => {
    const api = createFakeApi();
    render(<App api={api} player={createFakePlayer({ durationSeconds: 8 })} />);
    await screen.findByText("No recordings yet.");

    expect(api.calls).toEqual(["listLibrary"]);
    expect(api.calls.some((call) => call.startsWith("openProject"))).toBe(
      false,
    );
  });
});
