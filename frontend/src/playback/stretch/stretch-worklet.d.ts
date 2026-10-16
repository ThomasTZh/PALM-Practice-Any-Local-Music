/**
 * Type surface for `stretch-worklet.js` (plain script, M2.9, spec §11;
 * rolling-seek playback model in M2.10 §12.3).
 *
 * The runtime file has no imports and no exports: it is concatenated
 * into the AudioWorklet blob and imported on the main thread for its
 * side effect only, exposing itself as `globalThis.StretchWasm`. This
 * declaration file serves two purposes:
 * - it satisfies the type check of `import './stretch-worklet.js'`
 *   (module resolution maps the `.js` specifier onto this `.d.ts`);
 * - it declares the `globalThis.StretchWasm` global that the worklet
 *   processor and `stretch-host.ts` consume.
 */

export interface StretchLatencies {
  inputFrames: number
  outputFrames: number
}

export interface StretchEngineLike {
  /** Input regions: JS writes the context window here (windowLength each). */
  inL: Float32Array
  inR: Float32Array
  /** Output regions: the engine writes `process` results here. */
  outL: Float32Array
  outR: Float32Array
  /** Configure for `sampleRate` (stereo). Call once, before use. */
  configure(sampleRate: number, maxFrames?: number): void
  latencies(): StretchLatencies
  /** Frames in one context window (blockSamples + interval; 7200 @48k). */
  windowLength(): number
  /** Feed the context window and place the analysis at `rate`. */
  seek(inFrames: number, rate: number): void
  /** Consume `inputFrames`, write `outputFrames`; returns consumed. */
  process(inputFrames: number, outputFrames: number): number
  /** Target playback rate (clamped 0.25…2.0, ≈50 ms ramp; probes only). */
  setRate(rate: number): void
  /** Ramp-free rate jump (engine probes). */
  setRateNow(rate: number): void
  /** The currently ramped effective rate. */
  effectiveRate(): number
  /** Fresh engine state; the next output starts silent. */
  reset(): void
}

export interface StretchWasmApi {
  STRETCH_MAX_FRAMES: number
  STRETCH_CHANNELS: number
  STRETCH_MEMORY_BYTES: number
  /** True when the runtime supports WebAssembly SIMD (spec §11.3.7). */
  simdSupported(): boolean
  StretchEngine: new (exports: unknown) => StretchEngineLike
  /** Instantiate the engine from a bundled artifact (synchronous). */
  instantiateStretch(wasmBytes: ArrayBuffer | Uint8Array): StretchEngineLike
}

declare global {
  // eslint-disable-next-line no-var
  var StretchWasm: StretchWasmApi
}
