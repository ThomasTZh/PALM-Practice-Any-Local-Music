import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createFakeApi } from "../../state/fakeApi";
import type { LibraryEntry } from "../../state/types";
import { LibraryPanel } from "./LibraryPanel";

const ENTRIES: LibraryEntry[] = [
  {
    id: "p1",
    title: "Demo take",
    durationSeconds: 8,
    sampleRate: 44100,
    channels: 1,
    importedAt: "2026-10-31T18:00:00Z",
    projectId: "p1",
  },
  {
    id: "p2",
    title: "Slow blues",
    durationSeconds: 125,
    sampleRate: 48000,
    channels: 2,
    importedAt: "2026-10-30T10:00:00Z",
    projectId: "project-2",
  },
];

describe("LibraryPanel", () => {
  it("lists recordings with their duration and opens one", async () => {
    const api = createFakeApi({ listLibrary: async () => ENTRIES });
    const onOpen = vi.fn();
    render(<LibraryPanel api={api} onOpen={onOpen} />);

    expect(await screen.findByText("Demo take")).toBeInTheDocument();
    expect(screen.getByText("0:08")).toBeInTheDocument();
    expect(screen.getByText("2:05")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Open Demo take" }),
    );

    expect(onOpen).toHaveBeenCalledWith("p1");
  });

  it("uses the project id when it differs from the entry id", async () => {
    const api = createFakeApi({ listLibrary: async () => ENTRIES });
    const onOpen = vi.fn();
    render(<LibraryPanel api={api} onOpen={onOpen} />);

    await screen.findByText("Slow blues");
    await userEvent.click(
      screen.getByRole("button", { name: "Open Slow blues" }),
    );

    expect(onOpen).toHaveBeenCalledWith("project-2");
  });

  it("shows an empty state", async () => {
    const api = createFakeApi({ listLibrary: async () => [] });
    render(<LibraryPanel api={api} onOpen={vi.fn()} />);

    expect(await screen.findByText("No recordings yet.")).toBeInTheDocument();
  });

  it("reports a library failure in plain language", async () => {
    const api = createFakeApi({
      listLibrary: async () => {
        throw new Error("offline");
      },
    });
    render(<LibraryPanel api={api} onOpen={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  });

  it("imports a recording and opens it", async () => {
    const api = createFakeApi({
      listLibrary: async () => [],
      importRecording: async () => ENTRIES[0],
    });
    const onOpen = vi.fn();
    render(<LibraryPanel api={api} onOpen={onOpen} />);

    await screen.findByText("No recordings yet.");
    const input = screen.getByLabelText("Import recording");
    const file = new File([new Uint8Array([1, 2, 3])], "demo.wav", {
      type: "audio/wav",
    });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(api.calls).toContain("importRecording:demo.wav"),
    );
    expect(onOpen).toHaveBeenCalledWith("p1");
  });
});
