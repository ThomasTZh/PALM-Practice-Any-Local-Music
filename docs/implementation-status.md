# basseparate — implementation status ledger

Persistent resume point. A fresh agent must be able to continue from this file
plus the repository state. Keep it concise; put long evidence in `docs/evidence/`.

## Current position

- **Milestone:** 2 (Bass practice workflow)
- **Gate:** Milestone 1 exit complete — all of M1.1–M1.16 committed; §18
  test corpus green (748 py + 307 frontend); contract in sync.
- **Work package:** M2.1 (Confirm prerequisites and extend the domain) —
  **complete** (800 py + 307 frontend green; `ba0b151`).
- **M2.2:** complete — `42d8726` (842 py + 307 frontend green; all 3
  devices qualified in the locked analysis env).
- **M2.3:** complete — `cd2ca9e` (hash-pinned `htdemucs_ft` baseline;
  registry + bundle service + offline qualification; 884 py green).
- **M2.4:** complete — `ebd58aa` (reference-mix resolution, one-shot
  resample to the model rate, prepared-input identity, versioned global
  normalization profile; 936 py green).
- **Current work package:** M2.5 (Windowed inference adapter) — not
  started.
- **Last commit:** `ebd58aa` — M2.4 (prepare separation input
  consistently); `cd2ca9e` — M2.3 (pin and provision the bundled Demucs
  baseline); `42d8726` — M2.2 (isolated Demucs runtime); `ba0b151`
  — M2.1 (confirm prerequisites and extend the domain); `9510656` (ledger
  M1.16 hash); `af51265` — M1.16 (test
  corpus and automated verification); `ede3d26` — M1.15 (markers, persistence, and
  undo/redo); `934d6c1` — M1.14 (synchronized readout and
  follow-playhead); `c7d78ef` — M1.13 (buffering and browser
  compatibility); `bccd7b5` — M1.12 (AudioWorklet transport);
  `fd3468f` — M1.11 (navigation, zoom, selection);
  `62513ce` — M1.10 (waveform editor);
  `ffa0142` — chore: prettier normalization of pre-existing sources
  (baseline was not prettier-clean);
  `72cd2e5` — M1.9 ledger hash;
  `06c2cb3` — M1.9 (media HTTP interfaces);
  `fe2b815` — M1.8 ledger hash;
  `4a6004a` — M1.8 (waveform pyramid);
  `825e884` — M1.7 ledger hash;
  `af6ad7f` — M1.7 (monitoring + playback rate);
  `4098c58` — M1.6 (disk budget + acceptance tests);
  `ae11417` — M1.6 ledger hash; `d5be576` — M1.4 (durable media jobs).
- **Next action:** M2.4 (Prepare separation input consistently) —
  reference-mix resolution (canonical stereo/mono PCM, explicit M1 stereo
  downmix for multichannel), single whole-file resample to the model rate,
  channel-layout conversion, transform identity + source-time mapping.
  Spec: `projectPlans/milestone2.md` §6. Milestone 1 remains fully
  committed; its only deferred items are the out-of-scope §19 manual
  acceptance and looping.

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
`projectPlans/m1.10-plan.md` (written, uncommitted with the plan
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

**Phase 5 (complete this session, uncommitted):**
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
- Note: `ruff check scripts/` has 2 pre-existing findings from
  M0.10/M0.11 (RET504 in `dev.py`, F541 in `generate_licenses.py`);
  unchanged by M1.7, left for a later cleanup.

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

### M1.4 — Durable media jobs (complete)

**Research notes (FFmpeg 8.1.2 experiments, /tmp/opencode/gaptest):**
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
