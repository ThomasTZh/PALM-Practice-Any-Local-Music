import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createFakePractice } from "../../state/fakePractice";
import { PracticePanel } from "./PracticePanel";

function setup() {
  const controller = createFakePractice();
  const view = render(<PracticePanel controller={controller} />);
  return { controller, view };
}

describe("PracticePanel", () => {
  it("shows the default practice state", () => {
    const { controller } = setup();

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
      screen.queryByRole("button", { name: "Accent downbeat" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Metronome volume")).not.toBeInTheDocument();
    expect(controller.getState().accentDownbeat).toBe(true);
    expect(controller.getState().metronomeVolume).toBe(1);
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

  it("changes count-in and metronome enable", () => {
    const { controller } = setup();

    fireEvent.change(screen.getByLabelText("Count-in"), {
      target: { value: "2" },
    });
    expect(controller.getState().countInBars).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "Metronome" }));
    expect(controller.getState().metronomeEnabled).toBe(true);
    expect(screen.queryByLabelText("Metronome volume")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accent downbeat" }),
    ).not.toBeInTheDocument();
  });

  it("has no snap control in the practice bar", () => {
    setup();

    expect(screen.queryByLabelText("Snap mode")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Snap")).not.toBeInTheDocument();
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
  });
});
