# basseparate

Local music-analysis and bass practice application.

## Status

The project is now a local practice studio: local files, Demucs stems, a
Vamp QM bar/beat grid, editable Song Map sections, loops, and speed control.
The old Beat This!/custom-meter path remains as an experimental comparison
path, not the default.

Current slice: **core practice workflow**. The Firefox golden path passes:
import → ready → Vamp analysis → 4/4 bars → metronome schedule → speed →
musical loop → section → section loop → count-in → portable save. The
remaining work is real stem-separation UI acceptance, portable sections,
and the five-recording review.

- [Product goals](GOALS.md)
- [Execution plan](EXECUTION_PLAN.md)
- [Quality baseline](docs/quality-baseline.md)
- [Current status ledger](docs/implementation-status.md)
- [Requirements archive](requirements/README.md)

## Implemented features

- Local audio/video import with chunked upload, ffprobe inspection,
  stream selection, and canonical PCM decode.
- Waveform pyramid generation and a source waveform editor with zoom,
  pan, selection, markers, follow-playhead, and undo/redo.
- Monitoring downmix and playback-rate representations for correct pitch
  and duration at any browser output rate.
- AudioWorklet transport with bounded buffering, underrun diagnostics,
  suspension handling, and audio-device recovery.
- Demucs stem separation backend with progress, cancellation, immutable
  result sets, caching, and a browser **Separate stems** panel.
- Aligned stem tracks with mute, solo, gain, pan, and 0.25x–2x speed.
- Local Vamp QM bar/beat analysis through a native host (preferred) or a
  Piper host fallback; cached features and a generated rhythm branch.
- Editable Song Map sections with add/split/rename/color/delete, linked
  section loops, arbitrary range loops, and speed control.
- Metronome and count-in driven by the local Vamp grid.
- WAV export and self-contained portable project save/open.
- Autosaved working state with revision checks and undo/redo.
- The historical Beat This! rhythm pipeline and corpus remain available
  for comparison, but are not required for the default workflow.

## Not implemented yet / not accepted

- Real stem-separation UI acceptance on the five recordings (backend and
  panel tests pass; the full Demucs browser run is still manual).
- Portable-project round-trip test for sections (the state is included;
  the end-to-end check remains).
- Editing/correction of pulses, downbeats, and meter regions.
- Automatic section suggestions from the Vamp Segmenter; sections are
  manual in the current slice.
- Section chain/playlist looping (active section and selected ranges are
  supported).
- Milestone 4 harmony, Milestone 5 transcription, and later release work.
- Chromium/Safari/mobile support.

## Supported platform

Linux (initial target: Nobara). Other POSIX systems may work but are not
tested. The service binds loopback only.

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.11.15 | Managed by uv; system Python is not used |
| Node | 22.22.2 | Frontend build and tests only |
| pnpm | 12.8.1 | Pinned in the root `packageManager` field |
| FFmpeg | 8.x | System package (`ffmpeg`, `ffprobe`) |
| uv | 0.12+ | Python environment manager |
| Analysis environment | Python 3.11, demucs 4.1.0, torch 2.9.1+cu128 | Separate `analysis/` environment and lockfile; GPU optional |
| Rhythm environment | Python 3.11, beat-this 1.1.0, torch/torchaudio 2.9.1+cu128 | Separate `rhythm/` environment and lockfile; GPU optional |
| Model bundle | `htdemucs_ft` (hash-pinned) | `models/htdemucs_ft`; not in source control |

## Setup

Application and frontend dependencies (network access required for this
step):

```sh
uv run --locked python scripts/dev.py setup
```

Analysis environment, needed for separation and media-model jobs:

```sh
cd analysis && uv sync --locked
```

Then place the verified `htdemucs_ft` bundle (four checkpoint files and
the preset YAML) in `models/htdemucs_ft`. The runner verifies every
artifact's size and SHA-256 against
`src/basseparate/models/registry.py` before loading it, and runs with
the Hugging Face/Transformers offline flags set. `basseparate doctor`
reports whether the bundle is available.

Optional legacy rhythm environment (Beat This! comparison only):

```sh
cd rhythm && uv sync --locked
```

Beat This! checkpoints are **not bundled** and are never downloaded
automatically. Install one explicitly while online mode is allowed:

```sh
BASSEPARATE_OFFLINE_MODE=false \
  .venv/bin/basseparate models install beat_this_final0 --yes
```

`beat_this_small0` is the faster optional preset. A verified offline
bundle can be imported with `basseparate models import-bundle`, and
`basseparate models verify` checks an installed checkpoint. The
checkpoint store is `data/models/<model_id>/` under the active storage
root; `basseparate doctor` reports installed models without downloading
anything.

## Build

```sh
uv run --locked python scripts/dev.py build
```

Builds the frontend (`frontend/dist`) and the Python wheel (`dist/`).

## Run

```sh
uv run --locked basseparate serve
```

Or, from an already-synced checkout:

```sh
.venv/bin/basseparate serve
```

Starts the service on `127.0.0.1:8765` and opens a browser tab. Use
`--no-browser` to skip the browser and print the bootstrap URL instead:

```sh
.venv/bin/basseparate serve --no-browser
```

Optional flags: `--port N`, `--storage-root /path`.

## Shutdown

Press **Ctrl-C** (SIGINT) or send SIGTERM. The service:

1. Stops accepting new requests
2. Completes active short operations
3. Closes the database
4. Releases the instance lock
5. Exits with code 0

## Storage locations

| Category | Default path | Override |
|----------|-------------|----------|
| Config | `~/.config/basseparate` | `--storage-root` |
| Data (database, assets, portable archives) | `~/.local/share/basseparate` | `--storage-root` |
| Cache (waveform and analysis caches) | `~/.cache/basseparate` | `--storage-root` |
| State | `~/.local/state/basseparate` | `--storage-root` |
| Runtime (locks, staging) | `~/.local/state/basseparate/runtime` | `--storage-root` |

With `--storage-root /path`, all categories are placed under `/path/`.

## Models

| Model | Delivery | Notes |
|---|---|---|
| Demucs `htdemucs_ft` | Bundled development/release copy in `models/htdemucs_ft` | Hash-pinned; verified before loading; offline |
| Beat This! `final0` | Explicit install from the official CPJKU source | 81,058,141 bytes; SHA-256 pinned; MIT weights |
| Beat This! `small0` | Explicit install | 8,451,101 bytes; SHA-256 pinned; faster/optional |

Installation is offline-gated: while `offline_mode` is active (the
default), the install action refuses before any network access. Existing
projects and playback work with no rhythm model installed.

## Tests

```sh
# Formatting, lint, types, contracts, frontend build checks:
uv run --locked python scripts/dev.py check

# Python and frontend unit tests:
uv run --locked python scripts/dev.py test

# Playwright browser tests (requires system dependencies):
uv run --locked python scripts/dev.py test-browser
```

Direct commands used in the resume ledger:

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/basseparate
.venv/bin/python scripts/check_contract.py
cd frontend && npx vitest run
```

The current slice evidence is the Firefox golden path and the quality
baseline, not the total test count:

```sh
cd frontend && npm run e2e:golden
```

See `docs/quality-baseline.md` for the red/green quality gates and
`docs/implementation-status.md` for the current resume point.

## Diagnostics

```sh
.venv/bin/basseparate version
.venv/bin/basseparate doctor
.venv/bin/basseparate worker-probe
```

## Local Vamp configuration

The default analysis path needs the local Sonic Visualiser/Vamp tools. No
network access is used at runtime:

```sh
export BASSEPARATE_VAMP_PLUGIN_PATH="$PWD/storage/tools/vamp-plugins"
export BASSEPARATE_VAMP_NATIVE_HOST_PATH="$PWD/storage/tools/vamp-host"
```

The native host is the fast path. A Piper JSON host remains available via
`BASSEPARATE_VAMP_SERVER` and `BASSEPARATE_VAMP_LIBRARY_PATH`. See
`docs/troubleshooting.md` for setup and `scripts/vamp_reference.py` for the
reference oracle.

## Development workflow

```sh
uv run --locked python scripts/dev.py dev
```

Starts the Vite dev server and the backend together. Stop both with Ctrl-C.

## Documentation

- [Product goals](GOALS.md)
- [Execution plan](EXECUTION_PLAN.md)
- [Quality baseline](docs/quality-baseline.md)
- [Requirements archive](requirements/README.md)
- [Current implementation status](docs/implementation-status.md)
- [Architecture notes](docs/architecture.md)
- [Troubleshooting guide](docs/troubleshooting.md)
- [Firefox acceptance guide](docs/acceptance/firefox-listening.md)
- [Audible judgement guide](docs/acceptance/audible-judgement.md)
- [Rhythm environment notes](rhythm/README.md)
- [Dependency notices](licenses/NOTICES.md)

## License

Private and unpublished. No public license is claimed. See
[licenses/NOTICES.md](licenses/NOTICES.md) for third-party component
notices. The application environment installs no machine-learning
packages; model weights used by the isolated analysis environment are
described in the notices and in the model registry.
