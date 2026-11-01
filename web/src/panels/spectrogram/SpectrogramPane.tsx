import { useEffect, useId, useMemo, useRef, useState } from "react";

import {
  createFrequencyAxis,
  noteAxisHeight,
  noteLabels,
} from "../../spectrogram/axis";
import { SpectrogramCache, spectrogramCacheKey } from "../../spectrogram/cache";
import type { PcmLoader } from "../../spectrogram/pcm-loader";
import { paletteTable } from "../../spectrogram/palette";
import {
  DEFAULT_CEILING_DB,
  DEFAULT_FFT_SIZE,
  DEFAULT_FLOOR_DB,
  DEFAULT_MAX_HZ,
  DEFAULT_MIN_HZ,
  DEFAULT_ROWS,
  spectrogramAxisRange,
  type SpectrogramImage,
} from "../../spectrogram/stft";
import {
  createWorkerSpectrogramEngine,
  type SpectrogramEngine,
} from "../../spectrogram/worker-client";
import { timeToX, type Viewport } from "../waveform/viewport";
import "./spectrogram.css";

export interface SpectrogramPaneProps {
  /** Used to reset the cache and label the pane. */
  projectId: string;
  /** Shared with the ruler and waveform pane. */
  viewport: Viewport;
  /** Shared timeline width in CSS pixels. */
  widthPx: number;
  sampleRate: number;
  /** Asset length in frames; PCM requests are clamped to it. */
  frameCount: number;
  positionSeconds: number;
  /** Ranged PCM provider; `createRangedPcmLoader` matches the server. */
  loadPcm: PcmLoader;
  /** Injected in tests; defaults to the Web Worker engine. */
  engine?: SpectrogramEngine;
  fftSize?: number;
  rows?: number;
  floorDb?: number;
  ceilingDb?: number;
  minHz?: number;
  maxHz?: number;
  /** Overrides the note-count-derived default height. */
  heightPx?: number;
  defaultCollapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

const SCALE_SAMPLES = 16;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

function scaleGradient(): string {
  const table = paletteTable(SCALE_SAMPLES);
  const stops: string[] = [];
  for (let index = 0; index < SCALE_SAMPLES; index += 1) {
    const offset = index * 4;
    const position = (index / (SCALE_SAMPLES - 1)) * 100;
    stops.push(
      `rgb(${table[offset]}, ${table[offset + 1]}, ${table[offset + 2]}) ${position}%`,
    );
  }
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/**
 * Collapsible spectrogram pane. It shares the viewport, width and playhead of
 * the waveform pane, computes the image in a worker (never on this thread) and
 * caches it per (start, width, FFT). Collapsing only hides the body, so the
 * shared timeline above keeps its geometry.
 */
export function SpectrogramPane({
  projectId,
  viewport,
  widthPx,
  sampleRate,
  frameCount,
  positionSeconds,
  loadPcm,
  engine: engineProp,
  fftSize = DEFAULT_FFT_SIZE,
  rows = DEFAULT_ROWS,
  floorDb = DEFAULT_FLOOR_DB,
  ceilingDb = DEFAULT_CEILING_DB,
  minHz = DEFAULT_MIN_HZ,
  maxHz = DEFAULT_MAX_HZ,
  heightPx,
  defaultCollapsed = false,
  onCollapsedChange,
}: SpectrogramPaneProps) {
  const bodyId = useId();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [image, setImage] = useState<SpectrogramImage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const cache = useMemo(() => new SpectrogramCache(), [projectId]);
  const [defaultEngine] = useState<SpectrogramEngine | null>(() =>
    engineProp === undefined ? createWorkerSpectrogramEngine() : null,
  );
  const engine = engineProp ?? defaultEngine;
  const gradient = useMemo(scaleGradient, []);

  useEffect(
    () => () => {
      if (engineProp === undefined) {
        defaultEngine?.dispose();
      }
    },
    [defaultEngine, engineProp],
  );

  const axis = useMemo(() => {
    if (!(sampleRate > 0)) {
      return null;
    }
    const range = spectrogramAxisRange(sampleRate, minHz, maxHz);
    try {
      return createFrequencyAxis(range.minHz, range.maxHz, rows);
    } catch {
      return null;
    }
  }, [sampleRate, minHz, maxHz, rows]);
  const labels = useMemo(() => (axis === null ? [] : noteLabels(axis)), [axis]);
  const paneHeight = heightPx ?? noteAxisHeight(labels);

  useEffect(() => {
    if (collapsed || engine === null || !(sampleRate > 0)) {
      return;
    }
    let cancelled = false;
    const key = spectrogramCacheKey(viewport.startSeconds, widthPx, fftSize);

    function consume(promise: Promise<SpectrogramImage>): void {
      promise
        .then((next) => {
          if (!cancelled) {
            setImage(next);
            setError(null);
            setLoading(false);
          }
        })
        .catch((failure: unknown) => {
          if (!cancelled && !isAbort(failure)) {
            setError(errorMessage(failure));
            setLoading(false);
          }
        });
    }

    const cached = cache.get(key);
    if (cached !== undefined) {
      consume(cached);
      return () => {
        cancelled = true;
      };
    }

    const controller = new AbortController();
    const frames = Number.isFinite(frameCount)
      ? Math.max(0, Math.floor(frameCount))
      : 0;
    if (frames <= 0) {
      return;
    }
    const visibleEnd =
      viewport.startSeconds + widthPx * viewport.secondsPerPixel;
    const paddingSeconds = fftSize / sampleRate;
    const requestedStart = Math.max(
      0,
      Math.floor((viewport.startSeconds - paddingSeconds) * sampleRate),
    );
    const requestedEnd = Math.max(
      requestedStart + 1,
      Math.ceil((visibleEnd + paddingSeconds) * sampleRate),
    );
    const startFrame = Math.min(frames - 1, requestedStart);
    const endFrame = Math.min(frames, Math.max(startFrame + 1, requestedEnd));

    setLoading(true);
    setError(null);
    const promise = loadPcm(startFrame, endFrame, controller.signal).then(
      (chunk) =>
        engine.compute({
          pcm: chunk.samples,
          pcmStartSeconds: chunk.startFrame / chunk.sampleRate,
          sampleRate: chunk.sampleRate,
          startSeconds: viewport.startSeconds,
          secondsPerPixel: viewport.secondsPerPixel,
          widthPx,
          fftSize,
          rows,
          floorDb,
          ceilingDb,
          minHz,
          maxHz,
        }),
    );
    cache.set(key, promise);
    consume(promise);

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    cache,
    collapsed,
    engine,
    sampleRate,
    frameCount,
    viewport.startSeconds,
    viewport.secondsPerPixel,
    widthPx,
    fftSize,
    rows,
    floorDb,
    ceilingDb,
    minHz,
    maxHz,
    loadPcm,
  ]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || image === null) {
      return;
    }
    canvas.width = image.width;
    canvas.height = image.height;
    let context: CanvasRenderingContext2D | null = null;
    try {
      context = canvas.getContext("2d");
    } catch {
      context = null;
    }
    if (context === null || typeof ImageData === "undefined") {
      return;
    }
    context.putImageData(
      new ImageData(
        new Uint8ClampedArray(image.pixels),
        image.width,
        image.height,
      ),
      0,
      0,
    );
  }, [image]);

  function toggleCollapsed(): void {
    const next = !collapsed;
    setCollapsed(next);
    onCollapsedChange?.(next);
  }

  const statusText =
    error !== null
      ? "Unavailable"
      : loading
        ? "Rendering…"
        : image !== null
          ? `${image.width} × ${image.height} · ${image.fftSize} FFT`
          : "Waiting for PCM";

  const playheadX = timeToX(positionSeconds, viewport);

  return (
    <section
      className="spectrogram"
      data-testid="spectrogram"
      data-project-id={projectId}
      data-image-start={image === null ? undefined : image.startSeconds}
      style={{ width: widthPx }}
      aria-label="Spectrogram pane"
    >
      <header className="spectrogram-header">
        <button
          type="button"
          className="spectrogram-toggle"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={toggleCollapsed}
        >
          {collapsed ? "Show spectrogram" : "Hide spectrogram"}
        </button>
        <span className="spectrogram-title">Spectrogram</span>
        <span className="spectrogram-status" data-testid="spectrogram-status">
          {statusText}
        </span>
        <div className="spectrogram-scale" aria-label="dB colour scale">
          <span>{floorDb} dB</span>
          <span
            className="spectrogram-scale-bar"
            style={{ background: gradient }}
            aria-hidden="true"
          />
          <span>{ceilingDb} dB</span>
        </div>
      </header>

      <div
        className="spectrogram-body"
        id={bodyId}
        data-testid="spectrogram-body"
        hidden={collapsed}
      >
        <div className="spectrogram-axis" aria-label="Note axis">
          {axis !== null &&
            labels.map((label) => (
              <span
                key={label.midi}
                style={{ top: `${label.percentFromTop}%` }}
                data-midi={label.midi}
                data-hz={label.hz.toFixed(3)}
              >
                {label.label}
              </span>
            ))}
        </div>
        <div className="spectrogram-canvas-wrap">
          <canvas
            ref={canvasRef}
            className="spectrogram-canvas"
            data-testid="spectrogram-canvas"
            width={widthPx}
            height={rows}
            style={{ height: paneHeight }}
            aria-label={`Spectrogram of project ${projectId}`}
          />
          {playheadX >= 0 && playheadX <= widthPx && (
            <div
              className="spectrogram-playhead"
              data-testid="spectrogram-playhead"
              style={{ left: playheadX }}
            />
          )}
          {error !== null && (
            <p className="spectrogram-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
