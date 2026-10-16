// stretch_wrapper.cpp — project-owned WASM wrapper for the Signalsmith
// stretch core (M2.9, spec §11).
//
// Owns one `SignalsmithStretch<float>` instance and exposes a small C ABI
// to the AudioWorklet (and to Node for tests):
//
//   stretch_configure(channels, sampleRate, maxFrames)
//   stretch_input_latency() / stretch_output_latency()
//   stretch_input_demand(outputFrames) -> input frames the engine wants
//   stretch_process(inputFrames, outputFrames) -> frames consumed
//   stretch_set_rate(rate)          — ≈50 ms linear ramp (§11.7)
//   stretch_effective_rate()
//   stretch_reset()                 — fresh engine state (seek / reload)
//   stretch_flush_tail(maxOutputFrames)
//   stretch_seek_length()           — priming frames for the current rate
//   stretch_output_seek(inFrames)   — prime the engine from inL/inR[0..n)
//   stretch_pool_offset()           — byte offset of the I/O pool (JS views)
//   stretch_pool_input_frames()     — floats per input region (≥ maxFrames)
//
// The engine infers the playback rate from the input/output frame ratio
// of each `process` call, so this wrapper is what *controls source-frame
// consumption* (§11.1): it tracks the target rate, ramps the effective
// rate, and keeps a fractional consumption accumulator so the per-call
// integer rounding does not drift the timeline.
//
// Audio-thread constraints (spec §14.7, inherited): the I/O buffers are
// pre-allocated once in `stretch_configure` (graph-creation context, not
// a render callback); the WASM memory is built with ALLOW_MEMORY_GROWTH=0
// so the audio callback can never trigger a heap grow. No I/O, no
// logging, no exceptions.
//
// Determinism: the engine is constructed with a fixed seed so scalar and
// SIMD builds produce comparable output for the same input (the tests in
// Phase 4 rely on this).

#include "signalsmith-stretch/signalsmith-stretch.h"

#include <emscripten.h>

#include <cmath>
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
// [inL | inR | outL | outR]. The input regions hold `seekFrames` floats —
// a full priming buffer at the fastest rate (outputSeekLength(2.0) =
// inputLatency + 2.0*outputLatency, 8640 @48k / 7938 @44.1k) — because
// `outputSeek` reads inL/inR[0..seekLength) in one shot. The output
// regions only need `maxFrames`. The heap address is not known to JS, so
// `stretch_pool_offset` reports the pool's byte offset from the start of
// the wasm linear memory; JS computes the region views from the two sizes.
Sample *pool = nullptr;
int poolFrames = 0;
int seekFrames = 0;
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

// Rate state: the transport sets the target; the wrapper ramps the
// effective rate over kRateRampSeconds of rendered output.
double targetRate = 1.0;
double effectiveRate = 1.0;
double rampStartRate = 1.0;
int rampFramesTotal = 0;
int rampFramesDone = 0;

// Fractional source-consumption accumulator (§11.7.3).
double consumedFraction = 0.0;

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
  // Input regions must hold a full priming buffer at the fastest rate
  // (see the pool layout comment); the engine latencies are only known
  // after presetDefault.
  seekFrames = stretch.inputLatency() +
               static_cast<int>(kMaxRate * stretch.outputLatency());
  const int poolSize = 2 * seekFrames + 2 * maxFrames;
  if (poolFrames < poolSize) {
    delete[] pool;
    poolFrames = poolSize;
    pool = new Sample[poolSize];
  }
  bufInL = pool;
  bufInR = pool + seekFrames;
  bufOutL = pool + 2 * seekFrames;
  bufOutR = pool + 2 * seekFrames + maxFrames;
  targetRate = 1.0;
  effectiveRate = 1.0;
  rampStartRate = 1.0;
  rampFramesTotal = 0;
  rampFramesDone = 0;
  consumedFraction = 0.0;
}

int EMSCRIPTEN_KEEPALIVE stretch_input_latency() {
  return stretch.inputLatency();
}

int EMSCRIPTEN_KEEPALIVE stretch_output_latency() {
  return stretch.outputLatency();
}

// How many input frames the engine will want for `outputFrames` of output
// at the current (ramped) effective rate. The worklet fetches this many
// source frames before calling stretch_process.
int EMSCRIPTEN_KEEPALIVE stretch_input_demand(int outputFrames) {
  if (outputFrames < 0) outputFrames = 0;
  double want = static_cast<double>(outputFrames) * effectiveRate + consumedFraction;
  int inFrames = static_cast<int>(std::floor(want));
  if (inFrames < 0) inFrames = 0;
  if (inFrames > maxFrames) inFrames = maxFrames;
  return inFrames;
}

// Consume `inputFrames` (written by JS into the inL/inR regions) and write
// `outputFrames` into the outL/outR regions. Returns the consumed count.
int EMSCRIPTEN_KEEPALIVE stretch_process(int inputFrames, int outputFrames) {
  if (inputFrames < 0) inputFrames = 0;
  if (outputFrames < 0) outputFrames = 0;
  if (inputFrames > maxFrames) inputFrames = maxFrames;
  if (outputFrames > maxFrames) outputFrames = maxFrames;
  advanceRamp(outputFrames);
  IO in{bufInL, bufInR};
  IO out{bufOutL, bufOutR};
  stretch.process(in, inputFrames, out, outputFrames);
  // Carry the rounding remainder into the next demand (bounded to [0,1]).
  consumedFraction = static_cast<double>(outputFrames) * effectiveRate - inputFrames;
  if (consumedFraction < 0.0) consumedFraction = 0.0;
  if (consumedFraction > 1.0) consumedFraction = 1.0;
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

double EMSCRIPTEN_KEEPALIVE stretch_effective_rate() {
  return effectiveRate;
}

// Fresh engine state: the next process call starts from silence (the
// transport re-positions the source before calling this, e.g. on seek).
void EMSCRIPTEN_KEEPALIVE stretch_reset() {
  stretch.reset();
  consumedFraction = 0.0;
}

// Read the engine's remaining output (no further input). Writes at most
// `maxOutputFrames` into the outL/outR regions and returns the count.
int EMSCRIPTEN_KEEPALIVE stretch_flush_tail(int maxOutputFrames) {
  if (maxOutputFrames < 0) maxOutputFrames = 0;
  if (maxOutputFrames > maxFrames) maxOutputFrames = maxFrames;
  IO out{bufOutL, bufOutR};
  stretch.flush(out, maxOutputFrames, static_cast<Sample>(effectiveRate));
  return maxOutputFrames;
}

// How many input frames the engine needs to prime at the current
// effective rate: inputLatency + rate*outputLatency (5760 @1x/48k).
int EMSCRIPTEN_KEEPALIVE stretch_seek_length() {
  int n = static_cast<int>(
      stretch.outputSeekLength(static_cast<Sample>(effectiveRate)));
  if (n < 0) n = 0;
  if (n > seekFrames) n = seekFrames;
  return n;
}

// Prime the engine so the first process() output is aligned to the audio
// at inL/inR[0]. `inFrames` frames of the input regions must be valid
// (JS fills the tail with silence on underrun). Internally this resets
// the engine, writes the analysis window, and pre-rolls the synthesis
// (the canonical usage of cmd/main.cpp and the web demo).
void EMSCRIPTEN_KEEPALIVE stretch_output_seek(int inFrames) {
  if (inFrames < 0) inFrames = 0;
  if (inFrames > seekFrames) inFrames = seekFrames;
  IO in{bufInL, bufInR};
  stretch.outputSeek(in, inFrames);
  consumedFraction = 0.0;
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
  return seekFrames;
}

}  // extern "C"
