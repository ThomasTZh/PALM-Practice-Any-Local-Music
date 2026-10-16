# Stretch WASM build manifest (M2.9)

Built 2026-10-16T16:53:19.192Z by `build.mjs`.

## Pinned inputs

| input               | pin                                                                                      |
| ------------------- | ---------------------------------------------------------------------------------------- |
| Emscripten SDK      | 4.0.23 (`third_party/emsdk`, gitignored)                                                 |
| signalsmith-stretch | `a670068d9aeb64913331d5cc29337b19a457a7df`                                               |
| signalsmith-linear  | `de55e6a50ffcf6f8f43f649692d94691c7025151` (tag 0.6.4)                                   |
| wrapper source      | `1f845509498ff1deafef533d82b74c8d2860ec899766a2bfad245d3b0e390d26` (stretch_wrapper.cpp) |

## Artifacts (SHA-256)

| artifact                 | SHA-256                                                            |
| ------------------------ | ------------------------------------------------------------------ |
| dist/stretch-scalar.js   | `7a2ee168f39a1596ab267ca855970ae8fa09352477e3ee46c0a6ac12685a5a89` |
| dist/stretch-scalar.wasm | `cab0c104e81f8e2e97cf3ed2dfc074f4824046deae33cd0841913517e3b050e7` |
| dist/stretch-simd.js     | `1b21e95ed560162b9243ff922bcff9d7bebd3add638ca0141ba123fb7f91272e` |
| dist/stretch-simd.wasm   | `def232e79eb1588c42696dbac5aedc08df0ddaa3fb34c86de35b2dca37c8bf99` |

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
(2 × seekFrames + 2 × maxFrames floats; seekFrames = 8640 @48k →
≈100 KiB) plus the engine state must fit, so the audio callback can
never trigger a heap grow.
