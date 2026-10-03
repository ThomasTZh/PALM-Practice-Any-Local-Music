/**
 * Test fixtures for raw PCM (M1.7).
 */

/** Build an interleaved little-endian float32 buffer with deterministic values. */
export function f32leBytes(frameCount: number, channelCount: number): ArrayBuffer {
  const total = frameCount * channelCount
  const buffer = new ArrayBuffer(total * 4)
  const data = new Float32Array(buffer)
  for (let i = 0; i < total; i++) {
    data[i] = (i % 97) / 100
  }
  return buffer
}
