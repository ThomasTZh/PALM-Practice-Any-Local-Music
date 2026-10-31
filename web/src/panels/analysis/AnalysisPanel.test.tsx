import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AnalysisJobClient,
  AnalysisJobState,
  AnalysisSnapshot,
} from "../../state/analysis";
import { AnalysisPanel } from "./AnalysisPanel";

const SNAPSHOT: AnalysisSnapshot = {
  bpb: 4,
  bpm: 120.185,
  key: "C major",
  chords: [
    { startSeconds: 0, endSeconds: 2, label: "C:maj" },
    { startSeconds: 2, endSeconds: 4, label: "A:min7" },
  ],
  beats: [0, 0.5, 1, 1.5],
  bars: [0, 2],
  cached: true,
};

function jobState(
  status: AnalysisJobState["status"],
  progress: number,
  overrides: Partial<AnalysisJobState> = {},
): AnalysisJobState {
  return {
    id: "job-1",
    status,
    progress,
    message: status === "running" ? "chords" : status,
    error: null,
    snapshot: null,
    ...overrides,
  };
}

function setup(overrides: Partial<Parameters<typeof AnalysisPanel>[0]> = {}) {
  const start = vi.fn(async () => jobState("running", 0.1));
  const status = vi.fn(async () =>
    jobState("succeeded", 1, { snapshot: SNAPSHOT }),
  );
  const client: AnalysisJobClient = { start, status };
  const onAnalyzed = vi.fn();
  const view = render(
    <AnalysisPanel
      projectId="p1"
      analysis={null}
      client={client}
      pollIntervalMs={1}
      onAnalyzed={onAnalyzed}
      {...overrides}
    />,
  );
  return { start, status, onAnalyzed, client, view };
}

describe("AnalysisPanel", () => {
  it("shows a cached badge for existing analysis and its key/tempo", () => {
    setup({ analysis: SNAPSHOT });

    expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
      "Cached",
    );
    expect(screen.getByTestId("analysis-cache-badge")).toHaveAttribute(
      "data-cached",
      "true",
    );
    expect(screen.getByTestId("key-bpm-key")).toHaveTextContent("C major");
    expect(screen.getByTestId("key-bpm-value")).toHaveTextContent("120.2 BPM");
    expect(screen.getByTestId("analysis-summary")).toHaveTextContent(
      "2 chords · 2 bars",
    );
  });

  it("runs the job with the selected beats per bar and shows progress", async () => {
    let resolveStatus: ((state: AnalysisJobState) => void) | null = null;
    const start = vi.fn(async () => jobState("running", 0.1));
    const status = vi.fn(
      () =>
        new Promise<AnalysisJobState>((resolve) => {
          resolveStatus = resolve;
        }),
    );
    const onAnalyzed = vi.fn();
    render(
      <AnalysisPanel
        projectId="p1"
        analysis={null}
        client={{ start, status }}
        pollIntervalMs={1}
        onAnalyzed={onAnalyzed}
      />,
    );

    fireEvent.change(screen.getByLabelText("Beats per bar"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    await waitFor(() => expect(start).toHaveBeenCalledWith("p1", 3));
    expect(await screen.findByTestId("analysis-progress")).toHaveAttribute(
      "aria-valuenow",
      "10",
    );

    await act(async () => {
      resolveStatus?.(jobState("running", 0.55));
    });
    await waitFor(() =>
      expect(screen.getByTestId("analysis-progress")).toHaveAttribute(
        "aria-valuenow",
        "55",
      ),
    );

    await act(async () => {
      resolveStatus?.(jobState("succeeded", 1, { snapshot: SNAPSHOT }));
    });
    await waitFor(() =>
      expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
        "Cached",
      ),
    );
    expect(onAnalyzed).toHaveBeenCalledWith(SNAPSHOT);
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("shows a fresh result as not cached", async () => {
    const fresh = { ...SNAPSHOT, cached: false };
    const client: AnalysisJobClient = {
      start: async () => jobState("running", 0.2),
      status: async () => jobState("succeeded", 1, { snapshot: fresh }),
    };
    render(
      <AnalysisPanel
        projectId="p1"
        analysis={null}
        client={client}
        pollIntervalMs={1}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    await waitFor(() =>
      expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
        "Fresh",
      ),
    );
  });

  it("reports a failed job in plain language", async () => {
    const client: AnalysisJobClient = {
      start: async () => jobState("running", 0.2),
      status: async () =>
        jobState("failed", 0.4, {
          message: "piper crashed",
          error: "piper crashed",
        }),
    };
    render(
      <AnalysisPanel
        projectId="p1"
        analysis={null}
        client={client}
        pollIntervalMs={1}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("piper crashed");
    expect(screen.getByTestId("analysis-cache-badge")).toHaveTextContent(
      "Not analysed",
    );
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("reports a client failure", async () => {
    const client: AnalysisJobClient = {
      start: async () => {
        throw new Error("cannot reach the studio server");
      },
      status: async () => jobState("running", 0),
    };
    render(
      <AnalysisPanel
        projectId="p1"
        analysis={null}
        client={client}
        pollIntervalMs={1}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "cannot reach the studio server",
    );
  });
});
