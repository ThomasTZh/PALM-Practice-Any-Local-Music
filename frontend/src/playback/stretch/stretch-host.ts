/**
 * stretch-host.ts — typed main-thread facade for the stretch WASM core
 * (M2.9, spec §11).
 *
 * The implementation lives in `stretch-worklet.js` (plain script, no
 * imports/exports): it is concatenated into the AudioWorklet blob, so
 * the main thread and the worklet execute the SAME code (no drift).
 * Importing it here for its side effect attaches
 * `globalThis.StretchWasm`; this file re-exports the surface with types
 * (see `stretch-worklet.d.ts`).
 *
 * The bundled artifacts (`dist/stretch-{scalar,simd}.wasm`, built by
 * `build.mjs` from `stretch_wrapper.cpp` — see `BUILD.md`) are
 * instantiated **directly** with `WebAssembly.Module`/`Instance`: no
 * emscripten glue, no fetch (a blob-URL worklet has no base for
 * relative fetches, and Node has no toolchain on PATH, spec §11.3.11).
 *
 * The WASM import surface is the emscripten runtime stub set
 * (`{a: {a: fd_write, b: resize_heap, c: abort}}`). Heap growth is a
 * hard error: the memory is fixed (`ALLOW_MEMORY_GROWTH=0`, spec §14.7).
 *
 * Emscripten mangles the export names (`d`–`r`); the mapping is
 * validated at load time and `BUILD.md` records the exact artifact
 * hashes it applies to.
 */

import './stretch-worklet.js'
import type { StretchEngineLike, StretchLatencies, StretchWasmApi } from './stretch-worklet'

const api: StretchWasmApi = globalThis.StretchWasm

export const STRETCH_MAX_FRAMES = api.STRETCH_MAX_FRAMES
export const STRETCH_CHANNELS = api.STRETCH_CHANNELS
export const STRETCH_MEMORY_BYTES = api.STRETCH_MEMORY_BYTES

export type { StretchLatencies }

/** A configured stretch engine (the same instance the worklet drives). */
export type StretchEngine = StretchEngineLike

/** Instantiate the engine from a bundled artifact (synchronous). */
export const instantiateStretch = api.instantiateStretch

/** True when the runtime supports WebAssembly SIMD (spec §11.3.7). */
export const simdSupported = api.simdSupported
