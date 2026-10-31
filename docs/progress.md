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
