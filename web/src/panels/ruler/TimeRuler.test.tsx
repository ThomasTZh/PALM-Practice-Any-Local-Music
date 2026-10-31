import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Grid } from "../../state/types";
import { fitViewport } from "../waveform/viewport";
import { TimeRuler } from "./TimeRuler";

const WIDTH = 960;
const DURATION = 8;
const VIEWPORT = fitViewport(DURATION, WIDTH);
const GRID: Grid = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

function renderRuler(overrides: Partial<Parameters<typeof TimeRuler>[0]> = {}) {
  const onSeek = vi.fn();
  render(
    <TimeRuler
      viewport={VIEWPORT}
      widthPx={WIDTH}
      grid={GRID}
      positionSeconds={0}
      onSeek={onSeek}
      {...overrides}
    />,
  );
  return { onSeek };
}

describe("TimeRuler", () => {
  it("renders second labels and bar numbers together", () => {
    renderRuler();

    expect(screen.getByTestId("time-ruler")).toBeInTheDocument();
    expect(screen.getByText("0:00")).toBeInTheDocument();
    expect(screen.getByText("0:07")).toBeInTheDocument();

    const bars = screen.getByTestId("ruler-bars");
    expect(within(bars).getByText("1")).toBeInTheDocument();
    expect(within(bars).getByText("4")).toBeInTheDocument();
  });

  it("seeks to the time under the cursor", () => {
    const { onSeek } = renderRuler();

    fireEvent.click(screen.getByTestId("time-ruler"), { clientX: 480 });

    expect(onSeek).toHaveBeenCalledWith(4);
  });

  it("places the playhead at the current position", () => {
    renderRuler({ positionSeconds: 4 });

    expect(screen.getByTestId("ruler-playhead")).toHaveStyle({ left: "480px" });
  });

  it("hides the bar strip when the grid is not known yet", () => {
    renderRuler({ grid: null });

    expect(screen.queryByTestId("ruler-bars")).not.toBeInTheDocument();
    expect(screen.getByText("0:00")).toBeInTheDocument();
  });

  it("keeps ticks inside the scrolled window", () => {
    renderRuler({
      viewport: { startSeconds: 4, secondsPerPixel: DURATION / WIDTH },
    });

    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
    expect(screen.getByText("0:04")).toBeInTheDocument();
  });
});
