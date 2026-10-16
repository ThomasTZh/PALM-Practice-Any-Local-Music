// stretch_wrapper.cpp — project-owned WASM wrapper for the Signalsmith
// stretch core (M2.9, reworked in M2.10, spec §11/§12.3).
//
// Owns one `SignalsmithStretch<float>` instance and exposes a small C ABI
// to the AudioWorklet (and to Node for tests):
//
//   stretch_configure(channels, sampleRate, maxFrames)
//   stretch_input_latency() / stretch_output_latency()
//   stretch_window_length()        — context window frames per seek
//   stretch_seek(inFrames, rate)   — feed the context window, position it
//   stretch_process(inputFrames, outputFrames)
//   stretch_set_rate(rate)         — ≈50 ms linear ramp (engine-level)
//   stretch_set_rate_now(rate)     — ramp-free jump (engine-level)
//   stretch_effective_rate()
//   stretch_reset()                — fresh engine state (reload / reset)
//   stretch_pool_offset()          — byte offset of the I/O pool (JS views)
//   stretch_pool_input_frames()    — floats per input region
//
// Playback model (M2.10 §12.3): the worklet drives the engine with a
// *rolling seek*, exactly like the upstream web demo's live playback:
// every render quantum it writes the context window
//
//   [audible + inputLatency() − windowLength(),  audible + inputLatency())
//
// into the inL/inR regions, calls `stretch_seek(windowLength(), rate)`,
// then `stretch_process(0, quantumFrames)`. Because `seek()` puts the
// analysis block centre at `inputLatency()` frames *before* the end of
// the supplied window (the upstream "difference between the internal
// position and the input samples you're supplying"), the next output
// block is centred exactly on `audible`: audible output starts at the
// requested source boundary with the requested context before it. The
// M2.9 `outputSeek` priming path is gone — its documented alignment
// ("the next output samples correspond to the beginning of the sample")
// made the audible cursor lag the fed input by a rate-dependent amount
// the demand-based bookkeeping could not express (measured 2026-10-16:
// the replayed buffer starts at index 0 for every rate).
//
// `seek()` does not reset the synthesis state ("change the input
// location without interrupting the output"), so steady playback and
// small repositionings crossfade through the existing overlap-add; a
// hard re-position is prepared by the worklet (see the M2.10 plan §12.3
// for the reset/drain strategy).
//
// The engine's own rate ramp (`set_rate`) is not used by the playback
// path any more: the worklet ramps the playback rate itself and passes
// the current rate to every `stretch_seek`. The rate exports remain for
// engine probes and for future use.
//
// Audio-thread constraints (spec §14.7, inherited): the I/O buffers are
// pre-allocated once in `stretch_configure` (graph-creation context, not
// a render callback); the WASM memory is built with ALLOW_MEMORY_GROWTH=0
// so the audio callback can never trigger a heap grow. No I/O, no
// logging, no exceptions.
//
// Determinism: the engine is constructed with a fixed seed so scalar and
// SIMD builds produce comparable output for the same input.

#include "signalsmith-stretch/signalsmith-stretch.h"

#include <emscripten.h>

#include <cstdint>

namespace {

using Sample = float;
using Stretch = signalsmith::stretch::SignalsmithStretch<Sample>;

// Fixed seed: reproducible phase-randomisation across builds/variants.
constexpr long kSeed = 0x5EED5EEDL;
// Rate transitions are smoothed over ≈50 ms of render time (§11.7).
constexpr double kRateRampSeconds = 0.05;
// Domain bounds (spec §11.6): the wrapper clamps defensively.
constexpr double kMinRate = 0.25;
constexpr double kMaxRate = 2.0;

Stretch stretch(kSeed);

// Pre-allocated I/O pool, one contiguous allocation laid out as
// [inL | inR | outL | outR]. The input regions hold `windowFrames` floats
// (the engine's plain seekLength() = blockSamples + interval, 7200 @48k /
// 6615 @44.1k): `stretch_seek` reads the whole context window in one shot.
// The output regions only need `maxFrames`. The heap address is not known
// to JS, so `stretch_pool_offset` reports the pool's byte offset from the
// start of the wasm linear memory; JS computes the region views from the
// two sizes.
Sample *pool = nullptr;
int poolFrames = 0;
int windowFrames = 0;
Sample *bufInL = nullptr;
Sample *bufInR = nullptr;
Sample *bufOutL = nullptr;
Sample *bufOutR = nullptr;
int maxFrames = 0;
double sampleRate = 48000.0;

// Indexable channel pair for the engine's templated I/O.
struct IO {
  Sample *ch[2];
  Sample *operator[](int c) {
    return ch[c];
  }
};

// Rate state: kept for engine probes and future use; the playback path
// passes its (worklet-ramped) rate straight to `stretch_seek`.
double targetRate = 1.0;
double effectiveRate = 1.0;
double rampStartRate = 1.0;
int rampFramesTotal = 0;
int rampFramesDone = 0;

void advanceRamp(int outputFrames) {
  if (rampFramesTotal <= 0) {
    effectiveRate = targetRate;
    return;
  }
  rampFramesDone += outputFrames;
  if (rampFramesDone >= rampFramesTotal) rampFramesDone = rampFramesTotal;
  const double t = static_cast<double>(rampFramesDone) / rampFramesTotal;
  effectiveRate = rampStartRate + (targetRate - rampStartRate) * t;
  if (rampFramesDone >= rampFramesTotal) rampFramesTotal = 0;
}

}  // namespace

extern "C" {

void EMSCRIPTEN_KEEPALIVE stretch_configure(int channels, double rate, int frames) {
  maxFrames = frames;
  sampleRate = rate;
  // §11.5: Signalsmith's default quality preset, 0 semitones, no formant
  // (transpose and formant defaults are already 1.0).
  stretch.presetDefault(channels, static_cast<Sample>(rate), false);
  // The input regions must hold the full context window (see the pool
  // layout comment); the engine geometry is only known after presetDefault.
  windowFrames = stretch.seekLength();
  const int poolSize = 2 * windowFrames + 2 * maxFrames;
  if (poolFrames < poolSize) {
    delete[] pool;
    poolFrames = poolSize;
    pool = new Sample[poolSize];
  }
  bufInL = pool;
  bufInR = pool + windowFrames;
  bufOutL = pool + 2 * windowFrames;
  bufOutR = pool + 2 * windowFrames + maxFrames;
  targetRate = 1.0;
  effectiveRate = 1.0;
  rampStartRate = 1.0;
  rampFramesTotal = 0;
  rampFramesDone = 0;
}

int EMSCRIPTEN_KEEPALIVE stretch_input_latency() {
  return stretch.inputLatency();
}

int EMSCRIPTEN_KEEPALIVE stretch_output_latency() {
  return stretch.outputLatency();
}

// Frames in one context window: the engine's `seekLength()`
// (blockSamples + interval; rate-independent, 7200 @48k).
int EMSCRIPTEN_KEEPALIVE stretch_window_length() {
  return windowFrames;
}

// Feed the context window in inL/inR[0..inFrames) as the "previous input"
// and place the analysis at `playbackRate` (input frames per output
// frame). The worklet calls this once per render quantum with the window
// ending `stretch_input_latency()` frames after the desired audible
// boundary; the next process() output starts at that boundary.
void EMSCRIPTEN_KEEPALIVE stretch_seek(int inFrames, double playbackRate) {
  if (inFrames < 0) inFrames = 0;
  if (inFrames > windowFrames) inFrames = windowFrames;
  if (playbackRate < kMinRate) playbackRate = kMinRate;
  if (playbackRate > kMaxRate) playbackRate = kMaxRate;
  IO in{bufInL, bufInR};
  stretch.seek(in, inFrames, playbackRate);
}

// Consume `inputFrames` (written by JS into the inL/inR regions) and write
// `outputFrames` into the outL/outR regions. The rolling-seek playback
// path always passes `inputFrames = 0` (the context arrives via
// `stretch_seek`); non-zero input remains supported for engine probes.
int EMSCRIPTEN_KEEPALIVE stretch_process(int inputFrames, int outputFrames) {
  if (inputFrames < 0) inputFrames = 0;
  if (outputFrames < 0) outputFrames = 0;
  if (inputFrames > maxFrames) inputFrames = maxFrames;
  if (outputFrames > maxFrames) outputFrames = maxFrames;
  advanceRamp(outputFrames);
  IO in{bufInL, bufInR};
  IO out{bufOutL, bufOutR};
  stretch.process(in, inputFrames, out, outputFrames);
  return inputFrames;
}

void EMSCRIPTEN_KEEPALIVE stretch_set_rate(double rate) {
  if (rate < kMinRate) rate = kMinRate;
  if (rate > kMaxRate) rate = kMaxRate;
  if (rate == targetRate) return;
  targetRate = rate;
  rampStartRate = effectiveRate;
  rampFramesTotal = static_cast<int>(sampleRate * kRateRampSeconds);
  if (rampFramesTotal < 1) rampFramesTotal = 1;
  rampFramesDone = 0;
}

// Ramp-free rate set: the worklet's speed changes are applied through
// `stretch_seek`'s rate argument, so this is only meaningful for engine
// probes that compare ramped vs. jumped rates.
void EMSCRIPTEN_KEEPALIVE stretch_set_rate_now(double rate) {
  if (rate < kMinRate) rate = kMinRate;
  if (rate > kMaxRate) rate = kMaxRate;
  targetRate = rate;
  effectiveRate = rate;
  rampStartRate = rate;
  rampFramesTotal = 0;
  rampFramesDone = 0;
}

double EMSCRIPTEN_KEEPALIVE stretch_effective_rate() {
  return effectiveRate;
}

// Fresh engine state: the next process call starts from silence (the
// transport re-positions the source before relying on it, e.g. on load).
void EMSCRIPTEN_KEEPALIVE stretch_reset() {
  stretch.reset();
}

// Byte offset of the I/O pool from the start of the wasm linear memory.
// In wasm32 a pointer *is* a byte offset from the memory base, so the
// pool's address is the offset directly. The JS host reads this after
// configure to build its Float32Array views (heap addresses are not
// predictable, so this is the single source of truth for the layout).
int EMSCRIPTEN_KEEPALIVE stretch_pool_offset() {
  if (!pool) return -1;
  return static_cast<int>(reinterpret_cast<uintptr_t>(pool));
}

// Floats per input region (see the pool layout comment). The host uses
// this to size the inL/inR views; the output regions are maxFrames.
int EMSCRIPTEN_KEEPALIVE stretch_pool_input_frames() {
  return windowFrames;
}

}  // extern "C"
