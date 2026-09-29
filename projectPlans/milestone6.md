# Milestone 6 — Complete persistence and workflow: detailed implementation specification

This expands Milestone 6 in Section 13 of `basseparate_project_plan.md`.

It builds on `milestone0.md` through `milestone5.md`. Those milestones remain authoritative for the application foundation, import/media storage, waveform and transport architecture, source separation, variable-speed practice, portable project format, musical grid, chord/key/tuning analysis, bass transcription, model/result provenance, revisioned editing, and module-specific cache/staleness rules. Milestone 6 must consolidate and harden those systems rather than replace their domain semantics.

The main-plan Milestone 6 scope is: complete command coverage for all manual edits; project-wide persistent undo/redo hardening; unified retained-result/model/input selection with Auto/Edited switching for editable analysis families; revision-conflict handling; crash recovery; downstream stale-result indicators; snippet queues; full remappable keyboard mapping; export presets; FLAC/MP3 export; analysis exports; cache inspection/cleanup; project-migration tests; and missing-asset/corruption handling.

Where this document introduces concrete implementation choices, they are Milestone 6 engineering decisions consistent with the main project plan. They do not redefine the musical-analysis algorithms implemented in Milestones 2–5.

---

## 1. Required outcome and milestone boundary

### 1.1 Complete user workflow

At completion, the user can:

1. Launch basseparate after a normal shutdown or an interrupted previous session.
2. Open an active working project and immediately see whether recovery is required.
3. Continue from the last committed semantic edit after a crash without rerunning completed analysis.
4. Undo and redo every user-editable project operation introduced in Milestones 1–5 after restarting the application.
5. See an accurate description of the next undo and redo operation.
6. Make a new edit after undo and have the old redo branch become non-redoable without erasing its audit record.
7. Create named historical checkpoints and later restore one as a new project revision.
8. Switch each analysis family explicitly among retained result/model/input versions, and switch Auto/Edited only for families that define editable branches; separation remains immutable result-version selection.
9. Switch between retained model/input versions without deleting older results or corrections.
10. See which active and retained downstream results are current, stale, unavailable, or corrupt, and why.
11. Keep using stale results deliberately where safe, with visible warnings.
12. Resolve a stale-edit conflict from another browser tab without silent overwriting.
13. Create a queue of noncontiguous practice snippets.
14. Reorder, enable/disable, rename, and repeat queue entries.
15. Play the queue through the existing synchronized transport, speed control, mixer, metronome, and count-in system.
16. Use and remap the complete keyboard shortcut set without shortcuts firing while typing in text fields.
17. Save reusable audio-export presets.
18. Export WAV, FLAC, or MP3 according to the selected preset and source/result version.
19. Export original audio, stems, mixer output, a selection, a loop, or a snippet queue as supported by the selected preset.
20. Export chords, notes, beats, meter/tempo, markers, loops, and provenance in the defined analysis formats.
21. Inspect working-project storage, model storage, rebuildable cache, temporary/staging data, and reclaimable bytes separately.
22. Preview cache cleanup before deletion.
23. Clean only unreferenced rebuildable cache objects without damaging working projects, portable projects, models, active jobs, or edit history.
24. Open projects created by every supported earlier schema version through tested migrations.
25. Refuse unsupported newer schemas without modifying the original data.
26. Open a project with missing optional caches and rebuild them where possible.
27. Open a project with missing analysis evidence while preserving surviving corrected/manual state where safe.
28. Receive a precise diagnostic when an essential asset is missing or corrupt.
29. Save a portable `.basseparate` archive from one stable project revision while edits or analysis continue elsewhere.
30. Reopen that archive offline without running any analysis model.
31. Export and practise from saved results even when the original model/runtime is no longer installed.
32. Continue to use the existing five-track evaluation workflow without regression in timing, analysis editing, or playback.

### 1.2 Included work

Milestone 6 includes:

- a project-wide semantic command registry;
- coverage audit for every editable object/state introduced in Milestones 1–5;
- durable command history and persistent undo/redo state;
- redo-branch invalidation without destructive history loss;
- named historical checkpoints and restore-as-new-revision behavior;
- command coalescing rules and history compaction/checkpoints;
- unified analysis-family result/branch selection;
- explicit retained-result/model/input version switching, plus Auto/Edited switching for editable symbolic/annotation analysis families;
- a normalized dependency and staleness graph;
- global stale/unavailable/corrupt status and reason reporting;
- project-level revision-conflict responses and browser conflict UX;
- multi-tab revision notifications;
- clean-shutdown/session records;
- startup integrity checks and crash recovery;
- interrupted-job and staging recovery;
- snippet queues and queue playback;
- a centralized action/shortcut registry;
- remappable keyboard shortcuts and conflict validation;
- reusable export presets;
- FLAC and MP3 audio export;
- general WAV/FLAC/MP3 export jobs;
- project-wide analysis export formats;
- cache inventory, budgets, pinning, dry-run cleanup, and explicit cleanup;
- project/database/portable-schema migrations and fixtures;
- asset integrity classification and repair/rebuild workflows;
- complete API, WebSocket, persistence, portable-project, browser, and documentation integration;
- regression tests covering all earlier milestone workflows.

### 1.3 Explicitly deferred work

Milestone 6 must not pull Milestone 7 or Milestone 8 implementation forward.

Still deferred:

- SCNet integration;
- RoFormer integration;
- six-stem guitar mode;
- promotion of new quality/speed separation presets based on Milestone 7 benchmarks;
- the larger model manager UX planned for Milestone 7 beyond the model-management capabilities already needed by prior milestones;
- yt-dlp/EJS YouTube import;
- YouTube-specific cancellation/error handling;
- independent extractor updating;
- final whole-pipeline `Analyze All` orchestration if it has not already been implemented as a reusable partial graph;
- final Chromium/Firefox/Safari release qualification;
- release packaging and desktop integration;
- final versioned public build.

Milestone 6 may define interfaces used by Milestone 7, but must not claim those later capabilities are complete.

### 1.4 Prerequisite state inherited from Milestones 0–5

Milestone 6 assumes the prior milestones provide:

1. An authenticated loopback backend and generated typed frontend client.
2. SQLite working storage with ordered migrations.
3. Immutable source and derived asset identities.
4. Durable jobs with staged atomic publication.
5. Stable source-frame timing.
6. Shared waveform rendering and linked selection.
7. A synchronized multi-stem transport.
8. Variable-speed playback and source-time loops.
9. Portable ZIP64 project save/open.
10. Basic autosave and clean-working-project persistence.
11. Project revisions, idempotency keys, and command-based editing.
12. Module-specific undo/redo support introduced incrementally.
13. Immutable automatic analysis results.
14. Editable analysis branches.
15. Multiple retained result versions.
16. Module-specific cache identities and staleness rules.
17. Rhythm/grid branches and musical positions.
18. Chord/key/tuning branches.
19. Bass-transcription branches and note-edit commands.
20. Bass MIDI export.
21. Model-absent portable reopen.
22. Missing-optional-artifact handling at module level where already specified.

A defect in those prerequisites is fixed at its owning milestone boundary. Milestone 6 may strengthen the shared mechanism, but must not hide an earlier timing, analysis, or storage defect behind workflow-specific special cases.

### 1.5 Definition of the milestone boundary

Milestone 6 is complete only when persistence, history, result selection, dependency status, crash recovery, snippet practice, shortcuts, export, cache management, migrations, and integrity handling work as one project-wide workflow.

The following are insufficient by themselves:

- persisting only the last project snapshot while losing undo/redo;
- retaining command rows but not being able to replay undo/redo safely after restart;
- showing one generic `stale` badge without stating the changed dependency;
- deleting cache by age without checking project references;
- switching analysis results in the UI without making the selection itself revisioned and undoable;
- resolving conflicts with last-writer-wins overwrites;
- treating a worker crash as project corruption;
- restoring partial staging output as a completed asset;
- exporting MP3 by silently changing unsupported sample-rate/bitrate constraints;
- analysis CSV/JSON exports that do not say whether Auto or Edited data was exported;
- shortcut remapping that permits ambiguous duplicate chords without warning;
- a snippet queue that drifts from source time or bypasses existing transport timing;
- migrating a project in place without preserving the original on failure;
- opening a corrupt archive and silently dropping missing required state.

---

## 2. Fixed implementation decisions for Milestone 6

| Area | Milestone 6 decision |
|---|---|
| Authoritative edit history | SQLite-backed semantic command ledger |
| Project revision | Monotonically increasing integer; undo/redo also create new revisions |
| Undo model | Apply stored inverse payload transactionally; never decrement project revision |
| Redo model | Reapply stored forward payload transactionally |
| Redo after divergent edit | Old redo path becomes abandoned/non-redoable but remains auditable |
| Command grouping | One semantic gesture/transaction = one history entry |
| Named history | Named revision checkpoints point to stable revisions and restorable state |
| Fast reconstruction | Periodic compact project-state checkpoints plus command ledger |
| Active analysis selection | Explicit per-analysis-family selection record |
| Result status | `current`, `stale`, `unavailable`, `corrupt`, `incomplete` |
| Staleness | Derived from declared dependency edges; never inferred from timestamps alone |
| Stale behavior | Keep results available unless required input bytes are unavailable/corrupt |
| Conflict policy | Strict base revision for semantic edits; no silent last-writer-wins merge |
| Multi-tab update | Event-ID WebSocket notifications plus authoritative refetch |
| Recovery | SQLite/WAL recovery + session record + staged-artifact ownership manifests |
| Snippet queues | Ordered project objects using source or musical interval anchors |
| Shortcut storage | User-level configuration; project files do not force personal mappings |
| Export presets | Versioned declarative profiles; built-ins plus user-defined presets |
| Audio export | Backend-owned durable export jobs through FFmpeg |
| Practice-speed audio export | Explicit versioned offline stretch profile; never silently claim live-engine identity |
| Analysis export | Versioned schemas with explicit Auto/Edited/result provenance |
| Cache cleanup | Reference-aware, pin-aware, dry-run first |
| Default cache budget | 50 GiB rebuildable analysis/waveform cache, configurable |
| Model files | Accounted separately; never evicted as ordinary cache |
| Migration | Ordered transactional DB/project migrations; originals preserved on failure |
| Corruption handling | Classify essential vs optional/rebuildable assets before recovery action |
| Portable save | Snapshot one committed revision; concurrent later edits are excluded by design |

### 2.1 Undo/redo does not move the revision number backwards

The project revision is a concurrency/version identity, not an index into the visible undo stack.

Example:

```text
revision 40: move chord boundary
revision 41: rename chord
revision 42: undo rename chord
revision 43: redo rename chord
```

At revision 42, the project state may resemble revision 40 in one field, but the project revision remains 42.

This rule prevents:

- reuse of stale base revisions;
- ambiguous idempotency behavior;
- multi-tab clients mistaking undo for time travel;
- accidental identity collision between old and newly reconstructed state.

### 2.2 History and domain branches are separate concepts

Do not confuse:

1. **Command history branch** — the user's sequence of project edits and undo/redo operations.
2. **Analysis editable branch** — a corrected rhythm/chord/key/transcription branch derived from immutable machine output.

Undoing a note edit modifies the active transcription branch state. It does not delete the branch object.

Switching from Edited to Auto is itself a project command. It does not undo every edit ever made in the Edited branch.

### 2.3 Stale is not corrupt

Use distinct meanings:

- `current`: declared dependencies match the currently selected relevant upstream identities.
- `stale`: bytes and result are valid, but one or more declared upstream dependencies no longer match the active context.
- `unavailable`: required bytes or runtime-independent data needed to use the result cannot currently be resolved.
- `corrupt`: an integrity check failed.
- `incomplete`: job/publication did not complete and the object is not a valid result.

A stale result may remain playable, viewable, editable, and exportable with a warning.

### 2.4 Declared dependency edges determine staleness

Every analysis result/branch declares dependencies by semantic role.

Initial edge classes:

- `hard_input` — changing this dependency makes the result stale.
- `decode_context` — consumed by the algorithm/decoder and therefore part of cache/stale identity.
- `display_context` — used only for rendering/review and does not stale the result.
- `optional_evidence` — result remains usable when missing, but evidence inspection is degraded.
- `derived_from` — provenance edge to immutable parent output/branch.

Examples:

- bass transcription → selected bass stem: `hard_input`;
- bass transcription → tuning context when decoder consumes it: `decode_context`;
- bass transcription → chord regions used only for review: `display_context`;
- edited chord branch → raw logits artifact: often `optional_evidence` after the branch's chord regions are persisted;
- rhythm edited branch → automatic rhythm result: `derived_from`.

### 2.5 Portable archives are not the live autosave mechanism

Working storage remains the fast durable editing state.

Portable `.basseparate` archives remain explicit snapshots.

Milestone 6 must not rebuild a large ZIP archive after each edit.

### 2.6 User shortcut preferences are not project semantics

Shortcut mappings belong to user configuration because collaborators or future machines may use different keyboards/preferences.

A portable project may store project-specific UI state, but must not overwrite the receiving user's global shortcut configuration on open.

### 2.7 Export is always version-explicit

Every export resolves an exact source/result identity before execution.

For analysis exports, the export must state whether it used:

- an immutable automatic result;
- an editable branch;
- a specific model/input version;
- the active project selection at the moment the job snapshot was created.

Do not export from a moving UI pointer after the job starts.

---

## 3. Work package M6.1 — Verify prerequisites and audit all mutable project state

### 3.1 Run prerequisite acceptance suites

Before changing persistence/history:

1. Run Milestones 0–5 unit/integration/browser acceptance suites.
2. Open representative projects at each milestone capability level.
3. Verify project revision increments under existing edit commands.
4. Verify stale base revisions return conflicts.
5. Verify current portable save/open succeeds.
6. Verify analysis results remain immutable.
7. Verify editable branches survive reopen.
8. Verify source/stem/rhythm/chord/key/note timing remains source-frame aligned.
9. Verify variable-speed playback and loops remain correct.
10. Verify model-absent reopen succeeds.
11. Record baseline working-database size and command-history behavior.
12. Record any failing prerequisite before refactoring shared history.

### 3.2 Build a mutable-state inventory

Create a machine-readable inventory of every user-mutable state field introduced so far.

Categories include:

- project name/metadata;
- source markers and sections;
- selection-derived saved loops;
- loop properties;
- mixer state;
- playback speed preference;
- limiter state;
- track visibility/order/height/amplitude zoom;
- viewport zoom/scroll/follow mode;
- active separation result;
- active rhythm result/branch;
- rhythm pulse edits;
- tempo anchors;
- meter regions/grouping;
- bar origin/pickup settings;
- snap mode;
- metronome settings;
- count-in settings;
- active chord result/branch;
- chord-region edits;
- chord display complexity;
- active key result/branch;
- key-region edits;
- tuning edits;
- active bass-transcription result/branch;
- bass-note edits and gesture metadata;
- confidence review state;
- lane visibility and analysis-view settings;
- named loops and future snippet queues;
- analysis selection state;
- project-level export defaults when intentionally project-scoped.

### 3.3 Classify each mutable field

For every field, record:

- owner domain;
- authoritative storage table/object;
- command type(s);
- inverse representation;
- redo representation;
- whether command is semantic or view-only;
- whether it affects analysis dependencies;
- whether it affects portable project content;
- whether it belongs to user config instead of project state;
- whether it is allowed during playback;
- whether it requires transport reconfiguration;
- whether it can be coalesced.

### 3.4 Detect component-local mutations

Search frontend/backend implementation for state changes that bypass project commands.

Any persistent user edit that directly mutates component/store state must be migrated to the common command path.

Transient state may remain local, including:

- hovered object;
- in-progress drag preview;
- current playhead frame;
- temporary dialog text before commit;
- pending file-picker state;
- transient job progress;
- canvas hover guides.

### 3.5 Produce command-coverage report

Generate a development-time report:

```text
mutable_state_field -> command_type -> persistence -> undo -> redo -> tests
```

Fail the Milestone 6 completion check if any persistent semantic field lacks command coverage without an explicit documented exception.

**Acceptance:** all mutable project semantics have one authoritative persistence path and a known command/history policy.

---

## 4. Work package M6.2 — Define the project-wide semantic command contract

### 4.1 Command envelope

Standardize every project command on:

- `command_id` UUID;
- `project_id`;
- `command_type` stable identifier;
- command-schema version;
- base project revision;
- optional base domain/branch revision;
- idempotency key;
- actor/session ID;
- UTC client creation timestamp for diagnostics only;
- server commit timestamp;
- target object IDs;
- normalized forward payload;
- normalized inverse payload generated/validated by the backend;
- command grouping metadata;
- optional coalescing key;
- human-readable history summary;
- dependency-impact summary;
- resulting project revision.

Do not trust a browser-supplied inverse payload as authoritative.

### 4.2 Command registry

Create a central registry where every command declares:

1. Stable command type.
2. Payload schema.
3. Validation function.
4. Authorization/project scope.
5. Domain read set.
6. Domain write set.
7. Forward application function.
8. Inverse construction function.
9. Redo application function or verified reuse of the normalized forward payload.
10. Conflict rules.
11. Coalescing policy.
12. Staleness/dependency impacts.
13. Transport side effects if any.
14. History summary formatter.
15. Minimum project schema version.

### 4.3 Command determinism

Given the same validated pre-state and normalized payload, command application must produce the same domain state.

Do not include:

- current wall-clock time in musical data;
- random IDs generated separately during redo;
- model calls;
- network calls;
- filesystem scanning;
- nondeterministic ordering.

If a command creates an object, preallocate its stable object ID during initial command normalization and retain that ID for redo.

### 4.4 Command validation order

For semantic edits:

1. Authenticate request.
2. Validate project identity.
3. Validate idempotency key.
4. Read current project revision.
5. Compare base revision.
6. Validate target existence/current branch.
7. Validate domain constraints.
8. Build canonical before-state/inverse.
9. Apply domain mutation in one SQLite transaction.
10. Record command history entry.
11. Increment project revision.
12. Update dependency/stale state.
13. Commit.
14. Emit revision event.

### 4.5 Batch commands

Support one atomic user operation containing multiple subcommands.

Examples:

- dragging a shared chord boundary updates two regions;
- meter edit changes grouping and display unit;
- deleting a selected group of notes;
- restoring a named historical checkpoint;
- reordering multiple snippet-queue entries.

The batch has one history label and one project revision.

### 4.6 Command size limits

Do not store large binary arrays in command payloads.

Commands reference stable objects/artifacts and store compact before/after semantic state.

Set a configurable serialized command-size limit, initially 1 MiB, with lower typical targets.

Bulk region/note operations should use compact structured records rather than framewise evidence arrays.

### 4.7 Command schema evolution

Command history must remain readable after application upgrades.

Every command type has a schema version.

Migration rules must either:

- migrate old command payloads;
- retain a compatible decoder for old versions; or
- materialize a history checkpoint before retiring an old representation.

**Acceptance:** every persistent semantic edit uses the same validated command envelope and can provide a reliable inverse/redo representation.

---

## 5. Work package M6.3 — Complete command coverage for all Milestones 1–5

### 5.1 Marker and section commands

Cover:

- create marker;
- move marker;
- rename marker;
- recolor marker;
- delete marker;
- create section;
- resize section;
- move section;
- rename/recolor section;
- delete section.

### 5.2 Mixer and track-state commands

Cover:

- gain change;
- pan/balance change;
- mute;
- solo;
- track visibility;
- track height;
- track order;
- per-lane amplitude display scale;
- master gain;
- monitoring limiter state;
- active original/stem playback group.

Continuous fader movement coalesces into one history entry after gesture end.

### 5.3 Loop commands

Cover:

- create;
- rename;
- recolor;
- move;
- resize;
- source/musical anchor changes where supported;
- repeat count;
- boundary fade;
- duplicate;
- delete;
- active loop selection;
- loop-enabled state.

### 5.4 Rhythm/grid commands

Reuse and standardize Milestone 3 operations:

- pulse add/delete/move;
- downbeat/role changes;
- acceptance state;
- tempo-anchor add/delete/move/lock;
- half/double interpretation;
- meter-region insertion/deletion/boundary/grouping edits;
- first numbered bar;
- pickup state;
- active rhythm result/branch selection;
- snap settings;
- metronome settings;
- count-in settings.

### 5.5 Chord/key/tuning commands

Reuse and standardize Milestone 4 operations:

- chord rename/alternative/no-chord/unknown/custom label;
- boundary drag;
- split/merge/insert/delete;
- inversion edits;
- review state;
- key-region boundary/tonic/mode/spelling edits;
- key split/merge/insert/delete;
- tuning reference/offset edits;
- active chord/key result/branch selection;
- display complexity.

### 5.6 Bass-note commands

Reuse and standardize Milestone 5 operations:

- start/end movement;
- pitch change;
- semitone/octave shift;
- insert/delete;
- split/merge;
- unknown/unpitched state;
- slide/bend metadata;
- review state;
- active transcription result/branch selection.

### 5.7 View-state commands

Include persistent view state in history where the main plan requires it:

- horizontal zoom;
- scroll position;
- lane heights/order;
- collapsed/visible tracks;
- overlays;
- follow-playhead mode;
- pitch-analysis view options.

Coalesce rapid navigation gestures aggressively to prevent command-log noise.

### 5.8 Excluded transient operations

Do not place these in undo history:

- play/pause;
- playhead movement caused by playback;
- hover;
- job progress;
- temporary selection preview;
- transport buffering state;
- connection/reconnect state;
- diagnostics panel expansion unless intentionally treated as persistent view preference.

**Acceptance:** command-coverage report shows no persistent manual edit bypassing the shared command system.

---

## 6. Work package M6.4 — Implement durable history storage

### 6.1 Database records

Add/standardize:

- `command_entries`;
- `command_batches` where useful;
- `history_state` per project;
- `named_revisions`;
- `history_checkpoints`;
- optional `history_abandoned_segments` metadata;
- command-schema version metadata.

### 6.2 Command entry fields

Each history entry stores:

- sequence ID;
- command ID;
- project ID;
- command type/version;
- normalized forward payload;
- normalized inverse payload;
- project revision committed by the original apply;
- current history status;
- original parent history position;
- created/committed timestamps;
- history summary;
- affected domain/object IDs;
- actor/session diagnostics;
- abandonment reason if no longer redoable.

### 6.3 History state

Persist:

- current active history head;
- next undoable entry;
- next redoable entry where one exists;
- history generation/branch identity;
- last checkpoint ID;
- last compacted sequence.

This state must survive restart exactly.

### 6.4 Transaction rule

Domain mutation, command entry, history-state update, and project-revision increment occur in one SQLite transaction.

A crash must not produce:

- edited domain state without a history record;
- a history record whose domain edit did not commit;
- project revision increment without the corresponding state change.

### 6.5 Existing command migration

For command history already written by Milestones 1–5:

1. Detect legacy command representation.
2. Migrate to the shared envelope when semantics are known.
3. Preserve original IDs/timestamps where safe.
4. Materialize a baseline checkpoint when a legacy command cannot be safely replayed.
5. Never fabricate an inverse that is not supported by stored before-state.
6. Mark pre-baseline history as non-undoable if required while preserving the current project state.

### 6.6 History loading

On project open:

1. Load latest materialized project state.
2. Load history state.
3. Validate referenced history head.
4. Validate command schemas needed for available undo/redo.
5. Reconstruct labels for Undo/Redo UI.
6. Avoid replaying the entire project lifetime when a valid checkpoint exists.

**Acceptance:** the exact undo/redo availability and labels survive backend restart and portable save/open according to the project's included history.

---

## 7. Work package M6.5 — Persistent undo, redo, and divergent-history behavior

### 7.1 Undo operation

`POST /api/v1/projects/{id}/undo` accepts:

- expected project revision;
- optional expected command ID;
- idempotency key.

Backend:

1. Resolve current undoable command/batch.
2. Verify it is still valid for the current history head.
3. Validate stored inverse against current target identities.
4. Apply inverse transactionally.
5. Increment project revision.
6. Mark the original history entry undone in the active history generation.
7. Update redo pointer.
8. Recompute affected dependency status.
9. Emit revision/history events.

### 7.2 Redo operation

Redo:

1. Resolves the next redoable command.
2. Revalidates its normalized forward payload against the state produced by the undo chain.
3. Applies forward state transactionally.
4. Increments project revision.
5. Marks entry applied again.
6. Updates history state.
7. Emits events.

### 7.3 New edit after undo

When a new semantic edit occurs while redo entries exist:

1. Mark those redo entries as abandoned from the active history path.
2. Preserve their rows for audit/recovery diagnostics.
3. Start a new active history generation/segment.
4. Clear the redo pointer presented to the user.
5. Do not garbage-collect any asset solely because its creating command moved off the active history path until reference analysis proves it unreferenced.

### 7.4 Undo/redo labels

Expose human-readable labels such as:

- `Undo Move chord boundary`;
- `Redo Change bass note D2 → D3`;
- `Undo Reorder snippet queue`;
- `Undo Switch active rhythm result`.

Do not derive labels only in the browser; persist normalized command summaries or deterministic summary inputs.

### 7.5 Coalescing

Coalesce:

- drag motion;
- slider movement;
- zoom gesture;
- scroll gesture where view changes are historical;
- repeated key-based semitone changes performed inside one bounded gesture window when configured.

Do not coalesce unrelated semantic object edits merely because they occur close in time.

### 7.6 History limits

Do not enforce a small arbitrary count limit that silently destroys recent project history.

Control size through:

- compact payloads;
- checkpoints;
- optional history retention settings introduced only with clear semantics;
- explicit project maintenance, never opportunistic silent truncation.

### 7.7 Analysis jobs

Starting/completing an analysis job is not undoable as an analysis computation.

Undoable project actions include:

- selecting an analysis result;
- creating/editing branches;
- changing project-visible module settings where treated as project state.

The immutable result remains retained after undoing its selection.

**Acceptance:** undo/redo works across restart, preserves revision monotonicity, and handles divergent edits without hidden data destruction.

---

## 8. Work package M6.6 — Named historical revisions and history checkpoints

### 8.1 Named revision object

Define:

- UUID;
- project ID;
- name;
- optional description;
- referenced project revision;
- referenced history checkpoint/state identity;
- creation timestamp;
- optional tags.

### 8.2 User operations

Support:

- create named revision from current committed state;
- rename;
- edit description;
- delete bookmark metadata;
- inspect summary;
- restore.

Deleting a named revision must not delete assets/history still referenced elsewhere.

### 8.3 Restore semantics

Restoring a named revision does not decrement revision numbers or rewrite history.

Instead:

1. Resolve the named historical state.
2. Compare it to current project semantic state.
3. Build a grouped restore command containing the required reversible changes.
4. Apply as one new project revision.
5. Preserve newer immutable analysis artifacts unless the restored state simply stops referencing/selecting them.
6. Keep the pre-restore state undoable.

### 8.4 Internal history checkpoints

Create compact internal project-state checkpoints:

- after a configurable number of commands, initially about 500 semantic entries;
- before a command-schema retirement/migration;
- before large history maintenance operations;
- optionally before portable save when it improves reopen performance.

A checkpoint contains only project semantic metadata/state, not duplicated large PCM/model artifacts.

### 8.5 Checkpoint integrity

Record:

- project revision;
- history position;
- schema version;
- content hash;
- referenced asset/result IDs;
- creation reason.

Verify before using it as a reconstruction base.

**Acceptance:** long-lived projects can reopen and restore named historical states without replaying an unbounded command log or reusing old revision numbers.

---

## 9. Work package M6.7 — Unify Auto/Edited/model/input version selection

### 9.1 Analysis-family selection model

Define a common `AnalysisSelection` record for each family, initially:

- separation;
- rhythm;
- chords;
- key;
- bass transcription.

The record contains:

- family ID;
- selected automatic/result-set ID where relevant;
- selected edited branch ID only for families that define editable branches;
- mode: `auto` or `edited` only for editable families; separation uses immutable result-set selection with no generic Edited mode;
- selected model/input version metadata;
- last changed project revision.

Tuning remains an explicit project tonal context rather than pretending to be the same kind of immutable result family if its existing domain model differs.

### 9.2 Result catalog

Expose retained versions with:

- model/module name;
- model/checkpoint hash;
- input role/asset;
- creation timestamp;
- automatic/edited status;
- parent result;
- branch revision;
- current/stale/unavailable/corrupt status;
- concise stale reason;
- active-selection marker.

### 9.3 Switching behavior

Switching active result/branch:

1. Is an explicit project command.
2. Uses base revision and idempotency.
3. Does not delete the previous selection.
4. Updates every dependent UI view atomically.
5. Recomputes relative staleness of downstream selections.
6. Does not automatically start analysis.
7. Does not overwrite manual edits in any branch.

### 9.4 Auto/Edited toggle

The UI must not show an `Edited` choice unless the owning analysis family defines editable branches and an edited branch exists. Separation never shows a generic Edited toggle; mixer/project controls remain ordinary editable state outside the separation result.

If the user initiates an edit while viewing Auto:

- create the editable branch according to the owning milestone's semantics;
- make the edit in the same semantic transaction when practical;
- switch to Edited explicitly;
- preserve the immutable Auto parent.

### 9.5 Multiple model versions

For a family with multiple automatic results:

- each model/input pair remains distinct;
- edited branches remain attached to their parent automatic result;
- selecting model B does not rebase edits from model A automatically;
- a future explicit rebase/merge feature is not invented here.

### 9.6 Separation/transcription constraint

Selecting a new bass separation may make the currently selected transcription stale relative to the active bass stem.

It must not silently switch to another transcription or delete the old one.

### 9.7 Rhythm/harmony constraint

Selecting a different rhythm result affects only downstream analyses whose declared dependency includes that exact rhythm context.

Source-anchored chord/note branches do not become stale merely because the display grid changes unless their generating algorithm declared that dependency.

**Acceptance:** every analysis family uses one predictable retained-version selection UI; editable symbolic/annotation families additionally expose Auto/Edited state, while immutable separation result sets never acquire a synthetic Edited branch. Old outputs/corrections remain intact when the active version changes.

---

## 10. Work package M6.8 — Implement the normalized dependency and staleness graph

### 10.1 Dependency-node types

Represent graph nodes for:

- source/original asset;
- canonical audio representation;
- monitoring/downmix representation;
- separation result set;
- stem asset;
- rhythm automatic result;
- rhythm edited branch;
- tuning context/version;
- chord automatic result;
- chord edited branch;
- key automatic result;
- key edited branch;
- bass transcription automatic result;
- bass transcription edited branch;
- prepared analysis artifacts where required for diagnosis;
- export snapshot identities only when useful for provenance, not as active dependency nodes.

### 10.2 Edge record

Each edge stores:

- downstream node ID;
- upstream node ID;
- dependency role;
- expected upstream content/version identity;
- whether missing upstream bytes block use;
- cache-key participation;
- stale-impact policy;
- provenance description.

### 10.3 Staleness computation

For a downstream result:

1. Load declared dependency edges.
2. Resolve current active context only for edges marked as active-context-sensitive.
3. Compare expected identity with current identity.
4. Produce zero or more structured stale reasons.
5. Keep result `current` if no hard/decode dependency changed.
6. Mark `stale` when bytes are valid but context differs.
7. Mark `unavailable` when required result bytes are missing.
8. Mark `corrupt` when verified bytes/hash/schema fail.

### 10.4 Structured stale reason

Example:

```json
{
  "code": "BASS_STEM_CHANGED",
  "dependency_role": "hard_input",
  "expected_id": "stem-old",
  "current_id": "stem-new",
  "message": "This transcription was created from a different bass stem."
}
```

UI text is localized/formatted from structured codes where possible.

### 10.5 Dependency impact from commands

The command registry declares which dependency contexts may change.

After a relevant commit:

- recompute only affected downstream graph regions;
- avoid full-project graph scans for every view-state edit;
- emit status-changed events.

### 10.6 Stale-result retention

Stale results remain:

- selectable;
- inspectable;
- exportable when underlying required bytes exist;
- editable when domain invariants permit.

Display a warning that edits will remain tied to the stale parent/input unless the user chooses a current result.

### 10.7 No over-staling

Explicit regression tests ensure:

- chord display complexity does not stale chord detection;
- key spelling changes do not stale bass F0 when spelling is display-only;
- changing metronome volume does not stale rhythm analysis;
- waveform amplitude zoom does not stale anything;
- source-loop edits do not stale analysis;
- chord/key context used only for bass-note review does not stale transcription;
- active model selection does not corrupt or mutate retained nonactive results.

**Acceptance:** stale status is explainable, dependency-driven, selective, and consistent across every module.

---

## 11. Work package M6.9 — Add project-wide stale/unavailable/corrupt UI

### 11.1 Status surfaces

Show status in:

- analysis-module toolbar;
- result/version selector;
- relevant lane header;
- inspector;
- project diagnostics/storage panel;
- export confirmation when exporting a noncurrent result.

### 11.2 Status language

Use distinct labels:

- Current;
- Stale;
- Unavailable;
- Corrupt;
- Incomplete;
- Rebuilding optional cache.

Do not use one generic warning icon for all cases.

### 11.3 Stale details panel

For a selected result, show:

- what changed;
- old dependency;
- current dependency;
- whether result remains safe to view/edit/export;
- whether rerun is possible;
- whether required model is installed;
- what action would create a current result.

### 11.4 Do not force reruns

A stale badge must not automatically start a model.

The user chooses whether to:

- keep using stale result;
- switch to an existing current result;
- rerun analysis;
- install a missing model first;
- dismiss/collapse warning while preserving status.

### 11.5 Project overview

Add a compact dependency-health summary:

- current modules;
- stale modules;
- unavailable modules;
- corrupt optional artifacts;
- jobs requiring attention.

This is a status overview, not a new analysis dashboard.

**Acceptance:** the user can identify exactly why a result is stale or unusable without inspecting database records or logs.

---

## 12. Work package M6.10 — Harden revision conflicts and idempotency

### 12.1 Conflict response

For a semantic command whose base revision is stale, return HTTP `409` with:

- error code `REVISION_CONFLICT`;
- submitted base revision;
- current revision;
- current active analysis selections relevant to the command when useful;
- target object existence/revision summary;
- request ID;
- whether an exact idempotent retry was recognized.

### 12.2 No silent rebase

Do not automatically apply a stale semantic edit to new state simply because target IDs still exist.

Manual musical edits can conflict semantically even when fields are different.

### 12.3 Browser conflict workflow

When a conflict occurs:

1. Preserve the user's pending gesture intent in frontend memory where practical.
2. Fetch the latest authoritative project state/delta.
3. Show what changed.
4. Re-render current objects.
5. Offer `Retry on current state` only when the command can be reconstructed safely from user intent.
6. Otherwise require the user to perform the edit again.
7. Never overwrite newer state silently.

### 12.4 Object-level revisions

Where analysis branches already have branch revisions, include them in conflict validation.

A command may require both:

- base project revision;
- base branch revision.

This catches stale branch editing even if future project architecture permits nonsemantic revision domains.

### 12.5 Idempotency persistence

Persist idempotency records long enough to cover browser/network retries across restart.

Record:

- key;
- project;
- normalized request fingerprint;
- response identity/resulting revision;
- expiration/retention policy.

Reuse of a key with a different normalized body returns `409`.

### 12.6 Undo/redo idempotency

Undo/redo requests also use idempotency keys.

Repeated delivery of one undo request must not undo two commands.

### 12.7 Concurrent job requests

Analysis/export/cache-cleanup requests continue to use durable job idempotency/coalescing rules separate from semantic project edits.

**Acceptance:** stale tabs and network retries cannot silently duplicate or overwrite project edits.

---

## 13. Work package M6.11 — Complete revision/event synchronization across browser tabs

### 13.1 Project revision events

Use the existing `/api/v1/events` WebSocket architecture or complete it where prior milestones used polling.

Emit event IDs and project-scoped messages for:

- project revision committed;
- history state changed;
- active result selection changed;
- stale status changed;
- job status changed;
- asset integrity status changed;
- recovery state changed;
- cache cleanup complete;
- export complete.

### 13.2 Event payload principle

Events are notifications, not the sole authoritative state.

Include compact identifiers/revisions, not entire project snapshots or large artifact arrays.

### 13.3 Reconnection

On reconnect:

1. Send/retain last seen event ID.
2. Backend determines whether missed event replay is available.
3. If replay is unavailable, client refetches current project state.
4. Client compares project revision.
5. Never assume no change occurred during disconnect.

### 13.4 Open-tab behavior

When another tab commits a revision:

- update revision indicator;
- refetch affected state;
- cancel/rebase only transient frontend gestures that depended on old object geometry;
- do not stop playback unless changed state requires transport reconfiguration;
- display a nonintrusive message when a visible edit context was changed externally.

### 13.5 Session identity

Give each browser tab/session a nonsecret session ID for diagnostics and conflict messages.

Do not treat session ID as authentication.

**Acceptance:** two open tabs cannot drift indefinitely into contradictory editable state without clear revision synchronization/conflict handling.

---

## 14. Work package M6.12 — Add clean-shutdown records and startup crash detection

### 14.1 Session record

Persist application session metadata:

- session UUID;
- start timestamp;
- application version;
- database version;
- clean-shutdown flag;
- shutdown timestamp;
- projects open/active at last durable state where useful;
- running job IDs;
- runtime PID for diagnostics only.

### 14.2 Startup sequence after clean shutdown

1. Open database.
2. Apply migrations.
3. Verify prior session marked clean.
4. Clean known expired temporary session files.
5. Resume ordinary job/recovery checks.
6. Start service.

### 14.3 Startup sequence after unclean shutdown

1. Let SQLite perform normal WAL recovery.
2. Run targeted integrity checks before writes.
3. Mark previous `running/cancelling` jobs interrupted.
4. Scan owned staging manifests.
5. Verify asset publication state.
6. Identify complete-but-unreferenced assets.
7. Identify incomplete temporary output.
8. Reconcile portable-save temporary files.
9. Create a recovery report.
10. Start project access in a safe state.

### 14.4 Integrity checks

Use bounded startup checks:

- `PRAGMA quick_check` normally after unclean shutdown;
- stronger integrity check only when quick check fails or explicitly requested;
- foreign-key check;
- schema version validation;
- selected referenced-asset existence checks.

Do not hash every gigabyte-scale PCM/stem asset at every startup.

### 14.5 Recovery state

Expose:

- `clean`;
- `recovery_available`;
- `recovery_in_progress`;
- `recovery_attention_required`.

### 14.6 Clean shutdown

On orderly shutdown:

1. Stop accepting new semantic mutations/jobs.
2. Flush pending debounced view-state commit.
3. Persist history state.
4. Request worker shutdown.
5. Mark remaining owned running jobs interrupted if necessary.
6. Close resources.
7. Flush logs.
8. Mark session clean only after durable state is complete.

**Acceptance:** an unclean exit is distinguishable from ordinary startup and committed edits survive without manual database repair.

---

## 15. Work package M6.13 — Implement working-project crash recovery

### 15.1 Recovery principle

The last committed semantic transaction is authoritative.

Do not attempt to reconstruct an in-progress drag or unsubmitted text edit after a process crash.

### 15.2 SQLite recovery

Rely on SQLite WAL transaction guarantees for committed metadata.

Recovery logic must not copy only the main database while ignoring live WAL state.

### 15.3 Job recovery

For jobs interrupted at crash:

- preserve published completed dependencies;
- mark job `interrupted`;
- retain retry parameters;
- discard/inspect staging according to ownership manifest;
- never expose partial output as complete;
- permit explicit restart from the owning milestone's safe boundary.

### 15.4 Staging ownership manifest

Every long-running operation that writes staging bytes has a small manifest containing:

- operation/job ID;
- owning project where applicable;
- intended output type;
- expected parent identities;
- creation timestamp;
- publication target category;
- completion marker/hash when final validation finished.

### 15.5 Complete-but-unreferenced output

If a crash occurred after atomic file publication but before DB attachment:

- classify the object as an orphan complete asset;
- verify its metadata/hash lazily or during recovery;
- do not attach it automatically unless the job's publication transaction can be proven;
- allow cache cleanup to reclaim it later;
- optionally offer diagnostic recovery when a deterministic transformation key proves it matches an interrupted job.

### 15.6 Recovery UX

Show a concise report:

- last session ended unexpectedly;
- committed project edits recovered automatically;
- interrupted jobs count;
- incomplete staging removed/quarantined count;
- any items requiring user attention.

Do not alarm the user when SQLite recovered normally and no data is at risk.

### 15.7 Portable-save recovery

For an interrupted portable save:

- keep last successful target archive;
- inspect temporary candidate only if it reached closed/verified state;
- never replace the known-good archive with an unverified temp file;
- permit explicit promotion of a fully verified candidate only if publication metadata proves it represented the requested revision.

**Acceptance:** killing the backend during edits/jobs/save cannot produce a project that points to partial artifacts or loses already committed semantic edits.

---

## 16. Work package M6.14 — Add project recovery and integrity diagnostics

### 16.1 Project health endpoint/service

Provide a project health operation returning:

- database/project schema status;
- referenced asset existence summary;
- optional cache status;
- corrupt/missing items;
- stale result count;
- unavailable result count;
- interrupted jobs;
- last clean save/revision;
- recovery recommendations.

### 16.2 Fast versus deep verification

Support:

- **fast verification:** metadata/existence/size/basic schema checks;
- **deep verification:** hashes and full artifact validation, explicit user action or recovery need.

Do not deep-hash all audio automatically on every open.

### 16.3 Diagnostic report

Allow export/copy of a privacy-conscious diagnostic report containing:

- application/tool versions;
- project schema versions;
- anonymized/opaque asset IDs;
- error codes;
- integrity status;
- no audio samples;
- no authentication token;
- no arbitrary absolute source paths unless explicitly requested.

**Acceptance:** recovery decisions can be explained with structured project-health evidence rather than generic errors.

---

## 17. Work package M6.15 — Define missing-asset and corruption classification

### 17.1 Asset classes

Classify project-referenced data as:

1. **Essential irreplaceable project state**
   - project database/snapshot metadata;
   - manual edits/branches/history not recoverable elsewhere.
2. **Essential media for a particular workflow**
   - source/canonical audio required for playback;
   - selected stem required for that stem/transcription playback.
3. **Retained automatic analysis result data**
   - decoded regions/notes/pulses required to show the result.
4. **Optional diagnostic/evidence artifacts**
   - framewise logits;
   - F0 evidence arrays;
   - activation arrays when decoded/edited results remain independently usable according to module policy.
5. **Rebuildable cache**
   - waveform tiles;
   - browser-rate playback representations;
   - prepared analysis inputs where source/dependencies exist.
6. **External runtime/model files**
   - not project assets; absence affects rerun, not saved-result readability.

### 17.2 Missing source/canonical audio

If canonical audio is missing:

- source-independent metadata/edit state may still open;
- playback/waveform become unavailable;
- do not delete analysis results;
- if original imported media exists and decode can be rerun, offer explicit rebuild;
- rebuilt canonical bytes receive their actual identity;
- downstream results become stale/unavailable as dictated by exact identity requirements rather than pretending byte identity is unchanged.

### 17.3 Missing waveform cache

- mark waveform pending/missing cache;
- rebuild automatically or on demand according to existing cache policy;
- do not mark analysis stale;
- do not treat missing peaks as missing audio.

### 17.4 Missing raw analysis evidence

If decoded automatic result or edited branch state remains complete:

- preserve result/edits;
- disable only raw-evidence inspection/redecoding features that require the missing artifact;
- show `optional evidence unavailable`;
- rerun only on explicit request.

### 17.5 Missing decoded result required by an edited branch

If branch persistence contains complete edited objects independent of parent decoded bytes:

- keep branch usable;
- retain provenance link as missing parent;
- label automatic parent unavailable.

If branch representation relies on a delta that cannot be resolved without its parent:

- branch becomes unavailable;
- do not invent materialized objects.

Milestone 6 should prefer migration toward self-sufficient materialized edited branch state where practical.

### 17.6 Corrupt asset

On hash/format failure:

- quarantine logically; do not serve bytes as trusted content;
- record error and expected/actual identity;
- preserve original archive/file unchanged;
- offer rebuild only if deterministic upstream inputs exist;
- otherwise report unrecoverable workflow portion precisely.

### 17.7 Missing model/runtime

This is not project corruption.

Existing results remain usable.

Only rerun/install actions report model/runtime unavailability.

**Acceptance:** the application distinguishes missing cache, missing model, stale result, unavailable result, and corrupt essential asset without conflating them.

---

## 18. Work package M6.16 — Implement repair/rebuild workflows

### 18.1 Repair planner

Given project-health findings, generate actions such as:

- rebuild waveform cache;
- rebuild playback-rate representation;
- re-decode canonical audio from preserved original;
- rerun a selected analysis;
- re-download/reinstall a registered model;
- relink no arbitrary external files automatically;
- remove abandoned staging;
- restore from previous portable archive/save.

### 18.2 Safe rebuild rule

A rebuild publishes a new validated asset/result under the owning module's existing transformation/cache identity rules.

Do not mutate corrupt bytes in place.

### 18.3 User confirmation

Require confirmation for operations that:

- consume substantial disk/compute;
- alter active analysis selection;
- create a new canonical identity;
- invalidate downstream results;
- delete quarantined data.

### 18.4 No magic reconstruction

If required information is gone, say so.

Do not recreate manual corrections from machine inference and present them as recovered edits.

### 18.5 Previous portable save

Where the managed save procedure retains one previous successful archive artifact, offer it as a recovery source/download without overwriting any browser-downloaded file automatically.

**Acceptance:** repair actions are explicit, identity-preserving, and never disguise regenerated data as the original missing object.

---

## 19. Work package M6.17 — Complete project/database/portable schema migration framework

### 19.1 Version domains remain separate

Continue to keep separate:

- application version;
- HTTP API version;
- SQLite database schema version;
- project serialization schema version;
- portable archive manifest version;
- worker protocol version;
- individual artifact format versions;
- command-schema versions.

### 19.2 Database migrations

For every DB migration:

1. Check current `user_version`/managed schema version.
2. Reject unsupported newer versions.
3. Create a consistent backup before modifying a nonempty existing DB when required by the existing migration policy.
4. Run migration transactionally.
5. Update version only after successful changes.
6. Run foreign-key/schema validation.
7. Record migration outcome.
8. Keep backup after failure.

### 19.3 Portable project migrations

Opening an older archive:

1. Validate manifest first.
2. Extract into a managed temporary/working location with path and size protections.
3. Verify original archived asset hashes before migration where applicable.
4. Preserve the original archive unchanged.
5. Migrate the extracted working copy.
6. Record original archive version and migration chain.
7. Require an explicit new Save to produce an upgraded archive.

### 19.4 Project semantic migrations

Migrations must preserve:

- source-frame timing;
- immutable result IDs where possible;
- editable branch object IDs;
- review state;
- command/history meaning;
- active result selections;
- stale dependency declarations;
- loops/markers/mixer/view state.

### 19.5 Command-history migration

If a command cannot be upgraded safely:

- materialize current semantic state into a verified checkpoint;
- preserve old history as read-only/audit data where possible;
- define the new undo baseline honestly;
- do not invent replayability.

### 19.6 Migration fixtures

Maintain fixtures for at least:

- Milestone 0 empty project;
- Milestone 1 imported project with markers;
- Milestone 2 separated project with mixer/loops;
- Milestone 3 rhythm branch/metronome/musical loop;
- Milestone 4 chord/key/tuning edits;
- Milestone 5 transcription edits/MIDI settings;
- stale-result project;
- interrupted-job project;
- project with optional missing caches;
- portable archives from each supported manifest version.

### 19.7 Migration idempotency

Opening an already migrated working project must not rerun a migration or duplicate records.

### 19.8 Unsupported newer schema

- refuse write access;
- explain supported/current version;
- preserve original bytes;
- optionally permit limited metadata inspection only if explicitly safe and schema-independent;
- never downgrade silently.

**Acceptance:** every supported historical fixture opens to equivalent project semantics, and migration failure leaves original data intact.

---

## 20. Work package M6.18 — Harden portable project save/open around stable revisions

### 20.1 Save snapshot revision

When save begins:

1. Resolve current committed project revision `R`.
2. Create a consistent SQLite/project snapshot at `R`.
3. Freeze the list of references reachable from that snapshot.
4. Permit later edits to continue in working storage.
5. Exclude later revision `R+1...` changes from this archive.
6. Display `Saving revision R` when useful for diagnostics.

### 20.2 History in portable archive

Include:

- current project state;
- persistent command history required for continued undo/redo;
- history state/head;
- named revisions intended to travel with the project;
- required history checkpoints.

Do not include unrelated abandoned cache data simply because an old command once referenced it.

### 20.3 Reachability traversal

Collect assets through explicit references from snapshot state, retained result versions/history protection rules, and portable-save policy.

Do not scan arbitrary cache directories by filename.

### 20.4 Integrity manifest

Manifest records:

- project/archive schema versions;
- application build metadata;
- project ID/revision;
- included asset paths;
- hashes;
- byte sizes;
- roles;
- required/optional classification;
- model provenance without model weights;
- history/checkpoint metadata.

### 20.5 Save concurrency

While save runs:

- edits may continue against working DB;
- analysis jobs may continue;
- cache cleanup must pin assets selected for save;
- project close/shutdown must either finish/cancel safely according to job policy;
- save job uses frozen snapshot references.

### 20.6 Open behavior

After extraction/validation:

- load project state/history;
- evaluate missing optional artifacts;
- evaluate staleness relative to saved active selections;
- do not contact network;
- do not run models;
- do not upgrade archive in place.

**Acceptance:** portable save is revision-consistent and reopens with undo/redo, selections, stale status, snippets, presets/project state, and manual corrections intact.

---

## 21. Work package M6.19 — Build snippet-queue domain objects

### 21.1 Queue schema

Define `SnippetQueue`:

- UUID;
- project ID;
- name;
- ordered entry IDs;
- enabled/active state;
- creation/update timestamps;
- optional description;
- optional default transition/fade policy.

### 21.2 Queue-entry schema

Each `SnippetQueueEntry` contains:

- UUID;
- queue ID;
- order index/order key;
- name/label override;
- anchor mode: `source` or `musical`;
- start/end source frames when source-anchored;
- start/end musical positions when musical-anchored;
- resolved source bounds cache with grid identity when musical;
- repeat count, minimum 1;
- enabled flag;
- boundary-fade setting;
- optional linked saved-loop ID;
- creation/update timestamps.

### 21.3 Linked-loop versus owned interval

When created from a saved loop, let the user choose/define one deterministic policy.

Milestone 6 default decision:

- queue entry stores its own anchor interval copied from the loop at creation;
- it also stores provenance `created_from_loop_id`;
- later loop edits do not silently change the queue entry.

This avoids a practice queue changing unexpectedly because a loop was adjusted elsewhere.

### 21.4 Create entries from

Support:

- current selection;
- active loop;
- selected note/chord/bar/section range;
- explicit numeric source bounds;
- explicit musical bounds when a valid grid exists.

### 21.5 Validation

- source interval must be inside project duration;
- musical interval must resolve monotonically through the selected active grid;
- empty/negative intervals rejected;
- repeat count bounded to a safe integer;
- queue may contain disabled entries;
- queue must have at least one enabled valid entry to start playback.

### 21.6 Commands

Add command types for:

- create/delete/rename queue;
- add/remove entry;
- reorder entries;
- edit entry bounds;
- rename entry;
- change repeat count;
- toggle entry;
- change anchor mode where valid;
- duplicate entry/queue;
- set active queue.

All participate in persistent undo/redo.

**Acceptance:** noncontiguous practice material is represented as stable revisioned project state independent of transient playback state.

---

## 22. Work package M6.20 — Integrate snippet-queue playback with the shared transport

### 22.1 Queue playback state

Transport tracks:

- active queue ID;
- current entry ID/index;
- current pass within entry repeat count;
- queue-playing flag;
- upcoming entry prebuffer state;
- transport generation;
- source position.

Transient current pass/index is not necessarily undo history; queue structure/settings are.

### 22.2 Start behavior

Starting queue playback:

1. Resolve active queue at a stable project revision.
2. Resolve musical entries through the current selected rhythm/grid.
3. Validate enabled entries.
4. Prepare first entry pre-roll/buffers.
5. Prebuffer the next enabled entry within memory limits.
6. Start through the existing source/render-clock transport path.

### 22.3 Entry transitions

At entry end:

1. Complete the configured repeat count.
2. Apply the existing short boundary-fade policy.
3. Switch source mapping to the next entry.
4. Keep stems synchronized.
5. Reset/prime time-stretch state according to the established finite-segment transport rules.
6. Preserve metronome/count-in semantics.
7. Update visible source playhead discontinuously to the new entry start.
8. Do not pretend noncontiguous source regions are one continuous source-time interval.

### 22.4 Prebuffering

- prefetch next entry's active audio streams;
- pin required ranges while transition is near;
- do not load an entire long queue into browser memory;
- cancel obsolete prefetch after queue reorder/stop;
- if next entry is not ready, enter coherent buffering rather than outputting misaligned streams.

### 22.5 Count-in policy

Use existing count-in settings.

Add queue-specific option:

- count in at queue start only;
- before every queue entry;
- follow existing `before every repeat` semantics where applicable.

Keep count-in separate from source time.

### 22.6 Metronome

For musical/grid-valid entries:

- metronome follows source→musical mapping of the entry;
- correct bar phase at entry start;
- rebuild future events at each noncontiguous transition.

For source entries without valid meter context:

- use mapped tempo only where available;
- do not fabricate bar accents.

### 22.7 Mid-play edits

If queue structure changes while playing:

- retain current entry until a controlled boundary when safe;
- recompute upcoming sequence from new committed queue revision;
- if current entry is deleted/resized incompatibly, stop or transition through explicit controlled buffering rather than using stale bounds.

### 22.8 End behavior

After final enabled entry/pass:

- stop at that entry's end;
- queue remains selected;
- pressing Play Queue restarts from first enabled entry unless user selected another start entry.

**Acceptance:** a queue of noncontiguous source/musical passages plays at all supported speeds without stem drift, cumulative timing error, or unbounded buffering.

---

## 23. Work package M6.21 — Create a centralized action and keyboard-shortcut registry

### 23.1 Action registry

Define stable action IDs separate from physical keys, for example:

- `transport.play_pause`;
- `transport.seek_left_1s`;
- `transport.seek_right_1s`;
- `transport.seek_left_bar`;
- `transport.seek_right_bar`;
- `transport.go_start`;
- `transport.go_end`;
- `loop.toggle`;
- `metronome.toggle`;
- `history.undo`;
- `history.redo`;
- `selection.delete`;
- `view.zoom_in`;
- `view.zoom_out`;
- `stem.1.solo` ...;
- `stem.1.mute` ...;
- `editor.cancel`.

The action registry owns enabled/disabled context, not React component key handlers.

### 23.2 Default mappings

Implement the main-plan defaults:

| Key | Action |
|---|---|
| Space | Play/pause |
| L | Toggle active loop |
| Left/right | Seek one second |
| Shift + left/right | Seek one bar when grid exists |
| Home/End | Start/end |
| `+` / `-` | Horizontal zoom |
| 1–9 | Toggle corresponding stem solo |
| Shift + 1–9 | Toggle corresponding stem mute |
| M | Metronome toggle |
| Ctrl/Cmd + Z | Undo |
| Ctrl/Cmd + Shift + Z | Redo |
| Delete | Delete selected editable objects |
| Escape | Cancel gesture/close editor |

Add explicit bindings for snippet-queue navigation only if they do not conflict with this required baseline; otherwise leave them remappable/unbound by default.

### 23.3 Shortcut representation

Represent a shortcut as:

- physical/logical key policy;
- modifier set;
- action ID;
- context scope;
- platform normalization.

Use logical keys for common character shortcuts and explicit codes where layout-independent behavior is necessary. Test non-US keyboard implications before relying on physical key codes.

### 23.4 Context suppression

Disable ordinary transport/edit shortcuts when focus is in:

- text input;
- textarea;
- contenteditable;
- numeric editor actively typing;
- modal shortcut-capture field.

Allow Escape and explicitly safe dialog shortcuts according to modal behavior.

### 23.5 Shortcut remapping UI

Provide settings UI to:

- search actions;
- view current mapping;
- capture a new key chord;
- remove optional mapping;
- reset one action;
- reset all to defaults;
- show conflicts;
- reject reserved/browser-unsafe combinations when necessary.

### 23.6 Conflict rules

Two enabled actions cannot share the same shortcut in overlapping contexts unless an explicit deterministic priority rule exists.

Prefer rejection with a clear conflict message over implicit winner behavior.

### 23.7 Persistence

Store custom mappings in user configuration, not project database/archive.

Include configuration schema version and migration.

### 23.8 Accessibility

Every shortcut-triggered function remains available through visible controls/menus.

Shortcut-only access is not acceptable for essential editing.

**Acceptance:** all required default shortcuts work, remapping persists across app restart, conflicts are detected, and typing never triggers destructive editor actions.

---

## 24. Work package M6.22 — Define versioned export presets

### 24.1 Export preset record

Define:

- preset ID;
- name;
- schema version;
- output kind: audio or analysis;
- source-selection policy;
- region policy;
- format;
- sample-rate policy;
- bit-depth/codec settings;
- normalization policy;
- mixer application policy;
- speed policy;
- naming template;
- metadata/provenance options;
- overwrite/collision policy;
- creation source: built-in/user.

### 24.2 Built-in audio presets

Provide at least:

1. `Aligned stems — WAV 24-bit`
   - full duration;
   - project sample rate;
   - normalization off;
   - individual aligned stems.
2. `Current mix — WAV 24-bit`
   - current mixer output;
   - full duration or selected region.
3. `Selection — FLAC`
   - active selected time range;
   - compatible integer depth.
4. `Practice mix — MP3 320 kb/s`
   - current mixer output;
   - compatible sample rate;
   - user chooses original/practice speed.

Preset names/settings are implementation defaults and remain editable/duplicable where appropriate.

### 24.3 Built-in analysis presets

Provide:

- `Complete analysis JSON`;
- `Editable analysis CSV set`;
- `Chord labels (.lab)`;
- `Bass MIDI` using existing Milestone 5 exporter;
- `Markers and loops CSV`.

### 24.4 User-defined presets

Support:

- duplicate built-in;
- rename;
- edit;
- delete user preset;
- reset built-ins;
- import/export preset JSON only if schema validation is implemented safely.

Do not let a project archive silently replace user-global presets.

### 24.5 Storage scope

- built-ins live in application code/config;
- user presets live in user configuration/data;
- project stores last-used preset ID/settings snapshot only when useful;
- export job stores a complete immutable resolved preset snapshot.

### 24.6 Validation

Validate combinations before job creation.

Examples:

- MP3 bit depth is not a valid parameter;
- FLAC float32 may be unsupported under selected profile;
- MP3 sample rate must be codec-compatible;
- stem export cannot apply current stereo mixer sum unless user selected a processed-stem/mix mode;
- linked normalization only applies to a set of outputs.

**Acceptance:** export behavior is reproducible from an immutable resolved preset rather than scattered dialog state.

---

## 25. Work package M6.23 — Generalize durable audio export jobs

### 25.1 Export job snapshot

At job creation, freeze:

- project revision;
- source/result IDs;
- selected stems/tracks;
- mixer state if applicable;
- region/loop/queue definition;
- playback speed if applicable;
- resolved export preset;
- delivery mode and browser download filename (the backend does not rely on an arbitrary browser-selected filesystem path);
- application/FFmpeg profile versions.

Later project edits do not alter the running job.

### 25.2 Supported source modes

Support:

- original audio;
- one stem;
- multiple individual stems;
- selected stems as one mix;
- current mixer output;
- active time selection;
- saved loop;
- snippet queue.

### 25.3 Common alignment

For multi-file stems:

- preserve common source start;
- preserve requested full source duration by default;
- use the same project sample rate unless user chose compatible conversion;
- do not independently trim silence from stems.

### 25.4 Mixer-render path

For a mix export:

- apply selected track mute/solo/gain/pan/balance;
- use the frozen job mixer snapshot;
- apply master gain where specified;
- monitoring limiter is applied only when the export preset explicitly includes it; do not assume live monitoring limiter belongs in raw export.

### 25.5 Normalization

Support:

- off;
- linked peak normalization for a multi-stem set;
- independent peak normalization, separately labelled;
- mix normalization according to selected profile.

Record gain applied.

Do not normalize by default.

### 25.6 Dither

When reducing floating-point PCM to lower integer depth:

- use a documented dither profile;
- do not dither float output;
- record encoder/filter settings.

### 25.7 Disk and publication

Before export:

- estimate output size where possible;
- verify managed export staging/storage has sufficient free space;
- write temporary output inside managed export staging on the same filesystem as managed publication;
- validate encode completion;
- probe output;
- publish the managed artifact atomically;
- expose it through an authenticated download endpoint using `Content-Disposition`;
- let the browser/user choose the final filesystem location and collision handling outside backend project semantics.

### 25.8 Progress/cancellation

Report:

- rendering/preparing;
- encoding;
- validating;
- publishing.

Cancellation:

- terminate owned FFmpeg/helper processes;
- remove incomplete temp output;
- keep previously published files intact.

**Acceptance:** audio exports are durable, revision-consistent, cancellable, and never mix source/result identities from different project revisions.

---

## 26. Work package M6.24 — Add FLAC export

### 26.1 FLAC profiles

Expose supported integer depths, initially:

- 16-bit;
- 24-bit;

Add other depths only after verifying the installed FFmpeg encoder behavior and frontend compatibility.

### 26.2 Sample rate

Default to project/source sample rate where FLAC supports it.

If conversion is requested:

- use the existing versioned resampling quality profile or an export-specific documented profile;
- preserve alignment across multi-stem outputs.

### 26.3 Metadata

Optionally write basic project metadata where safe:

- title/project name;
- stem role;
- export profile/version.

Do not embed private absolute source paths or model paths.

### 26.4 Validation

After encode:

- ffprobe codec/sample rate/channel count;
- duration/frame-equivalent tolerance;
- decode smoke test on representative fixtures;
- verify no unintended normalization.

### 26.5 Lossless round-trip tests

For integer-compatible source fixtures, decode exported FLAC and compare against the quantized expected PCM.

For float source, compare after the selected quantization/dither policy rather than expecting original float bit identity.

**Acceptance:** FLAC exports preserve intended timing/channels and documented integer conversion behavior.

---

## 27. Work package M6.25 — Add MP3 export

### 27.1 Encoder detection

Use the installed FFmpeg build's available MP3 encoder.

Record encoder name/build identity.

Do not promise `libmp3lame` specifically unless present in the deployed build.

### 27.2 Bitrate options

Provide validated choices such as:

- 128 kb/s;
- 192 kb/s;
- 256 kb/s;
- 320 kb/s when supported.

Do not show a bitrate the selected encoder rejects.

### 27.3 Sample-rate compatibility

Present compatible output sample rates.

If project rate is not suitable for the chosen MP3 profile:

- show the conversion explicitly;
- resample once before/within encode;
- record output rate.

### 27.4 Timing caveat

MP3 encoding can introduce codec delay/padding and is not a sample-exact PCM interchange format.

Validation uses decoded audible duration/timing tolerance and encoder metadata where available.

Do not promise exact PCM round-trip alignment for MP3.

### 27.5 Gapless metadata

Where FFmpeg/encoder writes delay/padding metadata, retain it normally and verify playback decoders handle representative exports.

Do not manually trim twice.

### 27.6 Tags

Allow basic optional tags:

- title;
- artist if present in project metadata;
- comment identifying basseparate export profile.

### 27.7 Tests

Test:

- mono;
- stereo;
- 44.1 kHz;
- 48 kHz;
- a rate requiring conversion;
- full song;
- short selection;
- queue export;
- cancellation;
- existing destination collision.

**Acceptance:** MP3 export produces playable files with explicit bitrate/sample-rate choices and no claim of sample-exact lossless timing.

---

## 28. Work package M6.26 — Define original-speed and practice-speed export behavior

### 28.1 Original speed

Original-speed export is the reference/canonical audio-export path.

It uses source-time region boundaries directly.

### 28.2 Practice-speed export profile

The main plan permits exporting at practice speed.

Implement this as a separately versioned offline time-stretch stage.

Requirements:

- pitch preserved;
- requested speed 0.25×–2.0×;
- deterministic profile/version recorded;
- source region resolved before stretching;
- finite-signal latency/tail handled;
- resulting duration validated;
- no source annotations rewritten.

### 28.3 Engine identity

Do not label an offline export as `Signalsmith live playback` unless it actually uses the same pinned Signalsmith processing core/profile.

Preferred implementation order:

1. Reuse the pinned Signalsmith core in a backend-owned offline renderer if it can be packaged reproducibly.
2. If a different durable offline engine/profile is used, expose its identity in the preset/provenance and benchmark quality separately.
3. Never silently substitute a different engine while claiming exact live-playback equivalence.

### 28.4 Snippet/loop duration

For each source interval:

```text
expected_output_duration ≈ source_duration / speed
```

Allow documented DSP endpoint/tail tolerance.

For snippet queues, stretch each resolved entry under one consistent profile and concatenate through the defined transition policy.

### 28.5 Mixer/limiter ordering

Use an explicit offline graph matching the intended live semantics as closely as practical:

```text
source/stems -> per-track mix -> time stretch -> optional export limiter/master -> encode
```

Do not apply monitoring-only processing unless the preset says so.

**Acceptance:** practice-speed export is reproducible, pitch-preserving, and clearly identifies its offline processing engine/profile.

---

## 29. Work package M6.27 — Implement snippet-queue audio export

### 29.1 Queue snapshot

Freeze:

- queue revision;
- enabled ordered entries;
- resolved source bounds/grid identity;
- repeat counts;
- transition fades;
- selected active audio source/mixer state;
- speed profile.

### 29.2 Output modes

Initial mode:

- one concatenated audio file representing the queue in order.

Optional additional mode if implementation cost is low:

- one file per entry with stable sequence numbering.

Do not make the optional mode a completion requirement unless implemented/tested.

### 29.3 Transition handling

Between noncontiguous entries:

- use configured short fades;
- do not insert unintended source audio between entries;
- no overlap that changes displayed snippet duration unless preset explicitly defines a crossfade;
- record transition policy.

### 29.4 Source-time provenance sidecar

For concatenated queue export, create optional/paired provenance metadata describing output-time ranges mapped to source intervals.

This is important because the concatenated file no longer has one continuous source-time mapping.

### 29.5 Analysis annotations

Do not automatically rewrite chord/note/beat timestamps into concatenated queue time unless the user selects a corresponding analysis-export mode designed for queue remapping.

**Acceptance:** queue export reflects exactly the selected ordered practice passages and records enough provenance to understand the noncontiguous source mapping.

---

## 30. Work package M6.28 — Implement project-wide analysis export schemas

### 30.1 Complete analysis JSON

Define a versioned JSON export containing selected/project-visible analysis state:

- export schema version;
- project ID/name;
- source sample rate/frame count/hash identity;
- selected result/branch identities;
- model/module provenance;
- tuning context;
- beats/downbeats;
- tempo anchors;
- meter regions/grouping;
- bar-origin/pickup state;
- chords;
- keys;
- bass notes/gestures;
- markers/sections;
- loops;
- snippet queues;
- confidence/review state;
- stale status/reasons;
- source-frame timing and derived seconds;
- musical positions where available.

Do not embed large raw activation/logit/F0 arrays by default.

### 30.2 Raw evidence option

If the user explicitly requests diagnostic evidence export:

- package referenced binary artifacts or documented summaries;
- preserve artifact format/version/hash;
- keep this separate from the ordinary compact analysis JSON preset.

### 30.3 CSV export set

Use one CSV per event family where schemas differ, for example:

- `beats.csv`;
- `tempo.csv`;
- `meter.csv`;
- `chords.csv`;
- `keys.csv`;
- `bass_notes.csv`;
- `markers.csv`;
- `loops.csv`;
- `snippets.csv`.

Common fields where applicable:

- object ID;
- start/end source frame;
- start/end seconds;
- musical position/bar-beat if resolved;
- label/value;
- confidence kind/value;
- review state;
- provenance/result ID.

### 30.4 Chord `.lab`

Export timestamped chord labels using source seconds.

Rules:

- explicit selected Auto/Edited branch;
- preserve `N`/no-chord and unknown according to documented label convention;
- preserve custom labels text safely;
- use half-open region semantics internally while writing conventional timestamps;
- record result provenance in a sidecar or companion metadata when `.lab` cannot carry it.

### 30.5 Bass MIDI

Reuse the Milestone 5 MIDI exporter.

Milestone 6 adds:

- preset integration;
- explicit result/version selector;
- global export job/provenance handling;
- cache/storage destination behavior.

Do not rewrite pitch-decoding semantics.

### 30.6 Tempo/time-signature MIDI

Where representable:

- export tempo events from the selected active rhythm map;
- export time-signature events at valid bar/meter boundaries;
- use a documented PPQ;
- handle variable tempo with enough event resolution/tolerance;
- state limitations for unusual denominators/groupings not directly representable in standard MIDI meta events.

### 30.7 Markers/loops

Export marker/loop interval lists with:

- names;
- source frames;
- seconds;
- musical anchors when present;
- anchor mode;
- repeat count for loops;
- snippet queue membership/order where relevant.

### 30.8 Auto/Edited explicitness

Every analysis export request either:

- specifies exact result/branch IDs; or
- resolves the current project selections into exact IDs at job creation.

The output provenance includes those IDs.

**Acceptance:** exported analysis is machine-readable, versioned, source-time grounded, and explicit about which result/branch produced each dataset.

---

## 31. Work package M6.29 — Add export UX, naming, collision, and provenance handling

### 31.1 Export dialog

Provide:

- export kind;
- source/result selection;
- Auto/Edited/model/input version summary;
- region selector;
- preset selector;
- format-specific controls;
- estimated size when possible;
- suggested download filename/delivery action;
- stale-result warning;
- start/cancel controls.

### 31.2 Filename templates

Support safe tokens such as:

- project name;
- track/stem role;
- result/model short name;
- region/loop/queue name;
- date of export;
- sequence index.

Sanitize for filesystem safety.

Do not allow template expansion to create directory traversal.

### 31.3 Collision behavior

Offer explicit:

- ask/confirm;
- replace atomically;
- auto-number.

Never silently overwrite an existing file by default.

### 31.4 Provenance sidecar

For formats that cannot carry rich provenance, optionally/default where appropriate write a small JSON sidecar containing:

- project revision;
- source hash;
- result/branch IDs;
- model/module provenance;
- export preset;
- encoder build;
- normalization/stretch settings;
- stale status at export time.

### 31.5 Stale export

Allow exporting stale results when bytes are valid, but require a visible warning and record stale reasons in provenance.

Do not force rerun.

**Acceptance:** users can tell exactly what they are exporting and existing files are protected from accidental overwrite.

---

## 32. Work package M6.30 — Build cache inventory and storage accounting

### 32.1 Storage categories

Report separately:

- working project metadata/databases;
- project-essential audio/assets;
- installed models;
- rebuildable waveform caches;
- playback-rate representations;
- prepared analysis inputs;
- automatic analysis result artifacts considered rebuildable under current policy;
- optional raw evidence;
- staging/temp;
- complete orphan assets;
- exports when inside managed directories;
- portable project archives when known.

### 32.2 Cache object metadata

For each managed cache object record/index:

- asset/content ID;
- category;
- byte size;
- creation time;
- last access time;
- transformation key;
- owning/referencing project IDs;
- active job pin;
- save/export pin;
- history/named-revision pin;
- rebuildability;
- upstream dependencies;
- integrity status.

### 32.3 Access-time policy

Do not update SQLite on every waveform tile read.

Use buffered/coalesced access updates, for example:

- in-memory recent-use tracking;
- periodic durable flush;
- coarse timestamps.

### 32.4 Project storage summary

For each project, estimate:

- essential referenced bytes;
- rebuildable referenced cache;
- retained inactive analysis versions;
- reclaimable unreferenced bytes attributable to prior work.

Avoid double-counting content-addressed assets shared between projects in global totals.

### 32.5 Model storage

Show model storage separately by registered model ID/version.

Cache cleanup must never classify model weights as ordinary LRU analysis cache.

### 32.6 Default budget

Enforce/monitor the main-plan initial 50 GiB budget for rebuildable cache categories.

The budget is configurable.

Project-essential assets are not automatically deleted merely because the cache budget is exceeded.

**Acceptance:** storage UI explains where disk space is used and which bytes are actually reclaimable.

---

## 33. Work package M6.31 — Implement safe cache cleanup and eviction

### 33.1 Protection graph

Before deleting a cache object, prove it is not protected by:

- active working project state;
- retained history needed for undo/redo;
- named revision;
- running analysis/export/save job;
- portable-save snapshot in progress;
- explicit user pin where supported;
- another cache object whose integrity/rebuild path requires it and that is protected.

### 33.2 Automatic budget eviction

When rebuildable cache exceeds configured budget:

1. Build unprotected candidate list.
2. Order by least recently used with category-aware safeguards.
3. Compute target reclaim amount.
4. Delete only rebuildable unreferenced candidates.
5. Commit deletion metadata.
6. Stop when under target/budget.

Do not delete current-project essential analysis result state automatically.

### 33.3 Explicit cleanup preview

Before user-requested cleanup, show:

- categories selected;
- object count;
- bytes to reclaim;
- projects affected only through rebuildable cache;
- items that cannot be deleted and why.

### 33.4 Cleanup categories

Offer safe selections such as:

- orphan staging/temp;
- unreferenced waveform/playback caches;
- unreferenced prepared analysis inputs;
- unreferenced optional evidence/results classified rebuildable;
- all eligible rebuildable cache.

Do not include models in these controls.

### 33.5 Deletion procedure

For each object:

1. Recheck pins/references immediately before deletion.
2. Move/delete according to filesystem strategy.
3. Remove metadata only after byte deletion succeeds or mark missing consistently.
4. Handle races with new references through transaction/locking.
5. Record cleanup result.

### 33.6 Failure behavior

Partial cleanup failure:

- does not mark remaining valid objects corrupt;
- reports bytes reclaimed and failures;
- can be retried.

### 33.7 History protection tests

Explicitly test that assets required to undo to a retained state are not evicted.

Where history stores semantic state independent of an old rebuildable artifact, the artifact may be evictable according to declared policy.

**Acceptance:** cleanup reclaims only proven rebuildable/unprotected bytes and never breaks surviving manual edits or selected results.

---

## 34. Work package M6.32 — Add cache/storage UI

### 34.1 Storage panel

Show:

- working projects;
- essential project assets;
- cache used/budget;
- models;
- staging/orphans;
- reclaimable estimate;
- free disk space.

### 34.2 Cache object drill-down

Allow filtering by:

- project;
- category;
- analysis module;
- status;
- referenced/unreferenced;
- age/last use.

Do not require exposing raw filesystem paths for ordinary use.

### 34.3 Cleanup flow

1. Choose category/filter.
2. Run dry-run calculation.
3. Review reclaimable bytes.
4. Confirm.
5. Start durable cleanup operation/job if large.
6. Stream/report progress.
7. Refresh inventory.

### 34.4 Rebuild hint

For a deleted/missing rebuildable cache, module UI may show `will rebuild when needed` instead of an error.

**Acceptance:** the user can understand and safely control disk usage without knowing the internal content-addressed directory layout.

---

## 35. Work package M6.33 — Extend local API and contracts for workflow completion

### 35.1 History routes

Add/complete:

- `GET /api/v1/projects/{id}/history`;
- `GET /api/v1/projects/{id}/history/state`;
- `POST /api/v1/projects/{id}/undo`;
- `POST /api/v1/projects/{id}/redo`;
- `POST /api/v1/projects/{id}/named-revisions`;
- `POST /api/v1/projects/{id}/named-revisions/{rid}/restore`;
- rename/delete named revision operations.

### 35.2 Analysis selection/status routes

Add/complete:

- list result catalog by family;
- switch active result/branch through project command endpoint;
- fetch dependency/stale details;
- fetch project analysis-health summary.

Do not create an unrevisioned side channel for selection mutation.

### 35.3 Snippet routes

Use project commands for mutation.

Provide read helpers as needed for:

- queue list;
- resolved queue playback plan;
- validation diagnostics.

### 35.4 Export routes

Add:

- export preset discovery;
- user preset CRUD under user settings scope;
- `POST /api/v1/projects/{id}/exports` generalized request;
- `GET /api/v1/downloads/{artifact_id}` authenticated attachment delivery for completed managed export/portable artifacts;
- export job state through existing jobs API;
- cancellation;
- final output metadata.

### 35.5 Cache routes

Add:

- `GET /api/v1/storage/summary`;
- `GET /api/v1/cache/objects` with bounded pagination/filters;
- `POST /api/v1/cache/cleanup/preview`;
- `POST /api/v1/cache/cleanup`;
- cleanup job state where operation is long.

### 35.6 Recovery/integrity routes

Add:

- project health summary;
- deep verify request;
- repair-plan generation;
- explicit rebuild action request.

### 35.7 Error codes

Standardize codes including:

- `REVISION_CONFLICT`;
- `BRANCH_REVISION_CONFLICT`;
- `HISTORY_EMPTY`;
- `REDO_UNAVAILABLE`;
- `HISTORY_COMMAND_UNSUPPORTED`;
- `RESULT_STALE` only when an operation explicitly requires current result;
- `RESULT_UNAVAILABLE`;
- `ASSET_MISSING`;
- `ASSET_CORRUPT`;
- `PROJECT_RECOVERY_REQUIRED`;
- `MIGRATION_UNSUPPORTED_NEWER_VERSION`;
- `MIGRATION_FAILED`;
- `EXPORT_PROFILE_INVALID`;
- `EXPORT_FORMAT_UNSUPPORTED`;
- `CACHE_OBJECT_PROTECTED`;
- `SNIPPET_QUEUE_INVALID`;
- `SHORTCUT_CONFLICT` for settings validation where API-backed.

### 35.8 Contract regeneration

Regenerate:

- OpenAPI;
- Pydantic JSON schemas;
- TypeScript client types;
- contract-drift checks.

**Acceptance:** every new workflow uses typed authenticated local interfaces and no browser code manipulates managed files directly.

---

## 36. Work package M6.34 — Complete workflow-level frontend state architecture

### 36.1 Backend-authoritative semantic state

Frontend Zustand/editor stores cache/derive project semantic state but do not become the sole source of truth for:

- history head;
- project revision;
- analysis selection;
- stale status;
- snippet queues;
- project integrity.

### 36.2 Optimistic editing policy

Use optimistic previews during gestures.

Commit only after backend command success.

If commit conflicts/fails:

- revert preview;
- refetch authoritative state;
- preserve user intent where possible for retry.

### 36.3 Unified result selector component

Reuse one interaction pattern across rhythm/chords/key/transcription/separation as appropriate:

- Auto/Edited;
- model/input/version list;
- status badges;
- provenance summary;
- stale reason detail;
- `Run again` separate from `Select`.

### 36.4 History controls

Provide:

- Undo button with next-action tooltip;
- Redo button;
- disabled states;
- named revision/checkpoint UI;
- recent history list where useful.

Do not expose raw command payload JSON to ordinary users.

### 36.5 Recovery banner

After interrupted session:

- show compact summary;
- link to recovery details;
- distinguish auto-recovered state from items requiring action;
- allow dismissal after acknowledgement without erasing diagnostic record.

### 36.6 Storage/export/shortcut settings

Integrate with the existing app layout without obstructing the main editor.

**Acceptance:** project-wide workflow state is coherent across reload/reconnect and does not depend on one component retaining hidden local state.

---

## 37. Work package M6.35 — Security, locality, and filesystem constraints

### 37.1 Loopback/authentication

All new routes remain under existing loopback authentication/origin protections.

### 37.2 Export paths

For export delivery:

- write only to app-managed export staging/publication roots on the backend;
- expose completed artifacts through authenticated loopback download endpoints with `Content-Disposition`;
- let the browser/user select the final filesystem destination through normal browser download behavior;
- never accept an arbitrary browser-supplied server filesystem path as the baseline mechanism;
- never accept archive-internal traversal;
- subprocess receives argument arrays;
- temporary filenames are app-generated.

A future launcher/native convenience path may add a separately validated direct-save capability, but browser download remains the required cross-browser baseline.

### 37.3 Cache cleanup

Only delete paths resolved from managed asset records and verified under managed roots.

Never accept arbitrary browser-supplied filesystem paths for deletion.

### 37.4 Portable extraction

Retain:

- path traversal rejection;
- symlink/hardlink policy;
- extraction-size limits;
- manifest/hash validation;
- no executable plugin installation on project open.

### 37.5 Offline behavior

With internet disabled:

- history/undo/redo works;
- recovery works;
- stale status works;
- snippet queues work;
- export works for installed FFmpeg/offline renderer;
- analysis export works;
- cache cleanup works;
- project migration works;
- portable save/open works;
- no missing model triggers automatic network calls.

### 37.6 Logs

Do not log:

- auth tokens;
- entire command payloads when they may contain user labels/content unnecessarily;
- full absolute user source paths unless diagnostic level explicitly requires and policy allows;
- audio data.

**Acceptance:** workflow completion does not weaken the local-only/security boundaries established in Milestone 0.

---

## 38. Work package M6.36 — Define end-to-end project state and history invariants

### 38.1 Revision invariants

- revision is nonnegative and monotonic;
- exactly one committed semantic transaction produces the expected revision increment;
- undo/redo increments revision;
- portable snapshot names the exact revision included;
- stale client edits cannot commit.

### 38.2 History invariants

- every applied history entry has valid forward/inverse schema;
- current history head is reachable;
- redo chain is valid only after compatible undo sequence;
- divergent new edit abandons redo path;
- named revisions reference valid historical materialization/checkpoint;
- command targets use stable IDs.

### 38.3 Analysis selection invariants

- selected branch belongs to selected/compatible family/result;
- Auto points to immutable result;
- Edited points to editable branch;
- branch parent provenance remains immutable;
- selecting result cannot delete another result.

### 38.4 Dependency invariants

- every stale reason points to a declared edge;
- display-only edges never create semantic staleness;
- missing required upstream data can cause unavailable, not fake current;
- corrupt bytes never remain current.

### 38.5 Asset invariants

- published asset path resolves inside managed storage;
- hash/metadata agree when verified;
- incomplete staging is never referenced as published asset;
- deletion never leaves a live DB reference to an object claimed present without marking missing/unavailable.

### 38.6 Snippet invariants

- entry intervals valid;
- order stable;
- musical entry resolves through declared grid identity;
- queue changes revisioned;
- playback never advances source time through skipped gaps as if continuous.

### 38.7 Export invariants

- job freezes project revision and source/result identities;
- output is not published before encode validation;
- stale status at snapshot recorded;
- Auto/Edited source explicit;
- failed export preserves existing output.

**Acceptance:** invariant checks can run in tests and selected diagnostics, catching workflow corruption close to its source.

---

## 39. Work package M6.37 — Automated unit-test matrix

### 39.1 Command registry tests

Test:

- schema validation;
- inverse generation;
- stable object IDs;
- deterministic forward application;
- batch atomicity;
- command-size rejection;
- unsupported command version.

### 39.2 History tests

Test:

- persistent undo after restart;
- persistent redo after restart;
- redo invalidation after new edit;
- abandoned history retained;
- coalesced drag;
- grouped batch;
- named revision restore;
- history checkpoint reconstruction;
- monotonic revisions.

### 39.3 Conflict tests

Test:

- two clients same base revision;
- first commits, second receives 409;
- idempotent retry same body returns same outcome;
- same key different body conflicts;
- duplicate undo request does not double-undo;
- stale branch revision conflicts.

### 39.4 Dependency tests

For each declared edge class:

- correct stale propagation;
- no propagation for display context;
- missing optional evidence behavior;
- missing hard input behavior;
- corrupt input behavior;
- stale result retention.

### 39.5 Snippet tests

- order/reorder;
- source anchors;
- musical anchors;
- invalid interval;
- repeat count;
- loop-derived snapshot semantics;
- queue undo/redo.

### 39.6 Shortcut tests

- defaults;
- remap persistence;
- conflicting mapping rejected;
- input focus suppression;
- Ctrl versus Cmd normalization;
- reset defaults.

### 39.7 Export preset tests

- schema validation;
- unsupported format combinations;
- built-in immutability/reset;
- user preset CRUD;
- resolved job snapshot.

### 39.8 Cache tests

- reference pinning;
- history pinning;
- active job pinning;
- save pinning;
- LRU order;
- dry-run bytes;
- race recheck;
- model exclusion.

### 39.9 Migration tests

- every version step;
- rollback on failure;
- unsupported newer version;
- idempotent reopen;
- command-history baseline when old replay unsupported.

### 39.10 Corruption tests

- missing peaks;
- missing playback representation;
- missing raw activations;
- missing parent automatic result;
- missing stem;
- corrupt hash;
- corrupt project DB fixture;
- missing model is not corruption.

**Acceptance:** core workflow semantics are covered by deterministic unit tests before browser end-to-end testing.

---

## 40. Work package M6.38 — Integration tests for database, filesystem, jobs, and recovery

### 40.1 Transaction crash points

Inject/process-kill around:

- before domain mutation;
- after mutation before command row;
- after command row before transaction commit;
- after asset file publication before DB reference;
- after DB reference before job-complete event;
- during portable save;
- during export;
- during cache cleanup.

Expected outcome follows transaction/publication invariants.

### 40.2 WAL recovery

Test unclean backend termination with WAL activity.

Verify:

- committed rows remain;
- uncommitted rows absent;
- history head valid;
- startup recovery report correct.

### 40.3 Staging recovery

Fixtures for:

- partial PCM/cache file;
- completed hashed file without DB reference;
- stale staging manifest;
- interrupted export temp;
- interrupted portable archive temp.

### 40.4 Cache cleanup race

Start cleanup preview, then create a new project/history/job reference before deletion.

Deletion phase must recheck and protect the newly referenced object.

### 40.5 Migration failure

Force migration error after partial SQL statements.

Verify transaction rollback and retained backup/original archive.

### 40.6 Portable save concurrency

Start save at revision R, then commit edits R+1/R+2.

Open archive and assert state exactly matches R.

### 40.7 Multi-tab API conflict

Run two HTTP clients with interleaved edits and event stream.

Verify conflict/reload behavior.

**Acceptance:** failure injection demonstrates that project integrity depends on transactions/atomic publication, not ideal shutdown order.

---

## 41. Work package M6.39 — Browser end-to-end workflow tests

### 41.1 Persistent history workflow

1. Open project.
2. Edit marker.
3. Edit chord.
4. Edit note.
5. Change mixer.
6. Restart app.
7. Undo each in reverse.
8. Restart again.
9. Redo selected entries.
10. Verify audio/timeline state.

### 41.2 Version switching workflow

1. Retain multiple rhythm/chord/transcription results.
2. Create edits on one.
3. Switch Auto/Edited/model versions.
4. Verify all lanes/readout/export selection update.
5. Verify old edits remain.

### 41.3 Staleness workflow

1. Select bass separation A and transcription A.
2. Select separation B.
3. Observe transcription A stale with exact reason.
4. Keep viewing/exporting A.
5. Select or run transcription B.
6. Observe current state.

### 41.4 Conflict workflow

1. Open two tabs.
2. Edit same project in tab A.
3. Attempt stale edit in tab B.
4. Verify visible conflict, state refresh, no overwrite.

### 41.5 Crash recovery workflow

1. Commit edits.
2. Start analysis/export.
3. Kill backend process.
4. Relaunch.
5. Verify committed edits.
6. Verify interrupted jobs.
7. Verify no partial results exposed.

### 41.6 Snippet queue workflow

1. Create three noncontiguous entries.
2. Reorder.
3. Set repeats.
4. Play at 0.5× and 1.5×.
5. Verify transitions/playhead/metronome.
6. Restart and repeat.

### 41.7 Shortcut workflow

- remap play/pause;
- verify persistence;
- type in chord/note text field without transport trigger;
- reset mapping.

### 41.8 Export workflow

- WAV stems;
- FLAC selection;
- MP3 mix;
- analysis JSON;
- chord LAB;
- bass MIDI;
- queue audio;
- stale-result export warning.

### 41.9 Cache workflow

- fill test cache;
- inspect categories;
- preview cleanup;
- clean unreferenced objects;
- reopen project;
- rebuild missing peaks;
- verify edits/results intact.

### 41.10 Migration workflow

Open representative older portable projects and verify editable state after migration.

**Acceptance:** browser tests validate the complete workflow rather than isolated forms/endpoints.

---

## 42. Work package M6.40 — Audio/export validation matrix

### 42.1 WAV regression

Ensure Milestone 2 WAV stem export remains correct after export refactor.

### 42.2 FLAC matrix

Test:

- mono/stereo;
- 16/24-bit;
- 44.1/48/96 kHz representative rates;
- full duration;
- short selection;
- multiple aligned stems.

### 42.3 MP3 matrix

Test:

- bitrates 128/192/256/320 where supported;
- 44.1/48 kHz;
- source rate conversion;
- very short region;
- queue output;
- tag writing.

### 42.4 Mixer export

Verify frozen:

- mute/solo;
- gain;
- pan/balance;
- master gain;
- limiter inclusion/exclusion policy.

### 42.5 Speed export

At:

- 0.25×;
- 0.5×;
- 0.75×;
- 1×;
- 1.5×;
- 2×.

Measure:

- output duration error;
- pitch preservation on tones/music fixture;
- discontinuities at finite boundaries;
- queue transition artifacts.

### 42.6 Clipping/normalization

Test:

- normalization off preserves level aside from quantization/encode behavior;
- linked stem normalization uses one gain;
- independent normalization uses per-file gains and is labelled;
- clipping detection warnings;
- dither profile only on bit-depth reduction.

**Acceptance:** new export formats do not regress timing/alignment and every lossy/processed transformation is explicit.

---

## 43. Work package M6.41 — Analysis-export validation matrix

### 43.1 JSON schema round-trip

Validate exported JSON against its published schema.

### 43.2 CSV parsing

Parse all CSV outputs with a standards-compliant parser and verify:

- headers;
- Unicode labels;
- commas/quotes/newlines in custom labels;
- source-frame integers;
- time precision;
- null/unknown representation.

### 43.3 Chord LAB

Verify:

- monotonic timestamps;
- adjacent region continuity where expected;
- no-chord/unknown convention;
- Auto versus Edited differences.

### 43.4 MIDI

Parse exported MIDI and verify:

- bass note timing;
- no stuck notes;
- tempo events;
- meter events where representable;
- variable-tempo timing tolerance;
- no invented grid when unavailable under the chosen profile.

### 43.5 Provenance

Verify output/sidecar identifies:

- project revision;
- source identity;
- exact result/branch IDs;
- model/module versions;
- stale status;
- export schema/preset version.

**Acceptance:** analysis exports are parseable, versioned, and unambiguous about source/result provenance.

---

## 44. Work package M6.42 — Resource, scale, and responsiveness validation

### 44.1 Long history

Generate a project with at least tens of thousands of compact command entries in a stress fixture.

Measure:

- open time with checkpoints;
- undo/redo latency;
- database size;
- named restore latency.

Do not require replay of every command at normal open.

### 44.2 Many retained results

Test a project with multiple versions of:

- separation;
- rhythm;
- chords;
- key;
- transcription.

Result selector and dependency graph must remain responsive.

### 44.3 Large cache

Simulate/cache tens of GiB worth of indexed objects without loading metadata for every object into the browser at once.

Use paginated/aggregated APIs.

### 44.4 Long snippet queue

Test hundreds of entries for UI operations while playback acceptance can use a smaller practical queue.

Reorder should not rewrite all entries with quadratic cost if an order-key strategy is used.

### 44.5 Export responsiveness

Large export runs outside API event loop/frontend thread.

Playback remains responsive during CPU/IO export within resource limits.

Throttle export worker IO/CPU if necessary to protect playback.

### 44.6 Hash verification

Deep integrity verification is background/durable and should not freeze normal project UI.

**Acceptance:** Milestone 6 workflow features remain usable on large realistic projects and do not compromise playback responsiveness.

---

## 45. Work package M6.43 — Manual recovery, workflow, and export acceptance sessions

### 45.1 Required sessions

Run manual sessions covering:

1. Normal edit/restart/undo/redo.
2. Divergent history after undo.
3. Named revision restore.
4. Multi-result switching.
5. Intentional stale-result use.
6. Two-tab conflict.
7. Backend kill during active project.
8. Backend kill during export/save.
9. Missing waveform cache.
10. Missing optional raw analysis evidence.
11. Missing required stem.
12. Cache cleanup and rebuild.
13. Snippet queue practice at multiple speeds.
14. Shortcut remapping.
15. WAV/FLAC/MP3 exports.
16. Complete analysis export.
17. Older-project migration.
18. Model-absent offline reopen/export.

### 45.2 Five existing recordings

Use the existing local listening corpus to verify:

- prior analysis/edit state survives Milestone 6 migration;
- snippet queues are practical;
- exports sound correct;
- no source/stem timing drift appears;
- stale/version selector semantics remain understandable.

Do not claim ground-truth model accuracy from these tracks unless separately annotated.

### 45.3 Issue log

For every defect record:

- project fixture;
- app revision;
- operation;
- expected state;
- actual state;
- whether data integrity was affected;
- recovery path;
- regression test added.

### 45.4 Acceptance priority

Any data-loss, silent-overwrite, wrong-result-export, wrong-cache-deletion, or partial-asset-publication bug blocks Milestone 6 completion regardless of UI polish.

**Acceptance:** manual destructive/recovery scenarios confirm the persistence design under realistic user behavior.

---

## 46. Work package M6.44 — Documentation and developer operations

### 46.1 User documentation

Document:

- persistent undo/redo behavior;
- named revisions;
- Auto/Edited/model version switching;
- stale versus unavailable/corrupt;
- conflict resolution;
- crash recovery;
- snippet queues;
- shortcut remapping;
- export presets/formats;
- cache/storage cleanup;
- project migration;
- missing-asset recovery.

### 46.2 Export documentation

State clearly:

- WAV/FLAC lossless/integer behavior;
- MP3 lossy/timing limitations;
- normalization defaults;
- dither behavior;
- original versus practice-speed engine/profile;
- analysis export schemas;
- Auto/Edited provenance.

### 46.3 Recovery documentation

Provide steps for:

- unclean shutdown;
- corrupt optional cache;
- missing source/stem;
- failed project migration;
- restoring previous portable archive;
- collecting diagnostics.

### 46.4 Developer documentation

Document:

- command registry extension procedure;
- inverse/redo requirements;
- history checkpoints;
- dependency-edge declarations;
- stale computation;
- cache protection graph;
- migration authoring/testing;
- export preset schema;
- asset classification;
- recovery staging manifests.

### 46.5 Operational scripts/checks

Add developer commands for:

- command-coverage audit;
- project invariant check;
- migration fixture sweep;
- cache dry-run report;
- deep project integrity verification;
- export-schema validation.

**Acceptance:** new workflow behavior can be maintained without rediscovering hidden invariants from code.

---

## 47. Implementation order and milestone gates

Milestone 6 should proceed through gates. Do not begin destructive cache cleanup or broad migration work before the command/history and dependency models are stable.

### Gate A — Prerequisite and state inventory

Complete:

- M6.1 mutable-state audit;
- baseline regression suite;
- command coverage matrix.

Pass when:

- every persistent state field has a declared owner/history policy;
- no known earlier milestone integrity regression is being hidden.

### Gate B — Unified commands and persistent history

Complete:

- M6.2 command contract;
- M6.3 command coverage;
- M6.4 durable history storage;
- M6.5 persistent undo/redo;
- M6.6 named revisions/checkpoints.

Pass when:

- restart preserves undo/redo;
- revision numbers stay monotonic;
- divergent edits clear redo safely;
- named restore is reversible.

### Gate C — Unified result selection and staleness

Complete:

- M6.7 analysis selection;
- M6.8 dependency graph;
- M6.9 stale UI.

Pass when:

- every analysis family has explicit retained-version selection, and Auto/Edited appears only for families with editable branches;
- selective stale propagation matches declared dependencies;
- old results remain intact.

### Gate D — Conflict and recovery hardening

Complete:

- M6.10 conflict/idempotency;
- M6.11 multi-tab events;
- M6.12 shutdown detection;
- M6.13 crash recovery;
- M6.14 diagnostics;
- M6.15–M6.16 asset recovery.

Pass when:

- two-tab edits never silently overwrite;
- kill tests preserve committed state;
- incomplete outputs never publish;
- missing/corrupt assets have accurate status/actions.

### Gate E — Migration and portable-project completion

Complete:

- M6.17 migration framework;
- M6.18 portable snapshot/history integration.

Pass when:

- supported old fixtures migrate correctly;
- originals remain unchanged on failure;
- portable reopen preserves history/selections/stale state.

### Gate F — Snippet and keyboard workflow

Complete:

- M6.19–M6.20 snippet queues;
- M6.21 shortcut registry/remapping.

Pass when:

- noncontiguous queue practice is stable at supported playback speeds;
- shortcut remapping persists and cannot trigger destructive actions while typing.

### Gate G — Export completion

Complete:

- M6.22 presets;
- M6.23 general export jobs;
- M6.24 FLAC;
- M6.25 MP3;
- M6.26 speed behavior;
- M6.27 queue export;
- M6.28 analysis exports;
- M6.29 export UX/provenance.

Pass when:

- output identity is frozen at job start;
- WAV/FLAC/MP3 validation passes;
- analysis exports parse and identify Auto/Edited sources;
- failed exports preserve prior files.

### Gate H — Cache management

Complete:

- M6.30 inventory;
- M6.31 cleanup;
- M6.32 storage UI.

Pass when:

- dry-run preview is accurate;
- reference/history/job/save pins prevent unsafe deletion;
- model files remain outside ordinary cache eviction.

### Gate I — Full regression and operational acceptance

Complete:

- M6.33–M6.44 APIs/UI/security/invariants/tests/docs.

Pass when:

- automated and manual recovery/export/migration tests pass;
- all prior milestone workflows remain regression-clean;
- no known silent data-loss/overwrite/cache-deletion defect remains.

---

## 48. Detailed completion checklist

Milestone 6 is not complete until all applicable items below pass.

### 48.1 Mutable-state/command coverage

- [ ] Every persistent semantic field is inventoried.
- [ ] Every persistent semantic edit has a command type.
- [ ] Component-local persistent mutations are removed.
- [ ] Transient playhead/hover/progress state is excluded from history.
- [ ] Command schemas are versioned.
- [ ] Backend generates/verifies inverse payloads.
- [ ] Object creation IDs remain stable across redo.
- [ ] Batch commands are atomic.
- [ ] Continuous gestures coalesce.

### 48.2 Persistent history

- [ ] History entries persist in SQLite.
- [ ] History head persists.
- [ ] Undo availability survives restart.
- [ ] Redo availability survives restart.
- [ ] Undo increments project revision.
- [ ] Redo increments project revision.
- [ ] New edit after undo abandons redo path safely.
- [ ] Abandoned history remains auditable.
- [ ] Undo/redo labels are available.
- [ ] Long history uses checkpoints.
- [ ] Named revisions exist.
- [ ] Named restore creates a new revision.
- [ ] Named restore is undoable.

### 48.3 Analysis versions

- [ ] Separation version selection is explicit.
- [ ] Rhythm Auto/Edited/version selection is explicit.
- [ ] Chord Auto/Edited/model/input selection is explicit.
- [ ] Key Auto/Edited/version selection is explicit.
- [ ] Bass transcription Auto/Edited/version selection is explicit.
- [ ] Switching selection is undoable.
- [ ] Switching does not delete older results.
- [ ] Edited branches remain attached to their parent automatic result.
- [ ] Rerun never overwrites corrections.

### 48.4 Dependency/stale state

- [ ] Dependency edges are persisted/derivable.
- [ ] Hard input changes stale downstream result.
- [ ] Decode-context changes stale downstream result.
- [ ] Display-only context does not stale result.
- [ ] Optional evidence absence is distinguished.
- [ ] Stale results remain usable where safe.
- [ ] Stale reason identifies changed dependency.
- [ ] Unavailable is distinct from stale.
- [ ] Corrupt is distinct from unavailable.
- [ ] No timestamp-only stale heuristic is used.

### 48.5 Revision/conflict/idempotency

- [ ] Semantic edit requires base revision.
- [ ] Branch edit validates branch revision where applicable.
- [ ] Stale base returns 409.
- [ ] No silent semantic rebase occurs.
- [ ] Frontend refetches authoritative state after conflict.
- [ ] Idempotent retry returns same outcome.
- [ ] Key reuse with different body conflicts.
- [ ] Undo/redo are idempotent against duplicate requests.
- [ ] Multi-tab revision events work.
- [ ] Reconnect cannot assume uninterrupted event stream.

### 48.6 Crash recovery

- [ ] Session clean-shutdown flag exists.
- [ ] Unclean shutdown is detected.
- [ ] SQLite/WAL recovery is respected.
- [ ] Quick integrity checks run when appropriate.
- [ ] Running jobs become interrupted.
- [ ] Staging manifests are scanned.
- [ ] Partial outputs are never published.
- [ ] Complete unreferenced assets are classified safely.
- [ ] Portable-save temp cannot replace verified save unless validated.
- [ ] Recovery report is visible.
- [ ] Committed edits survive kill tests.

### 48.7 Missing/corrupt assets

- [ ] Assets have essential/optional/rebuildable classification.
- [ ] Missing peaks trigger rebuild path.
- [ ] Missing playback representation triggers rebuild path.
- [ ] Missing model is not project corruption.
- [ ] Missing raw evidence can preserve decoded/manual result when independent.
- [ ] Missing required stem makes dependent workflow unavailable, not silently current.
- [ ] Corrupt hash is reported.
- [ ] Corrupt bytes are not served as trusted result.
- [ ] Repair publishes new validated objects.
- [ ] Manual corrections are never regenerated/overwritten as fake recovery.

### 48.8 Migrations

- [ ] DB migrations are ordered/transactional.
- [ ] Existing DB backup policy is retained.
- [ ] Portable archive original remains unchanged.
- [ ] Working-copy migration is recorded.
- [ ] Migration preserves source-frame timing.
- [ ] Migration preserves branch/object IDs where possible.
- [ ] Migration preserves active selections.
- [ ] Migration preserves stale/dependency semantics.
- [ ] Older command history is migrated or honestly baselined.
- [ ] Every supported historical fixture passes.
- [ ] Unsupported newer schema is not modified.

### 48.9 Portable projects

- [ ] Save freezes one committed revision.
- [ ] Later edits do not leak into save.
- [ ] History/head is included.
- [ ] Named revisions intended for portability are included.
- [ ] Required checkpoints are included.
- [ ] Reachability collection protects referenced assets.
- [ ] Save pins assets against cache cleanup.
- [ ] Manifest records required/optional classification.
- [ ] Model weights remain excluded.
- [ ] Reopen does not invoke models/network.
- [ ] Undo/redo continues after reopen.

### 48.10 Snippet queues

- [ ] Queue schema exists.
- [ ] Source anchors work.
- [ ] Musical anchors work.
- [ ] Create from selection works.
- [ ] Create from loop works with snapshot semantics.
- [ ] Create from note/chord/bar/section range works.
- [ ] Rename works.
- [ ] Reorder works.
- [ ] Enable/disable works.
- [ ] Repeat count works.
- [ ] Delete/duplicate works.
- [ ] Queue edits are undoable.
- [ ] Next snippet prebuffers.
- [ ] Queue plays at 0.25×–2×.
- [ ] Stems stay synchronized.
- [ ] Source playhead jumps correctly between noncontiguous entries.
- [ ] Metronome/count-in phase is correct where grid exists.
- [ ] Queue survives reopen.

### 48.11 Keyboard mapping

- [ ] Action registry exists.
- [ ] Space mapping works.
- [ ] L mapping works.
- [ ] Left/right seek works.
- [ ] Shift-left/right bar seek works when grid exists.
- [ ] Home/End works.
- [ ] +/- zoom works.
- [ ] 1–9 solo works.
- [ ] Shift+1–9 mute works.
- [ ] M metronome works.
- [ ] Undo/redo shortcuts work cross-platform.
- [ ] Delete works only on editable selected targets.
- [ ] Escape cancels appropriately.
- [ ] Typing fields suppress ordinary shortcuts.
- [ ] Remapping persists.
- [ ] Conflicts are rejected/reported.
- [ ] Defaults can be restored.
- [ ] All actions remain available without shortcuts.

### 48.12 Export presets

- [ ] Preset schema is versioned.
- [ ] Built-in WAV stem preset exists.
- [ ] Built-in FLAC preset exists.
- [ ] Built-in MP3 mix preset exists.
- [ ] Analysis presets exist.
- [ ] User preset CRUD works.
- [ ] Invalid combinations are rejected before job start.
- [ ] Resolved job stores immutable preset snapshot.

### 48.13 Audio export

- [ ] WAV regression passes.
- [ ] FLAC 16-bit works.
- [ ] FLAC 24-bit works.
- [ ] MP3 bitrate options are validated against encoder.
- [ ] 320 kb/s appears only when supported.
- [ ] MP3 sample-rate conversion is explicit.
- [ ] Full-duration aligned stems work.
- [ ] Selection export works.
- [ ] Loop export works.
- [ ] Mixer export works.
- [ ] Queue export works.
- [ ] Normalization defaults off.
- [ ] Linked normalization preserves stem balance.
- [ ] Independent normalization is separately labelled.
- [ ] Dither only applies on integer reduction.
- [ ] Output is validated before atomic publication.
- [ ] Failed/cancelled export preserves existing files.
- [ ] Practice-speed export identifies its engine/profile.

### 48.14 Analysis export

- [ ] Complete analysis JSON schema exists.
- [ ] JSON states exact project revision/source.
- [ ] JSON states exact Auto/Edited result IDs.
- [ ] Beat CSV works.
- [ ] Tempo CSV works.
- [ ] Meter CSV works.
- [ ] Chord CSV works.
- [ ] Key CSV works.
- [ ] Bass-note CSV works.
- [ ] Marker/loop/snippet CSV works.
- [ ] Chord LAB works.
- [ ] Bass MIDI integrates with preset/export jobs.
- [ ] Tempo/time-signature MIDI is emitted where representable.
- [ ] Unusual meter limitations are explicit.
- [ ] Stale status is recorded in provenance.
- [ ] Raw evidence is excluded by default.

### 48.15 Cache inventory/cleanup

- [ ] Storage categories are separated.
- [ ] Global totals avoid double-counting shared content.
- [ ] Per-project essential/cache estimates exist.
- [ ] Models are separate from cache.
- [ ] Default rebuildable cache budget is 50 GiB.
- [ ] Budget is configurable.
- [ ] Access tracking is coalesced.
- [ ] Reference protection works.
- [ ] History protection works.
- [ ] Named revision protection works.
- [ ] Job/save/export pins work.
- [ ] Dry-run cleanup reports bytes/count.
- [ ] Deletion rechecks pins.
- [ ] LRU automatic eviction uses only eligible rebuildable objects.
- [ ] Cleanup failure is recoverable.
- [ ] Project still opens after cleanup.

### 48.16 Security/offline

- [ ] All new APIs require existing auth/origin protections.
- [ ] No arbitrary browser filesystem deletion paths.
- [ ] Export filenames are sanitized.
- [ ] Archive extraction protections remain.
- [ ] Offline history works.
- [ ] Offline recovery works.
- [ ] Offline snippets work.
- [ ] Offline export works.
- [ ] Offline analysis export works.
- [ ] Offline cache cleanup works.
- [ ] Offline migration works.
- [ ] Missing model never causes hidden network access.

### 48.17 Testing/documentation

- [ ] Command unit tests pass.
- [ ] History persistence tests pass.
- [ ] Conflict tests pass.
- [ ] Dependency/stale tests pass.
- [ ] Recovery kill tests pass.
- [ ] Migration fixture sweep passes.
- [ ] Export validation passes.
- [ ] Cache race tests pass.
- [ ] Browser workflow tests pass.
- [ ] Long-history/large-cache stress tests pass.
- [ ] Five existing recordings complete manual workflow review.
- [ ] User docs updated.
- [ ] Developer docs updated.
- [ ] Troubleshooting/recovery docs updated.

---

## 49. Direct traceability to Section 13 Milestone 6

| Main-plan Milestone 6 item | Detailed coverage |
|---|---|
| 1. Complete command coverage for all manual edits | M6.1–M6.3 |
| 2. Harden and unify persistent undo/redo across editable domains | M6.4–M6.6 |
| 3. Add retained-result/model/input switching and Auto/Edited only for editable families | M6.7, M6.9, M6.34 |
| 4. Add revision conflict handling | M6.10–M6.11 |
| 5. Add crash recovery | M6.12–M6.16 |
| 6. Add downstream stale-result indicators | M6.8–M6.9 |
| 7. Add snippet queues | M6.19–M6.20, M6.27 |
| 8. Add full keyboard mapping | M6.21 |
| 9. Add export presets | M6.22–M6.23, M6.29 |
| 10. Add FLAC and MP3 | M6.24–M6.25 |
| 11. Add analysis exports | M6.28–M6.29 |
| 12. Add cache inspection/cleanup | M6.30–M6.32 |
| 13. Add project migration tests | M6.17, M6.37–M6.39 |
| 14. Add missing-asset/corruption handling | M6.14–M6.16, M6.37–M6.40 |

The main-plan acceptance condition—analysis and practice state survive crashes, reopening, and model changes—is satisfied only when Gates A–I pass. A persistent project snapshot without durable history, dependency status, migration, integrity, and recovery behavior is not sufficient.

---

## 50. Handoff to Milestone 7 — Quality models and YouTube

Deliver to Milestone 7:

1. A complete semantic command/history system with persistent undo/redo.
2. Named historical revisions and fast state checkpoints.
3. A unified retained-result catalog and active selection model across analysis families.
4. An explicit dependency/staleness graph that new SCNet/RoFormer/six-stem outputs can join by declaring dependencies.
5. Global current/stale/unavailable/corrupt UI semantics.
6. Revision-conflict and idempotency handling robust enough for new model/download actions to coexist with editing.
7. Crash-recovery/session infrastructure for future model downloads and larger pipeline jobs.
8. Staging ownership manifests and atomic publication conventions.
9. Stable migration framework for adding new model/result schemas.
10. Portable-project snapshots that remain independent of installed model weights.
11. Snippet-queue practice and export independent of analysis model choice.
12. A centralized action/shortcut registry requiring no Milestone 7 changes for ordinary controls.
13. Versioned export presets and durable export jobs.
14. Working WAV/FLAC/MP3 exports.
15. Complete analysis export schemas with explicit result provenance.
16. Cache inventory, protection, LRU cleanup, and separate model-storage accounting.
17. Storage UI that can later expose larger Milestone 7 model installations without treating them as evictable analysis cache.
18. Project-health/missing-asset diagnostics.
19. Tested old-project migration and corrupt-asset recovery behavior.
20. Regression suites proving the five existing recordings preserve edits/practice/export state.

Milestone 7 must integrate new separation models through the same retained-result/dependency system rather than adding model-specific selection state.

Specifically:

- SCNet/RoFormer results must declare exact source/model/checkpoint/preprocessing dependencies;
- switching quality presets must create/select immutable separation result versions rather than overwrite Demucs results;
- a transcription tied to an older bass stem must become stale, not silently retarget to a new model stem;
- model downloads must use separate model storage and never become ordinary cache eviction candidates;
- YouTube import must enter the same immutable source/import pipeline as local media after retrieval;
- YouTube retrieval failure must not affect existing project history/results;
- whole-pipeline execution must schedule existing module contracts/result identities, not create a second hidden analysis state model;
- cache reuse across pipeline runs must continue to use exact declared identities;
- opening a project must never download a new model or re-fetch YouTube media automatically.

---

## 51. Milestone 6 final acceptance statement

Milestone 6 is complete when basseparate behaves as a durable long-lived local project editor rather than a sequence of independent analysis demos: every manual edit is represented by the shared semantic command system; undo/redo and named history survive restart; all retained automatic/edited/model versions can be selected without losing corrections; downstream staleness is dependency-driven and explainable; stale tabs cannot overwrite newer revisions; committed work survives crashes; missing/corrupt assets are classified and repaired only when valid upstream data exists; noncontiguous snippet queues practise through the existing synchronized transport; keyboard controls are complete and remappable; audio exports cover WAV, FLAC, and MP3 with explicit processing profiles; analysis exports identify exact Auto/Edited provenance; cache usage is inspectable and safely reclaimable; older projects migrate through tested paths; portable projects reopen offline without model execution; and all earlier musical timing, editing, playback, and analysis workflows remain regression-clean.
