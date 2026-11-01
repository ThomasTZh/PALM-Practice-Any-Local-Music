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
const LONG_GRID = {
  beats: Array.from({ length: 121 }, (_, index) => index * 0.5),
  bpb: 4,
};
const VERSE: Section = {
  id: "s1",
  name: "Verse",
  startSeconds: 0,
  endSeconds: 8,
};

function pointer(element: Element, type: string, clientX: number): void {
  fireEvent(
    element,
    new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      clientX,
      button: 0,
    }),
  );
}

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
  it("adds a four-bar bar-snapped section by default", () => {
    const { onChange } = setup({ grid: LONG_GRID, durationSeconds: 60 });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const sections = onChange.mock.calls[0][0] as Section[];
    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      name: "Section 1",
      startSeconds: 0,
      endSeconds: 2,
    });
  });

  it("uses four bars of the detected grid for the default Add", () => {
    const detected = {
      beats: Array.from({ length: 12 }, (_, index) => index * 0.6),
      bpb: 3,
    };
    const { onChange } = setup({
      grid: detected,
      positionSeconds: 0,
      durationSeconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    const created = (onChange.mock.calls[0][0] as Section[])[0];
    expect(created.startSeconds).toBe(0);
    expect(created.endSeconds).toBeCloseTo(7.2);
  });

  it("ends a four-bar section at the playhead after the previous section", () => {
    const previous: Section = {
      id: "prev",
      name: "Verse",
      startSeconds: 0,
      endSeconds: 4,
    };
    const { onChange } = setup({
      grid: LONG_GRID,
      sections: [previous],
      positionSeconds: 12,
      durationSeconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    expect((onChange.mock.calls[0][0] as Section[])[1]).toMatchObject({
      startSeconds: 4,
      endSeconds: 12,
    });
  });

  it("re-sorts the list after adding a section before an existing one", () => {
    const later: Section = {
      id: "later",
      name: "Chorus",
      startSeconds: 20,
      endSeconds: 22,
    };
    const { view, props, onChange } = setup({
      grid: LONG_GRID,
      sections: [later],
      positionSeconds: 12,
      durationSeconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));
    const updated = onChange.mock.calls[0][0] as Section[];
    view.rerender(<SectionLane {...props} sections={updated} />);

    const items = Array.from(
      screen.getByTestId("section-list").querySelectorAll("li"),
    ).map((item) => item.getAttribute("data-testid"));
    expect(items).toEqual([
      "section-editor-item-section-1",
      "section-editor-item-later",
    ]);
  });

  it("clamps the add start to the previous section end", () => {
    const previous: Section = {
      id: "prev",
      name: "Verse",
      startSeconds: 0,
      endSeconds: 7,
    };
    const { onChange } = setup({
      grid: LONG_GRID,
      sections: [previous],
      positionSeconds: 10,
      durationSeconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    expect((onChange.mock.calls[0][0] as Section[])[1]).toMatchObject({
      startSeconds: 7,
      endSeconds: 10,
    });
  });

  it("refuses and reports why when the previous section leaves no room", () => {
    const onActionError = vi.fn();
    const previous: Section = {
      id: "prev",
      name: "Verse",
      startSeconds: 0,
      endSeconds: 10,
    };
    const { onChange } = setup({
      grid: LONG_GRID,
      sections: [previous],
      positionSeconds: 8,
      durationSeconds: 60,
      onActionError,
    });

    fireEvent.click(screen.getByRole("button", { name: "Add section" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(onActionError).toHaveBeenCalledWith(
      expect.stringContaining("No room"),
    );
    expect(onActionError.mock.calls[0][0]).toContain("Verse ends at 10.00 s");
  });

  it("moves a section body while keeping its length and allows overlaps", () => {
    const sections: Section[] = [
      { id: "s1", name: "Verse", startSeconds: 2, endSeconds: 4 },
      { id: "s2", name: "Chorus", startSeconds: 3, endSeconds: 6 },
    ];
    const { view, props, onChange } = setup({ sections });
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;
    const block = screen.getByTestId("section-block-s1");

    pointer(block, "pointerdown", 300);
    pointer(timeline, "pointermove", 500);
    expect(screen.getByTestId("section-draft")).toHaveTextContent("Move");
    pointer(timeline, "pointerup", 500);

    const moved = (onChange.mock.calls[0][0] as Section[]).find(
      (section) => section.id === "s1",
    );
    expect(moved).toMatchObject({ startSeconds: 4, endSeconds: 6 });

    const updated = onChange.mock.calls[0][0] as Section[];
    view.rerender(<SectionLane {...props} sections={updated} />);
    const listItems = Array.from(
      screen.getByTestId("section-list").querySelectorAll("li"),
    ).map((item) => item.getAttribute("data-testid"));
    expect(listItems).toEqual([
      "section-editor-item-s2",
      "section-editor-item-s1",
    ]);
    expect(Number(screen.getByTestId("section-block-s2").dataset.lane)).toBe(0);
    expect(Number(screen.getByTestId("section-block-s1").dataset.lane)).toBe(1);
  });

  it("draws overlapping blocks in separate readable lanes", () => {
    setup({
      sections: [
        { id: "s1", name: "Verse", startSeconds: 0, endSeconds: 4 },
        { id: "s2", name: "Chorus", startSeconds: 2, endSeconds: 6 },
      ],
    });

    expect(screen.getByTestId("section-block-s1")).toHaveAttribute(
      "data-lane",
      "0",
    );
    expect(screen.getByTestId("section-block-s2")).toHaveAttribute(
      "data-lane",
      "1",
    );
    expect(screen.getByTestId("section-block-s2")).toHaveAttribute(
      "data-overlap",
      "true",
    );
    expect(
      Number.parseFloat(
        (
          screen
            .getByTestId("section-lane")
            .querySelector(".section-timeline") as HTMLElement
        ).style.minHeight,
      ),
    ).toBeGreaterThan(54);
  });

  it("uses a four-bar length around a beat- or free-snapped start", () => {
    const { onChange } = setup({
      grid: LONG_GRID,
      positionSeconds: 1.7,
      durationSeconds: 60,
    });

    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "beat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section" }));
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 0,
      endSeconds: 1.5,
    });

    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "free" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section" }));
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 0,
      endSeconds: 1.7,
    });
  });

  it("puts the timeline first, toolbar second and a split editor below", () => {
    const outOfOrder: Section[] = [
      { id: "later", name: "Chorus", startSeconds: 5, endSeconds: 7 },
      { id: "early", name: "Verse", startSeconds: 0, endSeconds: 2 },
      { id: "middle", name: "Bridge", startSeconds: 2, endSeconds: 5 },
    ];
    setup({ sections: outOfOrder });

    const lane = screen.getByTestId("section-lane");
    expect(Array.from(lane.children).map((child) => child.className)).toEqual([
      "section-timeline",
      "panel-header section-toolbar",
      "section-editor-split",
    ]);
    const split = lane.querySelector(".section-editor-split") as HTMLElement;
    expect(Array.from(split.children).map((child) => child.className)).toEqual([
      "section-list-pane",
      "section-loop-pane",
    ]);
    expect(screen.getByTestId("section-loop-editor")).toHaveTextContent(
      "Loop customisation",
    );

    const items = Array.from(
      screen.getByTestId("section-list").querySelectorAll("li"),
    ).map((item) => item.getAttribute("data-testid"));
    expect(items).toEqual([
      "section-editor-item-early",
      "section-editor-item-middle",
      "section-editor-item-later",
    ]);
    expect(screen.getByLabelText("Section name early")).toHaveValue("Verse");
    expect(screen.getByLabelText("Section start early")).toHaveValue(0);
    expect(screen.getByLabelText("Section end early")).toHaveValue(2);
  });

  it("loops a section from the editor list", () => {
    const player = createFakePlayer({ durationSeconds: 8 });
    const { onLoop } = setup({ sections: [VERSE], player });

    fireEvent.click(
      screen.getByRole("button", { name: "Loop Verse from section list" }),
    );

    expect(player.calls).toContain(
      'setLoopRange:{"startSeconds":0,"endSeconds":8}',
    );
    expect(player.calls).toContain("setLoopEnabled:true");
    expect(onLoop).toHaveBeenCalledWith(VERSE);
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

  it("seeks on a section click without starting playback", () => {
    const player = createFakePlayer({ durationSeconds: 8 });
    const onSeek = vi.fn();
    setup({ sections: [VERSE], positionSeconds: 1, player, onSeek });

    fireEvent.click(screen.getByTestId("section-block-s1"));

    expect(onSeek).toHaveBeenCalledWith(0);
    expect(player.calls).toEqual([]);
  });

  it("creates a bar-snapped section by dragging empty lane space", () => {
    const { onChange } = setup();
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    pointer(timeline, "pointerdown", 150);
    pointer(timeline, "pointermove", 350);

    const draft = screen.getByTestId("section-draft");
    expect(draft).toHaveTextContent("New section");
    expect(draft).toHaveStyle({ left: "200px", width: "200px" });
    expect(onChange).not.toHaveBeenCalled();

    pointer(timeline, "pointerup", 350);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      name: "Section 1",
      startSeconds: 2,
      endSeconds: 4,
    });
    expect(screen.queryByTestId("section-draft")).not.toBeInTheDocument();
  });

  it("respects beat and free snapping while dragging", () => {
    const { onChange } = setup();
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "beat" },
    });
    pointer(timeline, "pointerdown", 160);
    pointer(timeline, "pointermove", 390);
    pointer(timeline, "pointerup", 390);
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 1.5,
      endSeconds: 4,
    });

    onChange.mockClear();
    fireEvent.change(screen.getByLabelText("Snap"), {
      target: { value: "free" },
    });
    pointer(timeline, "pointerdown", 150);
    pointer(timeline, "pointermove", 350);
    pointer(timeline, "pointerup", 350);
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 1.5,
      endSeconds: 3.5,
    });
  });

  it("seeks on a plain click in empty lane space without creating a section", () => {
    const onSeek = vi.fn();
    const { onChange } = setup({ onSeek });
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    pointer(timeline, "pointerdown", 250);
    pointer(timeline, "pointerup", 250);

    expect(onSeek).toHaveBeenCalledWith(2.5);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("section-draft")).not.toBeInTheDocument();
  });

  it("abandons a create drag on Escape or pointer cancel", () => {
    const { onChange } = setup();
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    pointer(timeline, "pointerdown", 150);
    pointer(timeline, "pointermove", 350);
    expect(screen.getByTestId("section-draft")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("section-draft")).not.toBeInTheDocument();
    pointer(timeline, "pointerup", 350);
    expect(onChange).not.toHaveBeenCalled();

    pointer(timeline, "pointerdown", 150);
    pointer(timeline, "pointermove", 350);
    fireEvent.pointerCancel(timeline);
    expect(screen.queryByTestId("section-draft")).not.toBeInTheDocument();
    pointer(timeline, "pointerup", 350);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("resizes the right edge with bar snapping and a one-bar minimum", () => {
    const section: Section = {
      id: "s1",
      name: "Verse",
      startSeconds: 2,
      endSeconds: 6,
    };
    const { onChange } = setup({ sections: [section] });
    const handle = screen.getByTestId("section-resize-s1-end");
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    pointer(handle, "pointerdown", 600);
    pointer(timeline, "pointermove", 400);
    expect(screen.getByTestId("section-draft")).toHaveTextContent("Resize");
    pointer(timeline, "pointerup", 400);

    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 2,
      endSeconds: 4,
    });

    onChange.mockClear();
    pointer(handle, "pointerdown", 600);
    pointer(timeline, "pointermove", 250);
    pointer(timeline, "pointerup", 250);
    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 2,
      endSeconds: 4,
    });
  });

  it("resizes the left edge with bar snapping", () => {
    const section: Section = {
      id: "s1",
      name: "Verse",
      startSeconds: 2,
      endSeconds: 6,
    };
    const { onChange } = setup({ sections: [section] });
    const handle = screen.getByTestId("section-resize-s1-start");
    const timeline = screen
      .getByTestId("section-lane")
      .querySelector(".section-timeline") as HTMLElement;

    pointer(handle, "pointerdown", 200);
    pointer(timeline, "pointermove", 500);
    pointer(timeline, "pointerup", 500);

    expect((onChange.mock.calls[0][0] as Section[])[0]).toMatchObject({
      startSeconds: 4,
      endSeconds: 6,
    });
  });

  it("does not resize on an edge click without dragging", () => {
    const section: Section = {
      id: "s1",
      name: "Verse",
      startSeconds: 2,
      endSeconds: 6,
    };
    const { onChange } = setup({ sections: [section] });
    const handle = screen.getByTestId("section-resize-s1-end");

    pointer(handle, "pointerdown", 600);
    pointer(handle, "pointerup", 600);

    expect(onChange).not.toHaveBeenCalled();
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
