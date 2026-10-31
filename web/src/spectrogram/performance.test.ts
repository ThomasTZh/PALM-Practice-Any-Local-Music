// @vitest-environment node
import { describe, expect, it } from "vitest";

import { computeSpectrogram } from "./stft";

const SAMPLE_RATE = 44100;
const PROJECT_SECONDS = 300;
const WIDTH_PX = 1280;
const MEASURED_RUNS = 3;

/**
 * Five minutes of deterministic broadband-ish PCM at the project sample rate.
 * Generation sits outside the measurement; only the view change is timed.
 */
function fiveMinutePcm(): Float32Array {
  const frames = PROJECT_SECONDS * SAMPLE_RATE;
  const samples = new Float32Array(frames);
  for (let index = 0; index < frames; index += 1) {
    const bass = Math.sin((2 * Math.PI * 55 * index) / SAMPLE_RATE);
    const note = Math.sin((2 * Math.PI * 220 * index) / SAMPLE_RATE);
    const hiss = ((index * 2654435761) % 1024) / 1024 - 0.5;
    samples[index] = 0.35 * bass + 0.25 * note + 0.05 * hiss;
  }
  return samples;
}

describe("spectrogram view change performance", () => {
  it("renders a 1280 px view of a 5 minute project in under 100 ms", () => {
    const pcm = fiveMinutePcm();
    // One small warm-up so the measurement is not dominated by lazy class
    // initialisation inside V8.
    computeSpectrogram({
      pcm: pcm.subarray(0, SAMPLE_RATE),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 32,
      widthPx: 32,
      rows: 32,
    });

    function measure(): {
      wallMs: number;
      cpuMs: number;
      image: ReturnType<typeof computeSpectrogram>;
    } {
      const cpuBefore = process.cpuUsage();
      const started = performance.now();
      const image = computeSpectrogram({
        pcm,
        pcmStartSeconds: 0,
        sampleRate: SAMPLE_RATE,
        startSeconds: 0,
        secondsPerPixel: PROJECT_SECONDS / WIDTH_PX,
        widthPx: WIDTH_PX,
        rows: 256,
      });
      const wallMs = performance.now() - started;
      const cpu = process.cpuUsage(cpuBefore);
      return { wallMs, cpuMs: (cpu.user + cpu.system) / 1000, image };
    }

    // Three independent measured runs after the warm-up. A shared host can
    // delay individual runs, so the acceptance check uses the best wall time
    // (the documented methodology) while every wall and CPU value is printed.
    const runs = Array.from({ length: MEASURED_RUNS }, measure);
    const walls = runs.map((run) => Number(run.wallMs.toFixed(1)));
    const cpus = runs.map((run) => Number(run.cpuMs.toFixed(1)));
    const bestWall = Math.min(...walls);
    const bestCpu = Math.min(...cpus);
    const sortedCpu = [...cpus].sort((a, b) => a - b);
    const medianCpu = sortedCpu[Math.floor(sortedCpu.length / 2)];

    console.info(
      `spectrogram view change (${WIDTH_PX}x256, 2048 FFT, 5 min @ ${SAMPLE_RATE} Hz, ${MEASURED_RUNS} measured runs after warm-up): wall=[${walls.join(", ")}] ms, cpu=[${cpus.join(", ")}] ms, best wall=${bestWall} ms, best cpu=${bestCpu} ms, median cpu=${medianCpu} ms`,
    );
    expect(runs[0].image.width).toBe(WIDTH_PX);
    // Shared hosts delay individual runs; the acceptance target is the best
    // wall time for the view change (see PERFORMANCE.md). CPU values are
    // recorded above for diagnosis, not used to flake the capability check.
    expect(bestWall).toBeLessThan(100);
  });
});
