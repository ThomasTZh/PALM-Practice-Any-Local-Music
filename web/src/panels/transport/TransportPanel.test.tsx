import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Grid } from "../../state/types";
import { createFakePlayer } from "../../state/fakePlayer";
import { TransportPanel } from "./TransportPanel";

const GRID: Grid = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

describe("TransportPanel", () => {
  it("shows the player position and updates it as the player moves", () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      positionSeconds: 12.34,
    });
    render(<TransportPanel player={player} />);

    expect(screen.getByTestId("transport-position")).toHaveTextContent(
      "0:12.3 / 1:00.0",
    );

    act(() => player.setState({ positionSeconds: 42.5 }));
    expect(screen.getByTestId("transport-position")).toHaveTextContent(
      "0:42.5 / 1:00.0",
    );
  });

  it("reflects playing state on the toggle button", async () => {
    const player = createFakePlayer({ durationSeconds: 60 });
    render(<TransportPanel player={player} />);

    const toggle = screen.getByRole("button", { name: "Play" });
    await userEvent.click(toggle);

    expect(player.calls).toEqual(["toggle"]);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByTestId("transport-status")).toHaveTextContent("Playing");

    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("follows playback started or stopped outside the toggle", () => {
    const player = createFakePlayer({ durationSeconds: 60 });
    render(<TransportPanel player={player} />);

    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();

    act(() => player.play());
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByTestId("transport-status")).toHaveTextContent("Playing");

    act(() => player.pause());
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(screen.getByTestId("transport-status")).toHaveTextContent("Paused");
    expect(player.calls).toEqual(["play", "pause"]);
  });

  it("disables play while loading and reports errors", () => {
    const loading = createFakePlayer({
      status: "loading",
      durationSeconds: 60,
    });
    const { unmount } = render(<TransportPanel player={loading} />);
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
    unmount();

    const failed = createFakePlayer({
      status: "error",
      durationSeconds: 60,
      error: "decoder failed",
    });
    render(<TransportPanel player={failed} />);
    expect(screen.getByRole("alert")).toHaveTextContent("decoder failed");
  });

  it("shows the track, key and BPM readouts without a speed menu", () => {
    const player = createFakePlayer({ durationSeconds: 60 });
    render(
      <TransportPanel
        player={player}
        projectTitle="Carousel"
        keyLabel="C major"
        bpm={120}
        bpb={4}
      />,
    );

    expect(screen.getByTestId("project-title")).toHaveTextContent("Carousel");
    expect(screen.getByTestId("key-readout")).toHaveTextContent("C major");
    expect(screen.getByTestId("bpm-readout")).toHaveTextContent("120 · 4/4");
    expect(screen.queryByLabelText("Speed")).not.toBeInTheDocument();
  });

  it("turns the selection into a loop when the loop is switched on", async () => {
    const player = createFakePlayer({ durationSeconds: 60 });
    render(
      <TransportPanel
        player={player}
        selection={{ startSeconds: 2, endSeconds: 5 }}
      />,
    );

    const loop = screen.getByRole("button", { name: "Loop" });
    expect(loop).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(loop);

    expect(player.calls).toEqual([
      'setLoopRange:{"startSeconds":2,"endSeconds":5}',
      "setLoopEnabled:true",
    ]);
    expect(loop).toHaveAttribute("aria-pressed", "true");
  });

  it("loops the whole track when nothing is selected", async () => {
    const player = createFakePlayer({ durationSeconds: 60 });
    render(<TransportPanel player={player} />);

    await userEvent.click(screen.getByRole("button", { name: "Loop" }));

    expect(player.calls).toEqual([
      'setLoopRange:{"startSeconds":0,"endSeconds":60}',
      "setLoopEnabled:true",
    ]);
  });

  it("switches an existing loop off", async () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      loopEnabled: true,
      loopRange: { startSeconds: 1, endSeconds: 3 },
    });
    render(<TransportPanel player={player} />);

    const loop = screen.getByRole("button", { name: "Loop" });
    expect(loop).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(loop);

    expect(player.calls).toEqual(["setLoopEnabled:false"]);
    expect(loop).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the bar and beat when the grid is known", () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      positionSeconds: 2.5,
    });
    render(<TransportPanel player={player} grid={GRID} />);

    expect(screen.getByTestId("transport-bar-beat")).toHaveTextContent(
      "bar 2 · beat 2",
    );
  });

  it("resets the position with the return-to-start button", async () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      positionSeconds: 20,
    });
    render(<TransportPanel player={player} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Return to start" }),
    );

    expect(player.calls).toEqual(["seek:0"]);
  });
});
