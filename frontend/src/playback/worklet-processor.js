/**
 * AudioWorklet processor for PCM playback (M1.12/M1.13, spec §14–15).
 *
 * Self-contained on purpose: the browser loads this exact file as a
 * Blob-URL worklet module (see `transport.ts`), where imports are not
 * available, while the unit tests import it directly as an ES module
 * (the `registerProcessor` call is guarded by a global check, so the
 * module is safe to load on the main thread). The blob prepends
 * `stretch-worklet.js` (the stretch WASM core, M2.9), which attaches
 * `globalThis.StretchWasm` before this script runs — a blob URL has no
 * base for relative imports, so concatenation is the only wiring.
 *
 * `ConsumptionState` is the pure audio-thread state machine. It has two
 * data paths:
 * - transfer: `enqueueChannels` appends deinterleaved chunks to a
 *   bounded queue; `process` drains the queue into a per-channel ring
 *   and consumes from it.
 * - shared: `attachShared` binds a SharedArrayBuffer ring (Int32 header
 *   `[generation, writerIdx, readerIdx, 0]` + interleaved f32 data);
 *   the fetch worker is the sole writer and this processor the sole
 *   reader. `process` polls the atomic writer index — never blocks.
 *
 * The ring capacity follows the transport's M2.12 §14.1 sizing policy
 * (24 s duration cap, 32 MiB byte cap, group minimum) and is passed in
 * as `capacityFrames`; M1's flat 12 s cap is only the fallback for the
 * legacy single-source init shape. `process` uses the actual
 * output-block length — never an assumed size (spec §14 intro).
 *
 * Audio-thread constraints (spec §14.7): no network, no filesystem, no
 * promises, no logging, no unbounded allocations, no waits.
 */

/* global AudioWorkletProcessor, registerProcessor */

const PAUSE_RAMP_SECONDS = 0.005

/** Default anchor cadence: ~20 times per second (spec §16.1). */
function defaultAnchorEvery(sampleRate) {
  return Math.max(1, Math.round(sampleRate / 20))
}

/**
 * Fallback ring capacity in seconds when the caller does not pass
 * `capacityFrames`. M2.12 §14.1: the transport owns the sizing policy
 * (24 s duration cap, 32 MiB byte cap, group minimum) and always passes
 * `capacityFrames`; this default only serves the legacy init shape.
 */
const DEFAULT_CAPACITY_SECONDS = 12

/** Millisecond clock where one exists (AudioWorklet, jsdom). */
const nowMs =
  typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? () => performance.now()
    : () => Date.now()

export class ConsumptionState {
  /**
   * @param {object} opts
   * @param {number} opts.sampleRate
   * @param {number} opts.channelCount
   * @param {number} opts.frameCount total frames of the source
   * @param {number} [opts.anchorEveryFrames]
   * @param {number} [opts.capacityFrames] M2.12 §14.1 group ring capacity
   */
  constructor({ sampleRate, channelCount, frameCount, anchorEveryFrames, capacityFrames }) {
    if (!(sampleRate > 0)) throw new RangeError('sampleRate must be > 0')
    if (!(channelCount >= 1)) throw new RangeError('channelCount must be >= 1')
    if (!(frameCount >= 0)) throw new RangeError('frameCount must be >= 0')
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    this.frameCount = frameCount
    this.anchorEvery = anchorEveryFrames ?? defaultAnchorEvery(sampleRate)
    this.capacity =
      Number.isFinite(capacityFrames) && capacityFrames > 0
        ? Math.floor(capacityFrames)
        : Math.ceil(sampleRate * DEFAULT_CAPACITY_SECONDS)
    this.rings = []
    for (let c = 0; c < channelCount; c++) {
      this.rings.push({ data: new Float32Array(this.capacity), read: 0, write: 0, count: 0 })
    }
    /** Transfer-path chunk queue (deinterleaved). */
    this.queue = []
    this.queuedFrames = 0
    /** Shared path: { header, data, capacity } views over the SAB. */
    this.shared = null
    /** Shared path: the generation this processor is aligned to. */
    this.localGen = 0
    /** Next frame to consume (playback frames; stream frames when looping). */
    this.position = 0
    /** M2.11: the source is fed the periodic loop stream, so the source
     * length no longer bounds the position (stream coordinates). */
    this.looping = false
    /** No data expected yet: silence without an underrun flag. */
    this.flushing = true
    this.paused = false
    this.rampRemaining = 0
    this.rampTotal = 0
    /** Last consumed sample per channel (held during the pause ramp). */
    this.lastSample = new Float32Array(channelCount)
    this.ended = false
    this.endedNotified = false
    this.underrunNotified = false
    this.lastAnchorFrame = 0
    /** Final pause anchor already sent for the current pause episode. */
    this.pauseAnchorSent = false
  }

  /** Frames currently in the rings (transfer path). */
  get available() {
    return this.rings[0].count
  }

  /**
   * Total buffered frames on the active path: ring + queue (transfer)
   * or writer − reader (shared).
   */
  get buffered() {
    if (this.shared) {
      const { header } = this.shared
      const writer = Atomics.load(header, 1)
      const reader = Atomics.load(header, 2)
      return Math.max(0, writer - reader)
    }
    return this.available + this.queuedFrames
  }

  /** Frames sitting in the transfer queue (0 on the shared path). */
  get queued() {
    return this.shared ? 0 : this.queuedFrames
  }

  /**
   * Deinterleave f32le `buffer` into the queue.
   * @returns {boolean} false if the queue would overflow (caller drops it).
   */
  enqueue(buffer) {
    const bytesPerFrame = 4 * this.channelCount
    const totalFrames = Math.floor(buffer.byteLength / bytesPerFrame)
    if (totalFrames <= 0) return false
    const view = new DataView(buffer)
    const channels = new Array(this.channelCount)
    for (let c = 0; c < this.channelCount; c++) {
      channels[c] = new Float32Array(totalFrames)
      for (let f = 0; f < totalFrames; f++) {
        channels[c][f] = view.getFloat32((f * this.channelCount + c) * 4, true)
      }
    }
    return this.enqueueChannels(channels)
  }

  /**
   * Queue pre-deinterleaved per-channel arrays (transfer path).
   * @param {Float32Array[]} channels one array per channel
   * @returns {boolean} false if the budget would overflow (caller drops it).
   */
  enqueueChannels(channels) {
    if (this.ended || this.shared) return false
    if (!Array.isArray(channels) || channels.length !== this.channelCount) return false
    let frames = channels[0].length
    if (frames <= 0) return false
    // Never accept data beyond the valid endpoint (defensive; the
    // transport already clamps chunk ranges). The valid remainder
    // excludes everything already buffered (ring + queue). Looping
    // streams are unbounded (M2.11) — only the ring budget applies.
    if (!this.looping) {
      frames = Math.min(
        frames,
        this.frameCount - this.position - this.available - this.queuedFrames,
      )
      if (frames <= 0) return false
    }
    if (this.available + this.queuedFrames + frames > this.capacity) return false
    const trimmed = channels.map((ch) => (ch.length === frames ? ch : ch.subarray(0, frames)))
    this.queue.push({ channels: trimmed, frames })
    this.queuedFrames += frames
    this.flushing = false
    this.underrunNotified = false
    return true
  }

  /**
   * Move queued chunks into the rings while they fit. Called from
   * `process`; a chunk that does not fit waits for consumption to free
   * space (chunk ≈ 1 s < 12 s capacity, so progress is guaranteed).
   */
  drainQueue() {
    if (this.shared) return
    while (this.queue.length > 0) {
      const head = this.queue[0]
      if (this.available + head.frames > this.capacity) break
      for (let c = 0; c < this.channelCount; c++) {
        const ring = this.rings[c]
        const src = head.channels[c]
        for (let f = 0; f < head.frames; f++) {
          ring.data[ring.write] = src[f]
          ring.write = (ring.write + 1) % this.capacity
        }
        ring.count += head.frames
      }
      this.queue.shift()
      this.queuedFrames -= head.frames
    }
  }

  /**
   * Bind the shared ring (shared path). `sab` layout: 16-byte Int32
   * header `[generation, writerIdx, readerIdx, 0]` + interleaved f32.
   * The processor aligns to the current header generation.
   */
  attachShared(sab) {
    const header = new Int32Array(sab, 0, 4)
    const data = new Float32Array(sab, 16)
    const capacity = Math.floor(data.length / this.channelCount)
    this.shared = { header, data, capacity }
    // The SAB is authoritative on the shared path; keep the capacity
    // reported to the transport in sync with what the writer can hold.
    this.capacity = capacity
    this.localGen = Atomics.load(header, 0)
  }

  /** M2.11: enter/leave the periodic-loop stream (spec §13.7.4). */
  setLooping(looping) {
    this.looping = looping === true
  }

  /**
   * Drop all buffered data and move to `frame`. This is the stale-audio
   * barrier: nothing enqueued before the seek can be output after it.
   * On the shared path the processor stores its own (reader) index and
   * adopts the new generation; the writer index is reset only when the
   * worker receives the flush acknowledgment (spec §15.1.6).
   */
  seek(frame, generation) {
    const target = this.looping
      ? Math.floor(frame) // stream coordinates may be negative (loop pre-roll)
      : Math.max(0, Math.min(Math.floor(frame), this.frameCount))
    for (const ring of this.rings) {
      ring.read = 0
      ring.write = 0
      ring.count = 0
    }
    this.queue.length = 0
    this.queuedFrames = 0
    if (this.shared) {
      Atomics.store(this.shared.header, 2, target)
    }
    if (typeof generation === 'number') this.localGen = generation
    this.position = target
    this.flushing = true
    this.paused = false
    this.rampRemaining = 0
    this.rampTotal = 0
    this.ended = !this.looping && target >= this.frameCount
    this.endedNotified = false
    this.underrunNotified = false
    this.lastAnchorFrame = target
    this.pauseAnchorSent = false
    this.lastSample.fill(0)
  }

  /** Begin the ~5 ms output ramp; consumption stops, position preserved. */
  pause() {
    if (this.paused) return
    this.paused = true
    this.rampTotal = Math.max(1, Math.round(PAUSE_RAMP_SECONDS * this.sampleRate))
    this.rampRemaining = this.rampTotal
  }

  /** Resume consumption exactly at the preserved position. */
  resume() {
    this.paused = false
    this.rampRemaining = 0
    this.pauseAnchorSent = false
  }

  /**
   * Fill the output channels deterministically.
   * @param {number} time context time at which this block plays
   * @param {Float32Array[]} outputChannels one array per channel
   */
  process(time, outputChannels) {
    const frames = outputChannels[0].length
    const out = { consumed: 0, underrun: false, ended: false, anchor: null, buffered: 0 }
    if (this.ended) {
      this.fillSilence(outputChannels, 0, frames)
      out.buffered = this.buffered
      return out
    }
    if (this.paused) {
      if (this.rampRemaining > 0) {
        // Hold the last samples, scaled down; position does not advance.
        const level = this.rampRemaining / this.rampTotal
        for (let c = 0; c < this.channelCount; c++) {
          const s = this.lastSample[c] * level
          for (let i = 0; i < frames; i++) outputChannels[c][i] = s
        }
        this.rampRemaining -= frames
        if (this.rampRemaining <= 0 && !this.pauseAnchorSent) {
          // Final anchor at the exact paused position (spec §16.1).
          this.pauseAnchorSent = true
          out.anchor = { frame: this.position, time, paused: true }
        }
      } else {
        this.fillSilence(outputChannels, 0, frames)
      }
      out.buffered = this.buffered
      return out
    }
    let take
    if (this.shared) {
      take = this.consumeShared(outputChannels, frames)
    } else {
      this.drainQueue()
      take = this.consumeRing(outputChannels, frames)
    }
    if (take < frames) {
      this.fillSilence(outputChannels, take, frames - take)
      // An underrun is only reported when data was expected — silence
      // right after a seek (flushing) is not one.
      if (!this.flushing && !this.underrunNotified) {
        out.underrun = true
        this.underrunNotified = true
      }
    }
    this.position += take
    const endTime = time + take / this.sampleRate
    if (this.position >= this.frameCount) {
      this.ended = true
      if (!this.endedNotified) {
        this.endedNotified = true
        out.ended = true
        // Exact pair: the end frame plays `take` frames into this block.
        out.anchor = { frame: this.position, time: endTime, paused: false, rate: 1 }
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      // Exact pair: the frame named plays at the named context time
      // (spec §12.7: the UI maps through the ledger, not through a
      // lagging estimate).
      out.anchor = { frame: this.position, time: endTime, paused: false, rate: 1 }
      this.lastAnchorFrame = this.position
    }
    out.consumed = take
    out.buffered = this.buffered
    return out
  }

  /**
   * Consume from the transfer-path rings.
   * @returns {number} frames consumed
   */
  consumeRing(outputChannels, frames) {
    const avail = this.available
    const take = Math.min(frames, avail)
    for (let c = 0; c < this.channelCount; c++) {
      const ring = this.rings[c]
      for (let i = 0; i < take; i++) {
        const s = ring.data[ring.read]
        ring.read = (ring.read + 1) % this.capacity
        outputChannels[c][i] = s
      }
      ring.count -= take
      if (take > 0) this.lastSample[c] = outputChannels[c][take - 1]
    }
    return take
  }

  /**
   * Consume from the shared ring (SPSC, polling only).
   * @returns {number} frames consumed
   */
  consumeShared(outputChannels, frames) {
    const { header, data, capacity } = this.shared
    const gen = Atomics.load(header, 0)
    if (gen !== this.localGen) {
      // Generation mismatch: the ring holds stale data. Silence; the
      // worker resets it after the flush acknowledgment.
      return 0
    }
    const reader = Atomics.load(header, 2)
    const writer = Atomics.load(header, 1)
    const avail = Math.max(0, writer - reader)
    let take = Math.min(frames, avail)
    if (!this.looping) take = Math.min(take, this.frameCount - this.position)
    if (take <= 0) return 0
    for (let i = 0; i < take; i++) {
      // Negative-safe: loop streams may start below 0 (periodic pre-roll).
      const src = (((reader + i) % capacity) + capacity) % capacity
      const base = src * this.channelCount
      for (let c = 0; c < this.channelCount; c++) {
        outputChannels[c][i] = data[base + c]
      }
    }
    Atomics.store(header, 2, reader + take)
    for (let c = 0; c < this.channelCount; c++) {
      this.lastSample[c] = outputChannels[c][take - 1]
    }
    this.flushing = false
    return take
  }

  fillSilence(outputChannels, from, count) {
    for (let c = 0; c < this.channelCount; c++) outputChannels[c].fill(0, from, from + count)
  }

  /**
   * Consume up to `frames` frames into the provided per-channel arrays
   * (mixer path, M2.8): one `ConsumptionState` per source, consumed by
   * the `MixState` shared cursor. Advances `position`; the caller is
   * responsible for mixing the result.
   * @param {Float32Array[]} outChannels one array per channel
   * @returns {number} frames consumed
   */
  consumeInto(outChannels, frames) {
    if (this.ended) return 0
    if (this.shared) {
      const { header, data, capacity } = this.shared
      const gen = Atomics.load(header, 0)
      if (gen !== this.localGen) return 0
      const reader = Atomics.load(header, 2)
      const writer = Atomics.load(header, 1)
      const avail = Math.max(0, writer - reader)
      let take = Math.min(frames, avail)
      if (!this.looping) take = Math.min(take, this.frameCount - this.position)
      if (take <= 0) return 0
      for (let i = 0; i < take; i++) {
        const src = (((reader + i) % capacity) + capacity) % capacity
        const base = src * this.channelCount
        for (let c = 0; c < this.channelCount; c++) outChannels[c][i] = data[base + c]
      }
      Atomics.store(header, 2, reader + take)
      this.position += take
      this.flushing = false
      return take
    }
    this.drainQueue()
    let take = Math.min(frames, this.available)
    if (!this.looping) take = Math.min(take, this.frameCount - this.position)
    if (take <= 0) return 0
    for (let c = 0; c < this.channelCount; c++) {
      const ring = this.rings[c]
      for (let i = 0; i < take; i++) {
        outChannels[c][i] = ring.data[ring.read]
        ring.read = (ring.read + 1) % this.capacity
      }
      ring.count -= take
    }
    this.position += take
    return take
  }
}

/** Mixer parameter ramp time (spec §10.3). */
const MIX_RAMP_SECONDS = 0.005

/**
 * Worklet-side playback-rate ramp time (spec §11.7): the worklet ramps
 * the rate itself and passes the current value to every engine `seek`
 * (the engine's own `setRate` ramp is unused by the playback path).
 */
const RATE_RAMP_SECONDS = 0.05

/**
 * Dry/wet crossfade time at 1× (spec §12.4). The crossfade only ever
 * runs while both sides are at exactly 1×, so the two signals are
 * time-aligned frame-for-frame (never mixing differently timed dry and
 * stretched audio).
 */
const BYPASS_CROSSFADE_SECONDS = 0.005

/**
 * Silent pre-roll (output frames) run before a wet start after a hard
 * re-position. The engine's overlap-add accumulator fills over roughly
 * one block (measured: full level after 5760 output frames at every
 * rate), so a hard seek that starts at rate ≠ 1 primes the engine with
 * this many inaudible frames instead of fading the boundary in.
 */
const WARMUP_OUT_FRAMES = 5760

/**
 * Mix-ring capacity in frames. The ring holds the stem-mixed stereo
 * (master gain stays post-engine, §11.1) spanning the engine's context
 * window plus the rate-dependent lookahead (`r*outLat + inLat`, up to
 * 8640 frames at 2×) with margin.
 */
const MIX_RING_FRAMES = 16384

/**
 * Multi-source mixer state (M2.8, spec §10.3): ONE audio-thread state
 * machine consuming every active source in lockstep. Each source is a
 * plain `ConsumptionState`; the mixer advances all of them by the same
 * amount per quantum (the shared cursor), so alignment is exact and
 * drift is impossible.
 *
 * Per quantum the mixer:
 * - consumes `min(block, min buffered, endpoint)` frames per source;
 * - fills per-sample coefficient tables (5 ms linear ramps for gain,
 *   balance, mute/solo envelope, and master gain — transcendentals stay
 *   out of the sample loop);
 * - sums the sources (stereo: 3 dB/side balance; mono: equal-power pan),
 *   applies the master gain, and tracks per-track + master peaks.
 *
 * Solo eligibility: `!mute && (!anySolo || solo)` — mute always wins,
 * solo only silences the other sources. Visibility is a UI concern and
 * never reaches the audio thread (hidden ≠ muted).
 *
 * With a stretch engine (`opts.engine`, M2.9/M2.10, spec §11–§12) the
 * data path becomes: per-stem gain/pan/mute/solo → stereo sum → mix
 * ring → stretch → master gain → output (§11.1 order). The ring holds
 * the stem-mixed stereo and is filled from the sources with a
 * rate-dependent lookahead; two output taps read it:
 *
 * - **dry** — the exact-speed 1× bypass: frames read straight from the
 *   ring at the audible cursor (bit-identical to the no-engine path);
 * - **wet** — the rolling seek (§12.3): every render quantum the
 *   worklet writes the context window
 *   `[S + r*outLat + inLat − windowLength, S + r*outLat + inLat)` into
 *   the engine input regions, calls `seek(windowLength, r)` and
 *   `process(0, frames)`; the emitted block is centred exactly on the
 *   audible cursor `S` (advancing `r` frames per output frame).
 *
 * The output is `dryGain*dry + wetGain*wet`; the engine keeps rolling
 * (inaudible) during bypass, so rate changes are always prepared: the
 * crossfade to wet runs at exactly 1× first, then the worklet's own
 * ≈50 ms rate ramp starts (wet→dry mirrors that order, §12.4). A hard
 * re-position resets the engine and (when the rate is ≠ 1) primes it
 * with an inaudible pre-roll, so the boundary starts at full level
 * (§12.3).
 */
export class MixState {
  /**
   * @param {object} opts
   * @param {number} opts.sampleRate
   * @param {number} opts.frameCount project duration — all sources equal
   * @param {Array<{channelCount: number}>} opts.sources
   * @param {object|null} [opts.engine] stretch engine (M2.9/M2.10, spec §11–§12)
   * @param {number} [opts.capacityFrames] M2.12 §14.1 group ring capacity
   */
  constructor({ sampleRate, frameCount, sources, engine = null, capacityFrames = 0 }) {
    if (!(sampleRate > 0)) throw new RangeError('sampleRate must be > 0')
    if (!(frameCount >= 0)) throw new RangeError('frameCount must be >= 0')
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new RangeError('sources must be a non-empty array')
    }
    this.sampleRate = sampleRate
    this.frameCount = frameCount
    this.sources = sources.map(
      (s) =>
        new ConsumptionState({
          sampleRate,
          channelCount: s.channelCount,
          frameCount,
          // The mixer emits its own anchors from the shared cursor.
          anchorEveryFrames: Number.MAX_SAFE_INTEGER,
          capacityFrames,
        }),
    )
    this.params = sources.map(() => ({
      gain: 1.0,
      balance: 0.0,
      mute: false,
      solo: false,
      gFrom: 1.0,
      bFrom: 0.0,
      eFrom: 1.0,
      gTo: 1.0,
      bTo: 0.0,
      eTo: 1.0,
      rampTotal: 0,
      rampRemaining: 0,
    }))
    this.masterGain = 1.0
    this.masterFrom = 1.0
    this.masterTo = 1.0
    this.masterRampTotal = 0
    this.masterRampRemaining = 0
    this.position = 0
    this.ended = false
    this.endedNotified = false
    this.underrunNotified = false
    this.paused = false
    this.rampTotal = 0
    this.rampRemaining = 0
    this.pauseAnchorSent = false
    this.lastAnchorFrame = 0
    this.anchorEvery = defaultAnchorEvery(sampleRate)
    /** Playback rate reported in anchors (1 without an engine). */
    this.rateCurrent = 1
    /** Last mixed output sample per channel (held during the pause ramp). */
    this.lastSample = new Float32Array(2)
    /** Per-quantum peaks, reset after each report. */
    this.trackPeaks = sources.map(() => 0)
    this.masterPeak = 0
    /** M2.12 §14.4: duration of the last render callback (ms). */
    this.lastProcessMs = 0
    // Stretch engine (M2.9/M2.10): null keeps the plain mixer path.
    this.engine = engine
    /** Audible source position: content of the next output frame. */
    this.audible = 0
    if (engine) {
      const lat = engine.latencies()
      this.inLat = lat.inputFrames
      this.outLat = lat.outputFrames
      this.windowFrames = engine.windowLength()
      this.ringCap = MIX_RING_FRAMES
      this.ringL = new Float32Array(this.ringCap)
      this.ringR = new Float32Array(this.ringCap)
      /** Absolute frame of ring slot 0 (monotonic). */
      this.ringBase = 0
      /** Oldest valid frame still in the ring. */
      this.ringStart = 0
      /** Frame after the newest stem-mixed frame in the ring. */
      this.ringEnd = 0
      /** Worklet-owned ≈50 ms playback-rate ramp (spec §11.7). */
      this.rateTarget = 1
      this.rateGoal = 1
      this.rateFrom = 1
      this.rateRampTotal = Math.max(1, Math.round(RATE_RAMP_SECONDS * sampleRate))
      this.rateRampRemaining = 0
      /** 1× bypass state (spec §12.4): 'dry' | 'wet' plus a crossfade. */
      this.bypass = 'dry'
      this.xfade = null // { to: 'wet' | 'dry', fromDry, fromWet, remaining }
      this.xfadeTotal = Math.max(1, Math.round(BYPASS_CROSSFADE_SECONDS * sampleRate))
      this.dryGain = 1
      this.wetGain = 0
      /** Quantum-start gains (the mix loop interpolates to the new ones). */
      this.dryGainPrev = 1
      this.wetGainPrev = 0
      /** Rolling output frames since the last engine reset (warm-up). */
      this.rolledFrames = 0
      /** Remaining silent pre-roll (output frames, §12.3). */
      this.warmupRemaining = 0
    }
    // Practice-loop rendering (M2.11, spec §13). The loop makes the data
    // stream periodic over [start, end): stream coordinates are
    // source-aligned at the seek boundary, `loopNextCrossing` is the
    // stream frame of the next pass end (the content discontinuity), and
    // the pass counter drives the finite-repeat stop (§13.4.6).
    this.loop = null // { start, end, len, repeatCount, fade }
    this.loopPasses = 0
    this.loopComplete = false
    this.loopNextCrossing = null
    this.loopCounted = false
    this.loopAnchor = null
    this.loopCompletion = null // { frame, time } of the final crossing
    // Bounded per-quantum scratch, grown only if a larger block ever
    // arrives (audio thread: no steady-state allocation). The engine
    // path mixes ring fills in bounded chunks (≤ `engineFillChunk`).
    this.engineFillChunk = 4096
    this.blockCap = 0
    this.coeffL = []
    this.coeffR = []
    this.temp = []
    this.masterCoeff = null
    this.mixL = null
    this.mixR = null
    this.ensureBlockCapacity(engine ? this.engineFillChunk : 128)
  }

  /** Frames buffered on the weakest source (the binding budget). */
  get buffered() {
    let b = Infinity
    for (const s of this.sources) b = Math.min(b, s.buffered)
    return b === Infinity ? 0 : b
  }

  /** Transfer-queue frames on the weakest source. */
  get queued() {
    let q = Infinity
    for (const s of this.sources) q = Math.min(q, s.queued)
    return q === Infinity ? 0 : q
  }

  /** Ring capacity of the weakest source. */
  get capacity() {
    let cap = Infinity
    for (const s of this.sources) cap = Math.min(cap, s.capacity)
    return cap === Infinity ? 0 : cap
  }

  ensureBlockCapacity(frames) {
    if (frames <= this.blockCap) return
    this.blockCap = frames
    this.coeffL = this.sources.map(() => new Float32Array(frames))
    this.coeffR = this.sources.map(() => new Float32Array(frames))
    this.temp = this.sources.map((s) =>
      Array.from({ length: s.channelCount }, () => new Float32Array(frames)),
    )
    this.masterCoeff = new Float32Array(frames)
    // Engine path: the mixed stereo before the stretcher (§11.1 order).
    this.mixL = new Float32Array(frames)
    this.mixR = new Float32Array(frames)
  }

  /**
   * Patch the mixer parameters for one source (spec §10.3). `gain` is
   * linear amplitude (the transport converts dB); `balance` is in
   * [-1, 1]. Mute/solo change the source's eligibility, ramped like gain.
   */
  setSourceParams(index, patch) {
    const p = this.params[index]
    if (!p) return
    const changed =
      (patch.gain !== undefined && patch.gain !== p.gain) ||
      (patch.balance !== undefined && patch.balance !== p.balance) ||
      (patch.mute !== undefined && patch.mute !== p.mute) ||
      (patch.solo !== undefined && patch.solo !== p.solo)
    if (!changed) return
    if (patch.gain !== undefined) {
      p.gain = patch.gain
      p.gTo = patch.gain
    }
    if (patch.balance !== undefined) {
      p.balance = patch.balance
      p.bTo = patch.balance
    }
    if (patch.mute !== undefined) p.mute = patch.mute
    if (patch.solo !== undefined) p.solo = patch.solo
    // Solo eligibility: mute always wins; solo only silences the others
    // when at least one source is soloed.
    const anySolo = this.params.some((q) => q.solo)
    const dirty = new Set()
    this.params.forEach((q, i) => {
      const target = !q.mute && (!anySolo || q.solo) ? 1.0 : 0.0
      if (target !== q.eTo) {
        q.eTo = target
        dirty.add(i)
      }
    })
    dirty.add(index)
    dirty.forEach((i) => this.startParamRamp(i))
  }

  /**
   * Snapshot the in-flight values and begin a fresh 5 ms linear ramp
   * toward the current targets for source `i`.
   */
  startParamRamp(i) {
    const p = this.params[i]
    const k = p.rampTotal > 0 ? p.rampRemaining / p.rampTotal : 0
    p.gFrom = p.gTo - (p.gTo - p.gFrom) * k
    p.bFrom = p.bTo - (p.bTo - p.bFrom) * k
    p.eFrom = p.eTo - (p.eTo - p.eFrom) * k
    p.rampTotal = Math.max(1, Math.round(MIX_RAMP_SECONDS * this.sampleRate))
    p.rampRemaining = p.rampTotal
  }

  /** Set the master monitoring gain (linear); ramped over 5 ms. */
  setMasterGain(gain) {
    if (!(gain >= 0)) return
    if (gain === this.masterGain) return
    const k = this.masterRampTotal > 0 ? this.masterRampRemaining / this.masterRampTotal : 0
    this.masterFrom = this.masterTo - (this.masterTo - this.masterFrom) * k
    this.masterTo = gain
    this.masterGain = gain
    this.masterRampTotal = Math.max(1, Math.round(MIX_RAMP_SECONDS * this.sampleRate))
    this.masterRampRemaining = this.masterRampTotal
  }

  /** Route a transfer-path chunk to one source. */
  enqueueChannels(index, channels) {
    const s = this.sources[index]
    if (!s) return false
    const ok = s.enqueueChannels(channels)
    if (ok) this.underrunNotified = false
    return ok
  }

  /** Bind one source's shared ring. */
  attachShared(index, sab) {
    const s = this.sources[index]
    if (s) s.attachShared(sab)
  }

  /**
   * Install or clear the practice loop (M2.11, spec §13).
   *
   * The transport owns the periodic data stream; the worklet only needs
   * the geometry to count passes, fade the joins, and stop at the end of
   * a finite repeat sequence. `spec` is `{start, end, repeatCount,
   * fade}` in source frames (the stream is source-aligned at the seek
   * boundary) or `null` to clear. Called with the seek (atomic) or
   * mid-stream when looping is enabled inside the loop (§13.4.3); any
   * other spec change goes through a controlled re-seek (§13.8).
   */
  setLoop(spec) {
    this.loop = spec
      ? {
          start: Math.floor(spec.start),
          end: Math.floor(spec.end),
          len: Math.max(1, Math.floor(spec.end) - Math.floor(spec.start)),
          repeatCount: spec.repeatCount ?? null,
          fade: spec.fade !== false,
        }
      : null
    this.loopPasses = 0
    this.loopComplete = false
    this.loopAnchor = null
    this.loopCompletion = null
    this.loopCounted = false
    this.loopNextCrossing = this.loop ? this.nextCrossingFrom(this.loopCursor()) : null
    this.sources.forEach((s) => s.setLooping(this.loop !== null))
  }

  /** The audible cursor: fractional on the engine path, integer otherwise. */
  loopCursor() {
    return this.engine ? this.audible : this.position
  }

  /** Source frame carried by stream coordinate `c` (spec §13.7.4). */
  loopSourceOf(c) {
    const loop = this.loop
    const rel = (c - loop.start) % loop.len
    return loop.start + (rel < 0 ? rel + loop.len : rel)
  }

  /** Stream coordinate of the next pass end at or after `c`. */
  nextCrossingFrom(c) {
    return c + (this.loop.end - this.loopSourceOf(c))
  }

  /**
   * Join-fade length in output frames (spec §13.6): 5 ms, limited to a
   * fraction (¼) of the pass so short loops keep their duration.
   */
  loopFadeFrames(rate) {
    const loop = this.loop
    if (!loop.fade) return 0
    const byTime = Math.round(0.005 * this.sampleRate)
    const byLoop = Math.max(1, Math.round(loop.len / Math.max(rate, 0.01) / 4))
    return Math.min(byTime, byLoop)
  }

  /**
   * Loop bookkeeping for one quantum: locate the pass crossing whose
   * fade notch overlaps `[S, S + rate*frames)`, count the completed
   * pass, schedule the wrap anchor, and flag the finite-repeat stop.
   * Returns `{center, fade, final}` (`center` in output frames, possibly
   * fractional or ≥ frames) or null. At most one crossing overlaps a
   * quantum for loops ≥ 100 ms; the pass ends are exactly `len` stream
   * frames apart, so no per-iteration duration rounding accumulates
   * (spec §13.7.5).
   */
  loopQuantum(time, rate, frames) {
    const loop = this.loop
    if (!loop) return null
    // The audible cursor: the engine path tracks a fractional cursor,
    // the plain path advances the integer position by one frame per
    // output frame.
    const S = this.loopCursor()
    const advance = rate * frames
    const fade = this.loopFadeFrames(rate)
    let c = this.loopNextCrossing
    // Advance past crossings whose notch (fade-in) has fully passed; the
    // head crossing is then uncounted again.
    while (c !== null && c + fade * rate <= S) {
      c += loop.len
      this.loopCounted = false
    }
    if (c === null || c - fade * rate >= S + advance) {
      this.loopNextCrossing = c
      return null
    }
    const center = (c - S) / rate
    let final = false
    if (center <= frames && !this.loopCounted) {
      // Count the pass once; the crossing stays the head until its
      // fade-in has played out (so the notch completes across quanta).
      this.loopCounted = true
      this.loopPasses += 1
      final = loop.repeatCount !== null && this.loopPasses >= loop.repeatCount
      if (final) {
        // Stop exactly at the pass end (spec §13.4.6): the rest of this
        // quantum is silent and the cursor freezes at the boundary.
        this.loopComplete = true
        this.loopCompletion = { frame: c, time: time + center / this.sampleRate }
        this.position = c
      } else {
        this.loopAnchor = { frame: c, time: time + center / this.sampleRate }
      }
    }
    return { center, fade, final }
  }

  /**
   * Seek every source to the same fetch frame (the shared cursor) and
   * set the audible boundary. `frame` is the frame the transport will
   * feed first (it fetches the pre-roll from there); `audibleFrame`
   * defaults to `frame` and is the position the listener starts hearing
   * (the transport passes `frame = max(0, audible − preRoll)` for the
   * engine path, §12.3). `generations` is per-source on the shared path;
   * a single number (or undefined) applies to all. `loopSpec` installs
   * the practice loop atomically (M2.11): `undefined` keeps the current
   * one, `null` clears it; a loop left installed by an outside seek is
   * dropped (the transport disables looping on those, §13.4.5).
   */
  seek(frame, generations, audibleFrame, loopSpec) {
    if (loopSpec !== undefined) this.setLoop(loopSpec)
    const looping = this.loop !== null
    const target = looping
      ? Math.floor(frame)
      : Math.max(0, Math.min(Math.floor(frame), this.frameCount))
    const audible = looping
      ? Math.floor(audibleFrame ?? target)
      : Math.max(0, Math.min(Math.floor(audibleFrame ?? target), this.frameCount))
    if (looping && (audible < this.loop.start || audible >= this.loop.end)) {
      // A seek outside an active loop disables looping (§13.4.5).
      this.setLoop(null)
    }
    const active = this.loop !== null
    this.sources.forEach((s, i) => {
      const gen = Array.isArray(generations) ? generations[i] : generations
      s.setLooping(active)
      s.seek(target, gen)
    })
    this.position = audible
    this.ended = !active && audible >= this.frameCount
    this.endedNotified = false
    this.underrunNotified = false
    this.paused = false
    this.rampRemaining = 0
    this.pauseAnchorSent = false
    this.lastAnchorFrame = audible
    this.lastSample.fill(0)
    if (active) {
      this.loopNextCrossing = this.nextCrossingFrom(audible)
      this.loopCounted = false
    }
    if (this.engine) {
      // Hard re-position: drop the engine's synthesis state (the old
      // accumulator would bleed the previous position into the new one)
      // and re-roll from the fetch frame. The playback rate persists;
      // a wet start is warmed with an inaudible pre-roll below.
      this.engine.reset()
      this.audible = audible
      this.ringBase = target
      this.ringStart = target
      this.ringEnd = target
      this.rolledFrames = 0
      this.rateCurrent = this.rateTarget
      this.rateGoal = this.rateTarget
      this.rateFrom = this.rateTarget
      this.rateRampRemaining = 0
      this.bypass = this.rateTarget === 1 ? 'dry' : 'wet'
      this.xfade = null
      this.dryGain = this.bypass === 'dry' ? 1 : 0
      this.wetGain = 1 - this.dryGain
      this.warmupRemaining = this.rateTarget === 1 || this.ended ? 0 : WARMUP_OUT_FRAMES
    }
  }

  /**
   * Set the target playback rate (spec §11.7). The worklet ramps the
   * rate itself (≈50 ms, sampled once per quantum by the rolling seek);
   * the engine's own `setRate` ramp is unused by the playback path.
   *
   * Rate changes at 1× route through the aligned dry/wet crossfade
   * (§12.4): dry→wet crossfades at exactly 1× first, then ramps;
   * wet→dry ramps back to 1× first, then crossfades. A wet start needs
   * the engine's accumulator warm; when the rate is changed while the
   * playback is paused (or before it rolls), the pre-roll is run
   * inaudibly here (§12.3) — otherwise the dry→wet crossfade simply
   * waits for the (silently rolling) engine to warm, ≤ 120 ms.
   */
  setRate(rate) {
    const target = Math.min(2.0, Math.max(0.25, Number.isFinite(rate) ? rate : 1))
    this.rateTarget = target
    if (!this.engine || this.ended) return
    if (target !== 1 && this.rolledFrames < WARMUP_OUT_FRAMES) {
      if (this.paused || this.rolledFrames === 0) {
        // No audible output to interrupt: prime the engine inaudibly.
        this.warmupRemaining = Math.max(this.warmupRemaining, WARMUP_OUT_FRAMES - this.rolledFrames)
      }
    }
  }

  /** Begin the pause ramp on the mixed output; the cursor is preserved. */
  pause() {
    if (this.paused) return
    this.paused = true
    this.rampTotal = Math.max(1, Math.round(PAUSE_RAMP_SECONDS * this.sampleRate))
    this.rampRemaining = this.rampTotal
  }

  /** Resume at the preserved cursor. */
  resume() {
    this.paused = false
    this.rampRemaining = 0
    this.pauseAnchorSent = false
  }

  /**
   * Fill the per-sample per-source coefficient tables for `frames`
   * input frames. Each parameter ramps linearly toward its target;
   * within the block the ramp is a start value plus a per-sample slope,
   * so the sample loop contains only multiply-adds.
   */
  fillSourceCoeffs(frames) {
    for (let i = 0; i < this.sources.length; i++) {
      const p = this.params[i]
      const stereo = this.sources[i].channelCount > 1
      const coeffL = this.coeffL[i]
      const coeffR = this.coeffR[i]
      const remaining = Math.min(p.rampRemaining, frames)
      let gStart = p.gTo
      let bStart = p.bTo
      let eStart = p.eTo
      let gSlope = 0
      let bSlope = 0
      let eSlope = 0
      if (remaining > 0) {
        const inv = 1 / p.rampTotal
        gStart = p.gTo - (p.gTo - p.gFrom) * p.rampRemaining * inv
        bStart = p.bTo - (p.bTo - p.bFrom) * p.rampRemaining * inv
        eStart = p.eTo - (p.eTo - p.eFrom) * p.rampRemaining * inv
        gSlope = (p.gTo - p.gFrom) * inv
        bSlope = (p.bTo - p.bFrom) * inv
        eSlope = (p.eTo - p.eFrom) * inv
      }
      for (let k = 0; k < frames; k++) {
        const g = k < remaining ? gStart + gSlope * k : p.gTo
        const b = k < remaining ? bStart + bSlope * k : p.bTo
        const e = k < remaining ? eStart + eSlope * k : p.eTo
        const env = g * e
        if (stereo) {
          // 3 dB per side at the balance extremes (spec §10.3.5).
          coeffL[k] = env * Math.pow(10, (-3 * b) / 10)
          coeffR[k] = env * Math.pow(10, (3 * b) / 10)
        } else {
          // Equal-power pan (spec §10.3.6).
          const theta = ((b + 1) * Math.PI) / 4
          coeffL[k] = env * Math.cos(theta)
          coeffR[k] = env * Math.sin(theta)
        }
      }
      p.rampRemaining = Math.max(0, p.rampRemaining - frames)
    }
  }

  /**
   * Fill the master-gain coefficient table for `frames` output frames
   * (the master gain sits after the stretcher, §11.1, and ramps in
   * output/audition time).
   */
  fillMasterCoeffs(frames) {
    const mc = this.masterCoeff
    const remaining = Math.min(this.masterRampRemaining, frames)
    let mStart = this.masterTo
    let mSlope = 0
    if (remaining > 0) {
      const inv = 1 / this.masterRampTotal
      mStart = this.masterTo - (this.masterTo - this.masterFrom) * this.masterRampRemaining * inv
      mSlope = (this.masterTo - this.masterFrom) * inv
    }
    for (let k = 0; k < frames; k++) {
      mc[k] = k < remaining ? mStart + mSlope * k : this.masterTo
    }
    this.masterRampRemaining = Math.max(0, this.masterRampRemaining - frames)
  }

  /**
   * Mix one output quantum. The mixer always outputs 2 channels.
   * @param {number} time context time at which this block plays
   * @param {Float32Array[]} outputChannels one array per channel
   */
  process(time, outputChannels) {
    const startedAt = nowMs()
    const frames = outputChannels[0].length
    const out = {
      consumed: 0,
      underrun: false,
      ended: false,
      loopComplete: false,
      anchor: null,
      buffered: 0,
      peaks: null,
    }
    if (this.ended || this.loopComplete) {
      this.fillOutputSilence(outputChannels, 0, frames)
      if (this.loopComplete && !this.endedNotified) {
        // Finite repeat sequence finished (M2.11 §13.4.6): the transport
        // parks the playhead at the loop end.
        this.endedNotified = true
        out.loopComplete = true
        out.anchor = {
          frame: this.loopCompletion ? this.loopCompletion.frame : this.position,
          time: this.loopCompletion ? this.loopCompletion.time : time,
          paused: false,
          rate: this.rateCurrent ?? 1,
        }
      }
      out.buffered = this.buffered
      return this.finishProcess(out, startedAt)
    }
    if (this.engine && this.warmupRemaining > 0) {
      // Silent pre-roll for a wet start after a hard re-position (§12.3):
      // the engine's overlap-add accumulator fills inaudibly, so the
      // boundary starts at full level instead of fading in. Bounded per
      // callback; a starved source pauses the pre-roll (retried next
      // callback).
      this.runWarmup(frames)
      this.fillOutputSilence(outputChannels, 0, frames)
      out.buffered = this.buffered
      return this.finishProcess(out, startedAt)
    }
    if (this.paused) {
      if (this.rampRemaining > 0) {
        // Hold the last mixed samples, scaled down; cursor does not move.
        const level = this.rampRemaining / this.rampTotal
        for (let c = 0; c < 2; c++) {
          const s = this.lastSample[c] * level
          for (let i = 0; i < frames; i++) outputChannels[c][i] = s
        }
        this.rampRemaining -= frames
        if (this.rampRemaining <= 0 && !this.pauseAnchorSent) {
          // Final anchor at the exact paused position (spec §16.1).
          this.pauseAnchorSent = true
          out.anchor = { frame: this.position, time, paused: true }
        }
      } else {
        this.fillOutputSilence(outputChannels, 0, frames)
      }
      out.buffered = this.buffered
      return this.finishProcess(out, startedAt)
    }
    // The engine path mixes ring fills in bounded chunks (`engineFillChunk`),
    // so the scratch must hold the larger of the output block and the chunk.
    const cap = this.engine ? Math.max(frames, this.engineFillChunk) : frames
    this.ensureBlockCapacity(cap)
    if (this.engine) {
      return this.finishProcess(
        this.processWithEngine(time, outputChannels, frames, out),
        startedAt,
      )
    }
    // Shared cursor: every source advances by the same amount, so no
    // drift is possible. A starving source pauses the whole group.
    // Looping streams are unbounded (M2.11): the source length does not
    // cap the position.
    let take = frames
    for (const s of this.sources) take = Math.min(take, s.buffered)
    if (!this.loop) take = Math.min(take, this.frameCount - this.position)
    for (let i = 0; i < this.sources.length; i++) {
      this.sources[i].consumeInto(this.temp[i], take)
    }
    this.fillSourceCoeffs(frames)
    this.fillMasterCoeffs(frames)
    const notch = this.loopQuantum(time, 1, frames)
    const n = this.sources.length
    const ch0 = outputChannels[0]
    const ch1 = outputChannels.length > 1 ? outputChannels[1] : ch0
    for (let f = 0; f < take; f++) {
      let l = 0
      let r = 0
      for (let i = 0; i < n; i++) {
        const gL = this.coeffL[i][f]
        const gR = this.coeffR[i][f]
        let cl
        let cr
        if (this.sources[i].channelCount === 1) {
          const smp = this.temp[i][0][f]
          cl = smp * gL
          cr = smp * gR
        } else {
          cl = this.temp[i][0][f] * gL
          cr = this.temp[i][1][f] * gR
        }
        l += cl
        r += cr
        const a = Math.abs(cl)
        const b = Math.abs(cr)
        if (a > this.trackPeaks[i]) this.trackPeaks[i] = a
        if (b > this.trackPeaks[i]) this.trackPeaks[i] = b
      }
      if (notch) {
        // Join fade (spec §13.6) and the finite-repeat stop (§13.4.6).
        const g = notch.fade > 0 ? Math.min(1, Math.abs(notch.center - f) / notch.fade) : 1
        l *= g
        r *= g
        if (notch.final && f >= notch.center) {
          l = 0
          r = 0
        }
      }
      const mg = this.masterCoeff[f]
      l *= mg
      r *= mg
      ch0[f] = l
      ch1[f] = r
      const a = Math.abs(l)
      const b = Math.abs(r)
      if (a > this.masterPeak) this.masterPeak = a
      if (b > this.masterPeak) this.masterPeak = b
    }
    if (take < frames) {
      this.fillOutputSilence(outputChannels, take, frames - take)
      this.maybeUnderrun(out)
    }
    if (this.loopComplete) {
      // Frozen exactly at the pass end (spec §13.4.6).
      this.position = this.loopCompletion ? this.loopCompletion.frame : this.position
    } else {
      this.position += take
    }
    for (let c = 0; c < 2; c++) {
      this.lastSample[c] = take > 0 && c < outputChannels.length ? outputChannels[c][take - 1] : 0
    }
    this.advance(time, out, time + take / this.sampleRate)
    out.consumed = take
    out.buffered = this.buffered
    out.peaks = { tracks: this.trackPeaks.slice(), master: this.masterPeak }
    for (let i = 0; i < this.trackPeaks.length; i++) this.trackPeaks[i] = 0
    this.masterPeak = 0
    return this.finishProcess(out, startedAt)
  }

  /** Bookkeep the render-callback duration (M2.12 §14.4) and return. */
  finishProcess(out, startedAt) {
    this.lastProcessMs = nowMs() - startedAt
    return out
  }

  /**
   * End-of-source / anchor bookkeeping shared by both data paths.
   * `position` must already include this quantum's advance; `endTime`
   * is the context time at which the current position plays (the
   * quantum's end for a full render quantum). Anchors carry the exact
   * (frame, time) pair of the audible cursor, so the transport's ledger
   * maps to the audio actually being heard (spec §12.7) instead of a
   * lagging estimate.
   */
  advance(time, out, endTime) {
    const rate = this.rateCurrent ?? 1
    if (this.loop) {
      if (this.loopComplete) {
        if (!this.endedNotified) {
          // Finite repeat sequence finished (spec §13.4.6): park the
          // playhead exactly at the loop end.
          this.endedNotified = true
          out.loopComplete = true
          out.anchor = {
            frame: this.loopCompletion ? this.loopCompletion.frame : this.position,
            time: this.loopCompletion ? this.loopCompletion.time : endTime,
            paused: false,
            rate,
          }
        }
        return
      }
      if (this.loopAnchor) {
        // Wrap anchor: the exact (frame, time) of the pass crossing
        // (spec §13.7.5). Stream coordinates stay monotonic, so the
        // transport's ledger extrapolation never crosses a wrap. The
        // `wrap` marker distinguishes it from the cadence anchors.
        out.anchor = {
          frame: this.loopAnchor.frame,
          time: this.loopAnchor.time,
          paused: false,
          rate,
          wrap: true,
        }
        this.loopAnchor = null
        return
      }
      if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
        out.anchor = { frame: this.position, time: endTime, paused: false, rate }
        this.lastAnchorFrame = this.position
      }
      return
    }
    if (this.position >= this.frameCount) {
      this.ended = true
      if (!this.endedNotified) {
        this.endedNotified = true
        out.ended = true
        out.anchor = { frame: this.position, time: endTime, paused: false, rate }
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      out.anchor = { frame: this.position, time: endTime, paused: false, rate }
      this.lastAnchorFrame = this.position
    }
  }

  /**
   * Report an underrun once per starvation episode. Silence with
   * nothing buffered (prebuffer after a seek) is not one.
   */
  maybeUnderrun(out) {
    // Starvation is only an underrun when data was expected somewhere:
    // an empty source AND an empty mix ring is a seek/prebuffer state.
    const hadData = this.sources.some((s) => s.buffered > 0) || this.ringEnd > this.ringStart
    if (!this.underrunNotified && hadData) {
      out.underrun = true
      this.underrunNotified = true
    }
  }

  /**
   * Engine data path (M2.10, spec §12.3): per-stem gain/pan/mute/solo →
   * stereo sum → mix ring → rolling seek → master gain → output
   * (§11.1 order). Two taps read the ring:
   *
   * - **dry**: the exact 1× bypass — frames read straight at the audible
   *   cursor (bit-identical to the no-engine path, §12.4);
   * - **wet**: the rolling seek — every render quantum the context window
   *   `[S + r*outLat + inLat − windowLength, S + r*outLat + inLat)` goes
   *   into the engine, `seek(windowLength, r)` + `process(0, frames)`
   *   emit the block centred exactly on the cursor `S`.
   *
   * The output is `dryGain*dry + wetGain*wet`; the gains only crossfade
   * while both taps are at exactly 1× (never mixing differently timed
   * dry and stretched audio, §12.4.5). The engine keeps rolling
   * inaudibly during bypass, so transitions are always prepared. A short
   * supply takes the M2.8 underrun path (silence, no advance, no engine
   * call).
   */
  processWithEngine(time, outputChannels, frames, out) {
    const eng = this.engine
    this.updateRateState(frames)
    const rate = this.rateCurrent
    const dryStart = Math.round(this.audible)
    const dryActive = this.dryGain > 0 || this.dryGainPrev > 0
    // Context window centred on the audible cursor (measured law, §12.3).
    const windowEnd = Math.round(this.audible + rate * this.outLat + this.inLat)
    const windowStart = windowEnd - this.windowFrames
    // Ring coverage: the whole window plus the dry read, capped at EOF
    // (unbounded for a loop stream, M2.11).
    const windowTo = this.loop ? windowEnd : Math.min(windowEnd, this.frameCount)
    const dryTo = this.loop ? dryStart + frames : Math.min(dryStart + frames, this.frameCount)
    let needTo = windowTo
    if (dryActive) needTo = Math.max(needTo, dryTo)
    if (needTo > this.ringEnd) this.fillRing(needTo)
    if (this.ringEnd < windowTo || (dryActive && this.ringEnd < dryTo)) {
      // Starved: silence, no cursor advance, no engine call.
      this.fillOutputSilence(outputChannels, 0, frames)
      this.maybeUnderrun(out)
      out.buffered = this.buffered
      return out
    }
    const ch0 = outputChannels[0]
    const ch1 = outputChannels.length > 1 ? outputChannels[1] : ch0
    // Dry tap: exact 1× frames straight from the ring.
    if (dryActive) {
      if (dryTo > dryStart) {
        this.copyFromRing(this.ringL, ch0, 0, dryStart, dryTo - dryStart)
        this.copyFromRing(this.ringR, ch1, 0, dryStart, dryTo - dryStart)
      }
      if (dryTo - dryStart < frames) {
        this.fillOutputSilence(outputChannels, dryTo - dryStart, frames - (dryTo - dryStart))
      }
    } else {
      ch0.fill(0, 0, frames)
      if (ch1 !== ch0) ch1.fill(0, 0, frames)
    }
    // Wet tap: rolling seek (§12.3).
    this.fillEngineWindow(windowStart, windowEnd)
    eng.seek(this.windowFrames, rate)
    eng.process(0, frames)
    // Loop bookkeeping (M2.11): the join notch + pass counting for the
    // stream range this quantum renders.
    const notch = this.loopQuantum(time, rate, frames)
    // Mix the taps; the master gain stays after the stretcher (§11.1/§12.5).
    this.fillMasterCoeffs(frames)
    const d0 = this.dryGainPrev
    const w0 = this.wetGainPrev
    const ds = (this.dryGain - d0) / frames
    const ws = (this.wetGain - w0) / frames
    for (let i = 0; i < frames; i++) {
      const dg = d0 + ds * i
      const wg = w0 + ws * i
      let l = ch0[i] * dg + eng.outL[i] * wg
      let r = ch1[i] * dg + eng.outR[i] * wg
      if (notch) {
        // Join fade (spec §13.6) and the finite-repeat stop (§13.4.6).
        const g = notch.fade > 0 ? Math.min(1, Math.abs(notch.center - i) / notch.fade) : 1
        l *= g
        r *= g
        if (notch.final && i >= notch.center) {
          l = 0
          r = 0
        }
      }
      const mg = this.masterCoeff[i]
      l *= mg
      r *= mg
      ch0[i] = l
      ch1[i] = r
      const a = Math.abs(l)
      const b = Math.abs(r)
      if (a > this.masterPeak) this.masterPeak = a
      if (b > this.masterPeak) this.masterPeak = b
    }
    if (this.loopComplete) {
      // Frozen exactly at the pass end (spec §13.4.6): the cursor stops
      // at the boundary and the remaining output is silent.
      this.audible = this.loopCompletion ? this.loopCompletion.frame : this.position
      this.position = this.audible
    } else {
      this.audible += rate * frames
      // The audible cursor can overshoot the end; the reported position
      // is clamped (the ended anchor names the endpoint, §12.6). A loop
      // stream is unbounded, so no clamp applies.
      this.position = this.loop
        ? Math.round(this.audible)
        : Math.min(Math.round(this.audible), this.frameCount)
    }
    this.rolledFrames += frames
    for (let c = 0; c < 2; c++) {
      this.lastSample[c] = c < outputChannels.length ? outputChannels[c][frames - 1] : 0
    }
    this.advance(time, out, time + frames / this.sampleRate)
    out.consumed = frames
    out.buffered = this.buffered
    out.peaks = { tracks: this.trackPeaks.slice(), master: this.masterPeak }
    for (let i = 0; i < this.trackPeaks.length; i++) this.trackPeaks[i] = 0
    this.masterPeak = 0
    return out
  }

  /**
   * Advance the playback-rate ramp and the dry/wet crossfade for one
   * render quantum (§11.7, §12.4). Ordering: a dry→wet crossfade runs
   * at exactly 1× and only starts once the engine is warm; a wet→dry
   * transition ramps back to 1× first, then crossfades. The gains move
   * sample-accurately across the quantum (`dryGainPrev` → `dryGain`).
   */
  updateRateState(frames) {
    const wantWet = this.rateTarget !== 1
    if (!this.xfade) {
      if (wantWet && this.bypass === 'dry' && this.rolledFrames >= WARMUP_OUT_FRAMES) {
        this.xfade = {
          to: 'wet',
          fromDry: this.dryGain,
          fromWet: this.wetGain,
          remaining: this.xfadeTotal,
        }
      } else if (!wantWet && this.bypass === 'wet' && this.rateCurrent === 1) {
        this.xfade = {
          to: 'dry',
          fromDry: this.dryGain,
          fromWet: this.wetGain,
          remaining: this.xfadeTotal,
        }
      }
    }
    let goal = this.rateTarget
    if (this.bypass === 'dry') goal = 1
    if (this.xfade && this.xfade.to === 'wet') goal = this.rateCurrent
    if (this.xfade && this.xfade.to === 'dry') goal = 1
    if (goal !== this.rateGoal) {
      this.rateGoal = goal
      this.rateFrom = this.rateCurrent
      this.rateRampRemaining = this.rateCurrent === goal ? 0 : this.rateRampTotal
    }
    if (this.rateRampRemaining > 0) {
      this.rateRampRemaining = Math.max(0, this.rateRampRemaining - frames)
      this.rateCurrent =
        this.rateRampRemaining === 0
          ? this.rateGoal
          : this.rateFrom +
            (this.rateGoal - this.rateFrom) * (1 - this.rateRampRemaining / this.rateRampTotal)
    }
    this.dryGainPrev = this.dryGain
    this.wetGainPrev = this.wetGain
    if (this.xfade) {
      this.xfade.remaining = Math.max(0, this.xfade.remaining - frames)
      const t = 1 - this.xfade.remaining / this.xfadeTotal
      if (this.xfade.to === 'wet') {
        this.dryGain = this.xfade.fromDry * (1 - t)
        this.wetGain = this.xfade.fromWet + (1 - this.xfade.fromWet) * t
      } else {
        this.dryGain = this.xfade.fromDry + (1 - this.xfade.fromDry) * t
        this.wetGain = this.xfade.fromWet * (1 - t)
      }
      if (this.xfade.remaining === 0) {
        this.bypass = this.xfade.to
        this.dryGain = this.bypass === 'dry' ? 1 : 0
        this.wetGain = 1 - this.dryGain
        this.xfade = null
      }
    }
  }

  /**
   * Run one callback's worth of the silent pre-roll (§12.3): rolling
   * seeks advance the engine from `audible − remaining*rate` up to the
   * boundary; the output is discarded (the caller emits silence). The
   * batch is bounded so a hard seek never spikes one render callback; a
   * starved source pauses the pre-roll (retried next callback).
   */
  runWarmup(frames) {
    const eng = this.engine
    const batch = frames * 8
    let done = 0
    while (this.warmupRemaining > 0 && done < batch) {
      const n = Math.min(frames, this.warmupRemaining)
      const rate = this.rateTarget
      const cursor = this.audible - this.warmupRemaining * rate
      const windowEnd = Math.round(cursor + rate * this.outLat + this.inLat)
      const windowStart = windowEnd - this.windowFrames
      const needTo = this.loop ? windowEnd : Math.min(windowEnd, this.frameCount)
      if (needTo > this.ringEnd) this.fillRing(needTo)
      if (this.ringEnd < needTo) break // starved: retry next callback
      this.fillEngineWindow(windowStart, windowEnd)
      eng.seek(this.windowFrames, rate)
      eng.process(0, n)
      this.rolledFrames += n
      this.warmupRemaining -= n
      done += n
    }
  }

  /**
   * Stem-mix source frames into the ring until it reaches `until`.
   * Bounded chunks keep the scratch allocation-free; a starved source
   * stops the fill (the caller detects the shortfall). The ring is a
   * circular buffer over absolute frames: `ringBase` anchors slot 0,
   * `[ringStart, ringEnd)` is valid, and slots older than the capacity
   * are dropped.
   */
  fillRing(until) {
    const cap = this.ringCap
    while (this.ringEnd < until) {
      if (until - this.ringStart > cap) this.ringStart = until - cap
      let chunk = Math.min(
        until - this.ringEnd,
        this.engineFillChunk,
        cap - (this.ringEnd - this.ringStart),
      )
      chunk = this.loop
        ? chunk // a loop stream is unbounded (M2.11)
        : Math.min(chunk, this.frameCount - this.ringEnd)
      if (chunk <= 0) break
      let take = chunk
      for (const s of this.sources) take = Math.min(take, s.buffered)
      if (take <= 0) break
      for (let i = 0; i < this.sources.length; i++) {
        this.sources[i].consumeInto(this.temp[i], take)
      }
      this.fillSourceCoeffs(take)
      const n = this.sources.length
      const mixL = this.mixL
      const mixR = this.mixR
      for (let f = 0; f < take; f++) {
        let l = 0
        let r = 0
        for (let i = 0; i < n; i++) {
          const gL = this.coeffL[i][f]
          const gR = this.coeffR[i][f]
          let cl
          let cr
          if (this.sources[i].channelCount === 1) {
            const smp = this.temp[i][0][f]
            cl = smp * gL
            cr = smp * gR
          } else {
            cl = this.temp[i][0][f] * gL
            cr = this.temp[i][1][f] * gR
          }
          l += cl
          r += cr
          const a = Math.abs(cl)
          const b = Math.abs(cr)
          if (a > this.trackPeaks[i]) this.trackPeaks[i] = a
          if (b > this.trackPeaks[i]) this.trackPeaks[i] = b
        }
        mixL[f] = l
        mixR[f] = r
      }
      const off = (this.ringEnd - this.ringBase) % cap
      const first = Math.min(take, cap - off)
      this.ringL.set(mixL.subarray(0, first), off)
      this.ringR.set(mixR.subarray(0, first), off)
      if (take > first) {
        this.ringL.set(mixL.subarray(first, take), 0)
        this.ringR.set(mixR.subarray(first, take), 0)
      }
      this.ringEnd += take
    }
  }

  /**
   * Copy `count` frames starting at absolute frame `from` from a ring
   * channel into `dst[dstOff..]`. The caller guarantees the range is
   * valid (inside `[ringStart, ringEnd)`); the ring wraps at most once.
   */
  copyFromRing(src, dst, dstOff, from, count) {
    const cap = this.ringCap
    const off = (from - this.ringBase) % cap
    const first = Math.min(count, cap - off)
    dst.set(src.subarray(off, off + first), dstOff)
    if (count > first) dst.set(src.subarray(0, count - first), dstOff + first)
  }

  /**
   * Fill the engine's context window: real frames from the ring where
   * available (`[max(windowStart, 0), min(windowEnd, frameCount))`),
   * zeros elsewhere (source boundaries and the retained-ring edge). A
   * loop stream (M2.11) has no source-length bound and may start below
   * 0 (the periodic pre-roll), so the ring alone bounds it.
   */
  fillEngineWindow(windowStart, windowEnd) {
    const eng = this.engine
    const W = this.windowFrames
    eng.inL.fill(0, 0, W)
    eng.inR.fill(0, 0, W)
    const from = this.loop
      ? Math.max(windowStart, this.ringStart)
      : Math.max(windowStart, 0, this.ringStart)
    const to = this.loop
      ? Math.min(windowEnd, this.ringEnd)
      : Math.min(windowEnd, this.frameCount, this.ringEnd)
    if (to > from) {
      const off = from - windowStart
      const count = to - from
      this.copyFromRing(this.ringL, eng.inL, off, from, count)
      this.copyFromRing(this.ringR, eng.inR, off, from, count)
    }
  }

  fillOutputSilence(outputChannels, from, count) {
    outputChannels[0].fill(0, from, from + count)
    if (outputChannels.length > 1) outputChannels[1].fill(0, from, from + count)
  }
}

// The adapter only exists in the worklet scope, where
// `AudioWorkletProcessor` is a global; main-thread imports (tests) skip it.
if (typeof AudioWorkletProcessor !== 'undefined') {
  /** Thin adapter wiring the state machine to the worklet port. */
  class PcmProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super()
      const o = (options && options.processorOptions) || {}
      const sampleRate = o.sampleRate ?? 48000
      let sources
      let sabs
      if (Array.isArray(o.sources) && o.sources.length > 0) {
        sources = o.sources
        sabs = Array.isArray(o.sabs) ? o.sabs : []
      } else {
        // 1-source init shape (M1 fixtures): wrap in the mixer path.
        sources = [{ channelCount: o.channelCount ?? 2 }]
        sabs = Array.isArray(o.sabs) ? o.sabs : o.sab ? [o.sab] : []
      }
      // M2.9 (spec §11): every playback goes through the stretcher. The
      // engine is instantiated synchronously from the transferred
      // artifact bytes (no fetch in the worklet, spec §11.3.11).
      let engine = null
      if (o.stretch && o.stretch.wasmBytes) {
        const api = globalThis.StretchWasm
        if (!api) throw new Error('stretch: core missing from the worklet bundle')
        engine = api.instantiateStretch(o.stretch.wasmBytes)
        engine.configure(sampleRate, o.stretch.maxFrames ?? api.STRETCH_MAX_FRAMES)
      }
      this.core = new MixState({
        sampleRate,
        frameCount: o.frameCount ?? 0,
        sources,
        engine,
        // M2.12 §14.1: the transport owns ring sizing (byte/duration caps,
        // group minimum); shared rings derive it from the SAB instead.
        capacityFrames: o.capacityFrames ?? 0,
      })
      sabs.forEach((sab, i) => this.core.attachShared(i, sab))
      this.generation = 0
      if (engine) {
        // The transport maps playback position with the engine latencies.
        const lat = engine.latencies()
        this.port.postMessage({
          type: 'stretch-ready',
          inputLatency: lat.inputFrames,
          outputLatency: lat.outputFrames,
        })
      }
      this.port.onmessage = (e) => {
        const m = e.data
        if (!m || typeof m !== 'object') return
        if (m.type === 'channels') {
          const index = typeof m.source === 'number' ? m.source : 0
          const ok = this.core.enqueueChannels(index, m.channels)
          if (ok) {
            this.reportBuffered()
            if (this.core.buffered >= this.core.capacity) {
              this.port.postMessage({ type: 'queue-high', generation: this.generation })
            }
          } else {
            this.port.postMessage({
              type: 'chunk-dropped',
              frames: m.frames,
              source: index,
              generation: this.generation,
            })
          }
        } else if (m.type === 'seek') {
          if (Array.isArray(m.generations)) {
            this.generation = m.generations.reduce((a, b) => Math.max(a, b), 0)
            this.core.seek(m.frame, m.generations, m.audibleFrame, m.loop)
          } else {
            this.generation = m.generation
            this.core.seek(m.frame, this.generation, m.audibleFrame, m.loop)
          }
          this.port.postMessage({ type: 'flushed', generation: this.generation })
        } else if (m.type === 'params') {
          this.core.setSourceParams(m.source, m)
        } else if (m.type === 'master') {
          this.core.setMasterGain(m.gain)
        } else if (m.type === 'rate') {
          // The wrapper owns the ≈50 ms rate ramp (spec §11.7).
          this.core.setRate(m.value)
        } else if (m.type === 'loop') {
          // Install/clear the practice loop mid-stream (M2.11 §13.4.3):
          // enabling inside the loop continues without a re-seek.
          this.core.setLoop(m.loop)
        } else if (m.type === 'pause') {
          this.core.pause()
        } else if (m.type === 'resume') {
          this.core.resume()
        }
        // 'dispose' needs no worklet-side action.
      }
    }

    reportBuffered() {
      const msg = {
        type: 'buffered',
        frames: this.core.buffered,
        queuedFrames: this.core.queued,
        // M2.12 §14.2.1: per-stem buffered frames (group readiness).
        stems: this.core.sources.map((s) => s.buffered),
        // M2.12 §14.1: the group ring capacity in frames.
        capacityFrames: this.core.capacity,
        generation: this.generation,
      }
      // M2.12 §14.4: render-callback duration and stretcher configuration.
      if (typeof this.core.lastProcessMs === 'number') {
        msg.callbackMs = this.core.lastProcessMs
      }
      if (this.core.engine) {
        msg.stretcher = {
          rate: this.core.rateCurrent,
          bypass: this.core.bypass === 'dry',
          warmup: this.core.warmupRemaining,
        }
      }
      this.port.postMessage(msg)
    }

    /**
     * Web Audio callback. The AudioWorkletGlobalScope calls
     * `process(inputs, outputs, parameters)` and exposes the block time
     * as the global `currentTime` (§14.7). The transport has no audio
     * inputs; the core consumes one output's channel array.
     */
    process(_inputs, outputs) {
      const time = typeof globalThis.currentTime === 'number' ? globalThis.currentTime : 0
      const res = this.core.process(time, outputs[0] ?? [])
      if (res.anchor) {
        const msg = {
          type: 'anchor',
          frame: res.anchor.frame,
          time: res.anchor.time,
          paused: res.anchor.paused,
          rate: res.anchor.rate ?? 1,
          generation: this.generation,
        }
        // Pass-crossing anchors carry the wrap marker (M2.11 §13.7.5).
        if (res.anchor.wrap === true) msg.wrap = true
        // Peak metering rides the ~20 Hz anchor cadence (mixer path only).
        if (res.peaks) msg.peaks = res.peaks
        this.port.postMessage(msg)
        this.reportBuffered()
      }
      if (res.underrun) {
        this.port.postMessage({ type: 'underrun', generation: this.generation })
      }
      if (res.ended) {
        this.port.postMessage({ type: 'ended', generation: this.generation })
      }
      if (res.loopComplete) {
        // Finite repeat sequence finished (M2.11 §13.4.6); the anchor
        // carries the exact pass-end (frame, time).
        const a = res.anchor
        this.port.postMessage({
          type: 'loop-complete',
          frame: a ? a.frame : this.core.position,
          time: a ? a.time : 0,
          generation: this.generation,
        })
      }
      return true
    }
  }

  registerProcessor('basseparate-pcm', PcmProcessor)
}
