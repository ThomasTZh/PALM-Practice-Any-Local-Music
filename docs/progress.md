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
