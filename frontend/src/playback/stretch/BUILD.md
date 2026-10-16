# Stretch WASM build manifest (M2.9)

Built 2026-10-16T19:33:43.829Z by `build.mjs`.

## Pinned inputs

| input               | pin                                                                                      |
| ------------------- | ---------------------------------------------------------------------------------------- |
| Emscripten SDK      | 4.0.23 (`third_party/emsdk`, gitignored)                                                 |
| signalsmith-stretch | `a670068d9aeb64913331d5cc29337b19a457a7df`                                               |
| signalsmith-linear  | `de55e6a50ffcf6f8f43f649692d94691c7025151` (tag 0.6.4)                                   |
| wrapper source      | `5f7b3cb411cb26959db3de21cb9defd676301f4a545504ff2fb2f823a47dea45` (stretch_wrapper.cpp) |

## Artifacts (SHA-256)

| artifact                 | SHA-256                                                            |
| ------------------------ | ------------------------------------------------------------------ |
| dist/stretch-scalar.js   | `7c4ae9e50e13def61575d2d4d67b947d6e9477124410398e7b67c6d1594b32ea` |
| dist/stretch-scalar.wasm | `07eef818133b27e292d6bd57d6372c696a2138edafa6b7bdcca9a8ee2141b18e` |
| dist/stretch-simd.js     | `70a53006018d5e480eb55c648d35a0b54c3e7d916ad79ce24232ee4ebe791ab9` |
| dist/stretch-simd.wasm   | `d5020940a29fe757285d6bbf0cfe7fcef4480c0f18ee98ee465a5e437590a694` |

## Build flags

```
em++ stretch_wrapper.cpp
  -std=c++17 -O3 -ffast-math -fno-exceptions -fno-rtti
  -sMODULARIZE=1 -sEXPORT_NAME=StretchWasm<Variant>
  -sENVIRONMENT=web,worker,shell
  -sNO_EXIT_RUNTIME=1 -sFILESYSTEM=0
  -sINITIAL_MEMORY=2mb -sALLOW_MEMORY_GROWTH=0
  -sSTRICT=1 -sDYNAMIC_EXECUTION=0 --closure=0
  -sEXPORTED_FUNCTIONS=_stretch_*
  (SIMD variant adds -msimd128)
```

Memory is fixed at 2 MiB (no growth): the pre-allocated I/O pool
(2 × windowFrames + 2 × maxFrames floats; windowFrames = 7200 @48k,
maxFrames = 4096 → ≈88 KiB) plus the engine state must fit, so the
audio callback can never trigger a heap grow.
