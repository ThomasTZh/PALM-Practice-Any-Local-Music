# basseparate — implementation status ledger

Persistent resume point. A fresh agent must be able to continue from this file
plus the repository state. Keep it concise; put long evidence in `docs/evidence/`.

## Current position

- **Milestone:** 0 (Reproducible foundation)
- **Gate:** F in progress
- **Work package:** M0.12 (Verification matrix + package smoke)
- **Next action:** run full verification matrix (backend unit, storage
  integration, HTTP integration, frontend, browser E2E, offline-start,
  lifecycle, package smoke) and confirm all gates pass.

## Completed requirements (with evidence)

- M0.1.2/2.1: Five user WAVs hashed (SHA-256) in `docs/evidence/m0-file-baseline.md`
  (git-ignored local report). Files left in place at `audio2test/`.
- M0.1: `system-inventory.txt` untouched. Main plan moved to workspace root
  (`basseparate_project_plan.md`) to match intended top-level layout; content unchanged.
- M0.1: No repo instruction files (AGENTS.md/.agents/.codex) exist in workspace.
- M0.1: `.gitignore`, `.editorconfig`, `.python-version` (3.11.15), `.node-version` (22.22.2) created.
- M0.1: Git initialized on branch `main` (no placeholder `.git` existed; workspace writable).
  Repo-local identity set (`basseparate-dev`) because none existed.
- M0.1: ADR-0001 (8 foundation decisions) in `docs/decisions/`.
- M0.2: `pyproject.toml` (Hatchling, src layout, console script, `>=3.11,<3.12`),
  `uv.lock` generated, `uv sync --locked` passes; stale lockfile correctly
  refused (verified by temporary fastapi bump).
- M0.2: Python 3.11.15 (uv-managed); system Python untouched; no ML packages in lock.
- M0.2: pnpm 12.8.1 installed in user prefix `~/.npm-global` (no corepack on
  system; PATH line appended to `~/.bashrc`); pinned in root `packageManager`.
- M0.2: `frontend/` scaffold (Vite 8.3.1, React 19.3.0, TS 5.9.3, ESLint 10,
  Prettier, Vitest 5, RTL, jsdom, Playwright 1.63, openapi-typescript/fetch);
  `pnpm-lock.yaml` generated; `pnpm install --frozen-lockfile` passes;
  `pnpm run build` produces `frontend/dist`.
- M0.2: toolchain manifest `docs/toolchain.json`; WASM boundary recorded in
  `docs/architecture.md`.
- M0.3: `config.py` (AppConfig, CLI>env>TOML>defaults precedence, loopback-only
  bind validation), `storage.py` (XDG paths, `--storage-root`, owner-only
  permissions on data/runtime), `diagnostics.py` (non-mutating doctor checks:
  python, platform, RAM, storage, ffmpeg, node/pnpm, GPU, frontend-build,
  sqlite), `cli.py` (`version` + `doctor` commands). 22 unit tests pass.
- M0.4: `domain/common.py` (UUID, UTC timestamp, SHA-256, Revision,
  SamplePosition, HalfOpenInterval primitives), `domain/project.py`
  (ProjectRecord: empty/ready status, name validation, source-field
  co-presence), `domain/asset.py` (AssetRecord: relative path rules,
  traversal/NUL/absolute rejection, AudioMetadata), `domain/confidence.py`
  (Confidence: kind/value invariant, alternatives, review_state). 53 unit
  tests pass.
- M0.5: `storage/paths.py` (moved from `storage.py`), `storage/db.py`
  (sqlite3 connection, WAL, synchronous=FULL, foreign_keys, busy_timeout,
  `PRAGMA user_version`, migration 0→1 with projects/assets/project_assets
  tables, rejects newer schema), `storage/repository.py` (ProjectRepository:
  create_project, get_project, list_projects, register_asset, attach_asset;
  per-operation connections, parameterized SQL, immutable domain records).
  69 unit tests pass.
- M0.6: `app.py` (create_app factory, FastAPI lifespan: storage init, DB
  migration, session token, readiness flag), `api/routes.py` (health,
  system, projects CRUD, modules, models; idempotency-key support),
  `api/errors.py` (consistent error envelope, ApiError hierarchy),
  `api/middleware.py` (request-ID tracing), `api/idempotency.py`
  (in-memory key→project store). 85 unit tests pass.
- M0.7: `api/security.py` (SecurityMiddleware: bearer token auth with
  hmac.compare_digest, Host/Origin loopback validation, conservative
  rate limiting on failed auth, CSP/nosniff/referrer/COOP/COEP security
  headers; health route unauthenticated). 95 unit tests pass.
- M0.8: `scripts/export_openapi.py` (OpenAPI export from create_app),
  `contracts/openapi.json` + `frontend/src/api/schema.ts` (generated),
  `frontend/src/auth.ts` (token bootstrap from URL fragment → sessionStorage),
  `frontend/src/api/client.ts` (openapi-fetch wrapper with auth header),
  `frontend/src/App.tsx` (8-state browser shell: connecting, connected
  empty, connected with projects, creating, empty project, backend
  unavailable, session expired, API error; new-project workflow),
  `scripts/check_contract.py` (deterministic drift check), static mount
  in `app.py`. 95 py + 17 js tests pass; live browser acceptance passed.
- M0.9: `worker/protocol.py` (newline-delimited JSON envelope, typed
  messages, 1 MiB limit, version validation), `worker/probe_worker.py`
  (model-free diagnostic: hello, describe→capabilities, ping→pong,
  shutdown→stopped, stderr-only logging, EOF shutdown),
  `worker/supervisor.py` (subprocess launch via sys.executable,
  concurrent stdout/stderr readers, handshake timeout, graceful
  shutdown with terminate/kill escalation, child reaping),
  `cli.py` `worker-probe` command. 123 unit tests pass.
- M0.10: `serve.py` (run_server: static asset check, fcntl advisory lock
  on storage root, uvicorn loopback bind, readiness wait, browser open
  with graceful fallback, SIGINT/SIGTERM shutdown, lock release),
  `cli.py` `serve` command (--no-browser, --port, --storage-root),
  `scripts/dev.py` (setup, dev, build, check, test, test-browser,
  contracts, licenses). 136 unit tests pass.
- M0.11: `logging.py` (structured console + rotating JSON file logs, 5 MiB
  rotation, 5 backups, token/authorization redaction, request-ID binding),
  `scripts/generate_licenses.py` (parses uv.lock + pnpm-lock.yaml, queries
  installed .dist-info metadata, emits `licenses/components.json` and
  `licenses/NOTICES.md`), `docs/troubleshooting.md` (12 failure scenarios),
  README updated with all 12 required sections. 148 unit tests pass.

## Remaining (Milestone 0)

- M0.12 verification matrix + package smoke (Gate F).

## Environment facts (re-verified 2026-09-29, not from old inventory)

- uv 0.12.0; uv-managed Python 3.11.15 installed at
  `~/.local/share/uv/python/cpython-3.11-linux-x86-64-gnu`.
- Node 22.22.2 (`/usr/bin/node`); npm present; **no pnpm, no corepack** on this system.
- ffmpeg 8.1.2 + ffprobe at `/usr/bin`.
- CPU: 16 threads; RAM ~31 GB.
- `nvidia-smi` WORKS (contrary to old inventory's failed call):
  GPU0 RTX 4080 `GPU-0dab3af3-dd8f-90ac-d715-f565c30f98f6`,
  GPU1 RTX 5060 Ti `GPU-9cccfe8d-0957-ea9b-a1ef-ae4e3a3e899d`.
  CUDA/PyTorch runtime NOT yet qualified (M2+ concern; M0 needs no GPU).
- No Emscripten on PATH (M2 concern).
- Disk: ~399 GB free on `/home`.

## Architectural decisions so far

- Python 3.11.15 via uv, `>=3.11,<3.12`, Hatchling, src layout, console script `basseparate`.
- pnpm to be installed via npm global package (no corepack on system); exact version pinned
  in root `packageManager` field. (Recorded when version resolved.)
- Git is a development aid only; generated-artifact checks must work without it (filesystem comparison).
- App storage via platformdirs (XDG), overridable with `--storage-root`.

## Commands run / results

| Command | Result |
|---|---|
| `sha256sum audio2test/*.wav` | 5 hashes recorded in baseline report |
| `uv python list --only-installed` | 3.14.7 (system), 3.13.14, 3.11.15 (uv) |
| `nvidia-smi -L` | 2 GPUs listed (see above) |
| `git init -b main` | OK |

## Known failures / blockers

- None. (pnpm absence is handled by explicit install in M0.2, not a blocker.)
