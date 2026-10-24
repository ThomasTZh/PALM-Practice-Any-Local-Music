# basseparate — implementation status ledger

Persistent resume point. A fresh agent must be able to continue from this file
plus the repository state. Keep it concise; put long evidence in `docs/evidence/`.

## Current position

- **Milestones:** 0, 1, and 2 complete; M3.1 (rhythm domain and
  schema, `3d3c307`) and M3.2 (Beat This! runtime, registry, install
  boundary, CPU qualification) complete on 2026-10-24. M2.21 final separation-app acceptance was
  accepted on 2026-10-23 (objective plus human steps 6-10).
- **Next work package:** M3.3 (prepare rhythm-analysis input
  reproducibly). Specification is
  `projectPlans/milestone3.md` (work packages M3.1-M3.22; see
  "Milestone 3 progress" and `projectPlans/m3.1-plan.md`).
- **Repository:** branch `main`; HEAD is the M3.1 ledger follow-up on
  top of `3d3c307` ("M3.1: verify prerequisites and extend the rhythm
  domain"); 113 commits at the implementation commit; the tree was
  clean before the M3.1 work.
- **Workspace relocation (2026-10-24):** the checkout moved from
  `/home/thomas/Documents/localLLM playground/opencodetest/basseparate`
  to `/home/thomas/Documents/basseparate`. The venv's editable-install
  `.pth` still pointed at the deleted source directory, so every test
  module failed to import `PROJECT_SCHEMA_VERSION`; the path was
  repointed to `<workspace>/src`, the 24 `.venv/bin` scripts (including
  `basseparate`, `pytest`, `ruff`, `mypy`, and the `activate*` files)
  that embedded the old prefix were rewritten, and the stale
  `__pycache__` trees under `src/` and `tests/` were removed.
  `basseparate doctor` now reports the foundation ready (GPU warning
  only, as expected). Run all commands from the new root.
- **Documentation refresh (2026-10-24):** README, architecture,
  toolchain, troubleshooting, the milestone 1/2 specification links, the
  M2.19 evidence, and the generated license notices were brought up to
  the Milestone 2 state. `licenses/NOTICES.md` now lists the bundled
  model weights and resolves JS licenses from installed package
  metadata; 27 entries stay unresolved (optional platform bindings that
  are not installed on this host, plus colorama/tomli, which are
  conditional and not installed). The `generate_licenses.py` pnpm parser
  was fixed to read the project YAML document instead of pnpm's own
  package-manager graph, and its JS license lookup now reads installed
  package metadata. All 2026-10-24 work (docs, license regeneration, the
  `app-loops` expectation fix, and the Prettier normalization) is
  committed as `ba37ffc`; this ledger update is the follow-up commit.

**Verified gates (2026-10-24, current tree):**

| Gate | Result |
|---|---|
| `pytest tests/ -q` | 1474 passed |
| `ruff check src/ tests/` | clean |
| `ruff format --check src/ tests/` | **not clean**: 90 of 170 files would be reformatted (pre-existing drift with the locked ruff 0.16.9; no source file was touched by this session) |
| `mypy src/basseparate` | clean, 85 files |
| `scripts/check_contract.py` | in sync |
| `npx vitest run` (frontend) | 569 passed, 36 files |
| `npx tsc -b --force` | clean |
| `npm run format:check` | clean |
| `npm run build` | OK |
| `npm run lint` | 131 errors + 1 warning; all pre-existing |

The two historically load-sensitive tests
`tests/integration/test_analysis_job_manager.py::TestAnalysisJobClass::test_separation_completes_on_the_analysis_worker`
and
`tests/integration/test_job_manager.py::TestProbeCompletion::test_probe_job_completes_and_publishes`
passed in the final M3.1 full run; they remain timing-sensitive under
load, so do not treat them as regressions until they fail alone. The frontend baseline was 567
before the two M2.21 loop regression tests; it is now 569. One stale
overlay assertion in `frontend/tests/app-loops.test.tsx` still
expected the pre-`2e1c2f0` draw order and sizes, so the full suite was
red until 2026-10-24; it now asserts the selection-first order, the
2 px loop border, the boundary handles, and the top-center grip.
`frontend/tests/WaveformEditor.test.tsx` also needed Prettier
normalization after `2e1c2f0`.
A smoke start of the repaired install on an isolated port and temporary
storage root returned `health: ready` and HTTP 200 for `/`, applying
migrations 0 to 12; the acceptance storage was not touched. `uv run`
itself fails inside the agent sandbox (read-only uv cache), so use the
`.venv/bin/...` commands here; `uv run --locked` still works in a normal
shell.

- **Acceptance summary (2026-10-22/23):** GPU separation on the RTX
  4080 took 72.5 s and published four valid 48 kHz stems at 14,133,913
  frames; WAV24 export had a zero-lag four-stem sum (corr 0.9927, RMS
  ratio 1.0008); the portable save/reopen round trip matched geometry
  and archive hash (702,266,762 bytes, 380 members); the 60-minute
  whole-track loop playback recorded 12 resets, 11 full periods of
  293.88-294.91 s (mean 294.468 s vs expected 294.4565 s), one startup
  underrun and none later, with bounded memory. Human steps 6-10 all
  pass. Evidence:
  `docs/evidence/m2.20-performance-and-acceptance.md`,
  `docs/evidence/m2.21-listening-review.md`, and
  `docs/evidence/session-2026-10-23-handover.md`.
- **Current environment limits:** no NVIDIA driver (`nvidia-smi` fails;
  `torch.cuda.is_available()` is false), so do not attempt a new
  separation here. The acceptance stems, result set, and portable
  archive are preserved, and playback is CPU-side. The application
  environment is torch-free; inference runs only in `analysis/.venv`
  (Python 3.11.15, demucs 4.1.0, torch 2.9.1+cu128, soundfile 0.14.0)
  against the hash-pinned `models/htdemucs_ft` bundle. pnpm is installed
  as 12.15.0 at `~/.local/share/pnpm/bin/pnpm`; `package.json` pins
  12.8.1, and the installed pnpm cannot switch to the pinned engine in
  this sandbox (read-only package-manager store). The existing
  `frontend/node_modules` still works, so this does not block the
  frontend gates.
- **App state:** the acceptance app is **not running**. It was left
  running on 2026-10-23 and shut down at 22:55
  (`.m2.21-acceptance/server.log`). `storage/m2.21/` and
  `.m2.21-acceptance/` are preserved (both are gitignored). Relaunch
  with
  `.venv/bin/basseparate serve --no-browser --port 18796 --storage-root storage/m2.21`;
  the new token is printed in `.m2.21-acceptance/server.log`. Project
  `923d1e34-8141-495d-847d-6bb6aae3c114`, result set
  `5299022f-4495-4839-95c2-6358f7199735`; position 2,592,000 frames
  (54.0 s), selection 3,202,809-4,956,380 frames, one active loop
  `929a5978-15ff-4b1d-aa45-db1ce44761e8` at 2,400,000-2,832,000 frames
  (50.0-59.0 s), `Fade` off, `Looping` enabled, snapshot revision 1861
  (the position may advance if playback was left running).
- **Optional, non-blocking work:** make the loop join seamless without
  the 5 ms fade notch (for example a short crossfade); continue loop UX
  polish; rename or remove the residual 9 s test loop if desired. The
  e2e `app.spec.ts` harness bug (it spawns the Python server through
  `process.execPath`) is pre-existing and out of scope until the e2e
  suite is re-run in a full environment.

**Resume procedure:** read this file and the 2026-10-23 handover,
including its 2026-10-24 correction. From the workspace root:

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/basseparate
.venv/bin/python scripts/check_contract.py
cd frontend && npx vitest run
cd frontend && npx tsc -b --force
cd frontend && npm run format:check
cd frontend && npm run build
```

For the next milestone, read `projectPlans/milestone3.md` and start at
M3.1. The Beat This! model install is a deliberate network operation
(`milestone3.md` section 4); GPU-dependent acceptance runs will need
the NVIDIA driver restored (the M2.19 runs used approved escalated
device access).

- **Recent commits (full history in `git log`):** `3d3c307` M3.1 rhythm
  domain and schema; `ba37ffc` refresh the
  status ledger and project docs; `9bcdd6c` final
  ledger hash; `33162c5` finalize M2.21 acceptance and handover;
  `424b46b` ledger for the loop overlay fix; `2e1c2f0` show and drag
  the active loop overlay; `9a48c90` ledger for the selection fix;
  `53d2e32` select on waveform drags inside active loops; `c531488`
  ledger for the 60-minute playback acceptance; `b2e244c` keep the
  looped playhead stable; `10b183f` play stems from the mapped audio
  asset ids; `094eeb7` accept a null export target rate;
  `42655c4` correct stem endpoints and reuse existing published assets.
- **Recovery note:** if working-tree files appear reverted, versions
  are recoverable from the OpenCode snapshot store
  (`~/.local/share/opencode/snapshot/<workspace>/<repo>/objects`, read
  with `git cat-file` inside that repository).

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

### M1.12 — AudioWorklet transport (complete — `bccd7b5`)

Spec: `projectPlans/milestone1.md` §14. Plan:
`projectPlans/m1.12-plan.md`. Frontend-only:
replaces the `AudioBufferSourceNode` engine (`engine.ts`) with an
AudioWorklet transport. Shared-memory path, refined buffer defaults,
suspension/device recovery (M1.13) and synchronized-readout refinements
(M1.14) are out of scope.

Key design points (see plan):
- `worklet-processor.js` — self-contained plain-JS ES module: pure
  `ConsumptionState` (per-channel fixed 8 s ring, consumption, ~5 ms
  pause ramp, seek-as-stale-audio-barrier, 480-frame anchors, actual
  block length in `process`) + thin `AudioWorkletProcessor` adapter
  (whole class + `registerProcessor` inside a
  `typeof AudioWorkletProcessor !== 'undefined'` guard, so main-thread
  test imports skip it). Browser: `?raw` + Blob URL + `addModule`.
- `transport.ts` — `PcmTransport`: 8 spec states + `desiredPlaying`,
  ~1 s chunk prefetch (2 s prebuffer target, generation-scoped
  AbortController), anchor-based position extrapolation (playback →
  project frames at the boundary), `setOutputGain` on a GainNode after
  the worklet (canonical samples untouched).
- `pcm.ts` gains `playbackPosition` (inverse of `projectPosition`).
- `App.tsx` — `PlaybackPanel` swaps to the transport; new state labels;
  monitoring-volume range 0–200 % with a "may clip" hint above 100 %.
- `engine.ts` + `engine.test.ts` deleted; their coverage migrates to
  `transport.test.ts`.

Phases: 1 plan + kickoff → 2 worklet core → 3 transport → 4 app
integration + engine removal → 5 frontend gate + commit.

**Phase status:** all phases complete.
- Phase 2: `worklet-processor.js` (ConsumptionState + adapter guard) +
  hand-written `worklet-processor.d.ts` (tsc surface for the `.js`
  import) + `src/vite-env.d.ts` (`?raw` import types);
  `tests/worklet-core.test.ts` 12/12 green.
- Phase 3: `transport.ts` — `PcmTransport` with the 8 spec states +
  `desiredPlaying`; single long-lived fill loop that survives
  generation bumps (abort-aware parking delay, 50 ms cadence, ~1 s
  chunks to a 2 s prebuffer target); generation-guarded port
  messages; the worklet acks enqueued samples with `data` (so
  preparing/seeking can reach playing); `setOutputGain` clamped to
  [0, 4] with a 10 ms ramp; injectable context factory, byte fetcher,
  delay, and module-URL factory (jsdom has no `AudioContext` and no
  `URL.createObjectURL`). `tests/transport.test.ts` 10/10 green
  (fake context + scriptable worklet port).
- Phase 4: `App.tsx` `PlaybackPanel` — transport created eagerly once
  source info loads (the playback representation is resolved on first
  play via `ensurePlaybackTarget` at the context rate; the pending
  context is consumed once by the factory); project-switch reset
  effect; seek parks the playhead locally before the transport exists
  (M1.11 click-to-seek preserved); Play/Pause label derived from
  state (Pause while playing/buffering; disabled while
  preparing/seeking/buffering); Stop disabled while unloaded; volume
  range 0–200 % (5 % steps, `aria-label="Monitoring volume"`, "may
  clip" hint above 100 %, drives `setOutputGain(v/100)`);
  `.playback-volume` styles in `styles.css`.
  `playback-panel.test.tsx` fakes made worklet-capable (data-ack
  port, `URL.createObjectURL`/`revokeObjectURL` spies).
  `engine.ts` + `engine.test.ts` deleted.
- Phase 5: full gate green — `pnpm test` 224/224 (14 files),
  `pnpm typecheck`, `pnpm lint`, `pnpm format:check` all clean.

### M1.13 — Buffering and browser compatibility (complete — `c7d78ef`)

Spec: `projectPlans/milestone1.md` §15. Plan:
`projectPlans/m1.13-plan.md`. Frontend-only: extends the M1.12
transport with a fetch/deinterleave worker, the shared-memory path
(cross-origin isolated) and the transferable-buffer fallback, the
§15.3 buffer budget (2 s prebuffer/start threshold, 8 s steady
lookahead, 12 s retention cap), underrun diagnostics, browser
suspension handling, and audio-device-change recovery. No backend
changes. Synchronized-readout refinements and follow-playhead (M1.14)
are out of scope.

Key design points (see plan):
- `pcm-fetch.ts` — shared `fetchPcmRange` (Bearer + Range, 416 →
  `RangeError`) + `deinterleaveChannels`, used by both the worker and
  the main-thread fallback (jsdom has no `Worker`).
- `fetch-worker.ts` — Vite-bundled module worker (same pattern as
  `waveform/worker-script.ts`): sole producer for both paths.
- Worklet v2 — `enqueueChannels` (deinterleaved input), bounded chunk
  queue for the transfer path (high-water / consumed acks, flow
  control), `attachShared` SPSC consumption from a 12 s SAB
  (Int32 header `[generation, writerIdx, readerIdx]`, polling only,
  no blocking waits), `{buffered, frames}` reporting at anchor
  cadence.
- Transport v2 — mode selection (`auto` = `crossOriginIsolated &&
  SharedArrayBuffer`), worker lifecycle + main-thread fallback,
  flow control against the 12 s budget (ring + queue counted
  together), 2 s post-underrun start threshold, underrun
  diagnostics, `onstatechange` suspension handling (frozen
  extrapolation, gesture-resume via Play), context-loss detection +
  `rebind()` (retained position, representation re-resolved at the
  new context rate), `sync()` for visibility return.
- Seek on the shared path: worklet resets its reader + generation
  and posts `{flushed}`; only then does the transport forward
  `{flush-ack}` to the worker, which resets generation + writer
  index (spec §15.1.6).

Phases: 1 plan + ledger → 2 `pcm-fetch.ts` → 3 worker + worklet v2 →
4 transport v2 → 5 panel integration → 6 frontend gate + commit.

**Phase status:**
- Phase 1: plan written, ledger updated.
- Phase 2: `pcm-fetch.ts` (`fetchPcmRange` + `deinterleaveChannels` +
  shared-ring helpers `createSharedRing` / `writeSharedRing` /
  `acknowledgeSharedFlush`); `fetchAssetBytes` in `api/playback.ts`
  delegates to the shared helper; `tests/pcm-fetch.test.ts` 7/7 green.
- Phase 3: `fetch-worker.ts` (Vite module worker, sole producer,
  generation discipline); `fetch-source.ts` (`WorkerFetchSource` +
  `DirectFetchSource` main-thread fallback, `StaleGenerationError`);
  worklet v2 (`enqueueChannels`, bounded chunk queue, `attachShared`
  SPSC consumption, `{buffered, frames, queuedFrames}` reporting,
  12 s budget, generation-aware `seek`); `worklet-processor.d.ts`
  updated; `tests/worklet-core.test.ts` 22/22 green (12 M1.12 + 10 new).
- Phase 4 (transport v2) — **verified**: full frontend gate green
  (256/256 tests, typecheck, lint, format:check). Verification fixes:
  `position` getter returns `retainedProjectFrame` while `contextLost`
  (and `handleContextLost` reads the position *before* flipping the
  flag); `SharedRing` gains `sab` (single source of truth for the
  buffer); **production bug fixed**: `fetch-worker.ts` and
  `DirectFetchSource` allocated a *second* SAB on `shared-init` /
  `attachShared` — both now use the new `viewSharedRing` helper (view
  the transferred buffer); `FetchSource` interface gains
  `attachShared`; dead `queuedFrames` field removed; `contextLost` is a
  public field (was a private field shadowing a same-name getter).
  Test-side: v2 protocol timing (`settle()` after `play()` — the fill
  loop's fetch round is a microtask ahead), align-seek expectations
  (play now posts a gen-0 seek for fresh-worklet alignment), last-
  generation-message lookup, `TestWorkletNode` in
  `playback-panel.test.tsx` moved to the v2 protocol (`channels` in →
  `buffered` ack; was `samples` in → `data` ack).
  - `transport.ts` fully rewritten: `mode` (`auto`/`shared`/`transfer`;
    auto = `crossOriginIsolated && SharedArrayBuffer`);
    `TransportContextLike` gains `onstatechange`; `TransportOptions`
    gains `workerFactory` + `mode`; `fetchChunk` signature is now
    `(assetId, start, end, signal)`.
  - Fill loop v2: transfer path relays `fetchChunk` results to the
    worklet as `{type:'channels', channels, startFrame, frames,
    generation}` (transferred); shared path calls `writeChunk` into the
    SAB. Gate: `fetchedFrame − consumedEstimate < min(8·rate,
    max(2·rate, frameCount − genStartFrame))` AND `bufferedFrames <
    12·rate − 1·rate` AND not `workerPaused` (`queue-high`). 0-frame
    shared write = dropped chunk (diagnostics) + park, not an error.
  - Shared handshake: `flushBookkeeping(frame)` (sync: gen bump,
    abort, post `{seek, frame, generation}` to worklet) then
    `alignWorklet()` — transfer: sync `setGeneration`; shared: await
    worklet `{flushed}` (`lastFlushedGeneration` handles fast fakes),
    then `source.acknowledgeFlush(gen, baseFrame)`. `seek()`/`stop()`
    stay synchronous on the transfer path (M1.12 test behavior);
    shared-path refill starts only after the handshake. `play()` from
    `unloaded`/`error` aligns the fresh worklet (posts seek at
    `genStartFrame`, current gen) — fixes the M1.12 pre-playback-seek
    misalignment. `play()` from `ended` re-flushes to 0.
  - Start rules: `preparing`/`seeking` → `playing` on any
    `buffered > 0`; `buffering` (post-underrun) → `playing` only at
    `buffered ≥ 2·rate`. Diagnostics: `underruns`, `lastUnderrunAt`,
    `droppedChunks` (worklet `chunk-dropped` + 0-frame shared writes).
  - Suspension: `onstatechange` — `suspended` → `isSuspended`,
    position getter stops extrapolating, state untouched; `running` →
    re-engage fill. `play()` awaits `context.resume()`.
  - Context loss: `state === 'closed'` → `handleContextLost()`
    (retains `position` in `retainedProjectFrame`, teardown, `error` +
    `contextLost`); `rebind({target, projectRate,
    projectDurationFrames})` resets to `unloaded` parked at the
    retained frame (gen reset to 0, fresh abort); `sync()` returns
    `{state, position, isSuspended, contextLost}` and catches a
    context that closed while hidden.
  - Supporting fixes: `fetch-worker.ts` posts `ok: true` with
    `frames: 0` on ring-full shared writes (flow control, not error);
    `WorkerFetchSource.dispose()` rejects pending `readyAck`/`flushAck`;
    `App.tsx` `fetchChunk` call site updated to the `assetId`
    signature.
  - `tests/transport.test.ts` rewritten: v2 protocol (`buffered`
    acks instead of `data`), rig gains `tick()` (parked-delay wake),
    `mode`/`workerFactory`/`frameCount` injection, `FakeFetchWorker`
    (protocol recorder + real SAB writes via `writeSharedRing`),
    `settle()` macrotask helper. New suites: mode selection (4),
    transfer flow control (4), shared path end-to-end incl. flush
    handshake + `ConsumptionState` co-consumption (2), suspension (2),
    context loss + rebind (1), `sync` (2). M1.12 tests carried over
    with the v2 protocol.
- Phase 5 (panel integration) — **verified**: full frontend gate green
  (260/260 tests across 15 files, typecheck, lint, format:check).
  - `transport.ts`: `TransportOptions` gains `onSuspend(suspended)`;
    `onContextStateChange` fires it on suspension transitions;
    **production fix**: `play()` now resumes a suspended context up
    front (the old early-return for active states made
    "click Play to resume" a no-op).
  - `App.tsx` `PlaybackPanel`: `suspended` + `diagnostics` state
    (diagnostics refreshed in `onState`; an underrun always moves the
    state to `buffering`, so no separate callback is needed);
    suspension hint "Browser suspended audio — click Play to resume"
    while `suspended && state ∈ {playing, buffering, seeking}`; the
    Play/Pause button offers the resume gesture (not pause) while
    suspended; muted "Underruns: N" line when `diagnostics.underruns
    > 0`; context-loss recovery in `handlePlayPause` (fresh context →
    re-read `sampleRate` → `ensurePlaybackTarget` →
    `transport.rebind` (retains position) → `play()`);
    `visibilitychange` listener → `transport.sync()` → redraw state /
    position / suspension / diagnostics (cleaned up on unmount).
  - `styles.css`: `.suspension-hint` (warning color),
    `.underrun-diagnostics` (small, muted via `muted` class).
  - `tests/playback-panel.test.tsx`: plan items 15–18 (suspension
    hint + Play-to-resume; context-loss recovery re-resolves and
    plays the retained position; underrun diagnostics line;
    visibility `sync()` redraw). Harness: `TestAudioContext` tracks
    instances + worklet nodes and fires `statechange` on
    `resume()`/`close()` (like a real context); `TestWorkletNode`
    gains `postAnchor` / `postUnderrun`; `PLAYBACK_TARGET` is a full
    48000-frame asset (the 60-frame target made the retained-position
    story untestable — `rebind` clamps to the target frame count).
  - Test-side fix: the fetch mock now returns a **fresh** `Response`
    per call (`mockResolvedValue` reused one consumed body — the
    longer fill loop hit "Body is unusable" on the second chunk).

### M1.14 — Synchronized readout and follow-playhead (complete — `934d6c1`)

Spec: `projectPlans/milestone1.md` §16. Plan:
`projectPlans/m1.14-plan.md`. Frontend-only: worklet anchors at
~20 Hz (§16.1), audible-position estimate via
`getOutputTimestamp()` with retained transport segments and frozen
extrapolation (§16.2), exact-frame inspector line (§16.3), rAF
playhead drawing without per-update React state (§16.5), and
page-follow with 80 % trigger / 20 % landing, manual-navigation
suspension, a visible + persisted follow control (§16.4). No
backend changes.

Phases: 1 plan + ledger → 2 worklet cadence + transport audible
position → 3 editor playhead rewrite (rAF, 80/20 follow,
persistence) → 4 panel wiring (`registerPlayhead`, inspector frame
line) → 5 frontend gate + commit.

**Phase status:**
- Phase 1: plan written, ledger updated.
- Phase 2: verified (266/266 tests, typecheck, lint, format green).
  Worklet: anchor cadence `max(1, round(sampleRate / 20))` (≈20 Hz,
  §16.1) replacing the 480-frame default; `anchorEveryFrames` override
  kept; anchor payload gains `paused`; one final anchor
  (`paused: true`) is emitted when the pause ramp completes (exact
  paused position). Transport: `getOutputTimestamp?()` on
  `TransportContextLike`; retained segment list (pushed in
  `flushBookkeeping` + the play-align seek, capped at 16, cleared on
  graph teardown); `getAudiblePosition()` maps the output time through
  the newest segment started at or before it (older segments stay
  reachable for device-lag times after a seek), extrapolates from the
  last acknowledged anchor when it sits in that segment, clamps to
  `[segment start, frameCount]`; frozen states (paused/buffering/
  preparing/suspended/ended) report the last anchor with no
  extrapolation; documented zero-latency fallback
  (`FALLBACK_OUTPUT_LATENCY_SECONDS = 0`) keeps M1.13 expectations.
  `position` getter delegates. New tests: default 20 Hz cadence,
  final pause anchor, output-timestamp lag, segment mapping across a
  seek, buffering freeze.
- Phase 3: verified. Editor `playheadFrame` prop replaced by optional
  `playheadSource: { getPosition, isPlaying }` (display-only, never
  controls playback). One always-on rAF loop (runs while ready) reads
  the audible position each frame, redraws the per-lane playhead
  canvases only on ≥ 0.5 px movement, and drives the 80 %-trigger /
  20 %-landing page follow (`startFrame = frame − 0.2·visible`,
  clamped; one `setView` per page advance, suppressed when the view is
  already clamped). Follow is suspended by manual navigation
  (`commitView`, in memory only) and re-enabled by the visible
  "Follow playhead" checkbox and "Return to playhead" (which centers +
  re-enables); the preference persists in
  `localStorage['basseparate.playheadFollow']` (default true, explicit
  user actions persist, passive suspension does not).
  `playheadOutside` is now state written by the loop only on change.
  Tests: manual rAF scheduler stub (`tickRaf`) replaces jsdom's
  real-time rAF; `makePlayhead` factory; playhead-layer-isolation,
  80/20 follow (two zoom-ins so the landing is unclamped),
  return-to-playhead, and persistence tests.
- Phase 4: verified. `PlaybackPanel` gains `registerPlayhead`
  (mirrors `registerSeek`): registers a stable `PlayheadSource` that
  reads `transport.getAudiblePosition()` / `currentState` on demand;
  the M1.10 `onPositionChange` bridge is removed (the panel's own
  `position` state still drives the 20 Hz text readout). `ProjectView`
  holds the source in state and forwards it to the editor; the
  `playheadFrame` app state is gone. Source inspector `<dl>` gains the
  exact-frame `Frame` line (§16.3) with a panel test.

### M1.15 — Markers, persistence, and undo/redo (complete — `ede3d26`)

Spec: `projectPlans/milestone1.md` §17. Plan:
`projectPlans/m1.15-plan.md`. Full-stack: marker model
(UUID/project/position/label/color/timestamps; positions valid at 0
and exactly at project end), per-project working state (selection,
viewport, channel display, monitoring volume, last position,
follow-playhead), a project-command endpoint
(`POST /projects/{id}/commands`) with base-revision validation (409
stale), idempotency keys, and resulting-state responses; server-side
undo/redo history (per-project, snapshots exclude
`last_position_frames` so undo never moves the playhead; redo branch
cleared by a new edit; 200-row cap); working autosave (semantic
commands immediate, view state ~1 s debounce, position on pause + 5 s,
serialized per tab, flush on navigation, best-effort page close,
pending indicator); restore-on-reopen (markers/view/selection/display/
follow/position, remain paused); recovery surfaced (canonical missing
→ regenerate from retained original via the existing job endpoint;
original missing + valid canonical → provenance warning).

Phases: 1 plan + ledger → 2 backend domain (marker, working state,
command ops) → 3 backend storage (migration 6, apply/undo/redo,
history) → 4 backend API (command + undo/redo routes, idempotency,
openapi + schema.ts regeneration) → 5 frontend client + command hook
(serialization, debounce, flush, stale resync) → 6 frontend restore +
autosave wiring → 7 frontend editor marker UI → 8 full gate + commit.

**Phase status:**
- Phase 1: plan written, ledger updated.
- Phase 2: backend domain done. `domain/marker.py` (MarkerRecord:
  UUID, project_id, position_frames 0..duration inclusive, label 1-80
  trimmed no control chars, color #rrggbb, timestamps),
  `domain/project.py` (SelectionRange half-open, ViewportState,
  ChannelDisplay, WorkingState, ProjectRecord gains markers +
  working_state with cross-field validation), `domain/commands.py`
  (9 op models discriminated on `type`, CommandRequest with
  idempotency_key, CommandResult with revision/markers/working_state/
  can_undo/can_redo; HISTORY_EXCLUDED_TYPES = {"set_position"}).
  Tests: test_marker.py + test_commands.py.
- Phase 3: backend storage done. Migration 6 (projects.working_state,
  projects.history_seq, markers table, project_history table;
  DATABASE_SCHEMA_VERSION 5->6, 5->6 upgrade test). Repository gains
  apply_command/undo/redo returning CommandResult, snapshot-based
  history (before/after JSON, last_position_frames excluded per
  §17.4.10), 200-row cap, redo-branch deletion, exceptions
  (ProjectMissingError, StaleRevisionError, NothingToUndo/RedoError,
  MarkerNotFoundError, ProjectNotReady). get_project/list_projects
  attach markers + working_state. 23 tests in
  test_repository_commands.py; full unit suite green (576).
- Phase 4: backend API done. `api/command_routes.py` (POST
  /projects/{id}/commands with base-revision 409 + idempotency
  replay/conflict, POST /undo, POST /redo; repo exceptions mapped to
  API errors; repo calls via asyncio.to_thread). api/errors.py gains
  StaleRevisionError (409 + current_revision), NothingToUndo/RedoError
  (409), MarkerNotFoundError (404), InvalidCommandError (422).
  IdempotencyStore generalized to an opaque payload. Router registered
  in app.py. 15 route tests (test_command_routes.py). OpenAPI
  contract + frontend schema.ts regenerated; check_contract passes.
  Python gate green (pytest 576, ruff, mypy).
- Phase 5: frontend client + command hook done.
  `frontend/src/api/commands.ts` (sendCommand / undoCommand /
  redoCommand / getProjectSnapshot; fresh command_id + idempotency_key
  per call; 409 STALE_REVISION -> StaleRevisionError with
  currentRevision; camelCase result mapping).
  `frontend/src/projects/useProjectCommands.ts` (authoritative state
  from server responses only; serialized per-tab queue with base
  revision read at send time; ~1 s per-op-type view debounce with
  last-op-wins coalescing; set_position immediate on pause + 5 s
  cadence while playing; flush() sends armed ops and awaits the queue;
  stale -> snapshot refetch, state resync, armed ops dropped, one-line
  notice). Backend support: ProjectRecord gains can_undo/can_redo
  (computed by repository.get_project from the history pointer; list
  keeps defaults), contract + schema.ts regenerated again.
  Tests: tests/commands.test.ts (8) + tests/use-project-commands.test.ts
  (8; fake timers, microtask flush instead of waitFor). Full frontend
  suite 283 passed; typecheck/lint/format:check green. Python gate
  green (pytest 576, ruff, mypy).
- Phase 6 (complete): restore + autosave wiring.
  Hook project-switch flush of old project's armed ops
  (fire-and-forget sendCommand to prev id) + chain reset in the
  load/reset effect; pagehide sendBeacon of armed view ops
  (useProjectCommands.ts). WaveformEditor: initialViewport /
  initialSelection / initialChannelDisplay / initialFollow props
  (undefined = not loaded, null = server default -> legacy behavior),
  applied once at first ready via restoreAppliedRef (reset on
  projectId/sourceAssetId change); skipReportRef skip-flags so
  restored values are not echoed back (selection flag starts true —
  initial null consumed); autosave callback effects for view /
  selection / channel display; setFollow reports onFollowChange.
  channelCount declaration moved above the effects (TDZ).
  PlaybackPanel: initialVolume (seeded once via volumeSeededRef,
  reset to 100 on project change), onVolumeChange, onPositionReport
  (playing flag from transport state; transport already reports on
  pause), parkPosition (seeks once transport exists, stays paused).
  ProjectView: useProjectCommands(project.id), stable callbacks via
  refs (set_viewport / set_selection start_frames+end_frames /
  set_display / set_follow_playhead / set_monitoring_volume volume),
  notePosition wiring, flush on unmount, derived initial values
  (undefined until loaded; null on server defaults; channel display
  only when non-default; follow only when false), pending "Saving…"
  chip + stale notice with Dismiss. commands.ts toCommandResult
  gains boundary fallbacks (markers ?? [], working_state ??
  DEFAULT, can_undo/can_redo ?? false) — without them test fixtures
  without working_state poisoned hook state.
  Transport (M1.15 §17.6.4): pre-target `seek` no longer clamps to
  the zero `projectDurationFrames` placeholder (the park survives to
  `loadSource`), and `loadSource` now applies a parked frame to the
  start anchors + reports it. App.tsx: the volume-seed and park
  effects moved after the transport-creation effect so a same-commit
  snapshot arrival still finds the transport.
  Tests: tests/app-restore.test.tsx (new, 6 tests) — full-App render
  restores selection / viewport / channel display / follow, seeds
  volume, parks the playhead + saves, autosaves the debounced
  viewport, shows/clears the pending chip, and resyncs on 409.
  Fixtures: getAssetPcm buffer is frames x 2 channels x 2 floats
  (the earlier frames*2*4 size threw a RangeError that silently
  failed the PCM decode and left the lane unpainted); the zoom-in
  autosave expects 3.2 fpp (zoom in halves frames-per-pixel); the
  pending-chip test arms an op via a zoom click (the restore does not
  echo ops). scratch-debug.test.tsx deleted.
  Full frontend suite 289 passed; typecheck / lint / format:check
  green.
- Phase 7 (complete): editor marker UI (§17.2).
  render.ts: MARKER_COLORS 6-color palette, MARKER_FLAG_WIDTH/HEIGHT,
  drawMarkerFlag (2 px full-height stem + fixed 76×12 colored body +
  label truncated to 12 chars + dark selection outline; no measureText
  — not in the WaveformContext structural interface), drawMarkerTick
  (1 px vertical stroke). WaveformEditor: new optional props (markers,
  selectedMarkerId, onAddMarker, onMoveMarker, onUpdateMarker,
  onDeleteMarker, onSelectMarker, onSeekToMarker, onUndo, onRedo,
  canUndo, canRedo) + MARKER_ROW_HEIGHT 24; a `marker-row` CanvasLayer
  + transparent hit surface; a marker-draw effect (row flags with drag
  preview, one tick per visible lane, off-viewport flags skipped); a
  marker-list (color swatch cycles the palette, label input,
  exact-frame input + time, delete; commits on blur/Enter, uncontrolled
  inputs re-keyed on the server value so undo/external edits resync);
  toolbar (Add marker at playhead, Prev, Next) + a History fieldset
  (Undo/Redo, disabled by canUndo/canRedo). Interactions: click a flag
  selects (no seek), click empty space clears, drag previews locally and
  commits exactly one onMoveMarker on release (>3 px threshold),
  double-click a flag seeks + selects, ruler double-click adds at the
  pointer frame. App.tsx ProjectView: selectedMarkerId local state
  (reset on project change / when the marker disappears), stable marker
  + undo/redo callbacks via refs, markers/canUndo/canRedo from the
  hook. styles.css: marker row column layout, hit surface, toolbar,
  list, swatch, and wave-history-controls. Tests:
  tests/WaveformEditor.test.tsx +14 (render/flags/ticks, add at
  playhead, ruler dbl-click, select, clear, drag preview + one commit,
  dbl-click seek+select, prev/next, color cycle, label/frame commit on
  blur, delete, undo/redo enabled/disabled). Full frontend suite 303
  passed; typecheck / lint / format:check green.
- Phase 8 (complete): full gate + commit. `PROJECT_SCHEMA_VERSION`
  bumped 2 → 3 (per plan §1); two tests that pinned the literal
  version (tests/unit/test_api.py::test_create_project,
  tests/unit/test_project.py::test_empty_project_defaults) now import
  PROJECT_SCHEMA_VERSION. All gates green: Python (pytest 702 passed,
  ruff clean, mypy clean 49 files), contract (openapi.json +
  schema.ts regenerated, check_contract OK), frontend (vitest 303
  passed, typecheck, lint, format:check). Committed as a single
  `M1.15: …` change + ledger-hash follow-up.

### M1.16 — Test corpus and automated verification (complete — `af51265`)

Spec: `projectPlans/milestone1.md` §18. Plan:
`projectPlans/m1.16-plan.md`. Final Milestone 1 work package:
complete the automated test corpus against the §18.1–§18.7
checklists — shared synthetic fixture module (`tests/synth.py`),
ffmpeg format fixtures + capability recording (§18.2), import gaps
(unicode/space names, misleading extension, duplicate, probe
timeout), PCM correctness suite (§18.4), waveform gaps (outside ±1,
peak/sample consistency, transform-version cache invalidation,
corrupt-cache recovery), transport gaps (rapid seeks, near-EOF
seek, empty/final partial chunk, context-rate mismatch), and
integration restart/persistence tests (§18.7). Product-code changes
only for genuine bugs a new test exposes.

Phases: 1 plan + ledger → 2 `tests/synth.py` (+ refactor existing
local helpers onto it) → 3 format fixtures + `test_formats.py` +
capability evidence doc → 4 import gaps → 5 PCM correctness
(`test_pcm_correctness.py`) → 6 waveform gaps → 7 transport +
persistence (`test_persistence.py`) → 8 gate + commit.

**Phase status:**
- Phase 1 (complete): plan written (`projectPlans/m1.16-plan.md`),
  ledger updated. Surveyed coverage: import (test_imports.py, chunk
  semantics complete), decode (unit + integration, lossy MP3/AAC/
  Opus), waveform (32 tests incl. all-positive/negative, long
  multi-tile), transport (play/stop/seek/underrun/both buffering
  paths), persistence (M1.15 unit + reopen recovery). Gaps listed in
  plan §1. ffmpeg 8.1.2 verified: encoders pcm_s16le/pcm_f32le/flac/
  libmp3lame/aac/libvorbis/libopus.
- Phase 2 (complete): `tests/synth.py` — shared fixture module
  (tone/sine/stereo/impulse/silence/DC/full-scale/above-full-scale/
  short-in-bucket/block-edge/channel-impulse generators, s16 + f32
  WAV writers, chunked 60-min `long_wav_s16`, `encode_with_ffmpeg`).
  Refactored `tests/integration/test_decode.py` (dropped local
  `_write_wav`/`_sine`/`_encode`) and
  `tests/integration/test_media_worker.py` (dropped `_make_wav`) onto
  it. Full suite green after refactor: 702 passed.
- Phase 3 (complete): `tests/formats.py` (7 audio codec/container
  specs, video + cover-art builders, encoder/muxer probes) +
  `tests/integration/test_formats.py` (22 tests: s16/f32 WAV
  round-trips incl. above-full-scale, 7 format round-trips ×2, 4
  video/container tests, capability matrix). Build notes: no `m4a`
  muxer (AAC fixture uses audio-only `mp4`); lavfi `sine` is mono so
  video fixtures force `-ac 2`; MP4 stores stream titles in the
  `name` tag. Evidence: `docs/evidence/m1.16-format-capabilities.md`.
- Phase 4 (complete): `tests/unit/test_imports.py` gaps — unicode +
  space filename round-trip, misleading extension (WAV bytes as
  `.mp3` → probe reports `wav`), duplicate file imports, probe timeout
  (fake slow ffprobe on PATH + shortened 0.5 s timeout → 504
  `PROBE_TIMEOUT`, import marked failed). Also refactored the local
  `_make_wav` onto `synth.wav_s16_bytes`. 38 passed.
- Phase 5 (complete): `tests/integration/test_pcm_correctness.py`
  (§18.4) — exact s16→normalized values, byte order (byte-for-byte
  f32le), channel order (unique impulse position), time zero, EOF,
  above-full-scale finite (peak 2.0), MP3 t=0 marker survival (no
  double encoder-delay trim), truncated data serves no partial frame.
  8 passed.
- Phase 6 (complete): `tests/unit/test_waveform.py` gaps —
  above-full-scale extrema preserved (no ±1 clamp), peak/sample
  consistency vs direct numpy per-bucket reference, cache-version bump
  invalidation (old manifest rejected, rebuild publishes new version),
  corrupt-cache recovery (min>max tile detected, rebuild
  byte-identical). 41 passed.
- Phase 7 (complete): `frontend/tests/transport.test.ts` §18.6 gaps —
  rapid repeated seeks (last seek wins, stale-generation buffered/
  anchor messages dropped), near-EOF/beyond-endpoint seek clamped to
  the endpoint with no fetch past it, short final chunk (partial frame
  dropped, remainder refetched, reaches `ended`), context-rate
  mismatch (bookkeeping, fetch ranges, and clamping stay in target
  frames). 33 transport tests pass. `tests/integration/test_persistence.py`
  (§18.7) — 8 restart tests on two full app instances sharing one
  storage root: import + decoded PCM survive, reopen creates no jobs
  and leaves the PCM byte/mtime-identical (no re-decode), markers
  persist, working state (viewport/selection/display/volume/position/
  follow) persists, undo/redo history persists, stale revision → 409
  `STALE_REVISION` with state unchanged, running job marked
  `interrupted` on restart, original user file byte-identical.
- Phase 8 (complete): full gate green — Python `pytest tests/ -q`
  748 passed (702 baseline + 46 new), `ruff check` clean, `mypy` clean;
  frontend `vitest` 307 passed, `typecheck` + `lint` + `format:check`
  clean; contract export → `pnpm contracts` → `check_contract.py` in
  sync (regenerated stale M1.15 artifacts: `schema_version` default
  2 → 3). Committed as `af51265`.

**Milestone 1 exit:** all work packages M1.1–M1.16 are committed.
Out of scope for this milestone (per milestone1.md): §19 manual
browser/performance/listening acceptance and looping.

### M1.11 — Navigation, zoom, and selection (complete — `fd3468f`)

Spec: `projectPlans/milestone1.md` §13. Plan:
`projectPlans/m1.11-plan.md`. Frontend-only:
interactive horizontal zoom (§13.1), panning (§13.2), vertical zoom
refinements (§13.3), selection semantics (§13.4), ruler position
readout (§13.5). Looping, marker editing, and the AudioWorklet
transport (M1.12) are out of scope.

Key design points (see plan):
- The editor owns a width-free `View` (`{ startFrame, fpp }`,
  fractional); the `Viewport` is derived with the measured width.
  Pure math (clamp/zoom/pan/fit-range, 8 px/frame max) lands in
  `viewport.ts`.
- `useWaveform` takes the viewport as input (instead of deriving
  fit-to-song), gains an `overview` output (coarsest level, full tile
  set, fetched once per manifest), and decodes via the `worker.ts`
  wrappers (main-thread fallback in jsdom).
- `PlaybackEngine` gains a minimal `seek(offset)` (stop/reschedule
  while playing; position-only otherwise). Full seek-generation
  handling is M1.12.
- Component: zoom buttons / `+`-`-` keys / Ctrl-wheel (pointer anchor,
  non-passive native listener) / Shift-wheel / scrollbar drag /
  overview-window drag; playhead-follow with manual-pan suspension +
  return-to-playhead button; pointer click-vs-drag selection (3 px)
  with boundary handles, Escape, readout, seek-to-selection-start;
  per-lane amplitude with linked mode + localStorage persistence;
  pointer frame readout chip.
- `PlaybackPanel` gains `registerSeek`; `ProjectView` wires the seek
  function into the editor's new `onSeek` prop.

Phases: 1 plan + kickoff → 2 pure viewport math → 3 engine seek +
hook rework → 4 component navigation → 5 selection → 6 vertical zoom
+ readout → 7 frontend gate + commit.

**Phase status:** all phases complete.
- Phase 2: `viewport.ts` — `View`/`clampFpp`/`visibleFrames`/`clampView`/
  `zoomView`/`panView`/`fitRangeView` + `visibleFrameRange`;
  `tests/viewport.test.ts` 29 green.
- Phase 3: `engine.ts` `seek(offset)` (clamped; playing → stop +
  reschedule; else position-only, idle → `stopped`; `seekGeneration`
  bumped, stale fetches dropped); dead `endReached` field removed.
  `useWaveform` reworked: viewport input, `overview` output (coarsest
  level, full tile set, once per manifest, LRU-cached, failures
  non-fatal), decode via `worker.ts` wrappers. `render.ts` gained
  `drawSelection` (fill + 3 px handles) and `drawOverviewWindow`
  (fill + 1 px border). Tests: engine 10/10, useWaveform 10/10,
  render 22/22.
- Phases 4–6: `WaveformEditor.tsx` rewritten — `view` state +
  `useMemo` viewport (stable identity, no duration clamp in the memo),
  init/reset/width-reclamp/follow effects (follow re-pans only when
  the playhead leaves the visible range — 60 Hz safe); horizontal
  fieldset (Zoom in/out ×0.5/×2 center-anchored, `+`/`-` keys
  playhead-anchored, Ctrl-wheel pointer-anchored via a native
  non-passive listener, Fit song, Fit selection); hitbox pointer
  interaction (3 px click/drag threshold, click → `onSeek`, drag →
  selection, ±4 px boundary handles, no-crossing resize); scrollbar
  (track click jumps center-under-pointer, thumb drag pans; geometry
  from `contentWidth`, `left = min(start/duration × trackW,
  trackW − w)`); overview drag pan + window indicator; selection
  readout row (start – end · duration, seek-to-start, Clear);
  per-lane amplitude with linked mode, `basseparate:wave-amplitude:
  <projectId>` persistence (validated on read); pointer frame chip.
  `App.tsx`: `PlaybackPanel.registerSeek` (stable callback, `null` on
  unmount) → `ProjectView` `seekFn` state → editor `onSeek`.
  `styles.css`: hitarea, frame chip, scrollbar thumb, per-lane amp
  buttons, overview cursor, return-to-playhead, disabled states.
- Phase 7: `tests/WaveformEditor.test.tsx` rewritten (35 tests:
  states, layout, drawing, horizontal zoom, panning, selection,
  vertical amplitude, readout; jsdom pointer/wheel/key dispatch
  helpers, `getAssetPcm` mock for the PCM path). Full gate green:
  `pnpm test` 212/212, `pnpm typecheck`, `pnpm lint`,
  `pnpm format:check`.

### M1.10 — Waveform editor (complete)

Spec: `projectPlans/milestone1.md` §12. Plan:
`projectPlans/m1.10-plan.md` (written with the plan
document itself). Frontend-only: editor layout, canvas layers,
resolution selection, channel/amplitude display, empty/pending
states. Interactive zoom/pan/selection is M1.11; AudioWorklet
transport is M1.12.

Key design points (see plan):
- New files: `src/api/waveform.ts`, `src/waveform/{viewport,levels,
  decode,worker,worker-script,tileCache,render,useWaveform,
  WaveformEditor}.ts(x)`.
- Pure core (no DOM): viewport transform (§12.2, fractional coords),
  level/tile/PCM range selection (§12.5), binary parsing with explicit
  LE reads + truncation rejection (§11.5), byte-bounded LRU tile
  cache.
- `useWaveform` hook drives the §12.8 state machine
  (empty/decoding/pending/missing/ready); polls the M1.9 peaks
  manifest every 500 ms visible / 2 s hidden while a WAVEFORM job
  runs; generation counter aborts obsolete tile/PCM fetches.
- Five stacked canvas layers per lane; playhead updates redraw only
  the playhead layer; DPR-aware backing stores via ResizeObserver.
- Playhead source: existing `PlaybackEngine.onPosition` (project
  frames) lifted from `PlaybackPanel` to the project view.

Phases: 1 plan + kickoff → 2 pure core + tests → 3 `api/waveform.ts`
→ 4 `useWaveform` → 5 `render.ts` → 6 `WaveformEditor.tsx` + App
wiring + styles → 7 frontend gate + commit.

**Phase status (all 1–7 complete; frontend gate green:
160 tests / 13 files, tsc + eslint + prettier clean; backend
untouched, 628 tests):**
- Phase 2: `viewport.ts` (fit/x↔frame transforms), `levels.ts`
  (level/PCM choice, tile ranges), `decode.ts` (f32le tile parse, PCM
  aggregation), `tileCache.ts` (32 MiB byte-bounded LRU) + 4 test
  files.
- Phase 3: `src/api/waveform.ts` (JSON via openapi-fetch; binary
  tile/PCM via plain fetch + Bearer; `getPeaksManifest` null on 404;
  `NoWaveformCacheError`/`TileNotReadyError`/`RangeOutOfBoundsError`)
  + 12 API tests.
- Phase 4: `useWaveform` hook (state machine, 500 ms/2 s manifest
  polling, tile/PCM fetch with cancellation, 8 MiB PCM chunking, LRU
  + `parsePeakTile`) + `worker.ts`/`worker-script.ts` (main-thread
  fallback where `Worker` is absent) + 8 hook tests.
- Phase 5: `render.ts` pure painters (lane/PCM/sample waveforms,
  ruler with nice 1/2/5 steps, overview, playhead, lane grid) + 17
  recording-context tests.
- Phase 6: `WaveformEditor.tsx` (full §12.1 layout; five stacked
  canvas layers per lane; DPR-sized backing stores via
  ResizeObserver; vertical lane virtualization; channel collapse +
  checkboxes; amplitude scale 0.25×–16×; static scrollbar; empty
  marker/selection lanes; §12.8 state overlays with rebuild button)
  + 11 component tests (canvas 2D stub + ResizeObserver stub +
  mocked `api/waveform` with direct tile-byte injection).

**Phase 6 decisions:**
- Canonical asset id: no backend change needed — the project GET
  response (`ProjectRecord`) already exposes `canonical_asset_id`;
  it is threaded through `ProjectSummary` (`types.ts`) and
  `toSummary` (`App.tsx`) into `WaveformEditor.sourceAssetId`.
  (An interim `SourceInfoResponse.source_asset_id` backend edit was
  made and reverted after this was found.)
- Playhead lifting: `PlaybackPanel` gained an optional
  `onPositionChange` prop (called from `onPosition` and stop); it is
  wrapped in `memo` so 60 Hz position updates only re-render the new
  `ProjectView` component (which owns `playheadFrame` state and
  renders `PlaybackPanel` + `WaveformEditor` + meta), not the whole
  app.
- `tests/playback-panel.test.tsx`: fixture now carries
  `canonical_asset_id`; a `vi.mock('../src/api/waveform')` factory
  (exporting the three error classes) keeps the editor in a stable
  `missing` state without a network. `app.test.tsx` renders only
  empty projects — no change needed.
- Lane labels are derived from channel count (Mono/L/R/Ch N);
  layout-aware labels (5.1 FL/FR/…) from source info are an M1.11
  polish. The overview draws from the selected level's data — in
  fit-to-song that level guarantees ≤2 buckets/overview pixel
  (dedicated coarsest-level fetch is an M1.11 refinement).

### M1.9 — Media HTTP interfaces (complete)

Spec: `projectPlans/milestone1.md` §11. Plan:
`projectPlans/m1.9-plan.md`. Backend-only: five media routes + PCM
response contract + OpenAPI contract regen. Import (§11.1) and job
(§11.2) routes already exist. Frontend binary parsing + job polling
cadence are M1.10.

Routes: `GET /assets/{id}/metadata`, `GET /assets/{id}/pcm`
(frame-based, 8 MiB cap, EOF contract §11.4), `GET
/assets/{id}/peaks/manifest`, `GET /assets/{id}/peaks` (progressive
tiles from the M1.8 on-disk manifest), `POST
/projects/{id}/playback-preparations` (resolve/create; shared live job,
spec §6.5.6). The M1.7 `/assets/{id}/bytes` route stays (acceptance
evidence references it).

Key design points:
- `api/asset_routes.py` (new router): metadata, pcm, peaks/manifest,
  peaks. Asset resolved once per request; bytes + all metadata headers
  come from that single resolution (§11.4 rule 7).
- PCM contract: `start_frame ≥ 0` / `frame_count ≥ 1` query validation;
  `start > frame_count` → 422 `PCM_RANGE_OUT_OF_BOUNDS`; `start ==
  frame_count` → 200 zero frames + EOF; frame cap `min(requested,
  8 MiB // (4·channels), remaining)`; 1 MiB streamed chunks; headers
  `X-Asset-Id`, `X-Content-Hash`, `X-Sample-Rate`, `X-Channel-Count`,
  `X-Start-Frame`, `X-Frame-Count`, `X-EOF`. Roles: `source_pcm` /
  `derived_pcm` only (else 422 `NOT_PCM_ASSET`).
- Peaks: the on-disk manifest (M1.8) answers progressive availability;
  missing/invalid manifest → 404 `NO_WAVEFORM_CACHE` (never 500);
  geometry out of range → 422 `PEAK_RANGE_OUT_OF_BOUNDS`; tile not yet
  written → 404 `TILE_NOT_READY` (client retries). Metadata endpoint
  falls back to the DB row when no on-disk manifest.
- `playback-preparations` (in `api/playback_routes.py`): ready → source
  asset (same rate) or existing playback representation; else reuses a
  live (queued/running/cancelling) `playback_rate` job with the same
  `target_sample_rate` (shared, spec §6.5.6), else creates one through
  `JobManager.create_job` with the project's most recent completed
  import. Response: `status` ready/preparing + asset/job ids.
- 5 new errors in `api/errors.py`: `NOT_PCM_ASSET`,
  `PCM_RANGE_OUT_OF_BOUNDS`, `PEAK_RANGE_OUT_OF_BOUNDS`,
  `NO_WAVEFORM_CACHE`, `TILE_NOT_READY`.

Phases (all complete): 1 plan + kickoff → 2 errors + metadata/pcm
routes + tests → 3 peaks routes + tests → 4 playback-preparations +
tests → 5 contract regen (`contracts/openapi.json` +
`frontend/src/api/schema.ts`, `check_contract.py` OK) + full suite +
commit. 28 route tests in `tests/unit/test_asset_routes.py` (seeded via
repositories + real waveform engine, no ffmpeg).

Verification: 628 backend tests pass (600 at M1.8); 47 frontend tests
pass; `ruff check src/ tests/` clean; mypy strict clean (46 files);
contract artifacts in sync.

### M1.8 — Waveform pyramid (complete)

Spec: `projectPlans/milestone1.md` §10. Plan:
`projectPlans/m1.8-plan.md`. Backend-only: cache layout, streaming
generator, progressive publication, validation, memory bound, `WAVEFORM`
job type (last unimplemented one). Routes: M1.9; rendering: M1.10.

Key design points (see plan):
- Cache: `cache/waveforms/<source_hash>/` — `manifest.json` (atomic
  rewrites) + `level_L/tile_XXXXXX.bin` (4096 buckets/tile; bucket =
  per-channel signed min/max, f32le; level L bucket = `64·4^L` frames).
- On-disk manifest is the source of truth for progressive tile
  availability; the worker never touches the DB (M1.4 boundary).
- Streaming engine: bounded 4 MiB blocks, per-level partial-bucket
  buffers (≤ 4096+3), groups of 4 aggregate up, no zero padding of
  partial buckets, atomic tile writes + manifest updates per tile.
- Failure/cancel → delete the whole cache dir (cheap rebuild).
- Schema v5: `waveform_caches` table (one row per canonical asset).
- `build_publishers` gains `job_repository` + `cache_repository` params
  (auto-queue a WAVEFORM job after canonical commit).
- No new routes in M1.8; no contract regen.

Phases (all complete):
1. `domain/waveform.py` — frozen models (manifest/level summary/result/
   cache record), geometry (`expected_levels`, `tile_byte_count`),
   `validate_manifest`; exported from `domain/__init__.py`.
2. `media/waveform.py` — streaming engine (`build_waveform_cache`),
   `validate_tile_bytes`, `WaveformError`/`WaveformFailedError`/
   `WaveformCancelledError`; 37 unit tests in `tests/unit/test_waveform.py`.
3. Schema v5 (`waveform_caches` + `idx_waveform_caches_source_hash`),
   `WaveformCacheRepository` (idempotent `register` with hash/manifest
   guards, `get_for_asset`, `delete_for_asset`; manifest stored relative
   as `cache/waveforms/<hash>/manifest.json`), `cache` prefix in
   `resolve_asset_path`; 40 storage tests.
4. Worker `_run_waveform` (parameter validation `WAVEFORM_PARAMETERS`,
   missing/size-mismatch/hash-mismatch guards, progress, cancel + whole
   cache-dir cleanup) + dispatch; `JOB_TYPE_NOT_IMPLEMENTED` coverage
   moved to a synthetic-type dispatch test
   (`tests/unit/test_media_worker_dispatch.py`); 7 worker integration
   tests.
5. Manager: WAVEFORM in `_PARAMETERIZED_JOB_TYPES` (default guard
   `NO_CANONICAL`), `WaveformResult` verification; publisher
   `_publish_waveform` (final manifest + hash match + level-0 last-tile
   spot-check → idempotent `register`) and `_queue_waveform_if_needed`
   (skips live/completed WAVEFORM jobs, retries after failed/cancelled);
   `build_publishers(imports, projects, representations, paths,
   jobs, waveform_caches)`; `app.py` wiring (`_waveform_parameters_for`
   with `cache_dir`, `app.state.waveform_cache_repository`); manager
   picks up out-of-band queued jobs after each publish
   (`_enqueue_newly_queued` + `_known_job_ids`); 13 publisher + 32
   manager integration tests (incl. end-to-end decode → auto-queued
   WAVEFORM → registered cache row).
6. Full verification: 600 backend tests pass (538 at M1.7); `ruff check
   src/ tests/` clean; mypy strict clean (45 files).

### M1.7 — Monitoring channels + playback-rate representations (complete)

Spec: `projectPlans/milestone1.md` §9 (line 643+). Plan:
`projectPlans/m1.7-plan.md`. Acceptance: 44.1 kHz and 48 kHz sources play
with correct pitch and duration at either browser output rate.

**Phases 1–4 (complete, tested):**
- `domain/representation.py`: `MonitoringDownmixResult` +
  `PlaybackRateResult` models; v2 transform keys
  (`compute_downmix_key` / `compute_playback_key`).
- `storage/db.py`: schema v4 (`monitoring_asset_id`,
  `monitoring_left/right_channel` on projects; derived-asset role
  `derived_pcm`); `DATABASE_SCHEMA_VERSION=4`.
- `media/downmix.py` (new): spec §9.3 matrices — `standard_51_matrix()`
  (row-normalized Σ|coef|), `manual_matrix(l, r)`, `pan_expression()`
  (FFmpeg `pan=stereo|c0=...|c1=...`, no shell escaping),
  `resolve_downmix()`, `channel_labels()`, `MonitorSelectionError`.
- `media/derived.py` (new): `downmix_monitoring()` + `resample_playback()`
  via pinned `aresample=<rate>:filter_size=64:exact_rational=1:
  dither_method=0` profile v1; 19 engine tests.
- `worker/media_worker.py`: derived runs + dispatch; `TestDerivedJobs`.

**Phase 5 (complete):**
- `storage/paths.py`: `resolve_asset_path()` (data/ runtime/ state/
  prefixes for both XDG and `--storage-root` layouts).
- `storage/repository.py`: `ProjectRepository.get_asset()`;
  `set_monitoring()` (single transaction: register asset, attach, set
  monitoring fields).
- `jobs/manager.py`: `ParameterResolutionError(code, message)` (exported
  from `basseparate.jobs`); `_PARAMETERIZED_JOB_TYPES`; `_run_job`
  resolves parameters before the worker runs — a resolution failure
  fails the job with that code; empty dict → type-specific default
  (`NO_STREAM_SELECTION` decode / `NO_CANONICAL` derived).
- `app.py`: `_canonical_pcm_asset`, `_downmix_parameters_for`,
  `_playback_parameters_for`, `_job_parameters_for` dispatch;
  `RepresentationRepository` now on `app.state`.
- `jobs/publisher.py`: `_ensure_derived_asset` (hash dedup, moves staging
  → `data/assets/<hash>.pcm`, registers the row before any FK reference),
  `_publish_downmix` (parent = canonical, layout "stereo", identity
  mapping, matrix transform key, then `set_monitoring`),
  `_publish_playback` (parent = monitoring-or-canonical, TimeMapping
  project_rate→representation_rate, standalone — never attached to the
  project); both check `get_representation` before registering
  (idempotent re-publish).
- `api/errors.py`: 5 new errors — `AssetNotFoundError` (404),
  `ProjectNotReadyError` (409), `InvalidMonitoringSelection` (422),
  `NoPlaybackRepresentation` (404), `RangeNotSatisfiable` (416).
- `api/playback_routes.py` (new): `PUT
  /projects/{id}/monitoring-channels` (range-validated, 409 if not
  ready), `GET /projects/{id}/source-info` (rate, duration, labels,
  monitoring state, available playback rates), `GET
  /projects/{id}/playback?rate=N` (Query 8000–192000; source asset at
  its own rate, else the published representation, else 404),
  `GET /assets/{asset_id}/bytes` (HTTP Range: 200 full / 206 partial /
  416 unsatisfiable, 1 MiB `StreamingResponse` chunks,
  `Accept-Ranges`/`Content-Range`).
- `api/job_routes.py`: `CreateJobRequest.target_sample_rate`
  (int, 8000–192000) — required for `playback_rate` (422
  `JOB_REQUEST` if missing), rejected for other types; passed as
  `parameters={"target_sample_rate": ...}`.

**Phase 5 tests (all green):**
- `tests/unit/test_playback_routes.py` (new, 22 tests): full-pipeline
  ready projects (1/2/4-ch WAV) — monitoring-channels validation,
  source-info shape, playback resolution (incl. 404
  `NO_PLAYBACK_REPRESENTATION`), asset bytes 200/206/416.
- `tests/integration/test_publisher.py` (new, 9 tests): seeded ready
  projects via `publish_source` (no ffmpeg) — downmix standard 5.1 +
  manual, playback (incl. parent-is-monitoring chain), failure paths,
  idempotency (single asset + representation row).
- `tests/integration/test_job_manager.py`: +13 tests —
  `TestParameterResolution` (ParameterResolutionError → job fails with
  code; empty params → default codes) and `TestParameterResolvers`
  (real `_job_parameters_for`: 5.1 pan spec, manual selection,
  MISSING_MONITORING_SELECTION, NO_DOWNMIX_NEEDED, NO_CANONICAL,
  playback canonical/monitoring source, INVALID_TARGET_RATE).
- `tests/unit/test_job_routes.py`: +4 tests — `target_sample_rate`
  required/rejected/out-of-bounds, NO_CANONICAL end-to-end.
- Totals: 524 py tests pass (unit + integration); ruff + mypy clean.

**Phase 6 (complete this session):**
- `contracts/openapi.json` + `frontend/src/api/schema.ts` regenerated.
- `frontend/src/playback/pcm.ts` (new): `deinterleaveF32le`,
  `projectPosition`, `clampToDuration`, `formatTime` (m:ss.mmm),
  `framesFromBytes`.
- `frontend/src/api/playback.ts` (new): `getSourceInfo`, `resolvePlayback`
  (404 `NO_PLAYBACK_REPRESENTATION` → typed error), `createJob`
  (`JobType` from generated schema), `getJob`, `waitForJob` (500 ms poll,
  120 s timeout, abortable), `ensurePlaybackTarget` (resolve → 404 →
  create `playback_rate` job → poll → re-resolve), `setMonitoringChannels`,
  `fetchAssetBytes` (plain fetch + Bearer + `Range`; 416 → `RangeError`;
  total from `content-range`/`content-length`), `latestCompletedImportId`.
- `frontend/src/playback/engine.ts` (new): `PlaybackEngine` with injected
  `AudioContextLike`; 1.5 s lookahead, 150 ms scheduler tick, 50 ms start
  delay, 4 MiB default chunk; `idle|loading|playing|paused|stopped|error`
  state machine; `endReached` so natural end reports the end position
  (user stop → 0); position reported every tick; injectable delay for
  tests; `dispose()` closes only owned contexts.
- `frontend/src/App.tsx`: `PlaybackPanel` — source info, monitoring
  channel selection (L/R `<select>`s for >2-ch sources; standard 5.1
  skips the PUT), transport (play/pause toggle, stop, time readout,
  "Preparing playback…", errors); wired into the ready project view.
- `frontend/src/styles.css`: playback panel styles (dark theme).
- 28 new js tests: `tests/pcm.test.ts` (15), `tests/engine.test.ts` (6)
  + `tests/helpers/pcm-fixture.ts` (fake `AudioContext` harness),
  `tests/playback-panel.test.tsx` (7; mock handler factory — jsdom has no
  `AudioContext`). 47 js tests total; `pnpm run lint|typecheck|test|build`
  all clean.

**Phase 7 (complete this session):**
- `tests/integration/test_m17_acceptance.py` (new, 14 tests) — the
  acceptance matrix: 44.1 kHz / 48 kHz source × 44.1 kHz / 48 kHz
  playback, real ffmpeg `resample_playback` on a 1 s 440 Hz stereo sine:
  duration (output frame count within ±2 of the exact rational
  conversion), pitch (upward zero-crossing frequency ≈ 440 Hz ±2 %,
  analyzed on one de-interleaved channel), determinism (byte-identical
  runs). Plus the full pipeline: seeded ready 44.1 kHz project → resample
  → real publisher → `find_playback` resolves with resampled bytes on
  disk and staging moved; same-rate playback needs no representation.
- Full verification: 538 py tests pass (524 + 14); `ruff check
  src/ tests/` clean; `mypy` clean (43 files); 47 js tests, lint /
  typecheck / build clean.
- Note: `ruff check scripts/` had 2 pre-existing findings from
  M0.10/M0.11 (RET504 in `dev.py`, F541 in `generate_licenses.py`).
  The F541 was fixed during the 2026-10-24 doc refresh; the RET504 in
  `dev.py` remains for a later cleanup.

**Commit:** `af6ad7f` (implementation); ledger hash in the following
commit.

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

### M1.6 — Asset publication, hashing, and disk budgeting (complete)

Spec: `projectPlans/milestone1.md` §8 (lines 557–646). Gate B covers
M1.4–M1.6. Plan: `projectPlans/m1.6-plan.md`.

**Scope analysis:** most of §8 landed with M1.5 — content-addressed storage
(`data/assets/<hash>.pcm`, dual identity: content hash + transformation
key), the v1 transformation key (all seven canonical-decode elements), the
publication sequence (staging on the destination volume → validate → hash →
atomic same-filesystem rename → asset row → transactional project attach →
complete only after commit), hash-based dedup (originals by source hash,
canonical by content hash; never filename/size), and the cleanup boundary
(source/canonical preserved, no GC, stale staging removed only after
recovery). M1.6 closed the remaining gaps:

**Disk budget (§8.5):**
- `media/decode.py`: `PUBLISH_RESERVE_BYTES = 2 GiB`;
  `_required_free_bytes` now budgets retained original + `1.25 ×` canonical
  PCM estimate + the 2 GiB free-space reserve (64 MiB floor). Milestone 1
  has no monitoring/playback representations or waveform caches, so their
  budget is zero. `decode_canonical` passes the source file size as the
  retained original.

**Dedup policy (§8.4.2):**
- `_ensure_pcm_asset` documents that content-hash reuse is the stronger
  form of the transformation-key rule (identical bytes ⇒ identical key for
  a deterministic pipeline).

**Acceptance tests:**
- `tests/unit/test_decode.py` `TestDiskBudget` (3): exact budget
  arithmetic; no-estimate floor; fake low-free `shutil.disk_usage` →
  `InsufficientDiskSpaceError` before ffmpeg starts, no output file.
- `tests/integration/test_job_manager.py`
  `test_crash_between_publish_and_commit_recovers`: decode → delete asset +
  representation rows (file survives) → re-decode → same hash, fresh asset
  row, on-disk file byte-identical (reused, not re-written), project ready
  with the new canonical asset id. This is §8.3's "unreferenced complete
  asset, not a broken project" plus the acceptance property "reopening
  reuses existing assets".

**Verification:**
- `pytest tests/unit tests/integration -q`: 424 passed
- `ruff check src/ tests/`: clean
- `mypy`: clean (40 files)

**Commit:** `4098c58` (implementation); ledger hash in the following
commit.

### M1.5 — Decode canonical audio (complete)

Spec: `projectPlans/milestone1.md` §7 (lines 476–553). Gate B covers M1.4–M1.6.
Plan: `projectPlans/m1.5-plan.md` (9 phases, written 2026-10-03).

**Media engine:**
- `media/_process.py` (new): shared subprocess helpers — graceful termination
  with kill escalation (`TERMINATE_GRACE_SECONDS = 5.0`), cancel polling
  (`CANCEL_POLL_SECONDS = 0.1`), bounded stream reads. `probe.py` refactored
  onto it (behavior unchanged).
- `media/decode.py` (new): `decode_canonical()` runs the verified production
  command (`-map 0:<global_index>`, `-af aresample=async=1`,
  `-c:a pcm_f32le -f f32le -progress pipe:2`; no resample/reslice/seek —
  rate and channels are preserved). Disk headroom check before start (1.25×
  estimated PCM + 64 MiB floor). Progress parsing (0.25 s throttle, final
  block always emitted); cancel + timeout; the partial output file is removed
  on every failure path (cancel, timeout, non-zero exit, misalignment,
  non-finite, empty). Validation: frame alignment (size % 4), single-pass
  8 MiB-chunked SHA-256 + numpy `isfinite` + max amplitude; 0 frames →
  `EmptyAudioError`. Timing repair is detected arithmetically
  (`|decoded − probe duration| > 0.5 s` → warning, inclusive boundary).
  `mime_type_for_format` table for asset records.
- `domain/representation.py`: frozen `CanonicalDecodeResult` (frame count,
  rate, channels, layout, content hash, max amplitude, byte count, decoded/
  estimated duration, discrepancy, decoder + timing-repair warnings, tool
  versions, profile version, staging path) and `compute_transform_key` v1 —
  canonical JSON over (source_sha256, stream_index, profile_version,
  ffmpeg_version, "f32le", "preserve", "decoder-default",
  "async-fill-trim"). Content-addressed storage + this key satisfy the M1.5
  acceptance: reproducible sample count, preserved channel structure,
  defined time origin.

**Worker:**
- `worker/media_worker.py`: `_run_canonical_decode` — parameter validation
  (stream_index ≥ 0; sample_rate 8 000–192 000; channel_count 1–16; layout
  string) → `DECODE_PARAMETERS`; staged `canonical.pcm`; progress
  `decoded X.Ys of ~Z.Zs`; error mapping (`EmptyAudioError` → `EMPTY_AUDIO`,
  cancel → cancelled, timeout → `DECODE_TIMEOUT`, else `DECODE_FAILED`);
  staging removed on every non-completion path. Completion sends result
  metadata only — the worker never touches the database.

**Manager:**
- `jobs/manager.py`: injectable `parameters_for` closure; a decode job with
  no parameters fails `NO_STREAM_SELECTION` before staging/RUNNING;
  `_publish` runs the publisher while the job is still RUNNING (verify
  result vs probe → publish → `complete_job`); a publisher exception fails
  the job `PUBLISH_FAILED` (a completed job always has its references
  committed); staged dir cleaned after publish.

**Publisher + storage:**
- `jobs/publisher.py` (new): `build_publishers(imports, projects,
  representations, paths: StoragePaths)`. `_publish_decode` re-verifies the
  result against the probe (stream rate/channels), dedups the PCM asset by
  content hash (`get_asset_by_hash`), registers the original asset from the
  uploaded `.part` (`runtime/uploads/<import_id>.part`), and inserts the
  representation + asset rows + project source fields + ready state inside
  `ProjectRepository.publish_source`'s single `BEGIN IMMEDIATE` transaction.
  Idempotent: hash dedup + `INSERT OR IGNORE` + re-set source fields.
  PCM lands at `data/assets/<hash>.pcm`.
- `storage/repository.py`: `get_asset_by_hash`, `publish_source`
  (transactional attach), `_row_to_asset`.

**API:**
- `api/errors.py`: `MissingStreamSelection` (422, code
  `NO_STREAM_SELECTION`); `api/job_routes.py` rejects `canonical_decode`
  when the import has no selected stream (multi-stream files complete
  without auto-selection). Probe + canonical_decode are the two executable
  job types.
- `app.py`: `_decode_parameters_for(job, imports)` builds decode parameters
  from the import's probe + selected stream ({} when none →
  NO_STREAM_SELECTION); lifespan wires `build_publishers(...)` and the
  `parameters_for` closure.

**Tests (420 total):**
- `tests/unit/test_decode.py` (35): result invariants, transform key,
  progress parsing, alignment, discrepancy (inclusive boundary),
  `validate_pcm` (hash, amplitude, NaN/Inf, odd size, 16 MiB chunking),
  MIME table.
- `tests/integration/test_decode.py` (16, real ffmpeg): exact frame counts,
  deterministic byte-identical re-decodes, stereo preserved, progress
  ordering; MP3/M4A/Opus re-decodes byte-identical with codec-delay
  tolerance; empty WAV → `EMPTY_AUDIO`; truncated MP3 → non-empty
  `decoder_warnings`; cancel + timeout remove the partial output;
  resampler policy at the filter level (gap +48 000, overlap −24 000,
  clean no-op @48 kHz).
- `tests/integration/test_media_worker.py` (14): decode completion with
  staged `canonical.pcm` + result metadata; `DECODE_PARAMETERS`
  (missing/invalid); `DECODE_FAILED` (missing source); in-flight cancel via
  fake slow ffmpeg → staging removed; unimplemented type is now
  `monitoring_downmix`.
- `tests/integration/test_job_manager.py` (14): e2e probe → decode (assets,
  representation, project ready), re-decode dedup, `NO_STREAM_SELECTION`,
  `PUBLISH_FAILED` leaves no partial state and staging is cleaned.
- `tests/unit/test_job_routes.py` (15): 422 `NO_STREAM_SELECTION` (two-
  stream MKV fixture); e2e decode → project ready with source fields.
- `tests/unit/__init__.py` + `tests/integration/__init__.py`: fix the pytest
  basename collision between the two `test_decode.py` files.

**Verification:**
- `pytest tests/unit tests/integration -q`: 420 passed
- `ruff check src/ tests/`: clean
- `mypy`: clean (40 files)

**Commit:** `b1d92d1` (implementation); ledger hash in the following
commit.

### M1.4 research notes (FFmpeg 8.1.2 experiments, 2026-10-03)

**Experiments in /tmp/opencode/gaptest; the implementation section follows.**
- Production decode command verified: `ffmpeg -hide_banner -nostdin
  -v warning -threads N -i src -map 0:<global_index> -af aresample=async=1
  -c:a pcm_f32le -f f32le -progress pipe:2 out.pcm`. Explicit global-index
  map selects the probe-verified stream; video/subs/data excluded.
- `aresample=async=1` (default `min_hard_comp=0.1` s) = filling+trimming:
  `asetpts +1 s` gap → exactly +48000 padded samples @48 kHz; `asetpts
  −0.5 s` overlap → exactly −24000 trimmed; clean stream → no-op. No speed
  correction. (Modern option names: `min_comp`/`min_hard_comp`/
  `comp_duration`/`max_soft_comp`/`async` — the old `min_comp`/`max_comp`
  pair no longer exists.)
- Resampler gap/trim log lines are `AV_LOG_VERBOSE`
  ("adding N audio samples of silence" / "discarding N audio samples") —
  not visible at `-v warning`; timing repair is therefore detected
  arithmetically: `|decoded_duration − probe_duration| > 0.5 s` → warning.
- Codec delay/priming (1 s @44100 mono, deterministic across runs): mp3 →
  44100 frames, aac/m4a → 45056, opus/ogg → 48000.
- Zero-sample input → exit 0 + 0-byte output (→ `EMPTY_AUDIO`).
- Truncated media can exit 0 with decoder warnings on stderr (mp3:
  "invalid new backstep -1") → recorded, never a silent clean import.
- File-level gap/overlap fixtures not constructible here: MP3/M4A/MKV/TS
  muxers normalize audio timestamps; concat demuxer ignores
  `#outputts_offset` (this build); HLS demuxer hangs. Policy tested at the
  resampler level with `asetpts` (the component the production filter
  configures).

### M1.4 — Durable media jobs (complete)

Spec: `projectPlans/milestone1.md` §6 (lines 384–473). Gate B covers M1.4–M1.6.
Plan: `projectPlans/m1.4-plan.md` (8 phases).

**Domain:**
- `domain/media_job.py` (new): `JobType` (probe, canonical_decode,
  monitoring_downmix, playback_rate, waveform), `JobState` (queued, running,
  completed, failed, cancelling, cancelled, interrupted), `JobStage`, frozen
  `MediaJob`, `ALLOWED_TRANSITIONS` + `assert_transition` +
  `InvalidJobTransition`, `TERMINAL_STATES`. `queued → failed` is allowed
  (a job whose source is missing fails before it starts).

**Protocol v2:**
- `WORKER_PROTOCOL_VERSION` → 2. Six new message types: `run`, `progress`,
  `completed`, `failed`, `cancel`, `cancelled`. Explicit negotiation via
  `assert_protocol_version(hello)` + `ProtocolVersionMismatch` in
  `worker/supervisor.py`. `ERR_NOT_IMPLEMENTED = "JOB_TYPE_NOT_IMPLEMENTED"`.
- `worker/supervisor.py`: `media_worker_command()`; `_stdin_lock` serializes
  concurrent `send()`/`send_raw()` writes (route tasks and the scheduler can
  both send).

**Storage:**
- `DATABASE_SCHEMA_VERSION` → 3; migration 2→3: `media_jobs` table (CHECK
  constraints on job_type/state, FK `project_id` CASCADE, `import_id`
  SET NULL, indexes on `project_id` + `state`).
- `storage/repository.py`: `JobRepository` (create_job, get_job,
  list_jobs_for_project, set_state with transition assertion, set_progress,
  complete_job, fail_job, mark_interrupted). `PROJECT_SCHEMA_VERSION` stays 2
  (separate from the DB schema version). Fixed a latent bug: the repository's
  `SCHEMA_VERSION` constant was written into the `projects.schema_version`
  column; it now uses `PROJECT_SCHEMA_VERSION`.

**Worker + manager:**
- `worker/media_worker.py` (new): main thread reads stdin; one job thread for
  the active job; all stdout writes under `_stdout_lock`; staging removed on
  cancel/fail; `shutdown` cancels + joins (≤15 s) then emits `stopped`.
  `probe` executes via `probe_media`; the other four types return
  `JOB_TYPE_NOT_IMPLEMENTED` (real execution lands in M1.5–M1.7).
- `media/probe.py`: `probe_media` accepts an optional `cancel_event`;
  `ProbeCancelledError`; polls the event every 0.1 s; on cancel: graceful
  `terminate()` → wait ≤5 s → `kill()` (`TERMINATE_GRACE_SECONDS = 5.0`).
- `jobs/manager.py` (new): async `JobManager` in the API process. `start()`:
  spawn worker → handshake → `assert_protocol_version` → `mark_interrupted()`
  → reload queued jobs FIFO → scheduler task (one job at a time). `stop()`:
  cancel scheduler → stop supervisor. Injectables: `worker_command`,
  `source_path_for`, `publisher`. Staging at `staging_root/job_id.hex/staging`;
  `_cleanup_stale_staging()` at startup. `_publish` verifies
  `ProbeResult(**result)` before `complete_job`; the publisher runs only after
  the state is durably `completed`. Worker exit → `interrupted`;
  timeout/error → `failed`. The scheduler loop is exception-safe: one bad job
  cannot kill scheduling (failed as `INTERNAL_ERROR` and the loop continues).
- `build_import_publisher(import_repository)`: for completed probe jobs with
  an import_id, persists the probe result + auto-selects the single stream.

**API (no frontend UI in M1.4 — job API + generated schema only, per spec):**
- `api/job_routes.py` (new): `GET /api/v1/jobs/{id}`,
  `GET /api/v1/projects/{id}/jobs`, `POST /api/v1/projects/{id}/jobs` (201;
  import_id required; import must exist, belong to the project, and be
  COMPLETE; linked via `ImportRepository.add_job_id`),
  `POST /api/v1/jobs/{id}/cancel` (terminal → no-op; queued → cancelled;
  running → cancelling → worker finalizes → cancelled + staging cleaned).
- `api/errors.py`: `JobNotFoundError` (404), `InvalidJobType` (422),
  `JobRequestError` (422).
- `app.py` lifespan: `app.state.job_repository` + `app.state.job_manager`
  (staging `paths.runtime/jobs`, `source_path_for=UploadManager.part_path_for`,
  import publisher); `job_router` included. The app now spawns the media
  worker subprocess at startup (~50 ms; affects all TestClient-based tests).

**Tests:**
- `tests/unit/test_media_job.py` (new): model + full transition map.
- `tests/unit/test_job_repository.py` (new): CRUD, transitions, progress/
  result, `mark_interrupted`, FK cascade/SET NULL.
- `tests/unit/test_worker_protocol.py`: extended with v2 job-message
  roundtrips.
- `tests/integration/test_media_worker.py` (new): real worker subprocess —
  probe to completion, unimplemented type, in-flight cancel + staging cleanup,
  shutdown-while-running, missing source. Deterministic cancel tests use a
  fake slow `ffprobe` (`exec sleep 30`; PATH prepended before `start()`),
  because real ffprobe is sub-second on all local files (it estimates
  duration, it does not scan).
- `tests/integration/test_job_manager.py` (new): probe to completion +
  publisher, unimplemented type, cancel queued/running, restart →
  interrupted, stale staging cleanup, acceptance: a completed result survives
  a later failure; a cancelled job publishes nothing.
- `tests/unit/test_job_routes.py` (new): create/list/get/cancel via TestClient
  with the full M1.2 upload flow; 404/409/422 cases.

**Verification (all green):**
- `uv run --locked pytest tests/ -q`: 358 passed
- `uv run --locked ruff check src tests`: clean
- `uv run --locked ruff format --check src tests`: clean
- `uv run --locked mypy`: clean
- `scripts/check_contract.py`: OK (contracts + `schema.ts` regenerated;
  job routes + MediaJob schemas added)
- `pnpm run typecheck`: clean
- `pnpm run lint`: clean
- `pnpm run test`: 19 passed
- `pnpm run build`: clean

**Blocked:** none.

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

## Milestone 2 progress

### M2.1 — Confirm prerequisites and extend the domain (complete)

Spec: `projectPlans/milestone2.md` §3; plan: `projectPlans/m2.1-plan.md`.
Scope is domain + schema + serialization + frontend types only — no Demucs,
GPU, or network. Acceptance: a result set, its audio, and its playback
settings can be represented without modifying the original source record.

- **Phase 1 — Plan + ledger:** done. Plan written; ledger section added.
- **Phase 2 — Prerequisite checks (§3.1):** ran the full M1 test corpus as
  the prerequisite gate (import/reopen, hashes, playback, waveforms,
  rapid-seek, interrupted-job recovery, command history, local-only
  startup are all covered by the M1.16 suite). **Found 1 genuine bug**
  (`test_oversized_body_rejected`): `import_routes.py` string-parsed the
  `UploadError` "insufficient disk space" message and crashed with a 500
  `ValueError` instead of returning 507 `INSUFFICIENT_DISK_SPACE`. Root
  cause: the message carries an `insufficient disk space: need ` prefix the
  parser did not strip. The test was also environment-dependent (declared a
  10 GiB import; `reserve` adds 2 GiB headroom → needs 12 GiB of free disk).
  **Fix:** added structured `uploads.InsufficientSpaceError(needed, free)`;
  `reserve` raises it; the route catches it and returns 507. Reduced the
  chunk test's import to 16 MiB and added
  `test_insufficient_disk_space_returns_507` (mocks `free_bytes`). Gate now
  green: 748 py (747 baseline + 1 new, the 1 previously failing now passes).
- **Phase 3 — Domain records (§3.2–3.4):** done. `domain/separation.py` —
  `SeparationRun` (requested vs. effective params kept separate for
  auditability; cuda⇔gpu_uuid, completed⇔result_set invariants),
  `SeparationResultSet` (a `valid` set requires ≥1 stem + positive frame
  count; no duplicate roles), `StemRecord` (role from the model's declared
  label, bounded alignment offset, reuses `Confidence`), `SourceIdentity`,
  `ReferenceMixIdentity` + enums (`SeparationMode`, `SeparationRunStatus`,
  `ValidationStatus`, `DeviceType`, `StemRole`). Exported from
  `domain/__init__.py`.
- **Phase 4 — Mixer + practice state (§3.5):** done. `domain/practice.py` —
  `PlaybackMode`, `TrackSettings` (gain/balance/display-height bounds),
  `PracticeLoop` (end > start), `PracticeState` (stem modes require an active
  result set; `active_loop_id` references an existing loop; `tracks` keyed by
  stem role). `ProjectRecord` gains `practice_state` (defaulted, so v3
  projects deserialize unchanged).
- **Phase 5 — Versioning (§3.6):** done. DB migration 6→7 (`separation_runs`,
  `separation_result_sets`, `stems` tables — key columns + `record_json` blob —
  + `projects.practice_state` column); `DATABASE_SCHEMA_VERSION` 6→7,
  `PROJECT_SCHEMA_VERSION` 3→4; `SeparationRepository` (create/get/list for
  run, result set, stem) + `ProjectRepository.set_practice_state` (bumps
  revision, no history — command integration is M2.17).
- **Phase 6 — Tests:** done. New `tests/unit/test_separation.py`,
  `tests/unit/test_practice.py`; extended `tests/unit/test_project.py`
  (practice_state default/round-trip/v3-JSON-loads); new
  `tests/integration/test_migration_m2.py` (v6→v7: tables + defaulted
  practice_state, old project survives) and
  `tests/integration/test_separation_repository.py` (full round-trip; the
  original source record is value-for-value unchanged). Updated
  `test_storage_db.py` (v7 version, new tables) and
  `test_repository_commands.py` (v7 version assertion).
- **Phase 7 — Contract + frontend types:** done. Regenerated
  `contracts/openapi.json` + `frontend/src/api/schema.ts`; `practice_state`
  is generated **optional** (server default) so no frontend `Project` literal
  needed updating. Drift check OK. Frontend typecheck + lint + format clean.
- **Phase 8 — Full gate + commit:** **gates green.** Final full pytest:
  **800 passed** (748 M1 baseline + 52 new/updated). ruff clean, mypy clean
  (51 files), vitest 307 passed, frontend typecheck/lint/format clean,
  contract drift check OK. One observed flake:
  `test_job_manager.py::TestDecodeCompletion::test_publisher_failure_fails_job`
  failed once in a full-suite run but passes 3/3 in isolation and 3/3 for the
  whole class; the same test passed in the prior full run with identical
  code. Pre-existing async-teardown flake under load (matches the "Event
  loop is closed" ResourceWarning), unrelated to M2.1 (no job-manager,
  publisher, or decode-path changes).

**Deliverables:**
- `src/basseparate/domain/separation.py` — `SeparationRun`,
  `SeparationResultSet`, `StemRecord`, `SourceIdentity`,
  `ReferenceMixIdentity` + enums (`SeparationMode`, `SeparationRunStatus`,
  `ValidationStatus`, `DeviceType`, `StemRole`).
- `src/basseparate/domain/practice.py` — `PlaybackMode`, `TrackSettings`,
  `PracticeLoop`, `PracticeState`; `ProjectRecord.practice_state` (defaulted).
- `src/basseparate/storage/db.py` — migration 6→7 (`separation_runs`,
  `separation_result_sets`, `stems`, `projects.practice_state`).
- `src/basseparate/storage/repository.py` — `SeparationRepository`,
  `ProjectRepository.set_practice_state`.
- `src/basseparate/uploads.py` + `api/import_routes.py` — prerequisite bug
  fix (structured `InsufficientSpaceError`, 507 path).
- Version bumps: `DATABASE_SCHEMA_VERSION` 6→7, `PROJECT_SCHEMA_VERSION`
  3→4.
- Tests: `tests/unit/test_separation.py`, `tests/unit/test_practice.py`,
  `tests/integration/test_migration_m2.py`,
  `tests/integration/test_separation_repository.py`; extended
  `test_project.py`, `test_storage_db.py`, `test_repository_commands.py`,
  `test_imports.py`.
- Contracts: `contracts/openapi.json` + `frontend/src/api/schema.ts`
  regenerated (additive; `schema_version` default 3→4).

### M2.2 — Create the isolated Demucs runtime (complete)

Spec: `projectPlans/milestone2.md` §4; plan: `projectPlans/m2.2-plan.md`.
Scope: separately locked analysis environment, PyTorch/CUDA qualification
(both GPUs + CPU), and device records/selection in the main backend (which
stays free of PyTorch). Bundled model is M2.3; adapter is M2.5; API is
M2.17.

**Runtime assessment (2026-10-10):** driver 595.99.02 (CUDA 13.2); GPU0
RTX 4080 cc 8.9 / 16376 MiB; GPU1 RTX 5060 Ti cc 12.0 (Blackwell) /
16311 MiB. Blackwell requires cu128 wheels. Selected `torch==2.9.1+cu128`
(cp311 wheel verified on the official index; latest patched stable line
covering SM89 + SM120). Demucs 4.1.0 needs `torch>=2.1` — compatible.
Network to download.pytorch.org + PyPI verified.

- **Phase 1 — Plan + ledger:** done.
- **Phase 2 — Isolated environment (§4.1):** done. `analysis/` project
  (Python 3.11, demucs 4.1.0, torch 2.9.1 from the pytorch-cu128 index,
  soundfile); `uv lock` (48 packages, torch locked at `2.9.1+cu128`) +
  `uv sync --locked` (47 resolved packages); `tool.uv.environments`
  restricted to Linux because demucs pins `torch<2.3` on darwin/x86_64.
  Fingerprint: `docs/evidence/m2.2-analysis-environment.md` (git-ignored
  local report; the committed lock is the authoritative fingerprint).
  Main env verified torch/demucs-free (guard test included).
- **Phase 3 — Qualification (§4.2, §4.3):** done. `analysis/qualify.py`
  run with the explicit analysis interpreter: tensor/conv/FFT per GPU, a
  5 s `htdemucs` run per device (4 stems, all finite), CPU path at 4
  threads including a model run. **All three devices qualified** —
  including the Blackwell RTX 5060 Ti (SM120) on the cu128 wheel.
  Results: `docs/evidence/m2.2-qualification.md`. The final qualifying run
  used the exact `uv sync --locked` environment (an earlier debug round
  with a locally downgraded cffi was discarded and re-run after re-sync).
  One script bug fixed along the way: `sf.write` was given
  channels×frames data (soundfile wants frames×channels; libsndfile then
  rejected the implied >1024-channel WAV — not a soundfile bug).
- **Phase 4 — Device records + selection (§4.4–4.5):** done.
  `domain/device.py` (`DeviceRecord`, `QualificationStatus`, `DeviceKind`
  + invariants: qualified ⇒ timestamp, failed ⇒ reason, GPU ⇒ total VRAM,
  CPU ⇒ identifier `cpu` and no VRAM facts); `devices.py`
  (nvidia-smi discovery subprocess with injectable runner, free-VRAM
  refresh, JSON `QualificationStore` under the data dir,
  `select_device` with preference-by-UUID, first-qualified default order,
  explicit CPU offer, no silent GPU→CPU substitution); 42 unit tests
  (domain invariants, stubbed-nvidia-smi discovery/refresh, store
  round-trip, every selection case, environment boundary).
- **Phase 5 — Full gate + commit:** ruff clean, mypy clean (53 files),
  **842 passed** (800 M2.1 baseline + 42 new, 186 s), contract drift
  check OK (no API change — device domain is not API-exposed yet).
  Commit + ledger hash follow-up.

**Deliverables:**
- `analysis/pyproject.toml` + `analysis/uv.lock` + `analysis/.python-version`
  — separately locked inference-only environment (spec 4.1).
- `analysis/qualify.py` — qualification script, explicit-interpreter entry
  point (spec 4.1.7, 4.2.4–4.2.8, 4.3).
- `docs/evidence/m2.2-analysis-environment.md`,
  `docs/evidence/m2.2-qualification.md` (git-ignored local reports).
- `src/basseparate/domain/device.py`, `src/basseparate/devices.py`,
  `domain/__init__.py` exports.
- `tests/unit/test_device.py`, `tests/unit/test_devices.py`.

**Deferred (out of M2.2 scope):** writing qualification results into the
runtime store is not wired to a CLI/API yet — `record_qualification()` is
the tested integration point; the endpoint/CLI belongs to M2.17.
`htdemucs` checkpoint used the Hugging Face cache (dev qualification);
the bundled hash-pinned baseline is M2.3.

### M2.3 — Pin and provision the bundled Demucs baseline (complete)

Spec: `projectPlans/milestone2.md` §5; plan: `projectPlans/m2.3-plan.md`.
Scope: hash-pinned `htdemucs_ft` preset (4 components, identity ensemble),
checked-in manifest registry, bundle verification
(`bundled_available`/`bundled_missing`/`bundled_corrupt`), local
bundle import (strict file set, executable reject, verify-after-copy),
provenance store, offline load/inference qualification. No API (M2.17),
no adapter (M2.5). Main env stays torch/demucs-free.

**Resolved facts (2026-10-10, verified, none invented):** preset yaml 149
bytes sha256 `69470b8c…16346` (demucs 4.1.0 `remote/htdemucs_ft.yaml`,
byte-identical to upstream main); four 84,141,271-byte checkpoints with
full SHA-256 (embedded 8-hex filename checksums all match); total
336,565,233 bytes; local-repo layout = yaml + `<sig>-<checksum>.th` files;
`get_model("htdemucs_ft", repo=Path)` loads with no network (HF hub path
bypassed); offline smoke: load 1.38 s, 5 s CPU inference 7.95 s, output
(1, 4, 2, 110250) finite. License: code MIT (demucs LICENSE, Meta);
**no explicit weight license statement found** (README/LICENSE/HF card,
checked 2026-10-10) — provenance recorded, weight terms not assumed (§5.6).

- **Phase 1 — Plan + ledger:** done.
- **Phase 2 — Provisioning (§5.2.4):** done. Artifacts in the ignored
  `models/htdemucs_ft/` workspace dir; hashes computed and cross-checked
  against the embedded checksums (facts above; plan carries the table).
- **Phase 3 — Manifest registry (§5.1):** done.
  `src/basseparate/models/registry.py` — `ArtifactSpec` + `ModelManifest`
  frozen records, checked-in `REGISTRY` with real hashes/sizes/URLs/labels/
  notices, import-time invariants (unique plain-file names, no traversal,
  64-hex hashes, positive sizes, https provenance, label sanity).
- **Phase 4 — Bundle service (§5.3–5.5):** done.
  `src/basseparate/models/bundle.py` — `verify_bundle` three states
  (missing takes precedence; report lists both), `import_local_bundle`
  (strict manifest file set, executable-extension reject, copy,
  verify-after-copy, cleanup on failure), `ProvenanceStore` (JSON, data
  dir, version 1, `record_provisioning`/`record_qualification`),
  `default_bundle_root`/`default_bundle_dir` (bundle-relative prefix
  resolved against the repo root in dev); `diagnostics.py` gains a
  `model-baseline` check (optional — never blocks `doctor` before M2.5).
  `doctor` on this machine reports `htdemucs_ft: bundled_available`.
- **Phase 5 — Offline qualification (§5.3.6):** done.
  `analysis/qualify_bundled.py` sets HF-offline env vars before import,
  re-verifies artifact hashes against the checked-in registry (loaded by
  file path — single source of truth), loads from the explicit repo path,
  runs a 5 s inference. **PASS on cpu (load 1.567 s, inference 8.864 s)
  and cuda:1 (load 1.384 s, inference 3.151 s)**; output (1, 4, 2, 110250)
  finite; exit 0. Missing-bundle negative path fails cleanly (exit 1).
  Evidence: `docs/evidence/m2.3-bundled-qualification.md` (git-ignored).
- **Phase 6 — Tests + full gate + commit:** done. ruff clean, mypy clean
  (56 files), **884 passed** (842 M2.2 baseline + 42 new, 186 s),
  contract drift check OK (no API change — the model registry is not
  API-exposed yet). `M2.3: ...` commit + ledger hash follow-up.

**Deliverables:**
- `src/basseparate/models/registry.py` — checked-in hash-pinned manifest
  for `htdemucs_ft` (5 artifacts, 336,565,233 bytes, full SHA-256 set,
  upstream provenance URLs, input/output requirements, license notice).
- `src/basseparate/models/bundle.py` — `verify_bundle` (three states),
  `import_local_bundle` (strict file set, executable reject,
  verify-after-copy), `ProvenanceStore`, default dir resolution.
- `src/basseparate/models/__init__.py` — package exports.
- `src/basseparate/diagnostics.py` — `model-baseline` doctor check.
- `analysis/qualify_bundled.py` — offline bundled qualification script.
- `tests/unit/test_models_registry.py`,
  `tests/unit/test_models_bundle.py`, diagnostics tests (+2).
- `projectPlans/m2.3-plan.md`; evidence in
  `docs/evidence/m2.3-bundled-qualification.md` (git-ignored).

**Deferred (out of M2.3 scope):** CLI/API surface for bundle status and
import (M2.17); release packaging script (Milestone 7); the inference
adapter that will consume `default_bundle_dir` with
`get_model("htdemucs_ft", repo=...)` (M2.5). The `models/htdemucs_ft`
workspace copy is local-only (git-ignored) — reprovision with the URLs in
the registry if it is ever lost.

### M2.4 — Prepare separation input consistently (complete — `ebd58aa`)

Spec: `projectPlans/milestone2.md` §6; plan: `projectPlans/m2.4-plan.md`.
Scope: reference-mix resolution (stereo as-is, mono duplicated for model
input, multichannel via the explicit M1.7 stereo downmix), single whole-file
resample to the model rate (44.1 kHz from the M2.3 registry), hash-identified
prepared-input asset identity, source-time mapping (no trim), versioned
global normalization profile (streaming float64 stats, epsilon-capped
scale, anti-phase full-channel fallback, exact-silence shortcut). No API
(M2.17), no inference (M2.5). Main env stays torch/demucs-free (numpy +
the M1.7 ffmpeg driver are reused).

**Resolved facts (2026-10-10):** `resample_playback` (SWR profile v1,
endpoint_difference_frames), `downmix_monitoring` + `resolve_downmix`
(standard_5_1 / manual), `validate_pcm` (chunked hash/finiteness/max) all
exist from M1.5/M1.7 and are reused; demucs normalizes per window
(mean/std, 1e-5 epsilon) — the M2.4 global profile gives M2.5 a
whole-track reference scale (kept separate from demucs' internal step,
§6.3 rule 1).

- **Phase 1 — Plan + ledger:** done.
- **Phase 2 — Domain:** done — `src/basseparate/domain/preparation.py` —
  `DownmixSpec`, `ReferenceMixPlan`, `PreparedInput`, `ChannelStats`,
  `NormalizationProfile` (frozen pydantic, validators; reuses the M1
  `TimeMapping` for the source-time mapping — no new time type).
  Exported from `domain/__init__.py`.
- **Phase 3 — Service:** done — `src/basseparate/media/preparation.py` —
  `transform_identity_hash` (canonical JSON recipe, pure),
  `compute_normalization_profile` (streaming float64; modes
  normal / full_channel_fallback / exact_silence; EPSILON 1e-4,
  FALLBACK_RATIO 1e-2), `prepare_separation_input` (hash pre-check →
  optional M1.7 downmix → SWR v1 resample → numpy mono duplication →
  validate_pcm → endpoint tolerance ±2 frames → profile; staging cleanup
  on failure).
- **Phase 4 — Tests:** done — 41 unit
  (`tests/unit/test_preparation.py`: domain validators, identity purity,
  profile math on synthetic f32le: silence/DC/anti-phase/near-silence
  epsilon cap/float64 accuracy/determinism/malformed input) + 11
  integration (`tests/integration/test_preparation.py`, real ffmpeg:
  stereo 48k→44.1k, mono duplication byte-exact, 5.1 downmix, manual
  L/R extraction, two-run byte-identical determinism, hash mismatch,
  kind/channel mismatch, intermediate cleanup). Ruff clean, mypy clean
  (58 files), contract drift check OK.
- **Phase 5 — Commit:** `M2.4: ...` + ledger hash follow-up.
  Gates: **936 passed** (884 + 52 new), 218.75 s; the 2 suite warnings
  are pre-existing (fastapi/starlette deprecation; the known
  `test_publisher_failure_fails_job` subprocess-GC unraisable — that
  test passes).

### M2.5 — Implement bounded Demucs separation (complete — `18ace92`)

Spec: `projectPlans/milestone2.md` §7; plan: `projectPlans/m2.5-plan.md`.
Scope: versioned windowed inference adapter (120 s outer windows, 8 s
overlap, same global normalization profile for every window, per-window
seed, output-scale restore, complementary raised-cosine blend,
incremental staged writes, bounded memory), short-input upstream
reference runner, §7.3 comparison gate. No API (M2.17), no
validation/publication (M2.6). Main env stays torch/demucs-free:
torch-free windowing math lives in the main env (file-path loaded by
the worker, M2.3 registry pattern); the worker is an analysis-env
script entry point.

**Resolved facts (2026-10-10, pinned demucs 4.1.0 `apply.py`):**
`apply_model(..., segment=, callback=, callback_arg=)` — `segment`
overrides the model segment (memory-recovery lever); HTDemucs default
segment 10 s, the checked-in yaml does not override it → 7.5 s initial
internal segment is within the validated maximum; `shifts` draws
`random.randint(0, 0.5×rate)` from **Python `random`** per
(model-in-bag, shift) → reproducibility hook `random.seed(seed +
window_index)`; `split=True` internal handling (triangular weights,
weighted accumulate+divide) is reused inside each outer window;
`callback(dict)` fires per internal segment with
`model_idx_in_bag`/`shift_idx`/`segment_offset`/`models` and a raised
exception cancels queued chunks (`pool.shutdown(cancel_futures=True)`)
— the pinned progress/cancellation facility; `htdemucs_ft` output
`(1, 4, 2, L)`, labels = model `sources` cross-checked against the
registry.

- **Phase 1 — Plan + ledger:** done.
- **Phase 2 — Main env:** done. `src/basseparate/media/windowing.py`
  (torch-free numpy: `window_schedule`, `outer_window_weight`
  complementary raised cosine, `pre_scale`/`restore_scale`,
  `accumulate_overlap`, `finalize_region`) + `tests/unit/test_windowing.py`
  (24 tests). Gates re-run after the zip B905 fix: ruff clean, mypy clean
  (59 files), contract OK.
- **Phase 3 — Worker:** done. `analysis/separate.py` (offline model load,
  bundle hash verification, exact-silence shortcut without model load,
  window loop with per-window seed + global profile, (batch, channels,
  length) orientation, float64 overlap-add + incremental finalize,
  JSON-lines progress, cancel file checked between windows **and inside
  the per-segment callback**, OOM retry ladder 7.5→5→3 s with distinct
  staged dirs, run record). Smoke 2 s cuda:1: 8 units, complete, 4 stems,
  frames exact. `plan_units` now bounds the per-window count with
  `length + max_shift` (the shifts branch splits a view longer than the
  window) so the reported fraction never exceeds 1.0 (was 1.029 on the
  8 min run).
- **Phase 4 — Reference + gate:** `analysis/reference_separate.py`
  (one whole-track `apply_model`, same seed/shifts/split/overlap/segment
  + global pre-scale; `--offset-seconds`/`--seconds` for per-window
  slices; TF32 pinned off) and `analysis/compare_adapter.py` (two modes:
  `--reference` single = the literal §7.3 short-input gate; `--refs`
  windows = per-window upstream baseline + exact weighted-combination
  check of the blend bands + identity regions + boundary/continuity).
  **Upstream `apply_model` is not length-invariant:** shift offsets
  (`random.randint`, `apply.py:245`) interleave with one
  `random.randrange` per internal segment (`transformer.py:680`,
  `_get_pos_embedding`; the draw is always 0 but the state is still
  consumed), so the offsets depend on total track length — 120 s vs
  480 s draws (same seed, same content): `[11475, 12935, 8799, 19278,
  10246, 21840, 17690, 7762]` vs `[11475, 7830, 5849, 13893, ...]`.
  The per-window seeding (`run_seed + window_index`) is therefore the
  correct policy; the whole-track reference is only a valid baseline
  for single-window tracks. **Stem layout:** interleaved f32le
  `(frames, 2)` — the prepared-input PCM convention; window blocks are
  time-contiguous, so the incremental staged writes form one valid
  whole-track stream (`separate._stem_block_bytes`, shared with the
  reference runner).
- **Phase 5 — Evidence + close (2026-10-11):** done. The comparison
  gate's apparent 8 min window-0 divergence ("differs on
  [56 s, 112 s), max 0.285") was root-caused to a **file-layout
  mismatch in the comparison tooling**, not adapter numerics: the
  worker serialized each window's `(channels, frames)` block planar
  while the reference wrote a whole-track planar block, and the gate
  read the first `2·L` raw floats as `(2, L)` — the first differing
  float (`4,939,200`) is exactly window 0's second channel block
  ("56 s" on the row-pair axis; `max 0.285318`). Byte-level checks with
  correct extraction: adapter window 0 **bit-exact** vs the standalone
  TF32-off reference (both channels, all stems); an offline numpy
  replay of demucs' exact accumulation from dumped per-segment submodel
  outputs reproduced the staged file bit-for-bit; 8 min runs were
  SHA-stable across re-runs. Writers now emit interleaved f32le;
  references regenerated with the precision pin (measured torch
  2.9.1+cu128 defaults: matmul TF32 off, cudnn TF32 **on**; both
  pinned off — spec float32, removes process-dependent cuDNN
  algorithm/workspace selection). Final gates: 30 s single-mode
  **bit-exact** (max_abs_diff 0.0, scale 1.0, lag 0); windows-mode
  8 min vs 5 pinned per-window refs — identity **0.0**, blend
  **2.98e-8** (< 1e-6; one f32 ulp), scale 1.0, lag 0, boundary ratio
  4.2e-5 (< 3.0), bass continuity `[0.902, 1.026, 1.051, 0.928]`
  (0.8–1.25). `compare_adapter.py` boundary metric fixed for a
  bit-exact interior (tolerance floor, float division). Cancellation:
  cancel file at 20 s of the 8 min input → exit 2, staged removed,
  run-record `cancelled`. RSS (`/usr/bin/time -v`): 2 s **2,601,500
  KB**, 8 min **4,418,864 KB** (bounded by window size, not track
  length). Full gates green: pytest 960 passed, ruff clean, mypy clean
  (59 files), contract OK. Files: `projectPlans/m2.5-plan.md`,
  `src/basseparate/media/windowing.py`, `tests/unit/test_windowing.py`,
  `analysis/separate.py`, `analysis/reference_separate.py`,
  `analysis/compare_adapter.py`. Evidence:
  `docs/evidence/m2.5-bounded-separation.md`. Commit `M2.5: ...` +
  ledger hash follow-up.

### M2.6 — Validate and publish stems (complete — `a088363`)

Spec: `projectPlans/milestone2.md` §8; plan: `projectPlans/m2.6-plan.md`.
Scope: turn a completed staged M2.5 run (44.1 kHz f32le stems + run
record) into published **project-rate validated stem assets + an
immutable result set**, with the Bass + Others residual, reconstruction
diagnostics, the standard confidence object, atomic result publication
and representation queueing. No API/job wiring (M2.17), no cache lookup
(M2.7), no frontend (M2.8).

**Resolved facts (codebase map, 2026-10-11):** `domain/separation.py`
already models `SeparationRun`/`SeparationResultSet`/`StemRecord`
(validators: completed ⇒ result_set_id, valid ⇒ stems+frames, unique
roles); `Confidence` has the strict `unavailable ⇔ value is None` rule
(§8.6 standard object); assets are content-addressed
(`data/assets/<sha256>.pcm`) published with the M1 `publish_source`
transaction pattern; `SeparationRepository` (schema v7, JSON-blob rows)
has create/get/list only — no run-status update and no multi-record
transaction; `media/decode.py::validate_pcm` + `check_frame_alignment`
and `media/derived.py::resample_playback` (pinned SWR v1, endpoint
deltas) are the reusable primitives; waveform caches are keyed by asset
hash (`build_waveform_cache`), but the job/publisher path is
canonical-only; playback-rate jobs are on-demand in M1
(`api/playback_routes.py`), not eagerly queued; reference mix comes from
the M2.4 `ReferenceMixPlan` at project rate; `PreparedInput` is not yet
persisted as an asset (deferred decision).

**Design decisions:** `StemRole.OTHERS` added as a publication-only role
for the §8.4 residual (distinct from the model's `other`); the four
model stems are always published and retained (§8.5);
`SeparationRepository.publish_result_set` commits hash-idempotent
assets + `project_assets` stem linkage + result set + stems + run
completion in one `BEGIN IMMEDIATE` (rollback leaves nothing; no base
representation rows — the asset `AudioMetadata` carries
rate/channels/frames); new
`media/publication.py` service (restore → validate → diagnostics →
residual → publish) with bounded chunks and the documented endpoint
policy (±2 frames, exact canonical frame count); waveform queueing
generalized to arbitrary source assets; playback representations stay
on-demand; separation staging lives under
`runtime/separation/<run_id>/attempt-N/` (not wiped job staging).

- **Phase 1 — Plan + ledger:** done (`projectPlans/m2.6-plan.md`).
- **Phase 2 — Domain + repository:** done. `StemRole.OTHERS`
  (publication-only residual role, §8.4) with the result-set coupling
  validator (`others` ⇔ `bass_residual_asset_id`); repository
  `SeparationRepository.publish_result_set` — one `BEGIN IMMEDIATE`
  transaction (hash-idempotent assets + `project_assets` stem linkage +
  result set + stems + run completion), rejecting non-valid sets,
  identity mismatches and re-publication; 6 new tests (unit + integration
  incl. rollback and re-publish rejection). Gates so far: ruff clean,
  mypy clean (59 files), 784 unit + 182 integration tests green
  (966 total).
- **Phase 3 — Media services** (restore/validate/reconstruction/
  residual): done. `src/basseparate/media/publication.py`:
  `restore_stem_project_representation` (pinned SWR v1; byte-exact
  identity fast path; mono collapse `(L+R)/2` float64→float32; endpoint
  policy ±2 frames resampler rounding, final frame count must equal the
  project frame count exactly — never a blind trim), `validate_stems`
  (§8.2 checklist: roles complete/unique, frames, alignment, finite,
  hash, `max_amplitude`), `compute_reconstruction_error` (bounded
  float64 chunks → rms/max), `derive_bass_residual` (float64→float32,
  verified within 4× worst-case float32 quantization). 24 unit + 5
  integration tests (no GPU).
- **Phase 4 — Publication + queueing:** done.
  `publish_separation_result` orchestration in `media/publication.py`
  (restore all model stems → residual when `bass_pair` → §8.2
  validation → diagnostics → move assets into the content-addressed
  store (hash-dedup) → `publish_result_set` → per-stem waveform queueing
  → staging cleanup on success only; on failure staged stems are kept
  and no partial records commit). `queue_stem_waveforms` per-asset
  variant (skips while a live WAVEFORM job targets the same asset);
  `jobs/publisher.py::_publish_waveform` + `app._waveform_parameters_for`
  resolve the job's `asset_id` parameter with canonical fallback, so M1
  jobs are unaffected. 4 new integration tests (end-to-end synthetic
  staged run, bass-pair residual, failure path, queueing dedup).
- **Phase 5 — Evidence + close:** done. Evidence:
  `docs/evidence/m2.6-stem-publication.md` (git-ignored). Final gates:
  ruff clean, mypy clean (60 files), 808 unit + 192 integration = 1000
  py tests green, `scripts/check_contract.py` OK. Committed as `M2.6:
  validate and publish stems`; hash recorded below.

**Implementation notes (Phase 2):** in `publish_result_set` the result
set row is inserted **before** the stems (the stems table has an FK to
`separation_result_sets`); pydantic `model_copy(update=...)` skips
validation/coercion, so tests must pass real `datetime` values for
timestamps (strings raise `AttributeError` in `model_dump_json`); no
base representation rows are created for stem assets — the asset
`AudioMetadata` carries rate/channels/frames and playback-rate
representations stay on-demand (M1 policy); any DB failure inside the
transaction rolls back everything (tested).
**Implementation notes (Phase 3/4):** the pinned SWR profile has a
start transient at float32 rounding level (zero-padded filter history,
~1e-6 relative on a DC signal) — the DC-based end-to-end tests assert
`< 1e-5`, not exactness; the residual verification tolerance is
`peak * 2**-22` (4× the worst-case 0.5-ulp quantization of a difference
bounded by the input peak); `queue_stem_waveforms` treats
queued/running/cancelling/completed WAVEFORM jobs as live (a failed or
cancelled build is retried); WAVEFORM jobs for stems carry
`parameters["asset_id"]` and the publisher/worker resolve it with a
canonical fallback, so M1 jobs are byte-identical in behavior; on
publication failure the `restored/` intermediates are removed but the
staged stems + run record are kept for diagnostics; assets are
moved into `data/assets/<hash>.pcm` **before** the DB transaction (a
failed transaction leaves dedup-able files, a retry reuses them).
**Files committed with M2.6:** `projectPlans/m2.6-plan.md`,
`src/basseparate/domain/separation.py`,
`src/basseparate/storage/repository.py`,
`src/basseparate/media/publication.py`,
`src/basseparate/jobs/publisher.py`, `src/basseparate/app.py`,
`tests/unit/test_separation.py`,
`tests/integration/test_separation_repository.py`,
`tests/unit/test_publication.py`,
`tests/integration/test_publication.py`, `docs/implementation-status.md`.

## M2.7 — Analysis caching and version retention (spec §9)

**Scope (per `projectPlans/m2.7-plan.md`):** deterministic cache key
per separation request (§9.1), cache lookup + coalescing primitives
(§9.2), effective-parameter keying after memory recovery (§9.3),
undoable active-result-set selection persisted with the project
(§9.4), and a 50 GiB configurable storage policy with pinning,
reclaimable-size report, and explicit cleanup (§9.5). No new API
routes (the existing command endpoint exposes the new op;
report/cleanup routes are M2.17), no scheduler wiring (M2.17), no
frontend (M2.8).

**Key design decisions:**

- **Cache key** (`media/separation_cache.py::compute_cache_key`):
  pure, versioned (`CACHE_KEY_VERSION = "v1"` prefix → payload-format
  changes are clean misses, not collisions), canonical
  `json.dumps(sort_keys=True)` → sha256. Covers §9.1 via: source +
  reference-mix hashes, downmix spec, manifest id + every artifact
  hash, engine/adapter versions, the **effective** parameter dict
  (falls back to requested — the M2.5 run record already carries the
  resampling/normalization/window/segment/shift/precision profiles
  there), seed, device **profile** (cpu vs cuda; `gpu_uuid` excluded
  by the float32 pin), output transform profile (rate + channels).
- **Persistence:** `cache_key: Sha256Hash | None` on `SeparationRun`
  + `SeparationResultSet` (defaulted); schema v8 adds the query
  columns + `(project_id, cache_key)` indexes.
  `publish_separation_result` gains an optional `cache_key` parameter
  (M2.17 computes it; the orchestrator stamps it).
- **Lookup (§9.2):** `find_valid_result_set` / `find_active_run`
  (queued/running only — cancelled/failed never match, §9.2.8) +
  `lookup_cached_result` service: asset existence **with exact
  expected byte size** (partial files are misses, §9.2.5), optional
  `verify_hashes` re-hash pass (§9.2.3). Coalescing (§9.2.6–7) is the
  M2.17 scheduler's composition of these primitives + M2.6's
  re-publication rejection + asset hash-dedup.
- **Active result set (§9.4):** the selection lives in
  `PracticeState.active_result_set_id` (existing M2.1 field; stem
  playback modes already require it — **not** `WorkingState`, an early
  `WorkingState` addition was reverted net-zero). New undoable op
  `set_active_result_set` (in the `ProjectCommandOp` union, **not** in
  `HISTORY_EXCLUDED_TYPES`); null clears the selection **and** reverts
  `playback_mode` to `ORIGINAL` when in a stem mode (PracticeState
  invariant); setting an id keeps the current mode.
  `apply_command` validates the set belongs to the project
  (`ResultSetNotFoundError` → new API 404 `RESULT_SET_NOT_FOUND`).
  Mechanism: `_history_snapshot` carries `practice_state` (pre-M2.7
  snapshots lack the key → restore keeps the current practice state);
  `_apply_op` returns `(markers, working_state, practice_state)`;
  `_write_state` writes the `practice_state` column; `CommandResult`
  gained a `practice_state` field. Result-set records are **never
  deleted**; eviction removes rebuildable bytes of inactive sets only
  under cache-limit pressure, leaving the immutable record (a set
  whose assets were reclaimed simply misses lookup → rerun rebuilds
  it).
- **Storage policy (§9.5):** new `cache_limit_bytes` config (default
  50 GiB); `compute_storage_report` counts model storage
  separately (never against the limit), pins source/canonical +
  active-result-set stems + edit-history-referenced assets (M2.8
  hook) + in-flight-job assets, and treats the newest result set per
  cache key as pinned (the lookup winner); `reclaim_storage` is
  **explicit** (§9.5.7: report first), LRU by result-set
  `created_at`, never touches pinned bytes. Edits are project rows,
  not assets — they cannot be reclaimed.

**Phases:**

- **Phase 1 — Plan + ledger:** done (`projectPlans/m2.7-plan.md`).
- **Phase 2 — Domain + schema + config:** done. `cache_key` on
  `SeparationRun`/`SeparationResultSet`; `SetActiveResultSetOp` in the
  `ProjectCommandOp` union; schema v8 (`cache_key` columns +
  `(project_id, cache_key)` indexes, `DATABASE_SCHEMA_VERSION = 8`,
  migration 7→8); `cache_limit_bytes` config (default 50 GiB,
  validated ≥ 1 GiB); `create_run`/`create_result_set`/
  `publish_result_set` persist the key + run/result-set key-mismatch
  guard in `publish_result_set`. Tests: `test_storage_db.py`,
  `test_migration_m2.py` (+ `test_v7_to_v8_adds_cache_key_columns` +
  `_build_v7_db`), `test_config.py` (+3), `test_commands.py` (+2),
  `test_separation.py` (+2), `test_repository_commands.py` (version 8).
- **Phase 3 — Cache key + lookup:** done.
  `src/basseparate/media/separation_cache.py`: `compute_cache_key`
  (pure, versioned `CACHE_KEY_VERSION = "v1"`, canonical
  `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True)`
  → sha256; effective-params rule §9.3; device **profile** only,
  `gpu_uuid` excluded) + `lookup_cached_result` (newest valid set per
  key → every stem asset + bass residual must exist with **exact**
  expected byte size `frames × channels × 4`; partial files are
  misses §9.2.5; optional `verify_hashes` re-hash §9.2.3; the fast
  path trusts the content-addressed name + size). Repository:
  `find_valid_result_set` (newest valid by `created_at`) +
  `find_active_run` (queued/running only, §9.2.8).
  `publish_separation_result` gained the optional `cache_key` param
  (stamped on run + result set). Tests:
  `tests/unit/test_separation_cache.py` (25: determinism,
  order-independence, asset-id exclusion, 17 per-input changes,
  effective-params precedence, identical effective/requested share a
  key, GPU identity excluded, version prefix, non-serializable
  rejection); `tests/integration/test_cache_lookup.py` (14:
  hit/with-residual, miss on absent/unknown-key/missing/partial/
  residual-missing/invalid-set, fast-path vs `verify_hashes`
  corruption, newest-wins, live-states-only, coalescing
  composition, run/set key-mismatch guard).
  `test_publication.py` (+1: `test_publish_stamps_cache_key`).
- **Phase 4 — Active result set command:** done. Repository
  (`ResultSetNotFoundError` at ~line 243; 3-tuple `_apply_op` with
  `set_active_result_set` branch incl. clear-reverts-stem-mode;
  `_history_snapshot` + `_write_state` carry `practice_state`;
  `apply_command` validation; `_move_history` backward-compat
  restore); `CommandResult.practice_state`; API (`api/errors.py`
  `ResultSetNotFoundError` 404, `command_routes.py` mapping). Tests:
  `tests/integration/test_active_result_set.py` (6 tests: apply,
  unknown id 404, foreign project 404, undo/redo,
  clear-reverts-stem-mode, persistence across reopen).
- **Phase 5 — Storage policy (§9.5):** done.
  `src/basseparate/media/storage_report.py`:
  `compute_storage_report` (frozen `StorageReport`: model bytes counted
  separately and never against the limit §9.5.2; project bytes =
  source/canonical/derived + their waveform caches; separation bytes =
  stem assets deduped by content hash; pins = active set §9.5.3, newest
  set per cache key (lookup winner), caller pin hook for
  edit-history/in-flight assets §9.5.4/6) + `reclaim_storage`
  (explicit §9.5.7 — report first; LRU by `created_at`; deletes stem
  files + waveform caches only when no remaining result set references
  the hash/asset — dedup-safe via a shrinking `live` set; **records are
  never deleted**, an evicted set simply misses lookup and a rerun
  rebuilds it; edits are project rows and survive). `ProjectRepository`
  gained `list_project_assets` (project_assets × assets join).
  `tests/integration/test_storage_report.py` (10: model counted
  separately + untouched by reclaim, project/separation split, pinning
  rules, pin hook, no-op under limit, LRU eviction until under limit,
  pinned never touched, dedup shared-asset survival + final removal,
  waveform-cache removal, edits survive).
- **Phase 6 — Evidence + close:** done. Full gate green; evidence doc
  `docs/evidence/m2.7-analysis-caching.md` (git-ignored); contracts
  regenerated for the new `set_active_result_set` op.

**Verification (2026-10-13, full gate at close):**
`pytest tests/unit -q` → 840 passed (baseline 808);
`pytest tests/integration -q` → 224 passed (baseline 192);
`pnpm --dir frontend test` → 307/307; `pnpm format:check` clean;
`ruff check src/ tests/` clean; `mypy src/basseparate/` clean (62
files); `scripts/check_contract.py` OK (openapi.json + frontend
schema.ts regenerated).

**Committed:** `ac12159` — M2.7 (analysis caching and version
retention). 26 files: plan, ledger, domain (`commands`,
`separation`), config, API (`command_routes`, `errors`),
`media/publication.py`, new `media/separation_cache.py` +
`media/storage_report.py`, storage (`db` v8, `repository`),
contracts (`openapi.json`, `frontend/src/api/schema.ts`), and the test
additions (`test_separation_cache` new, `test_cache_lookup` new,
`test_active_result_set` new, `test_storage_report` new,
`test_publication` +1, plus Phase-2 test files).

## M2.8 — Aligned tracks and the stem mixer (spec §10)

**Scope (per `projectPlans/m2.8-plan.md`):** turn the active result
set into a usable practice surface — the original as a reference track
plus the active stem group (bass pair or four stems) as aligned
waveforms, a per-track mixer (mute / solo / gain / pan / visibility /
color / height), a shared-timeline multi-source transport, and
monitoring safety (peak meters + default-on limiter). The mixer is
**monitoring-only** (§10.3.8): no write path touches stem assets and
the limiter stays out of raw-stem exports. No separation runs, no
cache changes (M2.7), no time-stretch (M2.9), no loops UI.

**Key design decisions (see plan for full detail):**

- **Domain:** `TrackSettings.color` (hex `^#[0-9a-fA-F]{6}$`, default
  `#8fa3bf`; the domain is palette-agnostic — the frontend applies the
  role palette as the displayed initial value); `MAX_GAIN` 2.0 →
  `10 ** (12.0 / 20.0)` (+12 dB, §10.3.2) with the 0.0 floor kept
  (mute is exact silence, §10.3.3); `monitoring_limiter` default
  `True` (§10.6.3). No schema migration — `tracks` lives in the
  record JSON (pydantic defaults fill old rows).
- **Commands:** four new undoable ops (none in
  `HISTORY_EXCLUDED_TYPES`): `set_track_settings` (patch semantics on
  `practice_state.tracks[stem_role]`, at least one non-`None` field),
  `set_playback_mode` (pre-validation: a stem mode without an active
  result set → new `PlaybackModeRequiresResultSetError` → 409
  `PLAYBACK_MODE_REQUIRES_RESULT_SET`), `set_master_gain`,
  `set_monitoring_limiter`. Undo/redo come free from M1.15 history
  snapshots (`practice_state` included since M2.7).
- **Route:** read-only
  `GET /api/v1/projects/{id}/result-sets/{result_set_id}` →
  `ResultSetDetail` (set + stems + run provenance; 404 on missing or
  foreign). M2.17 keeps the storage report/cleanup routes.
- **Worklet:** ONE processor consumes all active sources — per-source
  `ConsumptionState`, one shared cursor (drift impossible); per-quantum
  mix: solo eligibility (`!mute && (!anySolo || solo)` — mute
  overrides solo; hidden ≠ muted), 5 ms linear ramp on parameter
  change, stereo 3 dB/side balance vs mono equal-power pan, per-track +
  master peaks reported with `consumed`; any-source underrun pauses
  the whole group; the legacy 1-source `init` path is preserved.
- **Transport:** N `SourceSpec`s; prepare validates `sampleRate` and
  `frameCount` against the project rate/duration (hard error, no
  resample); N per-asset fetch queues behind the one worker;
  `LIMITER_DELAY_SECONDS = 0.010` added to reported latency when the
  limiter is on; limiter = WebAudio `DynamicsCompressorNode` on the
  monitoring path only (threshold −1 dBFS, §10.6.4).
- **UI:** track stack (original + active group from `practice_state`)
  over the shared viewport, per-track lane height + amplitude zoom,
  labels + provenance, mixer strip (−60…+12 dB, pan, M/S, visibility,
  color, height), mode selector (Original / Bass pair / Four stems;
  the no-set 409 becomes a selection notice), monitoring panel
  (peaks + limiter toggle).
- **Frontend state:** `practice_state` was dropped in
  `toCommandResult()` / `getProjectSnapshot()` — mapped; the hook owns
  it; mixer ops are immediate sends (never debounced); new
  `api/result-sets.ts` client.

**Phases:**

- **Phase 1 — Plan + ledger:** done (`projectPlans/m2.8-plan.md`).
- **Phase 2 — Backend: domain + ops + route:** done.
  `domain/practice.py`: `TrackSettings.color` (hex pattern, default
  `#8fa3bf`), `MAX_GAIN = 10 ** (12.0 / 20.0)` (+12 dB),
  `monitoring_limiter` default `True` (no migration — tracks live in
  the record JSON). `domain/commands.py`: four undoable ops
  (`set_track_settings` patch semantics + ≥1 field + `StemRole` check,
  `set_playback_mode`, `set_master_gain`, `set_monitoring_limiter`);
  none in `HISTORY_EXCLUDED_TYPES`. `storage/repository.py`: the four
  `_apply_op` handlers; `set_playback_mode` pre-validation in
  `apply_command` (stem mode without active set → new
  `PlaybackModeRequiresResultSetError`, in the rollback tuple);
  `SeparationRepository.get_result_set_detail` (one connection:
  project-owned set + run + stems, `None` on missing/foreign).
  `api/errors.py` + `api/command_routes.py`: 409
  `PLAYBACK_MODE_REQUIRES_RESULT_SET` mapping. New
  `api/result_set_routes.py`: `GET
  /api/v1/projects/{id}/result-sets/{id}` → `ResultSetDetail` (404
  `RESULT_SET_NOT_FOUND` / `PROJECT_NOT_FOUND`); `app.state.
  separation_repository` wired in `app.py`. Tests:
  `test_practice.py` (cap +12 dB, color, limiter default),
  `test_commands.py` (9 op tests), new
  `tests/integration/test_mixer_commands.py` (12: patch/create,
  preserve, undo/redo, persistence, mode 409 + apply, legacy-JSON
  color default) and new
  `tests/integration/test_result_set_routes.py` (9: detail happy +
  404s + auth, 409 mapping, mixer op round-trips, empty-patch 422).
  Gates at Phase 2: 852 unit + 245 integration py green, ruff clean,
  mypy clean (63 files), contracts regenerated + `check_contract.py`
  OK, frontend 307/307.
- **Phase 3 — Frontend state:** done. `api/commands.ts`:
  `practiceState` mapped in `toCommandResult()` +
  `getProjectSnapshot()` (both were dropping it); `PracticeState` type
  exported. `projects/useProjectCommands.ts`: the hook owns
  `practiceState` (initial load, every command result, stale resync,
  reset on project switch). New `api/result-sets.ts`:
  `fetchResultSetDetail(projectId, resultSetId)` snake→camel +
  `ResultSetNotFoundError` on 404. New `projects/trackSettings.ts`:
  `ROLE_PALETTE` (displayed initial colors; domain stays
  palette-agnostic), `defaultSettingsFor(role)`,
  `effectiveTracks(practiceState, roles)` (stored entries win, missing
  roles get display defaults). Tests: new
  `tests/result-sets.test.ts` (4), new `tests/track-settings.test.ts`
  (5), `commands.test.ts` +2 (practice_state mapping both directions),
  `use-project-commands.test.ts` +1 (hook tracks practiceState from
  results). Gate at Phase 3: frontend 319/319 (307 + 12), prettier
  clean.
- **Phase 4 — Worklet mixing DSP:** done. `worklet-processor.js`:
  new `MixState` class — ONE audio-thread state machine consuming every
  active source in lockstep (one shared cursor: `take = min(block, min
  buffered, endpoint)` per quantum, so drift is impossible and a
  starving source pauses the whole group). Each source is a plain
  `ConsumptionState` (new `consumeInto(out, frames)` method added).
  Per quantum: per-sample coefficient tables (5 ms linear ramps for
  gain, balance, mute/solo envelope, master gain — transcendentals stay
  out of the sample loop), stereo 3 dB/side balance vs mono equal-power
  pan, per-track + master peaks reported with `consumed` (peaks ride
  the ~20 Hz anchor message; reset per quantum). Solo eligibility
  `!mute && (!anySolo || solo)` — mute wins; visibility never reaches
  the audio thread (hidden ≠ muted). `PcmProcessor` adapter: mixer path
  when `processorOptions.sources` is set (per-source `sabs`,
  per-source `seek` generations, `params`/`master` messages,
  `chunk-dropped` carries `source` index); legacy 1-source `init`
  path preserved. `worklet-processor.d.ts`: `MixState`/`MixStateOptions`/
  `SourceParamPatch`/`MixSourceSpec` + `consumeInto` + `ProcessResult.peaks`.
  Tests: `worklet-core.test.ts` +15 MixState cases (sum stereo+mono,
  cursor lockstep + underrun, flushing silence, 3 dB balance, mono pan,
  solo/mute semantics, 5 ms ramp, master gain, peaks+reset, pause/resume,
  seek, end, per-source shared rings + generations). Gate at Phase 4:
  frontend 334/334 (319 + 15), prettier clean.
- **Phase 5 — Multi-source transport:** done.
  `playback/transport.ts`: `LoadSourceOptions` now takes
  `sources: SourceSpec[]` (legacy `target` form still accepted,
  normalized); `normalizeSources` hard-validates every source's
  `sampleRate === projectRate` && `frameCount ===
  projectDurationFrames` (RangeError, no resample). The transport
  always uses the worklet mixer path: `processorOptions` carries
  `sources: [{channelCount}]` (plus per-source `sabs` in shared mode)
  — one ring per source, one shared cursor. `runFill` fetches the
  same frame range for every source per round and advances the shared
  `fetchedFrame` by the minimum written (sources can never drift);
  relayed `channels` messages carry the `source` index. New public
  API: `setSourceParams(index, patch)` → `params` message,
  `setMasterGain(linear)` → `master` message (remembered as
  `pendingMasterGain`, applied to a fresh graph on play).
  `TransportOptions` gains `limiter` (monitoring-only
  `DynamicsCompressorNode`, threshold −1 dBFS, inserted
  gain → limiter → destination; skipped when the context cannot
  create one) and `onPeaks` (per-quantum peaks from the anchor
  message). `LIMITER_DELAY_SECONDS = 0.010` is folded into
  `getAudiblePosition`'s audible-time mapping while the limiter is
  active (both the `getOutputTimestamp` and fallback branches).
  Seek/flush handshake unchanged: one generation for the whole mix;
  the flush-ack resets every ring's writer index at the shared base
  frame. `playback/fetch-source.ts`: `FetchSource` serves the whole
  mix — `fetchChunk`/`writeChunk`/`attachShared` take a source index
  (and `attachShared` takes the SAB array + channel counts); both
  `WorkerFetchSource` and `DirectFetchSource` keep N per-source
  queues/rings behind one generation. `playback/fetch-worker.ts`:
  one worker, N rings; `shared-init` carries the SAB array,
  `flush-ack` resets all rings, fetch jobs route by `source` index.
  `worklet-processor.js`: adapter guards — `channels` dispatches to
  the per-source `MixState.enqueueChannels` vs the legacy single
  `ConsumptionState.enqueueChannels`; `params`/`master` are no-ops on
  the legacy core. Tests: `transport.test.ts` updated (mixer
  `processorOptions` shape, plural `sabs`, `FakeFetchWorker` N-ring
  protocol, shared path consumes via `MixState`) + 8 new M2.8 cases
  (validation rate/duration/empty, two-source transfer init + per-
  source fetch routing + `source` index on relayed chunks, two-ring
  shared path + single flush handshake, params/master forwarding,
  pending master gain on fresh graph, anchor peaks surfaced, limiter
  graph + 10 ms latency fold, limiter skip). Gate at Phase 5:
  frontend 342/342 (334 + 8), tsc clean, prettier clean.
- **Phase 6 — UI: track stack + stem mixer:** done.
  `api/result_set_routes.py`: read-only `GET
  /api/v1/projects/{id}/result-sets` → `ResultSetSummary[]`
  (`id`, `created_at`, `validation_status`, `available_stem_roles`;
  oldest first via `list_result_sets_for_project`; 404 on foreign
  project, 401 unauth) — the selector needs the list to prompt
  selection. `tests/integration/test_result_set_routes.py` +
  `TestResultSetListRoute` (5). `api/result-sets.ts`:
  `fetchResultSets(projectId, signal?)` + `ResultSetSummary`.
  `playback/transport.ts`: live `setLimiter(enabled)` (rewires
  gain → [limiter] → destination on the live graph; always remembered
  for a fresh graph; `getAudiblePosition` already follows
  `limiterNode`) and a `contextRate` getter (sample rate of the live
  context, null before the graph). `waveform/WaveformEditor.tsx`:
  additive `registerView?: (source: ViewSource | null) => void` prop +
  `SharedView`/`ViewSource` types — the editor is 100 % unchanged
  otherwise (zero regression risk) and registers a stable getter
  (`{startFrame, fpp, widthCssPx} | null`) that lanes poll at display
  rate. New `src/tracks/` module: `db.ts` (dB math:
  `10^(dB/20)`, −60…+12 dB slider span, dBFS meter, balance label);
  `TrackLane.tsx` (RAF poll of the shared view, numeric-equality-gated
  `setState`; `useWaveform(projectId, assetId, viewport)`; two
  canvases — waveform layer redrawn on data/view/style change via the
  M1 painters, playhead layer redrawn on x movement; local copies of
  the editor's private source adapters; lane = channel 0; non-ready
  states show a text overlay; hidden = "Hidden (audio still plays)"
  — visibility never mutes); `MixerStrip.tsx` (M/S aria-pressed
  buttons, gain slider −60…+12 dB step 0.5 → linear, balance −1…+1,
  visibility checkbox, color input, height slider 0.25…2, peak meter
  dBFS; every control patches through `set_track_settings`);
  `ModeSelector.tsx` (three aria-pressed buttons + result-set
  `<select>` listing only `valid` sets + one-line notice);
  `MonitoringPanel.tsx` (master peak meter dBFS, master gain slider,
  limiter checkbox — state always visible); `TrackStack.tsx`
  (composes mode bar + one row per stem in canonical order
  `BASS_PAIR_ROLES = [bass, others]` /
  `FOUR_STEM_ROLES = [vocals, drums, bass, other]`; fetches the set
  list for the selector; the no-set prompt is a UI-side precondition
  check — stem mode without `active_result_set_id` → notice, no op
  sent, server 409 stays the backstop; provenance =
  `engineVersion · model <8-char manifest id>`; `LANE_BASE_HEIGHT`
  48 CSS px × `display_height`; settings from `effectiveTracks`).
  `App.tsx`: `ProjectView` owns the active-set detail fetch
  (`fetchResultSetDetail`, stem modes only), computes
  `stemSources: (SourceSpec & {role})[] | null` (mutually exclusive
  groups, §10.4.5), and sends the four ops (`set_playback_mode`,
  `set_active_result_set`, `set_track_settings`, `set_master_gain`,
  `set_monitoring_limiter`); holds `viewSource` (from
  `registerView`) + `peaks` (from the transport) state; renders
  `<TrackStack>` + the "Original" reference label above the editor.
  `PlaybackPanel`: new props `practiceState`, `stemSources`,
  `onPeaks`; `createAudioContext?: (sampleRate?)` — stem mode creates
  the AudioContext at the project rate (§10.5.1: stems are stored
  there, the transport never resamples), original mode keeps the M1
  device-rate context; `handlePlayPause` load path is dual (stem
  `loadSource({sources})` vs original `ensurePlaybackTarget`) and so
  is the context-loss recovery path; `targetRef` keeps the last
  resolved original target for mode-switch rebinds; mode-change
  effect → `pause()` + `rebind` (stems sync; original via
  `targetRef` or an on-demand resolution at the live context rate) +
  `sourceLoadedRef = false` (next play re-loads); `applyMix` =
  `setMasterGain` + `setLimiter` + per-index `setSourceParams`
  (called on every `practiceState`/`stemSources` change AND after a
  successful `play()` — the graph is where params take effect).
  `styles.css`: track stack, mode bar, mixer strip, meters, lane
  canvases, notice. Tests: new `tests/track-stack.test.tsx` (37:
  db helpers, ModeSelector buttons/sets/notice/onMode,
  MonitoringPanel meter/gain/limiter, MixerStrip M/S/gain/balance/
  visibility/color/peak, TrackStack canonical order per mode,
  provenance, color, height, hidden state, no-set notice, op
  callbacks, peak meters). Gate at Phase 6: 852 unit + 250
  integration py, ruff + mypy (63 files) clean, contracts in sync,
  frontend 379/379 (342 + 37), tsc clean, prettier clean.
- **Phase 7 — closeout:** done. Full gate re-run 2026-10-16: 852
  unit + 250 integration py green, ruff clean, mypy clean (63 files),
  contracts regenerate with no residual diff, frontend 379/379 +
  tsc clean + prettier clean. Evidence doc
  `docs/evidence/m2.8-aligned-tracks-mixer.md` (git-ignored). e2e
  `app.spec.ts` not runnable in this environment (pre-existing harness
  bug: it spawns the Python server via `process.execPath`; only the
  Firefox Playwright browser is installed) — the original-only flow is
  unchanged by construction (`WaveformEditor` 100 % untouched, M1
  original playback path preserved). Single M2.8 commit (includes
  `projectPlans/m2.8-plan.md`) + ledger-hash follow-up.

## M2.9 — Time-stretch engine (spec §11)

**Scope (per `projectPlans/m2.9-plan.md`):** pitch-preserving
playback speed (0.25×–2.0×) via Signalsmith's C++ core through a
project-owned WASM wrapper inside the existing AudioWorklet. The
engine controls source-frame consumption (variable demand); all
playback — including 1× — routes through the stretcher in M2.9.
Monitoring-only: no source/annotation writes, no pitch shift (0
semitones), no formant. The app launches with no compiler present
(artifacts built once in a pinned environment, bundled in the repo).

**Key design decisions (see plan for full detail):**

- **Build:** gitignored `third_party/emsdk` (official workflow, pinned
  release) + `third_party/signalsmith-stretch` (pinned commit);
  committed `frontend/src/playback/stretch/` (wrapper `stretch_wrapper.cpp`,
  `build.mjs`, `dist/` scalar + SIMD artifacts, `BUILD.md` manifest
  with SDK release + commit + SHA-256 hashes, `NOTICES-signalsmith.md`
  preserving the MIT notices). No WASM threads; SIMD selected only
  after capability detection.
- **Contract (§11.4):** create/configure, input + output latency
  reports, process (in/out frame counts), set rate, reset, flush
  tail, destroy. Pre-allocated processing buffers (fixed max block);
  the WASM heap never grows from the audio callback.
- **Engine profile:** Signalsmith default quality, 0 semitones, no
  formant; measured in/out latency + audio-thread cost recorded.
- **Worklet:** mix (per-stem → stereo sum) → stretcher → master gain;
  `MixState`'s shared-cursor `take` becomes the stretcher's demand
  (fractional accumulator inside the wrapper); rate transitions
  smoothed over ≈ 50 ms (wrapper owns the transition state); `anchor`
  keeps reporting consumed source frames. The no-stretch path is not
  preserved (the 1× bypass is M2.10 §12.4).
- **Transport:** fill lookahead scaled by speed (source frames at
  `s × rate`/s); minimal bounded position-segment list for
  `getAudiblePosition` across rate changes (full three-domain ledger
  is M2.10); `setRate(speed)` (post `rate`, remembered for a fresh
  graph); engine-profile latencies folded into the audible-time
  mapping.
- **Domain:** `SetPlaybackSpeedOp {speed}` (undoable, 0.25…2.0,
  422 on violation) writing the existing
  `practice_state.playback_speed`.
- **UI:** speed control in the PlaybackPanel — slider 0.25…2.0 step
  0.01, numeric entry, presets (0.25/0.5/0.75/1.0/1.25/1.5/2.0), 1×
  reset; invalid input clamped + current value preserved; slider
  gestures coalesced into one undoable op.

**Phases:**

- **Phase 1 — Plan + ledger:** done (`projectPlans/m2.9-plan.md`).
  Environment facts verified 2026-10-16: network to
  github.com/emscripten.org OK, 313 GB free on `/home`, git 2.55.0,
  curl/wget present; no Emscripten on PATH (installed in Phase 2).
  `playback_speed` already exists in the domain (0.25…2.0, default
  1.0) — only the op, engine, integration, and UI are missing.
- **Phase 2 — Environment:** done (2026-10-16). `.gitignore` +
  `third_party/`; `third_party/emsdk` = `emscripten-core/emsdk` clone,
  `install 4.0.23` + `activate 4.0.23` (emcc 4.0.23 verified);
  `third_party/signalsmith-stretch` pinned at
  `a670068d9aeb64913331d5cc29337b19a457a7df`;
  `third_party/signalsmith-linear` pinned at tag `0.6.4` /
  `de55e6a50ffcf6f8f43f649692d94691c7025151`. API study:
  `SignalsmithStretch<float>` is header-only; **rate is inferred from
  the `inputSamples/outputSamples` ratio in `process()`** (the wrapper
  owns `setRate` and computes the input demand — §11.1);
  `presetDefault(2, rate, false)` is the §11.5 config;
  `inputLatency()`/`outputLatency()` report the profile latencies
  (2880/2880 @48k, 2646/2646 @44.1k); fixed-seed ctor makes output
  deterministic.
- **Phase 3 — WASM wrapper + build:** done (2026-10-16).
  `frontend/src/playback/stretch/`: `stretch_wrapper.cpp` (single
  global engine, fixed seed `0x5EED5EEDL`, `presetDefault(2, rate,
  false)`; C ABI; one contiguous I/O pool `[inL|inR|outL|outR]` with
  the **input regions sized for a full 2× priming buffer**
  (8640 @48k) and output regions maxFrames; `stretch_pool_offset` +
  `stretch_pool_input_frames` report the layout to JS), `build.mjs`
  (em++ -O3 -ffast-math -fno-exceptions -fno-rtti, MODULARIZE,
  ENVIRONMENT=web,worker,shell, INITIAL_MEMORY=2mb,
  ALLOW_MEMORY_GROWTH=0, STRICT, no threads; scalar + SIMD
  `-msimd128`), `dist/` artifacts (committed), `BUILD.md` manifest
  (regenerated every build; hashes in older checkpoints are stale),
  `NOTICES-signalsmith.md`. The emscripten glue in `dist/*.js` is a
  byproduct for debugging only — the app instantiates the `.wasm`
  directly (`WebAssembly.Module`/`Instance`, sync).
- **Phase 4 — Host API + engine profile + tests:** done
  (2026-10-16). `stretch-host.ts`: `instantiateStretch()` (direct
  sync instantiation, import stubs `{a:{a,b,c}}`, start export `e`,
  export validation), `simdSupported()` (`i8x16.const` probe),
  `StretchEngine` (configure/latencies/inputDemand/process/setRate/
  effectiveRate/reset/flushTail/**seekLength/outputSeek** +
  `inL/inR/outL/outR` views from the pool offset). `stretch-profile.ts`
  (the §11.5 config + `measureLatencies`). `tests/stretch-host.test.ts`
  — 12 tests against the real artifacts (latencies 48k/44.1k, impulse
  alignment, 2×/0.5× consumption ratios, immediate output after
  priming, determinism, scalar==SIMD (maxDiff 0), re-seek, tail
  flush→silence, demand monotonicity, profile constants). All 391
  frontend tests pass.
  **Engine-silence root cause (resolved):** the engine must be primed
  with `outputSeek(inputs, outputSeekLength(rate))` before the first
  `process()` (canonical usage in `cmd/main.cpp` + web demo); without
  it the output is silent/bursty. `outputSeekLength(rate) =
  inputLatency + rate*outputLatency` (5760 @1×/48k). Verified natively
  (sine @1×: 99.8% non-zero, RMS ≈ 0.3535) and in WASM (Node probe,
  18/18 checks: priming, ratios 1.974/0.513, determinism, scalar==SIMD
  bit-identical, re-seek, tail decay + second-flush silence, ramp
  convergence at 2432 frames ≈ 50 ms). A long "bursty output"
  investigation turned out to be a test-harness bug (reading
  `outL[base+i]` — the engine writes every call's output to
  `outL[0..n)`), not an engine/compiler issue.
- **Phase 5 — Worklet integration:** done (2026-10-16). The worklet
  blob is a module script with no base URL for relative imports, so
  the stretch core is shared by **concatenation**: `stretch-worklet.js`
  (plain JS IIFE, no imports/exports) attaches `globalThis.StretchWasm`
  and is prepended to `worklet-processor.js` in `transport.ts`
  (`?raw` imports, both the `moduleUrlFactory` and `URL.createObjectURL`
  paths) — main thread and worklet run the SAME code (no drift).
  `stretch-host.ts` is now a typed facade over
  `globalThis.StretchWasm` (side-effect import + re-exports);
  `stretch-worklet.d.ts` (`export {}` + `declare global`) satisfies the
  strict bundler-resolution tsconfig. `MixState` gains an engine path
  (§11.1 order: per-stem gain/pan/mute/solo → stereo sum → stretch →
  master gain): `processWithEngine` (demand-driven `take`, M2.8
  underrun path when starved), `mixSources`/`fillEngineInput`
  (silence-pad), `processTail` (bounded `flushTail` drain after the
  source ends, early exit on all-zero), `advance` (shared ended/anchor
  bookkeeping), `setRate`; `fillCoeffs` split into
  `fillSourceCoeffs` (input frames) + `fillMasterCoeffs` (output
  frames). **Priming rule:** before the first output (and after every
  seek) the engine is primed with exactly `seekLength()` frames at the
  CURRENT effective rate via `outputSeek`, silence-padded when the seek
  lands within `seekLength` of the endpoint (no deadlock); scratch
  capacity grows to `max(block, seekLength)`. Two integration bugs
  caught by tests and fixed: prime step consumed all buffered frames
  (wrote past the 128-frame scratch) instead of `seekLength`, and the
  near-endpoint prime deadlocked on `budget < seekLength`. The adapter
  (`PcmProcessor`) always builds a `MixState` (1-source init shape
  wrapped), instantiates the engine synchronously from
  `processorOptions.stretch.wasmBytes` (no fetch in the worklet,
  §11.3.11), posts `stretch-ready {inputLatency, outputLatency}` at
  construction, handles `rate {value}` messages; the legacy `samples`
  branch is removed (transport never sent it). `worklet-processor.d.ts`
  updated. `tests/worklet-stretch.test.ts` — 12 tests vs the real WASM:
  prime + 1× (consumed 128, RMS > 0.15, position 9856 @32 quanta),
  2× ratio ≈ 1.97, 0.5× ≈ 0.51, ramp smoothness (no silent quantum),
  anchor bookkeeping (first anchor 0, strictly increasing), seek
  re-prime (anchor = seek target; no-data seek → silence, no underrun),
  near-endpoint prime, underrun at 2× (100 frames → silence/underrun;
  then prime @ 1× seekLength 5760 — the ramp only advances on
  `process()`), end + tail (ended once, tail decays to silence),
  pause/resume without re-prime, master gain post-stretch (RMS ≈ 0.5×),
  plus a worklet-scope adapter block (faked `AudioWorkletProcessor` +
  `registerProcessor` capture, real engine from transferred bytes,
  `stretch-ready` {2880, 2880}, `rate` message, real process loop).
  Gate: frontend 403/403 (391 + 12 new), tsc error set identical to
  clean HEAD (pre-existing only), prettier clean.
- **Phase 6 — Transport wiring:** done (2026-10-16). `transport.ts`
  now loads the stretch artifact on the main thread and hands it to
  the worklet: `defaultFetchStretchBytes()` picks the SIMD build when
  `simdSupported()`, else scalar, via two **static** `new URL(...,
  import.meta.url)` literals (a template literal would defeat Vite's
  asset rewrite in a production bundle) and returns the bytes; the
  transport takes an injectable `fetchStretchBytes` (tests stub it —
  jsdom cannot fetch). `initGraph` `await`s the bytes, adds
  `processorOptions.stretch = { wasmBytes }`, and **always** transfers
  (`[...sabs, stretchBytes]`), so the worklet instantiates the engine
  synchronously with no fetch (spec §11.3.11). A new `stretch-ready`
  worklet message records the engine latencies (source frames); a
  public `engineLatencies` getter exposes them (input latency folds
  into the audible-time mapping; output latency is recorded for the
  M2.10 three-time-domain ledger). `setRate(speed)` clamps to
  0.25…2.0, posts `{type:'rate', value}` to the live worklet, remembers
  the speed for a fresh graph (re-applied at `initGraph`), and — on a
  live graph — starts a new mapping segment (§11.7.5). `TransportSegment`
  gains a `speed` field so each segment extrapolates with its own speed.
  Position mapping: source is consumed at `rate × speed` frames/s, so
  the anchor/segment extrapolation, the `pause()` freeze, and the
  `runFill` budget (`consumedEstimate` + `targetAhead`, keeping the
  1 s / 2 s / 8 s shapes scaled by `s`) all scale with `speed`; the
  audible position subtracts the engine **input** latency (the anchor
  reports the consumed cursor, which leads the audible output).
  `teardownGraph` resets the latencies. Tests: `transport.test.ts`
  gains an M2.9 block (artifact transferred with the node, audible
  position through speed + engine latency at 1×/2×, clamp + `rate`
  post + remembered speed on a fresh graph after context loss) and the
  mode-selection transfer assertions now expect the artifact; the
  initial `processorOptions` assertion gains the `stretch` key.
  Gate: frontend 406/406 (403 + 3 new), tsc error set identical to
  clean HEAD (verified via throwaway worktree at `12c144f`; the one
  transient new error — unused `stretchOutputLatency` — was resolved by
  the `engineLatencies` getter), prettier clean.
- **Phase 7 — Domain + API:** done (2026-10-16).
  `SetPlaybackSpeedOp {speed}` in `domain/commands.py` (frozen,
  discriminated union member, `speed` validated 0.25…2.0 via the
  existing `MIN/MAX_PLAYBACK_SPEED` constants — out-of-range is a
  pydantic 422). Undoable: **not** in `HISTORY_EXCLUDED_TYPES` (only
  `set_position` is). No pre-validation beyond range (speed is
  independent of the result set). Handler branch in
  `storage/repository.py` writes
  `practice_state.playback_speed` (the field and bounds already
  existed in `PracticeState`). Tests: unit (`test_commands.py`:
  bounds, undoable list, request parsing) + integration
  (`test_mixer_commands.py`: `TestSetPlaybackSpeed` — default 1.0,
  apply min, undo/redo to 2.0, persistence across reopen;
  `test_result_set_routes.py`: round-trip through the commands
  endpoint asserts `practice_state.playback_speed == 1.5`, and a
  parametrized out-of-range 422 for 0.24/2.01). Contracts regenerated
  (`scripts/export_openapi.py` + `pnpm --dir frontend run contracts`)
  — the diff is exactly the new `SetPlaybackSpeedOp` schema.
  Gate: backend 1108/1108 (1102 + 6 new), ruff clean, mypy clean
  (63 files); frontend 406/406, tsc error set identical to clean HEAD,
  prettier clean.
- **Phase 8 — Frontend state + UI:** done (2026-10-16).
  New `src/tracks/SpeedControl.tsx` (spec §11.6): slider
  0.25…2.0 step 0.01, numeric entry, presets 0.25 / 0.5 / 0.75 / 1.0 /
  1.25 / 1.5 / 2.0, and a "1×" reset (distinct `aria-label` so it does
  not collide with the 1.0 preset's accessible name). Gesture
  coalescing (§11.7.8): the slider's `input` (React `onChange`) updates
  only a local `draft` display; one commit on release
  (`onPointerUp` / `onKeyUp` / `onBlur`) — same for Enter in the
  numeric entry, preset click, and reset. `clampSpeed` (exported,
  unit-tested): in-range kept, out-of-range clamped, non-finite → 1.0.
  Invalid/empty numeric entry preserves the current value (§11.6).
  `TrackStack` gains the required `onPlaybackSpeed` prop and renders
  the control in the mode bar (speed from
  `practiceState?.playback_speed ?? 1`). `App.tsx`: `handlePlaybackSpeed`
  sends `{type:'set_playback_speed', speed}` through the immediate
  `commands.send` path (never debounced); `applyMix` now also calls
  `transport.setRate(ps.playback_speed)` so the live transport follows
  the committed state (and a fresh graph gets the remembered speed).
  Styles in `styles.css` (`.speed-*`, matching the existing mode-bar /
  mixer look). Tests: new `tests/speed-control.test.tsx` (13 tests:
  clamp bounds + non-finite, render surface, drag coalescing
  input→display-only→release commits once, key-up and blur commits,
  release-without-draft no-op, entry Enter + clamp, invalid entry
  preserves value, preset click, reset, active-preset mark);
  `track-stack.test.tsx` `baseProps` gains `onPlaybackSpeed: noop`
  (all render sites spread it). Gate: frontend 419/419
  (406 + 13 new), tsc error set identical to clean HEAD (32 = 32; the
  one pre-existing App.tsx union error's *message* now prints "12
  more" instead of "11 more" because the `CommandRequest` union gained
  the `set_playback_speed` member — same error, expected display
  shift), prettier clean.
- **Phase 9 — Full gate + evidence + commit:** done (2026-10-16).
  Final gate: backend 1108/1108 pytest, ruff clean, mypy clean
  (63 files); frontend 419/419 Vitest (391 pre-M2.9 + 12 stretch-host
  + 12 worklet-stretch + 3 transport + 13 speed-control), `tsc -b`
  error set identical to clean HEAD (32 pre-existing; the one
  pre-existing App.tsx union error's message now prints "12 more"
  instead of "11 more" because the `CommandRequest` union gained
  `set_playback_speed` — same error, expected display shift),
  `prettier --check .` clean (the final sweep reformatted three
  Phase 3/4 stretch files: `BUILD.md`, `build.mjs`,
  `stretch-profile.ts`); contracts re-exported with no residual diff.
  No-compiler-launch verified: `dist/` artifacts are committed and
  instantiated synchronously from transferred bytes — nothing in the
  runtime path touches emsdk. Evidence doc
  `docs/evidence/m2.9-time-stretch-engine.md` (git-ignored). Single
  M2.9 commit (includes `projectPlans/m2.9-plan.md`) + ledger-hash
  follow-up.

## M2.10 — Latency, bypass, and transport mapping (spec §12)

**Scope (per `projectPlans/m2.10-plan.md`):** three-time-domain
transport ledger (§12.1–12.2), priming that starts audible output
exactly at the requested source boundary (§12.3), a 1× bypass with an
aligned dry/wet transition (§12.4), mixer/diagnostic guarantees
(§12.5), EOF trim (§12.6), and UI synchronization through the ledger
(§12.7). Monitoring-only. Loops themselves stay out (M2.11) — the
ledger carries their hook field.

**Key engine facts (authoritative; upstream source + probes):**

- `seek(inputs, inputSamples, rate)` copies only the **last**
  `blockSamples + interval` = 5760 frames (@48k) of the fed window
  (window length 7200 = 5760 + one interval). The analysis block's
  centre sits `inLat` before the window end; the synthesis places a
  block's centre `outLat` *output* frames after the render position
  where it was created.
- **Rolling law (validated):** with audible cursor `S` at the quantum
  start, `windowEnd = round(S + rate·outLat + inLat)`; zero-pad
  outside `[0, frameCount)`. Impulse-train residuals +45…+75 output
  frames (≈1 ms) at 0.25×–2×, no drift over 600 quanta. The upstream
  live-playback reference uses the same law. `process(0, N)` with
  `N ≤ interval` keeps every block a seek block (`timeFactor =
  1/rate`) — the per-quantum rolling seek is required.
- **Wet start:** `reset()` + silent warm-up (5760 output frames of the
  rolling seek, discarded, ≤8 quanta per callback). Cold first-quantum
  mean 0.0005; at 5760 warm-up frames 0.1000/0.1008/0.0994 at
  1×/2×/0.5× (steady ±0.002). Warm-up is alignment-neutral; cost
  ≈5.8 ms per warm-up (Node, scalar), steady ≈0.13 ms/quantum (≈5 %
  realtime).
- **EOF:** no tail flush; the window tail zero-pads past `frameCount`
  and the natural window fade is the trim (0.1012 → 0.0010 over ~3
  quanta); emission stops at `S ≥ frameCount`, position clamps.
- `set_rate`/`set_rate_now`/`effective_rate` stay as probes; the
  playback path passes its own ramped rate to every `seek`.

**Phase log (all complete — `f46baaf`):**

- **Phase 1 — Plan + ledger:** `projectPlans/m2.10-plan.md` written
  and later revised as-built; this section added.
- **Phase 2 — Wrapper + engine probe:** `stretch_wrapper.cpp`
  rewritten to the rolling-seek surface (`window_length`, `seek`,
  `set_rate_now` added; `input_demand`, `flush_tail`, `seek_length`,
  `output_seek` dropped), artifacts rebuilt (emsdk 4.0.23) and
  committed, `BUILD.md` regenerated; probes pinned the law, warm-up
  envelope/cost, hard-seek isolation, EOF fade.
- **Phase 3 — Worklet data path:** rolling seek, mix ring + exact dry
  tap, silent warm-up, EOF stop, underrun guard, exact-pair anchors
  with `rate` (the M2.9 `lastAnchorTime` latch removed).
- **Phase 4 — 1× bypass:** dry read bit-identical to the no-engine
  path; crossfades (~5 ms) only at exactly 1×; dry→wet = crossfade
  then ramp, wet→dry = ramp then crossfade; master gain post-stretch.
- **Phase 5 — Transport:** seek `{frame: fetchFrame,
  audibleFrame: B, generation}` with `PRE_ROLL_FRAMES = 12_288`;
  `anchorRate` extrapolation without latency subtraction; pre-roll in
  `load`/`rebind`; `controlResponseLatencySeconds` diagnostics.
- **Phase 6 — Tests + evidence:** `stretch-priming.test.ts` rewritten
  (§12.3 probe suite, 14), `stretch-host.test.ts` on the new API
  (15), `worklet-stretch.test.ts` (12), `worklet-core.test.ts` and
  `transport.test.ts` moved to the exact-pair/rolling model; evidence
  `docs/evidence/m2.10-latency-bypass.md`.
- **Phase 7 — Gate:** backend 1108/1108 pytest, ruff + mypy clean;
  frontend 438/438 Vitest, `tsc -b` at the 32-error pre-existing
  baseline, prettier clean.

**Accepted caveats (documented in the evidence):** a wet seek's sound
starts after the ≈16 ms silent warm-up (ledger maps the audible
boundary exactly; wall-clock onset trails it); sharp edges near a rate
change show transition-shape smearing (≤ ~1 ms at 1×, up to ~20 ms at
0.25× worst step; impulse centroids ±1.5 ms); the worklet's read-ahead
(max 8640 frames @2×) is the ≈120–180 ms §12.5 control-response
latency shown in diagnostics.

## M2.11 — Saved practice loops (spec §13)

**Scope (per `projectPlans/m2.11-plan.md`):** loop schema (name, exact
frame boundaries, color, repeat count, boundary fade), creation/editing
(selection, numeric entry, drag handles, move, rename, color,
duplicate, delete, active select, `L` toggle), validation (range
against the duration; ≥100 ms for repeated playback; exact boundaries),
playback behavior (enable rules, stop at completion, new repeat
sequence on Play), loop buffering, 5 ms boundary fades, looping through
the stretcher with cumulative fractional duration accounting.
Monitoring-only; count-in and musical anchors deferred.

**Design — the stream model:** a loop makes the transport's data stream
periodic over `[start, end)`; both transport and worklet track a stream
coordinate `c` whose source frame is
`start + ((c − start) mod len)`. Stream coordinates are source-aligned
at each seek boundary (the worklet reads the ring linearly; the
transport feeds the periodic content). The fetch cursor cycles (each
chunk clamped at the pass end in source space); a loop seek fetches
`B − 12288` **without** the `max(0, …)` clamp (negative stream
coordinates map to the loop's tail — the periodic pre-roll); the shared
ring's modulo becomes negative-safe. Positions stay monotonic in the
ledger; the public position maps stream → source. Wrap anchors
(`{frame: E_k, time}`) are emitted at each pass crossing; the pass end
is `current + (end − sourceOfStream(current))`, so a partial first pass
(enabled mid-loop) counts as pass 1. Fades are output-domain:
`min(5 ms, len/rate/4)` out/in around each crossing; `fade: false`
skips them (exact boundary audition, bit-exact 1× dry). Loop toggles
and boundary edits apply at controlled transitions (synchronized
re-seek, §13.8); seeks outside an enabled loop disable looping and
retain the loop (§13.4.5).

**Phase log (all complete — `f65370a`):**

- **Phase 1 — Plan + ledger:** done (2026-10-16). `m2.11-plan.md`
  written (stream model, fade design, playback rules, domain/UI
  breakdown); this section added.
- **Phase 2 — Domain + commands + repository:** done (2026-10-16).
  `PracticeLoop` gained `color` (default `#f59e0b`), `repeat_count`
  (`None` = infinite, 1…9999) and `boundary_fade` (default true);
  `PracticeState` enforces "`loop_enabled` requires an active loop".
  Six ops: `add_loop` (server default "Loop N"), `update_loop` (patch;
  absent vs explicit-null `repeat_count` via `model_fields_set`),
  `delete_loop` (clears active + enabled when it was active),
  `duplicate_loop` ("<name> copy", suffix preserved at 80 chars),
  `set_active_loop` (null clears + disables), `set_loop_enabled`.
  Validation: `add_loop`/`update_loop`/`set_loop_enabled` are
  ready-required; `0 ≤ start < end ≤ duration` (`LoopRangeInvalidError`
  → 422 `LOOP_RANGE_INVALID` with details); unknown loop → 404
  `LOOP_NOT_FOUND`; enable without an active loop → 409
  `NO_ACTIVE_LOOP`; enable < 100 ms → 409 `LOOP_TOO_SHORT` naming the
  minimum (the saved interval is untouched). Contract exported,
  `schema.ts` regenerated, `check_contract.py` OK. Tests: 39 new (30 in
  `test_loop_commands.py`, 4 in `test_practice.py`, 5 route-level
  `TestLoopCommands`); ruff + mypy clean.
- **Phase 3 — Worklet:** done (2026-10-16). `MixState` gained the loop
  state (`{start, end, len, repeatCount, fade}`), `setLoop` (with the
  seek — atomic — or mid-stream, §13.4.3), the pass counter, the
  crossing bookkeeping (`loopNextCrossing`/`loopCounted`, one crossing
  per quantum for loops ≥ 100 ms), the join notch
  (`loopFadeFrames = min(5 ms, len/rate/4)` output frames; V-gain
  `min(1, |center − i|/fade)`; the counted crossing stays the head until
  its fade-in played out), the finite-repeat stop (silence after the
  final crossing, position frozen at the pass end, `loopComplete` once)
  and the wrap anchors (`wrap: true`, exact `{frame: E_k, time}`). All
  `frameCount` clamps became loop-aware (window/dry/fillRing/warmup/EOF,
  plain + engine paths); `ConsumptionState` gained `setLooping` with the
  matching clamps and a negative-safe shared read; `writeSharedRing` is
  negative-safe (periodic pre-roll). Adapter: `seek` carries `loop`,
  the `loop` message installs/clears mid-stream, `loop-complete` is
  posted with the exact pass end (never `ended`). Tests: 15 new in
  `frontend/tests/worklet-loops.test.ts` (pass counting, exact wrap
  anchors, fade shape/cap/off, completion, partial first pass,
  mid-stream enable, adapter protocol, and the acceptance: exact
  crossing frames + exact cumulative durations at 0.25×–2× with the
  real WASM engine); 453/453 frontend tests, prettier clean, tsc
  unchanged (32 pre-existing).
- **Phase 4 — Transport:** done (2026-10-16). `TransportLoopSpec` +
  `onLoopDisabled`; worklet-loop bookkeeping (`workletLoop`/
  `workletLoopKnown`, idempotent sync); stream↔source mapping
  (`sourceFromStream`) with the worklet's loop as the authority;
  loop-aware `getAudiblePosition` (unbounded clamp; `loopStoppedSource`
  after a finite sequence); `play()` rule chain (§13.4.1–7: start at
  the loop start when outside, continue inside, synchronized seek when
  enabled outside, completion restarts); `seek()` outside an enabled
  loop disables looping + reports (§13.4.5); `setLoop`/
  `setLoopEnabled` with the mid-stream install policy (install only
  while the buffered content is entirely inside the loop and no fill
  round is in flight, else a controlled rebuffered transition —
  deliberate deviation from the plan's always-install wording:
  buffered lookahead past the loop end is linear content);
  `flushBookkeeping` loop-aware pre-roll (negative stream coordinates
  map to the loop tail) + `loop` in the seek message; `runFill` fetch
  cycling (chunk clamped at the pass end, unbounded target ahead);
  `loop-complete` parks the transport paused at the loop end (the stop
  position survives a later disable so Play restarts linearly from it);
  `teardownGraph` resets the loop bookkeeping. Tests: 12 new in
  `frontend/tests/transport.test.ts` (enable rules, mid-stream install
  vs transition, seek-outside disable + callback, completion, position
  mapping, fetch cycling + periodic pre-roll, boundary-edit transition);
  465/465 frontend tests, prettier clean, tsc unchanged (32
  pre-existing).
- **Phase 5 — UI:** done (2026-10-17).
  - `render.ts`: `LOOP_DEFAULT_COLOR`/`LOOP_COLORS`, `loopFillColor`,
    `drawLoop` (tint + top border + 3 px boundary handles).
  - `WaveformEditor.tsx`: `loop` + `onLoopRangeChange` props; the
    overlay draws on the selection layer under the selection; pointer
    priority is loop-start / loop-end (HANDLE_HIT_PX) / body move,
    Shift+drag bypasses to the selection gesture; body moves preserve
    the exact length and clamp to the source; drags preview locally and
    commit exactly once on pointerup; a sub-threshold body press seeks.
    7 new tests; 57/57 in `WaveformEditor.test.tsx`.
  - `practice/LoopsPanel.tsx` (new): list with swatch color cycle,
    inline rename (blur/Enter, 80-char cap), numeric boundaries in
    seconds (3 decimals, invalid entries revert locally — never
    expanded), duration + exact-frame readout, repeat count (blank =
    infinite), fade toggle, duplicate/delete (no row re-select),
    row-click active select, the Looping checkbox and the
    `MIN_REPEATABLE_LOOP_SECONDS` hint. 16 tests in
    `tests/loops-panel.test.tsx`.
  - App wiring: `PlaybackPanel` gains `applyLoop` (guarded so an
    unrelated practice change never re-sends an unchanged spec; seeded
    at transport creation so a restored `loop_enabled` applies without
    the first-play race) + `onLoopDisabled` → `set_loop_enabled false`;
    `ProjectView` gains the live selection mirror (seeded from the
    restored working state), all six loop command handlers (create
    activates the new loop), the local 100 ms enable validation with
    the inline explanation, and a document-level `L` toggle (typing
    guard, no-op without an active loop). `ProjectSummary` gained
    `sample_rate`; `useProjectCommands` gained `durationFrames`;
    `styles.css` loop-panel classes. `tsc -b` unchanged (32
    pre-existing); prettier clean on touched files.
  - `tests/app-loops.test.tsx` (new, 7 tests): restored loop → transport
    spec + `setLoopEnabled`; checkbox and `L` toggles (typing guard);
    no-op without an active loop; the 100 ms minimum explained locally
    with no command sent; create-from-selection (`add_loop` +
    `set_active_loop`) showing in the panel and as the drawn overlay;
    one `update_loop` per boundary drag with the transport following
    the new spec. App-level backend fake applies ops like the
    repository.
  - Gate: 495/495 frontend tests (28 files), `tsc -b` unchanged
    (32 pre-existing), `prettier --check .` clean.
- **Phase 6 — Evidence + gate + commit:** done (2026-10-17). Evidence
  report `docs/evidence/m2.11-practice-loops.md` (local, git-ignored;
  records the mid-stream install deviation and the UI gesture choices).
  Gate: backend **1147/1147** pytest (the known-flaky job-manager test
  passed), `ruff check src/ tests/` clean, `mypy src/` clean (63
  files), `check_contract.py` in sync; frontend **495/495** Vitest (28
  files; +30 over the pre-M2.11 465), `tsc -b` at the unchanged 32-error
  pre-existing baseline, `prettier --check .` clean. Commit `f65370a`
  (`M2.11: saved practice loops (spec §13)`).

**Accepted caveats (documented in the evidence):** the mid-stream
install policy is a deliberate refinement of the plan's "always send
`{type:'loop'}`" wording — install only while the buffered content is
entirely inside the loop and no fill round is in flight, else a
controlled rebuffered transition (buffered lookahead past the loop end
is linear content and must not leak into the periodic stream); the UI
loop gesture is an implementation choice (plain drags inside the
overlay range are loop edits, Shift+drag forces a selection), pinned by
the component tests; the 100 ms minimum is explained locally with the
server 409 as the backstop; count-in and musical anchors are deferred
by spec (§13.1) and loop export is M2.13. Monitoring-only throughout —
no source or annotation writes.

## M2.12 — Extended buffering and resource limits (spec §14)

**Scope (per `projectPlans/m2.12-plan.md`):** speed-scaled source
buffering with byte + duration caps (24 s/stem, 32 MiB/stem, group-min
frame capacity), the pinned-loop budget (64 MiB/group, pre-roll +
complete-loop cache, streaming fallback), group readiness (per-stem
reporting, group generation, single-stem failure policy, muted
alignment), thread/resource separation (priority job classes,
memory-bounded media worker, browser fetch priority), and local
runtime diagnostics (procfs, nvidia-smi, worklet counters) surfaced
through `/api/v1/system`. Separation job scheduling stays with M2.17
(analysis class slot reserved).

**Design decisions:**

- Sizing policy computed once per group in the transport
  (`SOURCE_BUFFER_SECONDS = 24`, `SOURCE_BUFFER_BYTES = 32 MiB`,
  group-min of the two); `capacityFrames` passed to the worklet in
  `processorOptions`; `targetAhead = rate × speed × 8 s` clamped to
  `capacity − margin` (2× headroom asserted).
- Loop pinning: eligible iff `len × ΣbytesPerFrame ≤` the remaining
  64 MiB; filled from ordinary loop fetches (transfer arrays adopted;
  shared payload captured alongside the SAB write); passes and the
  pre-roll served from the immutable pin once complete; released on
  change/disable; never counted in the streaming budget.
- Job priority classes: playback-preparation > import-critical >
  background (waveform); FIFO within class; one bounded media job;
  `media_worker_memory_limit_mb` (default 4096) → child `RLIMIT_AS`.
- Diagnostics: procfs (host + API + worker), nvidia-smi (free + peak
  sampled), job state, last separation elapsed (null until M2.17),
  worklet `buffered` extension (`stems`, `capacityFrames`,
  `lastCallbackMs`, `stretcher`); no telemetry, same-origin only.

**Phase log (all complete — `0e88c7a`):**

- **Phase 1 — Plan + ledger:** done (2026-10-17). `m2.12-plan.md`
  written; this section added.
- **Phase 2 — Backend scheduler + limits + diagnostics:** done
  (2026-10-17). `JobManager` now enqueues into a priority queue
  (playback-preparation `MONITORING_DOWNMIX`/`PLAYBACK_RATE` >
  import-critical `PROBE`/`CANONICAL_DECODE` > background `WAVEFORM`;
  FIFO within a class via a monotonic sequence) and exposes
  `queue_depth`/`worker_pid`. New `media_worker_memory_limit_mb`
  config (default 4096, min 256) flows through `media_worker_command`
  to a best-effort `RLIMIT_AS` in the child
  (`media_worker.apply_memory_limit`). New
  `runtime_diagnostics.py` (procfs RSS/CPU for API and worker,
  `nvidia-smi` free/peak via a sampler that runs only while a job is
  active, job state/queue depth, `SeparationRepository.
  latest_run_elapsed_seconds`) is wired in the lifespan and surfaced
  as an optional `runtime` object on `GET /api/v1/system`. Tests:
  priority ordering, config validation, memory-limit application,
  proc parsing, GPU tracker, collector shape, `/system` runtime
  block, repository elapsed query; contract + frontend schema
  regenerated.
- **Phase 3 — Transport sizing + worklet contract:** done (2026-10-17).
  New `sourceBufferCapacityFrames` policy in `transport.ts`
  (`SOURCE_BUFFER_SECONDS = 24`, `SOURCE_BUFFER_BYTES = 32 MiB`,
  per-source min of duration/byte caps, group minimum), passed to the
  worklet as `processorOptions.capacityFrames` and used for the shared
  SAB sizes; `runFill`'s speed-scaled `targetAhead` clamps to
  `capacity − margin`, and the gate/start thresholds clamp to fractions
  of a byte-capped ring so flow control cannot deadlock. The worklet
  accepts `capacityFrames` (12 s fallback for the legacy init shape),
  keeps the SAB capacity authoritative on the shared path, measures the
  render-callback duration (`lastProcessMs`), and reports `stems`,
  `capacityFrames`, `callbackMs`, and `stretcher` on `buffered`.
  `TransportDiagnostics` gained `capacityFrames`, `bufferedBytes`,
  `budgetBytes`, `stemBufferedFrames`, `callbackDurationMs`,
  `stretcher` (plus `pinnedBytes`, filled in Phase 4), and
  `initialTransportDiagnostics()` is shared with `App.tsx`. Tests: new
  `buffer-sizing.test.ts` (caps matrix), transport sizing/2× headroom/
  report tests, worklet capacity + callback tests; the 12 s-pinned
  transport tests moved to the new numbers.
- **Phase 4 — Loop pinning:** done (2026-10-17). New
  `loop-pin.ts` (`LoopPin`, `PINNED_BYTES_MAX = 64 MiB`): per-source
  channel arrays for the loop range, coverage bitset, partial-pass
  retention with duplicate/outside clipping, `ready`, `copyChannels`
  (transfer clones), `writeShared` (wrap-aware SAB write via a reused
  scratch, 0 when full). The transport installs one pin per effective
  loop when `len × ΣbytesPerFrame ≤ PINNED_BYTES_MAX` (group-wide
  first-come; `syncPin` on set/clear/disable/seek-outside/load/rebind/
  dispose), captures loop-interior frames during ordinary fetches
  (transfer arrays copied before relay; shared path asks the worker for
  the payload via `retain`), and serves the fill round from the pin
  once ready — including the periodic pre-roll (the mapped fetch cursor
  lands inside the pinned range). `pinnedBytes` is reported and
  preserved across seeks. Tests: `loop-pin.test.ts` (retention,
  clipping, multi-source readiness, byte accounting, serve/ring
  contract), transport tests (first pass fetched, later passes/pre-roll
  served without fetches, release + refill on disable, boundary edit
  replaces the pin, > 64 MiB streaming fallback, shared-path
  retention); the M2.11 pass-end cycling test now asserts pin-served
  stream order.
- **Phase 5 — Group readiness + fetch priority:** done (2026-10-17).
  `fetchPcmRange` takes a `priority` argument (default `'high'` for
  playback chunks); `fetchAssetBytes` and the waveform tile/PCM fetches
  pass `'low'`. Tests pin the hints (no-op without browser support).
  Group readiness: new transport tests prove a leg superseded by a seek
  aborts the entire round (the refill restarts at the seek pre-roll for
  both legs; the stale chunk never reaches the worklet) and that a
  permanent single-stem failure stops the group (error state, no
  further relayed chunks for the healthy stem); a new worklet test pins
  the group gate for a muted but unsynchronized stem (muted stems are
  consumed and aligned, not exempt). Per-stem `stems` reporting was
  wired in Phase 3 and is asserted from the transport side.
- **Phase 6 — Diagnostics UI:** done (2026-10-17). New
  `frontend/src/system/useSystemRuntime.ts` polls `GET /api/v1/system`
  every 2 s while the playback panel is mounted (project open), keeps
  the last good values on failure, and clears the interval on
  unmount/disable. The panel's `.underrun-diagnostics` line becomes an
  expanded `.runtime-diagnostics` block (aria-label "Runtime
  diagnostics"): underruns, per-stem buffered frames, buffer/pin bytes
  in MiB, worklet callback duration, stretcher rate/bypass, and the
  runtime rows (media-worker RSS/CPU, GPU peak, current job phase with
  progress and queue depth, last separation seconds). Tests: hook
  lifecycle (`use-system-runtime.test.tsx`) and panel rendering
  (`playback-panel.test.tsx`).
- **Phase 7 — Evidence + gate + commit:** done (2026-10-17). Evidence:
  `docs/evidence/m2.12-buffering.md` (git-ignored local artifact; the
  long-form record). Gates: backend **1180/1180** pytest passed (2
  pre-existing environment warnings), `ruff check` clean, `mypy src/`
  clean (64 files), `check_contract.py` in sync; frontend **530/530**
  Vitest (31 files; +32 over the pre-M2.12 495 plus 3 worklet-bridge
  tests), `tsc -b` at the unchanged 32-error pre-existing baseline,
  `prettier --check .` clean. Local acceptance run in a real browser
  (production bundle served by the CLI, Playwright/Chromium, fresh
  storage under `/tmp/opencode/m2.12-run/`): a 6:00 stereo project
  imported and decoded through the HTTP API played to its natural end
  with **zero underruns** while the media worker ran one
  `playback_rate` job, four single `waveform` jobs, and a batch of
  eight queued `waveform` jobs (9.23 s of worker time); the runtime
  diagnostics block reported the live job phase/progress/queue depth
  (`Job: waveform (building_waveform) 3%, 10 queued`) at a steady
  `Buffer: 2.5 MiB / 8.8 MiB`, `Callback: 0.0 ms`, `Stretcher: 1.00×
  (bypass)`, with `crossOriginIsolated === true` (the shared-ring
  path). The run could not start playback at all until five
  pre-existing browser-path defects were fixed: (1) no real-context
  `AudioContext` bridge for the transport's `createWorkletNode` seam
  (M1.12 era), (2) the CSP blocked the worklet Blob module and
  WebAssembly compilation (`script-src` now allows `blob:` and
  `'wasm-unsafe-eval'`), (3) SharedArrayBuffers were listed in
  transfer lists (the worklet options and the fetch worker's
  `shared-init`) — browsers throw on that; SABs now serialize by
  sharing, only the WASM artifact is transferred, (4) the worklet
  adapter implemented a non-standard `process(time, input, output)`
  signature instead of the real `(inputs, outputs, parameters)`
  contract (block time from the global `currentTime`; the node is now
  created with `numberOfInputs: 0, numberOfOutputs: 1,
  outputChannelCount: [2]`; the core consumes `outputs[0]`; the tests
  were updated to drive the real contract), and (5) the fetch worker
  had no session token (dedicated workers cannot read
  `sessionStorage`; the token is now injected with `{kind: 'auth'}`
  before any fetch job). Caveats in the evidence: the pre-existing UI
  uploader chunk-hash mismatch and the missing UI `canonical_decode`
  caller meant the acceptance imports were seeded through the HTTP
  API, exactly as the backend tests do; the separation half of the
  acceptance stays deferred with M2.17. Commit `0e88c7a` (`M2.12:
  extended buffering and resource limits (spec §14)`).

## M2.13 — WAV stem export (spec §15)

**Scope (per `projectPlans/m2.13-plan.md`):** export the published
stems of an immutable separation result set (bass, others residual,
four-stem outputs, or any selected subset) as WAV files — 16-bit,
24-bit (default), or float32, at the source rate (default) or 44.1/48
kHz, with optional linked peak normalization to −1 dBFS (off by
default; never per-stem), triangular dither when reducing to integer
PCM, and FFmpeg encoding with `-rf64 auto`. Full source duration at
original speed only; mixer/limiter/speed state never affects raw
exports. New §19.2-reserved interfaces: `POST
/api/v1/projects/{id}/exports`, `GET /api/v1/downloads/{artifact_id}`
(plus a project export listing). Separation scheduling stays with
M2.17; export is a media-worker job.

**Design decisions (Phase 1):**

- **Job shape:** `JobType.EXPORT` created by `POST
  /projects/{id}/exports` (Idempotency-Key honored via the existing
  store) with `result_set_id` (default: active set), `asset_ids`
  (default: all stems), `format`, `sample_rate`, `normalize`.
  Validation resolves the set via `get_result_set_detail`, checks stem
  files (`frames × channels × 4`), errors `EXPORT_RESULT_SET` /
  `EXPORT_STEM_MISSING` / `EXPORT_ALIGNMENT` / `NO_STEMS`.
- **Pre-existing defect fix:** `manager._run_job` requires an
  import-backed source for every job, so M2.7's stem waveform jobs
  (`parameters={"asset_id": …}`, no import) fail `NO_SOURCE` at
  execution. Import-less jobs now compute parameters first and resolve
  the run source from them (waveform: `parameters["source_path"]`;
  export: the first stem's path), with a stem-waveform regression test.
- **DSP (worker):** one streaming pass per stem for size/hash/joint
  peak; disk pre-flight (`DISK_HEADROOM_FACTOR` + minimum free);
  integer outputs refuse when the joint peak exceeds the integer
  full-scale bound (`EXPORT_CLIPPING`, remedies float32 or linked
  normalization); linked normalization applies one −1 dBFS gain across
  the set and records it; ffmpeg chain `volume=<gain>dB` (normalized
  only) → `aresample=<target>:dither_method=triangular` for integer
  outputs (resample-only for float32); `-rf64 auto`; ffprobe
  verification from the stream duration (decoded frames =
  `round(duration × rate)`; equal-rate exact, resampled within
  `ENDPOINT_TOLERANCE_FRAMES`; FFmpeg 8.x reports no meaningful
  `nb_frames` for PCM streams); output SHA-256.
- **Storage/report:** migration 9 adds `export_artifacts` (per-stem
  row: settings, gain, dither, hash, byte size, relative path, safe
  download filename) and extends the `media_jobs` job-type CHECK.
  Publisher verifies staged files and hash-dedup moves them to
  `data/exports/<sha256>.wav` (inside the protected `data` category,
  no `StoragePaths` change). `GET /downloads/{artifact_id}` streams
  with `Content-Type: audio/wav` + `Content-Disposition: attachment`.
  §9.5.6 protection: reclaim skips assets referenced by non-terminal
  export jobs.
- **Priority:** new export class between import-critical and waveform:
  playback preparation (0) > import-critical (1) > export (2) >
  waveform (3); the priority test is updated.
- **Frontend:** `api/exports.ts` (create/list/download; authenticated
  fetch → Blob → synthetic `<a download>`), `waitForJob(onProgress)`,
  an inline `ExportPanel` in the `TrackStack` mode bar (stem
  checkboxes, format/rate selects, linked normalization, progress,
  download list, clipping error surfacing).

**Phase log:**

- **Phase 1 — Plan + ledger:** done (2026-10-17). `m2.13-plan.md`
  written; this section added.
- **Phase 2 — Backend plumbing:** done (2026-10-17). `JobType.EXPORT`
  + the three export stages; migration 9 (`export_artifacts` + the
  `media_jobs` CHECK rebuild, schema v9); `ExportArtifactRepository`
  (republish-safe DELETE-then-INSERT); `manager._run_job` import-less
  source resolution (`_parameter_source_path`: waveform →
  `parameters["source_path"]`, export → first stem) with the
  stem-waveform regression test; `_export_parameters_for` + safe
  download filenames; `POST /projects/{id}/exports` (Idempotency-Key,
  `result_set_id`/`asset_ids`/`format`/`sample_rate`/`normalize`,
  validation `EXPORT_RESULT_SET`/`EXPORT_STEM_MISSING`/
  `EXPORT_ALIGNMENT`/`NO_STEMS`), `GET .../exports`, `GET
  /downloads/{artifact_id}` (attachment stream); publisher
  `ExportResult` branch (hash-dedup move to `data/exports/<sha256>.wav`);
  reclaim protection (`in_flight_export_asset_ids`); export priority
  class (2, between import-critical and waveform); contract + TS types
  regenerated (`check_contract.py` OK). 53 new backend tests; full
  suite 1238 passed.
- **Phase 3 — Worker export DSP:** done (2026-10-17).
  `media/export.py` (streaming size/hash/joint-peak measurement, disk
  pre-flight, clip rule, `volume`+`aresample` chain with
  `out_sample_fmt`/triangular dither, `-rf64 auto`, duration-based
  ffprobe verification, per-stem timeouts, cancellation); worker
  wiring (`_export_parameters` validation, `_run_export`, `EXPORT`
  dispatch, `EXPORT_*` error codes, `media.export` capability);
  `tests/integration/test_export_worker.py` (16 real-ffmpeg tests:
  wav16/24/32f, 44.1→48k resample, linked normalization to −1 dBFS,
  clipping refusal, verification failures, cancellation, progress
  stages, disk budget, worker protocol). Full suite 1254 passed;
  ruff + mypy clean.
- **Phase 4 — Frontend export panel:** done (2026-10-17).
  `src/api/exports.ts` (`createExport` with a fresh `Idempotency-Key`
  per call, `listExports`, `downloadExport` via authenticated fetch →
  Blob → synthetic `<a download>`, `ExportRequestError` carrying the
  server code); `waitForJob` gained an `onProgress` option
  (`src/api/playback.ts`); `src/tracks/ExportPanel.tsx` (collapsible
  in the `TrackStack` mode bar: stem checkboxes defaulting to all of
  the active set, format/rate selects, linked −1 dBFS normalization,
  job progress with stage labels, delivered-artifact list with
  download buttons, error surfacing incl. `EXPORT_CLIPPING`); CSS in
  `styles.css`. Frontend gates: 537 Vitest passed (530 baseline + 7
  new in `tests/exports.test.ts`; the 4 `track-stack.test.tsx` name
  queries scoped to `.track-name`), `tsc -b` at the 32-error baseline
  (no new errors), prettier clean, `vite build` OK.
M2.13 complete. Evidence in `docs/evidence/m2.13-wav-export.md`
(git-ignored): the export pipeline is verified end to end at the
worker level with real ffmpeg 8.1.2 (measurement, encoding,
duration-based ffprobe verification, clip refusal, cancellation,
disk budget, worker protocol), the routes and storage with the
FastAPI TestClient, and the frontend with jsdom. Accepted
caveats: duration-based frame verification (FFmpeg 8.x reports
no meaningful `nb_frames` for PCM), float32 passthrough within 1
ULP (deterministic pipeline rounding, no dither/quantization),
hash-deduped export files, no production-bundle browser run of
the panel. Commit `ff350c8` (`M2.13: WAV stem export (spec
§15)`).



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

## M2.14 — Portable project format (spec §16)

**Phase 1 (2026-10-17):** plan written
(`projectPlans/m2.14-plan.md`). M2.14 is the format *definition*
only: container layout, manifest schema, compression policy,
dependency closure, and the project-only database builder. Archive
writing is M2.15 (spec §17); opening is M2.16 (spec §18). No
routes, no frontend. Design: `portable/format.py` (FORMAT_ID
`basseparate.project`, container v1; members `manifest.json`,
`project.sqlite`, `assets/sha256/<hash><ext>`,
`caches/waveforms/<source_hash>/...`,
`provenance/separation-runs.json`,
`provenance/model-manifests.json`; stored compression for
media/PCM/sqlite, deflate for text; essential vs optional
classification — playback-rate and waveform caches optional,
source/canonical/downmix/stems essential); `portable/closure.py`
(`PortablePlan`: asset closure from project columns +
`project_assets` + result-set/stem `record_json` refs +
representation parents; waveform caches; provenance payloads;
export artifacts excluded — reproducible deliverables, not in
the §16.2 list); `portable/database.py` (backup-API snapshot →
DDL replay from `iterdump` → streaming `INSERT ... SELECT` per
table with closure predicates → `foreign_key_check` →
isolation proof → atomic move; delete journal mode, no WAL
sidecar).

**Phases 2–4 (2026-10-17):** `src/basseparate/portable/` implemented.
`format.py`: FORMAT_ID `basseparate.project`, container v1, fixed
member names, asset member naming (`assets/sha256/<hash><ext>`: `.pcm`
for PCM roles, the upload extension for `source_original`, `.bin`
fallback), waveform cache prefix `caches/waveforms/<source_hash>/`,
compression policy (stored for media/cache/sqlite, deflate for
text), `ManifestMember`/`ManifestAsset`/`ManifestProvenance`/
`PortableManifest` (all §16.4 fields, frozen, JSON round-trip).
`closure.py`: `compute_portable_plan` → `PortablePlan` (asset
closure from project columns + `project_assets` + result-set/stem
`record_json` refs + representation-parent fixpoint; waveform caches;
separation run records; `PortableAsset.essential` classification
— playback-rate caches optional, source/canonical/downmix/stems
essential); `separation_runs_payload` / `model_manifests_payload`
(registry metadata only, no weights). `database.py`:
`build_portable_database` (backup-API snapshot → DDL replay from
`iterdump` + explicit `user_version` → streaming `INSERT ... SELECT`
per table → `foreign_key_check` + `integrity_check` + isolation
proof → atomic `.part` → final move; `export_artifacts` excluded).
43 new unit tests (`tests/unit/test_portable_format.py`,
`test_portable_closure.py`, `test_portable_database.py` +
`portable_seed.py` two-project seed incl. a WAL-mode source test).
Gates (all green): backend 1297 pytest (1254 baseline + 43),
ruff clean, mypy clean (71 files), contract in sync; frontend
untouched — 537 vitest (baseline), tsc -b 32 pre-existing
errors (baseline), prettier clean, vite build OK.
M2.14 complete. Evidence in
`docs/evidence/m2.14-portable-format.md` (git-ignored). The
portable format is defined and its two core algorithms (the
dependency closure and the project-only database builder) are
implemented and tested; the archive writer (M2.15, spec §17)
and the archive reader/validator (M2.16, spec §18) build on
this package. Commit `ec0b1eb` (`M2.14: portable project format
(spec §16)`) + this ledger-hash follow-up.

## M2.15 — Safely save portable projects (spec §17)

**Phase 1 (2026-10-17):** plan written
(`projectPlans/m2.15-plan.md`). Design: synchronous save (FastAPI
threadpool, no media job — pure file I/O; job scheduling stays in
M2.17). `portable/writer.py`: ZIP64 writer, deterministic
`date_time` from `saved_at`, per-member streaming SHA-256,
`compression_for` per member, members in fixed order
(`project.sqlite`, `assets/...`,
`caches/waveforms/...`, provenance JSONs, `manifest.json` last),
manifest excludes itself, close + fsync. `portable/save.py`:
§17.1 pipeline — capture `projects.revision`, `compute_portable_plan`
(the plan's asset set is the temporary reference for the save),
file-presence check (essential missing → `SAVE_ASSET_MISSING` 409;
optional missing → excluded from archive AND portable DB via the new
`excluded_asset_ids` parameter on `build_portable_database`), size
estimate + free-space check (`SAVE_NO_SPACE` 507), stage in
`data/portable/.staging/<uuid>.basseparate`, verify the staged
archive (CRC + re-hash every member against the manifest + member-set
check + manifest validation), archive sha256, retain one previous
artifact, atomic `os.replace` publish to
`data/portable/<project_id>/<revision>-<sha12>.basseparate`,
best-effort directory fsync, record the `portable_artifacts` row;
failure deletes only its own staging file — the last valid file is
never destroyed. `domain/portable.py`: `PortableArtifact` (id,
project_id, saved_revision, sha256, byte_size, relative_path,
download_filename, created_at). Migration 10: `portable_artifacts`
table + index, schema v10. `PortableArtifactRepository` (publish,
delete_older, get, list, latest). Routes: `POST
/projects/{id}/portable-saves` (201, Idempotency-Key per M2.13),
`GET /projects/{id}/portable-saves`, `GET
/portable-downloads/{artifact_id}` (streaming, Content-Disposition,
X-Content-Sha256). Frontend: `api/portable.ts`,
`PortableSavePanel.tsx` in `ProjectView` (§17.5: saved-through
revision N + download link + newer-unsaved-changes note + saving
state), CSS, vitest. Contract regeneration required (new API
surface). "Flush pending manual commands" is an architectural no-op
(commands are durable at apply-time).

**Phase 2–6 (2026-10-17):** implemented and green. Backend:
`domain/portable.py` + migration 10 (`portable_artifacts` table +
index, schema v10, `DATABASE_SCHEMA_VERSION` bump); v9 test
baselines updated to v10; `PortableArtifactRepository` (publish /
delete_older / get / list_for_project / latest_for_project,
record_json + `model_validate_json` pattern) exported from
`basseparate.storage`; `excluded_asset_ids` on
`build_portable_database` filters `assets`, `representations`,
`waveform_caches` AND `project_assets` (FK constraint discovery;
invariant: excluded assets are never parents of retained
representation rows — true for playback-rate assets by
construction); `portable/writer.py` (ZIP64, per-member
`compression_for`, 1 MiB streamed chunks with SHA-256, all
`date_time` from `saved_at` for deterministic bytes, fixed member
order with `manifest.json` last, partial-file + fsync + replace);
`portable/save.py` (error family `SAVE_ASSET_MISSING` 409 /
`SAVE_NO_SPACE` 507 / `SAVE_VERIFY_FAILED` 500;
`plan_with_exclusions`; file-presence check; size estimate +
`shutil.disk_usage` check; `_verify_archive` = testzip + per-member
re-hash vs manifest + member-set equality + manifest validation;
retain one previous artifact; row recorded only after publish;
failure deletes only its own staging files — the last valid file is
never destroyed). Routes: `POST /api/v1/projects/{id}/portable-saves`
(201, Idempotency-Key, empty-body hash), `GET
/api/v1/projects/{id}/portable-saves`, `GET
/api/v1/portable-downloads/{artifact_id}` (streaming,
Content-Disposition, X-Content-Sha256, X-Artifact-Id);
`PortableArtifactNotFoundError` (404, missing_file variant) and
`PortableSaveConflictError` (409) in `api/errors.py`; router wired
in `app.py` (`app.state.portable_repository`). `relative_path`
carries the `data/` category prefix
(`data/portable/<project_id>/<file>.basseparate`) so
`StoragePaths.resolve_asset_path` resolves it like every other
data-root path (initial design used a bare `portable/...` prefix,
which resolved to the state dir — caught in route tests).
`portable_seed.py` extended: project rows carry the full source
fields (`source_stream_index`, `source_channel_count`,
`decode_profile_version`, `source_metadata`) and
`create_seed_files` writes the on-disk files (7 asset files +
waveform cache). Frontend: `api/portable.ts` (save / list /
download), `PortableSavePanel.tsx` mounted in `ProjectView` (§17.5:
saved-through revision N + size, download button, newer-unsaved
note, saving state, inline errors), CSS in `styles.css`, tests.
Contract regenerated (`contracts/openapi.json` +
`frontend/src/api/schema.ts`); `scripts/check_contract.py` passes.
New tests: 24 backend (`test_portable_writer.py`,
`test_portable_plan_exclusions.py`, `test_portable_save.py`,
`test_portable_routes.py`) + 13 frontend (`portable.test.ts`,
`portable-panel.test.tsx`). Gates green: 1321 backend pytest
(1297 + 24), ruff clean, mypy 75 files, 550 frontend vitest
(537 + 13), tsc clean, prettier clean, vite build OK.

## M2.16 — Open portable projects (spec §18)

**Phase 1 (2026-10-17):** plan written
(`projectPlans/m2.16-plan.md`). Design: open a `.basseparate` archive
produced by M2.15 as a new working copy. Transfer reuses the bounded
chunked-upload mechanism with a second `UploadManager`
(`runtime/archive-uploads`) under a new dedicated cap
`max_project_archive_bytes` (default 160 GiB, not the 20 GiB media value —
a maximal project's asset set is ≈7.5× the source size, stored
uncompressed in the archive) plus `max_archive_uncompressed_bytes` and
`max_archive_member_count` safeguards. Routes: `POST /projects/open`
(session), chunk `PUT`, synchronous `complete` (threadpool, pure file I/O
+ DB — no jobs), `GET` state, `POST` cancel. `portable/open.py`:
validate-before-import per §18.2 (ZIP directory, limits, bounded 1 MiB
manifest, format/container version, path safety incl. symlink/encrypted/
directory rejection, member-set equality, per-member streamed SHA-256),
staged extraction to `data/portable/.import-staging/<uuid>/` (no
`extractall`), then untrusted-DB handling per §18.3 (read-only, no
extensions, `user_version` must equal the current schema version, explicit
column queries, domain-model validation, no SQL from the archive). ID
policy per §18.5: default new working copy (new project ID, every row gets
a new ID, all FK references + `record_json`-embedded IDs remapped via
domain objects; free-form JSON gets exact-UUID replacement);
`as-archived` only when the archived ID is free (else 409); archived
identity kept in new `projects.portable_provenance` JSON column
(migration 11, schema v11). Asset restoration per §18.4: content-addressed
dedupe by hash, `source_original` to a fresh `runtime/uploads/<id>.part`,
optional missing assets (playback-rate) drop their rows for on-demand
regeneration (§18.6), waveform caches restored or dropped for rebuild.
Single-transaction `ProjectRepository.import_portable_bundle` — the
project is exposed only after commit. §18.7 state restoration is carried by
the imported rows (working_state, practice_state, markers, result sets);
the project opens paused. Frontend: `api/open.ts` + `OpenProjectPanel.tsx`
(file picker + drag-and-drop, upload progress, opening state, inline
errors) in the project-list view.

**Phase 2 (2026-10-18):** config keys `max_project_archive_bytes`
(160 GiB), `max_archive_uncompressed_bytes` (160 GiB),
`max_archive_member_count` (10 000) with validation; migration 11 adds
`projects.portable_provenance`; `DATABASE_SCHEMA_VERSION` = 11; v10
test baselines updated.

**Phase 3 (2026-10-18):** `portable/errors.py` (error family),
`portable/bundle.py` (validated `PortableImportBundle`), and
`portable/open.py`: `_validate_archive` (ZIP directory, limits, 1 MiB
manifest, versions, safety incl. duplicate/symlink/encrypted/directory,
member-set equality, essential presence), `_extract_staged` (streamed
hash-verified partial + rename), `_read_database` (read-only URI,
`query_only`, extensions off, schema equality, required tables, domain
model validation, isolation proof), `plan_assets` / `build_bundle`
(content-addressed asset reuse, full FK + `record_json` remap, loop IDs
kept, provenance), `drop_absent_optional_assets` (§18.6 asset + cache
drops), `check_free_space`, `restore_asset_files` (hash dedupe,
collision rejects), and the orchestrator. Design correction found by
the round trip: assets are **global** rows (`content_hash` UNIQUE), so
new-copy reuses asset/representation/waveform-cache rows by content
hash instead of duplicating them; project-local rows keep fresh IDs.

**Phase 4 (2026-10-18):** `ProjectRepository.import_portable_bundle`
(single `BEGIN IMMEDIATE`, assets before the project row,
`PRAGMA foreign_key_check`, commit; rollback on any failure),
`get_assets_by_hashes` and `get_asset_metadata_ids` reuse lookups.
`tests/integration/test_portable_open.py`: 38 tests (round trip, dedupe,
as-archived/conflict, optional asset/cache drops, every validation
failure code, DB tampering, rollback). Seed fixture corrected to real
content hashes/byte counts so archives are content-addressed.

**Phase 5 (2026-10-18):** `api/open_routes.py`: `POST /projects/open`
(filename/size/open-mode validation, 413 over the archive cap, 507 on a
failed reservation), chunk `PUT` (import protocol, 404/400/409/413),
`GET` session state, synchronous `complete` (threadpool via
`run_in_threadpool`, no jobs; failure keeps the session and records the
last error, success removes it), idempotent `cancel`. `OpenSessionStore`
persists the client parameters beside the upload manifest
(`runtime/archive-uploads/<id>.open.json`; no DB rows). App wiring:
second `UploadManager` under the archive cap + router. Nine route
integration tests.

**Phase 6 (2026-10-18):** round-trip integration coverage: save with
M2.15 → open into a fresh store (ready, all asset/cache files verified,
working/practice state and markers restored, provenance recorded, new
project id), second open into the same store (assets, representations,
and waveform caches reused; only project-local rows duplicated),
as-archived (IDs kept; second open → 409 `OPEN_ID_CONFLICT`), damaged
essential → rejected with the member named and no store rows.

**Phase 7 (2026-10-18):** frontend `api/open.ts` (typed session/chunk/
complete/cancel client, progress, retries, friendly error mapping for the
archive codes) and `projects/OpenProjectPanel.tsx` (file picker +
drag-and-drop, upload progress, "Opening…" phase, inline errors, cancel,
`onOpened`), mounted in the project-list view beside "New project" (the
clean-install entry point); CSS; 16 tests. Contract regenerated
(`contracts/openapi.json` + `frontend/src/api/schema.ts`).

**Final gates (2026-10-18):** backend 1368 pytest green; ruff
`src/ tests/` clean; mypy 79 files clean; frontend 566 Vitest green;
tsc 0 errors; prettier clean; Vite build OK; contract in sync.

## M2.17 — Analysis interfaces and separation scheduling (spec §19)

**Phase 1 (2026-10-18):** plan written (`projectPlans/m2.17-plan.md`).
Design: dedicated analysis worker (`analysis/worker.py`, protocol v2,
launched with the analysis environment interpreter per §4.1.7) that
relays `analysis/separate.py` progress and cancellation; `JobManager`
gains a second (analysis) job class + lazily started supervisor so
separation never blocks playback preparation; `POST /projects/{id}/runs`
resolves the reference plan/device/cache key, coalesces live runs, serves
valid cache hits, else creates a queued run + separation job;
preparation (M2.4) runs in the dispatch hook; the M2.6 publisher
validates/publishes stems; `GET /hardware` wraps the M2.2 device
discovery/qualification store; `GET /models` + `POST /models/{id}/verify`
wrap the M2.3 registry/bundle verification (local hashing, no network);
`GET /projects/{id}/separation-results` aliases the result-set listing.
Migration 12 extends the `media_jobs` job-type/stage CHECK constraints
(`separation`, `preparing_input`, `separating`); schema v12.

**Phase 2 (2026-10-18):** `JobType.SEPARATION`, `JobStage.PREPARING_INPUT`
and `SEPARATING`; migration 12 rebuilds `media_jobs` (and
`export_artifacts`, whose FK SQLite rewrites on the parent rename) with
the new CHECK values; `DATABASE_SCHEMA_VERSION` = 12; v11 baselines
updated.

**Phase 3 (2026-10-18):** `analysis/worker.py`: protocol-v2 worker for
the isolated environment (stdlib only at startup), capabilities declare
`analysis.separation.v1`, `run` spawns `analysis/separate.py` through
the explicit interpreter, relays JSON-lines progress, writes the cancel
flag, and reports completed (attempt dir, labels, record) / cancelled /
failed. `analysis_worker_command()` + `analysis_root()` (env override);
10 protocol tests with a fake separator (no torch).

**Phase 4 (2026-10-18):** `JobManager` two-class scheduling: a media
queue/supervisor (eager, unchanged) and an analysis queue with a lazily
started supervisor stopped when idle; cancellation routes to the running
class; the analysis receive timeout is 900 s. Four tests: completion,
missing runtime (`ANALYSIS_RUNTIME_UNAVAILABLE`), cancellation, and a
media job completing while a slow separation runs.

**Phase 5 (2026-10-18):** `media/separation_request.py` (reference mix
§6.1, model identity, requested parameters, §9.1 cache key/transform
hash, device profile); app dispatch hook prepares the model input
(M2.4) into job staging and writes the profile; the separation
publisher calls the M2.6 `publish_separation_result` with the run,
project-rate reference, geometry, and cache key, and queues stem
waveforms. 14 planner/publisher tests.

**Phase 6 (2026-10-18):** `api/analysis_routes.py`: `POST
/projects/{id}/runs` (reference plan, device rules incl. explicit CPU,
cache key, live-run coalescing with stale-run healing, cached results,
queued run + job; failures never leave a live run without a job), `GET
/projects/{id}/separation-results` (spec-name alias), `GET /hardware`
(discovery + qualification store + default selection), `GET /models`
(registry + cheap bundle state + recorded verification + qualification),
`POST /models/{id}/verify` (local hash verification recorded under
`state/analysis/models.json`). `SeparationRepository.fail_run` and the
verification store. 13 route tests.

**Final gates (2026-10-18):** backend 1409 pytest green; ruff
`src/ tests/` clean (also `analysis/worker.py`); mypy 82 files clean;
frontend 566 Vitest green; tsc 0 errors; prettier clean; Vite build OK;
contract regenerated and in sync.

## M2.18 — Test matrix (spec §20)

**2026-10-18:** `docs/evidence/m2.18-test-matrix.md` maps every §20
requirement (model provisioning/integrity, separation correctness,
worker/device failures, mixer timing, stretching, loops, portable
projects, WAV export) to the automated tests and earlier evidence that
exercise it. Three gaps closed: the analysis runner's offline flags are
pinned **before** torch/model load and the protocol worker never imports
torch (`tests/unit/test_analysis_offline.py`, 2 tests); an ENOSPC during
stem publication leaves no result-set/stem/asset rows, keeps the run
unpublished and the staged stems for diagnostics
(`test_publication.py::test_disk_full_during_asset_move_leaves_no_rows`).
Real inference correctness, timing/VRAM/RAM, the five-recording workflow,
and the human listening review are M2.19–M2.21 evidence, not claimed
here. Final gates: backend 1412 pytest green (one flaky supervisor test
passes on rerun); ruff clean; mypy 82 files clean; frontend 566 Vitest
green; tsc/prettier/Vite build/contract unchanged and green.

## M2.19 — Real separation acceptance (initial CPU run, 2026-10-18)

**Superseded by later acceptance:** the five-recording GPU matrix passed
on 2026-10-18 (section below), and the app-level acceptance plus human
review passed on 2026-10-23 (M2.20-M2.21 sections). This section records
the first partial CPU run and what was open at that point.

**2026-10-18:** `docs/evidence/m2.19-separation-acceptance.md`. The
environment has no usable NVIDIA driver (`nvidia-smi` fails;
`torch.cuda.is_available()` false), so the GPU acceptance could not run.
A real offline CPU run on a 12 s stereo 44.1 kHz excerpt of
`audio2test/46.GIBBS - Simplicity.wav` completed: four stems, 529,200
frames, 78.1 s (RTF 6.51×), peak host RSS 2.04 GiB, bundle verified
locally, network flags set before torch. The five full recordings
(≈18.4 min audio, ≈2 h at the measured CPU RTF), GPU/VRAM measurements,
and the human listening review remain open and are not claimed.

## M2.20–M2.21 — Performance targets and final acceptance

**2026-10-18:** `docs/evidence/m2.20-performance-and-acceptance.md`.
Records the measured targets (CPU RTF 6.51×, peak RSS 2.04 GiB for the
M2.19 excerpt; earlier M2.9/M2.10/M2.12 playback and latency evidence),
the responsiveness architecture (event loop never blocked; cancellation
acknowledged immediately), and the §22 final checklist with explicit
**partial/not-verified/human-only** statuses. GPU performance, all five
recordings, the 60-minute playback run, and the listening review are not
claimed at that point. No functional work packages remain; the
milestone's automated surface is complete (backend 1412 pytest,
frontend 566 Vitest).

**2026-10-23 final update:** the human listening review passed all steps
6–10. The listener accepted loop boundary timing (step 7) and the in-app
stereo image (step 8); practice speeds, exports, and reopen repeat had
already passed. The final loop UX fix is `2e1c2f0` (loop overlay above
the selection, 2 px border, top-center grip, plain-drag top edge), with
the focused `WaveformEditor` suite at 59 passed and a clean production
build. M2.20–M2.21 is complete. Optional future work only: a seamless
loop join without the 5 ms fade notch. See
`docs/evidence/m2.21-listening-review.md` and
`docs/evidence/session-2026-10-23-handover.md`.

## M2.19 — GPU acceptance (five recordings)

**2026-10-18 (GPU run):** with approved escalated device access (the
sandbox hides `/dev/nvidia*`), `analysis/qualify.py --all` passed on both
GPUs and the CPU. All five `audio2test/` recordings then completed on the
RTX 4080 (`cuda:0`, local verified bundle, offline flags): 18.4 min of
audio in 4.4 min of inference, RTF 0.217–0.260, peak VRAM 4,087–4,260
MiB, peak host RSS 3.05–4.20 GiB, four stems each, one attempt each.
Recorded in `docs/evidence/m2.19-separation-acceptance.md`; the
performance checklist in `m2.20-performance-and-acceptance.md` is updated
(analysis rows done; 60-minute playback and listening review remain).
Note: `analysis/qualify.py` itself does not set the offline flags and
printed an HF request warning; the production runner is offline and used
the local bundle for every acceptance run.

## M2.19 — Acceptance update (full recording + backend end-to-end)

**2026-10-18 (continuation):** the complete 68.57 s `46.GIBBS` recording
ran on CPU: 351.5 s (RTF 5.13×), peak RSS 2.62 GiB, four stems,
3,024,001 frames. The real backend path was also exercised end to end
(HTTP run request → analysis worker → `separate.py` → M2.6 publication):
job completed in 42.4 s for a 5 s project, one valid result set, four
stems at the exact project frame count. This exposed and fixed a real
publisher bug: transient dispatch parameters are not persisted on the
job row, so the publisher now re-derives the reference mix, source
identity, geometry, and model rate from the run/project (regression test
added). Also added the §20.7.3 save-while-separation-queued test.
Final gates: backend suite green, ruff/mypy/frontend gates unchanged.

## M2.21 — Listening review setup (pause point)

**2026-10-18 (review updated):** Carousel Theory is the primary
acceptance recording. The listener judged the bass stem acceptable (not
perfect), the Others solo fine, the sum "about right", and the stereo
image good. Window joins: a click+dip at 2:07/08 (the step matches a
reference transient; likely source content) and a real level dip at
3:48/49 (50 ms sum/reference RMS 0.94–0.97 inside the 224–232 s blend
region). Other recordings were briefly judged acceptable. The blend dip
is a candidate DSP follow-up. A level-matched blend experiment (gains
0.998/0.995) left the dip unchanged, so the cause is content/phase
difference between independently inferred windows, not gain; the
experiment was reverted. **Decision: the ~3:49 dip is accepted as a
minor artifact; no DSP change.** Remaining: app-level listening checks
(0.5×/0.75×, loop, WAV export, save/reopen) and the 60-minute playback
measurement. The five GPU
acceptance runs' stems were converted to
24-bit 44.1 kHz WAVs under `/tmp/opencode/listening-review/<slug>/`
(`reference`, `drums`, `bass`, `other`, `vocals`, `others` =
drums+other+vocals, `bass_plus_others`), with a README and the §21.4
checklist in `docs/evidence/m2.21-listening-review.md`. The session
handover is `docs/evidence/session-2026-10-18-handover.md`. Work is
paused here for the human review; the 60-minute playback measurement
follows it.

## M2.21 — App-level acceptance (Carousel, 2026-10-22)

**Setup:** detached `basseparate serve --port 18796 --storage-root
storage/m2.21`; source `audio2test/Carousel Theory Full Mix V1 (With
Limiter).wav` (48 kHz, 2 ch, 113,071,396 bytes, SHA-256 `2bc81e32...`);
project 14,133,913 frames (294.4565 s); device store qualified
`GPU-0dab3af3-...` and `cpu`; separation device `cuda:0`.

**2026-10-23 (playback rerun):** the first 60-minute attempt completed
but failed its loop criterion: 81 resets, 80 intervals at ~5 s, from
the autosave `setRate` defect fixed in `b2e244c`. A corrected run then
reached seven full passes (~294.4 s each) before the app server was
shut down at 19:59 on 2026-10-22, 38.8 minutes in. On 2026-10-23 the
server was restarted with the preserved `storage/m2.21` storage
(project `923d1e34...`, result set `5299022f...`), the two diagnostic
loops were removed, and the final 60-minute run completed on 2026-10-23:
12 resets, 11 full periods of 293.88–294.91 s (mean 294.468 s vs
expected 294.4565 s), one startup underrun and none later, bounded
memory. The restart needs no GPU: the earlier separation result is
preserved and playback is CPU-side; the current environment's NVIDIA
driver is unavailable, so no new separation is attempted.

**Objective results:**

- Separation run `df241f20...`: 72.5 s, result set `aa637e45...`,
  validation `valid`, four stems at 48 kHz/2 ch/14,133,913 frames,
  adapter `outer-window-v1`, engine `demucs-4.1.0`.
- WAV24 export: four artifacts, 84,803,616 bytes each, SHA-256 headers
  match; four-stem sum vs reference: zero lag, corr 0.9927 at 30 s,
  RMS ratio 1.0008; all roles present.
- Portable save: 702,266,762 bytes, SHA-256 `a656172a...`, 380 members,
  no model/source paths. Reopened project `923d1e34...`: ready, 48 kHz,
  14,133,913 frames, one valid set `5299022f...`, stem frames match,
  archive hash matches.
- Whole-track loop `929a5978...`: 0..14,133,913 frames; it was enabled
  for the 60-minute run and is now saved inactive for the human loop
  test.
- 60-minute playback: final run `.m2.21-acceptance/play60-final/`
  (2026-10-23): 3,600.7 s, 119 samples, no errors; 12 resets; the first
  interval (285.36 s) is partial and starts at the 10 s probe; the 11
  full periods were 293.88–294.91 s, mean 294.468 s vs expected
  294.4565 s (1 s sampling). Terminal playhead 60.86 s; one startup
  underrun and none later. Backend RSS 65.9–79.8 MB; media worker
  51.5 → 8.3 MB (cache released after the initial asset fetch; no
  error); browser process tree 0.93–1.60 GB; JS heap 7.5–38.1 MB
  (GC sawtooth); DOM 813–821.

**2026-10-23 (human review):** steps 6, 9 and 10 passed: all practice
speeds through 1× were normal, the four exported stems were accepted,
and repeat playback after reopen was confirmed. The first step 7
attempt exposed the active-loop selection gesture: the whole-track
acceptance loop's body owned waveform drags, so selecting the chorus
moved/trimmed the loop and `Create from selection` stayed disabled. The
loop panel's looping checkbox is a separate switch; creating a loop
activates it but does not enable repetition. Fixed in `53d2e32`: plain
drags select, Alt+drag moves the loop body, the boundary handles still
resize, and the hint documents the gestures. The acceptance loop was
restored to 0..14,133,913 frames, saved inactive, and the project reset
to position 0. Step 8's response confirmed the `x1` speed reset, not the
stereo image; the in-app stereo image was still unconfirmed at that
point, before the final retest.

**2026-10-23 (step 7 overlay/drag retest).** The listener confirmed that
the audio loops, but reported no visible loop indication, no plain drag,
and a slight gap at the join. The active loop was 2,400,000–3,621,936
frames (50.0–75.456 s), while the live selection was 3,202,809–4,956,380
frames (66.7–103.258 s): the visible selection was not the loop, and the
loop overlay was drawn under the selection tint. Fixed in `2e1c2f0`:
selection is drawn first, the active loop last, with a 2 px border and a
20×4 px top-center grip; a plain drag on the loop's top 12 px band moves
the whole interval, the boundary handles resize, and Alt+drag on the
body still moves. The hint now reads "Drag selects; grip moves loop; L
toggles". Focused `WaveformEditor.test.tsx`: 59 passed; production build
passed. The current loop is not the selection, so the listener may drag
the existing loop or create a new one from the selection. The slight
join gap is the intended 5 ms boundary fade; `Fade` off gives an exact
join.

**2026-10-23 (final human acceptance):** step 7 passed: boundary timing
was good with `Fade` off. The listener also confirmed step 8's in-app
stereo image is good. With steps 6, 9 and 10 already passed, all human
steps 6–10 pass and M2.21 is complete. The loop UX fix is `2e1c2f0`;
the final wrap-up state and resume instructions are in
`docs/evidence/session-2026-10-23-handover.md`. Future improvement,
non-blocking: make the loop join seamless without the 5 ms fade notch.
The current test loop is 2,400,000–2,832,000 frames (50.0–59.0 s),
`Fade` off, active and looping; position 2,592,000 frames; selection
3,202,809–4,956,380 frames.

**Defects found and fixed during acceptance:**

1. 48 kHz stem endpoints: two-stage resampling left 1–2 trailing frames;
   publication now corrects at most 4 frames (2 per stage) and fails
   larger differences; identity restores stay exact (`42655c4`).
2. Duplicate content hashes: publishing the same stems into a second
   project inserted a new asset id that `INSERT OR IGNORE` skipped, then
   failed the `project_assets` foreign key; the publisher now reuses the
   stored asset id (`42655c4`, regression test).
3. A null export target rate was coerced instead of meaning keep-source
   (`094eeb7`, regression test).
4. The app's four-stem transport and stem lanes read a nonexistent
   `assetId` instead of `audioAssetId`, so playback fetched
   `/assets/undefined/bytes` and failed 422. Fixed in `10b183f`; this
   also restored a clean `tsc -b` build (open_mode, StemRole typing,
   canvas types, test mocks). The prior ledger's `npx tsc --noEmit`
   did not check the referenced app project; use `npx tsc -b`.
5. The 5 s playhead autosave replays the practice state, so `setRate(1.0)`
   ran every 5 s. It pushed a timing segment even for an unchanged rate
   and clamped the segment coordinate to the project frame count; once a
   looped stream passed that count, the playhead mapping jumped every
   5 s and a full-track loop could not sustain a pass. The first
   60-minute attempt completed but failed objectively with 81 resets
   (80 intervals at ~5.0 s). Fixed in `b2e244c`: unchanged rates are a
   no-op and real rate changes use the unbounded stream coordinate. A
   10 s end-of-track loop then wrapped correctly; the corrected partial
   run reached seven full passes, and the final 60-minute run validated
   the full track.
6. With a full-track loop active, its body drag owned the waveform
   pointer, so a listener trying to select a chorus moved/trimmed the
   loop and `Create from selection` stayed disabled. Fixed in `53d2e32`:
   plain drags select, Alt+drag moves the loop body, and the boundary
   handles still resize. The hint now reads "Drag selects; Alt-drag
   moves; L toggles". The acceptance loop is saved inactive at
   0..14,133,913 frames; the project is at position 0. Focused
   `WaveformEditor.test.tsx` regression: 58 passed.
7. The step 7 retest confirmed audio looping but exposed a visibility
   and drag problem. The active loop (50.0–75.456 s) differed from the
   live selection (66.7–103.258 s), and the loop overlay was drawn under
   the selection tint; the loop body had no plain-drag move. Fixed in
   `2e1c2f0`: loop on top of the selection, 2 px border, top-center grip
   plus a forgiving 12 px top-edge move band. Focused
   `WaveformEditor.test.tsx`: 59 passed; build passed. Final retest:
   step 7 passed; boundary timing accepted with `Fade` off.

**Human-only items:** all accepted by the listener on 2026-10-23:
practice speeds (step 6), exported stems (step 9), repeat playback after
reopen (step 10), loop boundary timing (step 7), and the in-app stereo
image (step 8). Objective timing/alignment does not attest perception;
these are the listener's own confirmations. Audible control-response
latency was not separately re-tested; the M2.10 objective latency/bypass
evidence stands.

## Milestone 3 progress

Specification: `projectPlans/milestone3.md` (work packages M3.1-M3.22;
section 25 gives the implementation order and gates). M3 requires an
explicit Beat This! model install (a deliberate network operation), and
GPU-dependent acceptance runs will need the NVIDIA driver restored.

### M3.1 — Verify prerequisites and extend the domain (complete)

Spec: `milestone3.md` §3. Plan: `projectPlans/m3.1-plan.md`. Domain,
schema, project/portable serialization, and contracts only. No model,
GPU, network, or analysis execution. Implementation commit `3d3c307`;
this ledger update is the follow-up commit.

- **Prerequisites (§3.1, 2026-10-24):** current full gates were green
  except the two known load-sensitive timing tests and the pre-existing
  `ruff format` drift (see Current position). The preserved Carousel
  acceptance project was inspected read-only: project
  `923d1e34-...` ready, 48 kHz, 14,133,913 frames; canonical PCM
  113,071,304 bytes (= frames × 2 channels × 4); four stems all
  14,133,913 frames, 48 kHz, stereo, alignment offset 0; one
  source-anchored loop 2,400,000-2,832,000 frames; portable provenance
  present; result set `5299022f-...` valid; five waveform caches.
  Playback/speed/loop/transport/portable/409/worker-coexistence
  evidence remains the M2 corpus plus the M2.20-M2.21 records; no new
  human playback run is needed for M3.1, and no metronome work starts
  until the transport baseline is trusted.
- **Domain (§3.2-§3.9):** `src/basseparate/domain/rhythm.py`:
  `MusicalPosition` (exact reduced rational, safe-integer bounds),
  `MusicalInterval`, all shared enums, `RhythmAnalysisRun`,
  `ActivationArrayRef`/`ActivationFrameMapping`/
  `ActivationArtifactManifest` (relative `.npy` paths, distinct arrays,
  length checks), `RhythmPulse`, `TempoAnchor`, `MeterHypothesis`,
  `MeterRegion` (grouping, derived primary-pulse starts, exact display
  tempo-unit compatibility), `BarOriginState`, and
  `RhythmBranchRecord` (unique ids, pulse parent/link checks, strictly
  increasing source and musical anchor positions, source bounds,
  ordered meter regions on whole-bar boundaries, valid-grid
  requirements). Limits bound every collection.
- **Project state (§3.10):** `MetronomeSettings`, `CountInSettings`,
  `SelectedRhythmObject`, `ProjectRhythmState` (active result/branch,
  Auto/Edited display, lane/ruler visibility, lane height, snap mode,
  metronome, count-in, last selection). `ProjectRecord.rhythm_state`
  is defaulted.
- **Schema (§3.11):** migration 12→13 creates `rhythm_analysis_runs`,
  `rhythm_activation_artifacts`, `rhythm_branches` (record JSON plus
  index columns) and `projects.rhythm_state`;
  `DATABASE_SCHEMA_VERSION` 13, `PROJECT_SCHEMA_VERSION` 5.
  `RhythmRepository` provides run/artifact/branch create, read, list,
  run status save, and optimistic branch save
  (`RhythmBranchStaleRevisionError`); `ProjectRepository`
  gains `set_rhythm_state`.
- **Portable schema (§3.11.3):** the three rhythm tables are copied as
  project-scoped rows and included in the isolation proof. Portable
  **open** of rhythm rows and the raw activation files are deferred to
  M3.18 (Gate G).
- **Tests (§3.11.4-§3.11.7):** `tests/unit/test_rhythm.py` (33),
  `tests/integration/test_rhythm_repository.py` (5),
  `tests/integration/test_migration_m3.py` (empty, imported, separated,
  looped, and portable-opened v12 fixtures; 2),
  `tests/unit/test_project.py` rhythm-state tests (3), and a portable
  rhythm-row copy test (1). Existing schema-version assertions now use
  the exported constants.
- **Gate (2026-10-24):** backend **1460 passed** (1416 baseline + 44
  new/updated); ruff check clean; mypy clean (83 files); contract in
  sync; frontend Vitest **569 passed**, `tsc -b --force` clean,
  `format:check` clean, production build OK.
- **Known boundaries:** a v12 portable archive cannot be opened by the
  v13 build (the embedded database must equal the current schema
  version); archive upgrades belong to M3.18. Automatic
  `RhythmResult` and its table arrive in M3.6, so the branch parent and
  project active-result IDs are unconstrained nullable UUIDs until
  then. Command/undo integration for rhythm state is M3.10.

### M3.2 — Integrate the Beat This! runtime and model registry (complete)

Spec: `milestone3.md` §4. Plan: `projectPlans/m3.2-plan.md`. Isolated
rhythm runtime, verified model registry, explicit install/offline-import
boundary, and CPU qualification. Implementation commit follows this
ledger update.

- **Runtime (§4.1):** `rhythm/` is a dedicated uv project with its own
  lockfile: Python 3.11.15, `beat-this==1.1.0`, torch/torchaudio
  2.9.1+cu128 from the same `pytorch-cu128` index as the Demucs
  environment (33 packages). The backend never imports torch or
  beat_this; `rhythm/qualify.py` is launched with the explicit
  interpreter and a local checkpoint path.
- **Registry (§4.2):** `src/basseparate/models/rhythm_registry.py` pins
  `beat_this_final0` (81,058,141 bytes, SHA-256 `8c328b45...`) and
  `beat_this_small0` (8,451,101 bytes, SHA-256 `6074be2c...`), upstream
  tag `v1.1.0`/commit `ad7974846029`, PyPI wheel SHA-256, preprocessing
  (22,050 Hz, hop 441, 128 mels), 50 fps logit semantics, adapter
  version, CPU/GPU capability, MIT code and weight notices, and
  training-data caveats. The server SHA-1 checksums were verified at
  download time.
- **Install boundary (§4.3):** `src/basseparate/models/install.py`
  (`ModelStore`, `install_from_download`, `install_from_bundle`,
  `InstalledModel`, typed errors). Online install refuses before network
  access while offline mode is active, streams to staging with byte
  progress, checks cancellation, verifies exact size and SHA-256, and
  publishes atomically with an `installed.json` provenance/license
  record. Offline import verifies bundle manifest identity and re-hashes
  the checkpoint during copy. No torch import in this module.
- **CLI + diagnostics (§4.7):** `basseparate models
  list|install|verify|import-bundle`; `doctor` gains an optional
  `rhythm-models` check that reports installed presets and never
  downloads.
- **Real acceptance (2026-10-24):** both presets were installed through
  the explicit boundary from the official CPJKU source (offline mode
  disabled only for the command), then qualified on CPU from an
  explicit local path with `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`
  set before torch import. Both passed: finite, deterministic, 251
  frames at 50.2 fps on the 5 s fixture; final0 load 0.357 s, first
  inference 0.216 s, two-run total 0.732 s, RTF 0.146, peak RSS 708
  MiB; small0 first inference 0.086 s, two-run total 0.194 s, RTF
  0.039, peak RSS 638 MiB. Offline bundle import into a second store
  and `models verify` both passed. Evidence:
  `docs/evidence/m3.2-beat-this-qualification.md`; reports in
  `storage/m3.2/data/models/beat_this_*/qualification-cpu.json`.
- **Tests:** `tests/unit/test_model_install.py` (14) covers registry
  validation, offline-mode rejection before network, successful
  install/provenance, hash and size mismatch cleanup, cancellation,
  network errors, tampered checkpoints, and bundle success/mismatch/
  missing cases.
- **Gate:** backend **1474 passed** (1460 M3.1 baseline + 14 new); ruff
  check clean; mypy clean (85 files); contract in sync; frontend
  unchanged from M3.1 (569 passed, tsc/format/build green).
- **Known boundaries:** GPU qualification was not performed (no loaded
  NVIDIA driver; CUDA capability recorded but not claimed). The durable
  download job/worker, API routes, and settings UI are M3.17; the CLI is
  the explicit install path until then. Rhythm inference, activation
  artifacts, and publication are M3.4. Installed checkpoints live under
  `data/models/<model_id>/` in the active storage root.

## Architectural decisions so far

- Python 3.11.15 via uv, `>=3.11,<3.12`, Hatchling, src layout, console
  script `basseparate`.
- pnpm is installed in the user prefix; `package.json` pins 12.8.1
  (no corepack on the system). On 2026-10-24 the installed pnpm was
  12.15.0 at `~/.local/share/pnpm/bin/pnpm`, and the pinned-engine
  switch failed in this sandbox (read-only store); frontend commands use
  the existing `frontend/node_modules`.
- Inference runs only in the isolated `analysis/.venv` (torch, demucs);
  the application environment never imports torch.
- Git is a development aid only; generated-artifact checks must work
  without it (filesystem comparison).
- App storage via platformdirs (XDG), overridable with `--storage-root`.
- Project time is integer source sample frames; model rates, playback
  rates, and stream positions are derived coordinates.
- Audio assets are content-addressed (`data/assets/<sha256>.pcm`) with a
  transformation key; waveform pyramids are cached per source hash.

## Commands run / results

Milestone 0 setup (2026-09-29):

| Command | Result |
|---|---|
| `sha256sum audio2test/*.wav` | 5 hashes recorded in baseline report |
| `uv python list --only-installed` | 3.14.7 (system), 3.13.14, 3.11.15 (uv) |
| `nvidia-smi -L` | 2 GPUs listed at setup time (driver unavailable on 2026-10-24) |
| `git init -b main` | OK |

Current gates (2026-10-24): see the table in "Current position". All
listed commands were run from `/home/thomas/Documents/basseparate`.

## Known failures / blockers

- No functional blockers. Two timing-sensitive pytest integration tests
  fail intermittently under full-suite load and pass in isolation:
  `tests/integration/test_analysis_job_manager.py::TestAnalysisJobClass::test_separation_completes_on_the_analysis_worker`
  and
  `tests/integration/test_job_manager.py::TestProbeCompletion::test_probe_job_completes_and_publishes`.
- `npm run lint` reports 131 pre-existing errors (mostly
  `@typescript-eslint/no-this-alias` in older test harnesses) plus one
  warning; no gate depends on it.
- `ruff format --check src/ tests/` reports 90 of 170 files would be
  reformatted (locked ruff 0.16.9). This is pre-existing formatting drift,
  not a lint failure; `scripts/dev.py check` runs this command, so that
  aggregate check is red until the tree is reformatted in a dedicated
  change. `ruff check` and `mypy` are clean.
- The NVIDIA driver is unavailable on this host (`nvidia-smi` fails), so
  GPU separation cannot be re-run here; the accepted results are
  preserved and playback is CPU-side.
- The workspace moved on 2026-10-24; the venv editable install and stale
  bytecode caches were repaired (see "Current position"). For a fresh
  checkout, run `uv sync --locked` instead of reusing a moved `.venv`.
