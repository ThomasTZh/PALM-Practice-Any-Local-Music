import "@testing-library/jest-dom/vitest";

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createFakeMixer } from "../../state/fakeMixer";
import { MixerPanel, type MixerSeparation } from "./MixerPanel";

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

describe("MixerPanel stem separation", () => {
  function separation(
    overrides: Partial<MixerSeparation> = {},
  ): MixerSeparation {
    return {
      hasStems: false,
      running: false,
      progress: 0,
      stage: "",
      error: null,
      onSeparate: vi.fn(),
      onCancel: vi.fn(),
      ...overrides,
    };
  }

  it("offers Separate stems when the project has no stems", () => {
    const control = separation();
    render(
      <MixerPanel
        stems={[]}
        controller={createFakeMixer([])}
        separation={control}
      />,
    );

    const button = screen.getByRole("button", { name: "Separate stems" });
    expect(button).toBeVisible();
    fireEvent.click(button);
    expect(control.onSeparate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("separation-hint")).toHaveTextContent(
      /Cached separations are instant/,
    );
  });

  it("shows determinate progress, the stage and a cancel action", () => {
    const control = separation({
      running: true,
      progress: 0.42,
      stage: "separating window 2/4",
    });
    render(
      <MixerPanel
        stems={[]}
        controller={createFakeMixer([])}
        separation={control}
      />,
    );

    const progress = screen.getByTestId("separation-progress");
    expect(progress).toHaveAttribute("role", "progressbar");
    expect(progress).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByTestId("separation-stage")).toHaveTextContent(
      "separating window 2/4 · 42%",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Cancel stem separation" }),
    );
    expect(control.onCancel).toHaveBeenCalledTimes(1);
  });

  it("offers Re-separate and explains the cache hit when stems exist", () => {
    render(
      <MixerPanel
        stems={STEMS}
        controller={createFakeMixer(["bass", "drums"])}
        separation={separation({ hasStems: true })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Re-separate" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("separation-hint")).toHaveTextContent(
      "Stem separation is cached: a re-run is instant.",
    );
  });

  it("shows the server's failure message", () => {
    render(
      <MixerPanel
        stems={[]}
        controller={createFakeMixer([])}
        separation={separation({ error: "Demucs model bundle is missing" })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Demucs model bundle is missing",
    );
  });
});
