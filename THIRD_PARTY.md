# Third-party components and boundaries

PALM's original application source is MIT (`licenses/LICENSE`). The following
components, downloaded tools and data have their own terms. Nothing in this
repository grants a licence to them.

The authoritative machine-readable list is
[licenses/third_party/manifest.json](licenses/third_party/manifest.json). It
records every component's version, copyright owner, licence id, source URL and
bundled/downloaded/excluded status, and points at the full texts under
[licenses/third_party/](licenses/third_party/). Exact pins, URLs, sizes and
SHA-256 values are in [THIRD_PARTY_DOWNLOADS.md](THIRD_PARTY_DOWNLOADS.md);
the generated dependency inventory is [licenses/NOTICES.md](licenses/NOTICES.md).

## Bundled or required at runtime

| Component | Version | Licence | Role / boundary |
| --- | --- | --- | --- |
| CPython (python-build-standalone) | 3.11.15 | PSF-2.0 | Embedded interpreter in Linux tar, Windows ZIP and macOS app; downloaded at build time, not committed |
| uv | 0.12.0 | MIT OR Apache-2.0 | Embedded environment installer for setup and build tooling; downloaded at build time, not committed |
| psutil | 7.2.2 | BSD-3-Clause | Required app dependency for process inspection and `--status`/`--stop`; installed from the locked runtime |
| FastAPI / Starlette / Uvicorn | 0.142.0 / 1.7.0 / 0.54.0 | MIT / BSD-3-Clause / BSD-3-Clause | Local HTTP server |
| Pydantic / pydantic-settings | 2.13.5 / 2.15.0 | MIT | Request and settings models |
| NumPy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | PCM and analysis math |
| platformdirs | 4.12.1 | MIT | Platform-native data roots |
| React / React DOM | 19.3.0 | MIT | Browser UI |
| Vite / TypeScript | pinned in `web/package.json` | MIT / Apache-2.0 | UI build (excluded from releases) |

The packaged Linux tar, Windows ZIP and macOS app contain the application, the
built UI, analysis workers/registry, environment definitions, launcher and
licences. They do not contain model weights, Sonic Annotator, the Vamp Plugin
Pack, FFmpeg or inference environments. Setup downloads tools and models only
after the licence gate.

## Download-on-first-run tools

| Component | Version | Licence | Status |
| --- | --- | --- | --- |
| FFmpeg / FFprobe, Linux x86_64 | Martin Riedl 9.0.2 (build 1789931100_9.0.2) | **GPL-3.0-or-later**; binary also reports `--enable-nonfree` and "not legally redistributable" | Downloaded after explicit consent; never bundled |
| FFmpeg / FFprobe, macOS arm64 | Martin Riedl 9.0.2 (build 1789931890_9.0.2) | **GPL-3.0-or-later**; `--enable-gpl --enable-version3` | Downloaded after explicit consent; never bundled |
| FFmpeg / FFprobe, Windows x64 | gyan.dev 8.1.2 essentials (2026-06-27) | **GPL-3.0-or-later** | Downloaded after explicit consent; never bundled |
| 7-Zip helper | 26.06 | LGPL-2.1-or-later with the 7-Zip unRAR restriction | Downloaded after explicit consent; never bundled |

FFmpeg/FFprobe sources:
[Martin Riedl builds](https://ffmpeg.martin-riedl.de/) and
[gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/). Exact per-platform
`ffmpeg -L`/`ffprobe -L` evidence and pinned hashes are in
[licenses/third_party/notices/ffmpeg-media-licenses.txt](licenses/third_party/notices/ffmpeg-media-licenses.txt).
7-Zip source: <https://www.7-zip.org/download.html>.

## Analysis tools and plugins

| Component | Version | Licence | Platforms / use |
| --- | --- | --- | --- |
| Sonic Visualiser / Piper host | 5.2.1 | GPL-2.0-or-later | Linux analysis host, installed below the data root by setup |
| Sonic Annotator | 1.7 | GPL-2.0-or-later | Windows/macOS analysis backend, installed below the data root by setup |
| Vamp Plugin Pack | 2.0 | AGPL-3.0 for the pack; individual plugins GPL/AGPL | Chord/key/beat plugins on Linux, Windows and macOS; installed below the data root |
| NNLS-Chroma / Chordino | pack 2.0 | GPL-2.0-or-later | Chord analysis |
| QM Key Detector, QM Bar and Beat Tracker | pack 2.0 | GPL-2.0-or-later | Key, beats and bars |
| BeatRoot | pack 2.0 | GPL-2.0-or-later | Beat analysis |

These are separate executables/libraries, downloaded from pinned upstream
releases and extracted into the writable data root. They are not committed to
this repository and are not system-installed. Their source is available from
the upstream projects listed in the download record. The manifest marks tools
as `downloaded`; the release-audit test rejects a `bundled` tool or model.

## Model weights

| Model | Engine | Licence boundary |
| --- | --- | --- |
| `htdemucs_ft` | Demucs | Code MIT; weights research-use, no separate upstream weight licence |
| `scnet-xl-ihf` | MSST | MSST code MIT; weights distributed by MSST with no separate weight licence |
| `bs-roformer-sw` | MSST | Mirror has no clear upstream weight licence; private use only |

Model cards are equal choices with no default. The installer shows the
licence/size and downloads only after explicit consent. The weights are never
bundled in a release asset and must not be redistributed by this project.

## Web/audio third-party code

- Signalsmith Stretch and Linear: Geraint Luff / Signalsmith Audio, MIT; see
  `web/src/player/stretch/NOTICES-signalsmith.md`.
- Emscripten: MIT/NCSA, used only to build the preserved WASM artifacts.
- React, Vite, TypeScript and testing tools: see `web/package.json`,
  `web/pnpm-lock.yaml` and `licenses/NOTICES.md`.

## Binary policy

No upstream executable, model weight or plugin binary is committed to git.
Build scripts download pinned CPython/uv archives into an ignored cache; setup
downloads tools/models into the user data root. The release artifacts contain
the permitted embedded Python/uv runtime only, not FFmpeg, tools, plugins or
models.

## Credits

Sonic Visualiser, Piper, Sonic Annotator, the Vamp plugin SDK and the Vamp
Plugin Pack are by Chris Cannam, Queen Mary University of London and
contributors. Chordino/NNLS-Chroma is by Matthias Mauch and contributors. QM
plugins are by Katy Noland, Christian Landone, Matthew Davies and Chris Cannam.
BeatRoot is by Simon Dixon. Demucs is by Simon Rouard, Francisco Massa and
Alexandre Defossez (Meta AI Research). See
[THIRD_PARTY_DOWNLOADS.md](THIRD_PARTY_DOWNLOADS.md) and
[licenses/NOTICES.md](licenses/NOTICES.md) for full pins and notices.
