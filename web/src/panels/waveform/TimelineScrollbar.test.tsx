import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fitViewport, zoomViewport } from "./viewport";
import { TimelineScrollbar } from "./TimelineScrollbar";

const DURATION = 60;
const WIDTH = 960;
const FIT = fitViewport(DURATION, WIDTH);

function pointer(
  element: Element,
  type: string,
  clientX: number,
): void {
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

describe("TimelineScrollbar", () => {
  it("is hidden while the whole track fits the stage", () => {
    render(
      <TimelineScrollbar
        viewport={FIT}
        durationSeconds={DURATION}
        widthPx={WIDTH}
        onViewportChange={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("timeline-scrollbar")).not.toBeInTheDocument();
  });

  it("shows a proportional thumb that follows the visible range", () => {
    const viewport = clampStart(
      zoomViewport(FIT, DURATION, WIDTH, 2, 0),
      15,
    );
    const { rerender } = render(
      <TimelineScrollbar
        viewport={viewport}
        durationSeconds={DURATION}
        widthPx={WIDTH}
        onViewportChange={vi.fn()}
      />,
    );

    const thumb = screen.getByTestId("timeline-scrollbar-thumb");
    expect(Number.parseFloat(thumb.style.width)).toBeCloseTo(480);
    expect(Number.parseFloat(thumb.style.left)).toBeCloseTo(240);
    expect(screen.getByTestId("timeline-scrollbar")).toHaveAttribute(
      "aria-valuenow",
      "15",
    );

    const zoomed = clampStart(
      zoomViewport(viewport, DURATION, WIDTH, 2, 0),
      15,
    );
    rerender(
      <TimelineScrollbar
        viewport={zoomed}
        durationSeconds={DURATION}
        widthPx={WIDTH}
        onViewportChange={vi.fn()}
      />,
    );
    expect(
      Number.parseFloat(
        screen.getByTestId("timeline-scrollbar-thumb").style.width,
      ),
    ).toBeCloseTo(240);
  });

  it("drags the thumb to scroll the shared viewport", () => {
    const viewport = clampStart(
      zoomViewport(FIT, DURATION, WIDTH, 2, 0),
      15,
    );
    const onViewportChange = vi.fn();
    render(
      <TimelineScrollbar
        viewport={viewport}
        durationSeconds={DURATION}
        widthPx={WIDTH}
        onViewportChange={onViewportChange}
      />,
    );
    const thumb = screen.getByTestId("timeline-scrollbar-thumb");
    const track = thumb.parentElement as HTMLElement;

    pointer(thumb, "pointerdown", 480);
    pointer(track, "pointermove", 580);

    expect(onViewportChange).toHaveBeenCalled();
    const next = onViewportChange.mock.calls[0][0];
    expect(next.startSeconds).toBeCloseTo(21.25);

    pointer(track, "pointerup", 580);
    onViewportChange.mockClear();
    pointer(track, "pointermove", 700);
    expect(onViewportChange).not.toHaveBeenCalled();
  });
});

function clampStart(
  viewport: { startSeconds: number; secondsPerPixel: number },
  startSeconds: number,
) {
  return { ...viewport, startSeconds };
}
