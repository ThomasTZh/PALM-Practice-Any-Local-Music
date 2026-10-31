import { describe, expect, it } from "vitest";

import { createFrequencyAxis, frequencyAtRow } from "./axis";
import { colorForLevel } from "./palette";
import {
  computeSpectrogram,
  DEFAULT_FFT_SIZE,
  DEFAULT_MAX_HZ,
  DEFAULT_MIN_HZ,
  DEFAULT_ROWS,
} from "./stft";

const SAMPLE_RATE = 44100;

function tone(frequency: number, seconds = 1, amplitude = 0.5): Float32Array {
  const samples = new Float32Array(Math.round(seconds * SAMPLE_RATE));
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] =
      amplitude * Math.sin((2 * Math.PI * frequency * index) / SAMPLE_RATE);
  }
  return samples;
}

function brightestPixel(image: {
  width: number;
  height: number;
  pixels: Uint8ClampedArray;
}): { x: number; y: number; level: number } {
  let best = { x: 0, y: 0, level: -1 };
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const offset = (y * image.width + x) * 4;
      const level =
        image.pixels[offset] +
        image.pixels[offset + 1] +
        image.pixels[offset + 2];
      if (level > best.level) {
        best = { x, y, level };
      }
    }
  }
  return best;
}

describe("computeSpectrogram", () => {
  it("uses a 2048 sample Hann window by default", () => {
    expect(DEFAULT_FFT_SIZE).toBe(2048);
    expect(DEFAULT_ROWS).toBe(256);
    expect(DEFAULT_MIN_HZ).toBe(30);
    expect(DEFAULT_MAX_HZ).toBe(20000);
  });

  it("returns an RGBA image with the requested dimensions", () => {
    const image = computeSpectrogram({
      pcm: tone(1000),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 128,
      widthPx: 128,
      rows: 128,
    });

    expect(image.width).toBe(128);
    expect(image.height).toBe(128);
    expect(image.pixels).toBeInstanceOf(Uint8ClampedArray);
    expect(image.pixels.length).toBe(128 * 128 * 4);
    expect(image.fftSize).toBe(2048);
    expect(image.sampleRate).toBe(SAMPLE_RATE);
    expect(image.floorDb).toBe(-100);
    expect(image.ceilingDb).toBe(0);
  });

  it("puts a 1 kHz tone at the 1 kHz row of the log axis", () => {
    const image = computeSpectrogram({
      pcm: tone(1000),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 128,
      widthPx: 128,
      rows: 128,
    });
    const axis = createFrequencyAxis(DEFAULT_MIN_HZ, DEFAULT_MAX_HZ, 128);
    const peak = brightestPixel(image);

    expect(frequencyAtRow(axis, peak.y)).toBeGreaterThan(900);
    expect(frequencyAtRow(axis, peak.y)).toBeLessThan(1120);
    expect(peak.level).toBeGreaterThan(300);
  });

  it("renders silence as the darkest palette entry", () => {
    const image = computeSpectrogram({
      pcm: new Float32Array(SAMPLE_RATE / 2),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 128,
      widthPx: 32,
      rows: 32,
    });
    const darkest = colorForLevel(0);
    for (let offset = 0; offset < image.pixels.length; offset += 4) {
      expect([
        image.pixels[offset],
        image.pixels[offset + 1],
        image.pixels[offset + 2],
      ]).toEqual([darkest[0], darkest[1], darkest[2]]);
    }
  });

  it("zero-pads columns whose windows reach past the PCM", () => {
    const image = computeSpectrogram({
      pcm: new Float32Array(0),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 64,
      widthPx: 16,
      rows: 16,
    });

    expect(image.width).toBe(16);
    expect(image.pixels.length).toBe(16 * 16 * 4);
  });

  it("rejects unusable requests", () => {
    const base = {
      pcm: tone(440),
      pcmStartSeconds: 0,
      sampleRate: SAMPLE_RATE,
      startSeconds: 0,
      secondsPerPixel: 1 / 128,
      widthPx: 128,
      rows: 128,
    };

    expect(() => computeSpectrogram({ ...base, widthPx: 0 })).toThrow(
      RangeError,
    );
    expect(() => computeSpectrogram({ ...base, secondsPerPixel: 0 })).toThrow(
      RangeError,
    );
    expect(() => computeSpectrogram({ ...base, sampleRate: 0 })).toThrow(
      RangeError,
    );
    expect(() => computeSpectrogram({ ...base, fftSize: 1000 })).toThrow(
      RangeError,
    );
    expect(() => computeSpectrogram({ ...base, rows: 0 })).toThrow(RangeError);
    expect(() =>
      computeSpectrogram({ ...base, floorDb: 0, ceilingDb: -100 }),
    ).toThrow(RangeError);
  });
});
