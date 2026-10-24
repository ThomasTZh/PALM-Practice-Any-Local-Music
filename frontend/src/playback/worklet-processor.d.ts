/**
 * Type surface of `worklet-processor.js`. The file itself is plain JS so
 * the browser can load it as a self-contained Blob-URL worklet module
 * (no imports); this declaration is what the TypeScript build sees.
 * The main thread imports `ConsumptionState` and `MixState`.
 */

export interface ConsumptionOptions {
  sampleRate: number
  channelCount: number
  frameCount: number
  /** Anchor cadence in frames; defaults to ~20 Hz (spec §16.1). */
  anchorEveryFrames?: number
  /** M2.12 §14.1 group ring capacity in frames (12 s fallback). */
  capacityFrames?: number
}

export interface ProcessResult {
  /** Frames consumed from the buffer into this block. */
  consumed: number
  /** True once when the buffer emptied while data was expected. */
  underrun: boolean
  /** True once when the position reached the source endpoint. */
  ended: boolean
  /**
   * True once when a finite practice-loop repeat sequence finished
   * (M2.11 §13.4.6): the cursor stops exactly at the loop end and the
   * `anchor` names that pass-end boundary.
   */
  loopComplete: boolean
  /**
   * Position anchor: the audible cursor was exactly `frame` at context
   * time `time` (M2.10 §12.7 — exact pairs, so the main-thread
   * extrapolation `frame + (now - time) * sampleRate * rate` follows the
   * audio actually heard). `rate` is the worklet's ramped playback rate.
   * `paused` is true only for the final anchor emitted when the pause
   * ramp completes (the exact paused position). While looping (M2.11)
   * frames are stream coordinates; `wrap` marks the pass-crossing
   * anchors emitted at each boundary (spec §13.7.5).
   */
  anchor: { frame: number; time: number; paused: boolean; rate: number; wrap?: boolean } | null
  /** Total frames buffered on the active path after this block. */
  buffered: number
  /**
   * Per-quantum peak levels (mixer path only; null on the legacy
   * single-source core). `tracks` is one peak per source (after the
   * track gain/pan, before the master gain); `master` is the final
   * output peak.
   */
  peaks: { tracks: number[]; master: number } | null
}

export class ConsumptionState {
  constructor(opts: ConsumptionOptions)
  /** Next frame to consume (playback frames). */
  readonly position: number
  readonly ended: boolean
  readonly sampleRate: number
  readonly channelCount: number
  /** Ring capacity in frames (M2.12 §14.1 group policy; 12 s fallback). */
  readonly capacity: number
  /** Frames currently in the rings (transfer path). */
  readonly available: number
  /** Total buffered frames on the active path (ring + queue, or shared avail). */
  readonly buffered: number
  /** Frames in the transfer queue (0 on the shared path). */
  readonly queued: number
  /**
   * Deinterleave f32le `buffer` into the queue.
   * @returns false if the budget would overflow (caller drops the chunk).
   */
  enqueue(buffer: ArrayBuffer): boolean
  /**
   * Queue pre-deinterleaved per-channel arrays (transfer path).
   * @returns false if the budget would overflow (caller drops the chunk).
   */
  enqueueChannels(channels: Float32Array[]): boolean
  /**
   * Consume up to `frames` frames into the provided per-channel arrays
   * (mixer path, M2.8): driven by the `MixState` shared cursor.
   * @returns the number of frames consumed.
   */
  consumeInto(outChannels: Float32Array[], frames: number): number
  /**
   * Bind the shared ring (shared path): 16-byte Int32 header
   * `[generation, writerIdx, readerIdx, 0]` + interleaved f32 data.
   */
  attachShared(sab: SharedArrayBuffer): void
  /**
   * Enter/leave the periodic-loop stream (M2.11 §13.7.4): the source
   * length no longer bounds the position and the pre-roll may start
   * below frame 0.
   */
  setLooping(looping: boolean): void
  /**
   * Drop all buffered data and move to `frame` (the stale-audio
   * barrier). On the shared path this also stores the reader index and
   * adopts `generation`; the writer index resets only on the worker's
   * flush acknowledgment.
   */
  seek(frame: number, generation?: number): void
  /** Begin the ~5 ms output ramp; consumption stops, position preserved. */
  pause(): void
  /** Resume consumption exactly at the preserved position. */
  resume(): void
  /**
   * Fill the output channels deterministically using the actual block
   * length (`outputChannels[0].length`).
   */
  process(time: number, outputChannels: Float32Array[]): ProcessResult
}

export interface MixSourceSpec {
  channelCount: number
}

export interface MixStateOptions {
  sampleRate: number
  /** Project duration in frames — every source is exactly this long. */
  frameCount: number
  sources: MixSourceSpec[]
  /**
   * Stretch engine (M2.9, spec §11): the mixed stereo is fed to the
   * engine and its output becomes the quantum output. Null keeps the
   * plain mixer path (unit tests of the mixer math).
   */
  engine?: object | null
  /** M2.12 §14.1 group ring capacity in frames (12 s fallback). */
  capacityFrames?: number
}

/** Patch for one source's mixer parameters (spec §10.3). */
export interface SourceParamPatch {
  /** Linear amplitude (the transport converts dB). */
  gain?: number
  /** Stereo balance / mono pan in [-1, 1]. */
  balance?: number
  mute?: boolean
  solo?: boolean
}

/**
 * Practice-loop geometry (M2.11, spec §13.1) in source frames. The
 * transport feeds the periodic stream; the worklet counts passes, fades
 * the joins, and stops at the end of a finite repeat sequence.
 * `repeatCount` is the total number of passes (`null` = infinite); a
 * partial first pass (enabling inside the loop) counts as pass 1.
 */
export interface LoopSpec {
  start: number
  end: number
  repeatCount: number | null
  fade: boolean
}

/**
 * Multi-source mixer state (M2.8, spec §10.3). One audio-thread state
 * machine consuming every active source in lockstep: the shared cursor
 * makes drift impossible, and a starving source pauses the whole group.
 * Always outputs 2 channels.
 */
export class MixState {
  constructor(opts: MixStateOptions)
  /** Project duration in frames. */
  readonly frameCount: number
  /** One consumption state per source. */
  readonly sources: ConsumptionState[]
  /** Next frame of the shared cursor (playback frames). */
  readonly position: number
  readonly ended: boolean
  readonly sampleRate: number
  /** Frames buffered on the weakest source (the binding budget). */
  readonly buffered: number
  /** Transfer-queue frames on the weakest source. */
  readonly queued: number
  /** Ring capacity of the weakest source. */
  readonly capacity: number
  /** M2.12 §14.4: duration of the last render callback (ms). */
  readonly lastProcessMs: number
  /**
   * Patch one source's mixer parameters; changes ramp linearly over
   * 5 ms. Solo eligibility: `!mute && (!anySolo || solo)`.
   */
  setSourceParams(index: number, patch: SourceParamPatch): void
  /** Set the master monitoring gain (linear); ramped over 5 ms. */
  setMasterGain(gain: number): void
  /**
   * Set the target playback rate (0.25…2.0). The worklet owns the
   * ≈50 ms ramp (spec §11.7/§12.5); at exactly 1× the dry bypass is
   * bit-exact (§12.4). No-op without an engine.
   */
  setRate(rate: number): void
  /**
   * The rate currently being rendered (M2.10): 1 without an engine; with
   * one it ramps toward the target and equals it in steady state.
   */
  readonly rateCurrent: number
  /** Dry-tap gain of the §12.4 bypass crossfade (1 = pure dry). */
  readonly dryGain: number
  /** Wet-tap gain of the §12.4 bypass crossfade (1 = pure stretched). */
  readonly wetGain: number
  /** Route a transfer-path chunk to one source. */
  enqueueChannels(index: number, channels: Float32Array[]): boolean
  /** Bind one source's shared ring. */
  attachShared(index: number, sab: SharedArrayBuffer): void
  /**
   * Install or clear the practice loop (M2.11, spec §13). `null` clears;
   * called with the seek (atomic) or mid-stream when enabling inside
   * the loop. Resets the pass counter (a new repeat sequence).
   */
  setLoop(spec: LoopSpec | null): void
  /** Completed loop passes since the last seek/spec change. */
  readonly loopPasses: number
  /** True once a finite repeat sequence has finished. */
  readonly loopComplete: boolean
  /** Join-fade length in output frames for the current spec/rate. */
  loopFadeFrames(rate: number): number
  /**
   * Seek every source to the same fetch frame and set the audible
   * boundary (M2.10 §12.3). `frame` is what the transport feeds first
   * (the pre-roll); `audibleFrame` (default `frame`) is where the
   * listener starts hearing. `generations` is per-source on the shared
   * path; a single number applies to all. `loop` installs the practice
   * loop atomically (M2.11): `undefined` keeps the current one, `null`
   * clears it, and a loop left installed by an outside seek is dropped
   * (spec §13.4.5).
   */
  seek(
    frame: number,
    generations?: number | number[],
    audibleFrame?: number,
    loop?: LoopSpec | null,
  ): void
  /** Begin the pause ramp on the mixed output; the cursor is preserved. */
  pause(): void
  /** Resume at the preserved cursor. */
  resume(): void
  /**
   * Mix one output quantum into 2 channels using the actual block
   * length. Reports per-track + master peaks alongside `consumed`.
   */
  process(time: number, outputChannels: Float32Array[]): ProcessResult
}

/** Procedural metronome click mixer (M3.14 §16.3). */
export class MetronomeClickMixer {
  constructor(sampleRate: number, volume?: number)
  setVolume(volume: number): void
  scheduleClicks(
    clicks: { frame: number; strength: 'downbeat' | 'beat' | 'grouping' | 'subdivision' }[],
    volume?: number,
  ): void
  render(channels: Float32Array[], startFrame: number, frames: number): void
}
