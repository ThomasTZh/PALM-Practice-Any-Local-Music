import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Viewport } from "../waveform/viewport";
import { ChordRibbon } from "./ChordRibbon";
import { KeyBpmReadout } from "./KeyBpmReadout";

const VIEWPORT: Viewport = { startSeconds: 0, secondsPerPixel: 0.01 };
const CHORDS = [
  { startSeconds: 0, endSeconds: 2, label: "C:maj" },
  { startSeconds: 2, endSeconds: 4, label: "A:min7" },
  { startSeconds: 4, endSeconds: 5, label: "N" },
];

function renderRibbon(positionSeconds = 0) {
  const onSeek = vi.fn();
  render(
    <ChordRibbon
      chords={CHORDS}
      viewport={VIEWPORT}
      widthPx={500}
      positionSeconds={positionSeconds}
      onSeek={onSeek}
    />,
  );
  return { onSeek };
}

describe("ChordRibbon", () => {
  it("renders normalised labels and keeps raw labels as titles", () => {
    renderRibbon(0.5);

    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.getByText("Am7")).toBeInTheDocument();
    expect(screen.getByText("N.C.")).toBeInTheDocument();
    expect(screen.getByTitle("A:min7")).toHaveTextContent("Am7");
  });

  it("marks the chord under the playhead", () => {
    renderRibbon(2.5);

    expect(screen.getByTestId("chord-block-1")).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByTestId("chord-block-1")).toHaveAttribute(
      "data-current",
      "true",
    );
    expect(screen.getByTestId("chord-block-0")).toHaveAttribute(
      "data-current",
      "false",
    );
  });

  it("moves the current marker with the playhead", () => {
    renderRibbon(4.5);
    expect(screen.getByTestId("chord-block-2")).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("has no current chord in a gap or outside the track", () => {
    renderRibbon(6);
    for (const index of [0, 1, 2]) {
      expect(screen.getByTestId(`chord-block-${index}`)).toHaveAttribute(
        "data-current",
        "false",
      );
    }
  });

  it("positions blocks on the shared pixel timeline", () => {
    renderRibbon(0.5);
    expect(screen.getByTestId("chord-block-0")).toHaveStyle({
      left: "0px",
      width: "200px",
    });
  });

  it("positions its playhead with the shared time calculation", () => {
    renderRibbon(4.5);
    expect(screen.getByTestId("chord-ribbon-playhead")).toHaveStyle({
      left: "450px",
    });
  });

  it("seeks to the start of a clicked chord", () => {
    const { onSeek } = renderRibbon(0.5);
    fireEvent.click(screen.getByTestId("chord-block-1"));
    expect(onSeek).toHaveBeenCalledWith(2);
  });

  it("explains how to get chords when analysis has not run", () => {
    render(
      <ChordRibbon
        chords={[]}
        viewport={VIEWPORT}
        widthPx={500}
        positionSeconds={0}
      />,
    );
    expect(screen.getByText("Run analysis to see chords.")).toBeInTheDocument();
  });
});

describe("KeyBpmReadout", () => {
  it("shows the key and tempo", () => {
    render(<KeyBpmReadout keyLabel="C major" bpm={120} bpb={4} />);
    expect(screen.getByTestId("key-bpm-key")).toHaveTextContent("C major");
    expect(screen.getByTestId("key-bpm-value")).toHaveTextContent("120 BPM");
    expect(screen.getByTestId("key-bpm-meter")).toHaveTextContent("4");
  });

  it("uses one decimal for a measured tempo", () => {
    render(<KeyBpmReadout keyLabel="A minor" bpm={120.185} />);
    expect(screen.getByTestId("key-bpm-value")).toHaveTextContent("120.2 BPM");
  });

  it("shows placeholders before analysis", () => {
    render(<KeyBpmReadout keyLabel={null} bpm={null} />);
    expect(screen.getByTestId("key-bpm-key")).toHaveTextContent("—");
    expect(screen.getByTestId("key-bpm-value")).toHaveTextContent("—");
  });
});
