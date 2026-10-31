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

Filled in from the actual runs of this task; see the command output recorded
with the task completion. Commands: `make doctor`, `make bootstrap` (twice),
`make fixtures` (twice, with digest comparison), `make gate`,
`python scripts/studio.py fixtures-check`, and the legacy worktree test.
