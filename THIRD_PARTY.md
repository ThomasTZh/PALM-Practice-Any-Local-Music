# Third-party components

This repository contains only original code. The components below are
installed from their own release channels or compiled from MIT sources at build
time; none of their source trees, binaries, model weights or tools are
committed here. `LICENSE` covers the original files only.

## Runtime components

| Component | Version / revision | Licence (upstream) | In this repository | Role |
| --- | --- | --- | --- | --- |
| Demucs | 4.1.0 | MIT (code) | No | Stem separation |
| htdemucs_ft weights | four checkpoints, sizes and SHA-256 pinned in `analysis/checkpoints.json` | no separate weight licence; research use (see below) | No | Separation model |
| Torch | 2.9.1 | BSD-3-Clause | No | Demucs runtime, isolated environment |
| MSST | 0.1.0 | MIT (code) | No | SCNet / BS-RoFormer inference environment |
| SCNet XL IHF weights | checkpoint 214,063,778 B + config 5,906 B, pinned in `analysis/models.json` | no separate weight licence; research use (see below) | No | Optional four-stem model |
| BS-RoFormer-SW weights | checkpoint 699,412,152 B + yaml 4,613 B, pinned in `analysis/models.json` | unknown upstream licence; private use only | No | Optional six-stem model |
| Sonic Visualiser / Piper host | 5.2.1 AppImage, downloaded by the installer | GPL-2.0-or-later | No | Runs Vamp plugins |
| Vamp plugin SDK | local build | MIT-style permissive licence, see upstream `COPYING` | No | Plugin host interface |
| NNLS-Chroma / Chordino | Vamp Plugin Pack 2.0 | GPL-2.0-or-later | No | Chord recognition |
| QM Key Detector, QM Bar and Beat Tracker | Vamp Plugin Pack 2.0 | GPL-2.0-or-later | No | Key, beats and bars |
| BeatRoot | Vamp Plugin Pack 2.0 | GPL-2.0-or-later | No | Alternative beat tracker |
| Signalsmith Stretch | commit `a670068d9aeb64913331d5cc29337b19a457a7df` | MIT | Compiled WASM artifacts only, with the original wrapper | Time-stretch engine |
| Signalsmith Linear | commit `de55e6a50ffcf6f8f43f649692d94691c7025151` (0.6.4) | MIT | Compiled WASM artifacts only | FFT support for Stretch |
| Emscripten SDK | 4.0.23 | MIT / NCSA | No (build tool) | Builds the stretch WASM |
| Python dependencies | see `pyproject.toml` and `analysis/uv.lock` | per package | No | Service and tests |
| JavaScript dependencies | see `web/package.json` | per package | No | UI and tests |
| FFmpeg / FFprobe | system package, 8.1.3 during development | LGPL/GPL depending on the build | No | Decoding and probing |
| CPython (standalone) | 3.11.15+20260728 | PSF-2.0 | Bundled runtime in the portable asset | Runs PALM and setup |
| uv | 0.12.0 | Apache-2.0 or MIT | Bundled in the portable asset | Creates the analysis environments |

Pinned download URLs, versions and SHA-256 values are in
`THIRD_PARTY_DOWNLOADS.md`; the installer enforces them.

## Installing the external components

```sh
make install-tools                       # system checks, Sonic Visualiser, Vamp pack
make install-tools ACCEPT_MODEL_TERMS=1  # also the htdemucs_ft weights
```

The installer never writes third-party files into git. It writes only below
the ignored `storage/` and `models/` directories, verifies every download
against a pinned hash, and prints the upstream licence and credit information.
It does not bundle or redistribute any of these components.

## Demucs weights

The Demucs code is MIT. The pretrained `htdemucs_ft` weights are a separate
artifact: the upstream repository does not state a separate weight licence, and
the author has described the weights as research use. They were trained on
MUSDB18-HQ, which is a research corpus. The installer downloads them only after
the explicit `--accept-model-terms` flag (or typing `accept` at the prompt) and
does not redistribute them. This project cannot grant a licence for the
weights; obtain one from the rights holders if you need commercial use.

## Optional separation weights

`analysis/models.json` pins the optional SCNet XL IHF and BS-RoFormer-SW
checkpoints and configs by size and SHA-256. They are downloaded only by an
explicit `make models-install ID=<id>` and are never committed. SCNet XL IHF
comes from the MSST v1.0.15 release; the code is MIT, but the weights have no
separate licence and are used for research (ICASSP 2024). BS-RoFormer-SW comes
from the `FractalSurfer/BS-RoFormer-SW-6stem` mirror of the deleted
`enerjazzer/BS-ROFO-SW-Fixed` repository; the mirror declares no licence, so
the weights are used privately and are not redistributed. Obtain a licence from
the rights holders for any other use.

## GPL boundary

Sonic Visualiser, Piper, the Vamp plugin pack and the individual Vamp plugins
are GPL-family software. They are separate programs, invoked as subprocesses;
they are not linked into this repository's code and are not distributed with
it. If you redistribute those tools, you must comply with their licences,
including source and notice obligations. The MIT licence for this repository
does not apply to them.

## Compiled stretch artifacts

`web/src/player/stretch/dist/` contains the scalar and SIMD WebAssembly
modules built from Signalsmith Stretch and Signalsmith Linear (both MIT) with
this repository's `stretch_wrapper.cpp`. The exact input commits, toolchain
version and artifact SHA-256 values are recorded in
`web/src/player/stretch/BUILD.md`; the upstream MIT notice is preserved in
`web/src/player/stretch/NOTICES-signalsmith.md`. The artifacts are committed so
the application runs without a compiler. To rebuild them, follow
`web/src/player/stretch/build.mjs`, which expects a local Emscripten 4.0.23 and
clones of the two Signalsmith projects at the pinned commits.

The compiled modules were produced with Emscripten 4.0.23 (MIT and
University of Illinois/NCSA licences) and may include portions of musl libc
(MIT) and compiler-rt (Apache-2.0 WITH LLVM-exception). The full licences are
in `licenses/EMSCRIPTEN.txt`, `licenses/MUSL.txt` and
`licenses/COMPILER-RT.txt`; the artifacts are unmodified output of that
toolchain.

## Credits

- Demucs and the htdemucs_ft weights: Simon Rouard, Francisco Massa and
  Alexandre Defossez (Meta AI Research),
  https://github.com/facebookresearch/demucs.
- Chordino and NNLS-Chroma: Matthias Mauch and contributors,
  https://github.com/c4dm/nnls-chroma.
- QM Key Detector (Katy Noland, Christian Landone) and QM Bar and Beat Tracker
  (Matthew Davies, Christian Landone, Chris Cannam), Queen Mary University of
  London, https://code.soundsoftware.ac.uk/projects/qm-vamp-plugins.
- BeatRoot: Simon Dixon, https://code.soundsoftware.ac.uk/projects/beatroot-vamp.
- Sonic Visualiser, Piper and the Vamp plugin SDK: Chris Cannam and Queen Mary
  University of London, https://www.sonicvisualiser.org/.
- Signalsmith Stretch and Linear: Geraint Luff / Signalsmith Audio, MIT.
- Emscripten: the Emscripten authors, MIT/NCSA.
- FastAPI, Starlette, Pydantic, NumPy, React, Vite and TypeScript: see the
  dependency manifests and each project's upstream licence.
- HoliznaCC0 for the CC0 recording “Eat” used in the screenshot, and OpenGameArt
  for hosting the Funk Collection: https://opengameart.org/content/funk-collection.

## Obtain the excluded components

- Demucs and the `htdemucs_ft` weights: `make install-tools ACCEPT_MODEL_TERMS=1`,
  or place the four `.th` files and the preset YAML in `models/htdemucs_ft`
  yourself. The runner verifies every file against `analysis/checkpoints.json`.
- Vamp plugin pack and Sonic Visualiser / Piper: `make install-tools`, or
  install the upstream builds and point the application at them as described in
  `docs/troubleshooting.md`.
- Python and JavaScript dependencies: `uv sync`, `pnpm install`, and
  `(cd analysis && uv sync)`.

No credentials, datasets, recordings or model weights are included in this
repository.
