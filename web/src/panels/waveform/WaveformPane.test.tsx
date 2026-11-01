import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Selection } from "./selection";
import {
  clampViewport,
  fitViewport,
  visibleEndSeconds,
  zoomViewport,
  type Viewport,
} from "./viewport";
import { WaveformPane, type WaveformPaneProps } from "./WaveformPane";
import { makePeaksBuffer } from "./peaksFixture";

const WIDTH = 960;
const HEIGHT = 96;
const DURATION = 8;
const FIT = fitViewport(DURATION, WIDTH);

const LANE = {
  id: "mix",
  name: "Mix",
  peaks: makePeaksBuffer({
    buckets: 64,
    sampleRate: 8000,
    samplesPerBucket: 1000,
  }),
};

function setup(overrides: Partial<WaveformPaneProps> = {}) {
  const onViewportChange = vi.fn();
  const onSelectionChange = vi.fn();
  const onSeek = vi.fn();
  const onTogglePlay = vi.fn();
  const onToggleFollow = vi.fn();
  const props: WaveformPaneProps = {
    lane: LANE,
    viewport: FIT,
    durationSeconds: DURATION,
    selection: null,
    positionSeconds: 0,
    playing: false,
    follow: false,
    widthPx: WIDTH,
    heightPx: HEIGHT,
    onViewportChange,
    onSelectionChange,
    onSeek,
    onTogglePlay,
    onToggleFollow,
    ...overrides,
  };
  render(<WaveformPane {...props} />);
  return {
    onViewportChange,
    onSelectionChange,
    onSeek,
    onTogglePlay,
    onToggleFollow,
    pane: screen.getByTestId("waveform-mix"),
  };
}

describe("WaveformPane rendering", () => {
  it("draws an SVG path from the peaks binary and names the lane", () => {
    setup();

    expect(screen.getByText("Mix")).toBeInTheDocument();
    const path = screen.getByTestId("waveform-path-mix").getAttribute("d");
    expect(path).toBeTruthy();
    expect(path?.startsWith("M")).toBe(true);
    expect(path).not.toContain("NaN");
  });

  it("says so when the peaks binary is unusable", () => {
    setup({ lane: { ...LANE, peaks: new ArrayBuffer(3) } });

    expect(screen.getByText("Waveform unavailable")).toBeInTheDocument();
  });

  it("marks the selected region and the playhead", () => {
    setup({
      selection: { startSeconds: 2, endSeconds: 4 },
      positionSeconds: 3,
    });

    expect(screen.getByTestId("waveform-selection-mix")).toBeInTheDocument();
    const playhead = screen.getByTestId("waveform-playhead-mix");
    expect(playhead).toBeInTheDocument();
  });
});

describe("WaveformPane keyboard shortcuts", () => {
  it("toggles playback with space", () => {
    const { pane, onTogglePlay } = setup();

    fireEvent.keyDown(pane, { key: " " });

    expect(onTogglePlay).toHaveBeenCalledTimes(1);
  });

  it("zooms in, out and back to fit", () => {
    const { pane, onViewportChange } = setup();

    fireEvent.keyDown(pane, { key: "+" });
    const zoomed = onViewportChange.mock.calls[0][0] as Viewport;
    expect(zoomed.secondsPerPixel).toBeLessThan(FIT.secondsPerPixel);

    onViewportChange.mockClear();
    fireEvent.keyDown(pane, { key: "-" });
    expect(
      (onViewportChange.mock.calls[0][0] as Viewport).secondsPerPixel,
    ).toBeCloseTo(FIT.secondsPerPixel);

    onViewportChange.mockClear();
    fireEvent.keyDown(pane, { key: "0" });
    expect(onViewportChange).toHaveBeenCalledWith(FIT);
  });

  it("zooms out from a zoomed viewport", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const { pane, onViewportChange } = setup({ viewport: zoomed });

    fireEvent.keyDown(pane, { key: "-" });

    const next = onViewportChange.mock.calls[0][0] as Viewport;
    expect(next.secondsPerPixel).toBeGreaterThan(zoomed.secondsPerPixel);
    expect(next.secondsPerPixel).toBeLessThanOrEqual(FIT.secondsPerPixel);
  });

  it("zooms to the selection with z", () => {
    const { pane, onViewportChange } = setup({
      selection: { startSeconds: 2, endSeconds: 4 },
    });

    fireEvent.keyDown(pane, { key: "z" });

    const viewport = onViewportChange.mock.calls[0][0] as Viewport;
    expect(viewport.secondsPerPixel).toBeLessThan(DURATION / WIDTH);
    expect(viewport.startSeconds).toBeLessThanOrEqual(2);
  });

  it("toggles follow with f and seeks with the arrows", () => {
    const { pane, onSeek, onToggleFollow } = setup({ positionSeconds: 3 });

    fireEvent.keyDown(pane, { key: "f" });
    expect(onToggleFollow).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(pane, { key: "ArrowRight" });
    expect(onSeek).toHaveBeenCalledWith(4);

    fireEvent.keyDown(pane, { key: "ArrowLeft", shiftKey: true });
    expect(onSeek).toHaveBeenCalledWith(0);
  });
});

describe("WaveformPane selection drag", () => {
  it("selects a dragged region and clamps it to the track", () => {
    const { pane, onSelectionChange } = setup();

    fireEvent.mouseDown(pane, { clientX: 120, button: 0 });
    fireEvent.mouseMove(pane, { clientX: 360 });
    fireEvent.mouseUp(pane, { clientX: 360 });

    const calls = onSelectionChange.mock.calls.map(
      (call) => call[0] as Selection,
    );
    expect(calls[calls.length - 1].startSeconds).toBeCloseTo(1);
    expect(calls[calls.length - 1].endSeconds).toBeCloseTo(3);
  });

  it("seeks on a click without a drag", () => {
    const { pane, onSelectionChange, onSeek } = setup();

    fireEvent.mouseDown(pane, { clientX: 480, button: 0 });
    fireEvent.mouseUp(pane, { clientX: 480 });

    expect(onSeek).toHaveBeenCalledWith(4);
    expect(onSelectionChange).toHaveBeenLastCalledWith(null);
  });
});

describe("WaveformPane scrolling and wheel zoom", () => {
  it("scrolls the viewport with the wheel", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const { pane, onViewportChange } = setup({ viewport: zoomed });

    fireEvent.wheel(pane, { deltaY: 100 });

    const scrolled = onViewportChange.mock.calls[0][0] as Viewport;
    expect(scrolled.startSeconds).toBeGreaterThan(zoomed.startSeconds);
  });

  it("zooms around the pointer with ctrl+wheel", () => {
    const { pane, onViewportChange } = setup();

    fireEvent.wheel(pane, { deltaY: -100, ctrlKey: true, clientX: 480 });

    const zoomed = onViewportChange.mock.calls[0][0] as Viewport;
    expect(zoomed.secondsPerPixel).toBeLessThan(FIT.secondsPerPixel);
  });
});

describe("WaveformPane follow", () => {
  it("pages the viewport when the playhead reaches the right page line", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const { onViewportChange } = setup({
      viewport: zoomed,
      playing: true,
      follow: true,
      positionSeconds: 6,
    });

    const followed = onViewportChange.mock.calls[0][0] as Viewport;
    expect(followed.startSeconds).toBeGreaterThan(zoomed.startSeconds);
    expect(
      followed.startSeconds <= 6 && 6 <= visibleEndSeconds(followed, WIDTH),
    ).toBe(true);
  });

  it("does not scroll while the playhead is before the page line", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const { onViewportChange } = setup({
      viewport: zoomed,
      playing: true,
      follow: true,
      positionSeconds: 1,
    });

    expect(onViewportChange).not.toHaveBeenCalled();
  });

  it("does not auto-scroll when follow is disabled", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const { onViewportChange } = setup({
      viewport: zoomed,
      playing: true,
      follow: false,
      positionSeconds: 6,
    });

    expect(onViewportChange).not.toHaveBeenCalled();
  });

  it("pages back when playback loops to the start", () => {
    const zoomed = zoomViewport(FIT, DURATION, WIDTH, 4, 0);
    const scrolled = clampViewport(
      { startSeconds: 30, secondsPerPixel: zoomed.secondsPerPixel },
      DURATION,
      WIDTH,
    );
    const { onViewportChange } = setup({
      viewport: scrolled,
      playing: true,
      follow: true,
      positionSeconds: 0,
    });

    expect((onViewportChange.mock.calls[0][0] as Viewport).startSeconds).toBe(
      0,
    );
  });
});
