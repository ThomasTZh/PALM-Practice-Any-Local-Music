# basseparate

A private, local bass practice studio. Load a recording you already own,
separate the bass, read the chords and the grid, and practise it: loops,
bar-snapped sections, metronome and count-in, speed and pitch — all on this
machine, with no account, no upload and no network access.

This repository is being rebuilt from zero. The application is a fresh
skeleton; the tasks that build the server, the browser audio engine, the Vamp
analysis and the UI land on top of it. What exists now is the reset, the
preserved offline assets and the automation the rest of the work runs on.

- Product intent: [GOALS.md](GOALS.md)
- Build log and decisions: [docs/progress.md](docs/progress.md)
- Deterministic test audio: [tests/fixtures/README.md](tests/fixtures/README.md)

## Offline by construction

Nothing here downloads anything: no packages, no models, no media. The local
assets are preserved in place and never tracked by git:

| Asset | Location | Used for |
|---|---|---|
| Demucs model bundle | `models/htdemucs_ft` | stem separation |
| Analysis environment | `analysis/.venv` | Demucs/torch inference |
| Vamp plugin pack, native host, SDK | `storage/tools` | bars, beats, chords, key |
| Sonic Visualiser / Piper host | `storage/tools/sv` | Vamp fallback host |
| Emscripten and Signalsmith sources | `third_party` | pitch/time WASM builds |
| Test recordings | `audio2test` | acceptance material |
| App environment | `.venv` | server, tests, lint, types |
| pnpm virtual store | `node_modules/.pnpm` | web dependencies |

Package manifests pin only versions that are already installed. Adding a
dependency requires a licence, size, offline and measured-benefit review.

## Requirements

Linux, with the preserved local assets above. The harness uses Python 3.11,
Node 22, pnpm, FFmpeg, uv and GNU Make. `make doctor` reports what is present,
including the Vamp plugin pack, the Piper server, the model bundle and GPU
availability, without touching the network.

## Quick start

```sh
make doctor      # report toolchain and assets, offline
make bootstrap   # idempotent, offline: python env, web links, fixtures
make gate        # local gate: lint, format, types, fixtures, tests, build, e2e
make demo        # list the deterministic demo audio
```

`make gate-lite` is the fast subset. `make fix` applies the automatic
formatting and lint fixes. Empty test sets are reported as `SKIP` while the
skeleton is empty; the gate fails only on real errors.

The web dependencies are linked from the preserved pnpm virtual store by
`make bootstrap`; `pnpm install` is not used offline. See
[docs/progress.md](docs/progress.md) for why.

## Layout

```
src/basseparate/   server, media, analysis client, projects (Python 3.11)
web/               React + TypeScript UI, Vite, Vitest, Playwright
tests/             fixture generator output and Python tests
docs/              build log, architecture and acceptance notes
scripts/studio.py  offline dev harness behind the make targets
analysis/          isolated Demucs worker environment (preserved)
storage/tools/     local Vamp hosts and plugin pack (preserved)
```

## Make targets

| Target | What it does |
|---|---|
| `doctor` | toolchain, asset directories, plugin pack, Piper, model bundle, GPU |
| `bootstrap` | offline, idempotent setup; skips completed work |
| `fixtures` | writes the deterministic WAV fixtures |
| `dev` | UI dev server and local API server once they exist |
| `build` | compile Python and build the production UI |
| `test` | Python and web test suites |
| `e2e` | Playwright end-to-end suite |
| `gate` / `gate-lite` | full / fast local gate |
| `fix` | ruff and prettier fixes |
| `demo` | list the demo fixtures and next steps |

## Recovering the pre-reset application

The legacy application is not deleted from history. It is preserved as the
tag `legacy-studio` and the branch `legacy`, both at commit `394a369`:

```sh
git worktree add ../basseparate-legacy legacy
cd ../basseparate-legacy
PYTHONPATH=src ../basseparate/.venv/bin/python -m pytest tests/unit -q
```

The worktree is a checkout of the old tree; its runtime assets (`.venv`,
`node_modules`, models) are the preserved ones in the main checkout. The
repository-side capability is verified in `docs/progress.md`; this execution
sandbox is confined to the workspace, so the literal `../basseparate-legacy`
path is exercised in-workspace and reported there.

## Platform

Linux first, Firefox first. The server binds loopback only and is not exposed
to the network.
