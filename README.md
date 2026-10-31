# basseparate

A private, local bass practice studio. Bring a recording you already own,
separate the bass, read the chords and the grid, and practise it: loops,
bar-snapped sections, metronome and count-in, speed and pitch — on your own
machine, with no account, no upload and no network access.

The application is complete in this checkout: a FastAPI server, a React/TypeScript
browser UI, a real AudioWorklet playback engine, the preserved Vamp analysis
pipeline and CPU Demucs separation. The build log and all measured evidence are
in [docs/progress.md](docs/progress.md).

- Architecture and time model: [docs/architecture.md](docs/architecture.md)
- API reference: [docs/api.md](docs/api.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)
- Acceptance report: [docs/acceptance/report.md](docs/acceptance/report.md)
- Product intent: [GOALS.md](GOALS.md)

## Quick start

```sh
make doctor       # toolchain, assets, Vamp pack, Piper, model bundle, GPU
make bootstrap    # idempotent offline setup; skips completed work
make build-web    # typecheck + production UI build
.venv/bin/basseparate serve --no-browser --port 0
# open the printed `bootstrap: http://127.0.0.1:<port>/` URL
```

`make dev` starts the Vite dev server and an API instance; production use is the
CLI above serving `web/dist`. By default the server keeps its data in the
per-user application directory; pass `--data-root DIR` to use a different one
(the e2e suite uses an isolated temporary root per run).

There is no installer and no download step: the Python environment, web
dependencies, Vamp plugins, Piper host, model bundle and test recordings are
preserved in this workspace. `make bootstrap` verifies them and links the web
dependencies from the preserved pnpm store; `pnpm install` is not used offline.

## What it does

- **Import** a local audio/video file (path, upload or job), with ffprobe
  metadata, one canonical PCM decode at the project rate, waveform peaks and an
  atomic, versioned project document.
- **Separate stems** with the local `htdemucs_ft` bundle: four stereo stems
  (drums, bass, other, vocals) cached by content hash, with hash-verified
  checkpoints, progress, cancellation and stem PCM endpoints. Falls back to the
  mix with a visible notice when a stem set is unavailable.
- **Analyse** with the preserved Vamp plugins through the local Piper host:
  Chordino chords, Key Detector key, and QM Bar and Beat Tracker beats/bars with
  a beats-per-bar hint. Results are content-addressed and cached; the analysed
  grid, key and chords are persisted in the project.
- **Practise** in the browser: waveform with selection/zoom/seek, collapsible
  spectrogram, chord ribbon, bar-snapped sections and section loops, a five-source
  mixer with mute/solo/gain/pan, speed 0.25–2× with independent pitch, accented
  metronome, count-in, and a transport with frame-accurate position.
- **Save, reopen, export**: debounced atomic autosave of sections, loop, speed,
  pitch, position and mixer; reopen restores the project; mixdown export writes a
  16-bit WAV at the project rate with exactly the project frame count.

## Make targets

| Target | What it does |
|---|---|
| `doctor` | toolchain, assets, Vamp plugin pack, Piper, model bundle, GPU |
| `bootstrap` | offline, idempotent setup; skips completed work |
| `fixtures` | writes the six deterministic WAV fixtures |
| `dev` / `dev-smoke` | dev servers / start the real server, fetch health and root, stop |
| `build` / `build-web` | compile Python + build UI / typecheck + build UI only |
| `test` | Python and web suites |
| `test-backend` / `test-web` | scoped backend pytest / Vitest only |
| `test-separation` | real Demucs stem tests (slow, opt-in) |
| `e2e` | Playwright golden path on the real server (Firefox + Chromium) |
| `accept` | five-recording analysis report → `docs/acceptance/` |
| `gate` / `gate-lite` | full local gate / fast subset |
| `analysis-check` | Vamp SDK, plugin pack, Piper, native host and model bundle |
| `fix` | ruff + prettier fixes |
| `fixtures`, `demo` | regenerate fixture WAVs, list them |

`make gate` runs lint, format, strict typing, fixture determinism, Python and web
tests, the production build, and the two-browser golden path. It is offline.

## Acceptance evidence

Final gate (run for this documentation, exit 0):

```text
[PASS] ruff check / ruff format / fixtures (6) / mypy strict
[PASS] pytest 223 passed, 7 skipped
[PASS] web typecheck, web tests (47 files / 416 tests), web build
[PASS] e2e golden path: Firefox and Chromium, real server, isolated data root
gate: ok
```

`make accept` exit 0 analysed all five `audio2test` recordings: 1103.98 s of
audio in 213.32 s of cold wall time, with BPM, key, bar/beat counts, chord
sequences and per-file timings in [docs/acceptance/report.md](docs/acceptance/report.md)
and `report.json`. Missing recordings are reported as `missing` with null
values, never fabricated.

The golden path imports the deterministic `progression_120` fixture, analyses it
(C major, 120.2 BPM, 8 bars, C/Am/F/G), reopens the project, asserts transport
state and position movement, a 0.5× speed change, a bar-snapped section loop
that wraps, the metronome UI, autosave, reopen and WAV export. In the final run
both Firefox and Chromium advanced the transport, changed speed and wrapped the
loop; headless runs explicitly do not claim audible verification.

The manual listening checklist is in [docs/progress.md](docs/progress.md) under
the t15 entry. It is **not performed**; it needs a human with headphones and is
not claimed as passed.

## Known limitations

- **Tempo on beatless material:** sustained pads without onsets make QM Bar and
  Beat Tracker report 135.999 BPM/5 bars (the preserved native host reports the
  same). `click_120` and `progression_120` prove 120 BPM; the pad result is
  plugin behaviour, not a feed bug. No fixture-specific correction is applied.
- **Analysis cache and plugin versions:** the key includes source bytes, rate,
  bpb, lead-in and plugin names/parameters, but not plugin versions. The offline
  pack is frozen; bump `ANALYSIS_VERSION` if it ever changes.
- **Key tonic encoding:** `qm-keydetector` reports a 1-based tonic (C=1, A=10)
  in this pack; use the human key label, not the raw tonic.
- **CPU separation only here:** the NVIDIA driver is unavailable and torch
  reports no CUDA, so the worker runs on CPU. A fresh 8 s stereo fixture took
  17.93 s wall (≈2.4× realtime); full songs take minutes. 120 s windows, 8 s
  overlap and an OOM ladder bound memory.
- **Chord/key accuracy varies:** Chordino spelling depends on voicing/rate
  (`C` vs `C6`, slash chords) and Key Detector can change on ambiguous material.
  Raw labels are preserved; the UI normalises for display.
- **Automated audio cannot be heard:** tests assert engine/transport state with
  the real WASM and AudioWorklet, but no headless run claims audible quality.
- **Single platform, local only:** Linux, loopback, Python 3.11 and preserved
  assets; no macOS/Windows/mobile, no accounts or cloud.
- **Practical boundaries:** sections are bar ranges, loops are project frames;
  autosave pauses while playing (flushes on pause/stop); spectrogram PCM loads
  on expand; `make dev`'s API uses an ephemeral port while the Vite proxy
  targets 8765 (run the API on 8765 for proxied development).

## Offline assets

Nothing here downloads packages, models or media. These untracked directories
must stay where they are:

| Asset | Location | Used for |
|---|---|---|
| Python environment | `.venv` | server, tests, lint, types |
| Web dependencies | `node_modules/.pnpm` (linked into `web/node_modules`) | UI build/tests |
| Demucs model bundle | `models/htdemucs_ft` | stem separation |
| Analysis environment | `analysis/.venv`, `analysis/checkpoints.json` | Demucs inference + hash pins |
| Vamp plugin pack and hosts | `storage/tools` | chords, key, bars/beats |
| Sonic Visualiser / Piper host | `storage/tools/sv` | Piper JSON host |
| Emscripten and Signalsmith sources | `third_party` | pitch/time WASM builds |
| Test recordings | `audio2test` | acceptance material |

Package manifests pin only installed versions; adding a dependency requires a
licence/size/offline/measured-benefit review.

## Recovering the pre-reset application

The legacy application is preserved as the tag `legacy-studio` and branch
`legacy`, both at `394a369`:

```sh
git worktree add ../basseparate-legacy legacy
cd ../basseparate-legacy
PYTHONPATH=src ../basseparate/.venv/bin/python -m pytest tests/unit -q
```

The worktree is a checkout of the old tree; its runtime assets are the preserved
ones in this checkout. The in-workspace verification of that recovery path is
recorded in `docs/progress.md` (the execution sandbox cannot write the literal
sibling path).

## Platform

Linux first. Firefox and Chromium are supported for the browser UI; the local
server binds loopback only and is not exposed to the network.
