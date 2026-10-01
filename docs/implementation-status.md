# basseparate — implementation status ledger

Persistent resume point. A fresh agent must be able to continue from this file
plus the repository state. Keep it concise; put long evidence in `docs/evidence/`.

## Current position

- **Milestone:** 1 (Import, waveform, and original playback)
- **Gate:** F passed (Milestone 0 exit gate)
- **Work package:** M1.3 (ffprobe inspection, audio-stream selection) — complete
- **Last commit:** M1.3 commit (see git log; follows `ef005a7`)
- **Next action:** M1.4 (attach imported source to project) per
  `projectPlans/milestone1.md`.

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
- M0.12: Full verification matrix complete. `tests/integration/test_storage_integration.py`
  (12 scenarios: fresh init, idempotent init, CRUD, close/reopen, asset
  attach, missing-object rejection, transaction rollback, migration,
  failed-migration preservation, newer-version rejection, locked database,
  root isolation). `tests/integration/test_offline_start.py` (offline
  start, no model download). `frontend/e2e/app.spec.ts` (Playwright E2E:
  launch, bootstrap, token removal, project create, persistence, restart,
  port release). Keyboard navigation tests in `frontend/tests/app.test.tsx`.
  HTTP integration gaps in `tests/unit/test_api.py` (no-traceback-leak,
  contract conformance). Lifecycle gaps in `tests/unit/test_serve.py`
  (independent second instance, abrupt termination + restart, browser
  launch failure). Package smoke: wheel builds, installs in clean venv,
  `basseparate version`/`doctor`/`serve` all work. 162 py + 19 js tests
  pass. Ruff, mypy, typecheck, lint, build, contract-drift all clean.
  Fixed `.gitignore` `storage/` → `/storage/` (was excluding
  `src/basseparate/storage/` from wheel).

## Remaining (Milestone 0)

- None. Milestone 0 complete.

## Milestone 1 progress

### M1.2 — Bounded local file transfer (complete)

**Backend:**
- `config.py`: `import_chunk_bytes` (default 8 MiB, min 1 MiB),
  `max_import_bytes` (default 20 GiB); chunk ≤ max validation.
- `uploads.py` (new): `UploadManager` — bounded streaming reads (256 KiB
  internal), SHA-256 incremental hashing, per-import `asyncio.Lock`,
  manifest durability (tmp + `Path.replace`), fsync before manifest update,
  crash-residue truncation on reload, disk-space reservation (declared + 2 GiB
  headroom), cancel cleanup (delete temp media + manifest).
- `api/import_routes.py` (new): `POST /api/v1/imports` (create session,
  filename control-char validation, project-empty guard, size limit),
  `PUT /api/v1/imports/{id}/chunks?offset=...` (streaming body, offset
  validation, idempotent replay, conflict detection),
  `GET /api/v1/imports/{id}`, `GET /api/v1/projects/{id}/imports`,
  `POST /api/v1/imports/{id}/complete` (full-file SHA-256 verification),
  `POST /api/v1/imports/{id}/cancel`.
- `api/errors.py`: 8 new import/upload error classes
  (`ImportNotFoundError`, `ProjectNotEmptyError`, `ImportStateError`,
  `OffsetMismatchError`, `ChunkConflictError`, `ChunkSizeError`,
  `ImportSizeLimitError`, `InsufficientDiskSpaceError`).
- `app.py`: wired `ImportRepository` + `UploadManager` into app state;
  included `import_router`.
- `storage/__init__.py`: exported `ImportRepository`.
- Tests: `tests/unit/test_imports.py` (6 test classes: create, chunk,
  complete, cancel, reload-recovery, concurrency). 237 py tests pass.

**Frontend:**
- `src/api/uploader.ts` (new): `sha256Hex` (Web Crypto),
  `createImportSession`, `uploadChunk`, `completeImport`, `cancelImport`,
  `listProjectImports`, `uploadFile` (8 MiB chunks via `File.slice()`,
  sequential upload, 3 retries per chunk with backoff, AbortController
  cancellation, resume from server-side offset).
- `src/App.tsx`: `ImportPanel` component — drag-and-drop zone, file picker,
  multi-file selection prompt, progress bar with percentage, cancel button,
  error/cancelled states, reload-recovery banner listing incomplete imports.
  Shown for empty projects only.
- `src/styles.css`: import panel styles (dropzone, progress bar, recovery
  banner, multi-file prompt, error/cancelled states).
- `tests/app.test.tsx`: updated 5 assertions from "No audio imported yet."
  to import dropzone; added `/imports` path to mock GET handler.
  19 js tests pass.

**Verification (all green):**
- `uv run --locked pytest tests/ -q`: 237 passed
- `uv run --locked ruff check src tests`: clean
- `uv run --locked ruff format --check src tests`: clean
- `uv run --locked mypy`: clean
- `scripts/check_contract.py`: OK
- `pnpm run typecheck`: clean
- `pnpm run lint`: clean
- `pnpm run test`: 19 passed
- `pnpm run build`: clean

### M1.3 — Inspect media and select audio streams (complete)

**Backend:**
- `media/probe.py` (new): `probe_media(path, timeout_seconds=30.0)` runs
  ffprobe via `asyncio.create_subprocess_exec` (argument array, stdin
  DEVNULL, 30 s `asyncio.timeout`, 10 MiB bounded stdout/stderr reads,
  process kill on timeout/failure). `parse_probe_data` maps ffprobe JSON to
  `ProbeResult`/`AudioStreamInfo` (on-disk size fallback for byte count,
  title/artist tags, per-stream index/codec/rate/channels/layout/language/
  title/default-disposition/duration/start-time). `tool_versions()` caches
  ffmpeg/ffprobe versions per process. Application limits enforced:
  8 kHz–192 kHz, 1–8 channels. Typed errors: `ProbeTimeoutError`,
  `ProbeFailedError`, `NoAudioStreamError`, `UnsupportedMediaError`.
  Channel layout derived from channel count (mono/stereo/5.1/7.1) when the
  container does not expose it (FFmpeg 7+ dropped the field for many formats).
- `api/errors.py`: 5 new API errors — `NoAudioStreamError` (NO_AUDIO_STREAM,
  422), `UnsupportedMediaError` (UNSUPPORTED_MEDIA, 422),
  `ProbeTimeoutError` (PROBE_TIMEOUT, 504), `ProbeFailedError` (PROBE_FAILED,
  500), `StreamSelectionError` (INVALID_STREAM_SELECTION, 422, details carry
  the available stream indices).
- `api/import_routes.py`: `complete` now probes the finished part file after
  hash verification; stores `ProbeResult` via `ImportRepository.set_probe_result`;
  auto-selects the single audio stream; leaves selection open for multi-stream
  files; marks the import FAILED (with error text) on no-audio/timeout/failure/
  unsupported-media and returns the matching API error. New route
  `POST /api/v1/imports/{id}/select-stream` (body `{stream_index}`) validates
  COMPLETE state + known stream index and persists the selection.
  `CompleteImportResponse` now carries `probe_result` and
  `selected_stream_index`.
- Tests: `tests/unit/test_probe.py` (new; real ffmpeg/ffprobe against
  generated WAV/PNG fixtures: mono, stereo layout, no-audio, 4 kHz rejection,
  9-channel rejection, missing file, 1 ms timeout, garbage bytes, version
  cache, parse-data fallbacks) and `TestProbeIntegration` in
  `tests/unit/test_imports.py` (single-stream auto-select, multi-stream
  deferral, select-stream persistence, invalid index 422, pre-complete 409,
  no-audio → failed, unsupported rate → failed). M1.2 complete/cancel tests
  now upload generated WAV bytes.

**Frontend:**
- `src/api/uploader.ts`: `UploadResult` extended with `selectedStreamIndex`
  + `audioStreams` summaries; new `selectStream(importId, streamIndex)`.
- `src/App.tsx`: `ImportPanel` shows a stream-selection dialog after
  completion when the server leaves the choice open (>1 audio streams);
  lists index, title/language/codec, layout/channels, sample rate,
  highlights the default-disposition stream; selection calls
  `select-stream` then proceeds.
- `src/styles.css`: `.import-stream-dialog` + `.stream-default` styles.

**Verification (all green):**
- `uv run --locked pytest tests/ -q`: 260 passed
- `uv run --locked ruff check src tests`: clean
- `uv run --locked ruff format --check src tests`: clean
- `uv run --locked mypy`: clean
- `scripts/check_contract.py`: OK (contracts + `schema.ts` regenerated)
- `pnpm run typecheck`: clean
- `pnpm run lint`: clean
- `pnpm run test`: 19 passed
- `pnpm run build`: clean

### M1.1 — Validate prerequisites + extend contracts (complete)

- Prerequisites verified green before edits: 162 py + 19 js tests, contract
  drift check, worker probe.
- `src/basseparate/__init__.py`: `DATABASE_SCHEMA_VERSION = 2`,
  `PROJECT_SCHEMA_VERSION = 2` (API/worker protocol versions unchanged).
- `domain/project.py`: renamed `duration_samples` → `duration_frames`; added
  `WaveformStatus` (none/pending/ready), `canonical_asset_id`,
  `monitoring_asset_id`, `source_stream_index`, `source_channel_count`,
  `source_channel_layout`, `decode_profile_version`, `waveform_status`,
  `source_metadata`; togetherness rule for all source fields; rate bounds
  8k–192k Hz, channel bounds 1–8; empty status forbids source fields.
- `domain/asset.py`: `AudioMetadata.sample_count` → `frame_count`.
- `domain/import_record.py` (new): `TransferState` (created/uploading/
  complete/cancelled/failed), `AudioStreamInfo`, `ProbeResult`,
  `ImportRecord` (received ≤ declared; complete ⇒ hash + full bytes;
  cancelled/failed ⇒ error; filename 1–512 chars, no control chars).
- `domain/representation.py` (new): `RepresentationRole` (canonical/
  monitoring_downmix/playback_rate), `TimeMapping`, `RepresentationProvenance`,
  `AudioRepresentation` (M1 PCM fixed to f32le interleaved; `transform_key`
  is a SHA-256 identity hash).
- `storage/db.py`: migration 1→2 (column renames, new `projects` columns,
  `imports` + `representations` tables, 3 indexes).
- `storage/repository.py`: `SCHEMA_VERSION = 2`; `ProjectRepository` updated
  for new columns; new `ImportRepository`, `RepresentationRepository`.
- `pyproject.toml`: `numpy>=2.0,<3.0` (resolved 2.4.6); lock + licenses
  regenerated (44 components).
- Contracts regenerated (`contracts/openapi.json`, `frontend/src/api/schema.ts`);
  drift check OK.
- Tests: updated `test_project.py`, `test_asset.py`, `test_api.py`,
  `test_storage_db.py`; new `test_import_record.py`, `test_representation.py`,
  `test_repository_m1.py`. 210 py + 19 js tests pass; ruff, format, mypy,
  typecheck, lint, build all clean.

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
