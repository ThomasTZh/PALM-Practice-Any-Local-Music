import { describe, expect, it } from "vitest";

import {
  buildColumnPath,
  decodePeaks,
  mergePeakChannels,
  PEAKS_HEADER_BYTES,
  PeaksFormatError,
} from "./peaks";

interface EncodeOptions {
  sampleRate?: number;
  samplesPerBucket?: number;
  channels: Array<Array<[number, number]>>;
}

/**
 * Writes the documented BSPK container by hand so the decoder is tested
 * against bytes, not against its own encoder.
 */
function encodePeaks({
  sampleRate = 8000,
  samplesPerBucket = 100,
  channels,
}: EncodeOptions): ArrayBuffer {
  const buckets = channels[0].length;
  const buffer = new ArrayBuffer(
    PEAKS_HEADER_BYTES + buckets * channels.length * 4,
  );
  const view = new DataView(buffer);
  const magic = "BSPK";

  for (let index = 0; index < magic.length; index += 1) {
    view.setUint8(index, magic.charCodeAt(index));
  }
  view.setUint8(4, 1);
  view.setUint8(5, channels.length);
  view.setUint16(6, 0, true);
  view.setUint32(8, sampleRate, true);
  view.setUint32(12, buckets, true);
  view.setUint32(16, samplesPerBucket, true);

  let offset = PEAKS_HEADER_BYTES;
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    for (const channel of channels) {
      const [min, max] = channel[bucket];
      view.setInt16(offset, Math.round(min * 32767), true);
      view.setInt16(offset + 2, Math.round(max * 32767), true);
      offset += 4;
    }
  }
  return buffer;
}

function expectClose(actual: Float32Array, expected: number[]): void {
  expect(Array.from(actual)).toHaveLength(expected.length);
  expected.forEach((value, index) => {
    expect(actual[index]).toBeCloseTo(value, 4);
  });
}

describe("decodePeaks", () => {
  it("reads the header and every channel from the binary container", () => {
    const buffer = encodePeaks({
      channels: [
        [
          [-1, 1],
          [-0.5, 0.5],
        ],
        [
          [-0.25, 0.25],
          [0, 1],
        ],
      ],
    });

    const peaks = decodePeaks(buffer);

    expect(peaks.version).toBe(1);
    expect(peaks.sampleRate).toBe(8000);
    expect(peaks.buckets).toBe(2);
    expect(peaks.samplesPerBucket).toBe(100);
    expect(peaks.durationSeconds).toBeCloseTo(0.025);
    expect(peaks.channels).toHaveLength(2);
    expectClose(peaks.channels[0].min, [-1, -0.5]);
    expectClose(peaks.channels[0].max, [1, 0.5]);
    expectClose(peaks.channels[1].max, [0.25, 1]);
  });

  it("rejects a foreign or truncated container with a clear error", () => {
    const buffer = encodePeaks({ channels: [[[0, 0]]] });

    expect(() => decodePeaks(new ArrayBuffer(4))).toThrow(PeaksFormatError);
    expect(() => decodePeaks(buffer.slice(0, PEAKS_HEADER_BYTES + 2))).toThrow(
      PeaksFormatError,
    );
    expect(() => decodePeaks(new ArrayBuffer(PEAKS_HEADER_BYTES))).toThrow(
      /missing BSPK header/,
    );
  });
});

describe("mergePeakChannels", () => {
  it("takes the widest excursion of every channel for display", () => {
    const peaks = decodePeaks(
      encodePeaks({
        channels: [
          [
            [-0.2, 0.4],
            [-0.9, 0.1],
          ],
          [
            [-0.6, 0.8],
            [-0.1, 0.2],
          ],
        ],
      }),
    );

    const merged = mergePeakChannels(peaks);

    expectClose(merged.min, [-0.6, -0.9]);
    expectClose(merged.max, [0.8, 0.2]);
  });
});

describe("buildColumnPath", () => {
  const peaks = decodePeaks(
    encodePeaks({
      channels: [
        [
          [-1, 1],
          [-1, 1],
          [-1, 1],
          [-1, 1],
        ],
      ],
    }),
  );

  it("draws one vertical stroke per visible bucket", () => {
    const path = buildColumnPath(
      peaks,
      { startSeconds: 0, secondsPerPixel: peaks.durationSeconds / 100 },
      100,
      80,
    );

    expect(path.startsWith("M")).toBe(true);
    expect(path.match(/M/g)).toHaveLength(4);
    expect(path.match(/L/g)).toHaveLength(4);
    expect(path).not.toContain("NaN");
  });

  it("returns an empty path for an empty buffer", () => {
    const empty = decodePeaks(
      encodePeaks({
        channels: [[], []],
      }),
    );

    expect(
      buildColumnPath(
        empty,
        { startSeconds: 0, secondsPerPixel: 1 / 100 },
        100,
        80,
      ),
    ).toBe("");
  });
});
