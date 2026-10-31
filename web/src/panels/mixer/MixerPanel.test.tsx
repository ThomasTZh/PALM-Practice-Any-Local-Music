import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createFakeMixer } from "../../state/fakeMixer";
import { MixerPanel } from "./MixerPanel";

const STEMS = [
  { id: "bass", name: "Bass", role: "bass" },
  { id: "drums", name: "Drums", role: "drums" },
];

function setup(stems = STEMS) {
  const mixer = createFakeMixer(stems.map((stem) => stem.id));
  const view = render(<MixerPanel stems={stems} controller={mixer} />);
  return { mixer, view };
}

describe("MixerPanel", () => {
  it("renders one strip per stem and an empty state", () => {
    const { view } = setup();
    expect(screen.getByTestId("mixer-channel-bass")).toBeInTheDocument();
    expect(screen.getByTestId("mixer-channel-drums")).toBeInTheDocument();

    view.rerender(<MixerPanel stems={[]} controller={createFakeMixer([])} />);
    expect(screen.getByText("Separate stems to mix them.")).toBeInTheDocument();
  });

  it("shows neutral defaults", () => {
    setup();
    expect(screen.getByTestId("mixer-gain-bass")).toHaveTextContent("0.0 dB");
    expect(screen.getByTestId("mixer-pan-bass")).toHaveTextContent("C");
  });

  it("toggles mute on the controller", () => {
    const { mixer } = setup();

    const mute = screen.getByRole("button", { name: "Mute Bass" });
    expect(mute).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(mute);

    expect(mixer.calls).toContain("setMuted:bass");
    expect(mixer.getState().bass.muted).toBe(true);
    expect(mute).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("mixer-channel-bass")).toHaveAttribute(
      "data-audible",
      "false",
    );
  });

  it("soloes one stem and dims the rest", () => {
    const { mixer } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Solo Bass" }));

    expect(mixer.calls).toContain("setSoloed:bass");
    expect(screen.getByTestId("mixer-channel-bass")).toHaveAttribute(
      "data-audible",
      "true",
    );
    expect(screen.getByTestId("mixer-channel-drums")).toHaveAttribute(
      "data-audible",
      "false",
    );
    expect(screen.getByText("Solo")).toBeInTheDocument();
  });

  it("changes gain and shows the value", () => {
    const { mixer } = setup();

    fireEvent.change(screen.getByLabelText("Bass gain"), {
      target: { value: "-6" },
    });

    expect(mixer.calls).toContain("setGain:bass");
    expect(mixer.getState().bass.gainDb).toBe(-6);
    expect(screen.getByTestId("mixer-gain-bass")).toHaveTextContent("-6.0 dB");
  });

  it("changes pan and shows the side", () => {
    const { mixer } = setup();

    fireEvent.change(screen.getByLabelText("Drums pan"), {
      target: { value: "-0.5" },
    });

    expect(mixer.calls).toContain("setPan:drums");
    expect(mixer.getState().drums.pan).toBe(-0.5);
    expect(screen.getByTestId("mixer-pan-drums")).toHaveTextContent("L 50");
  });

  it("reflects state changes reported by the engine", () => {
    const { mixer } = setup();

    act(() => {
      mixer.sync("bass", { gainDb: 3, pan: 0.4, muted: true });
    });

    expect(screen.getByTestId("mixer-gain-bass")).toHaveTextContent("+3.0 dB");
    expect(screen.getByTestId("mixer-pan-bass")).toHaveTextContent("R 40");
    expect(screen.getByRole("button", { name: "Mute Bass" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
