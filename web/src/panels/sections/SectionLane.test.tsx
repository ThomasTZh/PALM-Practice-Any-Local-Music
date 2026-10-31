import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Section } from "../../state/sections";
import { createFakePlayer } from "../../state/fakePlayer";
import type { Viewport } from "../waveform/viewport";
import { BarBeatOverlay } from "./BarBeatOverlay";
import { SectionLane } from "./SectionLane";

const GRID = {
  beats: Array.from({ length: 16 }, (_, index) => index * 0.5),
  bpb: 4,
};
const VIEWPORT: Viewport = { startSeconds: 0, secondsPerPixel: 0.01 };
const VERSE: Section = {
  id: "s1",
  name: "Verse",
  startSeconds: 0,
  endSeconds: 8,
};

function setup(overrides: Partial<Parameters<typeof SectionLane>[0]> = {}) {
  const onChange = vi.fn();
  const onLoop = vi.fn();
  const onSnapModeChange = vi.fn();
  const props = {
    sections: [] as Section[],
    grid: GRID,
    viewport: VIEWPORT,
    widthPx: 800,
    durationSeconds: 8,
    positionSeconds: 1.9,
    onChange,
    onLoop,
    onSnapModeChange,
    ...overrides,
  };
  const view = render(<SectionLane {...props} />);
  return { view, props, onChange, onLoop, onSnapModeChange };
}

describe("SectionLane", () => {
  it("adds a bar-snapped section by default", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const sections = onChange.mock.calls[0][0] as Section[];
    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      name: "Section 1",
      startSeconds: 2,
      endSeconds: 4,
    });
  });

  it("changes the added boundary when snap switches to beat or free", () => {
    const { onChange } = setup({ positionSeconds: 1.7 });

    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "beat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section" }));
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 1.5,
      endSeconds: 2,
    });

    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "free" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section" }));
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 1.7,
      endSeconds: 2.7,
    });
  });

  it("reports snap-mode changes to a controlled parent", () => {
    const { onSnapModeChange } = setup();

    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "beat" },
    });

    expect(onSnapModeChange).toHaveBeenCalledWith("beat");
  });

  it("splits the section under the playhead at the nearest bar", () => {
    const { onChange } = setup({
      sections: [VERSE],
      positionSeconds: 3.2,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Split section at playhead" }),
    );

    const sections = onChange.mock.calls[0][0] as Section[];
    expect(sections).toHaveLength(2);
    expect(sections[0]).toMatchObject({ startSeconds: 0, endSeconds: 4 });
    expect(sections[1]).toMatchObject({
      name: "Verse (2)",
      startSeconds: 4,
      endSeconds: 8,
    });
  });

  it("disables split outside every section", () => {
    setup({ sections: [], positionSeconds: 3.2 });
    expect(
      screen.getByRole("button", { name: "Split section at playhead" }),
    ).toBeDisabled();
  });

  it("loops a section, sets the transport loop and leaves it editable", () => {
    const player = createFakePlayer({ durationSeconds: 8 });
    const { onChange, onLoop } = setup({
      sections: [VERSE],
      positionSeconds: 1,
      player,
    });

    fireEvent.click(screen.getByRole("button", { name: "Loop Verse" }));
    expect(onLoop).toHaveBeenCalledWith(VERSE);
    expect(player.calls).toContain(
      'setLoopRange:{"startSeconds":0,"endSeconds":8}',
    );
    expect(player.calls).toContain("setLoopEnabled:true");

    const nameInput = screen.getByLabelText("Section name s1");
    expect(nameInput).toBeInTheDocument();
    fireEvent.change(nameInput, { target: { value: "Chorus" } });

    expect((onChange.mock.calls[0][0] as Section[])[0].name).toBe("Chorus");
  });

  it("resizes an editable boundary with snapping", () => {
    const { onChange } = setup({ sections: [VERSE] });

    fireEvent.change(screen.getByLabelText("Section end s1"), {
      target: { value: "5.9" },
    });

    const sections = onChange.mock.calls[0][0] as Section[];
    expect(sections[0].endSeconds).toBe(6);
  });

  it("marks the section under the playhead", () => {
    setup({ sections: [VERSE], positionSeconds: 3.2 });
    expect(screen.getByTestId("section-block-s1")).toHaveAttribute(
      "data-current",
      "true",
    );
  });

  it("renders the bar and beat overlay from the grid", () => {
    setup();

    expect(screen.getByTestId("bar-beat-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("beat-1-1")).toHaveTextContent("1");
    expect(screen.getByTestId("beat-2-1")).toHaveTextContent("2");
    expect(screen.getByTestId("beat-1-2")).toHaveAttribute(
      "data-downbeat",
      "false",
    );
  });

  it("explains the empty lane", () => {
    setup();
    expect(
      screen.getByText("No sections yet. Add one to loop a passage."),
    ).toBeInTheDocument();
  });
});

describe("BarBeatOverlay", () => {
  it("renders detected beats with bar numbers on downbeats", () => {
    render(
      <BarBeatOverlay
        beats={[0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5]}
        bpb={4}
        viewport={VIEWPORT}
        widthPx={400}
      />,
    );

    expect(screen.getByTestId("beat-1-1")).toHaveStyle({ left: "0px" });
    expect(screen.getByTestId("beat-2-1")).toHaveStyle({ left: "200px" });
    expect(screen.getByTestId("beat-1-2")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^beat-/)).toHaveLength(8);
  });

  it("shows a placeholder without beats", () => {
    render(
      <BarBeatOverlay beats={[]} bpb={4} viewport={VIEWPORT} widthPx={400} />,
    );
    expect(screen.getByText("No beat grid yet.")).toBeInTheDocument();
  });
});
