/**
 * AudioWorklet processor for PCM playback (M1.12, spec §14).
 *
 * Self-contained on purpose: the browser loads this exact file as a
 * Blob-URL worklet module (see `transport.ts`), where imports are not
 * available, while the unit tests import it directly as an ES module
 * (the `registerProcessor` call is guarded by a global check, so the
 * module is safe to load on the main thread).
 *
 * `ConsumptionState` is the pure audio-thread state machine: a bounded
 * per-channel ring that fills the output blocks deterministically, emits
 * silence when data is unavailable, ramps to silence over ~5 ms on
 * pause, and reports position anchors. `process` uses the actual
 * output-block length — never an assumed size (spec §14 intro).
 *
 * Audio-thread constraints (spec §14.7): no network, no filesystem, no
 * promises, no logging, no unbounded allocations, no waits. All
 * preparation (deinterleaving) happens in the message handler, not in
 * `process`.
 */

/* global AudioWorkletProcessor, registerProcessor */

const PAUSE_RAMP_SECONDS = 0.005

/** Default anchor cadence: 480 frames = 10 ms at 48 kHz. */
const ANCHOR_EVERY_FRAMES = 480

/** Ring capacity in seconds; 8 s bounds every allocation (≫ 2 s prebuffer). */
const RING_SECONDS = 8

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
    this.anchorEvery = anchorEveryFrames ?? ANCHOR_EVERY_FRAMES
    this.capacity = Math.ceil(sampleRate * RING_SECONDS)
    this.rings = []
    for (let c = 0; c < channelCount; c++) {
      this.rings.push({ data: new Float32Array(this.capacity), read: 0, write: 0, count: 0 })
    }
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
  }

  /** Frames currently buffered (identical for every channel). */
  get available() {
    return this.rings[0].count
  }

  /**
   * Deinterleave f32le `buffer` into the rings.
   * @returns {boolean} false if the ring would overflow (caller drops it).
   */
  enqueue(buffer) {
    if (this.ended) return false
    const bytesPerFrame = 4 * this.channelCount
    let frames = Math.floor(buffer.byteLength / bytesPerFrame)
    if (frames <= 0) return false
    // Never accept data beyond the valid endpoint (defensive; the
    // transport already clamps chunk ranges). The valid remainder
    // excludes what is already buffered.
    frames = Math.min(frames, this.frameCount - this.position - this.available)
    if (frames <= 0) return false
    if (this.available + frames > this.capacity) return false
    const view = new DataView(buffer)
    for (let c = 0; c < this.channelCount; c++) {
      const ring = this.rings[c]
      for (let f = 0; f < frames; f++) {
        ring.data[ring.write] = view.getFloat32((f * this.channelCount + c) * 4, true)
        ring.write = (ring.write + 1) % this.capacity
      }
      ring.count += frames
    }
    this.flushing = false
    this.underrunNotified = false
    return true
  }

  /**
   * Drop all buffered data and move to `frame`. This is the stale-audio
   * barrier: nothing enqueued before the seek can be output after it.
   */
  seek(frame) {
    const target = Math.max(0, Math.min(Math.floor(frame), this.frameCount))
    for (const ring of this.rings) {
      ring.read = 0
      ring.write = 0
      ring.count = 0
    }
    this.position = target
    this.flushing = true
    this.paused = false
    this.rampRemaining = 0
    this.rampTotal = 0
    this.ended = target >= this.frameCount
    this.endedNotified = false
    this.underrunNotified = false
    this.lastAnchorFrame = target
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
  }

  /**
   * Fill the output channels deterministically.
   * @param {number} time context time at which this block plays
   * @param {Float32Array[]} outputChannels one array per channel
   */
  process(time, outputChannels) {
    const frames = outputChannels[0].length
    const out = { consumed: 0, underrun: false, ended: false, anchor: null }
    if (this.ended) {
      this.fillSilence(outputChannels, 0, frames)
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
      } else {
        this.fillSilence(outputChannels, 0, frames)
      }
      return out
    }
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
        out.anchor = { frame: this.position, time }
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      out.anchor = { frame: this.lastAnchorFrame, time }
      this.lastAnchorFrame = this.position
    }
    out.consumed = take
    return out
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
      this.port.onmessage = (e) => {
        const m = e.data
        if (!m || typeof m !== 'object') return
        if (m.type === 'samples') {
          if (this.core.enqueue(m.buffer)) {
            // Acknowledge so the main thread can leave preparing/seeking.
            this.port.postMessage({
              type: 'data',
              frames: this.core.available,
              generation: this.generation,
            })
          }
        } else if (m.type === 'seek') {
          this.generation = m.generation
          this.core.seek(m.frame)
          this.port.postMessage({ type: 'flushed', generation: this.generation })
        } else if (m.type === 'pause') {
          this.core.pause()
        } else if (m.type === 'resume') {
          this.core.resume()
        }
        // 'dispose' needs no worklet-side action.
      }
    }

    process(time, input, output) {
      const res = this.core.process(time, output)
      if (res.anchor) {
        this.port.postMessage({
          type: 'anchor',
          frame: res.anchor.frame,
          time: res.anchor.time,
          generation: this.generation,
        })
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
