import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PcmChunk } from "../../spectrogram/pcm-loader";
import type {
  SpectrogramComputeInput,
  SpectrogramImage,
} from "../../spectrogram/stft";
import type { SpectrogramEngine } from "../../spectrogram/worker-client";
import { TimeRuler } from "../ruler/TimeRuler";
import type { Viewport } from "../waveform/viewport";
import { SpectrogramPane, type SpectrogramPaneProps } from "./SpectrogramPane";

const WIDTH = 1280;
const DURATION = 300;
const VIEWPORT: Viewport = {
  startSeconds: 0,
  secondsPerPixel: DURATION / WIDTH,
};

function imageFor(input: SpectrogramComputeInput): SpectrogramImage {
  return {
    width: input.widthPx,
    height: input.rows ?? 256,
    pixels: new Uint8ClampedArray(input.widthPx * (input.rows ?? 256) * 4),
    floorDb: input.floorDb ?? -100,
    ceilingDb: input.ceilingDb ?? 0,
    fftSize: input.fftSize ?? 2048,
    sampleRate: input.sampleRate,
    startSeconds: input.startSeconds,
    secondsPerPixel: input.secondsPerPixel,
  };
}

function setup(overrides: Partial<SpectrogramPaneProps> = {}) {
  const compute = vi.fn(async (input: SpectrogramComputeInput) =>
    imageFor(input),
  );
  const dispose = vi.fn();
  const engine: SpectrogramEngine = { compute, dispose };
  const loadPcm = vi.fn(
    async (startFrame: number, endFrame: number): Promise<PcmChunk> => ({
      samples: new Float32Array(4096),
      sampleRate: 44100,
      channels: 1,
      startFrame,
      frames: endFrame - startFrame,
    }),
  );
  const props: SpectrogramPaneProps = {
    projectId: "p1",
    viewport: VIEWPORT,
    widthPx: WIDTH,
    sampleRate: 44100,
    frameCount: DURATION * 44100,
    positionSeconds: 15,
    loadPcm,
    engine,
    ...overrides,
  };
  const view = render(<SpectrogramPane {...props} />);
  return { view, compute, dispose, loadPcm, props };
}

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => null,
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SpectrogramPane", () => {
  it("loads ranged PCM and renders the worker image on a canvas", async () => {
    const { compute, loadPcm } = setup();

    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));

    expect(loadPcm).toHaveBeenCalledTimes(1);
    const [startFrame, endFrame] = loadPcm.mock.calls[0];
    expect(Number.isInteger(startFrame)).toBe(true);
    expect(Number.isInteger(endFrame)).toBe(true);
    expect(startFrame).toBe(0);
    expect(endFrame).toBe(300 * 44100);

    const input = compute.mock.calls[0][0];
    expect(input.widthPx).toBe(WIDTH);
    expect(input.fftSize).toBe(2048);
    expect(input.secondsPerPixel).toBeCloseTo(DURATION / WIDTH);
    expect(input.startSeconds).toBe(0);
    expect(input.sampleRate).toBe(44100);

    await waitFor(() =>
      expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
        "1280 × 256 · 2048 FFT",
      ),
    );
    const canvas = screen.getByTestId("spectrogram-canvas");
    expect(canvas).toHaveAttribute("width", "1280");
    expect(canvas).toHaveAttribute("height", "256");
  });

  it("shows every semitone note label and the dB colour scale", async () => {
    setup();
    await waitFor(() =>
      expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
        "1280",
      ),
    );

    const axis = screen.getByLabelText("Note axis");
    const labels = Array.from(axis.querySelectorAll("span"));
    expect(labels).toHaveLength(85);
    expect(screen.getByText("C1")).toBeInTheDocument();
    expect(screen.getByText("C#1")).toBeInTheDocument();
    expect(screen.getByText("A4")).toBeInTheDocument();
    expect(screen.getByText("C8")).toBeInTheDocument();
    expect(screen.queryByText("100 Hz")).not.toBeInTheDocument();
    expect(screen.getByTestId("spectrogram-canvas")).toHaveStyle({
      height: "850px",
    });
    expect(screen.getByText("-100 dB")).toBeInTheDocument();
    expect(screen.getByText("0 dB")).toBeInTheDocument();
    expect(screen.getByLabelText("dB colour scale")).toBeInTheDocument();
  });

  it("places the playhead on the shared time axis", async () => {
    setup({ positionSeconds: 15 });
    await waitFor(() =>
      expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
        "1280 × 256",
      ),
    );

    expect(screen.getByTestId("spectrogram-playhead")).toHaveStyle({
      left: "64px",
    });
  });

  it("clamps a near-end request to the asset frame count and keeps the cache stable", async () => {
    const frameCount = DURATION * 44100;
    const { compute, loadPcm } = setup({
      viewport: { startSeconds: 299.9, secondsPerPixel: 0.001 },
      frameCount,
    });
    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));

    const [startFrame, endFrame] = loadPcm.mock.calls[0];
    expect(startFrame).toBeGreaterThanOrEqual(0);
    expect(startFrame).toBeLessThan(endFrame);
    expect(endFrame).toBe(frameCount);

    fireEvent.click(screen.getByRole("button", { name: "Hide spectrogram" }));
    fireEvent.click(screen.getByRole("button", { name: "Show spectrogram" }));
    await waitFor(() =>
      expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
        "1280 × 256",
      ),
    );
    expect(compute).toHaveBeenCalledTimes(1);
  });

  it("collapses without moving the shared timeline and reuses the cached view", async () => {
    const compute = vi.fn(async (input: SpectrogramComputeInput) =>
      imageFor(input),
    );
    const engine: SpectrogramEngine = { compute, dispose: vi.fn() };
    const viewport = VIEWPORT;
    const { rerender } = render(
      <div>
        <TimeRuler
          viewport={viewport}
          widthPx={WIDTH}
          grid={null}
          positionSeconds={15}
        />
        <SpectrogramPane
          projectId="p1"
          viewport={viewport}
          widthPx={WIDTH}
          sampleRate={44100}
          frameCount={DURATION * 44100}
          positionSeconds={15}
          loadPcm={async (startFrame, endFrame) => ({
            samples: new Float32Array(2048),
            sampleRate: 44100,
            channels: 1,
            startFrame,
            frames: endFrame - startFrame,
          })}
          engine={engine}
        />
      </div>,
    );
    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));

    const rulerWidth = screen.getByTestId("time-ruler").style.width;
    const canvas = screen.getByTestId("spectrogram-canvas");
    expect(canvas).toHaveAttribute("width", "1280");

    fireEvent.click(screen.getByRole("button", { name: "Hide spectrogram" }));

    expect(screen.getByTestId("spectrogram-body")).toHaveAttribute("hidden");
    expect(screen.getByTestId("time-ruler").style.width).toBe(rulerWidth);
    expect(canvas).toHaveAttribute("width", "1280");
    expect(compute).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Show spectrogram" }));
    await waitFor(() =>
      expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
        "1280 × 256",
      ),
    );
    expect(compute).toHaveBeenCalledTimes(1);

    rerender(
      <div>
        <TimeRuler
          viewport={viewport}
          widthPx={WIDTH}
          grid={null}
          positionSeconds={15}
        />
        <SpectrogramPane
          projectId="p1"
          viewport={viewport}
          widthPx={WIDTH}
          sampleRate={44100}
          frameCount={DURATION * 44100}
          positionSeconds={15}
          loadPcm={async (startFrame, endFrame) => ({
            samples: new Float32Array(2048),
            sampleRate: 44100,
            channels: 1,
            startFrame,
            frames: endFrame - startFrame,
          })}
          engine={engine}
        />
      </div>,
    );
    expect(screen.getByTestId("time-ruler").style.width).toBe(rulerWidth);
  });

  it("caches per (start, width, fft) and refetches only new views", async () => {
    const { view, compute, loadPcm, props } = setup();
    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));

    view.rerender(
      <SpectrogramPane
        {...props}
        viewport={{ ...VIEWPORT, startSeconds: 60 }}
      />,
    );
    await waitFor(() => expect(compute).toHaveBeenCalledTimes(2));
    expect(loadPcm).toHaveBeenCalledTimes(2);

    view.rerender(<SpectrogramPane {...props} viewport={{ ...VIEWPORT }} />);
    await waitFor(() =>
      expect(screen.getByTestId("spectrogram")).toHaveAttribute(
        "data-image-start",
        "0",
      ),
    );

    expect(compute).toHaveBeenCalledTimes(2);
    expect(loadPcm).toHaveBeenCalledTimes(2);
  });

  it("does not compute while collapsed and starts on expand", async () => {
    const { compute } = setup({ defaultCollapsed: true });

    expect(screen.getByTestId("spectrogram-body")).toHaveAttribute("hidden");
    expect(compute).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Show spectrogram" }));

    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));
  });

  it("reports a failed worker computation without crashing the pane", async () => {
    const compute = vi.fn(async () => {
      throw new Error("worker crashed");
    });
    setup({ engine: { compute, dispose: vi.fn() } });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "worker crashed",
    );
    expect(screen.getByTestId("spectrogram-status")).toHaveTextContent(
      "Unavailable",
    );
    expect(screen.getByTestId("spectrogram-canvas")).toBeInTheDocument();
  });

  it("reports a failed PCM load", async () => {
    const loadPcm = vi.fn(async () => {
      throw new Error("PCM is missing");
    });
    setup({ loadPcm });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "PCM is missing",
    );
  });
});
