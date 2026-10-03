/**
 * Pure PCM helpers (M1.7).
 *
 * All Milestone 1 assets are interleaved little-endian float32 (f32le).
 * The browser has no native raw-PCM decoder, so these helpers split the
 * fetched bytes into per-channel samples and map between playback-time
 * and project-time positions. No decoding happens outside this module
 * and the engine.
 */

/**
 * Split an interleaved f32le buffer into per-channel Float32Arrays.
 *
 * `new Float32Array(buffer)` reads little-endian on every supported
 * platform (all modern CPUs are LE). Returns one array per channel,
 * each `floor(total / channelCount)` samples long.
 */
export function deinterleaveF32le(buffer: ArrayBuffer, channelCount: number): Float32Array[] {
  if (channelCount < 1) throw new RangeError('channelCount must be >= 1')
  const data = new Float32Array(buffer)
  const frameCount = Math.floor(data.length / channelCount)
  const channels: Float32Array[] = []
  for (let c = 0; c < channelCount; c++) {
    const out = new Float32Array(frameCount)
    for (let i = 0; i < frameCount; i++) {
      out[i] = data[i * channelCount + c]
    }
    channels.push(out)
  }
  return channels
}

/**
 * Map a playback-time frame position to the project (canonical) position.
 *
 * A playback representation at `playbackRate` covers the same real time as
 * the project at `projectRate`; a frame at index `playbackFrame` in the
 * playback stream corresponds to `playbackFrame * projectRate / playbackRate`
 * project frames.
 */
export function projectPosition(
  playbackFrame: number,
  projectRate: number,
  playbackRate: number,
): number {
  if (playbackRate <= 0) throw new RangeError('playbackRate must be > 0')
  return Math.floor((playbackFrame * projectRate) / playbackRate)
}

/** Clamp a frame position into `[0, durationFrames]`. */
export function clampToDuration(frame: number, durationFrames: number): number {
  return Math.max(0, Math.min(Math.floor(frame), durationFrames))
}

/** Format a frame position at `rate` as `m:ss.mmm`. */
export function formatTime(frames: number, rate: number): string {
  if (rate <= 0) throw new RangeError('rate must be > 0')
  const seconds = Math.max(0, frames) / rate
  const m = Math.floor(seconds / 60)
  const s = seconds - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}

/** Number of samples in one frame row for `channelCount` interleaved channels. */
export function framesFromBytes(byteCount: number, channelCount: number): number {
  if (channelCount < 1) throw new RangeError('channelCount must be >= 1')
  // 4 bytes per f32 sample, channelCount samples per frame.
  return Math.floor(byteCount / (4 * channelCount))
}
