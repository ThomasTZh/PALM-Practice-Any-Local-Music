# Stretch WASM build manifest (t2)

Built 2026-10-31T18:43:23.814Z by `build.mjs` from `web/src/player/stretch`.

## Pinned inputs

| input | pin |
| --- | --- |
| Emscripten SDK | 4.0.23 (`third_party/emsdk`, gitignored) |
| signalsmith-stretch | `a670068d9aeb64913331d5cc29337b19a457a7df` |
| signalsmith-linear | `de55e6a50ffcf6f8f43f649692d94691c7025151` (tag 0.6.4) |
| wrapper source | `b5d48d83b414c86eb913413a98a5c8d881094e337b15b5cdcd157e330d4780d1` (stretch_wrapper.cpp) |

## Artifacts (SHA-256)

| artifact | SHA-256 |
| --- | --- |
| dist/stretch-scalar.js | `83248bee9ec5dc9e7612b466f60f10a4942e2c97d25fb60543e0c4fa8b144e4c` |
| dist/stretch-scalar.wasm | `dc0df91ca445e4573a14aaef81ba4d7b0a8a71143daca462e1b89316c88ad182` |
| dist/stretch-simd.js | `a2fbcf01f63a5bf6fbe5be06de157177724e1e14a5c38f6e2b825313fd65bc8d` |
| dist/stretch-simd.wasm | `549e8f889cc0c327345b95e2d16b387149eec85e29a595219bf4a72eeaf6c9f8` |

## WASM export map (both variants)

Emscripten minifies export names; `stretch-worklet.js` resolves each API
from this table (validated at load time). Rebuilding the wrapper requires
refreshing the table in the same commit.

| API | WASM export |
| --- | --- |
| `stretch_configure` | `f` |
| `stretch_input_latency` | `g` |
| `stretch_output_latency` | `h` |
| `stretch_window_length` | `i` |
| `stretch_seek` | `j` |
| `stretch_process` | `k` |
| `stretch_set_rate` | `l` |
| `stretch_set_rate_now` | `m` |
| `stretch_effective_rate` | `n` |
| `stretch_set_transpose` | `o` |
| `stretch_reset` | `p` |
| `stretch_pool_offset` | `q` |
| `stretch_pool_input_frames` | `r` |

The first function export (`e`) is the static-initializer
start function; `d` is the fixed 2 MiB memory.

## Build flags

```
em++ stretch_wrapper.cpp
  -std=c++17 -O3 -ffast-math -fno-finite-math-only -fno-exceptions -fno-rtti
  -sMODULARIZE=1 -sEXPORT_NAME=StretchWasm<Variant>
  -sENVIRONMENT=web,worker,shell
  -sNO_EXIT_RUNTIME=1 -sFILESYSTEM=0
  -sINITIAL_MEMORY=2mb -sALLOW_MEMORY_GROWTH=0
  -sSTRICT=1 -sDYNAMIC_EXECUTION=0 --closure=0
  -sEXPORTED_FUNCTIONS=_stretch_*
  (SIMD variant adds -msimd128)
```

The artifacts are committed so a checkout runs without a compiler. The
repository's global `dist/` ignore covers this directory, so refresh the
committed copies with `git add -f web/src/player/stretch/dist` after a rebuild.

Memory is fixed at 2 MiB (no growth): the pre-allocated I/O pool
(2 × windowFrames + 2 × maxFrames floats; windowFrames = 7200 @48k,
maxFrames = 4096 → ≈88 KiB) plus the engine state must fit, so the
audio callback can never trigger a heap grow.
