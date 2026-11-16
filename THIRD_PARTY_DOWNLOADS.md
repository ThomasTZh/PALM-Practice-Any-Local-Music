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

## Verify a download

```sh
make install-tools                 # tools only; prompts about the weights
make install-tools ACCEPT_MODEL_TERMS=1
sha256sum storage/tools/plugins/embed-07-8888130.so
sha256sum models/htdemucs_ft/*.th
make doctor
```

## Windows and macOS platform assets

These are downloaded by setup only after the licence gate and extracted below
the writable data root. None are committed or installed system-wide.

| Component | Version | Platform | Upstream URL | SHA-256 | Size | Licence |
| --- | --- | --- | --- | ---: | ---: | --- |
| Sonic Annotator | 1.7 | Windows x64 | https://github.com/sonic-visualiser/sonic-annotator/releases/download/sonic-annotator-1.7/sonic-annotator-1.7-win64.zip | `c40717e029210cf1e1c97bc7dadea00cf4386327e67fdf9ca66027a91ea26693` | 6,618,013 B | GPL-2.0-or-later |
| Sonic Annotator | 1.7 | macOS | https://github.com/sonic-visualiser/sonic-annotator/releases/download/sonic-annotator-1.7/sonic-annotator-1.7.0-macos.tar.gz | `cb54f46af0f6c16b8274998d025019021b3b6c50410b8a8e2024d0aa7e65b040` | 10,638,233 B | GPL-2.0-or-later |
| Vamp Plugin Pack | 2.0 | Windows x64 | https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/v2.0/Vamp.Plugin.Pack.Installer.2.0.exe | `24d12812ffde04a20e7acbeb543860552d7aa05a729d9e9123b33c6e097c4d5f` | 35,093,344 B | AGPL-3.0 pack; plugins GPL/AGPL |
| Vamp Plugin Pack | 2.0 | macOS | https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/v2.0/Vamp.Plugin.Pack.Installer-2.0.dmg | `60e2569ab064dbaf9ca8a4c3cf8465298b91ea3be1b34c5395d45c1ca4c53f10` | 48,745,081 B | AGPL-3.0 pack; plugins GPL/AGPL |

Windows uses a per-user extraction below the data root and does not request
administrator rights. macOS uses `hdiutil`/`pkgutil` to extract the DMG below
the data root; no system package is installed.

## Embedded platform Python and uv

Release builds embed the standalone CPython and uv binaries. They are downloaded
by the build scripts and are not committed. The Linux tar, Windows ZIP and
macOS app contain the interpreter and uv for that platform.

| Component | Version | Platform | Upstream URL | SHA-256 | Size | Licence |
| --- | --- | --- | --- | --- | ---: | --- |
| CPython standalone | 3.11.15+20260728 | Linux x86_64 | https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.11.15%2B20260728-x86_64-unknown-linux-gnu-install_only.tar.gz | `2db18c7bb3a47e32ff41727abd1bb5f158a17d8681931770abf0ba911f5b6580` | 49,078,078 B | PSF-2.0 |
| CPython standalone | 3.11.15+20260728 | Windows x86_64 | https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.11.15%2B20260728-x86_64-pc-windows-msvc-install_only.tar.gz | `b711f62a787476bc57b9d7d00e4bcccbe3bada78a1853f9143a112c0965ea347` | 48,441,840 B | PSF-2.0 |
| CPython standalone | 3.11.15+20260728 | macOS arm64 | https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.11.15%2B20260728-aarch64-apple-darwin-install_only.tar.gz | `7dc10e31eede05a6ab1ec9e0b961f521078b0959f838ed1d7452597d529ff802` | 27,243,366 B | PSF-2.0 |
| uv | 0.12.0 | Linux x86_64 | https://github.com/astral-sh/uv/releases/download/0.12.0/uv-x86_64-unknown-linux-gnu.tar.gz | `eaf842262aa1c418d8ecc5605f02ee1ebfd369124fa48548e85f9481a47831a9` | 21,373,358 B | MIT OR Apache-2.0 |
| uv | 0.12.0 | Windows x86_64 | https://github.com/astral-sh/uv/releases/download/0.12.0/uv-x86_64-pc-windows-msvc.zip | `68200e25de594df92387186bbfb9d9df606ec1d87efaa0ae0c7f690970e53db6` | 18,813,141 B | MIT OR Apache-2.0 |
| uv | 0.12.0 | macOS arm64 | https://github.com/astral-sh/uv/releases/download/0.12.0/uv-aarch64-apple-darwin.tar.gz | `2b9e582af54f84fa50c115427451a6c13e80f43b52f8282b8af5791077317bbf` | 17,387,877 B | MIT OR Apache-2.0 |

The platform pins live in `packaging/build-manifest.toml`,
`packaging/windows/build-manifest.toml` and
`packaging/macos/build-manifest.toml`. Build scripts verify size and SHA-256
before extraction.

## Application dependency pins

`pyproject.toml` pins the application runtime, including `psutil==7.2.2`
(BSD-3-Clause) for process control. `uv.lock` and
`packaging/app-runtime/uv.lock` carry the exact hashes. No PyPI package is
vendored in git; setup/build installs from the locked indexes. FFmpeg is a
user-installed prerequisite, not a dependency downloaded by PALM.

| Package | Version | Upstream source | Pinned artifact | Licence |
| --- | --- | --- | --- | --- |
| psutil | 7.2.2 | https://pypi.org/project/psutil/7.2.2/ | sdist `psutil-7.2.2.tar.gz`, SHA-256 `0746f5f8d406af344fd547f1c8daa5f5c33dbc293bb8d6a16d80b4bb88f59372`; platform wheels pinned in `uv.lock` | BSD-3-Clause |

The lockfiles contain the wheel URLs, hashes and sizes for each target
platform. psutil is a required app dependency, not a separately downloaded
tool.

## Download-on-first-run: FFmpeg, FFprobe and 7-Zip

These components are downloaded only after explicit consent and are not
committed to git or bundled in a release. The manifest records them as
`downloaded`.

| Component | Version/build | Platform | Upstream URL | Size | SHA-256 | Licence |
| --- | --- | --- | --- | ---: | --- | --- |
| FFmpeg | 9.0.2 / Martin Riedl 1789931100_9.0.2 | Linux x86_64 | https://ffmpeg.martin-riedl.de/download/linux/amd64/1789931100_9.0.2/ffmpeg.zip | 33,326,445 B | `fa8ecf4abbd290d98f7d188b8649cc6b391ae209a98452be955a15aab1909d7f` | GPL-3.0-or-later; nonfree parts, not redistributable |
| FFprobe | 9.0.2 / Martin Riedl 1789931100_9.0.2 | Linux x86_64 | https://ffmpeg.martin-riedl.de/download/linux/amd64/1789931100_9.0.2/ffprobe.zip | 33,223,234 B | `3f428c49070be3d24ec338602b76d412e401ffcb8a5641ef0e729181a232fc32` | GPL-3.0-or-later; nonfree parts, not redistributable |
| FFmpeg | 9.0.2 / Martin Riedl 1789931890_9.0.2 | macOS arm64 | https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip | 28,395,699 B | `c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924` | GPL-3.0-or-later |
| FFprobe | 9.0.2 / Martin Riedl 1789931890_9.0.2 | macOS arm64 | https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip | 28,317,701 B | `fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6` | GPL-3.0-or-later |
| FFmpeg | 8.1.2 / gyan.dev essentials 2026-06-27 | Windows x64 | https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip | 109,728,040 B | `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec` | GPL-3.0-or-later |
| FFprobe | 8.1.2 / gyan.dev essentials 2026-06-27 | Windows x64 | https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip | 109,728,040 B | `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec` | GPL-3.0-or-later |
| 7-Zip helper | 26.06 | Windows | https://www.7-zip.org/download.html | pinned by downloader | pinned by downloader | LGPL-2.1-or-later with unRAR restriction |

Exact Linux and Windows `ffmpeg -L`/`ffprobe -L` output, and the macOS build
configuration extracted from the signed Mach-O binary, are in
`licenses/third_party/notices/ffmpeg-media-licenses.txt`. The Linux Martin
Riedl build reports nonfree parts; PALM does not redistribute any managed
media binary.

## Documentation match

The authoritative list is `licenses/third_party/manifest.json`. This file and
`THIRD_PARTY.md` are summaries of it; `licenses/third_party/licenses/` contains
the full texts and `licenses/third_party/notices/` contains component notices.

## Source pages for downloaded components

These are the source/release pages used by the manifest; they are not
additional downloads.

| Component | Source page |
| --- | --- |
| ffmpeg-linux-x86_64, ffprobe-linux-x86_64 | https://ffmpeg.martin-riedl.de/ |
| ffmpeg-macos-arm64, ffprobe-macos-arm64 | https://ffmpeg.martin-riedl.de/ |
| ffmpeg-windows-x86_64, ffprobe-windows-x86_64 | https://www.gyan.dev/ffmpeg/builds/ |
| sonic-annotator | https://github.com/sonic-visualiser/sonic-annotator/releases/tag/sonic-annotator-1.7 |
| sonic-visualiser-piper | https://github.com/sonic-visualiser/sonic-visualiser/releases/tag/sv_v5.2.1 |
| vamp-plugin-pack | https://github.com/vamp-plugins/vamp-plugin-pack/releases/tag/v2.0 |
| demucs-code, demucs-weights | https://github.com/facebookresearch/demucs/tree/b1ea86542ca11d7695cba4238909f461752283b5 |
| msst-code, scnet-weights | https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/tag/v1.0.15 |
| bs-roformer-weights | https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem/tree/2b98254b19bdab07ce225d884ec4aa9dd8aafce1 |

7-Zip 26.06 assets used by the Windows Vamp helper:

- `7z2606-extra.7z` - 1,758,340 B, SHA-256
  `396c180f12d2247c24b0b1fcd482c6fc2a2700f61211ffede1061dd971f5e104`
- `7zr.exe` bootstrap - 600,064 B, SHA-256
  `e80db2dad715a6c5adabe292d31ed54e11f4e9b99ca349827b50573b175891bc`

Both are downloaded only inside the licence-gated setup job, verified before
use, and persisted below `<data>/tools/7zip`; neither is committed or bundled.
