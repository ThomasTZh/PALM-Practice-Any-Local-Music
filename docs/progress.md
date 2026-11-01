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

`PERFORMANCE.md` was updated after t24 to describe the three-run/best-wall
methodology and to record three measured runs (best walls 50.1, 53.6 and
56.2 ms under suite contention).

## 2026-10-31 — field report and follow-up fixes (user session, Firefox)

The user ran a full `Carousel Theory Full Mix V1 (With Limiter).wav` session in
Firefox and reported the items below. They are recorded as given, not inferred.

| Checklist item | User result |
|---|---|
| Play 60 s at 1x | pass: no clicks, dropouts or pitch drift |
| 0.5x / 1.5x | pass: pitch stayed the same, no warble or metallic artefacts |
| Pitch +2/-2 st | works, but the listener judged the control useless (kept, no change) |
| Stem separation | no control was visible anywhere (defect) |
| Analysis | QM reported Ab major; the listener hears F minor (relative keys, accepted). BPM, bars and beats good; chords acceptable |
| Sections | worked but hard to use; the listener wants click-drag creation. Metronome sounded good |
| Save/reopen | no save button; the status read "save failed"; after a server restart the song, chords and analysis were still there but the section was gone |
| Playback behaviour | sometimes started on its own; the play button did not reflect playback started from another path; no autoplay when opening a project was requested |

Root cause of the save failure, found in the code: the analysis job writes the
project document and bumps its revision server-side, but the shell kept the
revision read at open time. The next `PUT /api/projects/{id}/state` therefore
returned 409, the status showed "save failed", and sections were never persisted
(analysis itself was persisted, which is why chords survived the restart).

Follow-up tasks and commits:

- t21 `127fad7`: Separate stems control with determinate progress, cancel,
  Re-separate/cache hint and activation of the four stems while preserving
  position, speed, pitch, loop, sections, metronome and paused/playing state.
- t22 `8ef93e5`: refresh the revision after analysis; one 409 refresh-and-retry
  in `saveState`; opening never plays; section click only seeks; the transport
  toggle follows direct engine `play()`/`pause()`.
- t23 `7e5b15b`: drag on the section lane to create (bar/beat/free snapping,
  live draft, Escape/pointercancel cancels) and edge-drag to resize.
- t24 `5260333`: spectrogram performance test asserts best wall of three runs,
  CPU printed for diagnosis only.
- t25 `d817b86`: the golden path waits for the created section to appear in the
  server state before reopening, and fails explicitly if it never does.

Verification on the final tree:

- `make gate` exit 0: pytest 223 passed / 7 skipped; web 49 files / 449 tests;
  tsc and Vite build; e2e 29.1 s on Firefox and Chromium.
- `make e2e` five consecutive runs passed on the stabilized tree (t25), with the
  saved-section annotation, speed deltas 0.80-0.90 s, loop wrap and the
  unchanged export assertions.

Still to do after these fixes: one repeat listening pass covering the new stem
control and mixer, section dragging, and save/reopen/export. The relative-key
ambiguity (Ab major vs F minor) is accepted as plugin behaviour.

## 2026-11-01 — full-width stage, left mixer rail and waveform-first order (t26)

### Layout

- The fixed 940/960 px stage is gone. `App` measures a `.stage-measure` element
  inside the stage with `getBoundingClientRect`, uses the fallback
  `window.innerWidth - rail/gaps/padding` before the first measurement, and
  observes both `ResizeObserver` and window `resize`. One `stageWidth` value is
  passed to TimeRuler, every WaveformPane, SpectrogramPane, ChordRibbon and
  SectionLane and used by fit/zoom/zoom-to-selection.
- On a width change the viewport keeps its zoom factor relative to fit and its
  start time, clamped to the new width, so the playhead and zoom stay aligned.
  The playhead x position is identical in ruler and waveform (unit-tested).
- `.studio-main` is a two-column grid: a 240–280 px left rail and the stage.
  The rail holds the mixer first and the library below it. The stage is a
  vertical flex column containing the toolbar, shared timeline (ruler, mix
  waveform, stem slot, spectrogram), chord ribbon, section lane, then analysis
  and practice.
- `stem-lanes` is the reserved slot between the mix waveform and spectrogram.
  It is driven by `project.stems` (`data-stem-count`, `data-stem-ids` and one
  `stem-lane-slot-<id>` placeholder per stem) for t28 to replace with real
  per-stem waveform panes.
- All existing testids and controls are unchanged; the mixer keeps its
  separation/progress/cancel UI inside the rail.

### Verification

- Unit tests measure a mocked 1234 px stage: ruler, waveform SVG, spectrogram,
  chord ribbon and section timeline all report 1234 px; after a 720 px resize
  all report 720 px. A seek at 4 s leaves ruler and waveform playheads at 617 px
  (1234 px) and 360 px (720 px), proving shared alignment.
- Order test: mix waveform → `stem-lanes` → spectrogram → chord ribbon →
  sections; the stem slot reports 4 stems from the project; the mixer and
  library are descendants of `studio-rail` and the mixer is not inside the
  stage/right column.
- Firefox smoke at 1280 and 1600 px with a mocked API: no horizontal overflow,
  rail at x=19–299, stage 948/1268 px, all panes 924/1244 px, order correct,
  4 stem slots, no page errors.
- `make test-web`: exit 0; `make build-web`: exit 0. No dependency added.

A first `make test-web` invocation hit the pre-existing spectrogram best-wall
perf flake under host load; the immediate rerun passed. The layout change does
not touch that test.

## 2026-11-01 — synced per-stem waveform lanes (t28)

### What landed

- `fetchStemPeaks(projectId, label, {buckets})` on the t4 API client requests
  `GET /api/projects/{id}/stems/{label}/peaks?buckets=N` from t27 and returns the
  raw BSPK bytes, with the same 256/1024/4096/16384 validation and HTTP error
  handling as mix peaks. `createShellApi` forwards it and `createFakeApi` records
  it for component tests.
- App loads peaks for every project stem on open and again after separation
  activates a new stem set. Fetch failures keep the lane visible with its label
  and "Waveform unavailable" rather than failing the whole project open.
- Stem lanes are ordered vocals, drums, bass, other (unknown labels after them),
  rendered as WaveformPane lanes between the mix waveform and the spectrogram,
  each at 64 px, labelled from the project's stem name. The container keeps
  `data-stem-count`/`data-stem-ids` in that order and is empty/hidden before
  separation.
- Stem lanes receive the mix's viewport, selection, playhead, seek, play/pause
  and follow callbacks, and the measured stage width. `follow` is owned by the
  mix lane to avoid four duplicate follow effects; zoom/scroll on any stem lane
  updates the shared viewport.

### Verification

- API client tests assert the exact per-stem URL with buckets=4096 and a 404
  stem-cache failure.
- App component tests with a fake API: opening a 4-stem project calls
  `stemPeaks:p1:vocals`, `drums`, `bass`, `other` and renders
  waveform-vocals → waveform-drums → waveform-bass → waveform-other with labels
  and the 4 ids in that order. After seeking to 4 s ruler and mix/stem playheads
  are within one pixel; ctrl-wheel zoom on the vocals lane changes the shared
  zoom and keeps every lane's playhead aligned. The resize test includes all
  four stem SVG widths (924/1244 px in the browser smoke; 940/1234/720 px in
  jsdom).
- The separation success test asserts no stem lanes before separation and four
  lanes plus a fresh set of per-label peaks calls after activation.
- Firefox smoke at 1280/1600 px: mix and four stem SVGs all 924/1244 px, order
  and labels correct, no horizontal overflow, no page errors.
- `make test-web` and `make build-web` pass. No dependency added.

A full-suite run under host load hit the pre-existing spectrogram best-wall
flake; the retry used for the final verification passed.

## 2026-11-01 — silence until explicit play (t30)

### Root cause

`PlaybackCore` initialised `paused = false`, and `PcmTransport.load` created
the worklet node, posted a seek and delivered PCM without ever posting a
pause. The engine therefore rendered as soon as data arrived while the
transport was paused: opening a project or seeking while paused could make
sound the UI did not reflect. A second contributor was `core.seek()`, which
reset `paused = false` on every reposition, so a paused seek resumed audio.

### Fix (web/src/player only)

- `PlaybackCore` now starts with `paused = true`; no PCM, metronome or
  count-in render happens before `resume()`.
- `seek()` no longer clears the pause flag. It still resets the stream,
  engine state and ramps, so a paused seek is silent; a seek during playback
  keeps playing.
- `PcmTransport.load()` posts `{type: "pause"}` to the freshly created node
  before any PCM source is created, before the seek and before the first
  chunk. This is belt-and-braces: even if the worklet default changed, an
  explicit pause is already queued ahead of all data.
- `PcmTransport.updateGrid(grid)` is now a public control (bpm, bpb, beat
  list). It updates tempo/beats without touching playback; the
  `createStudioPlayer` adapter uses it for `player.updateGrid` and grid
  changes. Speed, pitch, loop install, metronome and grid updates while
  paused leave the pause flag and transport state untouched.
- No UI state mapping or autoplay rule changed (`web/src/state/`, App and
  main were not touched).

### Tests

- `silence.test.ts` (real committed WASM): a fresh core fed a 4 s tone but
  never resumed renders 8 quanta of exact silence and leaves the PCM queued;
  resume produces signal; pause fades through the existing 5 ms ramp and
  stays silent; a second resume works; paused seek, loop install, rate and
  transpose changes stay paused and silent.
- `transport.test.ts`: a new node receives `pause` first, before `seek` and
  before the first `channels` message; seek, updateGrid, setSpeed and setLoop
  while paused settle back to `paused` and post no `resume`.
- Heavy loop/session tests now declare a 30 s timeout (they were within the
  default 5 s alone but could exceed it under the full-suite parallel load;
  the assertions were unchanged).

### Verification

- `web/node_modules/.bin/vitest run src/player`: exit 0, 11 files, 107 tests.
- `make test-web`: exit 0 (whole web suite).
- `make build-web`: exit 0 (`tsc --noEmit` + Vite build).

## 2026-11-01 — working follow, horizontal scrollbar, four-bar sections (t29)

### Follow

`followViewport` now pages instead of centering: while the playhead is before
70 % of the visible span it leaves the viewport alone; at/after the page line
(or when a loop jumps behind the window) it moves the start so the playhead sits
at 20 % of the span, clamped to the track. WaveformPane only runs this while
`follow && playing`, so toggling Follow off stops auto-scrolling immediately.
Tests cover below/at the 70 % line, paging forward, loop-jump back, follow-off,
and the App-level scrollbar thumb moving while following.

### Scrollbar

New `TimelineScrollbar` (panels/waveform) renders a real horizontal scrollbar
under the shared timeline only when `widthPx * secondsPerPixel < duration`.
The thumb width is the visible fraction of the track and its left is the
viewport start fraction (minimum 24 px). Pointer drag on the thumb converts
pixels to seconds and calls the shared `onViewportChange` with `clampViewport`,
so ruler, mix and stem lanes move together; zooming updates the thumb; the
scrollbar has role=scrollbar with aria values. Wired in App with the measured
stage width; hidden at fit.

### Four-bar default section

`draftSectionRange` with no selection now spans four bars: bar length is derived
from the detected grid (`beat span × bpb`), or 4/4 at 120 BPM when no grid is
available. The start still follows the selected snap mode (Bar default), and
the result is clamped to the track and passed through the existing bar/beat
snapping. Add with a selection still uses the selection. SectionLane and state
tests cover the detected 3/4 grid (7.2 s), 4/4 at 120 (8 s), beat/free starts,
and the clamp at the end of a short track.

### Verification

- Pointer/component tests: scrollbar hidden at fit, proportional thumb at two
  zoom levels, drag from 0 to 21.25 s, scrollbar-only-when-zoomed; follow paging
  and follow-off; four-bar Add on detected and fallback grids. App test drags
  the thumb and checks aria-valuenow advances; follow test uses the fake player
  position to page and confirms no movement after Follow is toggled off.
- Firefox smoke at 1280 px: scrollbar absent at fit, appears after two zooms
  (thumb 411 px), drag moved aria-valuenow 17→30, Add produced Section 1
  0–8 s (four bars at 120 BPM), no page errors or overflow.
- `make test-web` passes (51 files / 469 tests in the full run); `make
  build-web` passes. No dependency added.

## 2026-10-31 — second field report, layout round and the autoplay root cause

Second Carousel session on Firefox after the t21-t25 fixes. Results as reported:

| Item | User result |
|---|---|
| Stem separation | button found, separation works well |
| Save/reopen | saving works now |
| Sections | drag creation works, much easier to use |
| Autoplay / button sync | still present: playback starts after opening and after clicking a section |
| Pitch | still judged unnecessary (unchanged) |

Root cause of the autoplay, found by inspection and confirmed by inspection of
the committed worklet: `PlaybackCore` initialised with `paused = false`, and
`PcmTransport.load()` created the node, posted a seek and delivered PCM without
ever posting a pause. The engine therefore rendered audio as soon as data
arrived while the transport state was `paused`; the UI was not lying, the audio
was. Fixed in `19bc862`: the core starts paused, the transport posts a pause
before any PCM, and a paused seek no longer clears the pause flag. Real-WASM
tests assert exact silence on load/after pause and signal only after resume.
This needs one listening confirmation from the user.

Feature requests from the same session, implemented:

- `178e623` (t26): full browser width via one measured stage width, mixer moved
  to a left rail, vertical order mix waveform, stem-lane slot, spectrogram,
  chords, sections.
- `2d43bb2` (t27) + `4595c2a` (t28): per-stem BSPK peaks endpoint and synced
  waveform lanes for vocals, drums, bass, other, sharing viewport, playhead,
  zoom and width.
- `8e34ef3` (t29): paginated follow at 70 percent of the visible span, a real
  timeline scrollbar with proportional thumb, and a four-bar default section.
- `413be8a` (t31) + `3d86373` (t32): serialized web suite with 30 s timeouts
  (measured failures under load: 5 s timeouts in real-WASM player tests,
  spectrogram samples of 100-571 ms), and a golden path that derives the loop
  range from the created four-bar section instead of a hard-coded 2 s.
- `3098d12`: missing `fetchStemPeaks` forwarder in `createShellApi`, which t28
  had left uncommitted.

Final verification on the committed tree (`3d86373` plus the docs commit):

- `make gate` exit 0: ruff/format, 6 fixtures, strict mypy, pytest 228 passed /
  7 skipped, tsc, serialized web suite 57.8 s (51 files / 469 tests), Vite build,
  e2e 35.8 s on Firefox and Chromium.
- t32: five consecutive `make e2e` runs passed, each deriving the 0-7.98 s
  section range and observing a real wrap.
- t33: five consecutive `make test-web` runs passed while the backend suite ran
  continuously (64, 59, 62, 68, 68 s); spectrogram best wall 55 ms.
- Remaining human step: one listening pass for the silence-on-open/seek fix and
  the new layout, stem lanes and scrollbar. The manual checklist is otherwise
  satisfied by the two sessions above.

## 2026-11-01 — compact bottom transport, no header, tighter panels (t34)

### Shell

- Removed the whole top header (title, status line, Track/Key/BPM row).
- Track, Key and BPM/bpb now live in the bottom transport bar to the right of
  the transport buttons/readout, keeping `project-title`, `key-readout` and
  `bpm-readout`. The Speed select is gone from the transport; the Practice panel
  still owns `Practice speed`.
- The transport sits in a fixed-height bottom region of a 100dvh flex shell;
  `.studio-main` is the only scrolling container (`overflow-y:auto`, hidden
  scrollbar with `scrollbar-width:none` and ::-webkit-scrollbar display none).
  `html/body/#root` are height-bound with overflow hidden, so no page scrollbar
  exists. Status line, selection/zoom and `save-status` are a thin unobtrusive
  strip above the transport (`status-line`, `status-detail`, `save-status` kept).
- Waveform wheel handling now only prevents the default when the timeline can
  actually scroll horizontally; at fit the wheel falls through to the page's
  main scroll container instead of trapping it over the waveform.

### Panel compaction (1280 × 800, Firefox, mocked API)

| panel | before | after | reduction |
| --- | --- | --- | --- |
| Practice | 157 px | 110 px | 29.9 % |
| Analysis | 141 px | 80 px | 43.3 % |

Practice controls are a 3-column compact grid with smaller selects/buttons/
sliders and no controls removed. Analysis moved Beats-per-bar and Run analysis
into the header row next to the cached badge, tightened padding/gaps and the
KeyBPM readout/summary; every control remains.

### Browser smoke and e2e

- At 1280×800: no header/h1, transport top 721 / bottom 795 (fully visible),
  metadata at x 1091–1259 vs buttons x 21–193, main scrollHeight 993 / client
  689, wheel scrolled it to 214 px with the transport still at 721–795,
  document scroll size exactly 1280×800, no page scrollbars, no `Speed` select,
  Practice speed present, status/save testids present.
- At 1600×800: document 1600×800, transport 11–1589, no overflow. Wheel over
  the waveform scrolled main by 262 px, transport stayed pinned.
- Golden path now waits for `transport-toggle` (not the removed heading) and
  asserts the Practice speed select; `make e2e` passes.
- `make test-web`, `make build-web`, `make e2e` all pass. No dependency added.

## 2026-11-01 — stage width and native scrollbar containment (t35)

### Reproduction and source

On the current main the reported "stuck ~960 px stage, missing rail" state did
not reproduce: prior layout commits already removed the fixed VIEW_WIDTH and
put the rail in the grid. At 1280 the stage was already 963 px wide and ended at
the main area's right edge. What remained was a native horizontal scroll
container: `.timeline` had `overflow-x: auto`, so any transient mismatch between
the measured SVG/timeline width and its host could produce the grey scrollbar in
the screenshot. The containment was also implicit (grid/flex defaults) rather
than declared.

Source evidence before the fix (Firefox, 1280×800, mocked project, after open):
`.timeline` computed overflowX `auto`; document/body 1280/1280; rail 280 px;
stage 963 px. After zoom the custom green scrollbar appeared but the native
container remained configured.

### Fix

- `.timeline` is now a clipped viewport (`overflow-x: hidden`, `overflow-y:
  hidden`) with `width/max-width:100%`; the only horizontal navigation is the
  green TimelineScrollbar, which moves the shared viewport rather than scrolling
  a native element.
- Declared width containment on `.studio`, `.studio-main`, `.studio-column` and
  `.stage` (`width/max-width:100%`), and `overscroll-behavior-x:none` on main.
- No fixed stage width is used; App still measures the stage and the rail stays
  at 280 px.

### Browser/e2e measurements (new web/e2e/layout.spec.ts)

Both Firefox and Chromium pass the layout spec at 1280×800 and 1920×1080 after
opening a real fixture and zooming twice:

| viewport | rail | stage | stage right / main right | document client/scroll | green thumb | native overflow |
| --- | --- | --- | --- | --- | --- | --- |
| 1280×800 | 280 | 963 | 1269 / 1269 | 1280 / 1280 | 417 | none |
| 1920×1080 | 280 | 1603 | 1909 / 1909 | 1920 / 1920 | 701 | none |

body scrollWidth equals clientWidth at both sizes, no descendant with
overflowX auto/scroll has scrollWidth > clientWidth, and `.studio-main` reports
scrollbar-width none while remaining `overflow-y:auto`. The spec also drags the
green thumb (aria-valuenow increases) and wheels the main area at 1280×640,
asserting main scrollTop advances with the transport still inside the viewport.
`make e2e` passes 2 spec files (golden path + layout) on both browsers.

`make test-web`, `make build-web` and `make e2e` pass. No dependency added.

## 2026-11-01 — count-in independent of metronome and loop (t37)

### Rule change

Count-in was gated on a loop being installed (`countInBars > 0 && loop`) and
its clicks shared the metronome click pool, so a user with the metronome off
heard nothing. Now:

- `PcmTransport.play()` sends the count-in whenever `countInBars > 0`,
  whether or not a loop is installed, using the current `setTempo`/`updateGrid`
  bpm/bpb (detected grid or the 120/4 fallback).
- `PlaybackCore` owns a second `ClickMixer` (`countInClicks`, fixed 0.8)
  separate from the metronome pool. Count-in clicks are rendered only during
  the count-in phase and are audible even when the metronome volume is 0.
- After the count-in the normal path resumes: metronome clicks follow the
  toggle exactly as before (0 = silent, 0.5 volume = audible), and loop
  wrapping / speed / pitch behaviour is unchanged.
- `pause()` and `seek()` clear both click pools; no count-in voice leaks into
  playback.

### Tests (real committed WASM)

`count-in.test.ts` asserts the click frames for the four cases:
loop/no-loop × metronome off/on. One bar at 120 BPM 4/4 gives count-in clicks
at 0 / 24 000 / 48 000 / 72 000 output frames in every case; with the
metronome off there are no clicks at or after 96 000; with it on the next four
clicks land at 96 000 / 120 000 / 144 000 / 168 000. Additional cases cover a
detected 3/4 grid at 100 BPM (28 800-frame beats), a two-bar fallback
count-in, and 0.5× with no loop (count-in stays output-time, playback starts
after it).

`transport.test.ts` sends a count-in with `loop === null` and metronome volume
0; `studio-player.test.ts` sends `{bars:1,beatsPerBar:3,beatFrames:28800}`
for a 100 BPM 3/4 detected grid with the metronome off and no loop.

### Verification

- `web/node_modules/.bin/vitest run src/player`: exit 0, 12 files, 116 tests.
- `make test-web`: exit 0.
- `make build-web`: exit 0.
- `make e2e`: exit 0 (2 spec files; the earlier attempt lost Playwright trace
  artifacts to a concurrent run sharing `web/test-results`, not an app
  assertion failure — the rerun passed).

## 2026-11-01 — ordered left rail with Analysis and Practice (t36)

### Layout

- The right `.studio-column` is gone. `.studio-main` is a two-item grid: the
  rail and the stage. The rail contains, in DOM order, Analysis, Mixer, Practice,
  then Library; the stage keeps all remaining width.
- `.studio-rail` is sticky at the top of the main scroll area with its own
  `max-height: calc(100dvh - 7.5rem)` and hidden `overflow-y:auto` scrollbar.
  It therefore scrolls independently; the main area still scrolls the stage,
  and the pinned transport/status strip is outside both.
- Rail-specific compaction keeps Practice usable at 280 px (2-column controls,
  48 px sliders); the panel testids/controls are unchanged.
- At ≤820 px the stage comes first and the rail is static/non-scrolling.

### Browser smoke (Firefox, mocked 4-stem project)

At 1280×800: rail order `analysis, mixer, practice, library`, no
`.studio-column`; rail 280×688 with scrollHeight 1142; wheel over the rail moved
its scrollTop to 226.7 while main scrollTop stayed 0; transport stayed at
y 721–795. Stage width 963 ending at main right 1269. Document/body
1280×1280x800x800, no native overflow container.

At 1600×800: stage 1283 ending at 1589, rail still 280, document 1600×1600,
transport pinned, no native scrollbars.

Golden path and the layout spec both pass with the panels in the rail
(`make e2e` 2 specs, Firefox + Chromium). `make test-web` and `make build-web`
pass. No dependency added.

## 2026-11-01 — Sections timeline-first layout with sorted split editor (t38)

### Layout

- The Sections panel now renders, in order: the section timeline (blocks/drag
  editing), then the heading row (Sections, Snap, Add section, Split), then the
  editor.
- The editor is a two-column grid: left `.section-list-pane` with the sorted
  section list, right `.section-loop-pane` (`data-testid=section-loop-editor`,
  aria-label "Loop customisation") reserved for t40's chain-loop controls.
- The list sorts by start time ascending, then id. Each row shows the name
  input, Start/End numeric resize inputs, Loop and Delete. Loop in the list uses
  a distinct accessible name (`Loop <name> from section list`) so the block
  Loop buttons keep their old labels.
- Existing block drag-create/resize/click-seek and block Loop wiring are
  untouched; the list uses the same rename/resize/delete/loop helpers.

### Verification

- SectionLane tests (23) add: lane children exactly timeline → toolbar →
  editor split; split children list/loop panes; list order early/middle/later
  for sections supplied in the order later/early/middle; name/start/end values;
  and list Loop calling setLoopRange/setLoopEnabled/onLoop. All pointer
  drag-create, resize, cancel, click-seek and block loop tests still pass.
- Firefox mock at 1280×900: lane children
  `section-timeline, panel-header section-toolbar, section-editor-split`;
  split children `section-list-pane, section-loop-pane`; list order
  early/middle/later with names Verse/Bridge/Chorus; halves 455/455 px; 3 loop
  and 3 delete controls; loop placeholder text present; no page errors. Compact
  rows are 60 px high and the lane is 337 px (down from 403 before the row CSS).
- `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No dependency
  added.

## 2026-11-01 — move sections, overlap lanes, end-at-playhead Add (t39)

### Interactions

- Section bodies can be dragged (pointer down on the body, move, release). The
  move is snapped with the current Snap mode, clamped to the track, and keeps
  the original length. A pointer capture plus a one-tick click guard prevents
  the trailing click from also seeking; a plain click without movement still
  seeks. Edge handles and the Loop button stop pointer-down so they keep their
  resize/loop behavior.
- Overlaps are allowed. Visible blocks are assigned to the first free lane using
  their time ranges; the timeline min-height grows by 20 px per lane and blocks
  are offset with z-index and a highlighted overlap style, so every block stays
  visible. The existing blocks still render in time order independently of lane.
- Add section with no selection now ends at the snapped playhead and starts four
  bars earlier, clamped after the previous section's end. The end keeps the
  chosen snap mode; free mode preserves the clamped start exactly. If there is
  no room, it creates nothing and reports the reason (name/end/playhead) through
  the App status line. With no sections at the very start it places the first
  four bars from the first grid downbeat, which matters for recordings whose
  bar grid starts at e.g. 0.01161 s.
- Drag-create on empty lane space, edge resize, Split, click-seek, and list
  sorting by start time remain unchanged.

### Verification

- SectionLane 29 tests (new: body move with length preserved + list re-sort,
  overlap lanes and min-height, end-at-playhead with previous, start clamping,
  no-room message, list re-sort after add). State 39 tests (moveSectionRange
  snap/clamp/length; draftSectionEndingAt four bars, previous clamp, refusal,
  no-sections start fallback, offset-grid first-downbeat fallback).
- Firefox mock: overlapping Verse/Chorus drew at lanes 0/1 (top 26/46 px,
  timeline 74 px); moving Verse two bars re-sorted list to Chorus, Verse, Outro;
  Add at the start with an existing section reported "No room..." and created
  nothing; no page errors. Real e2e server (grid offset 0.01161 s): Add created
  Section 1 0.01161-8.01161 s (four bars), and the golden path loops/exports
  successfully.
- `make test-web`, `make build-web` and `make e2e` (2 specs, Firefox +
  Chromium) pass. No dependency added.

## 2026-11-01 — chain-loop selected sections (t40)

### Loop customisation pane

- The right pane of the Sections editor now lists the sections sorted by start
  with a checkbox each (`Select <name> for loop chain`) and their start-end
  range.
- `Loop selected` is disabled until at least two sections are selected. It
  sets the player loop from the earliest selected start to the latest selected
  end, gaps included, enables looping, and reports both in the pane and in the
  status line as e.g. `3 sections, 0.0-16.0 s`.
- `Clear loop` clears the selection, disables the player loop and clears its
  range, reports `Loop cleared`, and is available at all times.
- Per-section Loop buttons (timeline blocks and sorted list) are unchanged and
  still loop only that section.
- The pane derives its chain from the sorted section list, so selecting,
  moving or adding sections keeps the count/range in start order.

`sectionChainRange` in state/sections.ts is the pure min-start/max-end helper.

### Persistence

The chain calls the same player `setLoopRange`/`setLoopEnabled` seam as the
per-section loop, so the existing practice autosave writes the range to the
server loop frames. A new App test selects two gapped sections, checks autosave
writes start_frame 0/end_frame 264600 (6 s at 44.1 kHz), recreates the project
from the saved loop, and verifies the reopened player range and Practice loop
are restored.

### Verification

- SectionLane 32 tests (two-section chain with gaps, three-section chain ordered
  by start, disabled at 0/1 selected, clear selection/loop, existing single
  Loop); state 41 (chain range min/max); App 21 (chain status, autosave payload,
  reopen practice loop). Full suite green.
- Firefox mock: initial/one-selected disabled; two-selected enabled; loop
  reported `2 sections, 0.0-8.0 s`, then `3 sections, 0.0-16.0 s`; Clear
  reported `Loop cleared`, unchecked all, no page errors; screenshot shows the
  right-pane checkboxes, selected count/range and both actions.
- `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No dependency
  added.

## 2026-11-01 — remove user-facing pitch shifting (t41)

### UI and public seams

- Practice panel no longer renders the Pitch slider or `pitch-value` readout;
  the transport never had one. The control grid now contains Speed, Loop,
  Count-in, Metronome, Accent, volume and Snap unchanged.
- `PlayerState`/`StudioPlayer`, `PracticeState`/`PracticeController` and both
  fake/local implementations no longer expose `pitchSemitones` or
  `setPitchSemitones`; pitch clamp constants were removed. The App, studio
  runtime snapshot/restore and StudioPlayer adapter no longer copy pitch.
- Autosave (`ServerPracticeState`/`buildServerState`) no longer writes
  `pitch_semitones`. `practiceFromDocument` ignores old `pitch_semitones` and
  camel-case `pitchSemitones` fields, so a saved project containing either loads
  normally without a restored pitch value.

### Internal transpose

The audio transport/PlaybackCore transpose API stays internal for its existing
speed/loop/audio tests. The StudioPlayer adapter no longer calls
`transport.setPitch`; transport starts at transpose 0. This avoids ripping up the
WASM stretch path while ensuring no user-facing pitch API remains.

### Verification

- Targeted 90 tests across state/player/practice/project/runtime, PracticePanel,
  StudioPlayer adapter and App suites pass. Existing speed, loop, metronome,
  count-in and section tests are unchanged and green. `make test-web`,
  `make build-web` and `make e2e` (2 specs) pass.
- Firefox mock with legacy `pitch_semitones:-3` and `pitchSemitones:-3` opened
  without errors or alerts: zero Pitch controls, no semitone readout, while
  Speed/Loop/Count-in/Metronome/Accent/volume/Snap remained. The only "pitch"
  text matches were the test project title "NoPitch".
- No dependency added.

## 2026-11-01 — third layout round (t35-t41) and final gate

Requests from the user's third pass, and what was done:

| Request | Result |
|---|---|
| Native grey scrollbar still present, layout sometimes broken | t35 `740e6fd`: the remaining native scroller was `.timeline` (`overflow-x:auto`). It is now a clipped viewport; the green TimelineScrollbar is the only horizontal navigation. Explicit width containment on studio/main/column/stage, `overscroll-behavior-x:none`. New `web/e2e/layout.spec.ts` asserts document/body widths at 1280x800 and 1920x1080, rail 280, stage 963/1603, no native overflow. |
| Move Analysis and Practice into the left rail, order Analysis, Mixer, Practice, Library | t36 `b4d8fb6`: right column removed, sticky 280 px rail with independent hidden scroll; stage takes the remaining width; transport stays pinned. |
| Sections: timeline first, heading/snap below, sorted list, two columns (list left, loop right) | t38 `dc068e2`: exactly that order; list sorted by start time; `section-loop-editor` reserved and filled by t40. |
| Section body drag moves; Add section ends at the playhead | t39 `58fbd53`: body drag preserves length, overlaps allowed and drawn as stacked lanes; click still seeks. Add with no selection ends at the snapped playhead, four bars, clamped after the previous section, with a status message when there is no room. The first downbeat case starts on the grid downbeat. |
| Loop multiple connected sections | t40 `b5b746e`: checkboxes in the loop pane; Loop selected runs earliest start to latest end with gaps included, disabled below two; Clear loop; per-section Loop unchanged; persists through autosave. |
| Remove pitch | t41 `eb010c0`: controls and readouts removed; `pitchSemitones`/`setPitchSemitones` removed from PlayerState/StudioPlayer/PracticeController and autosave; legacy saved fields are ignored. Internal transport transpose remains for audio tests only. |
| Count-in clicks even with metronome off | t37 `4431b13`: count-in on any play when bars are set, dedicated 0.8 click pool independent of metronome volume; the metronome follows the toggle after the count-in. Real-WASM tests cover loop/no-loop x metronome off/on. |

Final gate on the committed tree (`eb010c0` plus docs):

- `make gate` exit 0: ruff/format, 6 fixtures, strict mypy, pytest 228 passed /
  7 skipped in 57.3 s, tsc, serialized web suite 52 files / 503 tests in 87.2 s,
  Vite build, e2e 2 specs (golden path + layout) in 45.8 s on Firefox and
  Chromium.
- Earlier stability evidence still stands: five consecutive e2e runs (t32) and
  five consecutive `make test-web` runs under a concurrent backend suite (t33).
- Remaining human step: one listening pass covering the silence-on-open fix, the
  pinned/compact layout, stem lanes, section move/overlap, chain loop and the
  count-in with the metronome off.

## 2026-11-01 — three-zone bottom bar, practice controls moved down (t42)

### Rail and practice controls

- The left rail is now Analysis, Mixer, Library only. PracticePanel is rendered
  in the bottom bar's left zone and no longer has its own panel header or Snap
  control; Snap remains only in Sections (`select[aria-label="Snap"]`, count 1).
- The bottom-left practice controls keep their testids/labels and behaviour:
  Practice speed, Practice loop (kept for the golden path and loop state),
  Count-in, Metronome, Accent, Metronome volume and its percentage. The volume
  row is full-width: the range fills the zone and the percentage sits directly
  beside it (no dead gap).
- Stage zoom buttons are now minus (Zoom out) then plus (Zoom in); Fit, Zoom to
  selection and Follow follow unchanged.

### Bottom bar

The transport is a three-column grid: practice zone, centred transport,
track/key/BPM meta. Inside the centre, position time, [return][play][loop],
bar/beat use a 1fr/auto/1fr grid. Play/pause uses an equal-width three-button
grid so it is the exact centre of the button group.

The paused/playing status text was removed visually. `transport-status` remains
as a 1px screen-reader-only node so existing tests and the golden path keep
their status assertions; notices/errors remain visible in the status strip and
transport error row.

### Measurements (Firefox mock, 1280×800)

- rail children analysis/mixer/library; document 1280/1280×800/800, no scroll.
- zones: practice 536×49, centre 389×33, meta 149×29 inside the 1258-wide bar.
- play centre 762.95 = centre-zone centre 762.95; gap return→play 5.25 px =
  gap play→loop 5.25 px. Position ends ~7 px left of the group, bar/beat starts
  ~7 px right.
- volume slider 404 px wide in the 536 px zone, percentage 8 px after it.
- at 1600×800: document 1600/1600, practice 744 px, centre still 389 px,
  play/zone centres 970.63, equal 5.25 px gaps, slider 607 px.
- toolbar first two buttons Zoom out "−", Zoom in "+"; Snap only Sections;
  `transport-status` is clipped 1×1 but keeps its text.

`make test-web`, `make build-web` and `make e2e` (2 specs) pass. No dependency
added.

## 2026-11-01 — single-row section list (t43)

### Layout

- Section list rows are one flex line: name input flexes, then inline Start/End
  numeric editors, Loop and Delete, all vertically centred. Rows use no wrap
  and no fixed row height; each measured 34 px high.
- The pane is a container query context. At the 455 px half width the visible
  "Start"/"End" words and 4 rem numeric fields fit with a 194 px name field.
  Below 360 px the words are hidden and number fields shrink to 3.2 rem; at a
  forced 280 px half width the row still measures 34 px high with name 99 px,
  Loop/Delete visible and row scrollWidth == clientWidth == 280.
- Sorting by start time remains in the left half; chain-loop checkboxes stay in
  the right half.

### Verification

- New SectionLane test asserts exactly five direct row children (text input,
  Start edge label+number, End edge label+number, distinct list Loop, Delete)
  and editable start/end. Existing rename, list/block Loop, Delete, drag-create,
  move, resize and chain-selection tests remain green (33 SectionLane tests).
- Firefox mock with rows supplied out of order (Chorus, Verse, Bridge): list
  order Verse, Bridge, Chorus. At 455 the five controls share y≈489-503; at
  280 all five remain one 34 px line and the labels collapse.
- `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No dependency.

## 2026-11-01 — equal-tempered note labels on the spectrogram axis (t44)

### Axis

- Added pure equal-tempered helpers in `spectrogram/axis.ts`:
  `midiToFrequency`, `frequencyToMidi`, `nearestMidi`, `midiNoteName`,
  `noteLabels` (every semitone inside the axis, highest first, with actual Hz
  and log-axis percent) and `noteAxisHeight` (10 px per label, 148 px floor).
- The default spectrogram range is now C1..C8 (MIDI 24..108,
  32.703..4186.009 Hz). The pane labels every semitone from C1 through B7 to C8
  with note names, positions them at their actual log-frequency rows and exposes
  `data-midi`/`data-hz`; the old Hz labels were removed. Rows/FFT/worker/palette
  are unchanged.
- The pane height defaults to the semitone count (85 × 10 = 850 px); an explicit
  `heightPx` override still works. Label CSS is 8 px/1 line-height at ~10.1 px
  note spacing, so labels do not overlap. Collapse/re-expand still works.
- PERFORMANCE.md notes the range/height change and that the 1280×256 worker
  workload and 100 ms target are unchanged.

### Verification

- Axis tests: 85 labels C1..C8, unique MIDI notes, C#/A4 names, log positions
  for C1/C8, every label round-trips through Hz↔MIDI and nearest-note name,
  height 850/148 floor. Pane test asserts 85 note spans, C1/C#1/A4/C8, no
  "100 Hz", and canvas height 850.
- Firefox mock at 1280×900 after expanding: 85 labels, first C8 (MIDI108,
  4186.009 Hz), last C1 (MIDI24, 32.703 Hz), minimum vertical gap 10.117 px
  against 8 px label height, `overlaps=[]`; canvas style height 850 (bitmap rows
  256); document 1280/1280 (no native scrollbar); Hide/Show toggles body
  hidden/re-expanded.
- Spectrogram suite including the performance test passes (best wall 63.2 ms
  under load). `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No
  dependency added.

## 2026-11-01 — fourth UI round (t42-t44)

User requests and results:

| Request | Result |
|---|---|
| Move all practice controls from the rail into the left part of the bottom drawer | t42 `261470a`: rail is Analysis, Mixer, Library; every practice control (speed, count-in, metronome, accent, volume, practice loop) sits in the bottom-left zone with no panel header. Snap remains only in Sections. |
| Centre the transport with play/pause in the middle and symmetric arrangement; drop the paused/playing text | t42: three-zone bottom bar; equal-width Return/Play/Loop with play at the zone centre (measured 762.95 at 1280), time left and bar/beat right symmetric, track/key/BPM right. `transport-status` kept screen-reader-only; notices/errors still visible. |
| Longer metronome slider | t42: the volume row fills its zone (404 px at 1280, 607 at 1600) with the percentage immediately beside it. |
| Swap zoom buttons to minus then plus | t42: order changed, labels and aria unchanged. |
| Section rows back to one line | t43 `f09f1a0`: name, editable Start, editable End, list Loop and Delete on one 34 px row in the sorted left half; a container query keeps it on one line at 280 px. |
| Note names on the spectrogram axis, every semitone | t44 `a47383b`: C1..C8 (MIDI 24..108, 32.703..4186.009 Hz), every semitone labelled at its log-frequency row with `data-midi`/`data-hz`, pane height 85 × 10 = 850 px, Hz labels removed. Pure note helpers round-trip; the 1280×256 worker workload and 100 ms target are unchanged. |

Final gate on the committed tree:

- `make gate` exit 0: pytest 228 passed / 7 skipped; web 52 files / 506 tests
  (serialized); tsc and Vite build; e2e 2 specs on Firefox and Chromium.
- Remaining human step: one listening/visual pass over the three-zone bottom bar,
  single-row section list and the 850 px note axis, plus the previously
  outstanding autoplay-silence confirmation.

## 2026-11-01 — drawer centring, toolbar readouts, volume revert (t45)

### Bottom drawer

- The metronome volume control is content-sized again: 96 px slider at 1280
  (76 px at ≤1180) with the percentage 7.25 px after it. It no longer spans the
  practice zone; controls wrap naturally.
- The drawer is now `minmax(0,1fr) auto minmax(0,1fr)`. The transport group sits
  in the centred auto column with `z-index:3`; practice/meta are z-index 1, so
  the transport stays above neighbouring content. Practice/meta columns
  `min-width:0`/overflow containment prevent overlap.
- Return/Play/Loop remain equal-width with 5.25 px gaps. Play centre equals the
  whole drawer centre at every tested width: 640.05 px @1280, 511.98 @1024,
  449.93 @900. Practice ends 11.25 px before the centre column; meta starts
  well after it.
- Position time and bar/beat moved out of the drawer into the top-right of the
  stage toolbar via `TransportReadouts`; `transport-position` and
  `transport-bar-beat` are unchanged. At 1280 they occupy x1090-1257, y29-47 in
  the toolbar and are not inside the drawer. The hidden status node stays in
  the drawer for test/golden-path compatibility.

### Verification

- New TransportReadouts tests cover position updates and bar/beat; the old
  in-panel readout tests were removed. App test asserts the readouts are inside
  the stage toolbar and absent from the Transport region.
- Firefox at 1280/1024/900: play centre exactly equals drawer centre, equal
  5.25 px side gaps, z-index 3, no zone overlap, slider 96/76 px with an
  immediate percentage, readouts in toolbar, document/client widths equal and
  no native scrollbar.
- `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No dependency.

## 2026-11-01 — spectrogram frame clamp and stage placement (t46)

### Frame clamp

- SpectrogramPane now takes the asset `frameCount` and clamps the requested
  window before loading: `start = min(frames-1, max(0, floor((start-padding) *
  sr)))`, `end = min(frames, max(start+1, ceil((visibleEnd+padding) * sr)))`.
  If frameCount is zero no PCM request is made. The cache key remains the view
  identity `(start seconds, width, FFT)`; since the clamp is deterministic,
  collapse/re-expand still hits the same cached image.
- App passes `project.frames` (the asset frame count) into the pane.
- New pane regression at viewport `start=299.9`, `0.001 s/px`, frameCount
  `300×44100`: loader gets start>=0, start<end and end exactly the frame count;
  Hide/Show keeps compute at one call (cache stable).

### Stage order

The pane moved out of the timeline block and now renders after the Sections
panel. Stage child order is stage-measure, toolbar, timeline (ruler/mix/stems),
chord ribbon, sections, spectrogram. Collapsing leaves the ruler width unchanged
(939 px before/after in the mock).

### Verification

- Firefox mock 16 s / 705600 frames: Show spectrogram requested
  `/api/projects/p1/pcm?start=0&end=705600`, i.e. end == frameCount, in bounds;
  no out-of-range error (the only error was the mock's deliberate 404).
- Spectrogram suite 71 tests including performance (best wall 65.4 ms) and the
  new near-end test; App order test updated to mix→stems→chords→sections→
  spectrogram. `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No
  dependency added.

## 2026-11-01 — eight-bar default for Zoom to selection (t47)

### Behaviour

- `defaultZoomRange(position, duration, bpm, bpb)` builds four bars either side
  of the playhead using the detected bpm/bpb, or 120 BPM in 4/4 when either is
  missing/invalid, then clamps both ends to the track.
- With no usable selection, App zooms exactly to that range (padding 0) via the
  existing zoom function. At a middle playhead the range is exactly eight bars
  and the playhead is the centre; at the start/end the window is clamped (e.g.
  0-8 s / 52-60 s on a 60 s 120/4 track).
- With a non-empty selection the previous path is unchanged, including its 8%
  framing margin. The Zoom to selection button is no longer disabled when there
  is no selection (or when the selection is empty).

### Tests

- viewport: fallback/NaN grid middle (22-38), start (0-8), end (52-60),
  detected 100 BPM 3/4 (22.8-37.2), short-track positive range, exact fit with
  playhead centre, existing selection margin.
- App: button enabled with no selection; long 60 s track zooms from 100% to
  750% (start window 0-8 s); an existing 15-30 s waveform selection still zooms
  to 345% (selection margin path).
- `make test-web`, `make build-web`, `make e2e` (2 specs) pass. No dependency.

## 2026-11-01 — fifth UI round (t45-t47) and final gate

| Request | Result |
|---|---|
| Revert the stretched metronome volume slider | t45 `8fca17d`: content-sized again (96 px at 1280, 76 px below 1180) with the percentage 7.25 px after it. |
| Play button at the centre of the whole bottom drawer, always on top | t45: equal side columns with an auto centre; Return/Play/Loop centred on the drawer, centre at z-index 3; play centre 640.05 / 511.98 / 449.93 at 1280 / 1024 / 900, gaps 5.25 px, no zone overlap. |
| Move the time and bar/beat readouts to the top-right of the waveform area | t45: new `TransportReadouts` in the stage toolbar top-right; the drawer keeps only return/play/loop and the testids still work. |
| Move the spectrogram below the section list | t46 `6728423`: order is mix, stem lanes, chords, sections, spectrogram; collapse leaves the ruler width unchanged. |
| Spectrogram error "requested end frame ... outside the asset range" | t46: the pane now takes `project.frames` and clamps start/end (start <= frames-1, end <= frames, minimum one frame, zero-frame skip). The 2048-frame overshoot was the FFT padding; a 16 s fixture now requests exactly 0..705600, with a near-end regression asserting end == frameCount. |
| Zoom to selection with no selection | t47 `25be70a`: `defaultZoomRange` builds ±4 bars around the playhead (detected bpm/bpb or 120/4, clamped to the track) and the view zooms to it; a real selection keeps its existing padded path, and the button is always enabled. |

Final gate on the committed tree:

- `make gate` exit 0: pytest 228 passed / 7 skipped; web 53 files / 515 tests
  (serialized); tsc and Vite build; e2e 2 specs on Firefox and Chromium.
- Remaining human step: one listening/visual pass over the drawer centring,
  toolbar readouts, spectrogram position and note axis, and the previously
  outstanding autoplay-silence confirmation.
