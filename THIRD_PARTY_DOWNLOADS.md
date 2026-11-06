# Third-party downloads

The repository contains only original code. None of the files below are
committed; `make install-tools` fetches them from their official release
channels into the ignored `storage/` and `models/` directories, verifies every
byte against a pinned SHA-256 value, and never writes them into git.

The MIT licence in `LICENSE` covers the original files only. It does not cover
the downloads, the GPL tools, or the Demucs weights.

## Runtime downloads

| Component | Version | Upstream URL | SHA-256 | Licence | Install path |
| --- | --- | --- | --- | --- | --- |
| Sonic Visualiser AppImage | 5.2.1 | https://github.com/sonic-visualiser/sonic-visualiser/releases/download/sv_v5.2.1/SonicVisualiser-5.2.1-x86_64.AppImage | `e31e7b970db7a9d6e5943c050c0a06c193d2c3fd4a82b6283aa08a9dc798599c` | GPL-2.0-or-later | `storage/tools/sv/squashfs-root` |
| Vamp Plugin Pack Linux AppImage | 2.0 | https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/v2.0/vamp-plugin-pack-installer-2.0 | `e8ed873f6e7dbdf8e11e61bd2fbc54f63469ff7c4a449c25a0fa14b52c42126f` | AGPL-3.0 for the pack; individual plugins GPL/AGPL | `storage/tools/plugins` and `storage/tools/vamp-plugins` |
| Demucs `htdemucs_ft` checkpoint | 4.1.0 release | https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/f7e0c4bc-ba3fe64a.th | `ba3fe64ae8ef66ac9a4857222ce48efbdc5eb3ad375cb79dd13debee5aaa4066` | see the weights notice below | `models/htdemucs_ft/` |
| Demucs `htdemucs_ft` checkpoint | 4.1.0 release | https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/d12395a8-e57c48e6.th | `e57c48e6b0e38af4f7118d7bd08c49f0a0c0edf7d09143bdd902ea0d237303e6` | see below | `models/htdemucs_ft/` |
| Demucs `htdemucs_ft` checkpoint | 4.1.0 release | https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/92cfc3b6-ef3bcb9c.th | `ef3bcb9c8b40d14ae5d51b6db2587339cc12c6b77c0be151ce6d69002e087bf2` | see below | `models/htdemucs_ft/` |
| Demucs `htdemucs_ft` checkpoint | 4.1.0 release | https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th | `f3cf25b222c4eed7cd49dd8b2c9597d50c18bd154090f7b919cfa5f93cf22c49` | see below | `models/htdemucs_ft/` |
| Demucs preset YAML | commit `b1ea86542ca11d7695cba4238909f461752283b5` | https://raw.githubusercontent.com/facebookresearch/demucs/b1ea86542ca11d7695cba4238909f461752283b5/demucs/remote/htdemucs_ft.yaml | `69470b8c1bbd674437b51bc9fb491327a10ab0396b702c93389b9cf750016346` | MIT (config file) | `models/htdemucs_ft/htdemucs_ft.yaml` |

Each checkpoint is 84,141,271 bytes. The model directory must contain exactly
these four checkpoints and the preset; `analysis/separate_track.py` verifies
size and SHA-256 before loading and refuses anything else.

### Optional model downloads

`make models-install ID=<id>` fetches these into the ignored
`models/<id>/` directory, verifies size and SHA-256 against
`analysis/models.json`, and publishes atomically. `make models-verify` checks
them offline. They are not downloaded by `make bootstrap` or the default gate.

| Component | Version | Upstream URL | SHA-256 | Licence | Install path |
| --- | --- | --- | --- | --- | --- |
| SCNet XL IHF checkpoint | MSST v1.0.15 | https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.15/model_scnet_ep_36_sdr_10.0891.ckpt | `ac25975f0f5704f3d1a3c3c251505b7a0f417a22eafe82773440ee4f7e14b74f` | no separate weight licence; research use | `models/scnet-xl-ihf/` |
| SCNet XL IHF config | MSST v1.0.15 | https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.15/config_musdb18_scnet_xl_more_wide_v5.yaml | `54ddcb8aeeae85c8d0e148741e7d87b0fbd38bd21cffa5d59ba124fe1e672f40` | MIT (MSST config) | `models/scnet-xl-ihf/` |
| BS-RoFormer-SW checkpoint | mirror commit `2b98254` | https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem/resolve/main/BS-Rofo-SW-Fixed.ckpt | `24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e` | unknown upstream licence; private use only | `models/bs-roformer-sw/` |
| BS-RoFormer-SW yaml | mirror commit `2b98254` | https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem/resolve/main/BS-Rofo-SW-Fixed.yaml | `f9fada9f94e5ba2d2e4600196299459294bc5f532b314c209cc156ac63e4329b` | unknown upstream licence; private use only | `models/bs-roformer-sw/` |
| MSST package | 0.1.0 | PyPI `msst[bs-roformer]` | pinned by `analysis-models/uv.lock` | MIT (code) | `analysis-models/.venv` |

Sizes: SCNet checkpoint 214,063,778 B and config 5,906 B; BS-RoFormer-SW
checkpoint 699,412,152 B and yaml 4,613 B.

### Demucs weights notice

The Demucs code is MIT. The pretrained weights are a separate artifact; the
upstream repository does not state a separate weight licence, and the author
has described them as research use. They were trained on MUSDB18-HQ, a
research corpus. The installer therefore downloads them only after the explicit
`--accept-model-terms` flag (or typing `accept` at the prompt), prints this
notice, and does not redistribute them. If you need a commercial licence,
obtain it from the rights holders; this project cannot grant one.

### Vamp plugin libraries

The pack installer embeds the plugin libraries. The installer extracts the
following three libraries, which the application needs, and installs the full
carved set under `storage/tools/plugins`:

| Plugin | Carved file | SHA-256 | Licence |
| --- | --- | --- | --- |
| NNLS-Chroma / Chordino | `embed-07-8888130.so` | `2908cb28c59c01330efd1bcb13300c7567b995d867e5ec796b55de5830e564ed` | GPL-2.0-or-later |
| QM Key Detector and Bar and Beat Tracker | `embed-12-10378903.so` | `f666669739f9645d84909f2c36f3bd2c5a60822dbd9804ac0daa316ab21c7275` | GPL-2.0-or-later |
| BeatRoot | `embed-02-1291431.so` | `05caf41777c4a68a4b53a0ae2e32de72926bf0891ea5c48d043d76aa6a42e46d` | GPL-2.0-or-later |

The full set of 23 carved libraries and their hashes is pinned in
`scripts/install_tools.py`. Redistributing the pack or the libraries is
governed by their own licences; this repository does not do so.

## Screenshot input

| Asset | Source | Licence | Distribution |
| --- | --- | --- | --- |
| “Eat” by HoliznaCC0, track 01 of the Funk Collection | https://opengameart.org/content/funk-collection | CC0 1.0 | Not distributed; only the UI screenshot is committed |

The screenshot in `assets/screenshot.png` depicts this CC0 recording. No audio
file is stored in the repository; the credit is kept in `assets/README.md` for
provenance.

## Bundled portable runtime

The portable assets include a pinned Python runtime and `uv`. They are
downloaded during the build with SHA-256 verification; they are not model or
tool downloads.

| Component | Version | Upstream URL | SHA-256 | Licence | Install path |
| --- | --- | --- | --- | --- | --- |
| CPython standalone | 3.11.15+20260728 | https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.11.15%2B20260728-x86_64-unknown-linux-gnu-install_only.tar.gz | `2db18c7bb3a47e32ff41727abd1bb5f158a17d8681931770abf0ba911f5b6580` | PSF-2.0 | `python/` |
| uv | 0.12.0 | https://github.com/astral-sh/uv/releases/download/0.12.0/uv-x86_64-unknown-linux-gnu.tar.gz | `eaf842262aa1c418d8ecc5605f02ee1ebfd369124fa48548e85f9481a47831a9` | Apache-2.0 or MIT | `bin/uv` |

The pinned list is authoritative in `packaging/build-manifest.toml`.

## Toolchain prerequisites

The installer checks these and prints installation instructions; it does not
bundle or silently install them.

| Tool | Version used | Official source | Distribution package |
| --- | --- | --- | --- |
| Python | 3.11 | https://www.python.org/ | `sudo dnf install python3.11` / `sudo apt install python3.11` |
| Node.js | 22.22.2 | https://nodejs.org/ | `sudo dnf install nodejs` / `sudo apt install nodejs` |
| pnpm | 12.15.0 | https://pnpm.io/installation | `corepack enable` |
| uv | 0.12.0 | https://docs.astral.sh/uv/ | `curl -LsSf https://astral.sh/uv/install.sh | sh` |
| FFmpeg / FFprobe | 8.1.3 | https://ffmpeg.org/ | `sudo dnf install ffmpeg` / `sudo apt install ffmpeg` |
| make | 4.4.1 | distribution | `sudo dnf install make` / `sudo apt install make` |

Python and FFmpeg are required for the service and analysis. Node, pnpm and uv
are required to build the UI and the environments. The installer does not
download or redistribute any of them.

## Credits

- Demucs code and `htdemucs_ft` weights: Simon Rouard, Francisco Massa and
  Alexandre Defossez (Meta AI Research), https://github.com/facebookresearch/demucs.
- Chordino and NNLS-Chroma: Matthias Mauch and contributors,
  https://github.com/c4dm/nnls-chroma.
- QM Key Detector (Katy Noland, Christian Landone) and QM Bar and Beat Tracker
  (Matthew Davies, Christian Landone, Chris Cannam), Queen Mary University of
  London, https://code.soundsoftware.ac.uk/projects/qm-vamp-plugins.
- BeatRoot: Simon Dixon, https://code.soundsoftware.ac.uk/projects/beatroot-vamp.
- Sonic Visualiser, Piper and the Vamp plugin SDK: Chris Cannam and Queen Mary
  University of London, https://www.sonicvisualiser.org/ and
  https://github.com/vamp-plugins/vamp-plugin-sdk.
- Signalsmith Stretch and Linear: Geraint Luff / Signalsmith Audio, MIT; the
  notices are in `web/src/player/stretch/NOTICES-signalsmith.md`.
- Emscripten: MIT/NCSA, https://emscripten.org/.
- FastAPI, Starlette, Pydantic, NumPy, React, Vite and TypeScript: see their
  upstream projects and the dependency manifests.
- “Eat” by HoliznaCC0, used for the screenshot: CC0 1.0,
  https://opengameart.org/content/funk-collection.

## Verify a download

```sh
make install-tools                 # tools only; prompts about the weights
make install-tools ACCEPT_MODEL_TERMS=1
sha256sum storage/tools/plugins/embed-07-8888130.so
sha256sum models/htdemucs_ft/*.th
make doctor
```
