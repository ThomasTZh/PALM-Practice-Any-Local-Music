/**
 * AudioWorklet processor for PCM playback (M1.12/M1.13, spec §14–15).
 *
 * Self-contained on purpose: the browser loads this exact file as a
 * Blob-URL worklet module (see `transport.ts`), where imports are not
 * available, while the unit tests import it directly as an ES module
 * (the `registerProcessor` call is guarded by a global check, so the
 * module is safe to load on the main thread).
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
 * The 12 s ring capacity is the §15.3 total-retention cap (8 s steady
 * lookahead + 2 s retained history, with headroom). `process` uses the
 * actual output-block length — never an assumed size (spec §14 intro).
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
 * Ring capacity in seconds — the §15.3 total-retention cap per active
 * playback representation (≫ the 2 s prebuffer and 8 s lookahead).
 */
const RING_SECONDS = 12

export class ConsumptionState {
  /**
   * @param {object} opts
   * @param {number} opts.sampleRate
   * @param {number} opts.channelCount
   * @param {number} opts.frameCount total frames of the source
   * @param {number} [opts.anchorEveryFrames]
   */
  constructor({ sampleRate, channelCount, frameCount, anchorEveryFrames }) {
    if (!(sampleRate > 0)) throw new RangeError('sampleRate must be > 0')
    if (!(channelCount >= 1)) throw new RangeError('channelCount must be >= 1')
    if (!(frameCount >= 0)) throw new RangeError('frameCount must be >= 0')
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    this.frameCount = frameCount
    this.anchorEvery = anchorEveryFrames ?? defaultAnchorEvery(sampleRate)
    this.capacity = Math.ceil(sampleRate * RING_SECONDS)
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
    /** Next frame to consume (playback frames). */
    this.position = 0
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
    // excludes everything already buffered (ring + queue).
    frames = Math.min(frames, this.frameCount - this.position - this.available - this.queuedFrames)
    if (frames <= 0) return false
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
    this.localGen = Atomics.load(header, 0)
  }

  /**
   * Drop all buffered data and move to `frame`. This is the stale-audio
   * barrier: nothing enqueued before the seek can be output after it.
   * On the shared path the processor stores its own (reader) index and
   * adopts the new generation; the writer index is reset only when the
   * worker receives the flush acknowledgment (spec §15.1.6).
   */
  seek(frame, generation) {
    const target = Math.max(0, Math.min(Math.floor(frame), this.frameCount))
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
    this.ended = target >= this.frameCount
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
    if (this.position >= this.frameCount) {
      this.ended = true
      if (!this.endedNotified) {
        this.endedNotified = true
        out.ended = true
        out.anchor = { frame: this.position, time, paused: false }
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      out.anchor = { frame: this.lastAnchorFrame, time, paused: false }
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
    const take = Math.min(frames, avail, this.frameCount - this.position)
    if (take <= 0) return 0
    for (let i = 0; i < take; i++) {
      const src = ((reader + i) % capacity) * this.channelCount
      for (let c = 0; c < this.channelCount; c++) {
        outputChannels[c][i] = data[src + c]
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
      const take = Math.min(frames, avail, this.frameCount - this.position)
      if (take <= 0) return 0
      for (let i = 0; i < take; i++) {
        const src = ((reader + i) % capacity) * this.channelCount
        for (let c = 0; c < this.channelCount; c++) outChannels[c][i] = data[src + c]
      }
      Atomics.store(header, 2, reader + take)
      this.position += take
      this.flushing = false
      return take
    }
    this.drainQueue()
    const take = Math.min(frames, this.available, this.frameCount - this.position)
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
 */
export class MixState {
  /**
   * @param {object} opts
   * @param {number} opts.sampleRate
   * @param {number} opts.frameCount project duration — all sources equal
   * @param {Array<{channelCount: number}>} opts.sources
   */
  constructor({ sampleRate, frameCount, sources }) {
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
    /** Last mixed output sample per channel (held during the pause ramp). */
    this.lastSample = new Float32Array(2)
    /** Per-quantum peaks, reset after each report. */
    this.trackPeaks = sources.map(() => 0)
    this.masterPeak = 0
    // Bounded per-quantum scratch, grown only if a larger block ever
    // arrives (audio thread: no steady-state allocation).
    this.blockCap = 0
    this.coeffL = []
    this.coeffR = []
    this.temp = []
    this.masterCoeff = null
    this.ensureBlockCapacity(128)
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
   * Seek every source to the same frame (the shared cursor).
   * `generations` is per-source on the shared path; a single number (or
   * undefined) applies to all.
   */
  seek(frame, generations) {
    const target = Math.max(0, Math.min(Math.floor(frame), this.frameCount))
    this.sources.forEach((s, i) => {
      const gen = Array.isArray(generations) ? generations[i] : generations
      s.seek(target, gen)
    })
    this.position = target
    this.ended = target >= this.frameCount
    this.endedNotified = false
    this.underrunNotified = false
    this.paused = false
    this.rampRemaining = 0
    this.pauseAnchorSent = false
    this.lastAnchorFrame = target
    this.lastSample.fill(0)
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
   * Fill the per-sample coefficient tables for this quantum. Each
   * parameter ramps linearly toward its target; within the quantum the
   * ramp is a start value plus a per-sample slope, so the sample loop
   * contains only multiply-adds.
   */
  fillCoeffs(frames) {
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
    const frames = outputChannels[0].length
    const out = {
      consumed: 0,
      underrun: false,
      ended: false,
      anchor: null,
      buffered: 0,
      peaks: null,
    }
    if (this.ended) {
      this.fillOutputSilence(outputChannels, 0, frames)
      out.buffered = this.buffered
      return out
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
      return out
    }
    this.ensureBlockCapacity(frames)
    // Shared cursor: every source advances by the same amount, so no
    // drift is possible. A starving source pauses the whole group.
    let take = frames
    for (const s of this.sources) take = Math.min(take, s.buffered)
    take = Math.min(take, this.frameCount - this.position)
    for (let i = 0; i < this.sources.length; i++) {
      this.sources[i].consumeInto(this.temp[i], take)
    }
    this.fillCoeffs(frames)
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
      // An underrun is only reported when data was available — some
      // source has frames but the group cannot advance (the weakest
      // source is starved). Silence with nothing buffered (prebuffer
      // after a seek) is not one.
      if (!this.underrunNotified && this.sources.some((s) => s.buffered > 0)) {
        out.underrun = true
        this.underrunNotified = true
      }
    }
    this.position += take
    for (let c = 0; c < 2; c++) {
      this.lastSample[c] = take > 0 && c < outputChannels.length ? outputChannels[c][take - 1] : 0
    }
    if (this.position >= this.frameCount) {
      this.ended = true
      if (!this.endedNotified) {
        this.endedNotified = true
        out.ended = true
        out.anchor = { frame: this.position, time, paused: false }
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      out.anchor = { frame: this.lastAnchorFrame, time, paused: false }
      this.lastAnchorFrame = this.position
    }
    out.consumed = take
    out.buffered = this.buffered
    out.peaks = { tracks: this.trackPeaks.slice(), master: this.masterPeak }
    for (let i = 0; i < this.trackPeaks.length; i++) this.trackPeaks[i] = 0
    this.masterPeak = 0
    return out
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
      if (Array.isArray(o.sources) && o.sources.length > 0) {
        // Mixer path (M2.8): one processor consumes all active sources.
        this.core = new MixState({
          sampleRate: o.sampleRate ?? 48000,
          frameCount: o.frameCount ?? 0,
          sources: o.sources,
        })
        if (Array.isArray(o.sabs)) {
          o.sabs.forEach((sab, i) => this.core.attachShared(i, sab))
        }
      } else {
        this.core = new ConsumptionState({
          sampleRate: o.sampleRate ?? 48000,
          channelCount: o.channelCount ?? 2,
          frameCount: o.frameCount ?? 0,
        })
        if (o.sab) this.core.attachShared(o.sab)
      }
      this.generation = 0
      this.port.onmessage = (e) => {
        const m = e.data
        if (!m || typeof m !== 'object') return
        if (m.type === 'channels') {
          const index = typeof m.source === 'number' ? m.source : 0
          // The mixer core is per-source; the legacy core is single-source.
          const ok =
            this.core instanceof MixState
              ? this.core.enqueueChannels(index, m.channels)
              : this.core.enqueueChannels(m.channels)
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
        } else if (m.type === 'samples') {
          // Kept for compatibility with the M1.12 protocol (legacy core).
          if (this.core instanceof ConsumptionState && this.core.enqueue(m.buffer)) {
            this.reportBuffered()
          }
        } else if (m.type === 'seek') {
          if (Array.isArray(m.generations)) {
            this.generation = m.generations.reduce((a, b) => Math.max(a, b), 0)
            this.core.seek(m.frame, m.generations)
          } else {
            this.generation = m.generation
            this.core.seek(m.frame, this.generation)
          }
          this.port.postMessage({ type: 'flushed', generation: this.generation })
        } else if (m.type === 'params') {
          // Mixer path only; the legacy core has no mixer parameters.
          if (this.core instanceof MixState) this.core.setSourceParams(m.source, m)
        } else if (m.type === 'master') {
          if (this.core instanceof MixState) this.core.setMasterGain(m.gain)
        } else if (m.type === 'pause') {
          this.core.pause()
        } else if (m.type === 'resume') {
          this.core.resume()
        }
        // 'dispose' needs no worklet-side action.
      }
    }

    reportBuffered() {
      this.port.postMessage({
        type: 'buffered',
        frames: this.core.buffered,
        queuedFrames: this.core.queued,
        generation: this.generation,
      })
    }

    process(time, input, output) {
      const res = this.core.process(time, output)
      if (res.anchor) {
        const msg = {
          type: 'anchor',
          frame: res.anchor.frame,
          time: res.anchor.time,
          paused: res.anchor.paused,
          generation: this.generation,
        }
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
      return true
    }
  }

  registerProcessor('basseparate-pcm', PcmProcessor)
}
