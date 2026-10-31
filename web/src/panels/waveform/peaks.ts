import type { Viewport } from "./viewport";

/**
 * BSPK peaks container, written by the server and read here.
 *
 * Layout, all integers little-endian:
 *   0..3   ASCII "BSPK"
 *   4      uint8  version (1)
 *   5      uint8  channel count
 *   6..7   uint16 reserved (0)
 *   8..11  uint32 sample rate
 *   12..15 uint32 bucket count
 *   16..19 uint32 samples per bucket
 *   then, per bucket and per channel, one int16 min and one int16 max,
 *   scaled by 32767 and clamped to [-1, 1].
 */

export const PEAKS_HEADER_BYTES = 20;
export const PEAKS_MAGIC = "BSPK";
export const PEAKS_VERSION = 1;

const MAX_CHANNELS = 8;

export class PeaksFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PeaksFormatError";
  }
}

export interface PeakChannel {
  min: Float32Array;
  max: Float32Array;
}

export interface Peaks {
  version: number;
  sampleRate: number;
  buckets: number;
  samplesPerBucket: number;
  durationSeconds: number;
  channels: PeakChannel[];
}

function clampSample(value: number): number {
  return Math.min(1, Math.max(-1, value));
}

function readMagic(view: DataView): string {
  let magic = "";
  for (let index = 0; index < PEAKS_MAGIC.length; index += 1) {
    magic += String.fromCharCode(view.getUint8(index));
  }
  return magic;
}

export function decodePeaks(buffer: ArrayBuffer): Peaks {
  if (buffer.byteLength < PEAKS_HEADER_BYTES) {
    throw new PeaksFormatError(
      `missing BSPK header: buffer is ${buffer.byteLength} bytes, need ${PEAKS_HEADER_BYTES}`,
    );
  }
  const view = new DataView(buffer);
  const magic = readMagic(view);
  if (magic !== PEAKS_MAGIC) {
    throw new PeaksFormatError(`missing BSPK header: found "${magic}"`);
  }
  const version = view.getUint8(4);
  if (version !== PEAKS_VERSION) {
    throw new PeaksFormatError(`unsupported peaks version ${version}`);
  }
  const channelCount = view.getUint8(5);
  if (channelCount < 1 || channelCount > MAX_CHANNELS) {
    throw new PeaksFormatError(`unsupported channel count ${channelCount}`);
  }
  const sampleRate = view.getUint32(8, true);
  const buckets = view.getUint32(12, true);
  const samplesPerBucket = view.getUint32(16, true);
  if (sampleRate <= 0 || samplesPerBucket <= 0) {
    throw new PeaksFormatError(
      "peaks header has an empty sample rate or bucket",
    );
  }
  const expectedBytes = PEAKS_HEADER_BYTES + buckets * channelCount * 4;
  if (buffer.byteLength < expectedBytes) {
    throw new PeaksFormatError(
      `truncated peaks: expected ${expectedBytes} bytes, got ${buffer.byteLength}`,
    );
  }

  const channels: PeakChannel[] = Array.from({ length: channelCount }, () => ({
    min: new Float32Array(buckets),
    max: new Float32Array(buckets),
  }));
  let offset = PEAKS_HEADER_BYTES;
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    for (let channel = 0; channel < channelCount; channel += 1) {
      channels[channel].min[bucket] = clampSample(
        view.getInt16(offset, true) / 32767,
      );
      channels[channel].max[bucket] = clampSample(
        view.getInt16(offset + 2, true) / 32767,
      );
      offset += 4;
    }
  }

  return {
    version,
    sampleRate,
    buckets,
    samplesPerBucket,
    durationSeconds: (buckets * samplesPerBucket) / sampleRate,
    channels,
  };
}

/** Combines channels into one display envelope: the widest excursion wins. */
export function mergePeakChannels(peaks: Peaks): PeakChannel {
  const first = peaks.channels[0];
  if (peaks.channels.length <= 1) {
    return first ?? { min: new Float32Array(0), max: new Float32Array(0) };
  }
  const min = new Float32Array(peaks.buckets);
  const max = new Float32Array(peaks.buckets);
  for (let bucket = 0; bucket < peaks.buckets; bucket += 1) {
    let low = 1;
    let high = -1;
    for (const channel of peaks.channels) {
      low = Math.min(low, channel.min[bucket]);
      high = Math.max(high, channel.max[bucket]);
    }
    min[bucket] = low;
    max[bucket] = high;
  }
  return { min, max };
}

function formatCoordinate(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Builds the SVG path for the visible peak columns, one vertical stroke per
 * bucket. Pure: the pane renders whatever path this returns.
 */
export function buildColumnPath(
  peaks: Peaks,
  viewport: Viewport,
  widthPx: number,
  heightPx: number,
): string {
  const channel = mergePeakChannels(peaks);
  const bucketCount = channel.min.length;
  if (bucketCount === 0 || !(viewport.secondsPerPixel > 0)) {
    return "";
  }
  const bucketSeconds = peaks.samplesPerBucket / peaks.sampleRate;
  const visibleStart = viewport.startSeconds;
  const visibleEnd = visibleStart + widthPx * viewport.secondsPerPixel;
  const firstBucket = Math.max(0, Math.floor(visibleStart / bucketSeconds));
  const lastBucket = Math.min(
    bucketCount,
    Math.ceil(visibleEnd / bucketSeconds),
  );
  const centre = heightPx / 2;
  const amplitude = (heightPx / 2) * 0.92;
  const strokes: string[] = [];

  for (let bucket = firstBucket; bucket < lastBucket; bucket += 1) {
    const time = (bucket + 0.5) * bucketSeconds;
    const x = formatCoordinate(
      (time - visibleStart) / viewport.secondsPerPixel,
    );
    const top = formatCoordinate(centre - channel.max[bucket] * amplitude);
    const bottom = formatCoordinate(centre - channel.min[bucket] * amplitude);
    strokes.push(`M${x} ${top}L${x} ${bottom}`);
  }
  return strokes.join("");
}
