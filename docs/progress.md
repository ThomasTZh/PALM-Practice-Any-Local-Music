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
