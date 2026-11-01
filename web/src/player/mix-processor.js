/**
 * AudioWorklet playback core for the local bass practice studio (t2).
 *
 * Ported from the proven legacy engine (`legacy:frontend/src/playback/
 * mix-processor.js`): the `ConsumptionState` ring reader, the
 * `MixState` multi-source mixer with the *rolling seek* Signalsmith
 * Stretch path, the practice-loop stream model, and the procedural
 * metronome clicks. The new parts are `stretch_set_transpose` support
 * (independent pitch, −12…+12 semitones) and a count-in phase that runs
 * before the first loop pass.
 *
 * Self-contained on purpose: the browser loads this exact file as a
 * Blob-URL worklet module (imports are not available there), while the
 * unit tests import it directly as an ES module. The `registerProcessor`
 * call is guarded by a global check, so the module is safe to load on
 * the main thread. A blob prepends `stretch/stretch-worklet.js`, which
 * attaches `globalThis.StretchWasm` before this script runs.
 *
 * The core has two data paths, both fed by the ranged PCM fetch worker:
 * - transfer: `enqueueChannels` appends deinterleaved chunks to a bounded
 *   queue; `process` drains the queue into per-channel rings and
 *   consumes from them.
 * - shared: `attachShared` binds a SharedArrayBuffer ring (Int32 header
 *   `[generation, writerIdx, readerIdx, 0]` + interleaved f32 data); the
 *   fetch worker is the sole writer and this core the sole reader.
 *   `process` polls the atomic writer index — never blocks.
 *
 * Audio-thread constraints: no network, no filesystem, no promises, no
 * logging, no unbounded allocations, no waits. Underruns, missing
 * sources and out-of-range controls are reported through the return
 * value / clamped values; nothing throws into the render callback.
 */

/* global AudioWorkletProcessor, registerProcessor */

const PAUSE_RAMP_SECONDS = 0.005;
const MIX_RAMP_SECONDS = 0.005;
const RATE_RAMP_SECONDS = 0.05;

/** Default ring capacity when the caller does not pass `capacityFrames`. */
const DEFAULT_CAPACITY_SECONDS = 12;

/** Silent pre-roll before a wet start (engine accumulator warm-up). */
const WARMUP_OUT_FRAMES = 5760;

/** Ring holding the stem-mixed stereo before the stretcher. */
const MIX_RING_FRAMES = 16384;

/** Supported control ranges (t2 contract). */
export const MIN_RATE = 0.25;
export const MAX_RATE = 2.0;
export const MIN_TRANSPOSE = -12;
export const MAX_TRANSPOSE = 12;

const nowMs =
  typeof performance !== "undefined" && typeof performance.now === "function"
    ? () => performance.now()
    : () => Date.now();

function defaultAnchorEvery(sampleRate) {
  return Math.max(1, Math.round(sampleRate / 20));
}

/** Clamp a playback rate; NaN/non-finite falls back to 1× (never throws). */
export function clampRate(rate) {
  if (!Number.isFinite(rate)) return 1;
  return Math.min(MAX_RATE, Math.max(MIN_RATE, rate));
}

/** Clamp a pitch shift; NaN/non-finite falls back to 0 semitones. */
export function clampTranspose(semitones) {
  if (!Number.isFinite(semitones)) return 0;
  return Math.min(MAX_TRANSPOSE, Math.max(MIN_TRANSPOSE, semitones));
}

/** Positive modulo for stream coordinates that may be negative. */
function wrap(value, length) {
  return ((value % length) + length) % length;
}

/**
 * One source's ring/queue reader. The transport feeds contiguous stream
 * frames; a loop stream is unbounded (`looping = true`), so the source
 * length no longer caps the position.
 */
export class ConsumptionState {
  constructor({
    sampleRate,
    channelCount,
    frameCount,
    anchorEveryFrames,
    capacityFrames,
  }) {
    if (!(sampleRate > 0)) throw new RangeError("sampleRate must be > 0");
    if (!(channelCount >= 1)) throw new RangeError("channelCount must be >= 1");
    if (!(frameCount >= 0)) throw new RangeError("frameCount must be >= 0");
    this.sampleRate = sampleRate;
    this.channelCount = channelCount;
    this.frameCount = frameCount;
    this.anchorEvery = anchorEveryFrames ?? defaultAnchorEvery(sampleRate);
    this.capacity =
      Number.isFinite(capacityFrames) && capacityFrames > 0
        ? Math.floor(capacityFrames)
        : Math.ceil(sampleRate * DEFAULT_CAPACITY_SECONDS);
    this.rings = [];
    for (let c = 0; c < channelCount; c++) {
      this.rings.push({
        data: new Float32Array(this.capacity),
        read: 0,
        write: 0,
        count: 0,
      });
    }
    /** Transfer-path chunk queue (deinterleaved). */
    this.queue = [];
    this.queuedFrames = 0;
    /** Shared path: { header, data, capacity } views over the SAB. */
    this.shared = null;
    /** Shared path: the generation this reader is aligned to. */
    this.localGen = 0;
    /** Next stream frame to consume. */
    this.position = 0;
    /** A loop stream is unbounded in stream coordinates. */
    this.looping = false;
    /** No data expected yet: silence without an underrun flag. */
    this.flushing = true;
    this.ended = false;
  }

  get available() {
    return this.rings[0].count;
  }

  get buffered() {
    if (this.shared) {
      const { header } = this.shared;
      const writer = Atomics.load(header, 1);
      const reader = Atomics.load(header, 2);
      return Math.max(0, writer - reader);
    }
    return this.available + this.queuedFrames;
  }

  get queued() {
    return this.shared ? 0 : this.queuedFrames;
  }

  /**
   * Queue pre-deinterleaved per-channel arrays (transfer path).
   * @returns {boolean} false if the budget would overflow (caller drops it).
   */
  enqueueChannels(channels) {
    if (this.ended || this.shared) return false;
    if (!Array.isArray(channels) || channels.length !== this.channelCount)
      return false;
    let frames = channels[0].length;
    if (frames <= 0) return false;
    if (!this.looping) {
      frames = Math.min(
        frames,
        this.frameCount - this.position - this.available - this.queuedFrames,
      );
      if (frames <= 0) return false;
    }
    if (this.available + this.queuedFrames + frames > this.capacity)
      return false;
    const trimmed = channels.map((ch) =>
      ch.length === frames ? ch : ch.subarray(0, frames),
    );
    this.queue.push({ channels: trimmed, frames });
    this.queuedFrames += frames;
    this.flushing = false;
    return true;
  }

  drainQueue() {
    if (this.shared) return;
    while (this.queue.length > 0) {
      const head = this.queue[0];
      if (this.available + head.frames > this.capacity) break;
      for (let c = 0; c < this.channelCount; c++) {
        const ring = this.rings[c];
        const src = head.channels[c];
        for (let f = 0; f < head.frames; f++) {
          ring.data[ring.write] = src[f];
          ring.write = (ring.write + 1) % this.capacity;
        }
        ring.count += head.frames;
      }
      this.queue.shift();
      this.queuedFrames -= head.frames;
    }
  }

  /** Bind the shared ring (SPSC: worker writes, this reader reads). */
  attachShared(sab) {
    const header = new Int32Array(sab, 0, 4);
    const data = new Float32Array(sab, 16);
    const capacity = Math.floor(data.length / this.channelCount);
    if (!(capacity > 0)) throw new RangeError("shared ring holds no frames");
    this.shared = { header, data, capacity };
    this.capacity = capacity;
    this.localGen = Atomics.load(header, 0);
  }

  setLooping(looping) {
    this.looping = looping === true;
  }

  /**
   * Drop all buffered data and move to `frame`: the stale-audio barrier.
   * On the shared path this stores the reader index and adopts the new
   * generation; the writer index is reset by the worker on flush ack.
   */
  seek(frame, generation) {
    const target = this.looping
      ? Math.floor(frame)
      : Math.max(0, Math.min(Math.floor(frame), this.frameCount));
    for (const ring of this.rings) {
      ring.read = 0;
      ring.write = 0;
      ring.count = 0;
    }
    this.queue.length = 0;
    this.queuedFrames = 0;
    if (this.shared) Atomics.store(this.shared.header, 2, target);
    if (typeof generation === "number") this.localGen = generation;
    this.position = target;
    this.flushing = true;
    this.ended = !this.looping && target >= this.frameCount;
  }

  /**
   * Consume up to `frames` into per-channel arrays; the mixer advances
   * every source by the same amount, so alignment is exact.
   * @returns {number} frames consumed
   */
  consumeInto(outChannels, frames) {
    if (this.ended) return 0;
    if (this.shared) return this.consumeShared(outChannels, frames);
    this.drainQueue();
    let take = Math.min(frames, this.available);
    if (!this.looping) take = Math.min(take, this.frameCount - this.position);
    if (take <= 0) return 0;
    for (let c = 0; c < this.channelCount; c++) {
      const ring = this.rings[c];
      for (let i = 0; i < take; i++) {
        outChannels[c][i] = ring.data[ring.read];
        ring.read = (ring.read + 1) % this.capacity;
      }
      ring.count -= take;
    }
    this.position += take;
    this.flushing = false;
    return take;
  }

  consumeShared(outChannels, frames) {
    const { header, data, capacity } = this.shared;
    if (Atomics.load(header, 0) !== this.localGen) {
      // Generation mismatch: the ring holds stale data.
      return 0;
    }
    const reader = Atomics.load(header, 2);
    const writer = Atomics.load(header, 1);
    const avail = Math.max(0, writer - reader);
    let take = Math.min(frames, avail);
    if (!this.looping) take = Math.min(take, this.frameCount - this.position);
    if (take <= 0) return 0;
    for (let i = 0; i < take; i++) {
      const src = wrap(reader + i, capacity);
      const base = src * this.channelCount;
      for (let c = 0; c < this.channelCount; c++)
        outChannels[c][i] = data[base + c];
    }
    Atomics.store(header, 2, reader + take);
    this.position += take;
    this.flushing = false;
    return take;
  }
}

// ---------------------------------------------------------------------------
// Metronome clicks

function makeClickTable(sampleRate, frequency, durationSeconds, amplitude) {
  const length = Math.max(1, Math.round(sampleRate * durationSeconds));
  const table = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const t = i / sampleRate;
    table[i] =
      amplitude * Math.exp(-t / 0.008) * Math.sin(2 * Math.PI * frequency * t);
  }
  return table;
}

const CLICK_TABLES = {
  downbeat: [1500, 0.04, 0.9],
  beat: [1000, 0.03, 0.6],
  subdivision: [800, 0.02, 0.3],
};
const MAX_CLICK_VOICES = 8;

/**
 * Procedural click voice pool. Beats and count-in clicks share it, so
 * the output is one mixed metronome layer regardless of who scheduled
 * the click. `trigger(strength, delay)` starts a voice `delay` output
 * frames into the next `render`; `render` mixes every active voice.
 */
export class ClickMixer {
  constructor(sampleRate, volume = 0.5) {
    this.sampleRate = sampleRate;
    this.volume = volume;
    this.tables = {};
    for (const [strength, [frequency, duration, amplitude]] of Object.entries(
      CLICK_TABLES,
    )) {
      this.tables[strength] = makeClickTable(
        sampleRate,
        frequency,
        duration,
        amplitude,
      );
    }
    this.voices = [];
    // Diagnostics: clicks actually rendered, not just scheduled.
    this.renderedClicks = 0;
    this.lastClickFrame = -1;
  }

  setVolume(volume) {
    this.volume = Number.isFinite(volume)
      ? Math.min(1, Math.max(0, volume))
      : 0;
  }

  /** Drop every active voice (seek / pause / count-in end). */
  reset() {
    this.voices.length = 0;
  }

  trigger(strength, delay = 0) {
    const table = this.tables[strength] ?? this.tables.beat;
    if (this.voices.length >= MAX_CLICK_VOICES) this.voices.shift();
    this.voices.push({ table, pos: 0, delay: Math.max(0, Math.round(delay)) });
    this.renderedClicks += 1;
    this.lastClickFrame += 0;
  }

  /**
   * Mix active voices into `channels[0..1]` for this output quantum.
   * `startFrame` is the absolute output frame of channel[0], used only
   * for the diagnostic `lastClickFrame`.
   */
  render(channels, frames, startFrame = 0) {
    if (frames <= 0 || channels.length === 0) return;
    const gain = this.volume;
    let writeIndex = 0;
    for (const voice of this.voices) {
      if (voice.delay >= frames) {
        voice.delay -= frames;
        continue;
      }
      const offset = voice.delay;
      voice.delay = 0;
      const count = Math.min(frames - offset, voice.table.length - voice.pos);
      for (let i = 0; i < count; i += 1) {
        const sample = voice.table[voice.pos + i] * gain;
        for (let c = 0; c < channels.length && c < 2; c++)
          channels[c][offset + i] += sample;
      }
      voice.pos += count;
      writeIndex += count;
    }
    this.voices = this.voices.filter((voice) => voice.pos < voice.table.length);
    if (writeIndex > 0 && this.lastClickFrame < 0)
      this.lastClickFrame = startFrame;
  }
}

/**
 * Multi-source mixer + Signalsmith Stretch (rolling seek) + practice loop
 * + metronome + count-in. One instance lives in the worklet.
 */
export class PlaybackCore {
  constructor({
    sampleRate,
    frameCount,
    sources,
    engine = null,
    capacityFrames = 0,
  }) {
    if (!(sampleRate > 0)) throw new RangeError("sampleRate must be > 0");
    if (!(frameCount >= 0)) throw new RangeError("frameCount must be >= 0");
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new RangeError("sources must be a non-empty array");
    }
    this.sampleRate = sampleRate;
    this.frameCount = frameCount;
    this.sources = sources.map(
      (source) =>
        new ConsumptionState({
          sampleRate,
          channelCount: source.channelCount,
          frameCount,
          anchorEveryFrames: Number.MAX_SAFE_INTEGER,
          capacityFrames,
        }),
    );
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
    }));
    this.masterGain = 1.0;
    this.masterFrom = 1.0;
    this.masterTo = 1.0;
    this.masterRampTotal = 0;
    this.masterRampRemaining = 0;
    this.position = 0;
    this.ended = false;
    this.endedNotified = false;
    this.underrunNotified = false;
    // The engine must never make sound before an explicit resume. The
    // transport also posts a pause before delivering PCM; both halves are
    // intentional so a worklet default change cannot leak audio on load.
    this.paused = true;
    this.rampTotal = 0;
    this.rampRemaining = 0;
    this.pauseAnchorSent = false;
    this.lastAnchorFrame = 0;
    this.anchorEvery = defaultAnchorEvery(sampleRate);
    this.rateCurrent = 1;
    this.lastSample = new Float32Array(2);
    this.lastProcessMs = 0;
    this.engine = engine;
    this.transpose = 0;
    if (engine) {
      const lat = engine.latencies();
      this.inLat = lat.inputFrames;
      this.outLat = lat.outputFrames;
      this.windowFrames = engine.windowLength();
      this.ringCap = MIX_RING_FRAMES;
      this.ringL = new Float32Array(this.ringCap);
      this.ringR = new Float32Array(this.ringCap);
      this.ringBase = 0;
      this.ringStart = 0;
      this.ringEnd = 0;
      this.rateTarget = 1;
      this.rateGoal = 1;
      this.rateFrom = 1;
      this.rateRampTotal = Math.max(
        1,
        Math.round(RATE_RAMP_SECONDS * sampleRate),
      );
      this.rateRampRemaining = 0;
      this.bypass = "dry";
      this.xfade = null;
      this.xfadeTotal = Math.max(1, Math.round(0.005 * sampleRate));
      this.dryGain = 1;
      this.wetGain = 0;
      this.dryGainPrev = 1;
      this.wetGainPrev = 0;
      this.rolledFrames = 0;
      this.warmupRemaining = 0;
      this.audible = 0;
    }
    // Practice loop (stream coordinates; source-aligned at the seek).
    this.loop = null;
    this.loopPasses = 0;
    this.loopComplete = false;
    this.loopNextCrossing = null;
    this.loopCounted = false;
    this.loopAnchor = null;
    this.loopCompletion = null;
    // Metronome: project-frame beats + count-in.
    this.clicks = new ClickMixer(sampleRate);
    this.beats = [];
    // Stream frames already clicked: a beat whose offset falls in the
    // last quantum of a pass must not fire again when the cursor lands
    // exactly on the pass start (and a frozen cursor must not repeat).
    this.recentClickFrames = [];
    this.countIn = null;
    // Bounded scratch, grown only if a larger block ever arrives.
    this.engineFillChunk = 4096;
    this.blockCap = 0;
    this.coeffL = [];
    this.coeffR = [];
    this.temp = [];
    this.masterCoeff = null;
    this.mixL = null;
    this.mixR = null;
    this.ensureBlockCapacity(engine ? this.engineFillChunk : 128);
  }

  get buffered() {
    let buffered = Infinity;
    for (const source of this.sources)
      buffered = Math.min(buffered, source.buffered);
    return buffered === Infinity ? 0 : buffered;
  }

  get queued() {
    let queued = Infinity;
    for (const source of this.sources) queued = Math.min(queued, source.queued);
    return queued === Infinity ? 0 : queued;
  }

  get capacity() {
    let capacity = Infinity;
    for (const source of this.sources)
      capacity = Math.min(capacity, source.capacity);
    return capacity === Infinity ? 0 : capacity;
  }

  ensureBlockCapacity(frames) {
    if (frames <= this.blockCap) return;
    this.blockCap = frames;
    this.coeffL = this.sources.map(() => new Float32Array(frames));
    this.coeffR = this.sources.map(() => new Float32Array(frames));
    this.temp = this.sources.map((source) =>
      Array.from(
        { length: source.channelCount },
        () => new Float32Array(frames),
      ),
    );
    this.masterCoeff = new Float32Array(frames);
    this.mixL = new Float32Array(frames);
    this.mixR = new Float32Array(frames);
  }

  // -- mixer parameters -----------------------------------------------------

  setSourceParams(index, patch) {
    const params = this.params[index];
    if (!params) return;
    const changed =
      (patch.gain !== undefined && patch.gain !== params.gain) ||
      (patch.balance !== undefined && patch.balance !== params.balance) ||
      (patch.mute !== undefined && patch.mute !== params.mute) ||
      (patch.solo !== undefined && patch.solo !== params.solo);
    if (!changed) return;
    if (patch.gain !== undefined) {
      params.gain = Number.isFinite(patch.gain)
        ? Math.max(0, patch.gain)
        : params.gain;
      params.gTo = params.gain;
    }
    if (patch.balance !== undefined) {
      params.balance = Number.isFinite(patch.balance)
        ? Math.min(1, Math.max(-1, patch.balance))
        : params.balance;
      params.bTo = params.balance;
    }
    if (patch.mute !== undefined) params.mute = patch.mute === true;
    if (patch.solo !== undefined) params.solo = patch.solo === true;
    const anySolo = this.params.some((other) => other.solo);
    const dirty = new Set();
    this.params.forEach((other, i) => {
      const target = !other.mute && (!anySolo || other.solo) ? 1.0 : 0.0;
      if (target !== other.eTo) {
        other.eTo = target;
        dirty.add(i);
      }
    });
    dirty.add(index);
    dirty.forEach((i) => this.startParamRamp(i));
  }

  startParamRamp(index) {
    const params = this.params[index];
    const k =
      params.rampTotal > 0 ? params.rampRemaining / params.rampTotal : 0;
    params.gFrom = params.gTo - (params.gTo - params.gFrom) * k;
    params.bFrom = params.bTo - (params.bTo - params.bFrom) * k;
    params.eFrom = params.eTo - (params.eTo - params.eFrom) * k;
    params.rampTotal = Math.max(
      1,
      Math.round(MIX_RAMP_SECONDS * this.sampleRate),
    );
    params.rampRemaining = params.rampTotal;
  }

  setMasterGain(gain) {
    if (!Number.isFinite(gain) || gain < 0 || gain === this.masterGain) return;
    const k =
      this.masterRampTotal > 0
        ? this.masterRampRemaining / this.masterRampTotal
        : 0;
    this.masterFrom = this.masterTo - (this.masterTo - this.masterFrom) * k;
    this.masterTo = gain;
    this.masterGain = gain;
    this.masterRampTotal = Math.max(
      1,
      Math.round(MIX_RAMP_SECONDS * this.sampleRate),
    );
    this.masterRampRemaining = this.masterRampTotal;
  }

  /** Route a transfer-path chunk to one source. */
  enqueueChannels(index, channels) {
    const source = this.sources[index];
    if (!source) return false;
    const ok = source.enqueueChannels(channels);
    if (ok) this.underrunNotified = false;
    return ok;
  }

  attachShared(index, sab) {
    const source = this.sources[index];
    if (source) source.attachShared(sab);
  }

  // -- pitch ----------------------------------------------------------------

  /**
   * Independent pitch shift in semitones (clamped −12…+12). The engine
   * applies it on the next render; the rolling seek is untouched, so
   * pitch changes never reposition or reset the stream.
   */
  setTranspose(semitones) {
    this.transpose = clampTranspose(semitones);
    if (!this.engine) return this.transpose;
    this.engine.setTranspose(this.transpose);
    // Pitch is a wet-path effect: engage the engine even at exactly 1x.
    if (this.transpose !== 0 && this.rolledFrames < WARMUP_OUT_FRAMES) {
      if (this.paused || this.rolledFrames === 0) {
        this.warmupRemaining = Math.max(
          this.warmupRemaining,
          WARMUP_OUT_FRAMES - this.rolledFrames,
        );
      }
    }
    return this.transpose;
  }

  // -- practice loop --------------------------------------------------------

  setLoop(spec) {
    this.loop = spec
      ? {
          start: Math.floor(spec.start),
          end: Math.floor(spec.end),
          len: Math.max(1, Math.floor(spec.end) - Math.floor(spec.start)),
          repeatCount: spec.repeatCount ?? null,
          fade: spec.fade !== false,
        }
      : null;
    this.loopPasses = 0;
    this.loopComplete = false;
    this.loopAnchor = null;
    this.loopCompletion = null;
    this.loopCounted = false;
    this.loopNextCrossing = this.loop
      ? this.nextCrossingFrom(this.loopCursor())
      : null;
    this.recentClickFrames.length = 0;
    this.sources.forEach((source) => source.setLooping(this.loop !== null));
  }

  loopCursor() {
    return this.engine ? this.audible : this.position;
  }

  loopSourceOf(c) {
    const loop = this.loop;
    return loop.start + wrap(c - loop.start, loop.len);
  }

  nextCrossingFrom(c) {
    return c + (this.loop.end - this.loopSourceOf(c));
  }

  loopFadeFrames(rate) {
    const loop = this.loop;
    if (!loop.fade) return 0;
    const byTime = Math.round(0.005 * this.sampleRate);
    const byLoop = Math.max(1, Math.round(loop.len / Math.max(rate, 0.01) / 4));
    return Math.min(byTime, byLoop);
  }

  /**
   * Locate the pass crossing whose join notch overlaps this quantum,
   * count the completed pass, schedule the wrap anchor and flag the
   * finite-repeat stop. Pass ends are exactly `len` stream frames apart,
   * so no per-iteration rounding accumulates.
   */
  loopQuantum(time, rate, frames) {
    const loop = this.loop;
    if (!loop) return null;
    const S = this.loopCursor();
    const advance = rate * frames;
    const fade = this.loopFadeFrames(rate);
    let c = this.loopNextCrossing;
    while (c !== null && c + fade * rate <= S) {
      c += loop.len;
      this.loopCounted = false;
    }
    if (c === null || c - fade * rate >= S + advance) {
      this.loopNextCrossing = c;
      return null;
    }
    const center = (c - S) / rate;
    let final = false;
    if (center <= frames && !this.loopCounted) {
      this.loopCounted = true;
      this.loopPasses += 1;
      final = loop.repeatCount !== null && this.loopPasses >= loop.repeatCount;
      if (final) {
        this.loopComplete = true;
        this.loopCompletion = {
          frame: c,
          time: time + center / this.sampleRate,
        };
        this.position = c;
      } else {
        this.loopAnchor = { frame: c, time: time + center / this.sampleRate };
      }
    }
    return { center, fade, final };
  }

  // -- transport controls ---------------------------------------------------

  seek(frame, generations, audibleFrame, loopSpec) {
    if (loopSpec !== undefined) this.setLoop(loopSpec);
    const looping = this.loop !== null;
    const target = looping
      ? Math.floor(frame)
      : Math.max(0, Math.min(Math.floor(frame), this.frameCount));
    const audible = looping
      ? Math.floor(audibleFrame ?? target)
      : Math.max(
          0,
          Math.min(Math.floor(audibleFrame ?? target), this.frameCount),
        );
    const active = this.loop !== null;
    this.sources.forEach((source, i) => {
      const generation = Array.isArray(generations)
        ? generations[i]
        : generations;
      source.setLooping(active);
      source.seek(target, generation);
    });
    this.position = audible;
    this.ended = !active && audible >= this.frameCount;
    this.endedNotified = false;
    this.underrunNotified = false;
    // A seek repositions the stream; it does not start playback. The pause
    // flag survives, so a paused seek stays silent until `resume`.
    this.rampRemaining = 0;
    this.pauseAnchorSent = false;
    this.lastAnchorFrame = audible;
    this.lastSample.fill(0);
    this.clicks.reset();
    this.recentClickFrames.length = 0;
    this.countIn = null;
    if (active) {
      this.loopNextCrossing = this.nextCrossingFrom(audible);
      this.loopCounted = false;
    }
    if (this.engine) {
      // Hard re-position: drop the synthesis state and re-roll from the
      // fetch frame. A wet start is warmed with an inaudible pre-roll.
      this.engine.reset();
      this.engine.setTranspose(this.transpose);
      this.audible = audible;
      this.ringBase = target;
      this.ringStart = target;
      this.ringEnd = target;
      this.rolledFrames = 0;
      this.rateCurrent = this.rateTarget;
      this.rateGoal = this.rateTarget;
      this.rateFrom = this.rateTarget;
      this.rateRampRemaining = 0;
      this.bypass =
        this.rateTarget === 1 && this.transpose === 0 ? "dry" : "wet";
      this.xfade = null;
      this.dryGain = this.bypass === "dry" ? 1 : 0;
      this.wetGain = 1 - this.dryGain;
      this.warmupRemaining =
        this.bypass === "dry" || this.ended ? 0 : WARMUP_OUT_FRAMES;
    }
  }

  /** Set the playback-rate target; the core ramps ≈50 ms itself. */
  setRate(rate) {
    const target = clampRate(rate);
    this.rateTarget = target;
    if (!this.engine || this.ended) return;
    if (target !== 1 && this.rolledFrames < WARMUP_OUT_FRAMES) {
      if (this.paused || this.rolledFrames === 0) {
        this.warmupRemaining = Math.max(
          this.warmupRemaining,
          WARMUP_OUT_FRAMES - this.rolledFrames,
        );
      }
    }
  }

  /** Begin the pause ramp; the cursor is preserved. */
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.countIn = null;
    this.clicks.reset();
    this.rampTotal = Math.max(
      1,
      Math.round(PAUSE_RAMP_SECONDS * this.sampleRate),
    );
    this.rampRemaining = this.rampTotal;
  }

  resume() {
    this.paused = false;
    this.rampRemaining = 0;
    this.pauseAnchorSent = false;
  }

  // -- metronome ------------------------------------------------------------

  setMetronomeVolume(volume) {
    this.clicks.setVolume(volume);
  }

  /**
   * Replace the metronome beat list. Frames are project frames; the
   * core maps them through the active loop and playback rate, so clicks
   * follow the music at every speed.
   */
  setBeats(beats) {
    this.beats = (Array.isArray(beats) ? beats : [])
      .filter(
        (beat) =>
          beat &&
          Number.isFinite(beat.frame) &&
          (beat.strength === "downbeat" ||
            beat.strength === "beat" ||
            beat.strength === "subdivision"),
      )
      .map((beat) => ({
        frame: Math.floor(beat.frame),
        strength: beat.strength,
      }))
      .sort((a, b) => a.frame - b.frame);
  }

  /**
   * Start a count-in: `bars × beatsPerBar` clicks at `beatFrames` apart
   * (output frames), accented on every bar start. The audible cursor
   * stays frozen at the current position for the whole count-in, so the
   * first loop pass begins only after the last click.
   */
  startCountIn({ bars, beatsPerBar, beatFrames }) {
    const safeBars = Math.max(0, Math.floor(bars ?? 0));
    const safeBeats = Math.max(1, Math.floor(beatsPerBar ?? 4));
    const safeBeatFrames = Math.max(
      1,
      Math.floor(beatFrames ?? Math.round(this.sampleRate * 0.5)),
    );
    if (safeBars === 0) {
      this.countIn = null;
      return 0;
    }
    this.countIn = {
      total: safeBars * safeBeats * safeBeatFrames,
      elapsed: 0,
      beatsPerBar: safeBeats,
      beatFrames: safeBeatFrames,
    };
    this.clicks.reset();
    return this.countIn.total;
  }

  countInRemaining() {
    return this.countIn
      ? Math.max(0, this.countIn.total - this.countIn.elapsed)
      : 0;
  }

  /** Tick the count-in for one output block and mix its clicks. */
  processCountIn(outputChannels, frames, time, out) {
    const countIn = this.countIn;
    const start = countIn.elapsed;
    const end = start + frames;
    const firstBeat = Math.ceil(start / countIn.beatFrames);
    const lastBeat = Math.floor((end - 1) / countIn.beatFrames);
    for (let beat = firstBeat; beat <= lastBeat; beat += 1) {
      const offset = beat * countIn.beatFrames - start;
      if (offset < 0 || offset >= frames) continue;
      const strength = beat % countIn.beatsPerBar === 0 ? "downbeat" : "beat";
      this.clicks.trigger(strength, offset);
    }
    this.fillOutputSilence(outputChannels, 0, frames);
    this.clicks.render(outputChannels, frames, start);
    countIn.elapsed = end;
    if (countIn.elapsed >= countIn.total) {
      this.countIn = null;
      out.countInDone = true;
      out.anchor = { frame: this.position, time, paused: true };
    }
    out.buffered = this.buffered;
    return out;
  }

  /** Trigger a beat once per stream frame (loop boundary dedupe). */
  triggerBeat(strength, streamFrame, offset) {
    const frame = Math.round(streamFrame);
    if (this.recentClickFrames.some((recent) => Math.abs(recent - frame) < 0.5))
      return;
    this.recentClickFrames.push(frame);
    if (this.recentClickFrames.length > 16) this.recentClickFrames.shift();
    this.clicks.trigger(strength, offset);
  }

  /**
   * Map this quantum's stream range to the beat list and trigger clicks.
   * Loop passes repeat the beat list; a click that would land outside
   * the quantum is picked up by the next one.
   */
  renderBeats(frames, rate, cursor) {
    if (this.beats.length === 0 || this.clicks.volume <= 0) return;
    const advance = rate * frames;
    if (this.loop) {
      const loop = this.loop;
      const passBase =
        loop.start + Math.floor((cursor - loop.start) / loop.len) * loop.len;
      for (const beat of this.beats) {
        if (beat.frame < loop.start || beat.frame >= loop.end) continue;
        let candidate = passBase + (beat.frame - loop.start);
        if (candidate < cursor - 1e-9) candidate += loop.len;
        if (candidate >= cursor + advance) continue;
        const offset = Math.round((candidate - cursor) / rate);
        if (offset >= 0 && offset < frames)
          this.triggerBeat(beat.strength, candidate, offset);
      }
      return;
    }
    for (const beat of this.beats) {
      if (beat.frame < cursor || beat.frame >= cursor + advance) continue;
      const offset = Math.round((beat.frame - cursor) / rate);
      if (offset >= 0 && offset < frames)
        this.triggerBeat(beat.strength, beat.frame, offset);
    }
  }

  // -- mixing ---------------------------------------------------------------

  fillSourceCoeffs(frames) {
    for (let i = 0; i < this.sources.length; i++) {
      const params = this.params[i];
      const stereo = this.sources[i].channelCount > 1;
      const coeffL = this.coeffL[i];
      const coeffR = this.coeffR[i];
      const remaining = Math.min(params.rampRemaining, frames);
      let gStart = params.gTo;
      let bStart = params.bTo;
      let eStart = params.eTo;
      let gSlope = 0;
      let bSlope = 0;
      let eSlope = 0;
      if (remaining > 0) {
        const inv = 1 / params.rampTotal;
        gStart =
          params.gTo - (params.gTo - params.gFrom) * params.rampRemaining * inv;
        bStart =
          params.bTo - (params.bTo - params.bFrom) * params.rampRemaining * inv;
        eStart =
          params.eTo - (params.eTo - params.eFrom) * params.rampRemaining * inv;
        gSlope = (params.gTo - params.gFrom) * inv;
        bSlope = (params.bTo - params.bFrom) * inv;
        eSlope = (params.eTo - params.eFrom) * inv;
      }
      for (let k = 0; k < frames; k++) {
        const gain = k < remaining ? gStart + gSlope * k : params.gTo;
        const balance = k < remaining ? bStart + bSlope * k : params.bTo;
        const env = k < remaining ? eStart + eSlope * k : params.eTo;
        const level = gain * env;
        if (stereo) {
          coeffL[k] = level * Math.pow(10, (-3 * balance) / 10);
          coeffR[k] = level * Math.pow(10, (3 * balance) / 10);
        } else {
          const theta = ((balance + 1) * Math.PI) / 4;
          coeffL[k] = level * Math.cos(theta);
          coeffR[k] = level * Math.sin(theta);
        }
      }
      params.rampRemaining = Math.max(0, params.rampRemaining - frames);
    }
  }

  fillMasterCoeffs(frames) {
    const coeff = this.masterCoeff;
    const remaining = Math.min(this.masterRampRemaining, frames);
    let start = this.masterTo;
    let slope = 0;
    if (remaining > 0) {
      const inv = 1 / this.masterRampTotal;
      start =
        this.masterTo -
        (this.masterTo - this.masterFrom) * this.masterRampRemaining * inv;
      slope = (this.masterTo - this.masterFrom) * inv;
    }
    for (let k = 0; k < frames; k++) {
      coeff[k] = k < remaining ? start + slope * k : this.masterTo;
    }
    this.masterRampRemaining = Math.max(0, this.masterRampRemaining - frames);
  }

  /**
   * Mix one output quantum. Always emits stereo.
   * @returns {{consumed:number, underrun:boolean, ended:boolean, loopComplete:boolean,
   *   countInDone:boolean, anchor:object|null, buffered:number}}
   */
  process(time, outputChannels) {
    const startedAt = nowMs();
    const frames = outputChannels[0].length;
    const out = {
      consumed: 0,
      underrun: false,
      ended: false,
      loopComplete: false,
      countInDone: false,
      anchor: null,
      buffered: 0,
    };
    if (this.countIn) {
      return this.finishProcess(
        this.processCountIn(outputChannels, frames, time, out),
        startedAt,
      );
    }
    if (this.ended || this.loopComplete) {
      this.fillOutputSilence(outputChannels, 0, frames);
      if (this.loopComplete && !this.endedNotified) {
        this.endedNotified = true;
        out.loopComplete = true;
        out.anchor = {
          frame: this.loopCompletion
            ? this.loopCompletion.frame
            : this.position,
          time: this.loopCompletion ? this.loopCompletion.time : time,
          paused: false,
          rate: this.rateCurrent ?? 1,
        };
      }
      out.buffered = this.buffered;
      return this.finishProcess(out, startedAt);
    }
    if (this.engine && this.warmupRemaining > 0) {
      this.runWarmup(frames);
      this.fillOutputSilence(outputChannels, 0, frames);
      out.buffered = this.buffered;
      return this.finishProcess(out, startedAt);
    }
    if (this.paused) {
      if (this.rampRemaining > 0) {
        const level = this.rampRemaining / this.rampTotal;
        for (let c = 0; c < 2; c++) {
          const sample = this.lastSample[c] * level;
          for (let i = 0; i < frames; i++) outputChannels[c][i] = sample;
        }
        this.rampRemaining -= frames;
        if (this.rampRemaining <= 0 && !this.pauseAnchorSent) {
          this.pauseAnchorSent = true;
          out.anchor = {
            frame: this.position,
            time,
            paused: true,
            rate: this.rateCurrent ?? 1,
          };
        }
      } else {
        this.fillOutputSilence(outputChannels, 0, frames);
      }
      out.buffered = this.buffered;
      return this.finishProcess(out, startedAt);
    }
    const cap = this.engine ? Math.max(frames, this.engineFillChunk) : frames;
    this.ensureBlockCapacity(cap);
    if (this.engine) {
      return this.finishProcess(
        this.processWithEngine(time, outputChannels, frames, out),
        startedAt,
      );
    }
    return this.finishProcess(
      this.processPlain(time, outputChannels, frames, out),
      startedAt,
    );
  }

  processPlain(time, outputChannels, frames, out) {
    const beatCursor = this.position;
    let take = frames;
    for (const source of this.sources) take = Math.min(take, source.buffered);
    if (!this.loop) take = Math.min(take, this.frameCount - this.position);
    for (let i = 0; i < this.sources.length; i++) {
      this.sources[i].consumeInto(this.temp[i], take);
    }
    this.fillSourceCoeffs(frames);
    this.fillMasterCoeffs(frames);
    const notch = this.loopQuantum(time, 1, frames);
    const count = this.sources.length;
    const ch0 = outputChannels[0];
    const ch1 = outputChannels.length > 1 ? outputChannels[1] : ch0;
    for (let f = 0; f < take; f++) {
      let l = 0;
      let r = 0;
      for (let i = 0; i < count; i++) {
        const gL = this.coeffL[i][f];
        const gR = this.coeffR[i][f];
        const sample = this.temp[i][0][f];
        if (this.sources[i].channelCount === 1) {
          l += sample * gL;
          r += sample * gR;
        } else {
          l += sample * gL;
          r += this.temp[i][1][f] * gR;
        }
      }
      if (notch) {
        const gain =
          notch.fade > 0
            ? Math.min(1, Math.abs(notch.center - f) / notch.fade)
            : 1;
        l *= gain;
        r *= gain;
        if (notch.final && f >= notch.center) {
          l = 0;
          r = 0;
        }
      }
      const master = this.masterCoeff[f];
      ch0[f] = l * master;
      ch1[f] = r * master;
    }
    if (take < frames) {
      this.fillOutputSilence(outputChannels, take, frames - take);
      this.maybeUnderrun(out);
    }
    if (this.loopComplete) {
      this.position = this.loopCompletion
        ? this.loopCompletion.frame
        : this.position;
    } else {
      this.position += take;
    }
    for (let c = 0; c < 2; c++) {
      this.lastSample[c] =
        take > 0 && c < outputChannels.length ? outputChannels[c][take - 1] : 0;
    }
    this.renderBeats(frames, 1, beatCursor);
    this.clicks.render(outputChannels, frames);
    this.advance(time, out, time + take / this.sampleRate);
    out.consumed = take;
    out.buffered = this.buffered;
    return out;
  }

  finishProcess(out, startedAt) {
    this.lastProcessMs = nowMs() - startedAt;
    return out;
  }

  advance(time, out, endTime) {
    const rate = this.rateCurrent ?? 1;
    if (this.loop) {
      if (this.loopComplete) {
        if (!this.endedNotified) {
          this.endedNotified = true;
          out.loopComplete = true;
          out.anchor = {
            frame: this.loopCompletion
              ? this.loopCompletion.frame
              : this.position,
            time: this.loopCompletion ? this.loopCompletion.time : endTime,
            paused: false,
            rate,
          };
        }
        return;
      }
      if (this.loopAnchor) {
        out.anchor = {
          frame: this.loopAnchor.frame,
          time: this.loopAnchor.time,
          paused: false,
          rate,
          wrap: true,
        };
        this.loopAnchor = null;
        return;
      }
      if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
        out.anchor = {
          frame: this.position,
          time: endTime,
          paused: false,
          rate,
        };
        this.lastAnchorFrame = this.position;
      }
      return;
    }
    if (this.position >= this.frameCount) {
      this.ended = true;
      if (!this.endedNotified) {
        this.endedNotified = true;
        out.ended = true;
        out.anchor = {
          frame: this.position,
          time: endTime,
          paused: false,
          rate,
        };
      }
    } else if (this.position - this.lastAnchorFrame >= this.anchorEvery) {
      out.anchor = { frame: this.position, time: endTime, paused: false, rate };
      this.lastAnchorFrame = this.position;
    }
  }

  /**
   * Report a starvation once per episode. Silence with nothing ever
   * buffered (prebuffer after a seek) is not an underrun; a source that
   * has already played data and then runs dry is.
   */
  maybeUnderrun(out) {
    const expected = this.sources.some((source) => !source.flushing);
    if (!this.underrunNotified && expected) {
      out.underrun = true;
      this.underrunNotified = true;
    }
  }

  /**
   * Engine data path: per-stem gain/pan/mute/solo -> stereo sum -> mix
   * ring -> rolling seek -> master gain -> output. Two taps read the
   * ring: the exact 1× dry bypass and the stretched wet path. They
   * only crossfade while both are at exactly 1×.
   */
  processWithEngine(time, outputChannels, frames, out) {
    const engine = this.engine;
    const beatCursor = this.audible;
    this.updateRateState(frames);
    const rate = this.rateCurrent;
    const dryStart = Math.round(this.audible);
    const dryActive = this.dryGain > 0 || this.dryGainPrev > 0;
    const windowEnd = Math.round(
      this.audible + rate * this.outLat + this.inLat,
    );
    const windowStart = windowEnd - this.windowFrames;
    const windowTo = this.loop
      ? windowEnd
      : Math.min(windowEnd, this.frameCount);
    const dryTo = this.loop
      ? dryStart + frames
      : Math.min(dryStart + frames, this.frameCount);
    let needTo = windowTo;
    if (dryActive) needTo = Math.max(needTo, dryTo);
    if (needTo > this.ringEnd) this.fillRing(needTo);
    if (this.ringEnd < windowTo || (dryActive && this.ringEnd < dryTo)) {
      this.fillOutputSilence(outputChannels, 0, frames);
      this.maybeUnderrun(out);
      out.buffered = this.buffered;
      return out;
    }
    const ch0 = outputChannels[0];
    const ch1 = outputChannels.length > 1 ? outputChannels[1] : ch0;
    if (dryActive) {
      if (dryTo > dryStart) {
        this.copyFromRing(this.ringL, ch0, 0, dryStart, dryTo - dryStart);
        this.copyFromRing(this.ringR, ch1, 0, dryStart, dryTo - dryStart);
      }
      if (dryTo - dryStart < frames) {
        this.fillOutputSilence(
          outputChannels,
          dryTo - dryStart,
          frames - (dryTo - dryStart),
        );
      }
    } else {
      ch0.fill(0, 0, frames);
      if (ch1 !== ch0) ch1.fill(0, 0, frames);
    }
    this.fillEngineWindow(windowStart, windowEnd);
    engine.seek(this.windowFrames, rate);
    engine.process(0, frames);
    const notch = this.loopQuantum(time, rate, frames);
    this.fillMasterCoeffs(frames);
    const d0 = this.dryGainPrev;
    const w0 = this.wetGainPrev;
    const ds = (this.dryGain - d0) / frames;
    const ws = (this.wetGain - w0) / frames;
    for (let i = 0; i < frames; i++) {
      const dg = d0 + ds * i;
      const wg = w0 + ws * i;
      let l = ch0[i] * dg + engine.outL[i] * wg;
      let r = ch1[i] * dg + engine.outR[i] * wg;
      if (notch) {
        const gain =
          notch.fade > 0
            ? Math.min(1, Math.abs(notch.center - i) / notch.fade)
            : 1;
        l *= gain;
        r *= gain;
        if (notch.final && i >= notch.center) {
          l = 0;
          r = 0;
        }
      }
      const master = this.masterCoeff[i];
      ch0[i] = l * master;
      ch1[i] = r * master;
    }
    if (this.loopComplete) {
      this.audible = this.loopCompletion
        ? this.loopCompletion.frame
        : this.position;
      this.position = this.audible;
    } else {
      this.audible += rate * frames;
      this.position = this.loop
        ? Math.round(this.audible)
        : Math.min(Math.round(this.audible), this.frameCount);
    }
    this.rolledFrames += frames;
    for (let c = 0; c < 2; c++) {
      this.lastSample[c] =
        c < outputChannels.length ? outputChannels[c][frames - 1] : 0;
    }
    this.renderBeats(frames, rate, beatCursor);
    this.clicks.render(outputChannels, frames);
    this.advance(time, out, time + frames / this.sampleRate);
    out.consumed = frames;
    out.buffered = this.buffered;
    return out;
  }

  updateRateState(frames) {
    const wantWet = this.rateTarget !== 1 || this.transpose !== 0;
    if (!this.xfade) {
      if (
        wantWet &&
        this.bypass === "dry" &&
        this.rolledFrames >= WARMUP_OUT_FRAMES
      ) {
        this.xfade = {
          to: "wet",
          fromDry: this.dryGain,
          fromWet: this.wetGain,
          remaining: this.xfadeTotal,
        };
      } else if (!wantWet && this.bypass === "wet" && this.rateCurrent === 1) {
        this.xfade = {
          to: "dry",
          fromDry: this.dryGain,
          fromWet: this.wetGain,
          remaining: this.xfadeTotal,
        };
      }
    }
    let goal = this.rateTarget;
    if (this.bypass === "dry") goal = 1;
    if (this.xfade && this.xfade.to === "wet") goal = this.rateCurrent;
    if (this.xfade && this.xfade.to === "dry") goal = 1;
    if (goal !== this.rateGoal) {
      this.rateGoal = goal;
      this.rateFrom = this.rateCurrent;
      this.rateRampRemaining =
        this.rateCurrent === goal ? 0 : this.rateRampTotal;
    }
    if (this.rateRampRemaining > 0) {
      this.rateRampRemaining = Math.max(0, this.rateRampRemaining - frames);
      this.rateCurrent =
        this.rateRampRemaining === 0
          ? this.rateGoal
          : this.rateFrom +
            (this.rateGoal - this.rateFrom) *
              (1 - this.rateRampRemaining / this.rateRampTotal);
    }
    this.dryGainPrev = this.dryGain;
    this.wetGainPrev = this.wetGain;
    if (this.xfade) {
      this.xfade.remaining = Math.max(0, this.xfade.remaining - frames);
      const t = 1 - this.xfade.remaining / this.xfadeTotal;
      if (this.xfade.to === "wet") {
        this.dryGain = this.xfade.fromDry * (1 - t);
        this.wetGain = this.xfade.fromWet + (1 - this.xfade.fromWet) * t;
      } else {
        this.dryGain = this.xfade.fromDry + (1 - this.xfade.fromDry) * t;
        this.wetGain = this.xfade.fromWet * (1 - t);
      }
      if (this.xfade.remaining === 0) {
        this.bypass = this.xfade.to;
        this.dryGain = this.bypass === "dry" ? 1 : 0;
        this.wetGain = 1 - this.dryGain;
        this.xfade = null;
      }
    }
  }

  runWarmup(frames) {
    const engine = this.engine;
    const batch = frames * 8;
    let done = 0;
    while (this.warmupRemaining > 0 && done < batch) {
      const n = Math.min(frames, this.warmupRemaining);
      const rate = this.rateTarget;
      const cursor = this.audible - this.warmupRemaining * rate;
      const windowEnd = Math.round(cursor + rate * this.outLat + this.inLat);
      const windowStart = windowEnd - this.windowFrames;
      const needTo = this.loop
        ? windowEnd
        : Math.min(windowEnd, this.frameCount);
      if (needTo > this.ringEnd) this.fillRing(needTo);
      if (this.ringEnd < needTo) break;
      this.fillEngineWindow(windowStart, windowEnd);
      engine.seek(this.windowFrames, rate);
      engine.process(0, n);
      this.rolledFrames += n;
      this.warmupRemaining -= n;
      done += n;
    }
  }

  fillRing(until) {
    const cap = this.ringCap;
    while (this.ringEnd < until) {
      if (until - this.ringStart > cap) this.ringStart = until - cap;
      let chunk = Math.min(
        until - this.ringEnd,
        this.engineFillChunk,
        cap - (this.ringEnd - this.ringStart),
      );
      chunk = this.loop
        ? chunk
        : Math.min(chunk, this.frameCount - this.ringEnd);
      if (chunk <= 0) break;
      let take = chunk;
      for (const source of this.sources) take = Math.min(take, source.buffered);
      if (take <= 0) break;
      for (let i = 0; i < this.sources.length; i++) {
        this.sources[i].consumeInto(this.temp[i], take);
      }
      this.fillSourceCoeffs(take);
      const count = this.sources.length;
      const mixL = this.mixL;
      const mixR = this.mixR;
      for (let f = 0; f < take; f++) {
        let l = 0;
        let r = 0;
        for (let i = 0; i < count; i++) {
          const gL = this.coeffL[i][f];
          const gR = this.coeffR[i][f];
          const sample = this.temp[i][0][f];
          if (this.sources[i].channelCount === 1) {
            l += sample * gL;
            r += sample * gR;
          } else {
            l += sample * gL;
            r += this.temp[i][1][f] * gR;
          }
        }
        mixL[f] = l;
        mixR[f] = r;
      }
      const offset = wrap(this.ringEnd - this.ringBase, cap);
      const first = Math.min(take, cap - offset);
      this.ringL.set(mixL.subarray(0, first), offset);
      this.ringR.set(mixR.subarray(0, first), offset);
      if (take > first) {
        this.ringL.set(mixL.subarray(first, take), 0);
        this.ringR.set(mixR.subarray(first, take), 0);
      }
      this.ringEnd += take;
    }
  }

  copyFromRing(source, destination, destinationOffset, from, count) {
    const cap = this.ringCap;
    const offset = wrap(from - this.ringBase, cap);
    const first = Math.min(count, cap - offset);
    destination.set(source.subarray(offset, offset + first), destinationOffset);
    if (count > first)
      destination.set(
        source.subarray(0, count - first),
        destinationOffset + first,
      );
  }

  fillEngineWindow(windowStart, windowEnd) {
    const engine = this.engine;
    const width = this.windowFrames;
    engine.inL.fill(0, 0, width);
    engine.inR.fill(0, 0, width);
    const from = this.loop
      ? Math.max(windowStart, this.ringStart)
      : Math.max(windowStart, 0, this.ringStart);
    const to = this.loop
      ? Math.min(windowEnd, this.ringEnd)
      : Math.min(windowEnd, this.frameCount, this.ringEnd);
    if (to > from) {
      const offset = from - windowStart;
      const count = to - from;
      this.copyFromRing(this.ringL, engine.inL, offset, from, count);
      this.copyFromRing(this.ringR, engine.inR, offset, from, count);
    }
  }

  fillOutputSilence(outputChannels, from, count) {
    if (count <= 0) return;
    outputChannels[0].fill(0, from, from + count);
    if (outputChannels.length > 1)
      outputChannels[1].fill(0, from, from + count);
  }
}

// ---------------------------------------------------------------------------
// Worklet adapter

if (typeof AudioWorkletProcessor !== "undefined") {
  class PlayerProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const opts = (options && options.processorOptions) || {};
      const sampleRate = opts.sampleRate ?? 48000;
      const sources =
        Array.isArray(opts.sources) && opts.sources.length > 0
          ? opts.sources
          : [{ channelCount: opts.channelCount ?? 2 }];
      const sabs = Array.isArray(opts.sabs)
        ? opts.sabs
        : opts.sab
          ? [opts.sab]
          : [];
      let engine = null;
      if (opts.stretch && opts.stretch.wasmBytes) {
        const api = globalThis.StretchWasm;
        if (!api)
          throw new Error("stretch: core missing from the worklet bundle");
        engine = api.instantiateStretch(opts.stretch.wasmBytes);
        engine.configure(
          sampleRate,
          opts.stretch.maxFrames ?? api.STRETCH_MAX_FRAMES,
        );
      }
      this.core = new PlaybackCore({
        sampleRate,
        frameCount: opts.frameCount ?? 0,
        sources,
        engine,
        capacityFrames: opts.capacityFrames ?? 0,
      });
      sabs.forEach((sab, i) => this.core.attachShared(i, sab));
      if (typeof opts.metronomeVolume === "number") {
        this.core.setMetronomeVolume(opts.metronomeVolume);
      }
      if (Number.isFinite(opts.rate)) this.core.setRate(opts.rate);
      if (Number.isFinite(opts.transpose))
        this.core.setTranspose(opts.transpose);
      this.generation = 0;
      this.renderFrame = 0;
      this.lastBufferedReport = 0;
      if (engine) {
        const lat = engine.latencies();
        this.port.postMessage({
          type: "stretch-ready",
          inputLatency: lat.inputFrames,
          outputLatency: lat.outputFrames,
        });
      }
      this.port.onmessage = (event) => this.onMessage(event.data);
    }

    onMessage(message) {
      if (!message || typeof message !== "object") return;
      if (message.type === "channels") {
        const index = typeof message.source === "number" ? message.source : 0;
        const ok = this.core.enqueueChannels(index, message.channels);
        if (!ok) {
          this.port.postMessage({
            type: "chunk-dropped",
            frames: message.frames,
            source: index,
            generation: this.generation,
          });
        }
      } else if (message.type === "seek") {
        this.generation = Array.isArray(message.generations)
          ? message.generations.reduce((a, b) => Math.max(a, b), 0)
          : (message.generation ?? 0);
        this.core.seek(
          message.frame,
          message.generations ?? this.generation,
          message.audibleFrame,
          message.loop,
        );
        this.port.postMessage({ type: "flushed", generation: this.generation });
      } else if (message.type === "params") {
        this.core.setSourceParams(message.source, message);
      } else if (message.type === "master") {
        this.core.setMasterGain(message.gain);
      } else if (message.type === "rate") {
        this.core.setRate(message.value);
      } else if (message.type === "transpose") {
        this.core.setTranspose(message.value);
      } else if (message.type === "metronome") {
        this.core.setMetronomeVolume(message.volume);
        if (Array.isArray(message.beats)) this.core.setBeats(message.beats);
      } else if (message.type === "count-in") {
        this.core.startCountIn(message);
      } else if (message.type === "loop") {
        this.core.setLoop(message.loop);
      } else if (message.type === "pause") {
        this.core.pause();
      } else if (message.type === "resume") {
        this.core.resume();
      }
    }

    process(_inputs, outputs) {
      const time =
        typeof globalThis.currentTime === "number" ? globalThis.currentTime : 0;
      const outputChannels = outputs[0] ?? [];
      const result = this.core.process(time, outputChannels);
      const frames = outputChannels.length > 0 ? outputChannels[0].length : 128;
      const blockStart = Math.round(time * this.core.sampleRate);
      this.renderFrame = blockStart + frames;
      if (result.anchor) {
        const message = {
          type: "anchor",
          frame: result.anchor.frame,
          time: result.anchor.time,
          paused: result.anchor.paused,
          rate: result.anchor.rate ?? 1,
          generation: this.generation,
        };
        if (result.anchor.wrap === true) message.wrap = true;
        this.port.postMessage(message);
      }
      if (result.underrun)
        this.port.postMessage({
          type: "underrun",
          generation: this.generation,
        });
      if (result.ended)
        this.port.postMessage({ type: "ended", generation: this.generation });
      if (result.loopComplete) {
        const anchor = result.anchor;
        this.port.postMessage({
          type: "loop-complete",
          frame: anchor ? anchor.frame : this.core.position,
          time: anchor ? anchor.time : 0,
          generation: this.generation,
        });
      }
      if (result.countInDone) {
        this.port.postMessage({
          type: "count-in-done",
          generation: this.generation,
        });
      }
      // ~10 Hz buffer report for the transport's prefetch loop.
      if (
        this.renderFrame - this.lastBufferedReport >=
        this.core.sampleRate / 10
      ) {
        this.lastBufferedReport = this.renderFrame;
        this.port.postMessage({
          type: "buffered",
          frames: this.core.buffered,
          queuedFrames: this.core.queued,
          capacityFrames: this.core.capacity,
          generation: this.generation,
        });
      }
      return true;
    }
  }

  registerProcessor("basseparate-player", PlayerProcessor);
}
