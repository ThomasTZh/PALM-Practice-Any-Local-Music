/**
 * stretch-profile.ts — the stretch engine's chosen configuration (M2.9,
 * spec §11.5.1–5).
 *
 * The profile records the settings the wrapper is built with so the
 * evidence doc, the transport, and the tests all refer to one source of
 * truth:
 *
 * 1. Signalsmith's default quality preset (`presetDefault`).
 * 2. Pitch shift at zero semitones (no `setTransposeSemitones` call).
 * 3. No formant manipulation (no formant calls).
 * 4. Measured input/output latency — `measureLatencies()` reads the
 *    wrapper's latency reports for a sample rate.
 * 5. Audio-thread cost — measured on the developer machine and recorded
 *    in `docs/evidence/m2.9-time-stretch-engine.md` (not a constant: it
 *    is machine dependent).
 */
import {
  STRETCH_CHANNELS,
  STRETCH_MAX_FRAMES,
  STRETCH_MEMORY_BYTES,
  type StretchEngine,
} from './stretch-host'

export interface StretchProfile {
  engine: string
  /** Pinned signalsmith-stretch commit (see BUILD.md). */
  coreCommit: string
  /** Pinned signalsmith-linear commit, tag 0.6.4 (see BUILD.md). */
  linearCommit: string
  /** Pinned Emscripten SDK release (see BUILD.md). */
  emsdk: string
  /** §11.5.1: Signalsmith's default quality preset. */
  qualityPreset: 'default'
  /** §11.5.2: pitch shift is fixed at zero semitones. */
  pitchShiftSemitones: number
  /** §11.5.3: formant manipulation is disabled. */
  formant: boolean
  /** Fixed seed: deterministic phase randomisation across builds. */
  seed: number
  channels: number
  /** Output region size in frames (fixed WASM heap, no growth). */
  maxOutputFrames: number
  /** Fixed WASM memory in bytes (§14.7: the audio callback never grows it). */
  memoryBytes: number
  /** Domain bounds for the playback speed (spec §11.6). */
  rateRange: { min: number; max: number }
  /** §11.7: rate transitions are smoothed over ≈50 ms of render time. */
  rateRampSeconds: number
  /** Where the measured audio-thread cost lives (machine dependent). */
  costNote: string
}

export const STRETCH_PROFILE: StretchProfile = {
  engine: 'signalsmith-stretch',
  coreCommit: 'a670068d9aeb64913331d5cc29337b19a457a7df',
  linearCommit: 'de55e6a50ffcf6f8f43f649692d94691c7025151',
  emsdk: '4.0.23',
  qualityPreset: 'default',
  pitchShiftSemitones: 0,
  formant: false,
  seed: 0x5eed5eed,
  channels: STRETCH_CHANNELS,
  maxOutputFrames: STRETCH_MAX_FRAMES,
  memoryBytes: STRETCH_MEMORY_BYTES,
  rateRange: { min: 0.25, max: 2.0 },
  rateRampSeconds: 0.05,
  costNote: 'docs/evidence/m2.9-time-stretch-engine.md',
}

export interface MeasuredLatencies {
  /** Engine input delay in frames (analysis window). */
  inputFrames: number
  /** Engine output delay in frames (synthesis window). */
  outputFrames: number
}

/**
 * §11.5.4: measure the engine's input and output latency for
 * `sampleRate` from the wrapper's latency reports. Configures
 * `engine` (construct it with `instantiateStretch` first) — the
 * transport accounts for both latencies when mapping playback
 * position to source position and when priming finite signals.
 */
export function measureLatencies(engine: StretchEngine, sampleRate: number): MeasuredLatencies {
  engine.configure(sampleRate)
  return engine.latencies()
}
