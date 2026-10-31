/**
 * Type surface for `mix-processor.js` (plain script, t2).
 *
 * The runtime file has no imports and no exports for the browser build:
 * it is concatenated with `stretch/stretch-worklet.js` into the
 * AudioWorklet Blob. The tests (and any main-thread probe) import it
 * directly as an ES module, so this declaration gives them types
 * without turning the audio-thread code into a module the worklet
 * cannot load.
 */

export interface MixerParamPatch {
  gain?: number;
  balance?: number;
  mute?: boolean;
  solo?: boolean;
}

export interface LoopSpec {
  start: number;
  end: number;
  repeatCount?: number | null;
  fade?: boolean;
}

export interface Beat {
  frame: number;
  strength: "downbeat" | "beat" | "subdivision";
}

export interface CountInSpec {
  bars: number;
  beatsPerBar: number;
  beatFrames: number;
}

export interface CoreResult {
  consumed: number;
  underrun: boolean;
  ended: boolean;
  loopComplete: boolean;
  countInDone: boolean;
  anchor: {
    frame: number;
    time: number;
    paused: boolean;
    rate?: number;
    wrap?: boolean;
  } | null;
  buffered: number;
}

export interface StretchEngineLike {
  inL: Float32Array;
  inR: Float32Array;
  outL: Float32Array;
  outR: Float32Array;
  configure(sampleRate: number, maxFrames?: number): void;
  latencies(): { inputFrames: number; outputFrames: number };
  windowLength(): number;
  seek(inFrames: number, rate: number): void;
  process(inputFrames: number, outputFrames: number): number;
  setTranspose(semitones: number): number;
  reset(): void;
}

export class ConsumptionState {
  constructor(options: {
    sampleRate: number;
    channelCount: number;
    frameCount: number;
    anchorEveryFrames?: number;
    capacityFrames?: number;
  });
  readonly capacity: number;
  readonly frameCount: number;
  readonly buffered: number;
  readonly queued: number;
  readonly position: number;
  setLooping(looping: boolean): void;
  seek(frame: number, generation?: number): void;
  enqueueChannels(channels: Float32Array[]): boolean;
  attachShared(sab: SharedArrayBuffer): void;
}

export class ClickMixer {
  constructor(sampleRate: number, volume?: number);
  readonly renderedClicks: number;
  setVolume(volume: number): void;
  reset(): void;
  trigger(strength: "downbeat" | "beat" | "subdivision", delay?: number): void;
  render(channels: Float32Array[], frames: number, startFrame?: number): void;
}

export class PlaybackCore {
  constructor(options: {
    sampleRate: number;
    frameCount: number;
    sources: Array<{ channelCount: number }>;
    engine?: StretchEngineLike | null;
    capacityFrames?: number;
  });
  readonly frameCount: number;
  readonly buffered: number;
  readonly capacity: number;
  readonly position: number;
  readonly audible: number;
  readonly loopPasses: number;
  readonly rateCurrent: number;
  readonly rateTarget: number;
  readonly dryGain: number;
  readonly wetGain: number;
  readonly engine: StretchEngineLike | null;
  readonly sources: ConsumptionState[];
  readonly transpose: number;
  readonly paused: boolean;
  readonly clicks: ClickMixer;
  readonly params: Array<{
    gain: number;
    balance: number;
    mute: boolean;
    solo: boolean;
  }>;
  enqueueChannels(index: number, channels: Float32Array[]): boolean;
  attachShared(index: number, sab: SharedArrayBuffer): void;
  setSourceParams(index: number, patch: MixerParamPatch): void;
  setMasterGain(gain: number): void;
  setTranspose(semitones: number): number;
  setRate(rate: number): void;
  setLoop(spec: LoopSpec | null): void;
  setBeats(beats: Beat[]): void;
  setMetronomeVolume(volume: number): void;
  startCountIn(spec: CountInSpec): number;
  countInRemaining(): number;
  seek(
    frame: number,
    generations?: number | number[],
    audibleFrame?: number,
    loopSpec?: LoopSpec | null,
  ): void;
  pause(): void;
  resume(): void;
  process(time: number, outputChannels: Float32Array[]): CoreResult;
  loopFadeFrames(rate: number): number;
  loopSourceOf(streamFrame: number): number;
  nextCrossingFrom(streamFrame: number): number;
}

export const MIN_RATE: number;
export const MAX_RATE: number;
export const MIN_TRANSPOSE: number;
export const MAX_TRANSPOSE: number;
export function clampRate(rate: number): number;
export function clampTranspose(semitones: number): number;
