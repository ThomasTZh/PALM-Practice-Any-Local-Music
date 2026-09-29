# Milestone 8 — Browser validation and release: detailed implementation specification

This expands **Milestone 8 — Browser validation and release** in Section 13 of `basseparate_project_plan.md`.

It builds on `milestone0.md` through `milestone7.md`. Those documents remain authoritative for the application architecture, media pipeline, waveform editor, source-time transport, separation, practice playback, musical grid, harmony, bass transcription, persistent history, exports, cache/storage management, model management, YouTube retrieval, and Analyze All orchestration. Milestone 8 is the release-qualification layer over those systems; it must not replace them with release-only implementations.

The main-plan Milestone 8 contains 16 required outcomes:

1. Test Chromium and Firefox on Nobara.
2. Test automated WebKit behavior.
3. Test actual Safari on macOS.
4. Validate user-gesture audio startup.
5. Validate WebAssembly and buffer fallback.
6. Test browser refresh/reconnection.
7. Test long tracks and large projects.
8. Test offline operation.
9. Test GPU failure and CPU fallback selection.
10. Produce a Linux launcher and desktop entry.
11. Package local frontend assets.
12. Provide offline model-import instructions.
13. Document model and cache locations.
14. Provide backup/recovery instructions.
15. Complete all feature acceptance cases.
16. Publish a versioned build and license inventory.

Safari validation remains a separate release gate. Automated WebKit coverage is necessary but is not evidence that actual Safari audio, AudioWorklet, WebAssembly, autoplay/user-gesture, or output-timing behavior is correct.

---

## 1. Required outcome and milestone boundary

### 1.1 Complete release outcome

At completion, basseparate must have a versioned release candidate and final release package that can be installed and started on the target Nobara Linux PC without a source checkout, Node, pnpm, Emscripten, or developer tooling on the runtime PATH.

A qualified release must demonstrate that the complete Milestone 0–7 workflow works as one application:

1. Install/start the application.
2. Open the local browser UI from the Linux launcher.
3. Create/open projects.
4. Import local media.
5. Import a supported single YouTube video when online and explicitly requested.
6. Render long waveforms with bounded browser memory.
7. Play original and separated audio.
8. Use bass-pair, four-stem, and six-stem projects where the relevant model/result exists.
9. Change gain/mute/solo/pan safely.
10. Slow or accelerate playback with pitch preserved.
11. Use source and musical loops.
12. Use snippet queues.
13. Run rhythm, chord/key, bass-transcription, and separation analyses individually.
14. Run Analyze All using the existing dependency graph.
15. Inspect Auto/Edited/model-version results and staleness.
16. Correct rhythm, harmony, key, notes, loops, markers, and other editable state.
17. Undo and redo after restart.
18. Export audio and analysis artifacts.
19. Save/open `.basseparate` portable projects.
20. Reopen existing projects without model execution or network access.
21. Recover committed work after an interrupted session.
22. Inspect model, cache, project, and storage state.
23. Diagnose missing GPU/model/runtime conditions without corrupting project data.
24. Shut down without leaving app-owned workers running.

### 1.2 Included work

Milestone 8 includes:

- release-branch/freeze procedure;
- release build identity and manifest;
- Chromium qualification on Nobara;
- Firefox qualification on Nobara;
- Playwright WebKit qualification;
- actual Safari qualification on macOS;
- browser capability and fallback matrix;
- user-gesture and AudioContext lifecycle tests;
- AudioWorklet/WebAssembly SIMD/scalar validation;
- SharedArrayBuffer and transferable-buffer validation;
- refresh/reconnect tests for editing, jobs, downloads, retrievals, and pipeline runs;
- long-track and large-project stress tests;
- browser-memory/resource regression tests;
- offline/no-egress tests;
- GPU-loss and CPU-selection tests;
- audio-device-loss tests;
- production Linux bundle;
- production launcher and desktop entry;
- production static-asset packaging;
- release runtime qualification and dependency checks;
- offline model-import instructions and test procedure;
- storage/model/cache documentation;
- backup/recovery documentation and verification;
- full feature-acceptance sweep;
- migration/reopen sweep across historical project fixtures;
- clean-machine installation tests;
- release license/model/runtime inventory;
- reproducibility evidence and artifact hashing;
- final release notes and known-limitations record.

### 1.3 Explicitly out of scope

Milestone 8 must not add another product feature milestone merely because a release test exposes a missing feature.

The following are not release-scope additions:

- new separation architectures beyond the registered Milestone 7 set;
- new chord, rhythm, key, or pitch models;
- a new desktop webview/Electron/Tauri application shell;
- automatic cloud synchronization;
- telemetry or analytics;
- automatic background model downloads;
- automatic project upload;
- a network-exposed backend;
- playlist YouTube download;
- browser-cookie extraction for YouTube;
- DRM/access-control bypass;
- hidden extractor/model/runtime updates;
- a new command/history implementation;
- a new cache system;
- a second export system;
- replacing the local browser architecture with an embedded browser;
- automatic software updating in the first release unless separately designed and approved later.

If a release test finds a defect in a Milestone 0–7 feature, fix the owning implementation while preserving its existing contracts. Do not add a release-specific fork.

### 1.4 Release-blocking inherited guarantees

The following inherited requirements are release blockers:

1. Backend remains bound to loopback.
2. Browser/API session protection remains enforced.
3. Runtime fonts, scripts, icons, and WASM are local.
4. Normal startup makes no external requests.
5. Project open never contacts model or YouTube servers automatically.
6. Offline mode disables explicit network workflows rather than degrading into repeated failed requests.
7. Model inference never downloads weights implicitly.
8. Projects reopen without model execution.
9. Browser playback uses bounded PCM buffering.
10. Long six-stem playback remains bounded.
11. Source/stem timing remains coherent at every supported speed.
12. Metronome uses the audio render clock.
13. Committed edits survive crash/restart.
14. Persistent undo/redo survives restart.
15. Automatic analysis versions remain immutable.
16. Manual branches remain attached to their intended parent result.
17. Stale results remain explicit and are never silently retargeted.
18. Missing optional caches are rebuildable without corrupting projects.
19. Portable save/open verifies archive integrity and asset hashes.
20. Model, cache, project, and export storage accounting remain distinct.
21. Export jobs use a fixed project revision/result selection.
22. License/provenance records remain separate for source code, runtime components, and model weights/checkpoints.
23. Every failure states what failed, what remains usable, whether retry is possible, and the action needed to resolve it.

### 1.5 Definition of completion

Milestone 8 is complete only when all release gates in Section 55 pass.

In particular:

- Playwright WebKit does not substitute for Safari.
- A source-tree launch does not substitute for the packaged release.
- a developer machine does not substitute for a clean runtime installation test;
- an online test does not substitute for blocked-egress/offline validation;
- a short project does not substitute for long-track/large-project validation;
- a GPU-present test does not substitute for GPU-loss/CPU-selection validation;
- a successful build does not substitute for a license/provenance inventory;
- a portable-project test does not substitute for working-storage crash recovery;
- one happy-path project does not substitute for the complete feature acceptance matrix.

---

## 2. Fixed implementation decisions for Milestone 8

| Area | Milestone 8 decision |
|---|---|
| Primary release OS | Nobara Linux 44/x86-64 target first |
| Linux browsers | Current qualified Chromium and Firefox builds available at release qualification time |
| Automated cross-engine browser | Playwright Chromium, Firefox, and WebKit |
| Safari | Actual Safari on actual macOS hardware; separate release gate |
| Backend exposure | Loopback only; no LAN mode added |
| Runtime UI assets | Fully local and bundled |
| Release format | Relocatable Linux application bundle + explicit desktop integration script |
| Sandboxed package formats | Not required for first release; evaluate later only if they preserve GPU/runtime/storage behavior |
| Core runtime | Bundled/pinned Python 3.11-compatible core runtime or equivalently self-contained release runtime; no dependency on system Python 3.14 |
| Model weights | Pinned Demucs `htdemucs_ft` baseline is bundled in the personal base release after hash/license/provenance verification; other model weights remain separately installed/imported |
| Analysis runtimes | Explicit managed runtime packs/environments, versioned separately from weights where needed |
| FFmpeg | Exact runtime strategy recorded and qualified; if bundled, its build/license is inventoried; if external, startup diagnostics must prove suitability |
| WASM | Bundle scalar + SIMD Signalsmith artifacts; capability-detect at runtime |
| Audio buffer fast path | SharedArrayBuffer ring buffer when cross-origin isolation succeeds |
| Audio buffer fallback | Transferable bounded buffers; always tested even when shared memory is available |
| Offline | Network egress blocked in qualification harness; normal local workflows must remain functional |
| Release version | SemVer release candidate `X.Y.Z-rc.N`, then `X.Y.Z`; exact version chosen at release cut |
| Release provenance | Machine-readable release manifest plus human-readable notices/release notes |
| Reproducibility | Lockfiles, runtime fingerprints, frontend/WASM hashes, model registry hashes, and release artifact hashes recorded |
| Auto update | None in first release; updates are explicit/manual |

### 2.1 Why the first Linux release is a relocatable bundle

The first release should use a transparent directory-based bundle (for example a compressed `tar.zst` release artifact) with an install/integration script rather than introducing a new application-container technology.

Reasons:

1. The project already uses multiple isolated Python analysis environments.
2. NVIDIA GPU/CUDA/PyTorch qualification must remain observable.
3. FFmpeg/yt-dlp/JS runtime diagnostics must remain transparent.
4. Optional/challenger model storage can be large and remains separate from the core application; the specifically pinned Demucs baseline is an intentional bundled exception for this personal release.
5. Project/cache/model storage follows XDG paths and should not be hidden behind a sandbox-specific filesystem abstraction.
6. The browser remains the UI; there is no need to add an embedded webview.
7. A directory bundle can be inspected, hashed, backed up, and removed predictably.
8. Desktop integration can still provide a normal launcher and icon.

This decision does not prohibit AppImage, Flatpak, RPM, or other packaging later. Those formats require a separate compatibility/maintenance evaluation and are not required to satisfy the current milestone.

### 2.2 Base release versus optional runtime/model content

Keep three layers distinct:

1. **Base application release**
   - launcher;
   - backend/core runtime;
   - frontend assets;
   - schemas/contracts;
   - Signalsmith WASM;
   - core documentation;
   - license/notices files;
   - model registry metadata;
   - the exact verified bundled Demucs `htdemucs_ft` baseline artifacts and notices;
   - diagnostic utilities.

2. **Analysis runtime packs/environments**
   - exact worker interpreter/dependency environment required by each adapter family;
   - versioned and qualified;
   - may be installed/provisioned explicitly;
   - contain no project audio;
   - contain no hidden remote-code hooks.

3. **Additional model/checkpoint artifacts**
   - excludes the pinned Demucs baseline already carried by the base application release;
   - installed explicitly or imported offline;
   - hash verified;
   - stored in managed model storage;
   - not ordinary cache;
   - not part of the portable `.basseparate` project;
   - not bundled into the base application release unless a later explicit personal-release decision records license/provenance and updates the release manifest.

### 2.3 Release evidence is immutable

For each candidate/final build, create one release-evidence directory containing:

- application version;
- source revision/commit when available;
- build timestamp;
- build host summary;
- Python runtime identity;
- Node/pnpm build identity;
- frontend asset hashes;
- WASM hashes;
- backend wheel/package hashes;
- release archive hash;
- dependency/license inventory;
- model registry snapshot;
- browser qualification matrix;
- GPU/runtime qualification matrix;
- acceptance-test report;
- known limitations;
- migration fixture results;
- offline network-observation result;
- Safari qualification result;
- clean-install result.

Do not overwrite evidence from an earlier release candidate.

---

## 3. Work package M8.1 — Freeze the release baseline

### 3.1 Release-candidate branch/state

Before browser/release qualification:

1. Choose a release-candidate application version.
2. Record the source revision or filesystem snapshot identity.
3. Freeze dependency lockfiles for the candidate.
4. Freeze frontend lockfile.
5. Freeze WASM/Signalsmith/Emscripten identity.
6. Freeze model registry entries and named presets.
7. Freeze worker runtime environment fingerprints.
8. Freeze database/project/archive schema versions.
9. Freeze API and worker-protocol versions.
10. Freeze export preset definitions.
11. Freeze benchmark corpus manifest used for model-preset claims.
12. Record outstanding known issues.

No dependency update, model-alias retarget, or schema change may occur during qualification without creating a new release candidate.

### 3.2 Prerequisite audit

Run all Milestone 0–7 gate suites.

Verify at minimum:

- foundation startup/shutdown;
- local import;
- waveform/playback;
- separation/mixer;
- stretch/loops;
- musical grid/metronome/count-in;
- chords/key;
- bass transcription;
- persistent undo/redo;
- stale-result graph;
- snippet queues;
- audio/analysis export;
- portable save/open;
- model manager;
- SCNet/RoFormer/six-stem flows;
- YouTube retrieval;
- Analyze All;
- crash recovery;
- migration fixtures;
- cache cleanup.

Any failing prerequisite blocks release qualification until fixed.

### 3.3 Baseline hardware record

Record the release target machine:

- OS and kernel;
- CPU;
- RAM;
- storage/free space;
- GPU names and UUIDs;
- VRAM;
- driver version;
- browser versions;
- audio output device and sample rates used during testing.

Do not use unstable CUDA device indices as release evidence.

**Acceptance:** one immutable candidate identity exists and all earlier milestone suites are green or explicitly blocked by a documented environment prerequisite.

---

## 4. Work package M8.2 — Build the release manifest and provenance format

### 4.1 `release-manifest.json`

Create a machine-readable release manifest containing:

- application version;
- build ID;
- source revision/snapshot ID;
- build timestamp;
- target OS/architecture;
- minimum/qualified runtime assumptions;
- core Python identity;
- backend package version/hash;
- frontend build hash;
- frontend asset manifest hash;
- WASM scalar hash;
- WASM SIMD hash;
- FFmpeg strategy and version/build hash if bundled;
- yt-dlp/JS runtime strategy and versions if included/provisioned;
- API version;
- DB schema version;
- project schema version;
- archive schema version;
- worker protocol versions;
- model registry snapshot hash;
- bundled Demucs manifest/artifact hashes and bundle-relative locations;
- license inventory hash;
- third-party notices hash;
- release archive hash recorded after final packaging;
- qualification report ID.

### 4.2 Human-readable build information

Expose from `basseparate version` and the UI About/Diagnostics page:

- application version;
- build ID;
- platform;
- core runtime version;
- frontend build ID;
- major schema versions;
- whether this is a release candidate or final build.

Do not expose session tokens, user file paths, or secrets.

### 4.3 Immutable model provenance

Ship the registry metadata needed to explain historical project model IDs even when those models are not installed.

A release must be able to display:

- model ID;
- checkpoint/config identity;
- expected hashes;
- adapter/runtime requirement;
- published license/provenance information;
- whether it is installed/qualified locally.

**Acceptance:** every release binary/archive can be tied to one manifest and one exact dependency/model-registry snapshot.

---

## 5. Work package M8.3 — Define the browser qualification matrix

### 5.1 Browser classes

Create a matrix with four release classes:

1. **Chromium on Nobara — required.**
2. **Firefox on Nobara — required.**
3. **Playwright WebKit — required automated compatibility signal.**
4. **Safari on macOS — required manual/integration release gate.**

### 5.2 Version recording

Do not hard-code browser versions in the design document.

At qualification time record:

- browser product/version;
- browser engine version where visible;
- OS version;
- Playwright version;
- test date;
- audio sample rate;
- relevant capability flags.

### 5.3 Capability matrix

Record for each browser:

- AudioContext creation;
- AudioWorklet;
- `getOutputTimestamp()` availability/behavior;
- WebAssembly;
- WebAssembly SIMD;
- SharedArrayBuffer;
- cross-origin isolation;
- transferable ArrayBuffer fallback;
- file input/drag-and-drop;
- WebSocket reconnect;
- Indexed/session storage behavior used by the frontend;
- pointer/wheel/keyboard interactions;
- full-screen/high-DPI canvas behavior;
- download behavior for exports;
- page visibility/suspension behavior.

A browser may pass using a documented fallback. Passing does not require every optional fast-path capability.

### 5.4 Required workflow matrix

Each required browser must exercise:

- launch/bootstrap;
- project open;
- local import;
- waveform navigation;
- original playback;
- multi-stem playback;
- pitch-preserving speed;
- loop;
- metronome/count-in;
- annotation editing;
- undo/redo;
- result selection;
- model-manager view;
- job progress view;
- export download;
- refresh/reconnect;
- portable save/open where browser download/upload is involved.

**Acceptance:** one browser matrix exists before qualification begins; tests are not improvised per browser.

---

## 6. Work package M8.4 — Qualify Chromium on Nobara

### 6.1 Automated suite

Run Playwright Chromium against the packaged backend/runtime, not the Vite development server.

Include:

1. bootstrap token removal;
2. local authenticated API access;
3. CSP/local-resource checks;
4. cross-origin isolation headers;
5. file import;
6. waveform rendering;
7. sample-level zoom;
8. playback start after gesture;
9. pause/seek/restart;
10. AudioWorklet initialization;
11. SharedArrayBuffer path where available;
12. transferable fallback forced by test configuration;
13. scalar/SIMD WASM selection;
14. stem mixing;
15. time stretching;
16. loops;
17. metronome/count-in;
18. editing and undo/redo;
19. refresh/reconnect;
20. export download;
21. session expiry/rebootstrap after backend restart.

### 6.2 Manual audio pass

Automated browser tests cannot prove subjective audio continuity.

Perform a manual pass for:

- click-free start/stop where designed;
- stable loops;
- pitch preservation at 0.5×, 0.75×, 1.25×, and 2×;
- no relative stem drift;
- metronome phase;
- mute/solo/gain responsiveness;
- six-stem playback;
- audio-device resume behavior.

### 6.3 Resource pass

Measure:

- JS heap/renderer memory;
- browser process memory;
- CPU during waveform scrolling;
- CPU during 1× and stretched playback;
- underrun count;
- audio callback timing diagnostics;
- tile cache size;
- retained PCM buffer size.

**Acceptance:** Chromium passes all required workflows on the release package with no release-blocking defect.

---

## 7. Work package M8.5 — Qualify Firefox on Nobara

Use the same functional matrix as Chromium.

### 7.1 Firefox-specific attention

Test specifically:

1. AudioContext user-gesture requirements.
2. AudioWorklet module loading under production CSP.
3. cross-origin isolation headers.
4. SharedArrayBuffer availability.
5. forced transferable fallback.
6. WASM SIMD capability detection.
7. output-timestamp fallback behavior if API behavior differs.
8. high-DPI canvas sizing.
9. wheel/pointer modifiers for zoom/pan.
10. browser download handling.
11. tab suspension/background behavior.
12. refresh/reconnection with an active backend job.

### 7.2 No browser-specific semantic state

Any Firefox workaround must remain inside browser capability/transport/render layers.

Do not fork:

- project schemas;
- edit semantics;
- analysis result semantics;
- source timing;
- export behavior.

**Acceptance:** Firefox executes the same project data and produces equivalent semantic results, using fallbacks where required.

---

## 8. Work package M8.6 — Automated WebKit qualification

### 8.1 Purpose

Playwright WebKit provides automated detection of many Safari/WebKit compatibility problems before access to actual Safari hardware.

It does not satisfy the Safari release gate.

### 8.2 Automated cases

Run at minimum:

- application bootstrap;
- session authentication;
- static asset loading;
- CSP;
- project create/open;
- import UI;
- waveform rendering;
- editing;
- keyboard navigation;
- undo/redo;
- refresh/reconnect;
- export UI;
- capability detection;
- user-gesture AudioContext test where supported by automation;
- AudioWorklet module creation;
- scalar WASM;
- SIMD capability branch;
- transferable buffer fallback;
- SharedArrayBuffer branch only if the test environment supports it.

### 8.3 Automated limitations record

Record anything Playwright WebKit cannot establish reliably, including:

- actual macOS audio-output behavior;
- Safari power/background policies;
- Safari-specific autoplay restrictions;
- hardware/device output timestamp behavior;
- Safari-specific download prompts;
- browser-extension/security-product interference.

**Acceptance:** automated WebKit suite passes or leaves only explicitly listed actual-Safari-only checks.

---

## 9. Work package M8.7 — Qualify actual Safari on macOS

### 9.1 Separate gate

A release candidate cannot become final until actual Safari is tested on macOS.

The currently inspected environment has no Mac. Therefore implementation may prepare the qualification procedure, fixtures, and portable test package, but this gate remains **blocked** until real macOS hardware is available.

Do not mark Safari accepted from Playwright WebKit alone.

### 9.2 Safari qualification package

Prepare a Mac test kit containing:

- release candidate build/source instructions sufficient to run the local backend on macOS for browser qualification;
- test project fixtures;
- a compact source file;
- a stem project;
- a rhythm/harmony/transcription project;
- browser test checklist;
- audio listening checklist;
- expected hashes;
- diagnostics collection instructions.

Milestone 8 does not require a polished macOS installer unless separately scoped. Safari browser correctness is the required result.

### 9.3 Actual Safari tests

Test:

1. launcher/manual backend start and local origin open;
2. bootstrap token behavior;
3. user-gesture AudioContext start;
4. AudioWorklet loading;
5. scalar WASM;
6. SIMD if Safari reports support;
7. SharedArrayBuffer path if cross-origin isolation permits;
8. transferable buffer fallback regardless;
9. original playback;
10. multi-stem playback;
11. time stretch;
12. loop wrapping;
13. metronome/count-in;
14. seek during playback;
15. rate change during playback;
16. tab background/foreground;
17. page refresh;
18. backend reconnect;
19. output-device/sample-rate behavior available on the test system;
20. export download;
21. portable project open/save through browser file selection;
22. long-enough playback to detect drift or buffer instability.

### 9.4 Safari defect policy

Classify:

- release blocking;
- fallback required;
- cosmetic;
- unsupported optional fast path.

A Safari-only fast-path failure is acceptable only if the documented fallback passes and all user-visible correctness requirements remain satisfied.

**Acceptance:** actual Safari passes the required audio, editing, refresh, and export workflows on macOS, or the release remains blocked.

---

## 10. Work package M8.8 — Validate user-gesture audio startup and lifecycle

### 10.1 Fresh page

For each browser:

1. Load a project without starting AudioContext automatically where prohibited.
2. Show a clear “Start audio”/Play-enabled state.
3. Start/resume AudioContext from the first valid user gesture.
4. Initialize worklet/WASM outside the real-time callback.
5. Begin playback only after the context is running.
6. Do not interpret browser suspension as project corruption.

### 10.2 Reload

After page reload:

- project state may restore;
- session token may restore within the same backend session;
- audio playback must remain stopped until browser rules permit restart;
- previous desired playback must not cause hidden sound without user action;
- transport source position must remain coherent.

### 10.3 Suspension/background

Test:

- tab backgrounding;
- laptop/display idle if practical;
- AudioContext suspension;
- foreground return;
- manual resume gesture if required;
- playhead freeze while no source frames are consumed.

### 10.4 Device loss/recreation

When AudioContext closes/fails:

1. capture last acknowledged source position;
2. recreate only through permitted user interaction;
3. re-read output sample rate;
4. resolve/reuse playback representation;
5. refill bounded buffers;
6. resume only if the user still intends playback.

**Acceptance:** no browser begins unintended playback, loses the authoritative source position, or advances the visual playhead over unheard audio.

---

## 11. Work package M8.9 — Validate WebAssembly variants and failure handling

### 11.1 Packaged artifacts

Ship and hash:

- scalar Signalsmith WASM;
- SIMD Signalsmith WASM;
- JS/TypeScript loader glue required at runtime.

No runtime compiler is required.

### 11.2 Capability detection

At runtime:

1. test SIMD capability without crashing unsupported browsers;
2. select SIMD when qualified;
3. otherwise load scalar;
4. record the active variant in diagnostics;
5. keep output semantics identical.

### 11.3 Forced-path testing

Provide test-only switches to force:

- scalar;
- SIMD where supported;
- WASM load failure;
- stretcher initialization failure.

The test switch must not become a normal user-facing unsupported mode.

### 11.4 Failure behavior

If both runtime WASM variants fail:

- exact 1× playback may remain available through the non-stretched path if valid;
- variable-speed playback must be marked unavailable;
- project editing/export/analysis remain usable where independent;
- error explains that the time-stretch component failed;
- do not silently change playback speed semantics.

**Acceptance:** scalar and SIMD variants are both independently exercised; unsupported SIMD falls back cleanly rather than breaking playback.

---

## 12. Work package M8.10 — Validate SharedArrayBuffer and transferable-buffer fallback

### 12.1 Shared-memory path

Verify production headers enable cross-origin isolation where intended.

Test:

- ring-buffer creation;
- atomic producer/consumer indices;
- seek generation reset;
- EOF;
- underrun handling;
- loop wrap;
- six-stem source demand;
- variable speed;
- long playback.

### 12.2 Forced fallback

Disable SharedArrayBuffer/cross-origin isolation in the test harness and run the complete playback suite through transferable bounded buffers.

Verify:

- same project/source positions;
- same loop boundaries;
- same EOF behavior;
- same rate range;
- no stale chunks after seek;
- bounded queued-buffer count;
- acknowledgements/recycling work;
- no memory growth from unreturned transfer buffers.

### 12.3 Fallback is a release requirement

Do not classify the transferable-buffer path as “untested legacy fallback.” It is a supported compatibility path and must pass release tests even on browsers where shared memory normally works.

**Acceptance:** both buffer paths pass correctness and long-playback tests.

---

## 13. Work package M8.11 — Browser refresh and reconnect qualification

### 13.1 Idle project refresh

Verify:

- project reloads;
- viewport/state restores according to persistence policy;
- manual edits remain;
- undo/redo remains available;
- stale/result selection remains correct;
- no analysis reruns automatically.

### 13.2 Refresh during backend job

Test refresh while each durable job type is active or represented by a fixture:

- import/decode;
- waveform generation;
- separation;
- rhythm;
- harmony;
- transcription;
- export;
- model download;
- YouTube retrieval;
- Analyze All;
- portable save.

After refresh:

1. frontend reconnects to backend;
2. it fetches authoritative durable state;
3. it does not create a duplicate job;
4. completed/missed events are reconstructed from backend state;
5. cancellation still targets the correct job.

### 13.3 Backend restart

When backend restarts:

- old session token becomes invalid;
- frontend shows session-expired/reopen-app state;
- working project remains intact;
- running jobs become interrupted according to owning job policy;
- no browser-side optimistic state is treated as committed;
- new launcher session can reopen the project and recovery state.

### 13.4 WebSocket/event gap

Simulate dropped event connection.

The client must recover by event ID/durable state refresh rather than assuming every event was observed.

**Acceptance:** refresh/reconnect never duplicates operations or loses committed edits.

---

## 14. Work package M8.12 — Build long-track release fixtures

### 14.1 Required long-track cases

Create or generate legal local fixtures for:

1. at least 60 minutes stereo at 48 kHz;
2. at least 60 minutes with six aligned stem representations;
3. long variable-tempo musical grid;
4. long waveform peak pyramid;
5. long project with loops/markers/snippets across the timeline.

An optional extended two-hour source-only fixture may be used for additional confidence but is not required by the main plan.

### 14.2 Long-track actions

Test:

- initial project open;
- fit-song waveform;
- random seeks near start/middle/end;
- sample-level zoom;
- panning across distant regions;
- selection;
- marker placement;
- playback at 0.25×, 1×, 2×;
- six-stem playback;
- mute/solo changes;
- loop near start/middle/end;
- metronome;
- snippet queue with distant entries;
- export a short distant selection;
- save/reopen.

### 14.3 Bounded-memory requirement

The browser must not decode/load the full long track or every stem into memory.

Verify:

- waveform tiles are bounded;
- PCM lookahead/history remains within configured limits;
- offscreen canvas/tile caches evict;
- hidden stems do not cause whole-file decode into browser memory;
- long duration does not linearly increase retained JS arrays.

**Acceptance:** all long-track workflows remain responsive and bounded.

---

## 15. Work package M8.13 — Build a large-project stress fixture

### 15.1 Large project composition

Construct a synthetic/integration project containing enough retained state to stress project metadata and UI without relying on one giant JSON object.

Include approximately:

- original source;
- multiple separation result sets including four- and six-stem variants;
- multiple rhythm automatic results and edited branches;
- multiple chord results/branches;
- multiple key/tuning results/branches;
- multiple bass transcription results/branches;
- hundreds of markers/loops/snippets;
- thousands of note/chord/rhythm events;
- long persistent command history;
- named revisions/checkpoints;
- multiple exports and job records;
- cache inventory with referenced and reclaimable objects.

Exact counts should be generated deterministically and recorded in the fixture manifest.

### 15.2 Large-project operations

Measure:

- project open time;
- initial UI render time;
- result selector responsiveness;
- history/undo latency;
- scrolling/zooming;
- branch switching;
- stale-dependency recomputation;
- cache inventory calculation;
- portable save time/memory;
- portable reopen;
- project close/reopen.

### 15.3 No JSON inflation regression

Framewise activations, pitch arrays, PCM, waveform tiles, and other large binary data remain file-backed assets.

The large-project fixture must fail the release gate if a code path accidentally serializes them into main project JSON/API responses.

**Acceptance:** project metadata size may grow with retained objects, but UI and backend remain usable and binary artifacts remain external.

---

## 16. Work package M8.14 — Add resource and performance regression instrumentation

### 16.1 Measurements

Collect during release tests:

- backend RSS;
- worker RSS where practical;
- browser process memory;
- browser JS heap where available;
- GPU VRAM;
- CPU utilization;
- PCM-buffer occupancy;
- waveform cache occupancy;
- underrun count;
- audio render deadline overruns if exposed;
- job runtime;
- export throughput;
- project-open time.

### 16.2 Baseline comparison

Store candidate measurements with the release evidence.

Use regression warnings rather than ungrounded hard limits where the design does not specify a numeric target.

Hard release failures include:

- unbounded growth with track duration during steady playback;
- unbounded transfer-buffer accumulation;
- continuously increasing waveform tile cache beyond configured budget;
- stem drift;
- repeatable audio underruns under the qualified target profile;
- browser lockups during ordinary editing;
- OOM on the documented 60-minute six-stem playback case.

### 16.3 Visual-playhead target

Validate the main-plan target that the foreground visual playhead is generally within approximately 30 ms of audible position after latency compensation and does not exhibit steadily increasing drift.

Treat occasional UI scheduling jitter separately from cumulative timing error.

**Acceptance:** release performance evidence proves boundedness and identifies any known machine-specific limits.

---

## 17. Work package M8.15 — Build an offline/no-egress qualification harness

### 17.1 Network restriction

Run the packaged application with external network access blocked while loopback remains available.

Use an OS/test harness capable of observing attempted outbound connections.

### 17.2 Expected behavior

Offline mode must allow:

- application startup;
- project create/open;
- local import;
- waveform/playback;
- existing stem playback;
- editing;
- undo/redo;
- existing analysis result inspection;
- analysis using already installed models/runtimes;
- loops/snippets;
- audio export;
- analysis export;
- cache inspection/cleanup;
- migration;
- portable save/open;
- recovery.

### 17.3 Explicitly unavailable offline actions

Offline mode must clearly disable/fail before network work for:

- online model download;
- YouTube metadata retrieval/download;
- extractor/runtime online update;
- any future network maintenance feature.

### 17.4 Prohibited external requests

Fail release qualification if normal/offline workflows attempt:

- CDN resources;
- web fonts;
- external icons/scripts;
- analytics/telemetry;
- remote thumbnails;
- embedded players;
- model-check calls;
- automatic YouTube probes;
- automatic version checks not explicitly designed/approved.

**Acceptance:** observed runtime traffic is loopback-only for offline workflows.

---

## 18. Work package M8.16 — Complete offline functional qualification

### 18.1 Bundled and already installed models

With network blocked, the bundled Demucs baseline present, and any optional required model artifacts already installed:

1. run Demucs separation;
2. run a registered quality separator if qualified;
3. run rhythm analysis;
4. run chord/key analysis;
5. run bass transcription;
6. run Analyze All;
7. confirm no hidden download request occurs.

### 18.2 Missing model offline

Remove/disable one optional model and request its analysis.

Expected:

- `MODEL_NOT_INSTALLED` or equivalent explicit state;
- install button indicates online install unavailable in offline mode;
- offline bundle import remains available;
- existing project/results remain usable;
- no network retry loop.

### 18.3 YouTube-derived project offline

Open a project whose source originally came from YouTube.

Verify:

- project opens from local immutable media;
- URL is provenance only;
- no metadata refresh;
- no source re-fetch;
- playback/analysis/export works as for local imports.

**Acceptance:** offline mode is a first-class operational state, not a degraded error storm.

---

## 19. Work package M8.17 — Qualify GPU failure behavior

### 19.1 Failure classes

Test:

- `nvidia-smi` unavailable;
- GPU visible to OS but not PyTorch;
- one GPU unavailable;
- both GPUs unavailable;
- model/device qualification failed;
- insufficient VRAM/OOM;
- worker crash during GPU inference;
- GPU disappears between preflight and job start where simulation is possible.

### 19.2 UI behavior

Display:

- requested device;
- qualification state;
- failure reason;
- other qualified devices;
- CPU availability where supported;
- estimated/known warning that CPU may be significantly slower.

### 19.3 No silent CPU fallback

Never transform a requested GPU job into CPU execution without explicit user selection.

The pipeline may pause and request a new device choice or mark the node blocked.

### 19.4 Independent GPU pools

If one GPU fails, do not reinterpret both devices as one combined memory pool or transfer a live job silently.

A retry on another GPU is a new effective execution profile recorded in provenance.

**Acceptance:** GPU failure does not break project playback/editing and never causes hidden hours-long CPU computation.

---

## 20. Work package M8.18 — Qualify explicit CPU fallback selection

### 20.1 Supported adapters

For each model family that declares CPU support:

- validate worker startup;
- validate one short inference;
- validate cancellation;
- validate progress behavior;
- validate output schema equivalence;
- record runtime in qualification evidence.

### 20.2 CPU selection UX

The user must explicitly select CPU after accelerator failure or choose it from device controls.

Show:

- compatibility;
- slower-performance warning;
- current CPU thread limit/profile;
- cancellation control.

### 20.3 Playback responsiveness

While CPU analysis runs:

- preserve UI responsiveness;
- preserve prepared playback responsiveness;
- limit worker threads according to module policy;
- detect/report repeated playback underruns as release defects.

**Acceptance:** CPU fallback is functional where declared, explicit, cancellable, and does not silently starve playback.

---

## 21. Work package M8.19 — Qualify audio-device loss and output changes

Test across the required Linux browsers and Safari where possible:

1. begin playback;
2. suspend/close/recreate AudioContext through a test hook or real device change;
3. preserve last acknowledged source position;
4. re-read actual output sample rate;
5. prepare/reuse matching playback representation;
6. reset buffers/transport generation;
7. require user gesture where browser mandates it;
8. resume coherently.

Also test:

- output sample-rate change between sessions;
- headphones/device switch where practical;
- temporary context suspension;
- rate/loop state after recreation.

**Acceptance:** output-device changes do not change project/source timing or corrupt transport state.

---

## 22. Work package M8.20 — Define the Linux release directory layout

### 22.1 Example layout

Use a versioned release root such as:

```text
basseparate-X.Y.Z-linux-x86_64/
├── bin/
│   ├── basseparate
│   └── basseparate-launch
├── runtime/
│   └── core-python/
├── app/
│   ├── python-package/
│   └── web/
├── wasm/
│   ├── stretch-scalar.wasm
│   └── stretch-simd.wasm
├── contracts/
├── registry/
│   └── models/
├── licenses/
│   ├── components.json
│   ├── THIRD_PARTY_NOTICES.md
│   └── models.json
├── docs/
├── share/
│   ├── applications/
│   ├── icons/
│   └── mime/
├── release-manifest.json
└── README.txt
```

Exact paths may differ, but ownership boundaries must remain clear.

### 22.2 No user data in the install tree

Never store active user state under the release directory.

Use XDG/platformdirs-managed locations for:

- configuration;
- projects/working data;
- cache;
- models;
- logs/state;
- runtime lock/session metadata.

### 22.3 Relocatability

The launcher must resolve the application root relative to itself rather than assuming the original build path.

Test from:

- home directory;
- a path containing spaces;
- a non-default install path;
- outside the source checkout.

**Acceptance:** the release directory is self-describing, relocatable, and contains no mutable user project data.

---

## 23. Work package M8.21 — Build the core runtime bundle

### 23.1 Core runtime requirements

The release must not depend on the Nobara system Python version matching Python 3.11.

Use a pinned release runtime strategy that provides a known Python 3.11-compatible interpreter for the core backend.

### 23.2 Include core application dependencies

Bundle/install from exact locked artifacts:

- FastAPI stack;
- Pydantic stack;
- storage/runtime libraries;
- NumPy and non-model core dependencies required at runtime;
- packaged frontend files;
- application Python package.

Do not include development-only tools in the runtime unless required for diagnostics.

### 23.3 Model worker environments

Model workers continue to use their explicit managed interpreter/environment paths.

The base launcher must:

- start without those environments;
- report which runtimes are installed/qualified;
- allow playback/reopen when analysis runtimes are missing.

### 23.4 Runtime mutation policy

Normal application startup never runs `pip`, `uv sync`, `pnpm`, compilers, or package upgrades.

Any runtime installation/update action is explicit and separated from normal startup.

**Acceptance:** the base application launches on a clean compatible Linux system without source/dev tooling.

---

## 24. Work package M8.22 — Produce the production Linux launcher

### 24.1 Launcher responsibilities

`basseparate-launch` must:

1. resolve the release root;
2. select the packaged core runtime;
3. load user configuration;
4. verify writable storage paths;
5. enforce single-instance behavior for the selected storage root;
6. start the backend on loopback;
7. wait for health/readiness;
8. create the per-session authentication token;
9. open the preferred browser/local URL;
10. display actionable startup errors;
11. forward shutdown signals;
12. stop/reap app-owned child processes;
13. leave working data intact after failure.

### 24.2 Browser opening

Use desktop-supported URL opening rather than hard-coding Chromium.

Provide `--no-browser` for troubleshooting/headless diagnostics.

### 24.3 Startup failures

Handle:

- port conflict;
- storage permission error;
- missing frontend assets;
- corrupt core runtime;
- unsupported architecture;
- DB schema newer than app;
- instance already running;
- browser launch failure.

Browser-launch failure must leave the backend usable and print the local URL.

### 24.4 Logging

Launcher logs must not contain the bootstrap token or authorization header.

**Acceptance:** desktop launch and terminal launch use the same backend lifecycle and cleanup path.

---

## 25. Work package M8.23 — Add Linux desktop integration

### 25.1 `.desktop` entry

Install a desktop entry with:

- application name;
- executable launcher path;
- local icon path;
- application category appropriate for audio/music utilities;
- terminal disabled for normal launch;
- startup notification behavior as supported.

### 25.2 Icon assets

Bundle required icon sizes locally.

Do not fetch icons from the network.

### 25.3 Optional MIME association

If `.basseparate` file association is implemented:

- register a project MIME type;
- pass the selected project path safely as an argument array;
- validate it as a user-selected portable project;
- preserve ordinary archive path-safety checks;
- do not make MIME registration required for application correctness.

### 25.4 Install/uninstall integration scripts

Provide explicit scripts/commands to:

- install desktop entry/icon/MIME metadata for the current user;
- remove those integration files;
- never delete projects, models, cache, or user configuration during desktop-entry removal.

**Acceptance:** the app can be launched normally from the Linux desktop without converting it into a separate desktop-webview product.

---

## 26. Work package M8.24 — Package and verify all frontend runtime assets

### 26.1 Production build

Generate the frontend using the pinned Node/pnpm lock.

Bundle:

- JS chunks;
- CSS;
- fonts;
- icons;
- WASM loader/runtime files;
- source maps only if release policy permits them and they disclose no sensitive build paths.

### 26.2 No runtime CDN dependency

Search built assets for:

- `http://`;
- `https://`;
- known CDN domains;
- remote font imports;
- remote image URLs.

Allow explicit documentation/source links only in non-executed documentation where appropriate; runtime asset loading must remain local.

### 26.3 Production headers

Verify backend serves:

- CSP;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- `Cross-Origin-Opener-Policy: same-origin`;
- `Cross-Origin-Embedder-Policy: require-corp`;
- correct WASM MIME type;
- cache headers appropriate for hashed immutable assets.

### 26.4 Asset integrity

Create a frontend asset manifest with SHA-256 hashes.

The release manifest references its hash.

**Acceptance:** packaged UI starts with Node/pnpm absent and with all external network access blocked.

---

## 27. Work package M8.25 — Qualify external/native runtime dependencies

### 27.1 FFmpeg/ffprobe

At startup/doctor:

- locate executable according to release strategy;
- record version;
- record relevant build configuration/license implications;
- execute bounded probe command;
- mark supported/unsupported status.

If the release bundles FFmpeg, verify its exact binaries and notices are included.

If it relies on system FFmpeg, document the minimum qualified behavior and fail clearly when absent/incompatible.

### 27.2 NVIDIA/driver

`doctor` records:

- NVIDIA command availability;
- detected GPUs;
- driver version where available;
- worker/runtime compatibility results.

Missing NVIDIA support is not a base application startup failure.

### 27.3 yt-dlp/JS/EJS

For YouTube capability:

- display tool versions;
- run non-network capability checks where possible;
- distinguish absent runtime from network failure;
- preserve explicit update mechanism from Milestone 7.

### 27.4 Audio

Record browser audio context sample rate and active capability profile in diagnostics.

**Acceptance:** optional dependency failures degrade only their owning feature and are clearly diagnosable.

---

## 28. Work package M8.26 — Release analysis-runtime provisioning

### 28.1 Runtime registry

Add/complete a registry describing each analysis runtime pack:

- stable runtime ID;
- version/fingerprint;
- Python version;
- platform/architecture;
- dependency lock identity;
- adapter families using it;
- install size;
- source/provenance;
- license inventory reference;
- installed path;
- qualification state.

### 28.2 Explicit installation

If an analysis runtime is not bundled:

- installation is explicit;
- progress is visible;
- network/offline source is explicit;
- integrity is verified;
- normal project open never installs it;
- model weight installation remains a distinct logical step even if UI can coordinate both.

### 28.3 Offline runtime pack

Where release use requires installation without network, define an offline runtime-pack format with:

- manifest;
- exact dependency artifacts;
- hashes;
- notices;
- platform/architecture identity;
- safe extraction rules.

Do not allow an offline model bundle to inject arbitrary worker source code.

**Acceptance:** release users can understand whether a failure is caused by missing runtime versus missing model weights.

---

## 29. Work package M8.27 — Provide and verify offline model-import instructions

### 29.1 Documentation scope

Document the generalized registered-model bundle format from Milestone 7.

For each separately installable model family, document:

- model ID;
- purpose;
- runtime prerequisite;
- expected artifacts;
- expected hashes;
- source/provenance;
- license information;
- import command/UI action;
- verification behavior;
- qualification step after import.

For the bundled Demucs baseline, document verification plus application repair/reinstall (or the registered local repair bundle path if retained), not ordinary Model Manager installation.

### 29.2 Offline import procedure

Procedure for separately installable models:

1. obtain the registered bundle on a networked machine from a permitted source;
2. verify/download according to registry instructions;
3. transfer it to the offline target;
4. open Model Manager;
5. choose offline import;
6. select bundle;
7. verify manifest and hashes;
8. publish into model storage atomically;
9. qualify on selected device;
10. keep bundle/import log for troubleshooting.

### 29.3 Negative tests

Test offline import with:

- wrong model ID;
- wrong checkpoint hash;
- missing file;
- extra executable file;
- path traversal;
- unsupported platform runtime pack;
- unresolved license/provenance state;
- insufficient disk space.

### 29.4 No hidden network use

Run offline import with egress blocked and fail the test if import attempts external resolution.

**Acceptance:** a registered model can be imported and qualified entirely offline from verified local bytes.

---

## 30. Work package M8.28 — Document model, cache, project, state, and log locations

### 30.1 Storage documentation

Document exact platform-resolved categories rather than only generic XDG names.

Expose in the application/doctor:

- configuration directory;
- working project/data directory;
- content-addressed asset store;
- rebuildable cache directory;
- model store;
- analysis runtime store;
- logs/state directory;
- runtime/lock directory;
- default export location policy;
- portable `.basseparate` files are user-selected and external to managed working storage.

### 30.2 Storage UI consistency

The Storage/Model Manager UI and documentation must show the same resolved paths.

No documentation path may be a stale build-machine example presented as the actual user location.

### 30.3 Classification

Explain which categories are:

- essential project data;
- user configuration;
- installed model/runtime data;
- rebuildable cache;
- logs/diagnostics;
- portable backups/exports.

### 30.4 Deletion rules

Document:

- what cache cleanup can remove;
- that model files are not ordinary cache;
- that deleting working project data can lose unsaved/unexported project state;
- that removing the application bundle does not automatically remove user data.

**Acceptance:** a user can locate and distinguish all major storage categories without reading source code.

---

## 31. Work package M8.29 — Define the supported backup model

### 31.1 Primary project backup

The preferred per-project backup is a successful, verified `.basseparate` portable save containing the project revision, original/canonical media, stems/results, history, and referenced project assets according to the archive policy.

Model weights are intentionally excluded from portable projects, including the Demucs baseline that is bundled with the application itself.

### 31.2 Working-data backup

For whole-application disaster recovery, document a cold backup of managed data while basseparate is stopped.

Include:

- configuration if desired;
- working data/database;
- content-addressed essential assets;
- model store optionally;
- runtime packs optionally;
- exclude rebuildable cache unless the user wants faster restore;
- logs optional.

### 31.3 Do not copy live SQLite naively

Do not instruct users to copy only the main SQLite file while the application is actively using WAL.

Use either:

- stop the application before filesystem-level backup; or
- an application-supported consistent snapshot/portable save.

### 31.4 Backup verification

A backup procedure is not complete until restore is tested on a separate temporary storage root.

**Acceptance:** documentation distinguishes portable project backup from full installation/data backup and avoids unsafe live DB copying.

---

## 32. Work package M8.30 — Write and test backup instructions

Create user documentation with procedures for:

1. backing up one project to `.basseparate`;
2. verifying the save completed successfully;
3. storing a previous successful save;
4. backing up all working projects while app is stopped;
5. optionally backing up models/runtime packs;
6. excluding rebuildable cache to reduce backup size;
7. preserving configuration/keyboard mappings/export presets if desired;
8. verifying available disk space;
9. copying backup to another volume;
10. test-restoring to an alternate storage root.

Include warnings about:

- not assuming cache is a backup;
- not assuming installed model files contain project state;
- not deleting working data until backup is verified;
- archive integrity/hash failure.

**Acceptance:** a test user can follow the documented procedure and recover a project without undocumented steps.

---

## 33. Work package M8.31 — Write and test recovery procedures

### 33.1 Interrupted session recovery

Document:

1. restart application;
2. inspect recovery report;
3. distinguish committed edits from interrupted jobs;
4. retry/restart jobs only when appropriate;
5. rebuild optional caches when requested;
6. inspect missing/corrupt asset diagnostics.

### 33.2 Portable project recovery

Document:

- open last verified `.basseparate`;
- restore into managed working storage;
- verify essential assets;
- preserve original archive untouched;
- handle missing model as optional analysis capability rather than corruption.

### 33.3 Missing/corrupt data

Explain separately:

- missing waveform cache;
- missing playback representation;
- missing model;
- missing optional raw evidence;
- missing required stem;
- corrupt essential media;
- newer unsupported schema.

### 33.4 Full storage loss

If only a portable project survives:

- reinstall app;
- open project;
- playback/edit existing saved results without models;
- re-import model/runtime bundles only if new analysis is required.

**Acceptance:** recovery docs match actual error classes and tested repair/rebuild actions.

---

## 34. Work package M8.32 — Verify recovery on the packaged build

Run fault-injection/recovery scenarios against the release bundle:

1. kill backend during edit after commit;
2. kill during analysis staging;
3. kill during export staging;
4. kill during portable save;
5. kill during model download;
6. kill during YouTube retrieval;
7. kill during Analyze All;
8. remove rebuildable waveform cache;
9. remove playback cache;
10. corrupt an optional cache object;
11. remove a required stem from a temporary fixture;
12. corrupt a portable archive copy;
13. start with WAL recovery needed;
14. run cache cleanup while protected assets are pinned by a save/export job.

Verify no scenario silently promotes partial output as complete.

**Acceptance:** packaged behavior matches Milestone 6 recovery guarantees exactly.

---

## 35. Work package M8.33 — Run historical migration and compatibility sweep

### 35.1 Historical fixtures

Maintain fixtures representing supported states from earlier milestones, including:

- empty project;
- imported project;
- waveform/marker project;
- separation/loop project;
- rhythm project;
- harmony project;
- bass-transcription project;
- persistent-history project;
- export/cache project;
- SCNet/RoFormer/six-stem project;
- YouTube-derived project;
- Analyze All project;
- portable archive versions.

### 35.2 Packaged migration test

For each fixture:

1. copy fixture;
2. open with packaged candidate;
3. migrate working copy if supported;
4. verify source/stem frame counts;
5. verify IDs/history/results;
6. verify active selections;
7. verify stale/dependency state;
8. verify playback;
9. verify portable save after migration;
10. verify undo/redo where history exists.

### 35.3 Newer schema

A project/archive newer than the release supports must remain unmodified and receive a specific compatibility error.

**Acceptance:** supported historical projects migrate cleanly and unsupported future projects are preserved.

---

## 36. Work package M8.34 — Build the final feature acceptance matrix

### 36.1 One matrix for all requested features

Create `docs/acceptance-matrix.md` mapping all 35 requested features from the main plan to:

- owning milestone;
- implementation component;
- automated test ID;
- manual test ID where required;
- qualified browsers;
- fixture/project used;
- result;
- evidence link/file;
- known limitation.

### 36.2 Acceptance status values

Use explicit states:

- `pass`;
- `fail`;
- `blocked-environment`;
- `not-applicable` with reason.

Do not use `pass` for unexecuted tests.

### 36.3 Cross-feature cases

Include integrated cases where correctness depends on several features:

- separation → transcription;
- rhythm correction → metronome/count-in/musical loop;
- active result switching → stale transcription;
- variable speed + stem mix + loop + playhead;
- snippet queue + metronome + speed;
- portable save/open + undo/redo;
- YouTube source + offline reopen;
- Analyze All + cache reuse;
- export from Edited result at a fixed revision.

**Acceptance:** every main-plan feature has direct release evidence or an explicit release blocker.

---

## 37. Work package M8.35 — Qualify the five existing local recordings end to end

The main plan identifies five existing WAV files as the initial local listening corpus. They are not ground-truth separation/transcription references, but they are required real-world workflow fixtures.

For each recording:

1. verify original file hash remains unchanged;
2. import or reopen existing project;
3. render waveform;
4. play original;
5. run/select separation preset where models are available;
6. inspect bass/stems;
7. run rhythm;
8. correct at least one rhythm element if needed;
9. run harmony/key;
10. correct at least one harmony/key element if needed;
11. run bass transcription;
12. correct at least one note if needed;
13. create loop;
14. use variable speed;
15. use metronome/count-in where musical grid exists;
16. create snippet queue entry;
17. exercise undo/redo;
18. export stems/mix/analysis;
19. save portable project;
20. close/reopen offline;
21. verify manual edits/results remain.

Record subjective listening observations separately from quantitative benchmark claims.

**Acceptance:** all five complete the project workflow without data-loss or timing defects.

---

## 38. Work package M8.36 — Final timing and synchronization qualification

### 38.1 Stem alignment

Verify:

- no cumulative relative stem drift;
- untreated aligned stems begin on the same output sample according to design;
- seeks reset all active streams to the same project position;
- muted streams retain alignment for immediate unmute.

### 38.2 Rate/stretch

At 0.25×, 0.5×, 0.75×, 1×, 1.25×, 1.5×, and 2×:

- source-time display remains correct;
- pitch remains stable within practical listening/measurement tolerance;
- loop duration does not accumulate rounding drift;
- rate changes do not jump source position.

### 38.3 Metronome/count-in

Verify:

- render-clock scheduling;
- variable tempo;
- meter changes;
- compound meter;
- loop start not on beat 1;
- count-in once;
- count-in every repeat;
- no source-time advancement during count-in.

### 38.4 Playhead

Measure foreground playhead against audible position and verify no steadily increasing drift.

**Acceptance:** timing targets from Section 12.8 of the main plan pass on the qualified release environment.

---

## 39. Work package M8.37 — Final model and Analyze All qualification

### 39.1 Individual modules

Verify installed/qualified modules can still run independently from the packaged build.

### 39.2 Named presets

For every published separation preset:

- resolve concrete model/checkpoint/profile;
- show purpose/limitations;
- run one short qualification case;
- confirm cache key includes exact identity.

### 39.3 Analyze All

Test:

- cold run;
- warm-cache rerun;
- one missing model;
- optional node unavailable;
- cancellation;
- backend restart;
- one node failure;
- one GPU unavailable;
- two independent GPUs available;
- user continues playback while analysis runs;
- changing separator stales only dependent results.

### 39.4 Cache equivalence

A module run individually and as an Analyze All node with the same identity must resolve to the same successful cached result.

**Acceptance:** packaging/release code does not create alternate model/pipeline behavior.

---

## 40. Work package M8.38 — Final export qualification

### 40.1 Audio formats

Test packaged FFmpeg path for:

- WAV 16-bit;
- WAV 24-bit;
- WAV float32;
- FLAC supported depths;
- MP3 supported bitrates including 320 kb/s only where encoder supports it.

### 40.2 Export sources

Test:

- original;
- individual stem;
- multiple stems;
- mixer output;
- selection;
- loop;
- snippet queue;
- original speed;
- practice speed where supported.

### 40.3 Analysis exports

Test:

- complete JSON;
- CSV variants;
- chord `.lab`;
- bass MIDI;
- tempo/time-signature MIDI where representable;
- marker/loop/snippet lists.

### 40.4 Provenance

Verify exports identify:

- project revision;
- active Auto/Edited result IDs;
- stale status when relevant;
- processing/export preset identity.

**Acceptance:** exported files validate independently after generation and failed exports never replace existing valid outputs.

---

## 41. Work package M8.39 — Final security and locality qualification

### 41.1 Loopback security

Re-run:

- Host validation;
- Origin validation;
- bearer/session auth;
- hostile cross-site request rejection;
- WebSocket Origin checks;
- opaque asset IDs;
- filesystem containment;
- archive path traversal rejection;
- subprocess argument-array behavior.

### 41.2 Browser static security

Validate production CSP does not require unsafe remote origins.

### 41.3 Locality observation

Observe outbound traffic during:

- startup;
- project open;
- playback;
- analysis with installed models;
- export;
- portable save;
- cache cleanup;
- recovery.

All must remain local.

### 41.4 Explicit network actions

Observe online model download and YouTube retrieval separately to confirm their network behavior is limited to the explicit action and expected hosts/tool behavior.

**Acceptance:** no hidden network path exists in ordinary project operation.

---

## 42. Work package M8.40 — Final accessibility and input qualification

Although not a separate Milestone 8 line item, accessibility and input behavior were established in earlier milestones and must remain release-clean.

Verify:

- keyboard-only navigation;
- visible focus;
- form labels;
- status text not color-only;
- dialog focus restoration;
- remappable shortcuts;
- shortcut suppression in text inputs;
- Escape behavior;
- Delete safety;
- all shortcut actions remain reachable through visible UI;
- high-DPI canvas pointer mapping;
- common desktop viewport sizes.

Run at least basic browser accessibility checks where tooling exists, then manually verify audio/editor interactions that automation cannot judge.

**Acceptance:** release packaging/browser differences do not regress earlier accessibility/input guarantees.

---

## 43. Work package M8.41 — Generate the final dependency and license inventory

### 43.1 Inventory classes

Generate separate records for:

1. application/core dependencies;
2. frontend dependencies;
3. WASM/native bundled components;
4. bundled/external FFmpeg strategy;
5. yt-dlp and JS runtime components;
6. analysis runtime dependencies;
7. model/checkpoint artifacts;
8. development-only build/test dependencies.

### 43.2 Required fields

For each component record:

- name;
- exact version/commit;
- ecosystem;
- source/homepage;
- artifact hash where distributable/bundled;
- code license;
- weight/checkpoint license separately where applicable;
- required notices;
- bundled versus separately installed;
- runtime versus development-only;
- unresolved restrictions/questions;
- verification status.

### 43.3 Model licenses remain distinct

Never infer a checkpoint license from:

- wrapper/source-code license;
- training dataset license;
- similarly named model family;
- community mirror metadata.

### 43.4 FFmpeg

Record the actual FFmpeg build configuration used by the release or the external runtime expectation, because LGPL/GPL obligations depend on build configuration.

### 43.5 Application-license status

Do not assign a public license to the user’s own application unless that publication decision has been made separately.

**Acceptance:** no distributed runtime/model artifact has an unknown/unreviewed license state hidden by a generic third-party notice.

---

## 44. Work package M8.42 — Produce human-readable notices and attribution

Generate/update:

- `THIRD_PARTY_NOTICES.md`;
- model/checkpoint notices;
- runtime/tool notices;
- Signalsmith notice;
- FFmpeg notice appropriate to actual strategy;
- yt-dlp/JS runtime notices;
- any GPL/AGPL obligations for optional components according to actual distribution decision.

Do not include components merely considered in the design if they are not in the release.

Conversely, do not omit transitive/bundled runtime components because they were not direct dependencies.

**Acceptance:** notices match the actual release manifest rather than the aspirational main plan.

---

## 45. Work package M8.43 — Make the release build reproducible and verifiable

### 45.1 Build from locks

Build using:

- `uv` locked core dependencies;
- locked frontend dependencies;
- pinned Node release;
- pinned Emscripten SDK;
- pinned Signalsmith commit;
- recorded worker runtime locks;
- versioned scripts.

### 45.2 Clean build

Build from a clean working copy/snapshot with generated artifacts removed where appropriate.

### 45.3 Deterministic checks

Where byte-identical output is practical, compare hashes across two clean builds.

Where timestamps/toolchain metadata prevent byte-identical archives, compare normalized manifests and internal file hashes and document the non-deterministic fields.

### 45.4 Contract drift

Run generated-schema/API/type checks before packaging.

### 45.5 Release artifact hashes

Publish SHA-256 for:

- release archive;
- release manifest;
- optional runtime packs;
- any offline model bundles distributed by the project.

**Acceptance:** a second build can verify the same dependency/source inputs and explain any non-byte-identical packaging metadata.

---

## 46. Work package M8.44 — Clean-machine Linux installation qualification

### 46.1 Test environment

Use a clean compatible Linux environment distinct from the source-development tree.

Prefer actual Nobara or a fresh Nobara installation/VM where GPU testing is not required; GPU qualification remains on the physical target machine.

### 46.2 Installation test

1. unpack release archive;
2. run integrity/hash verification;
3. install desktop integration;
4. launch from desktop;
5. launch from terminal;
6. create project;
7. import small local audio;
8. play waveform/audio;
9. stop/restart;
10. reopen project;
11. run doctor;
12. confirm Node/pnpm/Emscripten are absent from runtime PATH;
13. confirm source repository is absent;
14. remove desktop integration;
15. verify project data remains.

### 46.3 Analysis capability

Install/provision one model runtime/model through the release-supported procedure and run a short analysis.

### 46.4 Offline reopen

Disconnect egress and reopen/play/export the project.

**Acceptance:** clean installation does not rely on undeclared developer-machine state.

---

## 47. Work package M8.45 — Upgrade/reinstall/uninstall behavior

### 47.1 Reinstall same version

Reinstalling the same release bundle must not delete user data or duplicate desktop entries unpredictably.

### 47.2 Upgrade candidate

Test upgrading from at least one supported earlier application fixture/build to the release candidate:

- application bundle replaced;
- user data remains in managed storage;
- DB/project migrations execute according to Milestone 6 rules;
- backups are created where migration policy requires;
- project opens successfully.

### 47.3 Downgrade

If a newer schema has been written, an older application must refuse unsafe writes rather than silently downgrade.

Document downgrade limits.

### 47.4 Uninstall

Removing the app bundle/desktop entry does not automatically delete:

- working projects;
- portable projects;
- models;
- cache;
- exports;
- configuration.

Provide explicit manual data-cleanup instructions instead of destructive uninstall defaults.

**Acceptance:** application replacement is separate from user-data lifecycle.

---

## 48. Work package M8.46 — Finalize diagnostics and support bundle procedure

### 48.1 `basseparate doctor`

Release doctor should report, without mutating the environment:

- application/build version;
- core runtime;
- storage paths/free space;
- DB accessibility/schema;
- FFmpeg/ffprobe;
- browser/static build presence;
- GPU visibility;
- model-runtime status;
- model store status;
- yt-dlp/JS runtime state;
- WASM asset presence/hashes;
- cache/model/project size summary;
- last clean shutdown/recovery state where safe.

### 48.2 Privacy-safe diagnostic export

If a support bundle/export is implemented, include only:

- build manifest;
- redacted logs;
- doctor output;
- component/version inventory;
- job error codes;
- optional user-approved project metadata summary.

Exclude by default:

- audio;
- model weights;
- authorization tokens;
- full absolute paths where unnecessary;
- YouTube cookies/credentials;
- project content text beyond what is needed for diagnosis.

If no support-bundle feature exists, document manual collection using existing logs/doctor output rather than adding a rushed new feature.

**Acceptance:** release failures can be diagnosed without asking users to expose project audio or secrets.

---

## 49. Work package M8.47 — Finalize user documentation

Create/update release user documentation covering:

1. system requirements;
2. installation/unpacking;
3. desktop integration;
4. first launch;
5. browser choice/support matrix;
6. local import;
7. YouTube import limitations;
8. model manager;
9. online model installation;
10. offline model import;
11. GPU/CPU selection;
12. project workflow;
13. playback/speed/loops/snippets;
14. rhythm/chords/key/transcription editing;
15. Auto/Edited/model-version behavior;
16. stale-result meaning;
17. undo/redo/history;
18. audio exports;
19. analysis exports;
20. portable save/open;
21. offline mode;
22. storage/model/cache locations;
23. cache cleanup;
24. backup;
25. recovery;
26. migration/version compatibility;
27. troubleshooting;
28. known limitations;
29. privacy/locality statement;
30. license/notices location.

Documentation screenshots, if used, must not embed private project data unintentionally.

**Acceptance:** a non-developer can install, launch, use, back up, and recover the application from the docs.

---

## 50. Work package M8.48 — Finalize developer/release documentation

Document:

- repository/build prerequisites;
- locked setup;
- frontend build;
- WASM build;
- worker runtime build/provisioning;
- model registry maintenance;
- license inventory generation;
- release-manifest generation;
- browser test matrix;
- Safari qualification procedure;
- long-project fixture generation;
- offline/no-egress harness;
- clean-install procedure;
- migration fixture sweep;
- release archive creation;
- hash publication;
- release-candidate promotion.

Provide one top-level release command/script orchestrating checks without hiding failures.

Example logical interface:

```text
python scripts/dev.py release-check
python scripts/dev.py build-release
python scripts/dev.py test-browser --release
python scripts/dev.py licenses
python scripts/dev.py release-manifest
```

Exact command names may follow the existing developer wrapper, but normal release checks must be repeatable and documented.

**Acceptance:** another developer can reproduce the release qualification process from documentation.

---

## 51. Work package M8.49 — Consolidate the final automated test suite

### 51.1 Backend/frontend checks

Run:

- formatting check;
- lint;
- static typing;
- unit tests;
- integration tests;
- contract drift;
- migration fixtures;
- worker protocol tests;
- storage/recovery tests;
- cache tests;
- export tests;
- security tests.

### 51.2 Browser suite tiers

Provide:

- fast smoke suite;
- full Chromium suite;
- full Firefox suite;
- WebKit compatibility suite;
- long-project/stress suite;
- offline suite;
- release-package suite.

### 51.3 Failure artifacts

Retain:

- browser screenshots only when safe/test fixtures are non-sensitive;
- console logs;
- backend logs;
- trace files;
- test environment versions;
- failing fixture IDs.

Do not collect user recordings in automated test artifacts.

**Acceptance:** release status is derived from repeatable test outputs, not an informal checklist alone.

---

## 52. Work package M8.50 — Run final manual listening and UX qualification

Automated testing cannot fully establish audio-practice quality.

Perform structured manual testing on the target PC for:

- original playback;
- four-stem playback;
- six-stem playback;
- bass isolation;
- 0.25×/0.5×/0.75×/1×/1.25×/1.5×/2×;
- loop joins;
- repeated loop duration;
- mute/solo/gain/pan changes;
- limiter behavior;
- metronome accents;
- count-in;
- snippet transitions;
- seek/rate change interaction;
- long playback;
- tab refresh/reconnect;
- CPU analysis while playing;
- GPU analysis while playing where hardware permits.

Record defects with exact project/build/browser/device context.

**Acceptance:** no release-blocking audible discontinuity, drift, or practice-flow defect remains.

---

## 53. Work package M8.51 — Produce release notes and known limitations

Release notes include:

- version/build ID;
- supported primary platform;
- tested browsers;
- Safari test environment/version;
- major implemented capabilities;
- shipped versus separately installed components;
- model presets available;
- model licensing caveats where relevant;
- known GPU/runtime limitations;
- known browser fallbacks;
- known YouTube limitations;
- storage/backup reminder;
- compatibility/migration notes;
- unresolved non-blocking defects.

Do not describe estimated model accuracy as guaranteed user performance.

Do not call optional experimental six-stem guitar/piano separation universally accurate.

**Acceptance:** release limitations are visible and specific rather than hidden in source issues.

---

## 54. Work package M8.52 — Final release artifact construction and verification

### 54.1 Build sequence

1. verify clean candidate source/snapshot;
2. run locked dependency checks;
3. generate contracts;
4. build frontend;
5. build scalar/SIMD WASM;
6. build/install core backend runtime;
7. assemble registry/docs/licenses;
8. generate release manifest draft;
9. assemble Linux release directory;
10. run package smoke tests from assembled directory;
11. run clean-machine smoke test;
12. run offline smoke test;
13. compute internal file hashes;
14. create compressed release archive;
15. compute archive SHA-256;
16. finalize manifest/evidence with archive hash;
17. verify archive by extracting into a clean temporary location and launching it.

### 54.2 No mutable release directory after hashing

Once the final archive/hash is created, any content change creates a new build ID/version candidate.

Do not edit notices or docs inside a hashed release and keep the same published checksum.

### 54.3 Release evidence bundle

Create a separate release-evidence bundle containing test reports and build records. It must not contain user/private audio.

**Acceptance:** the published artifact is exactly the artifact that passed the final smoke/integrity checks.

---

## 55. Implementation order and release gates

Execute Milestone 8 in the following order.

| Gate | Work packages | Required evidence |
|---|---|---|
| A — Freeze | M8.1–M8.3 | Immutable candidate identity, green M0–M7 prerequisites, browser/release matrices |
| B — Linux browsers | M8.4–M8.6, M8.8–M8.11 | Chromium + Firefox + WebKit suites, audio lifecycle, WASM and both buffer paths |
| C — Safari | M8.7 | Actual Safari/macOS qualification report; WebKit alone is insufficient |
| D — Scale/reliability | M8.12–M8.19 | Long-track/large-project, memory, offline, GPU/CPU, audio-device results |
| E — Packaging | M8.20–M8.28 | Relocatable bundle, launcher, desktop entry, local assets, runtime/model provisioning docs |
| F — Backup/recovery | M8.29–M8.35 | Tested backup/recovery docs, migration sweep, acceptance matrix, five-track workflow |
| G — Full product acceptance | M8.36–M8.42 | Timing, models/pipeline, exports, security, accessibility, license/notices pass |
| H — Reproducible release | M8.43–M8.48 | Reproducible build evidence, clean install, upgrade/uninstall, diagnostics, docs |
| I — Final candidate | M8.49–M8.52 | Full automated/manual suite, release notes, final artifact and hashes |

A final release requires Gates A–I.

If actual Safari hardware is unavailable, Gate C remains blocked and the candidate must remain a release candidate rather than being represented as fully qualified under the main plan.

---

## 56. Release acceptance checklist

### 56.1 Release identity

- [ ] Application version is fixed.
- [ ] Build ID exists.
- [ ] Source revision/snapshot ID exists.
- [ ] Core dependency lock is frozen.
- [ ] Frontend lock is frozen.
- [ ] WASM toolchain/commit is frozen.
- [ ] Model registry snapshot is frozen.
- [ ] Worker runtime fingerprints are frozen.
- [ ] Schema/API/protocol versions are recorded.
- [ ] Release manifest exists.
- [ ] Release archive SHA-256 exists.

### 56.2 Chromium on Nobara

- [ ] Production package launches.
- [ ] Bootstrap auth works.
- [ ] Local assets load.
- [ ] CSP works.
- [ ] Audio starts only after permitted gesture.
- [ ] AudioWorklet works.
- [ ] SIMD/scalar selection works.
- [ ] SharedArrayBuffer path works where available.
- [ ] Transferable fallback works.
- [ ] Waveform navigation works.
- [ ] Multi-stem playback works.
- [ ] Time stretch works.
- [ ] Loop/metronome/count-in work.
- [ ] Editing/undo/redo work.
- [ ] Refresh/reconnect works.
- [ ] Export download works.
- [ ] No release-blocking manual listening issue remains.

### 56.3 Firefox on Nobara

- [ ] Production package launches.
- [ ] Bootstrap auth works.
- [ ] Audio gesture behavior works.
- [ ] AudioWorklet works.
- [ ] WASM works.
- [ ] Shared-memory/fallback behavior is correct.
- [ ] Waveform/editor works.
- [ ] Multi-stem/stretch/loop works.
- [ ] Metronome/count-in works.
- [ ] Refresh/reconnect works.
- [ ] Exports work.
- [ ] No release-blocking Firefox-only semantic difference remains.

### 56.4 WebKit/Safari

- [ ] Playwright WebKit automated suite passes.
- [ ] WebKit-only limitations are documented.
- [ ] Actual Safari test was run on macOS.
- [ ] Safari version/macOS version are recorded.
- [ ] Safari audio gesture behavior passes.
- [ ] Safari AudioWorklet passes.
- [ ] Safari WASM path passes.
- [ ] Safari transferable-buffer fallback passes.
- [ ] Safari playback/stretch/loop passes.
- [ ] Safari refresh/reconnect passes.
- [ ] Safari export/download workflow passes.
- [ ] Safari gate is not inferred from Playwright alone.

### 56.5 Audio/WASM/buffering

- [ ] Scalar WASM is bundled and hashed.
- [ ] SIMD WASM is bundled and hashed.
- [ ] Unsupported SIMD falls back.
- [ ] WASM failure has explicit behavior.
- [ ] SharedArrayBuffer path is tested.
- [ ] Transferable-buffer path is tested.
- [ ] Seek discards stale buffered audio.
- [ ] Loop wrap does not accumulate drift.
- [ ] Buffering freezes source advancement.
- [ ] Audio-device loss/recreation is handled.

### 56.6 Long tracks/large projects

- [ ] 60-minute source fixture passes.
- [ ] 60-minute six-stem playback passes.
- [ ] Browser PCM is bounded.
- [ ] Waveform tile cache is bounded.
- [ ] No whole-track browser decode occurs.
- [ ] Long seeks work.
- [ ] Long loops work.
- [ ] Long snippet queue works.
- [ ] Large result catalog works.
- [ ] Large persistent history works.
- [ ] Portable save/open of large fixture works.
- [ ] Binary artifacts remain outside main project JSON.

### 56.7 Offline/locality

- [ ] Offline launch works.
- [ ] Local import works offline.
- [ ] Playback/editing works offline.
- [ ] Existing installed-model analysis works offline.
- [ ] Analyze All works offline when all required models are installed.
- [ ] Export works offline.
- [ ] Portable save/open works offline.
- [ ] Cache cleanup works offline.
- [ ] Recovery works offline.
- [ ] YouTube/model online actions are disabled clearly offline.
- [ ] Missing model does not trigger hidden download.
- [ ] YouTube-derived project does not re-fetch.
- [ ] Network observation finds no external requests during ordinary workflows.

### 56.8 GPU/CPU

- [ ] Missing GPU does not block app start.
- [ ] One-GPU failure is represented accurately.
- [ ] Two GPUs remain separate pools.
- [ ] OOM recovery is bounded.
- [ ] GPU worker crash preserves prior results.
- [ ] CPU is never selected silently.
- [ ] Supported CPU fallback can be selected explicitly.
- [ ] CPU job is cancellable.
- [ ] Playback remains responsive under qualified CPU job profile.

### 56.9 Packaging/launcher

- [ ] Release bundle is relocatable.
- [ ] User data is outside install tree.
- [ ] Core runtime does not depend on system Python 3.11 being installed.
- [ ] Node is not required at runtime.
- [ ] pnpm is not required at runtime.
- [ ] Emscripten is not required at runtime.
- [ ] Launcher binds loopback only.
- [ ] Launcher handles port conflict.
- [ ] Launcher handles browser-open failure.
- [ ] Shutdown reaps owned workers.
- [ ] Desktop entry launches the same runtime path.
- [ ] Desktop uninstall does not delete user data.
- [ ] Frontend assets are local.
- [ ] Production security headers are correct.

### 56.10 Models/runtime packs

- [ ] Model manager loads from release registry.
- [ ] Model storage path is documented.
- [ ] Runtime-pack state is distinguishable from model state.
- [ ] Online installation remains explicit for non-bundled models; bundled Demucs requires no install action.
- [ ] Offline model import works.
- [ ] Offline runtime provisioning works where required by distribution strategy.
- [ ] Hash verification works.
- [ ] Qualification works.
- [ ] Removing separately installed models does not delete project results; bundled Demucs is not removable through ordinary model cleanup.
- [ ] The bundled Demucs baseline is explicitly inventoried with hashes/license/provenance; no other model weights are hidden in the base release without an explicit recorded decision and review.

### 56.11 Backup/recovery/migration

- [ ] Portable project backup instructions are complete.
- [ ] Full working-data backup instructions are complete.
- [ ] Instructions avoid copying live SQLite main file without WAL handling.
- [ ] Restore test passes on separate storage root.
- [ ] Crash-recovery tests pass.
- [ ] Missing-cache rebuild tests pass.
- [ ] Corrupt optional cache tests pass.
- [ ] Missing essential asset classification works.
- [ ] Historical migration sweep passes.
- [ ] Newer unsupported schema is preserved.
- [ ] Portable project opens without models/network.

### 56.12 Full feature acceptance

- [ ] All 35 main-plan feature rows have evidence.
- [ ] Five existing WAV workflows complete.
- [ ] Separation/transcription dependency works.
- [ ] Rhythm correction drives ruler/metronome/count-in correctly.
- [ ] Harmony/key editing persists.
- [ ] Bass-note editing persists.
- [ ] Auto/Edited/version switching persists.
- [ ] Stale results are explainable.
- [ ] Persistent undo/redo survives restart.
- [ ] Snippet queues work.
- [ ] Keyboard mapping works.
- [ ] WAV/FLAC/MP3 export works.
- [ ] Analysis export works.
- [ ] Model manager works.
- [ ] YouTube import works online.
- [ ] YouTube-derived reopen works offline.
- [ ] Analyze All cold/warm/partial-failure cases work.

### 56.13 Timing

- [ ] No cumulative relative stem drift.
- [ ] Untreated stems align at start.
- [ ] Playback/source mapping is correct across supported rates.
- [ ] Loop iterations do not accumulate timing error.
- [ ] Metronome follows render clock.
- [ ] Count-in does not advance source time.
- [ ] Foreground playhead is generally within the main-plan timing target after latency compensation.
- [ ] No steadily increasing visual drift exists.

### 56.14 Export

- [ ] WAV 16/24/float32 pass.
- [ ] FLAC passes.
- [ ] MP3 passes where encoder supports selected profile.
- [ ] Stem alignment is preserved.
- [ ] Selection/loop/queue exports pass.
- [ ] Mixer export passes.
- [ ] Practice-speed export identifies DSP profile.
- [ ] JSON/CSV/LAB/MIDI exports pass.
- [ ] Project revision/result provenance is present.
- [ ] Failed/cancelled export does not overwrite valid file.

### 56.15 Security

- [ ] Host/Origin validation passes.
- [ ] Session auth passes.
- [ ] WebSocket origin validation passes.
- [ ] CORS remains restricted.
- [ ] Filesystem containment passes.
- [ ] Archive traversal rejection passes.
- [ ] Authorization tokens are absent from logs.
- [ ] Browser static assets expose no unintended external origin.
- [ ] Normal project open performs no external request.

### 56.16 License/release evidence

- [ ] `components.json` matches release contents.
- [ ] Model/checkpoint registry licenses are separate from code licenses.
- [ ] FFmpeg actual build licensing is recorded.
- [ ] Signalsmith notice is present.
- [ ] yt-dlp/runtime notices are present where distributed.
- [ ] Analysis runtime dependencies are inventoried.
- [ ] Development-only dependencies are distinguishable.
- [ ] Unresolved license items block distribution or are explicitly excluded.
- [ ] Human-readable notices match machine inventory.
- [ ] Release archive hash is published.
- [ ] Acceptance report is retained.
- [ ] Known limitations are published.

---

## 57. Direct traceability to Section 13 Milestone 8

| Main-plan Milestone 8 item | Detailed coverage |
|---|---|
| 1. Test Chromium and Firefox on Nobara | M8.3–M8.5, M8.8–M8.14, M8.49–M8.50 |
| 2. Test automated WebKit behavior | M8.6, M8.8–M8.11, M8.49 |
| 3. Test actual Safari on macOS | M8.7, Gate C, checklist 56.4 |
| 4. Validate user-gesture audio startup | M8.8, M8.19, checklist 56.2–56.5 |
| 5. Validate WebAssembly and buffer fallback | M8.9–M8.10, checklist 56.5 |
| 6. Test browser refresh/reconnection | M8.11, M8.32, checklist browser sections |
| 7. Test long tracks and large projects | M8.12–M8.14, checklist 56.6 |
| 8. Test offline operation | M8.15–M8.16, M8.39, checklist 56.7 |
| 9. Test GPU failure and CPU fallback selection | M8.17–M8.18, checklist 56.8 |
| 10. Produce Linux launcher and desktop entry | M8.20–M8.23, M8.44–M8.45, checklist 56.9 |
| 11. Package local frontend assets | M8.24, M8.43–M8.44, checklist 56.9 |
| 12. Provide offline model-import instructions | M8.26–M8.27, checklist 56.10 |
| 13. Document model and cache locations | M8.28, M8.47, checklist 56.10 |
| 14. Provide backup/recovery instructions | M8.29–M8.33, M8.47, checklist 56.11 |
| 15. Complete all feature acceptance cases | M8.34–M8.40, M8.49–M8.50, checklist 56.12–56.15 |
| 16. Publish a versioned build and license inventory | M8.1–M8.2, M8.41–M8.45, M8.51–M8.52, checklist 56.16 |

The main-plan acceptance condition for the full project is broader than “the package starts.” Milestone 8 closes only when every requested feature has an implemented and tested workflow; the existing five recordings can be imported, analyzed, edited, practised, exported, and reopened; long recordings remain bounded; timing remains coherent across playback/loops/metronome/annotations; automatic results remain reviewable/correctable; reruns preserve older results/manual edits; portable projects reopen without model execution; offline analysis produces no hidden external requests; model choices retain versions/licenses/hashes/measured hardware behavior; and uncertainty remains visible rather than being presented as certainty.

---

## 58. Final release evidence package

For every final release preserve:

```text
release-evidence/X.Y.Z/
├── release-manifest.json
├── acceptance-matrix.md
├── browser-matrix.json
├── chromium-report/
├── firefox-report/
├── webkit-report/
├── safari-report/
├── long-project-report.json
├── offline-network-report.json
├── gpu-qualification.json
├── clean-install-report.md
├── migration-report.json
├── timing-report.json
├── export-report.json
├── model-benchmark-reference.txt
├── license-inventory/
├── third-party-notices-hash.txt
├── release-archive.sha256
├── runtime-pack-hashes.txt
├── known-limitations.md
└── release-notes.md
```

Do not include private user recordings in the evidence package. Use synthetic/test fixtures or record only hashes/metadata of the five local tracks where needed.

---

## 59. Final release procedure

1. Cut `X.Y.Z-rc.N` candidate.
2. Freeze source/dependency/model-registry/runtime identities.
3. Run all M0–M7 prerequisite suites.
4. Build candidate package.
5. Run Chromium/Firefox release-package suites on Nobara.
6. Run WebKit automation.
7. Run actual Safari/macOS qualification.
8. Run WASM/shared-memory/transferable fallback tests.
9. Run refresh/reconnect tests.
10. Run long-track/large-project tests.
11. Run offline/no-egress tests.
12. Run GPU/CPU failure-selection tests.
13. Run recovery/migration tests.
14. Run five-track end-to-end review.
15. Run final timing/listening acceptance.
16. Run export acceptance.
17. Run security/locality acceptance.
18. Generate final licenses/notices.
19. Build clean final archive.
20. Run clean-install verification from that archive.
21. Compute SHA-256.
22. Finalize release manifest/evidence.
23. Review known limitations.
24. Promote candidate to final `X.Y.Z` only if all gates pass.
25. Preserve the exact final artifact and evidence used for promotion.

Any code/content change after Step 20 invalidates the candidate hash and requires rebuilding/re-running affected gates.

---

## 60. Milestone 8 final acceptance statement

Milestone 8 is complete when basseparate is not merely feature-complete in the source tree but release-qualified as a durable local application: the frozen candidate passes its inherited Milestone 0–7 regression suites; Chromium and Firefox on Nobara run the production bundle correctly; Playwright WebKit passes its compatibility suite; actual Safari on actual macOS hardware passes the required audio, WebAssembly, buffering, refresh, editing, and export workflows; browser audio starts/resumes only under valid user-gesture rules; scalar/SIMD Signalsmith WASM and both SharedArrayBuffer and transferable-buffer paths are tested; browser refresh/reconnection reconstructs durable jobs and revisions without duplication or lost edits; 60-minute/six-stem and large retained-result projects stay responsive with bounded browser memory; blocked-egress tests prove ordinary startup, playback, editing, installed-model analysis, export, save/open, cache cleanup, and recovery make no external requests; GPU loss is explicit and CPU execution is never selected silently; the Linux release is a relocatable production bundle with a reliable loopback launcher and desktop entry, local static assets, no runtime Node/pnpm/Emscripten requirement, and user data outside the install tree; non-bundled model/runtime installations remain explicit, bundled Demucs is verified as part of the application package, and offline registered imports are documented and verified; model, runtime, cache, project, log, and configuration locations are documented consistently with the UI; portable-project and full-working-data backup/recovery procedures are safe, tested, and avoid naive live SQLite/WAL copying; historical migration fixtures and crash/corruption scenarios pass; every one of the main plan's 35 requested features has release evidence; all five existing recordings complete the end-to-end workflow; timing/export/security/locality targets pass; and the exact published build carries a machine-readable release manifest, artifact hashes, complete code/runtime/model license inventory, required third-party notices, release notes, known limitations, and immutable qualification evidence.
