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
}

// The adapter only exists in the worklet scope, where
// `AudioWorkletProcessor` is a global; main-thread imports (tests) skip it.
if (typeof AudioWorkletProcessor !== 'undefined') {
  /** Thin adapter wiring the state machine to the worklet port. */
  class PcmProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super()
      const o = (options && options.processorOptions) || {}
      this.core = new ConsumptionState({
        sampleRate: o.sampleRate ?? 48000,
        channelCount: o.channelCount ?? 2,
        frameCount: o.frameCount ?? 0,
      })
      this.generation = 0
      if (o.sab) this.core.attachShared(o.sab)
      this.port.onmessage = (e) => {
        const m = e.data
        if (!m || typeof m !== 'object') return
        if (m.type === 'channels') {
          if (this.core.enqueueChannels(m.channels)) {
            this.reportBuffered()
            if (this.core.buffered >= this.core.capacity) {
              this.port.postMessage({ type: 'queue-high', generation: this.generation })
            }
          } else {
            this.port.postMessage({
              type: 'chunk-dropped',
              frames: m.frames,
              generation: this.generation,
            })
          }
        } else if (m.type === 'samples') {
          // Kept for compatibility with the M1.12 protocol.
          if (this.core.enqueue(m.buffer)) {
            this.reportBuffered()
          }
        } else if (m.type === 'seek') {
          this.generation = m.generation
          this.core.seek(m.frame, this.generation)
          this.port.postMessage({ type: 'flushed', generation: this.generation })
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
        this.port.postMessage({
          type: 'anchor',
          frame: res.anchor.frame,
          time: res.anchor.time,
          paused: res.anchor.paused,
          generation: this.generation,
        })
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
