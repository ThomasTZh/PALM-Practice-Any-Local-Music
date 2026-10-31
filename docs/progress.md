# Build log

Every entry records what changed, why, and how it was proven. The log is
append-only in spirit: corrections are new entries, not rewrites.

## 2026-10-31 — reset and offline automation skeleton (t1)

### Preserve the legacy application before touching anything

- `legacy-studio` is a lightweight tag and `legacy` a branch, both at commit
  `394a369` (`git rev-parse legacy-studio legacy` both print `394a369`). The
  old app stays recoverable and runnable through a worktree.
- Reason: a reset that only deletes is not recoverable; tagging first makes
  every later deletion reversible.
- Sandbox note: this execution environment can only write inside the
  workspace, so `git worktree add ../basseparate-legacy legacy` fails with
  `could not create leading directories of '../basseparate-legacy/.git':
  Read-only file system`. The same worktree operation was exercised at
  `.legacy-worktree/basseparate-legacy` inside the workspace and the legacy
  test suite was run there (see "Verification"). The repository-side command
  is unchanged for a normal checkout.

### What was removed, and what was deliberately kept

Removed from `main`: `frontend/`, `src/`, `tests/`, `contracts/`,
`requirements/`, `rhythm/`, `scripts/` and `docs/` as they existed, plus the
stale root `pnpm-lock.yaml`, `uv.lock`, `EXECUTION_PLAN.md` and
`CONTRIBUTING.md`. Those described the old FastAPI + React application and
would mislead the new tasks.

Kept: `GOALS.md` (product intent still holds), `licenses/` (third-party
attribution), `analysis/*.py` and its lockfile (the working Demucs pipeline the
stems task builds on) and every untracked asset directory: `models/`,
`analysis/.venv`, `third_party/`, `storage/`, `audio2test/`, `chords auto/`,
`.venv`, `node_modules`. Untracked local evidence under `docs/evidence/` and
`.m2.21-acceptance/` was left untouched.

Reason: the reset targets application code, not downloaded or user-owned
material. Deleting the analysis worker would throw away working separation
code; deleting the assets would break the offline rule.

### Skeleton and the offline make loop

New tree: `src/basseparate/`, `web/`, `tests/`, `docs/`, `Makefile`,
`pyproject.toml`, root `package.json`, `pnpm-workspace.yaml`, `.npmrc`,
`.editorconfig`, `README.md`. The harness is `scripts/studio.py` (standard
library only) and every make target is a thin wrapper so the logic lives in
one place.

Dependency versions in both manifests are pinned to what is already installed;
nothing new is declared. The app is imported from `src/` through pytest's
`pythonpath` instead of being installed into `.venv`, because the environment
is offline and the packaged build is not part of this task.

### Why bootstrap links `web/node_modules` instead of running `pnpm install`

`pnpm` 12.15.0 cannot install in this sandbox: the package manager's store
lives under the home directory, which the execution sandbox mounts read-only,
so every install fails with `ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK` even with
`--offline` and an explicit store directory. The dependency content is
preserved in `node_modules/.pnpm` (the pnpm virtual store from the legacy
checkout), and the installed versions are exactly the ones pinned in
`web/package.json`.

`make bootstrap` therefore links `web/node_modules` from that virtual store:
one relative symlink per direct dependency plus the `.bin` shims. It is
offline, deterministic and idempotent, and it reports "already linked" when
nothing changed. It refuses to guess: a missing package is a hard error naming
it. When a normal environment can run pnpm again, `pnpm install` produces the
same shape from the same pinned versions.

### Gate policy while the skeleton is empty

`gate` runs ruff check, ruff format check, fixture determinism, mypy strict,
pytest, and (full gate) web typecheck, vitest, vite build and Playwright. An
empty suite is reported as `SKIP`, not as success and not as failure: there
are no application tests yet, and the later tasks tighten the gate as their
suites land. Real errors always fail the gate. `gate-lite` keeps lint, format,
types, fixtures and tests.

### Fixtures

`make fixtures` synthesises the deterministic WAVs from fixed note lists with
`scripts/studio.py`: 120 BPM click (44.1 kHz mono), C-Am-F-G progression
(44.1 kHz mono, key C major), 440 Hz tone (44.1 kHz mono), silence, and a
48 kHz stereo tone so import tests cover a second rate. `manifest.json`
describes the musical facts, `SHA256SUMS` pins the bytes. The gate regenerates
the set in memory and compares it with the committed files, so the
"reruns byte-identically" property is checked on every gate run.

### Verification

Recorded from the actual runs on the committed tree.

- Recovery refs: `git rev-parse legacy-studio legacy` prints
  `394a36952d92a493ba39cca0eb8be8ee5ba6ce33` for both. `legacy-studio` is a
  lightweight tag so it points directly at the commit.
- Worktree: `git worktree add ../basseparate-legacy legacy` fails in this
  sandbox with `could not create leading directories of
  '../basseparate-legacy/.git': Read-only file system`. The equivalent
  in-workspace worktree `.legacy-worktree/basseparate-legacy` was created,
  `PYTHONPATH=src ../../.venv/bin/python -m pytest
  tests/unit/test_config.py tests/unit/test_project.py -q` reported
  `48 passed in 0.41s`, and the worktree was removed again. The repository
  side of the acceptance is satisfied; only the sibling-path write is blocked
  by the execution sandbox.
- Assets: `find models analysis third_party storage audio2test "chords auto"
  .venv node_modules -newermt "2026-10-31 18:10"` lists only `analysis/` and
  `analysis/pyproject.toml` (the in-scope pin edit). Every asset directory is
  still present; nothing was deleted from `node_modules` or the model bundle.
- `make doctor`: exit 0. Toolchain, `.venv` imports, analysis torch/demucs,
  16 linked web dependencies, Vamp SDK/plugins/native host, Piper server,
  model bundle, and recordings are reported ok. GPU is reported missing
  (`nvidia-smi` cannot talk to the driver, torch reports `cuda False`), which
  is expected on this machine and informational. No network access.
- `make bootstrap`: exit 0. First run linked 16 direct dependencies from
  `node_modules/.pnpm` and skipped the existing `.venv`; the second and third
  runs reported all three steps skipped and "no network used".
- `make fixtures`: exit 0. Running it twice leaves every WAV, `manifest.json`
  and `SHA256SUMS` byte-identical (`sha256sum` diff empty); `make gate`
  regenerates the set in memory and compares it on every run.
- `make gate`: exit 0. ruff check, ruff format, fixture determinism, strict
  mypy and vitest pass; pytest, web typecheck, web build and e2e report SKIP
  because those suites and sources do not exist yet. Real failures fail the
  gate (this was observed while fixing the harness: long lines and a
  `PTH101` violation failed it before the fixes).
- Dependencies: the 6 runtime and 6 dev Python pins and the 16 web pins all
  match what is installed (`importlib.metadata` and `web/node_modules`), and
  no manifest declares anything new.
- Extra checks: `web/node_modules/.bin/tsc -p tsconfig.node.json` exits 0,
  `pnpm --dir web test` exits 0 with "No test files found", and
  `make dev`, `make build`, `make test`, `make e2e`, `make gate-lite` and
  `make fix` all exit 0 on the empty skeleton.


## 2026-10-31 — split automation targets for downstream tasks (follow-up)

Requested by media (t3): `make test-backend` and `make dev-smoke` were
missing. One correction first: no task contract cites those names. The
contract verify commands are `make test` / `make build` / `make gate-lite` /
`make e2e` / `make accept`, plus the direct serve and script commands for
t3 and t5. The split targets are still useful, so they were added to the
harness rather than invented in each task.

- `make test-backend TESTS="tests/unit/test_media tests/integration/test_media"`
  runs the fixture determinism check and then `pytest -q` scoped to the
  selection (`--` is inserted so pytest flags pass through). Without a
  selection it runs the configured suite.
- `make test-web` runs Vitest only; `make build-web` typechecks and builds
  the UI only.
- `make test-separation TESTS="tests/integration/test_stems"` sets
  `RUN_SEPARATION=1` for the real Demucs tests and reports SKIP while no
  stem tests exist.
- `make dev-smoke` starts the real server with `PYTHONPATH=src` and
  `serve --no-browser --port 0 --data-root <temp>`, parses the loopback URL
  the CLI prints, GETs `/api/health` and `/`, asserts non-empty HTML only
  when `web/dist/index.html` exists, and always terminates the child. It
  fails with an explicit message while `src/basseparate/cli.py` is absent.
- `make analysis-check` reports the Vamp SDK, plugin pack, native host,
  Piper server, model bundle and analysis venv without network access.
- `make accept` runs `scripts/accept.py` once the acceptance task provides
  it and fails explicitly until then. No `e2e-*` aliases were added: the e2e
  task owns `web/e2e` and `scripts/accept.py`, and `make e2e` already picks
  up `web/playwright.config.ts` or `web/e2e/playwright.config.ts` when that
  task adds one.

Verified: `ruff check`/`ruff format --check scripts` clean; fixtures-check
ok; analysis-check ok; test-backend and test-separation invocation proven
with `TESTS="--version"` (`pytest 9.1.1`); dev-smoke and accept exit 1 with
the explicit "not implemented yet" messages; the smoke HTTP and URL/process
helpers were exercised against a local HTTP server (200 JSON + HTML) and a
fake child that prints a URL and is then stopped (`-15`). The repository-wide
`make gate` is momentarily red because t3 and t4 are actively landing
untracked tests that import modules not written yet; this change touches
only the harness, Makefile, README and this log.

## 2026-10-31 — UI shell, ruler, waveform and transport (t4)

### Contracts fixed before the code

The UI needs two boundaries and neither existed yet. Both were agreed with the
owning tasks before the panels were written:

- **Server data** (t3): `GET /api/library` returns `{entries}` (a bare array is
  also accepted), `POST /api/library/import` takes multipart field `file`,
  `GET /api/projects/{id}` returns the UI aliases plus the canonical
  snake_case fields, and `GET /api/assets/{id}/peaks?buckets=N` returns the
  BSPK container. The binary layout is 20 bytes of header (`BSPK`, u8 version
  1, u8 channels, u16 reserved, u32 sample rate, u32 bucket count, u32 samples
  per bucket) followed by per-bucket per-channel int16 min/max scaled by 32767
  and clamped to [-1, 1]. t3 confirmed the same bytes in writing; a later
  change bumps the version instead of breaking version 1.
- **Playback** (t2): `web/src/state/player.ts` defines `PlayerState` and
  `StudioPlayer` (`play`, `pause`, `toggle`, `seek`, `setSpeed`,
  `setPitchSemitones`, `setLoopEnabled`, `setLoopRange`, `setDuration`,
  `subscribe`, `getState`, `dispose`). t2 exposes a lower-level frame
  transport, so the adapter that maps it to this seam belongs to t9. The shell
  does not import the engine.

Response parsing happens once, in `api/client.ts`: a malformed entry, project
or peaks response raises `ApiError` instead of leaking `undefined` into
rendering.

### Pure modules instead of component math

- `panels/ruler/ticks.ts`: second ticks walk a fixed step list so labels stay
  at least 80 px apart and always sit on multiples of the step (scrolling
  reveals ticks rather than moving them). Bar/beat ticks derive from
  BPM/meter/offset, label only downbeats, and thin bar numbers as bars get
  narrow.
- `panels/waveform/viewport.ts`: fit, zoom-at-an-anchor, scroll and follow.
  Clamping is the single place that decides the legal window.
- `panels/waveform/selection.ts`: drag direction, track clamping and the
  50 ms minimum that distinguishes a click from a selection.
- `panels/waveform/peaks.ts`: BSPK decoding, channel merge and the SVG column
  path. `peaksFixture.ts` writes deterministic BSPK bytes so the pane tests
  read real binary input.

The ruler and every waveform lane share one viewport, so they cannot drift
apart. The transport panel holds no playback state: it reads
`usePlayerState(player)` and calls the player.

### The follow-loop bug

The first App test that played through a keyboard shortcut hung. Instrumenting
the follow effect showed it firing continuously with identical values: the
effect compared `next !== viewport`, but `clampViewport` returned the
intermediate object it was given, which was always fresh. `followViewport` now
compares the clamped result with the caller's viewport and returns the caller's
object when nothing changed; `zoomViewport` and `scrollViewport` do the same so
repeated keys at a limit do not re-render either.

### Verification

Recorded from actual runs on the committed tree, after t2's engine landed.

- `make test`: exit 0. Fixtures match the generator byte for byte, `pytest`
  reports 154 passed, and the web suite passes.
- `make build`: exit 0. Python compiles, `tsc --noEmit` passes for the whole web
  tree, and `vite build` reports 29 modules, 243.63 kB JS (76.27 kB gzip) and
  6.53 kB CSS (1.99 kB gzip).
- `web/node_modules/.bin/vitest run`: 16 files, 163 tests, exit 0. 110 of those
  tests in 12 files belong to t4 (api client, state, panels, App); the rest are
  the concurrent player suite.
- While t2 was still landing, the shared `tsc` and Vitest runs failed only on
  `web/src/player/stretch.test.ts` (a `Uint8Array`/`BufferSource` type error
  and two stretch assertions). Those failures were reported to t2 rather than
  patched from this task, and the tree went green when t2 fixed them.
- No dependency was added: `web/package.json` is unchanged and the build uses
  the already linked React 19 / Vite 8 / Vitest 5 / testing-library set.

## 2026-11-01 — playback core: speed, pitch, loop, metronome (t2)

### What was ported, and what is new

The legacy branch already had a working rolling-seek engine, so the core is a
port, not a rewrite. `web/src/player/mix-processor.js` carries the
`ConsumptionState` ring reader (shared SAB / transfer queue in one state
machine), the `MixState` mixer with the Signalsmith Stretch rolling seek, the
practice-loop stream model (pass crossings, join fades, wrap anchors) and the
procedural metronome click tables. The port trims diagnostics that belong to
other tasks (peak metering, loop pinning, control-response latency) and keeps
the audio-thread rules intact: no I/O, no allocation in steady state, no
exceptions in the render callback.

New in t2:

- `stretch_set_transpose(semitones)` in `stretch_wrapper.cpp` and
  `setTranspose()` on the JS engine, clamped to −12…+12. Pitch is orthogonal
  to the playback rate; a non-zero transpose engages the wet path even at
  exactly 1× (the dry 1× bypass would otherwise discard the pitch shift).
- A count-in phase in the core: `bars × beatsPerBar` accented clicks at
  `beatFrames`, with the audible cursor frozen until the last click, so the
  first loop pass starts after the count-in.
- Beat-list metronome inside the core: beats are project frames, mapped
  through the active loop and the current (ramped) rate, with a dedupe guard
  for the pass-boundary quantum and accented bar starts.
- `web/src/player/time.ts`: the pure output-time -> stream-frame and
  stream-frame -> project-frame conversions (loop wrap, paused anchors,
  duration clamp), so the transport never mixes coordinate systems.
- `web/src/player/transport.ts`: the seven contract states
  (`unloaded/loading/paused/playing/seeking/buffering/error`), seek
  generations, ranged prefetch through the worker (or the identical direct
  fallback), loop-stream splitting at pass boundaries, anchor-based output-time
  to project-frame mapping, and count-in/speed/pitch/beat plumbing. A failed
  load or fetch stays in `error`; `play()` never throws.
- `web/src/player/pcm.ts`, `fetch-core.ts`, `fetch-worker.ts`,
  `fetch-source.ts`: HTTP Range fetch, whole-frame validation, 416 handling,
  the 16-byte-header SAB ring with atomic indices, and stale-generation
  rejection. The worker and the main-thread fallback share the same
  `RangedPcmFetcher`, so the two paths cannot drift.

### Rebuilding the WASM offline

`node web/src/player/stretch/build.mjs` uses the preserved local
`third_party/emsdk` (Emscripten 4.0.23) and the pinned signalsmith-stretch
`a670068` / signalsmith-linear `de55e6a`. No download was used. The build now:

- exports `_stretch_set_transpose` (minified export `o`) and records the full
  API→wasm export map in `dist`/`BUILD.md`, so the hand-maintained letter
  mapping has a checked source of truth;
- adds `-fno-finite-math-only`: with plain `-ffast-math`, NaN controls fell
  through every clamp (observed: `stretch_set_transpose(NaN)` returned NaN).
  The wrapper's bit-pattern NaN check now survives compilation, and the JS
  boundary also parses non-finite values to 0.

Artifacts and BUILD.md hashes were regenerated together. Scalar `.wasm`
`dc0df91c…`, SIMD `.wasm` `549e8f88…`, both `.js` glue files unchanged from the
previous build (`83248bee…`, `a2fbcf01…`).

### Tests (real WASM, Node)

All player tests read the committed scalar artifact from disk and instantiate
it directly; no compiler or browser is involved.

- Pitch, FFT peak with Hann window and parabolic interpolation: 440 Hz at 0.5×
  and 1.5× stays inside ±1%; +2 semitones measures 493.9 Hz ±1% at 1×, 0.5×
  and 1.5×.
- Duration: the audible span of a 4 s source at 0.5×/1×/1.5× matches
  `1/rate` within 1.5% (measured 1.999 / 0.9997 / 0.669).
- Loop: a 2 s loop at 0.5×/1×/1.5× over 61 s produces wrap anchors exactly
  96 000 stream frames apart, steady-state wrap time spacing exactly one pass,
  ≥10 passes, and no quiet run longer than 16 ms (< 20 ms). The 5 ms join
  notch is the only dip.
- Metronome: supplied beat lists click at the requested frames with a louder
  downbeat; at 0.5× the 0.5 s beat spacing becomes 1 s of output. Count-in
  plays four accent-correct clicks, keeps the cursor at 0, and the loop audio
  resumes only after the last click.
- Errors: missing source (silent, no throw), underrun on the engine path
  (silence + flag, recovery when data arrives), out-of-range rate/pitch/NaN
  control values all clamp without throwing.
- Transport: lifecycle transitions, `seeking` during a seek, anchor mapping
  to project frames, loop stream→loop-range mapping (104 800 → 8 800),
  buffering on underrun, error on missing source, count-in before resume,
  shared vs transfer mode, and ranged prefetch never crossing the source end.
- Adapter: the worklet module registers `basseparate-player`, reports the
  2 880/2 880 latencies and plays a seeked chunk in a faked worklet scope.

### Verification

Recorded from actual runs on this tree.

- `web/node_modules/.bin/vitest run src/player` (from the repo root): exit 0,
  6 files, 60 tests.
- `make gate-lite`: exit 0 (ruff, format, fixtures, mypy, pytest 147 passed,
  web tests 170 passed).
- `make gate`: exit 0 (full suite, web typecheck, `vite build`, e2e skipped:
  no specs yet).
- `web/node_modules/.bin/prettier --check` passes for all hand-written player
  sources; the generated `stretch/dist/*.js` are excluded from formatting so
  their BUILD.md hashes stay valid.

## 2026-11-01 — Piper Vamp pipeline: chords, key, BPM and bars/beats (t5)

### What changed

- `src/basseparate/piper.py` is the only place that speaks Piper. It starts
  the preserved `storage/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server`,
  sets `LD_LIBRARY_PATH` to the AppImage `usr/lib` and `VAMP_PATH` to
  `storage/tools/plugins`, resolves plugins by display name, feeds mono blocks
  and returns raw features. Errors carry the child's stderr tail.
- `src/basseparate/features.py` owns the analysis contract: decode, run the
  three plugins in parallel Piper sessions, parse, derive BPM, and publish
  `beats.json`, `key.json`, `chords.json` and `meta.json`.
- `scripts/analysis_timing.py` measures a cold five-minute run.
- Tests: `tests/unit/test_piper/test_protocol.py` (12),
  `tests/unit/test_piper/test_features.py` (17),
  `tests/integration/test_analysis/test_pipeline.py` (7). The task's verify
  selection is `TESTS="tests/unit/test_piper tests/integration/test_analysis"`,
  so both are directories.

### Protocol, verified against the preserved server

Start: `piper-vamp-simple-server json` with
`LD_LIBRARY_PATH=$PWD/storage/tools/sv/squashfs-root/usr/lib` and
`VAMP_PATH=$PWD/storage/tools/plugins`. The server lists 122 plugins. The
message shapes that work are:

```text
{"method":"list","params":{}}
{"method":"load","params":{"key":..., "inputSampleRate":..., "adapterFlags":["AdaptInputDomain"]}}
{"method":"configure","params":{"handle":..., "configuration": <load defaultConfiguration>}}
{"method":"process","params":{"handle":..., "processInput":{"inputBuffers":[<base64 float32>], "timestamp":{"s":..., "n":...}}}}
{"method":"finish","params":{"handle":...}}
```

Three details matter:

- `load` puts the framing inside `result.defaultConfiguration`; `configure`
  returns the actual `framing` and `outputList`.
- Without `adapterFlags:["AdaptInputDomain"]`, Chordino's time-domain blocks
  are rejected (`expected 16386 values, obtained 16384`) and it returns no
  features. With the adapter it returns `simplechord` regions. The adapter
  names are case-sensitive Cap'n Proto names (`AdaptInputDomain`,
  `AdaptBufferSize`, `AdaptChannelCount`); the lower-case spellings are
  rejected.
- Responses contain Latin-1 description text such as "João", so they are
  decoded as Latin-1. Input blocks are sent as base64 float32 strings (the
  protocol's string form): 0.38 s -> 0.13 s on the eight-second chord fixture,
  with byte-identical output.

The preferred framing is kept: at 44.1 kHz Chordino is 16384/2048, Key
Detector 32768/32768 and Bar and Beat Tracker 1024/512; at 48 kHz the beat
tracker scales to 1114/557.

### Resolution and labels

Display names are the primary lookup: `Chordino`, `Key Detector`, `Bar and
Beat Tracker`. The current pack resolves them to
`embed-07-8888130:chordino`, `embed-12-10378903:qm-keydetector` and
`embed-12-10378903:qm-barbeattracker`; the recorded embed keys are used only
as a fallback if the display name is absent. Nothing resolves by file name.
Chord labels are copied verbatim (`C`, `Am`, `N`, and `C:maj` in the unit
test); `chords.json` declares `labels_raw: true`, and normalisation is left to
the UI.

### Cache and cancellation

The key is SHA-256 over the source bytes, the actual analysis sample rate,
`bpb`, the lead-in and the ordered plugin display names with their parameter
overrides. All four documents are written into a private
`.<key>.XXXXXXXX` directory and the directory is renamed into place, so a
reader sees all four or none. A second run reads the entry before decoding and
before starting a server; the integration test replaces both `load_audio_mono`
and `PiperSession` with exploding stubs to prove it. Cancellation is checked
before every request and every block, kills the child, and leaves no cache
directory. A corrupt or incomplete entry is a miss.

### BPM and the C-Am-F-G fixture

`bpm_from_beat_times` is a pure function: sorted finite beat times, positive
intervals, median, `60 / median`, three decimals. One missed beat does not move
it.

Measured on the fixtures with the preserved pack:

| Fixture | Chords (N filtered) | Key | BPM | Bars | First beat |
| --- | --- | --- | --- | --- | --- |
| `chords_c_am_f_g.wav` | `C, Am, F, G` | `C major` | **135.999** | 5 | 0.174 s |
| `click_120bpm.wav` (2 s lead + 2 s tail) | `N` | `Db major` | **120.185** | 2 | 0.0 s |

The chord progression and the C-major key are exact. The BPM and bar/beat
clause is proven on the click fixture, not on the chord fixture. The reason is
the fixture, not the feed: the chord fixture is four sustained triads with no
beat-level onsets, and QM Bar and Beat Tracker estimates 136 BPM on it. The
legacy native C++ host (`storage/tools/vamp-host`) produces exactly the same
18 beats, 5 bars and 135.999 BPM from the same WAV, so this is plugin behaviour
and not a Piper protocol mistake. A tempo-hint sweep over
`inputtempo=110..140` with and without `constraintempo` produced no 120 BPM
estimate. No fixture-specific correction was added: on a real five-minute mix
the same code reports a plausible 139.745 BPM, 176 bars and 701 beats. The
contract's BPM/bar/first-beat evidence therefore comes from the metronome
fixture, where the tracker has an unambiguous pulse.

### Timing (cold cache, 48 kHz, all three plugins)

Recording: `audio2test/Carousel Theory Full Mix V1 (With Limiter).wav`,
294.46 s. The first sequential implementation measured **43.02 s** and
**46.54 s** cold, under the gate but with little margin. Per-plugin timing
showed Chordino at 35.4 s and the beat tracker at 32.9 s, so the three plugins
now run in parallel Piper sessions; the final cold runs are **24.49 s** and
**22.87 s**. The last run's output:

```text
analysis-timing: duration 294.46 s, project rate 48000 Hz, cold cache
analysis-timing: elapsed 22.87 s (limit 60.00 s) OK
analysis-timing: bpm=139.745 key=Ab major bars=176 beats=701 chords=167
```

Parallelism is only across plugins: each Piper session remains single-threaded,
uses its own preferred framing, and its features are merged in the fixed
plugin order. No native host was added: the 60 s gate passes with Piper alone.
The measured time is also in the t5 task report.

### Verification

- `make test-backend TESTS="tests/unit/test_piper tests/integration/test_analysis"`:
  exit 0. Fixtures match byte for byte and pytest reports 36 passed
  (12 Piper unit, 17 feature/cache unit, 7 real-asset integration). ruff check,
  ruff format check and mypy are clean on the analysis sources.
- `.venv/bin/python scripts/analysis_timing.py`: exit 0, 22.87 s for 294.46 s
  of audio.
- The integration suite covers the exact chord order, C major, cached second
  run with no decode and no server, cancellation with no cache entry, missing
  `storage/tools/sv`, a missing plugin directory and a missing display name.
- The unit suite covers display-name resolution, embed-key fallback, Latin-1
  listing, base64 process requests, unknown parameters, timeout with stderr
  tail, non-zero exit with stderr tail, and killing the child on cancellation.


## 2026-10-31 — client-side spectrogram with a worker STFT (t6)

### Contract with the ranged PCM endpoint

The server exposes `GET /api/projects/{id}/pcm?start=&end=` with **frame**
indices, interleaved little-endian float32, and the format in headers
(`x-sample-rate`, `x-channels`, `x-frame-start`, `x-frame-end`, `x-frame-count`,
`x-total-frames`). `spectrogram/pcm-loader.ts` validates the headers and the
byte length, downmixes channels to mono and returns the requested frame range.
A malformed response is a `PcmLoadError`, not a short buffer.

The pane asks for one extra FFT window on each side of the visible range and
transfers that mono buffer to the worker. The worker replies with the RGBA image
and transfers the pixel buffer back; the UI thread never runs an FFT.

### Pure modules

- `fft.ts`: hand-written iterative radix-2 complex FFT with a precomputed plan
  (bit reversal and per-stage twiddles), plus a real-input transform that packs
  even/odd samples into one half-length complex transform and untangles it. The
  tests compare every bin against a naive reference DFT for n = 2..32 and check
  the real transform up to Nyquist.
- `window.ts`: periodic Hann window (sum = N/2) with shape and symmetry tests.
- `magnitude.ts`: amplitude to dB, clamp and normalization; silence is
  `-Infinity` and clamps to the floor instead of becoming NaN.
- `axis.ts`: log-frequency mapping (row 0 = Nyquist, last row = minHz),
  canonical labels (`50 Hz`, `1 kHz`, `10 kHz`) positioned from the top.
- `palette.ts`: dark-to-warm 256-entry RGBA palette with a monotonic luminance
  test.
- `stft.ts`: 2048-sample Hann windows, one FFT per output column, magnitudes
  interpolated onto the log axis, then the dB palette. Windowing is packed
  straight into the FFT scratch, and only the bins the axis touches are
  measured (about a third of the spectrum).
- `cache.ts`: `(start, width, FFT)` cache of in-flight and finished images with
  a 12-entry LRU bound so a long practice session cannot accumulate images.
  Failed entries evict themselves.
- `worker-client.ts` / `spectrogram.worker.ts`: request ids, transferable PCM
  and pixel buffers, error propagation, dispose that rejects pending work.

### Pane and shell hand-off

`panels/spectrogram/SpectrogramPane.tsx` takes the same `viewport`, `widthPx`
and `positionSeconds` as the ruler and waveform pane, so time axis, zoom and
playhead line up. It renders the frequency labels over the canvas, a dB colour
scale in the header, and a collapse toggle that hides only the body. The section
width is pinned to `widthPx`, so collapsing cannot move the timeline.

The pane exports `SpectrogramPaneProps` and takes `loadPcm`, an optional
`engine` (tests inject one) and layout options. `createRangedPcmLoader({ projectId })`
wires the server. `main.tsx`/`App.tsx` are owned by t16, so this task only notes
the mounting point: one `SpectrogramPane` below the waveform lanes inside the
same timeline container (see `panels/spectrogram/README.md`).

### Performance

`src/spectrogram/performance.test.ts` computes five consecutive 1280 × 256 views
of a five-minute 44.1 kHz project and records wall and CPU time for each. On a
shared host it asserts the best wall time and the best CPU cost are both under
100 ms and records the medians. Standalone: best wall 53.0 ms, best CPU 52.7 ms.
With the other spectrogram suites in parallel: best wall 50.2 ms, best CPU
50.2 ms. Details and caveats are in `web/src/spectrogram/PERFORMANCE.md`. A
repeated view is a cache hit and runs no FFT.

### Verification

- `web/node_modules/.bin/vitest run src/spectrogram`: exit 0, 10 files,
  61 tests. It includes the reference-DFT comparisons, Hann/magnitude/palette/
  axis/stft/cache/PCM/worker-client suites and the recorded performance test.
- `web/node_modules/.bin/vitest run src/panels/spectrogram`: exit 0, 8 tests:
  ranged-PCM request, canvas from the worker image, frequency labels and dB
  scale, playhead at the shared pixel, collapse leaving the ruler width
  unchanged and reusing the cache, per-view caching, lazy compute while
  collapsed, and both failure paths.
- `make build-web`: exit 0 (typecheck, Vite build). A temporary library build of
  `SpectrogramPane.tsx` emitted `spectrogram.worker-*.js` (6.36 kB) and the pane
  bundle (9.86 kB), proving the worker is a real production chunk; the temporary
  config and output were removed afterwards.
- `web/node_modules/.bin/vitest run` (whole web suite): exit 0, 237 tests.
- No dependency was added: `package.json`, the root manifest and the workspace
  file are unchanged.

## 2026-10-31 — analysis and practice UI (t7)

### Contracts

The shell task (t16) owns `App.tsx` and `main.tsx`, so every panel in this task
is prop-driven and exports its interfaces. `web/src/state/UI_CONTRACTS.md`
records the mounting table for t16.

- Analysis job: `POST /api/jobs` with `{kind:"analysis", params:{project_id,bpb}}`
  then `GET /api/jobs/{id}`; result `{cached, bpb, bpm, key, chords, beats, bars}`.
  t17 owns the server job and persistence. The panel takes an injected
  `AnalysisJobClient`, so tests use a fake and t16 wires `createAnalysisJobClient`.
  The key is the label (`"C major"`), never the 1-based plugin tonic. The badge
  shows `Cached` for a cached result, `Fresh` after a fresh run and
  `Not analysed` before that.
- Mixer: `MixerController` with `setGain`, `setPan`, `setMuted`, `setSoloed`.
  Practice: `PracticeController` with speed, pitch, loop, count-in bars,
  metronome on/volume and downbeat accent. t16 maps both to the engine; the
  panels never import `web/src/player`.
- Sections: `onLoop(section)` is the shell hook, and the optional `player` prop
  additionally applies `setLoopRange`/`setLoopEnabled` so the loop is set
  directly when the shell passes the transport. Sections remain editable after
  looping (rename and snapped start/end inputs are always present).

### Pure modules

- `state/chords.ts`: Chordino raw labels become compact symbols. `C:maj` → `C`,
  `A:min7` → `Am7`, `N` → `N.C.`, accidentals, slash bass and already-compact
  labels all normalise; unknown qualities keep their text. `chordAt` and
  `chordBlocks` drive the ribbon and its aria-current emphasis; blocks are
  clipped to the shared viewport.
- `state/sections.ts`: detected beats plus bpb produce beat/bar marks. Snapping
  is nearest-bar by default, nearest-beat or free on request. Add, split,
  resize, rename and delete are pure array operations; a collapsed bar range
  grows to the next boundary, and the projected end of the final bar is a legal
  boundary so a section can end at the track's end. `uniformBeats` synthesises a
  grid from BPM/meter when analysis has no beats, so sections work before the
  first analysis run.
- `state/mixer.ts` and `state/practice.ts`: clamps and the solo/mute rules
  (solo wins, muted always silent), plus pure reducers shared by the fakes and
  the future adapter. `state/fakeMixer.ts` and `state/fakePractice.ts` log calls
  and expose `sync()` for engine-reported changes.

### Panels

`ChordRibbon` (normalised blocks, current chord highlighted, click to seek),
`KeyBpmReadout`, `SectionLane` (Add/Split, snap selector, Loop, inline editor,
bar/beat overlay), `BarBeatOverlay`, `MixerPanel` (mute, solo, gain, pan, audible
state), `PracticePanel` (speed, pitch, loop, count-in, metronome, volume, accent,
snap mode) and `AnalysisPanel` (bpb select, Run, aria progressbar, cached badge,
failure alert). Shared styles were appended to `web/src/styles.css`.

### Verification

- `web/node_modules/.bin/vitest run src/panels`: exit 0, 14 files, 119 tests.
  New: chords 10, sections 12, mixer 7, practice 5, analysis 5.
- `web/node_modules/.bin/vitest run src/state`: exit 0, including the new chord
  normalisation (12), section snapping/add/split/loop (29), mixer (7), practice
  (5), analysis runner (6) and analysis API (9) suites.
- `web/node_modules/.bin/vitest run` (whole web suite): exit 0, 40 files,
  346 tests.
- `make build-web`: exit 0 (tsc and Vite build). No dependency was added:
  `package.json`, the root manifest and the workspace file are unchanged.
- `App.tsx` and `main.tsx` were not touched.

## 2026-11-01 — transport integration with assets, stems and grid metronome (t9)

### What landed (web/src/player only)

- **Multi-source transport.** `PcmTransport` now loads an aligned group: the
  canonical mix plus the four server stems (`drums`, `bass`, `other`,
  `vocals`) at one sample rate and frame count. Every source gets its own
  ranged PCM source and ring; the prefetch step fetches the same source-frame
  range for all of them in parallel and advances by the shortest result, so
  the group cannot drift. Seek sends the group generation array and resets
  every ring writer; mixer changes post per-source gain/balance/mute/solo
  without a seek or restart.
- **Grid and section loops.** `grid.ts` turns detected beats (or a 120 BPM /
  4/4 fallback grid) into metronome `BeatSpec`s with a downbeat on every bar
  start, and converts section seconds to clamped loop frames. `loopEnabled`
  + `loopRange` are one source of truth shared by the transport panel and the
  practice panel.
- **Studio adapter.** `studio-player.ts` exports `createStudioPlayer(options)`
  returning `{player, mixer, practice, transport, ready, getNotice,
  subscribeNotice, diagnostics, dispose}`. `player` is exactly t4's
  `StudioPlayer`; `mixer` and `practice` are the fixed controller surfaces
  (`setGain` dB / `setPan` / `setMuted` / `setSoloed`; speed, pitch, loop,
  count-in, metronome volume, accent). `studioPlayerOptionsFromProject`
  derives endpoints, stem labels and grid from a parsed project plus the
  analysis snapshot, with explicit overrides for server frame count.
- **Fallbacks and reporting.** When a stem set is advertised but cannot be
  fetched, the factory reloads the canonical mix only and publishes
  `Stems unavailable; playing the mix.` through `getNotice()` /
  `subscribeNotice`. Analysis-free projects use the mix with no notice.
  Underruns increment `diagnostics().underruns` and surface
  `Buffering audio…`; dropped chunks are counted. `latencySeconds` comes
  from the stretcher's reported input+output latency.
- **State mapping.** unloaded→idle; loading/seeking/buffering→loading;
  playing→playing; paused→paused; error→error; ended only after a natural
  end at the duration (never during seeking/buffering and never for an active
  loop). Play from the end restarts at 0 like the shell fallback.

### t12 review findings closed

1. **Reproducible measurements.** `measurements.ts` is the committed
   measurement code; `measurements.test.ts` prints the exact table and asserts
   the tolerances. Quoted values below come from that run.
2. **Loop fade vs 16 ms warm-up.** `measureLoop` reports `warmupMs`
   separately and only scans quiet runs after the first audible quantum;
   `measureJoinFade` measures the notch at sample resolution. At 0.5×/1.5×:
   warm-up 16 ms, longest quiet run after warm-up 0 ms, join fade 5.02 ms. At
   1× (dry bypass): warm-up 0 ms, join fade 5.00 ms.
3. **Engine-path count-in.** A new engine test runs a one-bar count-in at
   0.5× through the real WASM: four accented clicks at 0/24 000/48 000/
   72 000 output frames, cursor frozen at 0, then the loop tone starts within
   the 768-frame wet pre-roll. No underrun is reported.

### Measured table (committed measurement code, real scalar WASM)

- Pitch at 0.5×/1.5×: 439.9305 / 439.9297 Hz (0.016 % error).
- +2 semitones at 1×/0.5×/1.5×: 494.524 / 494.633 / 494.473 Hz against
  493.883 Hz (0.12–0.15 %).
- Duration ratio at 0.5×/1×/1.5×: 1.9933 / 1.0000 / 0.6693 (expected
  2 / 1 / 0.6667; ≤0.67 %).
- 2 s loop over 61 s at 1×/0.5×/1.5×: 30/15/45 passes, wrap spacing exactly
  96 000 stream frames, longest wrap-time error <4e-10 frames, warm-up 0/16/
  16 ms, join fade 5.00/5.02/5.02 ms, longest quiet run after warm-up 0 ms.

### Tests

- `web/node_modules/.bin/vitest run src/player` (from the repo root): exit 0,
  10 files, 99 tests at the time of this entry (engine 22, integration 7,
  transport 17, fetch 13, stretch 5, time 6, grid 8, adapter 15, worklet
  adapter 1, measurements 6).
- `make build-web`: exit 0 (`tsc --noEmit` + Vite build).
- New coverage: five-source sample-exact sync; mute/solo/gain while the cursor
  keeps moving; bar-boundary loop at 1×/0.5×; 1×→1.5× pitch/position
  continuity; 60 s sessions with five sources at 1×/0.5×; missing-stem
  fallback; underrun notice and diagnostics; seek position within 30 ms;
  count-in message ordering; grid fallback and accents.

### Integration note for t16

The server's stem entries carry `label` (`drums`, `bass`, `other`, `vocals`)
and a `url`; the t4 project parser currently requires `id`. `studioPlayerOptionsFromProject`
accepts either (`role` label wins, otherwise `id`) and can derive the endpoint
from the project id, so t16 can pass the parsed project once the parser maps
`label`/`url`. Explicit `frameCount`/`channelCount` extras avoid
duration×rate rounding differences.

## 2026-10-31 — integrate panels and the real transport (t16)

### What the shell owns now

`main.tsx` constructs the real server API (`createShellApi`), the analysis job
client and one `ShellTransport` whose factory maps t9's `createStudioPlayer`
onto the t4 `StudioPlayer`, t7 `MixerController` and t7 `PracticeController`
seams. App receives those as props. It mounts the library, ruler, mix waveform,
collapsible spectrogram, chord ribbon, section lane, analysis, mixer and
practice panels, and keeps the existing toolbar, keyboard shortcuts and follow
behaviour. App/main were the only entry files touched; panels, player and
spectrogram code are unchanged.

The project boundary (`state/project.ts`) now parses the real server payload:
stems come as `{label,url,frames,channels,sampleRate}` and are normalised to the
t4 `Stem` shape; the analysis document (`grid`, `key`, `chords`, `analysis`)
becomes an `AnalysisSnapshot`; persisted sections (`start_bar`/`end_bar` plus
exact seconds), speed, pitch, position, loop and mixer are restored; the ruler
grid is rebuilt from the analysis document when the top-level alias is absent.
Autosave writes the same state back through `PUT /api/projects/{id}/state` with
the loaded revision, debounced and paused while the transport is playing.

### Two integration bugs found by running the real shell

- **StrictMode disposed the shared transport.** An App cleanup effect called
  `transport.dispose()`; React's development double-mount ran the cleanup on the
  first mount, so every project open aborted silently and the UI sat on
  "Opening…". The transport is owned by `main.tsx` for the page lifetime, so the
  cleanup effects were removed. The shell now renders the project as soon as the
  project payload, peaks and runtime factory resolve; restored practice state is
  applied when `runtime.ready` settles, so a slow or blocked audio context
  cannot hide the workspace. A stale-open token prevents an older project's
  readiness callback from applying over a newer one.
- **Real server stems did not parse.** The t4 parser required an `id` on stem
  rows while t8 emits `label`/`url`; the shell project layer normalises them
  instead of editing the t4 client.

### Verification

- `make test-web`: exit 0. The whole web suite is 47 files / 409 tests,
  including the new App integration tests.
- `make build-web`: exit 0 (whole-tree `tsc --noEmit`, Vite build).
- `App.test.tsx` (8 tests): mounts all six panes, shows key/BPM/chords and the
  cached badge, keeps Space/ruler/follow working, adds a bar-snapped section and
  loops it through the player, runs analysis and updates ribbon/readout,
  autosaves sections, shows the stem-fallback notice and reports a failed open
  without leaving a broken shell.
- `App.integration.test.tsx` (2 tests) drives t9's real `createStudioPlayer`
  (fake AudioContext/worklet) through the mounted UI: the adapter satisfies
  `StudioPlayer`, Play/Pause, the speed menu, the pitch slider, the transport
  loop from a waveform selection and the section loop reach the real
  transport/practice state, and follow toggles while the engine plays.
- 1280 px layout check in a browser with a mocked API: six panes mounted, page
  scroll width 1280 (no horizontal overflow), stage 978 px wide, section lane
  and panel grid inside the right column, transport/full width; screenshots were
  used during the check and removed afterwards.
- No dependency was added (`web/package.json`, root manifest and workspace file
  unchanged).

### Known limitations

- Completing analysis updates the ribbon, readouts and section grid but does not
  rebuild the playing engine, so its metronome grid is the one loaded when the
  project opened; reopening the project applies the analysed grid.
- Spectrum PCM loads only when the spectrogram is expanded (collapsed by
  default), keeping project open fast on long recordings.
- Autosave writes when the transport is not playing; a position reached during a
  long take is saved when playback pauses or stops.

## 2026-10-31 — apply completed analysis to the live transport (t18)

### The gap

t16 mounted the analysis panel on the already-open engine, but the engine's
`PlaybackGrid` was fixed at construction: completing analysis changed the
document, ribbon, readouts and section grid, yet the metronome, accents and
count-in kept the fallback 120 BPM / 4/4 until the project was reopened.

### Live grid update

- `state/player.ts` adds an optional `StudioPlayer.updateGrid(grid)` seam and
  `PlayerGrid` (bpm, bpb, beatsSeconds, offsetSeconds). Optional keeps the
  local/fake players valid; engines that support it implement it.
- `player/studio-player.ts` makes the engine grid mutable and adds
  `updateGrid` to the player object and `StudioEngine`. It normalises the new
  grid and runs the existing `applyControls()` path (`setTempo`, `setBeats`,
  `setCountIn`, metronome volume) without touching speed, pitch, loop, position
  or transport state. `main.tsx` needed no change because it already passes
  `engine.player` through to the shell.
- `App.handleAnalyzed` now feeds the job result into
  `player.updateGrid({bpm, bpb, beatsSeconds, offsetSeconds})` before updating
  the project state (analysis, chords, beats, bars, bpb, key, ruler grid), so
  the chord ribbon, key/BPM readout, bar/beat overlay and section snapping use
  the detected grid immediately. Existing sections stay on their seconds.
- `clampLoopRangeToDuration` keeps an existing loop under a shorter duration;
  if the range would collapse it keeps the shortest legal loop at the tail
  instead of silently deleting it. The shell re-applies the loop (and its
  enabled flag) only when clamping changed it, and analysis never pauses or
  restarts playback.

### Verification

- `player/studio-player.test.ts` (2 new tests): replacing the grid mid-play
  posts the detected beat frames and downbeat accents to the worklet, a later
  Play sends `count-in` with `beatsPerBar: 3` and `beatFrames: 32000` for a
  90 BPM/3 grid, and the engine keeps playing across `updateGrid`.
- `state/player.test.ts` (4 new tests): loop clamping keeps fitting ranges,
  clamps ends to a shorter duration, preserves a tail loop when the old range
  falls past the end, and returns null only at zero duration.
- `App.integration.test.tsx` new test with t9's real engine and no initial
  analysis: fallback 120 BPM/4/4 count-in (24000 frames) plays; analysis while
  playing delivers 100 BPM/3/4 beats (`0, 28800, 57600, ...`, downbeats every
  3), keeps the same engine instance (creation count 1), keeps the transport
  playing and the existing 0–2 s loop enabled, updates the key readout to G
  major and ribbon to G, and the next Play sends a count-in with
  `beatsPerBar: 3`, `beatFrames: 28800`. Adding a section afterwards snaps to
  the detected 1.8 s bars (the fallback would have produced 2 s), while the
  existing section stays editable.
- `make test-web`: exit 0, 47 files / 416 tests.
- `make build-web`: exit 0 (whole-tree `tsc --noEmit`, Vite build). No
  dependency was added.

### Limitations

- The engine grid update does not change the recording duration (analysis does
  not return a duration); loop clamping is therefore exercised by the pure
  helper and applies whenever a shorter duration is present.
- Chords feed the ribbon and shell state, not the audio engine (the engine only
  needs beats/tempo); the transport uses beats plus bpb for accents, with the
  analysed bpb matching the persisted bar boundaries.

## 2026-11-01 — documentation, limitations and acceptance evidence (t15)

### Documentation map

- [architecture.md](architecture.md): processes, data root, project document,
  time model, playback path, analysis/separation pipelines, caching.
- [api.md](api.md): every shipped route, request/response shapes, binary PCM and
  BSPK formats, SSE and job contracts.
- [troubleshooting.md](troubleshooting.md): setup, analysis, separation,
  playback, projects/export and acceptance failure modes.
- README.md: the user-facing quick start, commands, limitations and evidence.
- [acceptance/report.md](acceptance/report.md) and `report.json`: the
  five-recording report regenerated at the final gate (below).
- `web/e2e/golden-path.spec.ts`, `web/e2e/playwright.config.ts` and
  `scripts/e2e_server.py`: the browser acceptance path.

### Final gate (run before README, after the HTTP Range fix)

```text
gate (offline)
  [PASS] ruff check     ruff check 3 path(s) (0.1s)
  [PASS] ruff format    ruff format --check (0.1s)
  [PASS] fixtures       6 fixtures match the generator byte for byte (1.3s)
  [PASS] mypy           mypy strict (0.5s)
  [PASS] pytest         223 passed, 7 skipped, 1 warning in 49.99s (50.4s)
  [PASS] web typecheck  tsc --noEmit (2.3s)
  [PASS] web tests      vitest run (8.8s)
  [PASS] web build      vite build (0.8s)
  [PASS] e2e            1 spec file(s) (27.8s)
gate: ok
```

`gate: ok`, exit 0. An independent `vitest run` in `web/` reported 47 test
files / 416 tests; the Python gate number above is the authoritative one.
The gate's e2e step runs the golden path on both configured browsers against
the real FastAPI server with a fresh temporary data root per run.

### Browser transport evidence (final run)

A JSON-reporter run of the same e2e suite after the HTTP Range fix recorded:

| Project | Result | Position | 0.5x delta / 1.5 s | Loop wrap | Export |
| --- | --- | --- | --- | --- | --- |
| Firefox | passed | 0.20 s → 0.60 s | 0.90 s | 1 wrap (…1.9 → 0.1) | 705600 frames @ 44.1 kHz |
| Chromium | passed | 0.10 s → 0.40 s | 0.80 s | 1 wrap (…1.9 → 0.1) | 705600 frames @ 44.1 kHz |

Both reported `AudioWorklet=true`, a running AudioContext, a secure loopback
context, and no audible verification claim (headless). The earlier frozen
position was a transport/HTTP bug: the player sends `Range: bytes=…` and the
PCM routes ignored it until the fix that now returns `206` +
`Content-Range`/`Accept-Ranges` and `416` for unsatisfiable ranges. There is no
open browser-playback limitation; the only browser limitation is that automated
runs cannot judge what a human hears.

### Other measured results used by the docs

- `make doctor` exit 0: all required toolchain and assets present, no network.
  GPU section reports `nvidia-smi unavailable` and `torch cuda False`.
- `make test-separation TESTS="tests/integration/test_stems"`: 14 passed in
  30.50 s on the real CPU Demucs run.
- Fresh separation probe: 8.00 s stereo at 48 kHz → four 384000-frame stereo
  stems, 17.93 s wall (child 17.48 s, `device=cpu`), no network.
- `make accept` exit 0: 5/5 recordings, 1103.98 s of audio, 213.32 s wall.
  The Markdown printed to stdout was byte-identical to the committed
  `docs/acceptance/report.md` for that run. Per-file results are in that report
  (analysis times 7.635–76.426 s on this loaded machine).
- `make fixtures`: 6 fixtures, byte-identical on rerun; `progression_120`
  yields C major, 120.246 BPM at 48 kHz (120.185 at 44.1 kHz), 8 bars, raw
  N,C,Am,F,G with bar-aligned starts.

### Known limitations (measured, not intentions)

1. **Beatless material confuses the tempo tracker.** The four sustained chords
   in `chords_c_am_f_g.wav` have no beat-level onsets; QM Bar and Beat Tracker
   returns 135.999 BPM and 5 bars. The preserved native host returns the same
   18 beats / 5 bars / 135.999 BPM from the same WAV, so this is plugin
   behaviour. `click_120.wav` (120.185 BPM, 2 bars) and `progression_120.wav`
   (120.246 BPM, 8 bars, chords + click bed) are the tempo evidence. No
   fixture-specific correction is applied.
2. **The analysis cache key omits plugin versions.** The offline pack is
   frozen; if it is ever replaced, bump `ANALYSIS_VERSION` in
   `src/basseparate/features.py` so old entries cannot be reused. The cache
   key already includes the source hash, actual rate, bpb, lead-in and ordered
   plugin display names/parameters.
3. **`qm-keydetector` tonic is 1-based in this pack** (C=1, A=10, mode 0
   major/1 minor). Consumers must use the human key label (`key`,
   `key_label`), never treat the raw tonic as a 0-based MIDI pitch class.
4. **Stem separation is CPU-only here.** The NVIDIA driver is unavailable and
   `torch.cuda.is_available()` is false (`make doctor`); the worker reports
   `device=cpu`. A fresh 8 s stereo 48 kHz fixture took 17.93 s wall
   (≈2.4× realtime), so a five-minute song takes roughly twelve minutes; the
   worker uses 120 s windows with 8 s overlap and a 7.5/5/3 s OOM ladder.
5. **Chord/key output is an estimate, not ground truth.** Chordino label
   spelling varies with voicing/rate (`C` vs `C6`, `F` vs `F6`, slash chords)
   and Key Detector can change its mind on ambiguous material; the UI
   normalises chords for display and the raw labels remain in the cache. The
   fixture values above are the reproducible acceptance values, not a claim of
   universal accuracy.
6. **Automated runs cannot verify audibility.** Node and browser tests assert
   transport state, frame position, loop wraps and control state with the real
   WASM/AudioWorklet, but no headless run claims what a human hears. The manual
   listening checklist below is not performed by the agent.
7. **Single platform and local-only by design.** Linux, loopback only, Python
   3.11 and the preserved assets; project locks use `fcntl`; there is no macOS,
   Windows or mobile support, no accounts, no cloud sync and no streaming
   download.
8. **Persistence boundaries.** Sections are stored as bar ranges and loops as
   project frames; autosave skips while the transport is playing (it flushes on
   pause/stop); the spectrogram loads PCM only when expanded. `make dev` starts
   Vite plus an ephemeral API port, while the Vite proxy targets 8765; for
   proxied development run the API on 8765 and Vite separately.
9. **Dev/acceptance timing varies with machine load.** The committed
   acceptance report records one cold run (213.32 s wall for 1103.98 s of
   audio); musical values are stable, wall times are not a benchmark.

### Manual listening checklist (not performed — requires a human)

Status: **not performed**. Do not mark these as passed without a listener and a
date/initials. Run on Firefox or Chromium with real headphones, once per
`audio2test` recording plus `tests/fixtures/audio/progression_120.wav`:

- [ ] Import the file; play 60 s at 1×; no clicks, dropouts or pitch drift.
- [ ] 0.5× and 1.5×: pitch stays the same, no warble or metallic artefacts.
- [ ] Pitch +2 / −2 semitones at 1×: expected transposition, position stays
      continuous.
- [ ] Separate stems: bass solo, bass mute, drums/other/vocals solo; no obvious
      bleed that breaks practice, no start/stop glitch when switching.
- [ ] Analyse: key, BPM and bar/beat grid match the recording by ear; chord
      ribbon order matches the harmony (N.C. allowed in gaps).
- [ ] Create a bar-snapped section (two bars), loop it five passes; the wrap is
      seamless and the count-in/accented metronome lines up with the song.
- [ ] Save, restart `basseparate serve`, reopen: speed, loop/section, mixer and
      position restore; export WAV and confirm it plays and matches duration.
- [ ] Record listener, date, browser and any defects in this file's next entry.

### Acceptance evidence

- Five-recording report: [acceptance/report.md](acceptance/report.md);
  machine-readable rows: `docs/acceptance/report.json`.
- Golden path: `web/e2e/golden-path.spec.ts`; run with `make e2e` (Firefox and
  Chromium, real server, isolated temp data root).
- Fixtures: six deterministic WAVs generated by `make fixtures`, described in
  [tests/fixtures/README.md](../tests/fixtures/README.md).
- Every number above is from the commands named beside it in this entry; no
  document quotes a run that is not committed or reproducible with those
  commands.

## 2026-10-31 — stem separation control and live stem activation (t21)

### Why

The mixer only said "Separate stems to mix them." and there was no way to start
the server's ready separation job. After a successful run the open engine also
kept its mix-only source group until the project was reopened.

### Control and API

- `state/separation.ts`: separation job state and `runSeparationJob`, which
  starts POST `/api/separate`, polls GET `/api/jobs/{id}` (fraction + stage
  message), forwards updates, supports abort and raises the server's message on
  failed/cancelled jobs.
- `state/separationApi.ts`: `createSeparationJobClient` with the real request
  shapes (`POST /api/separate {project_id}`, `GET /api/jobs/{id}`,
  `POST /api/jobs/{id}/cancel`), tolerant job parsing and plain-language HTTP
  errors.
- Mixer panel: a separation block under the channels. No stems shows
  "Separate stems"; stems show "Re-separate" with "Stem separation is cached: a
  re-run is instant." Running shows a determinate progressbar with
  `aria-valuenow`, the stage and percentage, and a Cancel button; failures show
  the server message in a role=alert. Styles live in `panels/mixer/mixer.css`.

### Activation

On success App refetches the project (stems label/url), opens a new shell
runtime through the existing transport factory, waits for it to be ready and
reapplies a snapshot captured at activation time: position, duration, speed,
pitch, loop range/enabled, count-in, metronome on/volume, accent, and per-channel
mixer gains/pans/mutes/solos. The four stems plus the mix now appear in the
mixer; the mix is muted after separation so the stems do not double the audio.
Sections and snap mode are shell state and are preserved as-is, not overwritten
by the refetched document. Playback resumes only when it was playing before
activation; a paused project stays paused. Sections/analysis and the separation
project id are guarded so a project switch aborts activation.

### Verification

- state tests: separation runner progress/stage/failure/cancel/abort and the API
  client's POST body, status, cancel, HTTP detail and malformed payload.
- mixer tests: Separate stems, determinate progress/stage/cancel, Re-separate
  with cache hint, and the failure alert.
- App tests with a fake separation API: start + progress + cancel (no runtime
  rebuild), success activation with a second project fetch and new runtime,
  preserved position 4 s / practice speed 0.75 / pitch -2 / loop 2–4 s / 1 count-in
  bar / metronome 30% / accent off / Section 1, new channels mix, drums, bass,
  other, vocals with mix muted, playing resumed; paused completion never calls
  play; failure keeps the old runtime and Play still works; Re-separate shown
  for an existing-stem project.
- `make test-web`: exit 0, 49 files / 437 tests.
- `make build-web`: exit 0. No dependency added.

### Limitations

- Cancelling before the POST returns has no job id to send; polling aborts and
  the UI returns to idle, and the server job may still be running.
- Separation activation disposes and reloads the audio group once; a short
  buffering gap is expected (the UI is not blocked during the job).

## 2026-10-31 — autosave revision after analysis and explicit playback (t22)

### Save failure and lost sections

The analysis job writes the document and bumps the project revision server-side.
The shell kept the revision read at open time, so the next autosave PUT carried
a stale revision, the server returned 409, the footer showed "save failed", and
sections never reached disk. Analysis itself was persisted by the job, which is
why chords survived a restart while sections did not.

- `App.handleAnalyzed` now refreshes the shell revision after the job: it
  refetches the project, ignores a result if the user switched projects, and
  updates both `revisionRef` and the local project revision without replacing
  local chords/sections.
- `createShellApi.saveState` catches a 409 once, refetches the project to get
  the server revision, and retries the PUT with it. The retry returns the new
  revision so the shell's next save is current. Other errors still fail
  immediately.

### Implicit playback

No code change was needed for the three reported playback behaviours, but each
now has a regression test:

- Opening a project is asserted paused with the toggle reading Play, including
  with t9's real engine (duration/status ready, transport not "Playing").
- Clicking a section block calls `onSeek` only; a fake player receives no play,
  pause or toggle calls.
- `TransportPanel` already derives everything from `usePlayerState(player)`.
  A test starts playback by calling `player.play()` directly (not the toggle)
  and asserts the button becomes Pause and status Playing; calling
  `player.pause()` directly returns it to Play/Paused.

### Verification

- `state/project.test.ts`: simulated 409 -> exactly one GET project refresh,
  PUT retried with revision 7 instead of 3, second PUT body contains the latest
  Section 1 (start_bar 0, end_bar 1), returned revision 8. A 500 response is
  not retried.
- `App.test.tsx`: after analysis, a project refetch supplies revision 5 and the
  next autosave of a new section uses revision ≥ 5 (not the open-time 2), the
  saved state contains Section 1 and the footer shows saved. Opening asserts
  Play/no Playing.
- `SectionLane.test.tsx`: block click seeks to its start and the fake player has
  no playback calls.
- `TransportPanel.test.tsx`: direct engine play/pause flips the toggle and
  status, with only play/pause recorded (no toggle clicks).
- `make test-web`: exit 0, 49 files / 442 tests.
- `make build-web`: exit 0. No dependency added.

### Limitations

- The post-analysis revision refresh is a second project GET. If it fails, the
  save still has the one-shot 409 recovery, but a second conflict reports save
  failed.
- Local UI sections are authoritative during a refresh; the server document is
  only read for the revision, so unsaved section edits are not overwritten.

## 2026-10-31 — create and resize sections by dragging (t23)

### Interaction

The section lane timeline now uses pointer events:

- Pressing on empty lane space and dragging shows a dashed `section-draft`
  overlay for the snapped range. On release the range is passed through the
  existing `addSection` helper, so Bar (default), Beat and Free behave like the
  Add button. A small drag below a 4 px threshold is treated as a click and
  only seeks.
- Each section block has left/right edge handles. Dragging an edge previews the
  snapped range with the same draft overlay and commits on release. The right
  edge cannot come closer than one snap unit (one bar in Bar mode, one beat in
  Beat mode, 100 ms in Free) to the start, and the left edge cannot come closer
  than one unit to the end; `maximumStart`/`minimumEnd` derive the unit from the
  detected grid.
- Escape and pointer-cancel clear the interaction and discard the draft.
- Plain clicks on empty lane space seek to the clicked time; clicks on a section
  block still seek to its start. Add section, Split, rename, numeric start/end
  editing, Delete and Loop are unchanged; the Loop button and editor controls
  stop propagation so they do not start a create drag.
- Handles and the draft are styled in `styles.css`; the timeline disables text
  selection and touch panning while dragging.

### Verification

- Seven new SectionLane pointer tests (MouseEvent dispatched as pointer events
  because jsdom has no PointerEvent): bar-snapped create with visible draft
  (left/width 200/200 px) followed by onChange only on release; beat and free
  create; empty-lane click seeks without any onChange; Escape and pointercancel
  discard; right-edge resize snaps to 2–4 s and clamps a too-short drag to the
  one-bar minimum; left-edge resize to 4–6 s; edge click without movement does
  nothing. Existing Add/Split/rename/delete/Loop/click-seek tests still pass.
- Real Firefox smoke test at 1280 px against a mocked API: drag created a draft
  and a bar-snapped section (10–16 s), dragging its right handle resized it to
  10–16 s with bars, a plain lane click made no section, Escape during a drag
  discarded it, and there were no page errors.
- `make test-web`: exit 0, 49 files / 449 tests.
- `make build-web`: exit 0. No dependency added.

### Limitations

- Only the left/right edges resize a section; dragging its body is reserved for
  the existing click-to-seek behaviour.
- In Free mode the minimum section length is 100 ms because there is no musical
  snap unit.

## 2026-10-31 — stabilize the spectrogram performance test (t24)

The performance test flaked during t23 when the host was busy: it asserted the
best CPU time as well as the best wall time, and a loaded scheduler could push
every CPU sample over 100 ms even when the view change itself completed quickly.

- Kept the workload and threshold unchanged: 5 minutes of 44.1 kHz PCM, a
  1280 × 256 log-frequency view, 2048-sample FFT, one 32-column warm-up, and the
  100 ms acceptance target.
- After the warm-up the test now performs exactly three independent measured
  runs (`MEASURED_RUNS = 3`), prints every wall and CPU value plus best wall,
  best CPU and median CPU, and asserts only that the best wall time is under
  100 ms. CPU values remain printed for diagnosis; they no longer decide the
  capability check. The wall metric is the documented acceptance target in
  `PERFORMANCE.md`.
- Proof under load: five consecutive `web/node_modules/.bin/vitest run
  src/spectrogram` executions ran while `make test-backend` was executing its
  pytest suite (223 passed, 7 skipped in 55.47 s). All five exit 0, 61 tests
  each, with these printed best walls: 54.5, 55.2, 62.6, 78.7 and 67.2 ms.
  Example full line: `wall=[114.4, 111.7, 67.2] ms, cpu=[121.9, 125.4, 66.6]
  ms, best wall=67.2 ms, best cpu=66.6 ms, median cpu=121.9 ms`.
- `make test-web` passes; no other test was changed.

`PERFORMANCE.md` still describes the earlier five-run methodology and the CPU
assertion. It lies outside t24's declared scope (`performance.test.ts` only), so
it was not edited; its acceptance target (best wall under 100 ms) is unchanged.
