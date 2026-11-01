import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createFakePractice } from "../../state/fakePractice";
import { PracticePanel } from "./PracticePanel";

function setup() {
  const controller = createFakePractice();
  const onSnapModeChange = vi.fn();
  const view = render(
    <PracticePanel
      controller={controller}
      snapMode="bar"
      onSnapModeChange={onSnapModeChange}
    />,
  );
  return { controller, onSnapModeChange, view };
}

describe("PracticePanel", () => {
  it("shows the default practice state", () => {
    setup();

    expect(screen.getByLabelText("Practice speed")).toHaveValue("1");
    expect(screen.queryByLabelText("Pitch")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pitch-value")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Practice loop" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("Count-in")).toHaveValue("0");
    expect(screen.getByRole("button", { name: "Metronome" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      screen.getByRole("button", { name: "Accent downbeat" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Metronome volume")).toHaveValue("50");
    expect(screen.getByTestId("metronome-volume-value")).toHaveTextContent(
      "50%",
    );
  });

  it("changes speed and loop", () => {
    const { controller } = setup();

    fireEvent.change(screen.getByLabelText("Practice speed"), {
      target: { value: "0.75" },
    });
    expect(controller.calls).toContain("setSpeed");
    expect(controller.getState().speed).toBe(0.75);

    fireEvent.click(screen.getByRole("button", { name: "Practice loop" }));
    expect(controller.getState().loopEnabled).toBe(true);
    expect(
      screen.getByRole("button", { name: "Practice loop" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("changes count-in, metronome volume and accent", () => {
    const { controller } = setup();

    fireEvent.change(screen.getByLabelText("Count-in"), {
      target: { value: "2" },
    });
    expect(controller.getState().countInBars).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "Metronome" }));
    expect(controller.getState().metronomeEnabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Metronome volume"), {
      target: { value: "25" },
    });
    expect(controller.getState().metronomeVolume).toBeCloseTo(0.25);
    expect(screen.getByTestId("metronome-volume-value")).toHaveTextContent(
      "25%",
    );

    fireEvent.click(screen.getByRole("button", { name: "Accent downbeat" }));
    expect(controller.getState().accentDownbeat).toBe(false);
  });

  it("reports snap-mode changes", () => {
    const { onSnapModeChange } = setup();

    fireEvent.change(screen.getByLabelText("Snap mode"), {
      target: { value: "beat" },
    });

    expect(onSnapModeChange).toHaveBeenCalledWith("beat");
  });

  it("reflects engine-reported practice changes", () => {
    const { controller } = setup();

    act(() => {
      controller.sync({
        speed: 0.5,
        metronomeEnabled: true,
        countInBars: 1,
        metronomeVolume: 0.8,
      });
    });

    expect(screen.getByLabelText("Practice speed")).toHaveValue("0.5");
    expect(screen.getByRole("button", { name: "Metronome" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText("Count-in")).toHaveValue("1");
    expect(screen.getByLabelText("Metronome volume")).toHaveValue("80");
  });
});
