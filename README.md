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

This workspace preserves the Python environment, web dependencies, Vamp
plugins, Piper host, model bundle and test recordings, so `make bootstrap` needs
no network and links the web dependencies from the preserved pnpm store. On a
fresh checkout without those assets, `make install-tools` checks the OS and
toolchain, downloads the pinned Sonic Visualiser and Vamp Plugin Pack releases
from their official pages, verifies every SHA-256, and downloads the Demucs
weights only after the explicit `--accept-model-terms` flag or an `accept` answer. See
[THIRD_PARTY_DOWNLOADS.md](THIRD_PARTY_DOWNLOADS.md) for URLs, hashes, licences
and credits. Nothing third-party is committed.

## What it does

- **Import** a local audio/video file (path, upload or job), with ffprobe
  metadata, one canonical PCM decode at the project rate, waveform peaks and an
  atomic, versioned project document.
- **Separate stems** with a selectable model: the bundled `htdemucs_ft` is the
  default (four stems: vocals, drums, bass, other); optional `scnet-xl-ihf`
  (same four stems) and `bs-roformer-sw` (six stems, adding guitar and piano)
  can be installed on demand. Jobs are content-cached per model, show a
  determinate progress bar with the stage, cancel cleanly and expose stem PCM
  and waveform peaks. The mixer's model selector marks missing models disabled
  with their exact install command; a success activates the model's stem lanes
  and mixer channels, and a partial stem set falls back to the mix with a
  visible notice.
- **Analyse** with the preserved Vamp plugins through the local Piper host:
  Chordino chords, Key Detector key, and QM Bar and Beat Tracker beats/bars with
  a beats-per-bar hint. Results are content-addressed and cached; the analysed
  grid, key and chords are persisted in the project.
- **Practise** in a full-width browser layout with one shared timeline: mix
  waveform, synced waveform lanes for vocals, drums, bass and other, the chord
  ribbon, the sections and then the spectrogram. The left rail holds Analysis,
  Mixer and Library. The pinned bottom bar has the practice controls on the left,
  the transport (return, play, loop with play centred on the drawer) in the
  middle, and the position plus bar/beat readouts at its bottom right; the track,
  key and BPM readouts sit in the top-right of the stage toolbar, and Zoom to
  selection falls back to an eight-bar window around the playhead when nothing is
  selected. The spectrogram axis is labelled with every semitone from C1 to C8.
  Sections are created by dragging (four-bar default), moved by dragging their
  body (length preserved, overlaps allowed), resized by their edges, and added
  ending at the playhead; the single-row editor lists them sorted by start and
  can chain-loop several selected sections with the gaps included. A green
  timeline scrollbar and playhead-follow paging make zoomed views navigable;
  speed 0.25–2×, accented metronome and a count-in that clicks even when the
  metronome is off. Pitch shifting was removed on request. The engine starts
  silent and renders only after an explicit play.
- **Save, reopen, export**: debounced atomic autosave of sections, loop, speed,
  position and mixer; reopen restores the project; mixdown export writes a
  16-bit WAV at the project rate with exactly the project frame count.

## Separation models

Demucs remains the default and is bundled with the checkout. The two optional
models run through the isolated MSST environment and are not downloaded by
`make bootstrap` or the default gate.

| Model id | Default | Stems | Installed size | 8 s CPU fixture (measured) | 5 min song estimate (linear) |
| --- | --- | --- | ---: | --- | --- |
| `htdemucs_ft` | yes, bundled | vocals, drums, bass, other | 321.0 MiB | 19.24 s wall (18.85 s child) | ~2.4x realtime, about 12 min |
| `scnet-xl-ihf` | optional | vocals, drums, bass, other | 204.2 MiB | 58.20 s wall (55.32 s child), 3.9 GiB peak RSS | ~7.3x realtime, about 36 min |
| `bs-roformer-sw` | optional | bass, drums, other, vocals, guitar, piano | 667.0 MiB | 67.35 s wall (65.97 s child), 3.0 GiB peak RSS | ~8.4x realtime, about 41 min |

All timings are CPU-only on this machine (CUDA is unavailable); the full-song
values are linear estimates from the measured 8 s runs, not measured on a whole
song. Peak memory is model-dominated and scnet-xl-ihf is the heavier of the two.
The UI states the same figures before you start a run.

```sh
make models-list                         # offline status: installed/missing/hash-mismatch
make models-install ID=scnet-xl-ihf      # network only for this step
make models-install bs-roformer-sw       # same as ID=...
make models-verify                       # offline size + SHA-256 check of installed files
make models-env                          # offline sync of analysis-models/.venv from the uv cache
make test-models-real                    # opt-in real 8 s SCNet/BS-RoFormer runs
```

The installer writes a `.part` staging file, checks the declared size and
SHA-256, publishes atomically and re-verifies the whole model directory. A
failure leaves the previous directory or nothing, never a partial model. The
weights stay under the untracked `models/` directory; they are not committed.
`make gate` and `make test-web/test-backend` stay offline and skip the real
model tests.

Licences and provenance: Demucs code is MIT and its bundled weights are research
use only; SCNet/MSST code is MIT with weights released through MSST without a
separate weight licence; the BS-RoFormer-SW mirror has an unknown upstream
weight licence and is treated as private use only. Details, source URLs and
hashes are in [licenses/NOTICES.md](licenses/NOTICES.md) and
`analysis/models.json`.

## Make targets

| Target | What it does |
|---|---|
| `doctor` | toolchain, assets, Vamp plugin pack, Piper, model bundle, GPU |
| `bootstrap` | offline, idempotent setup; skips completed work |
| `install-tools` | checks the machine and fetches pinned Vamp/Piper tools |
| `install-model` | legacy helper: fetches the htdemucs_ft weights after accepting their terms |
| `models-list` / `models-verify` | offline list / size+SHA-256 verification of separation models |
| `models-install` | install an optional model: `ID=scnet-xl-ihf` (or `make models-install scnet-xl-ihf`) |
| `models-env` | offline sync of the isolated `analysis-models` environment from the uv cache |
| `test-models-real` | opt-in real 8 s SCNet/BS-RoFormer runs (weights installed; slow) |
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
[PASS] ruff check / ruff format / fixtures (6) / models verify / mypy strict
[PASS] pytest 299 passed, 8 skipped (real-model tests opt-in and skipped)
[PASS] web typecheck, web tests (53 files / 527 tests, serialized), web build
[PASS] e2e golden path + layout spec (2 specs): Firefox and Chromium, isolated data root
gate: ok
```

`make accept` exit 0 analysed all five `audio2test` recordings: 1103.98 s of
audio in 213.32 s of cold wall time, with BPM, key, bar/beat counts, chord
sequences and per-file timings in [docs/acceptance/report.md](docs/acceptance/report.md)
and `report.json`. Missing recordings are reported as `missing` with null
values, never fabricated.

The golden path imports the deterministic `progression_120` fixture, analyses it
(C major, 120.2 BPM, 8 bars, C/Am/F/G), reopens the project, asserts transport
state and position movement, a 0.5× speed change, a four-bar section loop whose
range is read back from the saved project state, the metronome UI, autosave,
reopen and WAV export. In the final run both Firefox and Chromium advanced the
transport, changed speed and wrapped the real section range; headless runs
explicitly do not claim audible verification.

The manual listening checklist is in [docs/progress.md](docs/progress.md). Two
field sessions are recorded there (Carousel on Firefox): playback, speed, pitch,
chords, key, BPM and metronome pass by ear; stems, saving and section dragging
were fixed after the first session and confirmed working in the second. The
second session also found the engine rendering audio before any play press, whose
root cause is fixed and covered by real-WASM silence tests. After the second
session the shell was reworked (header removed, pinned compact transport with
track/key/BPM, ordered left rail, layout and scrollbar containment, sections
timeline-first with sorted list, body drag, end-at-playhead Add and chain loop,
pitch removed, count-in independent of the metronome), then a fourth round moved
the practice controls into the bottom-left zone, centred the transport, restored
single-row section entries and labelled the spectrogram axis with every semitone
from C1 to C8. A fifth round put the play button at the drawer centre, moved the
position and bar/beat readouts to the stage toolbar, moved the spectrogram below
the sections and clamped its PCM window, and defaulted Zoom to selection to eight
bars around the playhead. Those changes need one final listening and visual pass;
the checklist is not claimed as fully passed.

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
  reports no CUDA, so Demucs and MSST run on CPU. Measured on the 8 s stereo
  fixture: htdemucs_ft 19.24 s, scnet-xl-ihf 58.20 s (3.9 GiB peak RSS),
  bs-roformer-sw 67.35 s (3.0 GiB peak RSS); 60 s estimates are about 7.3 and
  8.4 min for the two MSST models. Full songs take minutes, Demucs is the fast
  default, and cancelling a job stops the child without publishing a stem set.
- **Chord/key accuracy varies:** Chordino spelling depends on voicing/rate
  (`C` vs `C6`, slash chords) and Key Detector can change on ambiguous material.
- **Pitch shifting removed:** the UI and player API no longer expose it at the
  user's request; the internal worklet transpose remains only for audio tests.
- **Chain loop includes gaps:** looping several selected sections runs from the
  earliest start to the latest end, so unselected material between them is
  included by design.
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
| Demucs model bundle | `models/htdemucs_ft` | default 4-stem separation |
| Optional model weights | `models/scnet-xl-ihf`, `models/bs-roformer-sw` | SCNet 4-stem / BS-RoFormer 6-stem separation (untracked; `make models-verify`) |
| Analysis environment | `analysis/.venv`, `analysis/checkpoints.json` | Demucs inference + hash pins |
| MSST environment | `analysis-models/.venv`, `analysis-models/uv.lock` | SCNet/BS-RoFormer inference (offline uv sync) |
| uv cache | `storage/tmp-uv-cache` | offline rebuild of `analysis-models/.venv` |
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
