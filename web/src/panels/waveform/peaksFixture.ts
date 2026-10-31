import { PEAKS_HEADER_BYTES } from "./peaks";

export interface PeaksFixtureOptions {
  buckets?: number;
  sampleRate?: number;
  samplesPerBucket?: number;
  channels?: number;
}

/**
 * Deterministic BSPK bytes for tests and demos. The envelope is a slow sine so
 * the rendered path has visible shape without depending on real audio.
 */
export function makePeaksBuffer({
  buckets = 256,
  sampleRate = 8000,
  samplesPerBucket = 100,
  channels = 1,
}: PeaksFixtureOptions = {}): ArrayBuffer {
  const buffer = new ArrayBuffer(PEAKS_HEADER_BYTES + buckets * channels * 4);
  const view = new DataView(buffer);
  const magic = "BSPK";
  for (let index = 0; index < magic.length; index += 1) {
    view.setUint8(index, magic.charCodeAt(index));
  }
  view.setUint8(4, 1);
  view.setUint8(5, channels);
  view.setUint16(6, 0, true);
  view.setUint32(8, sampleRate, true);
  view.setUint32(12, buckets, true);
  view.setUint32(16, samplesPerBucket, true);

  let offset = PEAKS_HEADER_BYTES;
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    const envelope =
      0.15 + 0.8 * Math.abs(Math.sin((bucket / buckets) * Math.PI * 3));
    const peak = Math.round(envelope * 32767);
    for (let channel = 0; channel < channels; channel += 1) {
      view.setInt16(offset, -peak, true);
      view.setInt16(offset + 2, peak, true);
      offset += 4;
    }
  }
  return buffer;
}
