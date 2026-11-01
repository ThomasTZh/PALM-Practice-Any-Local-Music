import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Grid } from "../../state/types";
import { createFakePlayer } from "../../state/fakePlayer";
import { TransportReadouts } from "./TransportReadouts";

const GRID: Grid = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

describe("TransportReadouts", () => {
  it("shows the player position and updates it as the player moves", () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      positionSeconds: 12.34,
    });
    render(<TransportReadouts player={player} />);

    expect(screen.getByTestId("transport-position")).toHaveTextContent(
      "0:12.3 / 1:00.0",
    );

    act(() => player.setState({ positionSeconds: 42.5 }));
    expect(screen.getByTestId("transport-position")).toHaveTextContent(
      "0:42.5 / 1:00.0",
    );
  });

  it("shows the bar and beat when the grid is known", () => {
    const player = createFakePlayer({
      durationSeconds: 60,
      positionSeconds: 2.5,
    });
    render(<TransportReadouts player={player} grid={GRID} />);

    expect(screen.getByTestId("transport-bar-beat")).toHaveTextContent(
      "bar 2 · beat 2",
    );
  });
});
