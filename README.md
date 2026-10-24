# basseparate

Local music-analysis and bass practice application.

## Status

Milestones 0, 1, and 2 are complete (foundation, media pipeline and
waveform editor, separation-based bass practice workflow). Milestone 2
final acceptance passed on 2026-10-23, including the human listening
review. Milestone 3 (musical grid) is in progress: M3.1 (rhythm domain and
schema), M3.2 (isolated Beat This! runtime, verified model registry,
explicit install boundary, CPU qualification), M3.3 (reproducible
rhythm-analysis input), M3.4 (real Beat This! runs with retained
framewise activations), M3.5 (source-aligned beat/downbeat decoding),
M3.6 (immutable automatic results and editable branches), M3.7
(tempo-map construction and reinterpretation), M3.8 (meter features,
inference, and manual regions), and M3.9 (bars, beats, pickups, and
shared Python/TypeScript golden vectors), and M3.10 (transactional rhythm
editing with undo/redo) are complete; M3.11 (musical ruler and
rhythm lanes), M3.12 (musical snapping), and M3.13 (musical loops), M3.14
(synchronized metronome), M3.15 (count-in), and M3.16 (musical readout
and navigation) are complete. See
[docs/implementation-status.md](docs/implementation-status.md) for the
authoritative resume ledger and verified test results.

## Implemented features

- Local audio/video import with chunked upload, ffprobe inspection,
  stream selection, and canonical PCM decode.
- Waveform pyramid generation and a source waveform editor with zoom,
  pan, selection, markers, follow-playhead, and undo/redo.
- Monitoring downmix for multichannel sources and playback-rate
  representations, so 44.1 kHz and 48 kHz material plays at the correct
  pitch and duration at any browser output rate.
- AudioWorklet transport with bounded buffering, underrun diagnostics,
  suspension handling, and audio-device recovery.
- Stem separation with the bundled Demucs `htdemucs_ft` baseline (GPU or
  explicit CPU), progress, cancellation, immutable versioned result
  sets, and analysis caching.
- Aligned stem tracks with mute, solo, gain, pan, time stretching
  (0.25x-2x), and source-anchored practice loops.
- WAV stem export and self-contained portable project save/open.
- Autosaved working state (markers, viewport, selection, volume,
  position, loops) with server-side revision checks and recovery.
- Rhythm analysis foundation (Milestone 3): exact rational musical
  positions, rhythm branch/pulse/anchor/meter persistence, and a
  verified, separately installed Beat This! runtime. Beat/downbeat
  decoding and the musical editor are implemented in later M3 packages.

## Not implemented yet

- Remaining Milestone 3 work: beat/downbeat decoding, tempo map, meter
  regions, musical ruler and snapping, metronome, and count-in. The M3.1
  domain/schema and M3.2 runtime/install/qualification foundation are in
  place.
- Milestone 4: harmony analysis and editing.
- Milestone 5: bass transcription.
- Milestones 6-8: complete persistence/workflow, quality models and
  YouTube, browser validation and release.
- Multi-user support, LAN exposure, mobile, and non-Linux platforms.

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

Rhythm analysis environment (Beat This!, Milestone 3):

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

Known pre-existing gate noise: `ruff format --check` would reformat 90
files under the locked ruff 0.16.9, and ESLint reports 131 errors in older
test harnesses. `ruff check`, mypy, the contract check, the unit and
integration tests, the production build, and the frontend test suite are
otherwise clean. See `docs/implementation-status.md` for the exact current
results.

## Diagnostics

```sh
.venv/bin/basseparate version
.venv/bin/basseparate doctor
.venv/bin/basseparate worker-probe
```

## Development workflow

```sh
uv run --locked python scripts/dev.py dev
```

Starts the Vite dev server and the backend together. Stop both with Ctrl-C.

## Documentation

- [Main project plan](basseparate_project_plan.md)
- [Milestone 0 specification](projectPlans/milestone0.md)
- [Milestone 1 specification](projectPlans/milestone1.md)
- [Milestone 2 specification](projectPlans/milestone2.md)
- [Milestone 3 specification](projectPlans/milestone3.md)
- [Milestone 3 M3.1 plan](projectPlans/m3.1-plan.md)
- [Milestone 3 M3.2 plan](projectPlans/m3.2-plan.md)
- [Rhythm environment notes](rhythm/README.md)
- [Architecture notes](docs/architecture.md)
- [Troubleshooting guide](docs/troubleshooting.md)
- [Implementation status](docs/implementation-status.md)
- [Dependency notices](licenses/NOTICES.md)

## License

Private and unpublished. No public license is claimed. See
[licenses/NOTICES.md](licenses/NOTICES.md) for third-party component
notices. The application environment installs no machine-learning
packages; model weights used by the isolated analysis environment are
described in the notices and in the model registry.
