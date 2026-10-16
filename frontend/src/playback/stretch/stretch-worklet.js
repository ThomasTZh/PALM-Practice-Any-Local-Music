/**
 * stretch-worklet.js — the stretch WASM core as a plain script (M2.9,
 * spec §11).
 *
 * No imports, no exports, on purpose: the browser loads this file into
 * the AudioWorklet by concatenation with `worklet-processor.js` into a
 * Blob-URL module (a blob URL has no base for relative imports, so the
 * worklet cannot `import` it), and the unit tests import it for its side
 * effect. Both paths land in the same `globalThis.StretchWasm`
 * namespace, so the worklet and the main thread share ONE
 * implementation (no drift). `stretch-host.ts` is the typed main-thread
 * facade over this file.
 *
 * The bundled artifacts (`dist/stretch-{scalar,simd}.wasm`, built by
 * `build.mjs` from `stretch_wrapper.cpp` — see `BUILD.md`) are
 * instantiated **directly** with `WebAssembly.Module`/`Instance`. The
 * emscripten glue is not executed: with `-sFILESYSTEM=0` its wasm-loading
 * path has no reader in the AudioWorklet (which the glue classifies as
 * "shell") or in Node, and a blob-URL worklet has no base for relative
 * fetches. Direct instantiation is the same code path everywhere —
 * main thread (variant selection, tests), AudioWorklet (blob-URL module
 * script), and Node (unit tests with no toolchain on PATH, spec
 * §11.3.11).
 *
 * The WASM import surface is the emscripten runtime stub set
 * (`{a: {a: fd_write, b: resize_heap, c: abort}}`). Heap growth is a
 * hard error: the memory is fixed (`ALLOW_MEMORY_GROWTH=0`, spec §14.7).
 *
 * Emscripten mangles the export names (`d`–`r`); the mapping below is
 * validated at load time and `BUILD.md` records the exact artifact
 * hashes it applies to.
 */

;(function () {
  const STRETCH_MAX_FRAMES = 4096
  const STRETCH_CHANNELS = 2
  const STRETCH_MEMORY_BYTES = 2 * 1024 * 1024

  const IMPORTS = {
    a: {
      // fd_write: the audio thread never writes streams.
      a: () => 0,
      // resize_heap: memory is fixed; growth must never be requested.
      b: () => {
        throw new Error('stretch: memory growth is disabled')
      },
      c: () => {
        throw new Error('stretch: wasm abort')
      },
    },
  }

  function toBytes(wasmBytes) {
    return wasmBytes instanceof Uint8Array ? wasmBytes : new Uint8Array(wasmBytes)
  }

  /**
   * True when the runtime supports WebAssembly SIMD. The probe is a
   * minimal module whose only body is `i8x16.const 0`;
   * `WebAssembly.validate` accepts it only with SIMD enabled (spec
   * §11.3.7: SIMD is used only after capability detection).
   */
  function simdSupported() {
    const probe = new Uint8Array([
      0x00,
      0x61,
      0x73,
      0x6d,
      0x01,
      0x00,
      0x00,
      0x00, // \0asm v1
      0x01,
      0x04,
      0x01,
      0x60,
      0x00,
      0x01,
      0x7b, // type: () -> i8x16
      0x03,
      0x02,
      0x01,
      0x00, // func[0]: type 0
      0x0a,
      0x06,
      0x01,
      0x04,
      0x00,
      0xfd,
      0x0c,
      0x00,
      0x0b, // body: i8x16.const 0
    ])
    return WebAssembly.validate(probe)
  }

  /**
   * A configured stretch engine. Construct with
   * `instantiateStretch(wasmBytes)`, then `configure()` for the project
   * sample rate. All methods are synchronous and audio-thread safe once
   * configured (no I/O, no allocation outside the fixed WASM heap).
   */
  class StretchEngine {
    constructor(exports) {
      const mem = exports.d
      if (!(mem instanceof WebAssembly.Memory)) {
        throw new Error('stretch: artifact has no memory export')
      }
      if (mem.buffer.byteLength !== STRETCH_MEMORY_BYTES) {
        throw new Error(
          `stretch: unexpected memory size ${mem.buffer.byteLength} ` +
            `(expected ${STRETCH_MEMORY_BYTES})`,
        )
      }
      const fn = (name) => {
        const f = exports[name]
        if (typeof f !== 'function') {
          throw new Error(`stretch: artifact is missing export ${name}`)
        }
        return f
      }
      this.mem = mem
      this.fnConfigure = fn('f')
      this.fnInputLatency = fn('g')
      this.fnOutputLatency = fn('h')
      this.fnInputDemand = fn('i')
      this.fnProcess = fn('j')
      this.fnSetRate = fn('k')
      this.fnEffectiveRate = fn('l')
      this.fnReset = fn('m')
      this.fnFlushTail = fn('n')
      this.fnSeekLength = fn('o')
      this.fnOutputSeek = fn('p')
      this.fnPoolOffset = fn('q')
      this.fnPoolInputFrames = fn('r')
      const start = exports.e
      if (typeof start !== 'function') {
        throw new Error('stretch: artifact is missing the start export')
      }
      start() // static initializers
      this.maxFrames = 0
      this.seekFrames = 0
      this.configured = false
      /** In regions: `inL`/`inR`, each `seekFrames` floats (JS writes). */
      this.inL = null
      this.inR = null
      /** Out regions: `outL`/`outR`, each `maxFrames` floats. */
      this.outL = null
      this.outR = null
    }

    /** Configure for `sampleRate` (stereo). Must be called once, before use. */
    configure(sampleRate, maxFrames = STRETCH_MAX_FRAMES) {
      this.fnConfigure(STRETCH_CHANNELS, sampleRate, maxFrames)
      this.maxFrames = maxFrames
      const base = this.mem.buffer
      // The wrapper reports where its I/O pool actually lives in the
      // fixed heap; the layout is [inL | inR | outL | outR] with the
      // input regions sized seekFrames (a full priming buffer at 2x) and
      // the output regions maxFrames.
      const pool = this.fnPoolOffset()
      if (pool < 4) {
        throw new Error('stretch: wrapper reported no I/O pool')
      }
      this.seekFrames = this.fnPoolInputFrames()
      if (this.seekFrames < maxFrames) {
        throw new Error('stretch: input region smaller than maxFrames')
      }
      this.inL = new Float32Array(base, pool, this.seekFrames)
      this.inR = new Float32Array(base, pool + this.seekFrames * 4, this.seekFrames)
      this.outL = new Float32Array(base, pool + 2 * this.seekFrames * 4, maxFrames)
      this.outR = new Float32Array(base, pool + (2 * this.seekFrames + maxFrames) * 4, maxFrames)
      this.configured = true
    }

    assertConfigured() {
      if (!this.configured) {
        throw new Error('stretch: engine not configured')
      }
    }

    latencies() {
      this.assertConfigured()
      return {
        inputFrames: this.fnInputLatency(),
        outputFrames: this.fnOutputLatency(),
      }
    }

    /** Input frames the engine will want for `outputFrames` of output. */
    inputDemand(outputFrames) {
      this.assertConfigured()
      return this.fnInputDemand(outputFrames)
    }

    /**
     * Consume `inputFrames` from `inL`/`inR` (JS copies the mixed stereo
     * in first) and write `outputFrames` into `outL`/`outR`. Returns the
     * consumed count. The worklet calls this only with the exact demanded
     * count (short supplies take the underrun path instead).
     */
    process(inputFrames, outputFrames) {
      this.assertConfigured()
      return this.fnProcess(inputFrames, outputFrames)
    }

    /** Set the target playback rate (clamped to 0.25…2.0; ≈50 ms ramp). */
    setRate(rate) {
      this.assertConfigured()
      this.fnSetRate(rate)
    }

    /** The currently ramped effective rate. */
    effectiveRate() {
      this.assertConfigured()
      return this.fnEffectiveRate()
    }

    /** Fresh engine state (seek / reload); the next output starts silent. */
    reset() {
      this.assertConfigured()
      this.fnReset()
    }

    /** Read the engine's remaining tail (no further input). */
    flushTail(maxOutputFrames) {
      this.assertConfigured()
      return this.fnFlushTail(maxOutputFrames)
    }

    /**
     * Input frames the engine needs to prime at the current effective
     * rate (inputLatency + rate*outputLatency; 5760 @1x/48k).
     */
    seekLength() {
      this.assertConfigured()
      return this.fnSeekLength()
    }

    /**
     * Prime the engine from `inL`/`inR[0..inFrames)` so the first
     * `process()` output is aligned to `inL[0]` (canonical engine usage;
     * the caller silence-pads the tail on underrun). Internally resets
     * the engine, so call it at start and after every seek.
     */
    outputSeek(inFrames) {
      this.assertConfigured()
      this.fnOutputSeek(inFrames)
    }
  }

  /** Instantiate the engine from a bundled artifact (synchronous). */
  function instantiateStretch(wasmBytes) {
    const module = new WebAssembly.Module(toBytes(wasmBytes))
    const instance = new WebAssembly.Instance(module, IMPORTS)
    return new StretchEngine(instance.exports)
  }

  globalThis.StretchWasm = {
    STRETCH_MAX_FRAMES,
    STRETCH_CHANNELS,
    STRETCH_MEMORY_BYTES,
    simdSupported,
    StretchEngine,
    instantiateStretch,
  }
})()
