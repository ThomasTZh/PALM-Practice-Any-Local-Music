# Milestone 4 — Harmony analysis and editing: detailed implementation specification

This expands Milestone 4 in Section 13 of [`basseparate_project_plan.md`](../product/basseparate_project_plan.md).

It builds on `milestone0.md`, `milestone1.md`, `milestone2.md`, and `milestone3.md`. Those milestones remain authoritative for the local application foundation, media pipeline, source-frame timing, waveform editor, synchronized stem playback, time stretching, loops, portable projects, durable jobs, immutable analysis versions, editable branches, musical mapping, snapping, metronome, count-in, and revisioned command history. Milestone 4 must extend those systems rather than replace or fork them.

Where this document fixes an engineering choice that the main plan intentionally leaves open—such as the canonical internal chord-label representation, the raw prediction artifact format, the non-drum harmonic-remix profile, or the relationship between key spelling and chord spelling—that choice is an implementation decision for Milestone 4, not a change to the product scope in the main plan.

Exact third-party revisions, checkpoint hashes, downloadable artifact URLs, and license conclusions must be resolved and verified during implementation. This specification intentionally does not invent unverified model hashes or imply that a wrapper's license automatically applies to model weights.

---

## 1. Required outcome and milestone boundaries

### 1.1 Complete user workflow

At completion, the user can:

1. Launch basseparate and open an imported, separated, and/or rhythm-enabled project.
2. Explicitly install the selected neural chord model if it is not already available.
3. Run chord analysis on the original reference mix.
4. Select BTC, ChordMini, or an available Chordino fallback/comparison adapter.
5. Run the selected chord adapter without silently downloading weights or invoking a remote service.
6. Preserve and inspect the selected model's raw framewise prediction artifact when the adapter exposes one.
7. See automatic chord regions aligned to the source waveform, stem tracks, musical ruler, and playhead.
8. Distinguish `no chord` from `unknown` rather than conflating both with an empty label.
9. View the same detailed chord result through Simple, Standard, or Detailed display projections without destroying the underlying detailed label.
10. Inspect alternative chord predictions and their score semantics where the adapter provides useful alternatives.
11. Switch among retained automatic chord results from different model/input/profile combinations.
12. Create an editable chord branch from any retained automatic result.
13. Rename a chord using structured or custom text entry.
14. Enter slash chords such as `C/E` manually.
15. Drag chord starts and ends while preserving valid non-overlapping region structure.
16. Move a shared boundary between adjacent chord regions without creating an accidental gap or overlap.
17. Split a region at the playhead or selection boundary.
18. Merge adjacent regions.
19. Insert a missing region.
20. Delete a region and explicitly choose the resulting gap semantics when needed.
21. Assign `no chord` or `unknown` explicitly.
22. Choose an alternative automatic prediction as the edited label.
23. Mark chord regions reviewed/corrected and navigate among uncertain regions.
24. Use existing snapping modes while editing chord boundaries; snapping affects only the current edit.
25. Optionally create a separate grid-refined automatic chord result that consumes the explicitly selected rhythm result/branch.
26. Keep the default source-time chord result unquantized and independent of the musical grid.
27. When aligned stems are available, optionally analyze a non-drum harmonic remix as a separate result rather than silently replacing original-mix analysis.
28. Inspect inversion evidence separately from root/quality evidence.
29. Accept, reject, or manually enter an inversion without requiring Milestone 5 bass-note transcription.
30. Run tuning estimation before tonal key-feature aggregation.
31. Inspect the global tuning estimate relative to the configured reference pitch.
32. Manually adjust the project's active tuning offset/reference without altering audio samples.
33. Run global key analysis.
34. Run overlapping-window local key analysis.
35. See local key regions aligned to the same source timeline.
36. Distinguish `unknown` from `no stable key`.
37. Inspect relative-major/minor and other retained key alternatives.
38. Edit local key-region boundaries.
39. Edit tonic, mode, and enharmonic spelling.
40. Keep tonic/mode evidence distinct from the displayed key-signature spelling preference.
41. Allow key-aware chord spelling where appropriate without changing the chord's semantic pitch class.
42. Preserve a user's explicit chord spelling/text instead of respelling it behind their back after a key edit.
43. See the musical readout include the active chord and key context when available.
44. Use linked selection so chord, key, bar, waveform, and later bass-note views share source-time context without automatically becoming mutual edit targets.
45. Undo and redo every manual chord, key, tuning, review-state, active-result, and harmony-view edit introduced in this milestone.
46. Save the project as a self-contained `.basseparate` archive.
47. Reopen the project without BTC, ChordMini, Chordino, Essentia, their model weights, a GPU, or network access.
48. Retain all corrected chord/key/tuning state, active result selection, review state, and harmony view settings after reopen.
49. Export/reuse the harmony state later through the main plan's analysis-export milestone without changing the stored semantics introduced here.
50. Continue ordinary playback, loops, variable speed, metronome, and count-in while harmony analysis is unavailable or has failed.

### 1.2 Included work

Milestone 4 includes:

- BTC chord-analysis adapter integration.
- ChordMini challenger adapter integration.
- Chordino deterministic/CPU-oriented fallback and comparison integration.
- Separate locked runtime boundaries where third-party dependency conflicts require them.
- Explicit model/adapter registration and installation-state reporting.
- Chord-model provenance, model/weight/license records, and local-only inference.
- A canonical internal chord-label representation independent of any one detector vocabulary.
- A declared detector-vocabulary mapping for every adapter.
- Preservation of raw framewise chord outputs where available.
- Preservation of raw/segment-level Chordino output where framewise logits are not available.
- Versioned chord decoding and temporal-smoothing profiles.
- `no chord` and `unknown` as distinct semantic states.
- Immutable automatic chord results.
- Editable chord branches.
- Simple, Standard, and Detailed non-destructive display projections.
- Alternative-prediction inspection.
- Optional original-mix versus non-drum harmonic-remix analysis.
- Optional rhythm-aware boundary refinement as a separately identified automatic result/profile.
- Source-time chord-region representation.
- Conservative inversion evidence without full bass transcription.
- Dedicated editable chord lane and waveform overlays.
- Chord split/merge/insert/delete/rename/boundary/review operations.
- Explicit slash-chord entry.
- Key/tuning analysis foundation.
- A project-owned tuning-estimation stage.
- Tonal/chroma feature artifacts suitable for key analysis.
- Essentia `KeyExtractor` integration as the initial external key adapter.
- An independent project-owned chroma/profile-correlation key implementation for comparison and fallback.
- Global key results.
- Local key-region results.
- Relative-major/minor and other retained alternatives.
- Enharmonic spelling suggestions with explicit user override.
- Editable key branches.
- Editable tuning state.
- Key-region boundary, tonic, mode, and spelling operations.
- Key-aware chord spelling that does not mutate semantic chord results.
- Confidence/review UI for chord and key output.
- Linked selection and readout integration.
- API, worker, frontend, persistence, cache, portable-project, diagnostics, and license extensions.
- Synthetic harmony/tuning/key fixtures.
- Manually annotated evaluation excerpts from the existing supplied tracks.
- Quantitative chord, boundary, key, tuning, confidence, runtime, and correction-burden evaluation.
- Browser, long-project, offline, failure, persistence, and listening validation.

### 1.3 Deferred work

Do not pull later milestones into Milestone 4.

Still deferred:

- Full bass-note transcription.
- torchcrepe integration.
- pYIN bass transcription fusion.
- Low-register octave-up/double-speed bass pitch analysis.
- Bass note-event segmentation.
- Bass-note overlay and synchronized note-text lane.
- Bass-note MIDI export.
- Slide/bend note-event editing.
- Bass-note-aware chord inversion decisions based on a corrected note transcription.
- Automatic joint chord+bass-note decoding.
- SCNet and RoFormer quality separation adapters.
- Six-stem quality-model expansion.
- YouTube import.
- Noncontiguous snippet queues.
- FLAC/MP3 export additions.
- Final full multi-analysis comparison dashboard.
- General release packaging decisions that depend on unresolved GPL/AGPL distribution policy.

Milestone 4 may compute limited low-frequency tonal evidence for inversion hypotheses. That evidence is region-level harmony evidence only. It must not be exposed or persisted as a substitute bass-note transcription.

### 1.4 Prerequisite state inherited from Milestones 0–3

Milestone 4 assumes the preceding milestones have delivered:

1. Reproducible locked core/backend/frontend environments.
2. Authenticated loopback-only API behavior.
3. Durable working-project storage and migrations.
4. Generated API/frontend contracts.
5. Immutable canonical source audio addressed by content identity.
6. Source-frame project timing with half-open intervals.
7. Bounded PCM and waveform access.
8. Shared waveform viewport and rendering layers.
9. Synchronized source/stem playback.
10. Variable-speed pitch-preserving playback.
11. Saved source-time and musical loops.
12. Durable jobs and subprocess workers.
13. A general model registry and explicit model-installation path.
14. GPU qualification and stable GPU identity handling.
15. Immutable automatic result versions and editable branches.
16. Transactional commands with base revision and idempotency semantics.
17. Persistent undo/redo.
18. Safe portable `.basseparate` save/open.
19. Offline reopen without model execution.
20. A corrected/selected rhythm version with stable result/branch identity when rhythm exists.
21. Source-frame ↔ exact rational musical-position mapping.
22. Meter regions, bars, beats, subdivisions, and snapping services.
23. A musical readout and linked-selection foundation.
24. A confidence/review UI pattern.
25. Existing stem assets that may be used for a separately versioned harmonic remix.
26. Cache provenance and stale-result mechanisms.
27. A renderer capable of adding key and chord lanes without changing waveform timing.

A failed prerequisite must be corrected at its owning milestone boundary. Milestone 4 must not hide a source-time, transport, revision, portable-project, or grid defect behind harmony-specific compensations.

### 1.5 Definition of the milestone boundary

Milestone 4 is complete only when automatic harmony analysis, versioning, manual correction, key/tuning analysis, editor behavior, persistence, and evaluation operate as one coherent workflow.

The following are not sufficient by themselves:

- showing model chord labels without retaining model provenance;
- storing only a final chord string per frame and discarding useful raw prediction evidence;
- treating `no chord` and `unknown` as the same state;
- applying a Simple display mode by destructively replacing detailed predictions;
- snapping automatic chord regions to beats without an explicit separate profile/result;
- assuming the latest automatic rhythm run is the user's selected corrected grid;
- treating a chord-root prediction as evidence for a slash-bass inversion;
- inferring full bass notes as a side effect of chord analysis;
- estimating only one global key and calling it local-key support;
- using a displayed key signature as if it were directly observed from audio;
- silently respelling user-entered chord text after a key edit;
- calling an arbitrary low model score a calibrated probability;
- passing only triad/chord-class synthetic tests;
- reopening a portable project only when the original harmony models remain installed.

---

## 2. Fixed implementation decisions for Milestone 4

| Area | Milestone 4 decision |
|---|---|
| Initial neural chord baseline | BTC large-vocabulary configuration from the main plan |
| Primary challenger | ChordMini BTC continual-learning checkpoint selected and verified during implementation |
| Deterministic/CPU comparison | Chordino through a registered local native adapter |
| Default chord-analysis input | Original reference mix |
| Optional alternate chord input | Versioned non-drum harmonic remix when a compatible drum stem exists |
| Automatic chord boundary basis | Source time; no mandatory beat quantization |
| Optional grid-aware result | Separate rhythm-refined result/profile with explicit selected rhythm dependency |
| Raw neural artifact | Immutable frame-by-label score/logit matrix plus label-vocabulary/alignment manifest when exposed |
| Chordino raw artifact | Immutable native segment/output artifact plus adapter-normalized regions; no invented logits |
| Chord semantics | Structured canonical label plus preserved raw detector/custom text |
| No-chord/unknown | Distinct first-class states |
| Complexity modes | Display projections only; underlying detailed prediction remains unchanged |
| Inversion evidence | Separate evidence object; does not automatically become slash bass solely from transient low-note evidence |
| Chord manual timing | Integer source-frame half-open regions |
| Key/tuning input | Original mix by default; optional harmonic remix may be a separate key result/profile |
| Tuning | Estimated before pitch-class aggregation; stored separately from key labels |
| Key estimation | Essentia KeyExtractor plus independent chroma/profile correlation |
| Key outputs | Separate global key and local key-region results |
| Key signature | Display/spelling preference separate from tonic/mode evidence |
| Manual harmony results | Editable branches derived from immutable automatic results |
| Rhythm dependency | Consumed only by profiles that explicitly name the selected rhythm result/branch |
| Key dependency of chords | Key may affect display spelling, not the semantic pitch-class result |
| Chord dependency of key | Default key pipeline is audio-feature based and does not depend on chord predictions |
| Portable reopen | Requires neither model/runtime nor network |

### 2.1 Source time remains authoritative for chord and key regions

Milestone 4 does not replace the source-frame timeline established earlier.

- Chord-region start/end boundaries are integer project source frames.
- Key-region start/end boundaries are integer project source frames.
- Tuning estimates refer to an analysis interval in source frames.
- Raw model frame positions are mapped back to source frames inside the adapter/decoder.
- Musical position is derived from the selected rhythm mapping when needed for display, snapping, or optional refinement.
- Playback speed does not alter chord/key source coordinates.
- Editing the rhythm grid does not silently move an existing source-time chord or key region.
- A grid-refined automatic chord result records the rhythm identity that produced its adjusted source boundaries.

### 2.2 Chord semantics are structured, but raw text is preserved

Use a canonical `ChordLabel` model with four top-level kinds:

1. `structured` — parsed musical chord semantics.
2. `no_chord` — explicit absence of harmonic chord content.
3. `unknown` — harmony exists or may exist, but the label is not confidently/validly known.
4. `custom` — user-preserved text that does not need to fit the supported structured grammar.

A structured chord stores semantic fields rather than relying on string slicing.

A detector's original label is always retained in provenance even after canonical mapping.

### 2.3 Detector vocabulary and editor vocabulary are different concepts

Each chord adapter declares:

- model label vocabulary;
- canonical mapping for every known model label;
- whether inversions are natively represented;
- whether extensions/alterations are represented;
- score semantics;
- no-chord semantics;
- unknown/out-of-vocabulary behavior.

The editor is not restricted to the detector vocabulary.

A user may enter a richer structured or custom label than the active model can predict. Rerunning the model must not overwrite that edit branch.

### 2.4 Complexity projections are non-destructive

Simple, Standard, and Detailed are views over one semantic chord result.

Rules:

1. Detailed shows every structured component supported by the stored semantic label.
2. Standard applies an explicit table-driven projection to a supported mid-level vocabulary.
3. Simple applies an explicit table-driven projection to a small root/quality-oriented vocabulary.
4. `no_chord` remains `no_chord` in every projection.
5. `unknown` remains `unknown` in every projection.
6. Custom labels are preserved as entered unless the user explicitly requests a parsed/normalized replacement.
7. Projection never creates an extension/inversion that the underlying label lacks.
8. Projection never changes persistence identity of the chord region.
9. Switching projection is a view-setting command, not a chord edit.

### 2.5 Rhythm context is optional and explicit

Default chord decoding stays in source time.

If the user runs a rhythm-aware boundary-refinement profile:

- the request names the exact rhythm result/branch ID and revision/identity;
- the result records that dependency;
- only that result becomes stale when the referenced rhythm branch changes materially;
- the unrefined source-time result remains valid;
- automatic refinement cannot mutate an edited chord branch;
- manual chord boundary snapping uses the currently selected grid but remains an explicit edit gesture.

### 2.6 Key evidence and displayed key signature are separate

Store at least:

- tonic pitch class;
- mode identifier;
- key-evidence score/confidence semantics;
- alternatives;
- preferred tonic spelling;
- displayed key-signature/spelling preference;
- review state.

Do not claim that audio uniquely determines whether an enharmonic key should be written, for example, as F-sharp versus G-flat where the pitch-class evidence alone is insufficient.

### 2.7 Chord pitch class and spelling are separate

For structured automatic chord labels:

- semantic root is stored as pitch class plus optional detector spelling provenance;
- semantic slash bass is stored similarly when it exists;
- displayed spelling may be resolved using the active local key region;
- a user's explicit spelling override takes precedence over automatic key-aware display spelling;
- changing the active key spelling may refresh auto-spelled display text without changing the chord's semantic pitch classes;
- custom chord text is never silently respelled.

### 2.8 Tuning is analysis context, not audio processing

Milestone 4 tuning edits:

- change tonal-analysis interpretation;
- do not resample, pitch-shift, or retune playback;
- do not modify canonical/stem assets;
- are represented as project analysis/editor state;
- become an explicit dependency for key/tonal-feature results that use them;
- are made available to Milestone 5 for pitch-label interpretation.

### 2.9 Chord and key analyses are sibling pipelines initially

The initial key pipeline consumes audio-derived tonal features, not predicted chord labels.

Consequences:

- a chord-model rerun does not automatically stale the key result;
- editing chord labels does not silently change the key result;
- key edits can affect chord display spelling but not chord semantic identities;
- future joint inference can be added as a new explicitly versioned module/profile rather than changing the meaning of Milestone 4 results.

### 2.10 Cross-project constraints carried forward

The following decisions from the main plan and earlier milestone specifications remain binding:

1. **Local-first execution:** ordinary harmony analysis, editing, playback, save/open, and practice are local.
2. **Explicit downloads:** neural model installation requires a deliberate user action.
3. **No remote inference:** adapters do not expose remote analysis paths.
4. **Loopback security:** all new APIs use the authenticated local service.
5. **Source-frame authority:** model times map back to project source frames.
6. **Immutable automatic results:** reruns create new versions.
7. **Editable branches:** user corrections do not modify automatic artifacts.
8. **Typed confidence:** raw scores are not presented as calibrated probabilities without evidence.
9. **Bounded binary artifacts:** large score/chroma arrays stay outside project JSON.
10. **Durable jobs:** jobs persist before execution, support cancellation, and publish atomically.
11. **GPU isolation:** GPUs remain separate memory pools.
12. **Playback priority:** harmony workers must not routinely disrupt prepared playback.
13. **Transactional editing:** semantic edits use base revision and idempotency semantics.
14. **Persistent undo/redo:** every introduced manual harmony edit participates in history.
15. **Portable reopen without inference:** projects reopen without model/runtime installation.
16. **Cache provenance:** all result-changing dependencies enter cache identity.
17. **Stale results remain inspectable:** staleness is a dependency warning, not destructive deletion.
18. **No hidden certainty:** ambiguity remains visible.
19. **No destructive display simplification:** view settings do not rewrite analysis.
20. **Measured quality:** model/default decisions are based on the defined corpus, not headline benchmark claims alone.

---

## 3. Work package M4.1 — Verify prerequisites and extend the domain

### 3.1 Prerequisite verification

Before adding harmony analysis:

1. Run all Milestone 0–3 checks.
2. Open every existing local WAV project used in prior milestones.
3. Verify canonical source hash, sample rate, and frame count.
4. Verify original/stem playback alignment.
5. Verify source-time selection and marker behavior.
6. Verify variable speed at representative values including 0.5×, 1×, and 1.5×.
7. Verify source and musical loops remain stable.
8. Verify the selected rhythm result/branch is addressable by stable ID when present.
9. Verify source↔musical mapping remains valid after reopen.
10. Verify snapping does not retroactively move existing objects.
11. Verify portable save/open restores rhythm state without model access.
12. Verify project command conflicts still return `409` rather than merging silently.
13. Verify prior model workers can coexist with a model-free backend startup.
14. Record baseline CPU, RAM, GPU, UI responsiveness, and audio-underrun behavior during playback.
15. Do not begin harmony-model optimization until source-time and revision behavior are trustworthy.

### 3.2 Shared chord primitive types

Define typed primitives for:

- `PitchClass`: integer `0..11` using a documented C=0 convention.
- `PitchSpelling`: validated note spelling such as `C`, `C#`, `Db`, including supported double accidentals only if/when parser tests justify them.
- `ChordLabelKind`: `structured`, `no_chord`, `unknown`, `custom`.
- `ChordQuality`: canonical normalized quality token.
- `ChordDegree`: normalized scale-degree/alteration representation for extensions/additions/omissions.
- `ChordRegionId`.
- `ChordResultId`.
- `ChordBranchId`.
- `ChordProjectionMode`: `simple`, `standard`, `detailed`.
- `ChordInputRole`: `original_mix`, `harmonic_remix`, or a future declared role.
- `HarmonyReviewState`: reuse the shared review-state contract.

All source boundaries use existing integer sample-frame rules.

### 3.3 Canonical `ChordLabel`

A structured chord contains:

- label kind = `structured`;
- root pitch class;
- preferred root spelling or null;
- normalized quality;
- normalized extension/addition/alteration/omission components;
- optional slash-bass pitch class;
- optional slash-bass preferred spelling;
- optional raw/user display text;
- parser/profile version;
- optional detector vocabulary ID/source token.

`no_chord` and `unknown` do not contain fabricated root/quality fields.

A `custom` label contains:

- original user text;
- optional best-effort parse preview not used as authoritative semantics unless the user confirms normalization.

### 3.4 Chord-analysis run record

Add `ChordAnalysisRun` containing:

- run UUID;
- project ID;
- input asset IDs and hashes;
- input role/profile;
- optional source separation result dependency;
- model/adapter ID;
- model manifest ID/hash where applicable;
- worker environment fingerprint;
- preprocessing profile/version;
- decoder profile/version;
- optional rhythm-refinement profile;
- optional selected rhythm result/branch dependency;
- requested device;
- actual device/GPU UUID when applicable;
- precision/numerical profile;
- requested parameters;
- effective parameters;
- start/end timestamps;
- status;
- raw prediction artifact ID or null;
- decoded chord result ID or null;
- warnings;
- runtime/peak-memory metrics where available.

### 3.5 Raw chord-prediction artifact manifest

For adapters exposing framewise predictions, define `ChordPredictionArtifact` with:

- artifact UUID/hash;
- parent run ID;
- source/input asset identity;
- model/adapter identity;
- model vocabulary ID and ordered label list;
- score tensor reference;
- tensor dtype;
- tensor shape;
- score semantic: logit, probability, posterior-like score, distance, heuristic, or documented adapter-specific kind;
- calibration flag;
- frame count;
- model frame-hop/alignment metadata;
- model sample-rate/preprocessing metadata;
- mapping from model-frame coordinate to project source-frame coordinate;
- padding/context metadata;
- artifact format version;
- optional top-k companion artifact only as a derived optimization, never the sole preserved representation when the full matrix is available and practical.

Initial on-disk representation for dense neural outputs:

- one immutable `.npy`-compatible or equivalently simple row-major float32 array;
- one compact JSON manifest;
- optional vocabulary JSON if not embedded in the manifest.

Do not put the full score matrix into SQLite or ordinary project JSON.

### 3.6 Native/non-framewise raw artifact manifest

For Chordino or another adapter that does not expose a compatible dense score matrix, preserve:

- exact adapter/native output file where practical;
- tool/plugin version;
- command/configuration profile;
- native segment timestamps/labels;
- any exposed strength/confidence field with its documented semantics;
- normalization/mapping metadata;
- content hash;
- artifact format version.

Do not manufacture a dense posterior matrix from segment labels merely to match the neural schema.

### 3.7 Automatic chord region record

Each automatic `ChordRegion` contains:

- UUID;
- parent automatic result ID;
- start source frame inclusive;
- end source frame exclusive;
- canonical detailed `ChordLabel`;
- raw detector label/token;
- confidence object for the selected label;
- alternative label candidates with scores/semantics where available;
- boundary confidence/evidence if available, separate from label confidence;
- optional inversion-evidence reference;
- origin/provenance;
- review state;
- flags such as low-confidence, short-region, boundary-ambiguous, inversion-ambiguous, out-of-vocabulary mapping, or adapter-warning.

Validation:

1. `0 <= start < end <= source_length`.
2. Active automatic regions are ordered.
3. Regions do not overlap within one result.
4. Gaps are explicit and meaningful rather than accidentally implied.
5. Adjacent regions may share a boundary exactly.
6. Unknown/no-chord are explicit labels rather than missing records where the decoder has classified the interval.

### 3.8 Immutable chord result

Define `ChordResult` containing:

- result UUID;
- parent run ID;
- input identity/role;
- model/adapter identity;
- raw artifact ID or null;
- decoder/smoothing profile;
- optional rhythm-refinement dependency/profile;
- ordered chord regions;
- source coverage summary;
- vocabulary capabilities;
- result-level warnings;
- validation status;
- creation timestamp;
- derived summary statistics such as region count and no-chord duration, without treating them as accuracy measurements.

### 3.9 Editable chord branch

Define `ChordBranch` containing:

- branch UUID;
- parent automatic chord result ID;
- branch revision;
- ordered editable chord regions;
- user spelling overrides;
- review states;
- optional branch-level notes/metadata;
- created/updated timestamps;
- human-review summary.

Automatic results remain immutable. All user changes target a branch.

### 3.10 Tuning estimate record

Define `TuningEstimate` containing:

- estimate UUID;
- project ID;
- analysis interval start/end source frames;
- input asset identity;
- reference pitch frequency, default display convention A4=440 Hz unless the user changes it;
- estimated cents offset relative to the reference;
- optional equivalent fitted A4 frequency;
- confidence object;
- method/profile/version;
- alternatives or multimodal evidence summary where useful;
- origin: automatic/manual;
- review state;
- warnings such as insufficient harmonic content.

Do not force an automatic estimate when the evidence is insufficient.

### 3.11 Tonal feature artifact

Define a bounded binary artifact for tonal features containing:

- artifact UUID/hash;
- parent analysis run;
- input identity;
- tuning estimate/dependency identity;
- feature type, such as chroma/HPCP-like pitch-class energy;
- frame count;
- pitch-class/bin count;
- dtype;
- frame-hop/window metadata;
- normalization profile;
- source-frame mapping;
- optional energy/quality mask;
- artifact format version.

This artifact can be reused by the independent key estimator and, where valid, by inversion evidence.

### 3.12 Key-analysis run record

Define `KeyAnalysisRun` containing:

- run UUID;
- project ID;
- input asset/hash and input role;
- key adapter/algorithm ID;
- optional Essentia runtime fingerprint;
- tuning estimate dependency;
- tonal feature artifact dependency;
- global/local analysis parameters;
- window/hop/smoothing profile;
- start/end timestamps;
- status;
- result ID;
- warnings;
- runtime metrics.

### 3.13 Key candidate record

A key candidate contains:

- tonic pitch class;
- mode identifier;
- score/confidence object;
- suggested tonic spelling;
- optional relation tag to the selected candidate, such as relative or fifth-related;
- method/provenance.

Keep score meaning explicit. Do not compare raw scores across different key algorithms as though they share one calibrated scale.

### 3.14 Key region record

Each automatic `KeyRegion` contains:

- UUID;
- parent key result ID;
- start source frame;
- end source frame;
- tonic pitch class or null;
- mode or null;
- preferred spelling suggestion;
- displayed key-signature preference/suggestion;
- confidence object;
- alternative candidates;
- origin/provenance;
- review state;
- stability state: stable, uncertain, no_stable_key, or unknown.

### 3.15 Key result

Define `KeyResult` containing:

- result UUID;
- parent run ID;
- input identity/role;
- tuning dependency;
- tonal feature artifact ID;
- algorithm/profile identity;
- global key candidate/result;
- ordered local key regions;
- alternatives;
- warnings;
- validation status;
- creation timestamp.

Global and local key outputs are separate fields. A global result must not be copied into every local region to simulate local analysis.

### 3.16 Editable key branch

Define `KeyBranch` containing:

- branch UUID;
- parent automatic key result ID;
- branch revision;
- editable key regions;
- global display/spelling override where applicable;
- user key-signature preferences;
- review states;
- created/updated timestamps.

Manual edits do not alter the automatic key result.

### 3.17 Project-level active harmony state

Extend project state with:

- active chord result ID;
- active chord branch ID or null;
- chord display source: Auto or Edited;
- chord complexity projection;
- chord lane visibility/height;
- waveform chord-overlay visibility;
- alternative-prediction display setting;
- chord review filter/threshold;
- active key result ID;
- active key branch ID or null;
- key display source: Auto or Edited;
- key lane visibility/height;
- active tuning estimate/manual tuning state;
- tuning display visibility;
- key-aware automatic chord-spelling preference;
- harmony input/result selector state;
- last selected harmony object;
- optional harmony inspector panel state.

### 3.18 Database and schema migration

1. Add ordered database migrations for harmony tables/state.
2. Update project serialization schema.
3. Update portable-project schema.
4. Preserve Milestone 0–3 projects with no harmony state.
5. Add null/default harmony fields without modifying existing audio, stems, rhythm branches, loops, or mixer state.
6. Add foreign-key relationships for run/result/branch provenance.
7. Keep large prediction/feature arrays file-backed.
8. Generate updated JSON Schema/OpenAPI/TypeScript contracts.
9. Add migration fixtures for empty, imported, separated, rhythm-corrected, looped, and portable projects.
10. Reject newer unsupported harmony schema versions without modifying them.
11. Verify rollback/backup behavior for migration failure.

**Acceptance:** the database and project schemas can represent multiple chord models, raw prediction artifacts, editable chord branches, tuning estimates, global/local key results, editable key branches, and active harmony state without changing existing source/stem/rhythm timing semantics.

---

## 4. Work package M4.2 — Define chord vocabulary, parsing, normalization, and display projection

### 4.1 Why a project-owned canonical vocabulary is required

BTC, ChordMini, and Chordino do not have to expose identical label sets or string conventions. The application therefore needs one stable semantic layer between model adapters and the editor.

The canonical layer must:

- preserve detector-native labels;
- map supported labels deterministically;
- represent editor-entered labels beyond detector vocabulary;
- support slash bass;
- preserve no-chord and unknown;
- support non-destructive complexity projections;
- round-trip through backend/frontend/persistence;
- avoid string-only business logic.

### 4.2 Root and bass pitch-class convention

Use C=0 through B=11 internally.

Spelling is a separate field.

Examples:

- C and B# may map to pitch class 0 while preserving different spelling text where supported.
- F# and Gb map to pitch class 6.
- A slash bass is a separate pitch-class/spelling pair and does not replace the root.

Do not infer spelling solely from pitch class when a key context or user spelling is available.

### 4.3 Canonical quality families

The canonical schema must be capable of representing at least the families required by the main plan/editor:

- major;
- minor;
- diminished;
- augmented;
- suspended variants;
- power/no-third where explicitly entered or supported;
- seventh families;
- detector-supported extensions;
- additions/alterations/omissions;
- slash bass.

Do not promise automatic detection of every representable family.

The representational vocabulary can be richer than any detector's recognition vocabulary.

### 4.4 Degree representation

Represent extension/alteration/addition/omission components structurally where practical, for example by:

- diatonic degree number;
- accidental offset;
- role: extension/addition/omission;
- optional normalized token.

Keep order deterministic for serialization.

Do not treat arbitrary user text as a valid structured degree without parsing/validation.

### 4.5 Canonical text rendering

Implement one versioned canonical renderer for structured labels.

Requirements:

1. Deterministic output for equal semantic labels.
2. Configurable accidental/spelling preference.
3. Slash bass rendered only when present.
4. `no_chord` rendered using a dedicated UI token such as `N`/`No chord`, with storage semantics independent of display wording.
5. `unknown` rendered distinctly, such as `?`/`Unknown`.
6. Custom text rendered exactly as stored except for safe UI escaping.
7. Never hide a parse failure by silently rewriting the user's input.

### 4.6 Parser behavior

The editor parser:

1. Trims surrounding whitespace.
2. Rejects control characters.
3. Attempts structured parsing using the versioned grammar.
4. Shows a normalized preview when successful.
5. Lets the user preserve unsupported text as `custom`.
6. Does not require every custom symbol to be understood by Tonal or the backend.
7. Does not reinterpret `N`/`X` ambiguously; dedicated UI actions exist for No chord and Unknown.
8. Preserves explicit slash bass.
9. Preserves explicit spelling.
10. Round-trips common supported symbols through Python and TypeScript tests.

### 4.7 Backend/frontend parser ownership

Use project-owned semantic tests as the authority.

The frontend may use Tonal for parsing assistance, note spelling, and music-theory utilities, but:

- backend validation must not trust arbitrary frontend-only parsing;
- persistence must use the canonical project schema;
- Tonal is not an audio analyzer;
- discrepancies between frontend and backend parsing must fail clearly rather than silently diverge.

### 4.8 Adapter vocabulary descriptors

Every chord adapter registers a descriptor containing:

- vocabulary ID/version;
- ordered detector labels;
- mapping from detector label to canonical `ChordLabel`;
- detector no-chord token(s);
- detector unknown/out-of-vocabulary behavior;
- whether inversion is encoded;
- whether extensions are encoded;
- whether spelling is encoded semantically or merely textually;
- score tensor label axis ordering;
- any labels that cannot be losslessly represented, with explicit fallback behavior.

Fail adapter qualification if vocabulary mapping is incomplete for labels the model can emit.

### 4.9 No-chord versus unknown

Use explicit semantics:

- `no_chord`: the system/model asserts no stable chord should be labeled for that interval.
- `unknown`: the system/editor does not know a suitable chord label.

Examples where `unknown` may be appropriate:

- out-of-vocabulary harmony;
- strong ambiguity;
- malformed/unsupported detector token after safe preservation;
- manually marked uncertain content.

Silence may often map to no-chord, but do not force every low-energy interval to no-chord if the detector semantics differ.

### 4.10 Complexity projection contract

Define a pure `projectChordLabel(label, mode, profileVersion)` operation.

It returns a display label, not a new analysis result.

The mapping must be table-driven and tested against the actual canonical quality families.

Rules:

1. Detailed preserves all parsed semantic components.
2. Standard retains supported mid-level quality/seventh/suspension information defined by the projection profile.
3. Simple reduces to the configured small quality family without inventing information.
4. Slash bass is retained only when the projection profile explicitly allows it; if hidden in Simple view, the inspector still shows it.
5. A hidden detail remains available when switching back to Detailed.
6. Projection of custom labels defaults to identity display unless the user explicitly normalizes the label.
7. A projection profile change is versioned as UI logic but does not stale the stored analysis.

### 4.11 Key-aware spelling resolver

Implement a deterministic display-spelling service that can consume:

- semantic chord root/bass pitch classes;
- detector spelling provenance;
- active local key region;
- project accidental preference;
- explicit per-chord user spelling override.

Priority:

1. Explicit per-chord user spelling override.
2. Explicit custom label text.
3. Active local key spelling preference when enabled.
4. Detector/native spelling if valid and not contradictory to an explicit project preference.
5. Deterministic default spelling table.

Changing key spelling can update derived display text but must not create a chord-edit command unless the user explicitly chooses to store a chord spelling override.

### 4.12 Canonical-label tests

Create exhaustive unit cases for:

- every registered detector label;
- roots with sharps/flats;
- major/minor triads;
- seventh families supported by mappings;
- diminished/augmented/suspended examples;
- slash chords;
- no-chord;
- unknown;
- custom labels;
- parser failure;
- serialization round trip;
- frontend/backend canonical-render agreement;
- Simple/Standard/Detailed projection stability;
- key-aware respelling without semantic mutation.

**Acceptance:** every adapter label has an explicit deterministic mapping, user-entered rich/custom labels survive round trips, complexity changes are non-destructive, and no-chord/unknown remain semantically distinct.

---

## 5. Work package M4.3 — Integrate harmony runtimes, adapters, model registry, and license boundaries

### 5.1 Runtime-isolation policy

Follow the project's existing research-package isolation rule.

Use separate locked environments when dependency compatibility is not demonstrated.

Initial expected boundaries:

- BTC neural worker environment.
- ChordMini neural worker environment.
- Chordino native adapter/runtime boundary.
- Essentia key-analysis environment or isolated native/Python worker as required by the verified package.
- Project-owned lightweight tonal utilities in the normal analysis environment only when their dependencies are already compatible and licensed for that role.

Do not force all research packages into the core FastAPI environment.

### 5.2 BTC adapter

The BTC adapter must declare:

- stable module ID/version;
- pinned upstream revision;
- pinned runtime dependencies;
- model/checkpoint manifest;
- label vocabulary descriptor;
- preprocessing requirements;
- output tensor semantics;
- CPU/GPU support;
- expected memory class;
- cancellation behavior;
- determinism limitations;
- license/provenance records.

### 5.3 ChordMini adapter

The ChordMini adapter must independently declare the same information.

Do not assume ChordMini can share BTC's environment merely because it uses related vocabulary/model concepts.

Qualification determines whether shared dependencies are actually safe.

### 5.4 Chordino adapter

Integrate Chordino as a local deterministic comparison/fallback through a registered native path, such as the project's selected Vamp/Sonic Annotator hosting approach.

Requirements:

1. Detect runtime/plugin availability without network access.
2. Record exact native executable/plugin versions.
3. Use argument arrays rather than shell command strings.
4. Pass only managed local audio paths.
5. Bound captured output.
6. Parse output through a versioned adapter.
7. Preserve native output artifact where practical.
8. Record GPL/native licensing implications separately from neural model licensing.
9. Do not silently install native plugins during analysis.
10. Report unavailable fallback clearly when the plugin is not installed/bundled.

### 5.5 Essentia key adapter

Integrate the main plan's Essentia `KeyExtractor` behind its own adapter boundary.

Requirements:

- no Essentia import during ordinary core backend startup;
- explicit runtime availability check;
- version/profile provenance;
- deterministic request/response schema;
- tuning-aware preprocessing where the selected method requires it;
- no neural model download for this key module;
- separate AGPL/library license record and packaging decision.

### 5.6 Model registry entries

Create checked-in registry entries for neural chord models selected during implementation.

Each entry records:

- stable basseparate model ID;
- human-readable name;
- adapter/engine requirement;
- upstream source/revision;
- checkpoint/configuration identity;
- official download URL/resolver information;
- expected byte size when determinable;
- SHA-256 hash resolved during implementation;
- vocabulary ID;
- preprocessing declaration;
- code license;
- weight license/provenance separately;
- required notices;
- bundled-versus-separate-install status;
- adapter compatibility range.

Do not invent artifact hashes in this specification.

### 5.7 Installation workflow

Reuse the registry/provenance conventions from Milestone 2 and the separate durable network-download model-install flow established in Milestone 3:

1. Show model name and purpose.
2. Show expected download size where known.
3. Show source/provenance/license summary.
4. Require explicit Install.
5. Download to staging.
6. Report byte progress.
7. Support cancellation.
8. Resume only where safe metadata supports it.
9. Verify content hash.
10. Verify manifest/configuration pairing.
11. Publish atomically.
12. Start the adapter with network access disabled for qualification.
13. Run a short deterministic/known fixture.
14. Mark installed only after qualification succeeds.

### 5.8 Offline registered-model import

Support a local registered bundle:

1. Read expected manifest.
2. Verify model ID/revision.
3. Verify all hashes.
4. Preserve notices.
5. Reject arbitrary worker code.
6. Install into managed model storage.
7. Qualify with network disabled.
8. Record installation provenance as offline import.

### 5.9 Device qualification

For BTC and ChordMini separately:

1. Start the correct locked worker.
2. Load the exact registered model.
3. Run a short fixture.
4. Confirm finite outputs.
5. Validate output shape/vocabulary axis.
6. Validate source-time alignment.
7. Record elapsed time.
8. Record host RAM and GPU VRAM where available.
9. Record runtime/driver and GPU UUID.
10. Mark the model/device pair qualified only after successful inference.

A device qualified for Demucs or Beat This! is not automatically qualified for BTC/ChordMini.

### 5.10 Scheduling preference

Initial policy:

- harmony analysis may use the RTX 5060 Ti when qualified and free;
- it may use the RTX 4080 when appropriate and not occupied by heavier separation work;
- CPU execution is available where the adapter supports it;
- one heavy model job per GPU remains the default;
- playback responsiveness remains higher priority than analysis throughput.

Do not combine VRAM pools.

### 5.11 CPU fallback

For adapters supporting CPU:

- bound CPU thread use;
- label execution as potentially slower;
- preserve the same output schema;
- do not silently switch from requested GPU to CPU after GPU failure;
- let the user choose CPU explicitly or configure a deliberate fallback policy later.

Chordino is a separate fallback/comparison adapter, not an automatic substitute that hides a failed neural run.

### 5.12 No hidden downloads or remote code

Before inference:

1. Resolve adapter/runtime.
2. Resolve model manifest if required.
3. Verify local artifacts.
4. Pass explicit local paths.
5. Disable remote fallback.
6. Reject missing model with `MODEL_NOT_INSTALLED` or adapter-specific availability error.
7. Do not execute arbitrary checkpoint-provided Python hooks.
8. Do not fetch code because a project is opened.

### 5.13 License/packaging gate

Before declaring a harmony adapter bundled for a release:

- verify code license;
- verify weight/checkpoint terms separately;
- verify native plugin/library redistribution obligations;
- record required notices;
- decide bundled versus separately installed status;
- ensure the actual packaging configuration matches the license manifest.

Private use does not remove the need to record these terms correctly.

**Acceptance:** each harmony/key adapter has an isolated reproducible execution path, explicit availability/model state, verified provenance, no inference-time download, and a clear packaging/license status.

---

## 6. Work package M4.4 — Prepare harmony-analysis inputs reproducibly

### 6.1 Default original-mix input

Use the same project reference-mix convention already established for analysis.

- Mono source: use the canonical mono representation transformed only as required by the adapter.
- Stereo source: use canonical stereo unless the adapter declares a different channel requirement.
- Multichannel source: use the explicit documented stereo reference/monitoring downmix from earlier milestones.

Record the exact source asset/hash and downmix identity.

### 6.2 Model-specific analysis representation

For each adapter:

1. Read declared sample-rate/channel requirements.
2. Resolve or create a cached continuous analysis representation.
3. Resample continuously, not independently per inference HTTP chunk.
4. Apply documented channel transform.
5. Record amplitude/normalization transform.
6. Preserve source-time mapping.
7. Record endpoint rounding.
8. Validate duration.
9. Keep the canonical source unchanged.

### 6.3 Optional non-drum harmonic remix

When an active compatible four-stem separation result contains an aligned drum stem, offer a separate input profile:

`harmonic_non_drum = vocals + bass + other`

or equivalently the sum of all declared non-drum stems in that four-stem result.

Rules:

1. Use the raw aligned analysis stems, not current mixer gain/pan/mute state.
2. Use one exact selected separation result-set ID.
3. Require matching source rate/alignment/frame count.
4. Sum in bounded chunks with a higher-precision accumulator where useful.
5. Store/publish a derived immutable analysis input asset or streamable transformation cache.
6. Record every contributing stem hash and transform version.
7. Do not normalize the remix independently unless a versioned adapter preprocessing step requires it.
8. Do not call this the original mix.
9. Analyze it as a separate chord/key run/result.
10. Never silently promote it over the original-mix result.

If only Bass+Others mode exists without a separate drum stem, this specific profile is unavailable until a compatible retained four-stem result exists.

### 6.4 Harmonic-remix reconstruction diagnostics

Record:

- source separation result ID;
- included stem roles;
- excluded stem roles;
- peak/RMS level summary;
- frame count/alignment validation;
- any nonfinite/clipping diagnostic;
- transformation hash.

Do not treat lower percussion energy as proof that chord recognition will be better.

### 6.5 Tuning-aware tonal analysis input

Key/tuning pipeline order:

1. Select original mix by default.
2. Estimate tuning from a declared analysis signal/profile.
3. Create tuning-aware tonal features.
4. Run key algorithms.

If the user manually changes tuning context, tonal feature/key results depending on the old tuning context become stale but remain available.

### 6.6 Optional harmonic-remix key analysis

The user may explicitly run key analysis on the same non-drum harmonic remix.

Store as a separate result.

Do not replace original-mix key analysis automatically.

### 6.7 Optional rhythm context

Default chord/key input preparation does not require rhythm.

A later stage may consume selected rhythm context for:

- optional chord-boundary refinement;
- UI bar/beat context;
- evaluation grouping;
- manual snapping.

Key analysis does not require beat quantization.

### 6.8 Short/silent/degenerate input handling

Handle explicitly:

- pure silence;
- near silence;
- very short clips;
- long silent intro/outro;
- percussion-only material;
- single sustained tone;
- heavily detuned material;
- clipping/high crest-factor material;
- multichannel sources represented through the documented stereo downmix.

Rules:

1. Silence may produce no-chord and no-stable-key outcomes.
2. Do not fabricate a constant chord/key to fill unsupported evidence.
3. Preserve raw model output when it is valid even if downstream decoding decides `unknown`.
4. Return an explicit insufficient-evidence key/tuning state where appropriate.
5. Never let a near-zero normalization statistic create unbounded values.

### 6.9 Long-track processing

Prefer each pinned adapter's validated long-track path.

If custom chunking is required:

1. Define a versioned chunk/context profile.
2. Include enough context for the model receptive field.
3. Overlap windows where needed.
4. Merge output in model/source coordinates deterministically.
5. Remove duplicated/padded frame outputs.
6. Validate against a short whole-input reference path.
7. Include chunk profile in cache identity.
8. Keep host/GPU memory bounded.
9. Do not publish partial score matrices as complete.

### 6.10 Input/cache identity

Input-preparation identity includes:

- source asset hash;
- selected source stream/downmix identity;
- optional separation result and stem hashes;
- input-role/profile;
- adapter/model manifest;
- preprocessing profile/version;
- sample-rate/channel transform;
- normalization profile;
- analysis interval/context profile where applicable.

**Acceptance:** original and optional harmonic-remix inputs are immutable, aligned, reproducible, separately identified, and auditable back to exact source/stem assets.


---

## 7. Work package M4.5 — Run BTC and preserve raw neural predictions

### 7.1 BTC worker capability declaration

The BTC worker advertises:

- stable module ID/version;
- supported model IDs;
- supported input roles;
- expected sample-rate/channel format;
- output vocabulary ID;
- raw score/logit capability;
- score semantic;
- CPU/GPU support;
- expected memory class;
- cancellation granularity;
- determinism limitations;
- raw artifact schema;
- decoded-result schema compatibility;
- confidence capabilities;
- license records.

### 7.2 BTC inference sequence

1. Validate project/run request.
2. Resolve the exact input asset/profile.
3. Resolve the registered BTC model manifest.
4. Verify required local checkpoint/configuration bytes.
5. Resolve selected qualified device.
6. Start the BTC worker using its explicit interpreter.
7. Load the model without network fallback.
8. Warm up only if required by the pinned implementation.
9. Run preprocessing/inference using the validated long-track profile.
10. Emit progress by processed model windows/frames where possible.
11. Collect the full label-axis output exposed by the model.
12. Validate finite values.
13. Validate label dimension against the registered vocabulary descriptor.
14. Validate model-frame ordering and count.
15. Write the score tensor to staging.
16. Write the prediction manifest.
17. Hash staged artifacts.
18. Publish atomically.
19. Release device/model resources according to worker policy.
20. Mark raw-prediction stage complete.
21. Queue/reuse the configured chord decoder.

### 7.3 Raw-output preservation

Preserve the model output before project-owned temporal decoding.

Do not:

- collapse immediately to argmax labels and discard alternatives;
- destructively threshold low scores;
- round timestamps repeatedly;
- map model labels by ad-hoc string handling;
- call uncalibrated values probabilities;
- convert every frame/label cell into JSON.

### 7.4 Tensor format and access

Initial dense score artifact rules:

- row major: model frames × vocabulary labels;
- float32 unless the verified model output or storage study justifies another explicit dtype;
- immutable after publication;
- content hashed;
- label axis tied to a vocabulary hash/version;
- frame alignment tied to a preprocessing/profile hash;
- optionally memory-mappable by backend analysis tools;
- accessed by bounded API ranges for diagnostics, never full-song by default in the browser.

### 7.5 Source-frame mapping

For each model frame:

1. Keep model-frame coordinate authoritative within the raw artifact.
2. Derive a fractional source-frame coordinate using the stored preprocessing transform.
3. Round only when producing a discrete source-time boundary/candidate.
4. Use one documented rounding rule.
5. Record padding/context offset.
6. Validate first/final model frames against source duration.

### 7.6 BTC progress reporting

Progress phases:

- Preparing input.
- Loading BTC model.
- Running inference.
- Writing predictions.
- Validating raw artifact.
- Decoding chord regions.

Only show determinate percentage when a reliable denominator is available.

### 7.7 BTC cancellation

1. Mark job cancelling.
2. Signal worker.
3. Stop scheduling new inference windows.
4. Check cancellation at bounded model/window boundaries.
5. Close or discard incomplete score files.
6. Remove incomplete staging manifests.
7. Release GPU through worker cleanup/process exit if necessary.
8. Preserve installed model/input caches.
9. Preserve earlier completed chord results.

### 7.8 BTC crash recovery

If raw artifact publication is incomplete, restart that stage from a safe boundary.

Completed prepared inputs remain reusable.

A published complete raw prediction artifact can be decoded again without neural rerun.

### 7.9 BTC qualification fixtures

At least one qualification fixture must verify:

- model loads;
- output vocabulary size matches registry;
- outputs are finite;
- no external request occurs;
- mapping yields source positions within duration;
- deterministic/stochastic behavior matches documented expectations;
- a simple known harmony excerpt produces a parseable label sequence, without treating that single fixture as an accuracy benchmark.

**Acceptance:** BTC produces an immutable source-aligned raw prediction artifact that can be independently re-decoded, with explicit score semantics and no inference-time network access.

---

## 8. Work package M4.6 — Run ChordMini as an independent challenger

### 8.1 Independent adapter identity

ChordMini is a separate module/model result, not a mode flag on BTC.

Record:

- distinct adapter ID/version;
- distinct environment fingerprint;
- distinct checkpoint/configuration manifest;
- distinct vocabulary descriptor even if labels overlap BTC;
- distinct preprocessing profile;
- distinct output-score semantics;
- distinct resource measurements.

### 8.2 ChordMini inference sequence

Use the same general lifecycle as BTC:

1. Validate model installation.
2. Resolve input.
3. Resolve qualified device.
4. Load model.
5. Run pinned preprocessing/inference.
6. Retain raw framewise outputs where exposed.
7. Validate output against its own vocabulary descriptor.
8. Publish raw artifact atomically.
9. Decode through the project-owned canonical chord pipeline.
10. Publish a separate automatic chord result.

### 8.3 No shared-result identity with BTC

Even if BTC and ChordMini emit identical visible labels for a passage:

- they retain separate run IDs;
- raw artifact hashes differ or remain separately referenced;
- confidence/score semantics remain model-specific;
- model provenance remains visible;
- one result is never silently deduplicated against another solely because final labels match.

### 8.4 Reuse shared preprocessing only when valid

An analysis representation may be shared only if:

- required sample rate matches;
- required channel transform matches;
- amplitude/feature preprocessing identity matches;
- the transformation key proves equivalence.

Do not share a cached representation merely because both adapters accept WAV/audio input.

### 8.5 ChordMini cancellation/failure

Use the same durable job semantics as BTC.

A ChordMini failure must not invalidate existing BTC/Chordino results.

### 8.6 Challenger comparison readiness

Store enough metadata to compare BTC and ChordMini on:

- identical source/input profile;
- vocabulary projections;
- region boundaries;
- alternatives/confidence semantics;
- runtime;
- memory;
- correction burden.

### 8.7 Default-selection policy

BTC remains the initial baseline named by the main plan until the project's evaluation/promotion rule supports a default change.

ChordMini is presented as a named challenger rather than being called universally better before measurement.

**Acceptance:** ChordMini can be installed, qualified, run, retained, edited from, and compared with BTC without dependency/result conflation.

---

## 9. Work package M4.7 — Integrate Chordino as a deterministic CPU-oriented fallback/comparison

### 9.1 Availability model

Chordino availability has explicit states:

- available and qualified;
- runtime/executable missing;
- plugin missing;
- incompatible version;
- disabled by packaging/license policy;
- failed qualification.

Do not show an unavailable adapter as though it can run.

### 9.2 Native host invocation

The adapter:

1. Resolves the registered Sonic Annotator/Vamp host path selected by implementation.
2. Resolves the Chordino plugin identifier/path.
3. Uses a managed local analysis input.
4. Invokes with an argument array.
5. Disables/avoids stdin interaction as appropriate.
6. Applies a timeout/cancellation mechanism.
7. Captures bounded stdout/stderr.
8. Writes native output into a staging location.
9. Validates process exit.
10. Parses the exact native format through a versioned parser.
11. Publishes native output plus normalized result provenance.

### 9.3 Native output preservation

Preserve the original normalized native output file when practical.

Record:

- native timestamp units;
- plugin parameters;
- plugin/host versions;
- source input identity;
- exact command profile excluding sensitive paths where necessary;
- any native strength/confidence field.

### 9.4 Chordino canonical mapping

Map every Chordino label encountered in the supported configuration through the same `ChordLabel` normalization layer.

If the native tool emits a label outside the registered mapping:

- preserve the raw token;
- map to `unknown` or `custom` according to the adapter's explicit policy;
- raise an adapter warning;
- do not crash the entire project unless schema safety requires it.

### 9.5 Confidence behavior

If Chordino does not provide a meaningful probability:

- use `unavailable` or a documented heuristic/strength kind;
- do not invent a probability;
- preserve alternative information only when the native implementation actually exposes it.

### 9.6 CPU/resource behavior

Measure:

- elapsed time per track minute;
- CPU utilization;
- peak host RAM;
- output artifact size.

Limit concurrent native analysis so playback remains responsive.

### 9.7 Fallback semantics

Chordino is available as an explicit user-selected adapter and may be offered when neural models are unavailable.

It is not silently run after a neural failure unless a future user-configured policy explicitly requests that behavior.

### 9.8 Offline behavior

Once the host/plugin are installed locally, Chordino analysis requires no network access.

**Acceptance:** Chordino provides a separately identifiable, local, reproducible chord result with honest score semantics and no hidden neural-model or network dependency.

---

## 10. Work package M4.8 — Decode raw predictions into source-time chord regions

### 10.1 Decoder boundary

The chord decoder is a project-owned stage separate from neural inference.

Benefits:

- raw predictions can be re-decoded without rerunning a model;
- temporal smoothing changes have separate cache identity;
- different decoders can be compared later;
- source-time region semantics are consistent across neural adapters.

Chordino may already provide segments; its adapter still passes them through canonical validation/normalization, while decoder-only logic that requires frame scores is skipped or adapted explicitly.

### 10.2 Decoder input

Neural decoder consumes:

- raw prediction artifact hash;
- vocabulary descriptor;
- model-frame/source mapping;
- decoding profile;
- smoothing profile;
- no-chord policy;
- optional region-minimum policy;
- optional adapter-native decoder hints.

### 10.3 Initial decoder policy

Prefer the pinned model implementation's documented/reference decoding behavior as the first profile where available.

Wrap it behind a basseparate decoder profile so:

- parameters are explicit;
- behavior is testable;
- profile changes produce new result identity;
- raw artifacts remain reusable.

Do not invent a bespoke decoder solely to make regions look smoother before baseline behavior has been measured.

### 10.4 Frame-label sequence

For each model frame:

1. Validate score row length.
2. Determine selected label according to decoder/profile.
3. Retain top alternatives if configured and available.
4. Preserve no-chord token behavior.
5. Map label through vocabulary descriptor.
6. Preserve original token/index.
7. Attach score semantics.

### 10.5 Temporal smoothing

Smoothing is configurable and versioned.

Potential operations may include model-native postprocessing, median-like label smoothing, transition penalties, or short-segment suppression, but each enabled operation must:

- have a deterministic profile;
- be included in cache identity;
- be validated not to destroy genuine rapid chord changes on the evaluation corpus;
- never merge `unknown`/`no_chord` merely because their strings are empty.

### 10.6 Region construction

1. Convert the decoded frame sequence into contiguous label runs.
2. Determine source-frame boundaries from the stored frame alignment.
3. Use half-open intervals.
4. Merge adjacent identical canonical labels only when there is no meaningful boundary/evidence distinction required by the profile.
5. Preserve raw boundary evidence where available.
6. Ensure source-frame monotonicity.
7. Clamp only legitimate endpoint rounding.
8. Reject material out-of-bounds mapping errors.
9. Cover or explicitly account for the analyzed interval.
10. Avoid accidental one-frame gaps due to rounding.

### 10.7 Boundary mapping rule

Use a single documented frame-to-boundary convention based on the pinned model output alignment.

Do not assume the model score timestamp is automatically the left edge of a frame.

Verify whether the upstream alignment is centered, left-aligned, or otherwise offset.

Store that decision in the preprocessing/decoder profile.

### 10.8 Region alternatives

For a resulting region, derive alternatives conservatively from the underlying score rows when available.

Record:

- candidate canonical label;
- aggregated score/statistic;
- score kind;
- calibration flag;
- aggregation method/version.

Do not claim region confidence is a calibrated probability merely because per-frame values are normalized.

### 10.9 Short-region diagnostics

Flag very short regions for review rather than automatically deleting every short event.

If a smoothing profile suppresses/merges them, preserve enough provenance to compare with unsmoothed output.

### 10.10 `no_chord` and `unknown` decoding

Keep separate transitions and regions.

A decoder may emit:

- no-chord because the model explicitly predicts its no-chord class;
- unknown because mapping is unsupported/ambiguous or a review profile marks insufficient evidence.

Do not convert unknown to no-chord for display convenience.

### 10.11 Decoder caching

Cache key includes:

- raw prediction artifact hash;
- vocabulary mapping version;
- decoder implementation version;
- smoothing profile;
- all result-changing thresholds/parameters.

### 10.12 Re-decoding workflow

Expose a developer/user-facing advanced action where appropriate to create a new automatic result from an existing raw artifact using another decoder profile.

Neural inference is not rerun unless the raw artifact/model input changed.

**Acceptance:** neural/raw outputs can be converted into validated non-overlapping source-time chord regions reproducibly, with no-chord/unknown preserved and all smoothing decisions versioned.

---

## 11. Work package M4.9 — Publish immutable chord results and editable branches

### 11.1 Automatic result publication

A chord result becomes complete only after:

- raw/native artifact is valid or explicitly not applicable;
- decoded regions validate;
- vocabulary mappings validate;
- source coverage/alignment validates;
- confidence semantics are attached;
- provenance/cache identity is complete.

Publication sequence:

1. Publish raw/native artifacts.
2. Publish decoded region artifact/data.
3. Create `ChordResult` record.
4. Commit references transactionally.
5. Mark run complete.
6. Notify frontend/result selector.

### 11.2 Progressive UI availability

The UI may show stages such as:

- model running;
- raw predictions available;
- decoding;
- chord result available;
- optional inversion analysis pending;
- optional rhythm refinement pending.

Do not show an incomplete result as final.

### 11.3 Editable branch creation

When the user first performs a semantic chord edit:

1. Create a branch referencing the selected immutable result.
2. Copy/logically overlay the current regions.
3. Preserve source region IDs/provenance where feasible.
4. Apply the edit within the same transaction.
5. Increment project revision.
6. Leave automatic result unchanged.

### 11.4 Auto/Edited switching

Provide explicit Auto/Edited selection.

Switching:

- is undoable when it changes active project analysis source;
- updates chord lane/overlay/readout/review navigation consistently;
- does not move rhythm objects, loops, markers, or key regions;
- does not delete either version.

### 11.5 Multiple automatic results

Result selector displays at least:

- adapter/model name;
- input role: original/harmonic remix;
- decoder profile;
- optional rhythm-refinement marker;
- creation time;
- stale status;
- device/runtime summary in inspector;
- provenance details.

### 11.6 Rerunning chord analysis

1. Create a new automatic run/result.
2. Keep earlier automatic results.
3. Keep every edited branch.
4. Do not merge new model regions into an old edited branch automatically.
5. Let the user select the new result or create a new branch.
6. Preserve existing active branch until the user chooses otherwise.

### 11.7 Active-result staleness

If an active result becomes stale due to an upstream dependency change:

- keep it selectable/playable/displayable;
- show stale reason;
- do not rewrite/delete it;
- offer rerun/recompute where possible.

### 11.8 Branch provenance after edits

Each edited region keeps where practical:

- parent automatic region ID;
- original automatic label;
- original model confidence;
- original boundaries;
- edit/review state.

A human correction does not overwrite the model's original confidence with 1.0.

### 11.9 Named branch boundary

Milestone 4 requires at least one editable branch per parent result and the ability to retain branches.

A full branch-management/version-comparison dashboard remains a later workflow enhancement.

**Acceptance:** automatic chord output is immutable, manual corrections survive reruns/result switching, and every active view can identify the exact source result/branch it is displaying.

---

## 12. Work package M4.10 — Add optional rhythm-aware chord-boundary refinement

### 12.1 Purpose

Musical beats/bars can provide useful boundary context, but the main plan explicitly avoids mandatory beat quantization.

Therefore rhythm-aware refinement is a separate optional automatic stage/result.

### 12.2 Explicit dependency

The refinement request includes:

- source chord result ID;
- selected rhythm result/branch ID;
- selected rhythm branch revision/identity;
- refinement profile/version;
- optional maximum displacement profile.

Do not resolve "latest rhythm" implicitly.

### 12.3 Eligible rhythm targets

Depending on profile, candidate targets may include:

- bar boundaries;
- primary beat boundaries;
- selected subdivisions.

Do not create targets in `unmapped` regions.

Treat uncertain/unmetered context according to explicit profile rules.

### 12.4 Boundary evidence

For each chord boundary:

- retain original source frame;
- inspect nearby rhythm candidates;
- retain model transition evidence around the boundary where raw scores exist;
- decide whether a move is supported by the profile;
- record the selected target and displacement;
- retain reason/score diagnostics.

### 12.5 No blind quantization

The refiner must not simply round every boundary to the nearest beat.

At minimum, it must:

- retain boundaries when model evidence strongly supports an off-beat change;
- enforce a bounded displacement policy;
- preserve ordering/non-overlap;
- avoid collapsing neighboring regions;
- preserve no-chord transitions appropriately;
- flag ambiguous cases instead of forcing a target.

### 12.6 Profile tuning

Do not invent a universal displacement threshold in this design document.

Choose/measure the initial threshold/profile using the annotated evaluation corpus and record it as a versioned implementation parameter.

### 12.7 Source-time output

Even refined boundaries are stored as integer source frames.

The rhythm/musical target is provenance, not the authoritative persisted boundary coordinate.

### 12.8 Grid changes

If the referenced edited rhythm branch changes:

- mark the refined chord result stale;
- keep it available;
- do not move its boundaries automatically;
- offer recomputation as a new result.

The unrefined chord result remains valid.

### 12.9 Manual snapping remains separate

A user dragging an edited chord boundary with Beat/Bar snapping is performing a manual project command.

That command does not rerun or mutate the automatic rhythm-refinement result.

### 12.10 Evaluation

Compare:

- unrefined boundary precision/recall;
- refined boundary precision/recall;
- duration-weighted chord accuracy;
- number of harmful boundary moves;
- manual correction burden.

Do not enable refinement by default solely because boundaries look visually neater.

**Acceptance:** rhythm-aware refinement can improve/test chord boundaries without making the musical grid a hidden mandatory dependency or destructively quantizing source-time harmony.

---

## 13. Work package M4.11 — Add conservative inversion evidence without full bass transcription

### 13.1 Scope boundary

Milestone 4 needs inversion entry and can propose inversion evidence, but Milestone 5 owns bass-note transcription.

Therefore Milestone 4 may estimate a chord-region bass pitch class only as harmony evidence.

It must not create note onset/offset events, MIDI bass notes, fingering, slides, or a bass transcription lane.

### 13.2 Evidence sources

Use, in priority order where available:

1. Detector-native inversion/slash-bass prediction if the model explicitly supports it.
2. Sustained low-frequency pitch-class evidence from an aligned bass stem.
3. Sustained low-frequency pitch-class evidence from the original/harmonic input when no bass stem is available.

Each source is identified separately.

### 13.3 Low-frequency evidence representation

A project-owned lightweight inversion-evidence extractor may compute:

- low-frequency spectral/harmonic pitch-class energy;
- region-level dominant pitch-class candidates;
- temporal stability/dominance over the chord region;
- energy/voicing sufficiency indicators.

It does not segment note events.

### 13.4 Passing-bass protection

A short transient/passing low pitch must not automatically become slash bass.

Require region-level sustained/stable evidence according to a versioned profile before proposing a candidate.

If evidence is mixed:

- retain alternatives;
- mark inversion ambiguous;
- leave the chord's slash bass unset automatically unless the model natively predicted one under its own declared semantics.

### 13.5 Chord-tone relationship

For a candidate bass pitch class:

- record whether it is a chord tone under the canonical label;
- do not reject non-chord tones outright, because real harmony/pedal tones can be complex;
- use relationship as review evidence, not an absolute rule.

### 13.6 Result representation

Define `InversionEvidence` with:

- evidence UUID;
- chord region/result ID;
- candidate bass pitch classes/spellings;
- score/confidence semantics;
- source type: model/bass-stem/original-lowband;
- stability summary;
- chord-tone relationship;
- ambiguity flag;
- method/profile/version;
- optional source artifact reference.

### 13.7 User interaction

Inspector shows:

- current slash bass if any;
- detector-native inversion evidence;
- low-frequency candidate evidence;
- alternatives;
- action to apply candidate as an edit;
- action to clear slash bass;
- direct slash-chord text entry.

Applying a candidate is a normal undoable chord-label edit.

### 13.8 Key-aware slash spelling

Use the same spelling resolver for slash bass as chord root unless the user explicitly overrides the bass spelling.

### 13.9 Future Milestone 5 handoff

Milestone 5 may later provide corrected bass notes as stronger inversion evidence.

That future integration must produce a new explicitly dependent analysis/review suggestion. It must not retroactively rewrite Milestone 4 edits.

**Acceptance:** the editor can represent and manually correct inversions, while automatic inversion suggestions remain conservative, source-identified, and clearly separate from bass-note transcription.

---

## 14. Work package M4.12 — Estimate tuning and build reusable tonal features

### 14.1 Tuning-analysis purpose

Estimate systematic pitch offset before aggregating energy into pitch classes for key analysis.

This reduces errors where detuned recordings smear or shift chroma evidence.

### 14.2 Default reference convention

Use A4=440 Hz as the default reference convention for displaying offset.

Store the actual configured reference explicitly so future user changes are unambiguous.

### 14.3 Project-owned tuning estimator

Implement a lightweight versioned tuning estimator using audio-derived harmonic/spectral evidence.

The implementation may use established NumPy/SciPy/librosa primitives available in the harmony analysis environment, but the project owns:

- preprocessing profile;
- candidate aggregation;
- confidence/insufficient-evidence semantics;
- source-time mapping;
- output schema;
- tests.

### 14.4 Estimation sequence

1. Resolve analysis input.
2. Exclude or downweight near-silent frames.
3. Compute suitable spectral/pitch-class evidence.
4. Measure offsets of stable harmonic peaks relative to equal-tempered bin centers.
5. Aggregate offsets robustly modulo 100 cents.
6. Detect multimodal/ambiguous distributions.
7. Return best estimate or insufficient evidence.
8. Record confidence kind/method.
9. Publish estimate.

### 14.5 Offset convention

Document sign convention explicitly.

For example, positive cents means the recording is sharper than the configured equal-tempered reference.

Use the same convention in backend, UI, tests, and later Milestone 5 pitch labeling.

### 14.6 Range/ambiguity behavior

Do not assume every recording lies within a tiny offset.

Handle:

- near-zero offset;
- moderately flat/sharp recordings;
- offsets near ±50 cents where neighboring semitone interpretation becomes ambiguous;
- broad/multimodal tuning evidence;
- intentionally microtonal/non-12TET material by returning low confidence/unsupported rather than forcing a misleading global correction.

### 14.7 Tonal feature extraction

After selecting automatic or manual tuning context:

1. Compute a tuning-adjusted spectral representation.
2. Aggregate into 12 pitch-class energy bins or the verified KeyExtractor-required tonal representation.
3. Retain framewise/short-window feature matrix as a binary artifact.
4. Retain frame energy/quality mask.
5. Store frame hop/window/source mapping.
6. Preserve enough information for local key windows.
7. Normalize according to a versioned profile.

### 14.8 Feature reuse

The independent key estimator can reuse the tonal artifact.

Essentia may use its own internal features if required, but its result must still record the same tuning/input context.

Inversion evidence may reuse compatible low-frequency tonal data only when the artifact/profile is appropriate; do not misuse a full-band key chroma matrix as bass evidence without validation.

### 14.9 Manual tuning state

User may set:

- reference A4 frequency;
- cents offset;
- reset to automatic estimate;
- mark reviewed.

Manual tuning creates/updates project analysis state and is undoable.

### 14.10 Tuning dependency staleness

If the active tuning context changes:

- tonal feature artifacts tied to the previous context remain immutable;
- key results dependent on them become stale;
- chord neural raw results remain valid unless their adapter preprocessing explicitly depends on tuning;
- inversion/key-aware display can recompute derived display/evidence as defined by its dependency graph.

### 14.11 Tuning tests

Create fixtures with known global detuning, including:

- 0 cents;
- positive/negative offsets;
- pure chords;
- harmonic mixtures;
- silence;
- percussion-only;
- vibrato/modulation;
- ambiguous/microtonal cases.

Measure cents error on supported synthetic/known fixtures.

**Acceptance:** the project has a reproducible tuning context and reusable source-aligned tonal feature artifact, while unsupported/ambiguous tuning is represented honestly rather than forced.

---

## 15. Work package M4.13 — Implement global and local key analysis

### 15.1 Two independent initial algorithms

Implement:

1. Essentia `KeyExtractor` adapter as the initial external key-analysis baseline.
2. Project-owned chroma/profile-correlation estimator as an independent comparison/fallback.

Keep result identities separate.

### 15.2 Project-owned profile-correlation estimator

The project-owned estimator consumes tuning-aware tonal features and:

1. Aggregates features over a requested interval/window.
2. Computes candidate scores for supported tonic/mode profiles.
3. Normalizes/compares scores according to a versioned method.
4. Returns the selected candidate plus alternatives.
5. Identifies relative-major/minor alternatives explicitly where applicable.
6. Returns low-confidence/unknown when score separation is inadequate.

The exact profile set and coefficients are implementation-versioned and covered by tests/evaluation.

### 15.3 Essentia baseline

The Essentia adapter:

- receives the managed local input or required feature representation;
- receives/records tuning context as supported by the selected configuration;
- runs global key extraction with explicit parameters;
- returns tonic/mode/strength information according to documented semantics;
- maps output to canonical key candidate schema;
- records library/profile version.

### 15.4 Global key result

For each algorithm:

- analyze the full supported project interval;
- return best tonic/mode or unknown/no-stable-key;
- retain alternatives;
- retain score semantics;
- suggest spelling separately.

Do not infer a notated key signature as an observed ground truth.

### 15.5 Local-key windowing

Use overlapping source-time windows with a versioned profile.

The profile declares:

- window duration or musical-duration rule if a rhythm-aware experimental profile is added later;
- hop duration;
- edge handling;
- minimum tonal evidence;
- smoothing/transition behavior.

Initial local-key analysis should not require a rhythm grid.

### 15.6 Window-level candidates

For every local window:

- compute best candidate;
- retain top alternatives/margins;
- record tonal-energy adequacy;
- permit unknown/no-stable-key;
- map window center/span to source frames.

### 15.7 Local-key sequence smoothing

Decode/smooth window candidates into key regions using a versioned sequence profile.

Goals:

- suppress implausible frame-to-frame flicker;
- preserve real modulations;
- avoid forcing a single key across chromatic/ambiguous passages;
- permit no-stable-key regions;
- retain original window evidence for review.

### 15.8 Boundary placement

Local key-region boundaries remain source frames.

Initial boundary placement may use window transition locations/interpolation.

No mandatory bar snapping.

Manual key-region boundary editing can use the existing snapping system.

### 15.9 Relative-major/minor handling

For each selected candidate where applicable:

- identify the relative pair as an alternative relation;
- preserve its score;
- show ambiguity when scores are close according to the chosen confidence profile;
- do not arbitrarily collapse relative major/minor into one label.

### 15.10 Fifth-related errors

Retain enough candidate information to evaluate fifth-related confusion separately from exact-key errors as required by the main plan.

### 15.11 `unknown` versus `no_stable_key`

Use distinct states:

- `unknown`: insufficient/invalid evidence or unsupported interpretation.
- `no_stable_key`: sufficient tonal evidence exists but no stable single tonal center/mode is asserted for the interval.

Do not replace either with C major as a default.

### 15.12 Enharmonic spelling suggestion

The analyzer outputs tonic pitch class/mode evidence.

A separate spelling resolver suggests a conventional spelling based on:

- mode;
- neighboring/local key context;
- project accidental preference;
- user overrides.

A spelling suggestion is not additional model evidence.

### 15.13 Automatic key result publication

Publish:

- tuning dependency;
- feature artifact identity;
- algorithm/profile;
- global result;
- local regions;
- window-level alternative artifact/reference where useful;
- warnings;
- validation status.

### 15.14 Key-result comparison

The UI/result selector can retain Essentia and profile-correlation results side by side.

Milestone 4 does not require a complex overlay comparison dashboard, but must preserve both and expose provenance.

### 15.15 Key branch creation

On first semantic key edit:

1. Create editable branch from selected key result.
2. Preserve automatic tonic/mode/spelling/confidence in provenance.
3. Apply edit transactionally.
4. Keep automatic result unchanged.

**Acceptance:** the application produces independently versioned global/local key analyses with tuning provenance, retained alternatives, explicit unstable/unknown states, and editable source-time regions.

---

## 16. Work package M4.14 — Define chord/key interaction and spelling behavior

### 16.1 No circular default dependency

Default chord analysis does not depend on key analysis.

Default key analysis does not depend on chord analysis.

They can run independently or in parallel.

### 16.2 Key-aware chord display

When enabled, the display layer may use the active key branch/result to choose enharmonic spelling for auto-spelled structured chords.

It does not change:

- root pitch class;
- slash-bass pitch class;
- detector raw label;
- automatic result hash;
- edited custom text.

### 16.3 Local key resolution at chord time

For a chord region:

1. Resolve the key region covering the chord midpoint or another documented deterministic policy.
2. If a chord spans a key boundary, retain semantic chord unchanged.
3. Optionally show both contexts in the inspector.
4. Do not split a chord automatically at a key boundary.

### 16.4 User spelling override

A structured chord may store an explicit root/bass spelling override after user action.

Once explicit:

- key edits do not respell that component automatically;
- semantic pitch class remains unchanged;
- user may clear the override to return to automatic spelling.

### 16.5 Chord rename versus respell

Distinguish commands:

- `Set chord label` changes chord semantics/text.
- `Set chord spelling override` changes display spelling for the same pitch class where applicable.

Do not infer a semantic chord change when the user only changes `F#` to `Gb` with otherwise identical structure.

### 16.6 Key editing effect on chords

Changing key tonic/mode/spelling:

- may refresh derived auto-spelling;
- may change review context;
- does not stale raw chord inference;
- does not move chord boundaries;
- does not alter custom/manual chord labels unless a separate user command is issued.

### 16.7 Chord editing effect on key

Changing chord labels/boundaries does not alter the default key result.

A future chord-informed key algorithm must declare its chord dependency explicitly as a new result type/profile.

### 16.8 Musical readout integration

Once both results exist, compact readout may show:

`01:32.481 | Bar 42 Beat 3.27 | Key: G | Gmaj7`

or the project's established compact format.

Resolve values at latency-compensated source position.

If key/chord unavailable, show the established dash/unknown state.

### 16.9 Inspector context

Selecting a chord shows:

- source interval;
- musical/bar interval where mapped;
- semantic detailed chord;
- displayed projection;
- raw detector label;
- model/input/result provenance;
- alternatives;
- inversion evidence;
- active key context;
- key-aware spelling source;
- review state.

**Acceptance:** key context improves display/review without creating hidden circular dependencies or silently mutating chord semantics.


---

## 17. Work package M4.15 — Implement manual chord-region editing

### 17.1 Editing invariant

Within one active editable chord branch, regions are source-time intervals with deterministic ordering.

Default branch invariant:

- no overlapping active chord regions;
- shared boundaries are allowed;
- gaps are allowed only when explicitly represented by absence/unknown policy rather than accidental drag arithmetic;
- start < end for every region;
- all boundaries stay within source duration.

### 17.2 Select chord region

Selection stores:

- selected region ID;
- source range;
- focused chord lane;
- related bar/key/waveform context;
- selection origin.

Related objects are highlighted but do not automatically become edit targets.

### 17.3 Rename/set chord label

Workflow:

1. Open inline editor or inspector field.
2. Parse input.
3. Show structured normalized preview when possible.
4. Permit preservation as custom text when parsing is unsupported.
5. Validate no-chord/unknown through dedicated controls.
6. Commit one command.
7. Preserve original automatic label/confidence in provenance.

### 17.4 Set slash chord/inversion

User may:

- type a slash chord;
- choose an inversion candidate from evidence;
- set slash bass independently in structured editor;
- clear slash bass.

All are one semantic chord-label command per completed action.

### 17.5 Move start boundary

When dragging a region start:

1. Resolve pointer to source frame.
2. Apply optional snapping only to the current gesture.
3. Clamp to valid project range.
4. Enforce positive duration.
5. Respect neighbor policy.
6. Preview locally.
7. Commit one command on pointer release.

### 17.6 Move end boundary

Use symmetrical rules.

Do not store intermediate drag positions in command history.

### 17.7 Shared-boundary drag

When two adjacent regions share a boundary, provide a dedicated/shared gesture:

- move left region end and right region start together;
- preserve adjacency;
- enforce minimum positive duration on both sides;
- commit as one atomic command;
- undo restores both boundaries together.

Do not create an accidental gap/overlap from independent asynchronous updates.

### 17.8 Boundary edit with an intentional gap

If the product permits a gap, require an explicit operation or modifier/state that creates it.

The resulting unlabeled interval must have clear semantics in the branch:

- either represented as `unknown`/`no_chord` region as chosen;
- or represented by an explicit gap allowed by schema and shown distinctly.

Prefer explicit regions for analysis/export clarity.

### 17.9 Split region

Split at:

- playhead;
- click position;
- selection boundary;
- entered source/musical position resolved to source frame.

Rules:

1. Split point must lie strictly inside region.
2. Optional snapping affects the requested split.
3. Both children initially inherit semantic label/spelling/review state according to explicit policy.
4. Preserve parent provenance on both children.
5. Assign new region IDs.
6. Commit as one command.

### 17.10 Merge adjacent regions

Allow merge when selected regions are adjacent or when the command explicitly handles an intervening compatible tiny gap.

Default behavior from the main plan:

- keep the leftmost chord label.

Also:

- extend interval to cover selected regions;
- preserve a merge provenance summary;
- assign one resulting region ID or deterministically retain one according to command policy;
- reset/recompute review state conservatively if labels differed;
- make action immediately undoable.

### 17.11 Insert missing chord

User chooses an interval by:

- waveform selection;
- click plus entered end;
- gap selection;
- current bar/beat range resolved through the grid.

Insertion:

- validates against neighboring regions;
- offers boundary snapping;
- asks for chord/no-chord/unknown label;
- creates manual provenance;
- commits one command.

### 17.12 Delete region

Deletion behavior must be explicit.

Options may include:

- replace with `unknown`;
- replace with `no_chord`;
- merge surrounding region according to a deliberate command;
- leave an explicit gap only if branch schema supports it.

Do not silently extend a neighbor without telling the user.

### 17.13 Choose automatic alternative

For a region with retained alternatives:

1. Show candidate label and score kind.
2. Selecting one creates a normal manual chord-label edit.
3. Preserve which automatic alternative was chosen.
4. Do not reinterpret its score as human confidence.

### 17.14 Mark reviewed/corrected

Support:

- mark reviewed/accepted;
- mark corrected automatically when semantic edit occurs;
- clear/reset review state where appropriate.

Review changes are undoable project commands.

### 17.15 Batch operations

Support carefully bounded batch operations such as:

- mark selected regions reviewed;
- apply spelling preference to selected structured chords;
- set selected regions unknown/no-chord with confirmation;
- merge a contiguous selection.

Batch operation commits one transaction/command group.

### 17.16 Snapping behavior

Chord boundaries can use existing modes:

- Off;
- Beat;
- Half-beat;
- Quarter-beat;
- Bar;
- Nearest event boundary.

Add chord-region boundaries to the event-boundary snap provider for future/other edits.

Changing snap mode does not move existing chord boundaries.

### 17.17 Musical-position entry

If a user enters a bar/beat/musical position for a chord boundary:

- resolve through the currently selected rhythm map;
- store resulting integer source frame;
- record the mapping context in command metadata if useful for diagnostics;
- do not convert the chord into a musical-anchored object.

### 17.18 Audition selected chord range

Provide a command to play/audition the selected source interval using the existing transport.

It does not become part of edit history.

### 17.19 Edit conflict behavior

Every chord edit carries:

- command ID;
- idempotency key;
- base project revision;
- target branch ID/revision;
- before/after values.

Stale edit:

- returns `409`;
- does not merge silently;
- frontend preserves pending user input where practical for retry after refresh.

### 17.20 Undo/redo

For every chord operation:

- drag = one command;
- split/merge = one command;
- batch action = one transaction;
- undo restores exact source boundaries/labels/review state;
- redo reapplies it;
- a new edit clears active redo branch according to established rules.

**Acceptance:** the user can fully repair chord labels and boundaries without modifying automatic results, with deterministic interval invariants, snapping only on explicit edits, and complete undo/redo/restart persistence.

---

## 18. Work package M4.16 — Implement key-region and tuning editing

### 18.1 Editable key branch

Key edits target the selected `KeyBranch`.

If the user edits an Auto key result for the first time, create the branch transactionally with the edit.

### 18.2 Edit global key interpretation

Allow user to:

- change global tonic;
- change mode;
- change preferred spelling;
- set unknown;
- set no-stable-key;
- choose an automatic alternative;
- mark reviewed.

A global edit does not automatically overwrite local regions unless the user selects an explicit batch operation.

### 18.3 Edit local key region tonic/mode

1. Select region.
2. Choose tonic pitch class/spelling.
3. Choose mode from supported editor list.
4. Preserve unsupported/manual mode text only if the schema explicitly supports custom mode representation; otherwise validate against declared mode vocabulary.
5. Commit one command.
6. Preserve automatic evidence/provenance.

### 18.4 Edit key-region boundaries

Use source-frame boundaries.

Boundary drag:

- supports existing snapping;
- can move a shared boundary atomically;
- prevents overlap;
- preserves positive duration;
- commits one command.

### 18.5 Split key region

Split at playhead/selection/entered source position.

Children inherit current tonic/mode initially.

Commit one command.

### 18.6 Merge key regions

Merge contiguous selected regions.

Default:

- retain left region's key label/spelling;
- warn/confirm when labels differ if UX requires;
- preserve alternatives/provenance summary;
- remain undoable.

### 18.7 Insert/delete key region

Insertion/deletion follows explicit interval semantics similar to chord editing.

Do not silently extend a neighboring key across a deleted region without a deliberate merge/extend behavior.

### 18.8 Set spelling/key-signature preference

Allow edits that change only display notation while keeping tonic pitch class/mode.

Store separately from tonal evidence.

### 18.9 Unknown and no-stable-key edits

Provide explicit actions for:

- Unknown.
- No stable key.

Do not require the user to fake a tonic/mode to cover an atonal/ambiguous passage.

### 18.10 Tuning editor

Expose:

- automatic estimated cents offset;
- automatic fitted reference frequency;
- active reference A frequency;
- active cents offset;
- confidence/insufficient-evidence state;
- reset to automatic;
- manual numeric edit;
- reviewed/corrected state.

### 18.11 Tuning validation

1. Validate finite numeric input.
2. Use documented practical bounds for UI, but keep schema/error messages explicit rather than silently clipping.
3. Maintain exact sign convention.
4. Keep reference frequency positive.
5. Do not apply audio pitch shifting.
6. Commit semantic tuning changes immediately.

### 18.12 Dependency warning after tuning edit

After manual tuning changes:

- mark dependent tonal/key results stale;
- show which results remain usable but based on older tuning;
- offer recompute;
- do not erase key branches;
- do not rerun automatically unless a future explicit workflow requests it.

### 18.13 Key-spelling effect on chord display

A key spelling edit can refresh auto-spelled chords as a derived presentation change.

It is not recorded as hundreds of chord edit commands.

### 18.14 Review navigation

Provide next/previous uncertain key region using:

- confidence/relation margin;
- unstable state;
- unreviewed state;
- stale tuning context as a separate warning category.

### 18.15 Conflict/undo semantics

Reuse base-revision/idempotency rules.

Each drag/text selection change is one command.

**Acceptance:** tonic, mode, spelling, region boundaries, unknown/no-stable-key states, and tuning context are fully editable and persistent without transposing audio or destroying automatic evidence.

---

## 19. Work package M4.17 — Orchestrate Analyze Harmony and dependency-aware runs

### 19.1 Module identifiers

Add stable module IDs for at least:

- BTC raw chord inference.
- ChordMini raw chord inference.
- Chordino native chord analysis.
- Chord decode/smoothing.
- Rhythm-aware chord-boundary refinement.
- Inversion evidence extraction.
- Tuning estimation.
- Tonal-feature extraction.
- Essentia global/local key analysis.
- Project-owned profile-correlation key analysis.
- Harmony pipeline orchestration (`Analyze Harmony`).

### 19.2 Default Analyze Harmony pipeline

Initial default flow:

```text
original reference mix
    ├─────────────→ tuning estimate
    │                  ↓
    │             tonal features
    │                  ├────────→ project-owned key estimator
    │                  └────────→ Essentia key estimator (when available/selected)
    │
    └─────────────→ selected chord model raw/native output
                       ↓
                  chord decoder
                       ↓
                  validated chord result
```

Chord and key branches can execute partly in parallel after shared input preparation.

### 19.3 Default model behavior

`Analyze Harmony` initially uses the configured default chord adapter/preset, starting with BTC baseline under the main plan.

It does not automatically run every challenger unless the user selects a comparison/evaluation preset.

### 19.4 Missing-model behavior

If the selected neural chord model is missing:

- show missing installation;
- do not download automatically;
- key/tuning analysis may still run if its required adapters are available and the user chooses to continue;
- Chordino may be offered as an explicit available alternative, not silently substituted.

### 19.5 Optional result branches

Advanced/user actions can schedule separately:

- ChordMini comparison.
- Chordino comparison.
- Harmonic-remix chord analysis.
- Harmonic-remix key analysis.
- Rhythm-aware boundary refinement.
- Inversion evidence.

Each produces separately identified artifacts/results.

### 19.6 Progressive publication

Publish usable results as they finish:

- tuning estimate;
- tonal features;
- global key;
- local key regions;
- chord raw prediction status;
- decoded chord result;
- inversion evidence;
- optional refined result.

One failed module does not roll back successful independent modules.

### 19.7 Run graph dependencies

The scheduler declares exact dependencies.

Examples:

- chord decode depends on raw prediction artifact;
- rhythm refinement depends on decoded chord result + selected rhythm identity;
- harmonic remix depends on selected separation result;
- tonal features depend on input + tuning context;
- key result depends on tonal features/tuning profile;
- key-aware chord spelling is derived view state, not an analysis run.

### 19.8 Resource scheduling

Use existing scheduler policy:

- persisted queue;
- cache check before scheduling;
- one heavy job per GPU initially;
- CPU concurrency bounded;
- playback-responsive priority;
- atomic artifacts;
- bounded retries.

### 19.9 Cancellation scope

Cancelling Analyze Harmony:

- requests cancellation of pending/running child jobs owned by that orchestration where safe;
- does not delete already completed published results;
- does not cancel shared cached/input jobs required by another active request;
- reports which stages completed.

### 19.10 Retry behavior

A failed child stage can be retried independently if prerequisites remain valid.

Do not rerun BTC merely because key smoothing failed.

### 19.11 Stale dependency handling

Before starting a dependent run, validate referenced IDs/revisions still exist.

If a selected rhythm/separation/tuning dependency changed after request creation:

- either run against the immutable explicitly requested identity;
- or reject an invalid missing dependency;
- never silently switch to a newer active version.

### 19.12 Analyze All integration

Extend the main plan's `Analyze All` graph so, after prerequisites:

- harmony analysis can run on original mix independently of bass transcription;
- bass transcription remains Milestone 5 and depends on bass separation;
- rhythm and harmony can run concurrently when hardware/resource policy permits;
- successful harmony results survive failures in later bass transcription.

**Acceptance:** harmony modules participate in the durable job graph with explicit dependencies, partial success, cache reuse, cancellation, and no hidden model/input/version substitution.

---

## 20. Work package M4.18 — Add chord/key lanes, overlays, inspectors, and result selectors

### 20.1 Editor layout additions

Extend the existing editor with:

- dedicated key lane;
- dedicated editable chord lane;
- optional chord labels over/within waveform region overlays;
- tuning indicator/control in harmony inspector or project tonal panel;
- harmony result selector;
- chord complexity selector;
- harmony confidence/review controls.

All share the established horizontal viewport.

### 20.2 Vertical ordering

Default logical order above waveforms may be:

1. seconds/musical ruler;
2. tempo/meter/rhythm lanes;
3. key lane;
4. chord lane;
5. source/stem waveform tracks;
6. later bass-note lanes.

Keep lane ordering configurable where existing UI supports it.

### 20.3 Chord lane rendering

For visible source range:

- query/index only intersecting regions;
- draw region background/label/boundaries;
- show no-chord/unknown distinctly;
- show reviewed/corrected state without relying on color alone;
- show selected region handles;
- show low-confidence/ambiguous treatment;
- show stale-result banner at lane/result level rather than corrupting region labels.

### 20.4 Zoom-dependent chord detail

At far zoom:

- prioritize boundaries and readable labels;
- suppress labels that cannot fit rather than overlapping unreadably;
- offer hover/inspector access.

At medium zoom:

- show projected chord labels;
- show selected boundary handles.

At close zoom:

- permit precise frame-level boundary editing;
- show source/musical positions in inspector;
- display nearby beat/subdivision snap targets when enabled.

### 20.5 Waveform chord overlay

Optional overlay can shade/show chord region labels across waveform tracks.

Rules:

- use the same source-frame transform;
- overlay visibility is a view setting;
- overlay does not own edits; the chord branch/lane does;
- changing overlay does not redraw waveform sample data unnecessarily;
- ensure sufficient contrast/accessibility without obscuring waveform detail.

### 20.6 Key lane rendering

Show:

- global key summary separately;
- local key region blocks;
- tonic/mode/spelling;
- uncertain/no-stable-key/unknown states;
- selected boundary handles;
- review state.

### 20.7 Tuning display

Show compact state such as:

- `A4=440 Hz, +7 cents`;
- Automatic/Edited;
- confidence/insufficient evidence.

Do not imply audio is being retuned.

### 20.8 Result selector

Chord selector displays:

- BTC/ChordMini/Chordino;
- model/checkpoint name where relevant;
- original/harmonic input;
- decoder/refinement profile;
- Auto/Edited branch;
- stale marker;
- creation timestamp.

Key selector displays:

- algorithm;
- original/harmonic input;
- tuning context;
- Auto/Edited branch;
- stale marker.

### 20.9 Complexity control

Provide Simple/Standard/Detailed selector.

It updates visible labels immediately without analysis rerun.

Persist as project view/editor setting and make undo behavior consistent with other persistent UI settings according to the project's established history policy.

### 20.10 Alternative-prediction UI

Inspector can show top alternatives.

Requirements:

- label score kind;
- calibration status;
- avoid false percentage wording;
- allow selecting an alternative as an edit;
- avoid rendering huge vocabularies in the main lane.

### 20.11 Chord inspector

Include:

- detailed canonical label;
- projected display label;
- source start/end/duration;
- musical/bar context when mapped;
- raw detector token;
- model/input/result provenance;
- confidence/alternatives;
- inversion evidence;
- key/spelling context;
- review state;
- automatic parent label for an edited region.

### 20.12 Key inspector

Include:

- tonic/mode;
- preferred spelling/key-signature preference;
- source interval;
- global/local status;
- alternatives and relation tags;
- confidence semantics;
- tuning context;
- algorithm/input provenance;
- review state;
- automatic parent state for edited region.

### 20.13 Hit testing

Maintain region interval indices for visible chord/key lanes.

Hit-test priority should distinguish:

- boundary handle;
- region body;
- label/alternative control;
- empty lane space.

Do not scan every project region on every pointer move for long recordings.

### 20.14 Canvas/DOM separation

Use Canvas for dense timeline/region visualization where suitable and DOM for accessible controls/editors/inspectors.

A hover change must not cause complete waveform repaint.

### 20.15 Accessibility

- labels readable by screen readers through synchronized semantic elements/inspector;
- keyboard focus visible;
- selected/uncertain/review states not conveyed by color alone;
- boundary handles accessible through keyboard/numeric editing alternative;
- tooltips not the only source of score semantics.

**Acceptance:** chord/key/tuning results are readable and editable on the shared timeline at long-project and sample-level zoom without breaking waveform performance or accessibility.

---

## 21. Work package M4.19 — Extend linked selection, snapping, navigation, readout, and confidence review

### 21.1 Linked selection model

Extend related-object resolution to include:

- chord regions;
- key regions;
- rhythm bars/beats;
- waveform time ranges;
- markers/loops;
- later bass notes.

### 21.2 Selecting a chord

Highlights:

- chord source interval;
- overlapping key region(s);
- intersecting bar/beat context;
- waveform time range;
- later bass notes once Milestone 5 exists.

Only the chord remains the direct edit target unless the user explicitly multi-selects other objects.

### 21.3 Selecting a key region

Highlights:

- key source interval;
- intersecting chords;
- bar/beat context;
- waveform range.

### 21.4 Selecting waveform range

Show related chord/key regions that intersect the range.

Do not automatically trim/select them for editing.

### 21.5 Selecting a bar

Highlight intersecting chord/key regions using source boundaries derived from active rhythm map.

### 21.6 Event-boundary snapping extension

Add to nearest-event boundary provider:

- chord starts/ends;
- key-region starts/ends;
- existing markers/loops/rhythm boundaries.

Avoid duplicate candidate inflation when boundaries coincide.

### 21.7 Chord boundary snap modes

Use existing visual-radius semantics.

- Beat: active primary beat targets.
- Half/Quarter-beat: derived subdivisions.
- Bar: valid metered region boundaries.
- Event: nearby event boundaries including other chord/key boundaries.

### 21.8 Key boundary snapping

Use the same resolver.

Do not automatically force key changes to bars; user may choose Bar snapping.

### 21.9 Musical readout

Extend compact readout to include at least:

- source time;
- bar/beat when mapped;
- active key when available;
- active chord when available.

Until bass transcription exists, note field remains unavailable if the chosen compact format includes one.

### 21.10 Readout value resolution

At audible source position:

1. Resolve active rhythm mapping.
2. Resolve active key result/branch interval.
3. Resolve active chord result/branch interval.
4. Apply selected chord complexity projection/spelling.
5. Return unknown/dash for gaps/unavailable state.

### 21.11 Next/previous chord navigation

Provide commands for:

- next chord boundary;
- previous chord boundary;
- next uncertain/unreviewed chord;
- previous uncertain/unreviewed chord.

Navigation seeks/selects according to explicit UX convention and remains separate from editing.

### 21.12 Next/previous key navigation

Provide analogous key-region review navigation.

### 21.13 Confidence review prioritization

Review queue can consider:

- low selected-label margin;
- unknown region;
- short suspicious region;
- boundary ambiguity;
- inversion ambiguity;
- model disagreement where comparison results exist;
- unreviewed state.

Do not merge unrelated score scales into one universal numeric confidence.

### 21.14 Model disagreement review

When comparable results from multiple chord models exist:

- derive disagreement intervals as a review aid;
- keep source results unchanged;
- avoid declaring one model correct automatically;
- show exact model names/projections used for comparison.

### 21.15 Review threshold settings

Allow per-module review threshold/profile.

Persist user setting.

Changing review threshold changes review highlighting, not result semantics.

### 21.16 Keyboard behavior

Add documented/remappable shortcuts for harmony review only if they do not conflict with established transport/edit bindings.

At minimum ensure keyboard alternatives for:

- select previous/next region;
- nudge boundary using numeric/arrow controls when focused;
- open label editor;
- mark reviewed;
- cancel edit.

Disable shortcuts while typing into text fields as already required.

**Acceptance:** harmony objects participate in the shared timeline selection/snapping/readout/review systems without coupling unrelated edits or introducing a second coordinate model.

---

## 22. Work package M4.20 — Add API, worker, generated-contract, and frontend domain services

### 22.1 Reuse project run API

Continue using:

`POST /api/v1/projects/{id}/runs`

Harmony request can declare:

- module/pipeline ID;
- input role/result ID;
- chord adapter/model preset;
- device preference;
- decoder profile;
- optional rhythm refinement and exact rhythm dependency;
- key algorithm/profile;
- tuning policy/context;
- optional harmonic remix source separation result;
- force-rerun flag.

### 22.2 Chord result APIs

Add interfaces similar to:

| Interface | Purpose |
|---|---|
| `GET /api/v1/projects/{id}/chord-results` | List immutable automatic chord results |
| `GET /api/v1/projects/{id}/chord-results/{result_id}` | Chord result summary/provenance/regions |
| `GET /api/v1/projects/{id}/chord-branches` | List editable chord branches |
| `GET /api/v1/projects/{id}/chord-branches/{branch_id}` | Editable chord branch data |
| `GET /api/v1/chord-predictions/{artifact_id}` | Bounded raw score access for diagnostics/review |

Exact route names must remain consistent with existing API conventions; generated contracts become authoritative.

### 22.3 Bounded raw score endpoint

Parameters include:

- start model frame;
- frame count;
- optional label range/top-k derived view only if explicitly supported.

Rules:

1. Authenticate.
2. Verify artifact access/project relationship.
3. Bound response byte size.
4. Return versioned binary data.
5. Return vocabulary/alignment metadata through companion JSON/headers.
6. Reject invalid ranges.
7. Never return unrelated local files.
8. Do not load full long-track matrix into API memory for a small range.

### 22.4 Key/tuning result APIs

Add interfaces for:

- list/get key results;
- list/get key branches;
- get current automatic/manual tuning state;
- bounded tonal-feature range access for diagnostics if needed.

Regular UI should not fetch full tonal-feature arrays by default.

### 22.5 Project command types — chord

Add at least:

- Select active chord result.
- Select active chord branch/Auto versus Edited.
- Set chord complexity projection.
- Set chord overlay/lane view state as project policy requires.
- Set chord label.
- Set chord spelling override.
- Clear chord spelling override.
- Move chord start/end/shared boundary.
- Split chord region.
- Merge chord regions.
- Insert chord region.
- Delete/replace chord region.
- Set no-chord.
- Set unknown chord.
- Choose chord alternative.
- Mark chord reviewed.

### 22.6 Project command types — key/tuning

Add at least:

- Select active key result.
- Select active key branch/Auto versus Edited.
- Set global key interpretation.
- Set key region label.
- Move key region boundary.
- Split/merge/insert/delete key region.
- Set key spelling/signature preference.
- Set unknown/no-stable-key.
- Choose key alternative.
- Mark key region reviewed.
- Set active tuning reference/offset.
- Reset tuning to automatic.
- Mark tuning reviewed.
- Set key-aware chord-spelling preference.

### 22.7 Command validation

Backend validates:

- branch ownership/active identity;
- base revision;
- source-frame bounds;
- interval ordering/non-overlap;
- label schema;
- spelling fields;
- safe integer positions;
- referenced alternative/evidence IDs;
- stale/missing target behavior.

### 22.8 Worker protocol

Reuse existing `run/progress/completed/failed/cancel/cancelled` messages where semantics suffice.

Harmony modules declare typed request/result schemas in capabilities.

Increment protocol version only if actual envelope/message semantics change.

### 22.9 Frontend domain services

Add non-React services/modules such as:

- `ChordLabelParser`.
- `ChordLabelRenderer`.
- `ChordProjectionService`.
- `ChordSpellingResolver`.
- `ChordIntervalIndex`.
- `KeyIntervalIndex`.
- `HarmonySelectionResolver`.
- `HarmonyReviewNavigator`.
- `HarmonyResultStore`.
- `TuningContextStore`.
- `HarmonySnapProvider` integration.

React components consume these services rather than reimplementing semantics.

### 22.10 Shared Python/TypeScript semantic fixtures

Create generated/shared fixture files for:

- canonical chord labels;
- parsing/rendering;
- detector vocabulary mappings;
- complexity projections;
- key spelling examples;
- source interval operations.

Run equivalent tests in backend/frontend to detect drift.

### 22.11 Generated contracts

After schema/API changes:

1. Regenerate OpenAPI.
2. Regenerate project JSON Schema.
3. Regenerate worker schemas.
4. Regenerate TypeScript API types.
5. Regenerate any vocabulary descriptor schema.
6. Run deterministic contract-drift checks.
7. Never hand-edit generated types.

### 22.12 WebSocket/events

If the general event infrastructure is present by this stage, publish:

- harmony job progress;
- result availability;
- project revision updates;
- stale-dependency state changes.

Reconnection still resolves durable status from backend rather than assuming continuous messages.

**Acceptance:** worker, backend, generated client, frontend editor, and project commands share one versioned harmony contract without hand-built semantic divergence.

---

## 23. Work package M4.21 — Cache identity, dependency staleness, autosave, and portable projects

### 23.1 BTC/ChordMini raw artifact cache key

Include:

- input asset/transformation hash;
- input role;
- model manifest and every weight/config hash;
- adapter/engine version;
- preprocessing profile;
- long-track chunk/context profile;
- precision/numerical profile;
- analysis interval;
- result-changing parameters.

Device identity is recorded in provenance and enters cache identity only when required by the project's determinism policy/evidence.

### 23.2 Chord decoder cache key

Include:

- raw prediction artifact hash;
- vocabulary mapping version;
- decoder implementation/profile;
- smoothing parameters;
- no-chord/unknown policy parameters;
- region aggregation profile.

### 23.3 Chordino cache key

Include:

- input hash/profile;
- Chordino plugin identity/version;
- host version where result-relevant;
- plugin parameters;
- adapter parser/mapping version.

### 23.4 Harmonic remix cache key

Include:

- separation result ID;
- every included stem asset hash;
- stem-role list;
- summing/precision profile;
- output rate/channel profile.

### 23.5 Rhythm-refinement cache key

Include:

- source chord result identity;
- exact rhythm result/branch identity and branch revision/content hash;
- refinement profile;
- candidate-target policy;
- displacement/evidence parameters.

### 23.6 Tuning cache key

Include:

- input asset/profile hash;
- tuning estimator version;
- spectral/analysis parameters;
- analysis interval;
- reference convention where result-relevant.

### 23.7 Tonal feature cache key

Include:

- input hash/profile;
- tuning-context identity;
- feature extractor/profile version;
- window/hop parameters;
- normalization profile.

### 23.8 Key result cache key

Include:

- tonal feature artifact hash or exact input+tuning transform identity;
- key algorithm/adapter version;
- profile coefficients/configuration;
- global/local window/hop settings;
- smoothing/transition profile;
- supported mode/profile set.

### 23.9 Staleness rules

Apply dependency-specific staleness rather than broad project-wide invalidation.

Examples:

- New rhythm branch edit stales only rhythm-refined chord results that depend on it.
- Unrefined source-time chord results remain valid.
- New separation selection stales harmonic-remix harmony results that depend on that separation result, not original-mix results.
- Manual tuning change stales tonal/key results tied to old tuning context.
- Key edit does not stale raw chord results.
- Chord edit does not stale default key results.
- Chord/key view projection/spelling changes do not stale analysis.

### 23.10 Manual branch persistence

Manual harmony edits are project state, not evictable analysis cache.

Protect:

- chord branches;
- key branches;
- manual tuning state;
- review state;
- active result/branch selection;
- command history;
- harmony view/complexity/spelling settings according to project policy.

### 23.11 Autosave

Commit semantic harmony commands immediately.

Debounce only view-state changes such as:

- lane height;
- overlay visibility;
- inspector section;
- review filter;
- result-selector panel state.

### 23.12 Interrupted analysis recovery

After restart:

- completed raw prediction artifacts are reusable;
- completed decoded results are reusable;
- completed tonal features/key results are reusable;
- interrupted stage becomes interrupted/retryable;
- edited branches remain intact;
- no partial artifact becomes active.

### 23.13 Portable project contents

Extend portable save with:

- chord run/result metadata;
- active and retained chord result references;
- chord editable branches;
- chord raw prediction/native artifacts according to analysis-artifact policy;
- chord vocabulary/provenance metadata needed to interpret stored results;
- inversion evidence artifacts/metadata where referenced;
- tuning estimate/manual state;
- tonal feature artifacts according to optional/essential classification;
- key run/result metadata;
- key editable branches;
- harmony active-selection/view/review settings;
- model/adapter provenance and license identifiers;
- command history entries.

Do not include model weights or runtime environments.

### 23.14 Essential harmony assets for reopen

Essential to reproduce the user's corrected visible harmony state:

- active chord branch/result region data;
- active key branch/result region data;
- active/manual tuning state;
- canonical label/spelling data;
- command/project revision state;
- active selection settings.

### 23.15 Optional/rebuildable artifacts

May be treated as optional for ordinary reopen/practice if project policy permits:

- dense neural score matrices;
- nonactive automatic alternatives;
- tonal feature arrays;
- low-frequency inversion feature arrays;
- comparison-model raw outputs not required by an active branch.

If missing/corrupt:

- preserve corrected visible chord/key regions;
- preserve playback/readout;
- report reduced re-decoding/review capability;
- never rerun a model automatically.

### 23.16 Vocabulary/provenance durability

A saved chord result must remain interpretable even if the current application no longer has the original adapter installed.

Portable metadata must contain enough canonicalized region semantics and detector provenance to display the result without loading the detector vocabulary code.

### 23.17 Reopen without models/network

On reopen:

1. Restore harmony branches/results.
2. Rebuild interval indices.
3. Restore active result/branch.
4. Restore chord projection/spelling settings.
5. Restore key/tuning state.
6. Restore review state.
7. Remain paused.
8. Permit immediate chord/key lanes and readout.
9. Do not inspect/install models unless the user requests new analysis.

### 23.18 Cache eviction

Evict only unreferenced rebuildable artifacts under cache policy.

Protect artifacts referenced by:

- active projects;
- retained result versions required for branch provenance;
- portable save/export jobs;
- active analysis/redecode jobs.

### 23.19 Save/open integrity tests

Verify hashes/schema for harmony artifacts during portable save/open using the existing archive safety mechanisms.

A corrupt optional score matrix must not prevent opening a project whose canonical chord regions are intact.

A corrupt essential active branch must produce a clear project-integrity error rather than silently replacing it with another result.

**Acceptance:** harmony edits/results survive restart and portable reopen offline, while cache invalidation/staleness affects only results with real dependencies and never silently destroys user corrections.


---

## 24. Work package M4.22 — Build harmony/key/tuning test corpus and automated verification

### 24.1 Deterministic synthetic chord fixtures

Generate local test audio/metadata fixtures for at least:

1. Sustained C major triad.
2. Sustained A minor triad.
3. Major/minor alternation.
4. Dominant seventh example.
5. Major seventh example.
6. Minor seventh example.
7. Diminished example.
8. Augmented example.
9. Suspended example.
10. Chord sequence with silence/no-chord gaps.
11. Chord sequence with deliberately ambiguous transition.
12. Inversion fixture with stable third in the bass.
13. Inversion fixture with stable fifth in the bass.
14. Passing bass note that must not automatically become a slash bass.
15. Pedal bass spanning chord changes.
16. Very short chord between longer neighbors.
17. Off-beat chord changes.
18. Beat-aligned chord changes.
19. Chord changes across a tempo ramp.
20. Chord changes across a meter change.
21. Detuned chord progression.
22. Percussion-only audio.
23. Pure silence.
24. Single sustained tone.
25. Dense/chromatic harmony that should permit unknown/ambiguity.
26. Long progression generated during tests for memory/performance.

Synthetic fixtures do not need to sound production-quality; they need deterministic ground truth and coverage of timing/semantic edge cases.

### 24.2 Canonical chord-label fixtures

Create JSON fixtures containing:

- raw detector label;
- detector vocabulary ID;
- expected canonical label;
- expected canonical rendering;
- expected Simple projection;
- expected Standard projection;
- expected Detailed rendering;
- expected key-aware spelling under selected keys;
- expected parser round trip;
- expected no-chord/unknown/custom behavior.

Use the same fixture data in Python and TypeScript tests.

### 24.3 Raw prediction artifact tests

Verify:

- correct tensor dimensions;
- vocabulary hash/axis agreement;
- finite values;
- dtype/endianness where relevant;
- model-frame count;
- source-time alignment;
- bounded range reads;
- truncated/corrupt file rejection;
- wrong vocabulary manifest rejection;
- hash mismatch handling;
- missing optional artifact behavior.

### 24.4 Model-frame mapping tests

Test:

1. First frame mapping.
2. Middle frame mapping.
3. Last frame mapping.
4. Resampled input mapping.
5. Padded/context inference mapping.
6. Chunk overlap deduplication.
7. Rounding collision handling.
8. Boundary mapping convention against known impulses/transitions.

### 24.5 Decoder tests

Test:

- argmax/reference decoding where applicable;
- adapter-native decoder parity on a controlled fixture;
- smoothing profile identity;
- no-chord preservation;
- unknown preservation;
- identical-run region merging;
- short-region behavior;
- alternatives aggregation;
- source coverage;
- no overlaps;
- half-open boundaries;
- deterministic re-decoding from same raw artifact.

### 24.6 Adapter vocabulary tests

For BTC, ChordMini, and Chordino:

- every registered possible output label maps;
- no duplicate mapping collisions unless intentionally equivalent;
- no-chord token semantics are explicit;
- slash/inversion support declaration matches actual adapter capability;
- unsupported tokens fail/flag predictably.

### 24.7 Chord branch editing tests

For each command:

- create branch on first edit;
- rename structured label;
- preserve custom label;
- set/clear inversion;
- move start;
- move end;
- move shared boundary;
- split;
- merge;
- insert;
- delete/replace;
- choose alternative;
- set no-chord;
- set unknown;
- mark reviewed;
- batch review;
- undo;
- redo;
- restart/reopen.

Check stale-revision conflict behavior for concurrent tabs.

### 24.8 Interval invariant property tests

Generate random valid chord-region sequences and random edit operations.

Assert after every accepted operation:

- bounds within source;
- start < end;
- ordering;
- no forbidden overlap;
- deterministic shared-boundary behavior;
- serialization round trip.

Rejected operations must not partially mutate state.

### 24.9 Snapping tests

Test chord/key boundary edits under:

- Snap Off;
- Beat;
- Half-beat;
- Quarter-beat;
- Bar;
- Event boundary;
- variable tempo;
- 6/8 grouping;
- irregular meter;
- unmapped regions;
- far and close zoom.

Verify changing snap mode alone never changes stored boundaries.

### 24.10 Rhythm-refinement tests

Using known chord+grid fixtures:

- explicit rhythm dependency required;
- off-beat strong boundary retained;
- near-beat weak/ambiguous boundary can move under profile;
- displacement bound enforced;
- no region inversion/collapse;
- no target in unmapped region;
- refined result stales after referenced rhythm edit;
- source result remains non-stale;
- recompute creates a new result.

### 24.11 Harmonic-remix tests

Verify:

- exact stem roles included/excluded;
- common source frame count;
- sum output alignment;
- bounded memory;
- no current mixer-state dependency;
- stable transformation hash;
- cache reuse;
- invalid mismatched stem result rejected;
- original-mix result remains independent.

### 24.12 Inversion evidence tests

Create fixtures for:

- root position;
- stable third bass;
- stable fifth bass;
- passing bass;
- pedal tone;
- low-frequency noise;
- bass stem absent;
- bass stem present;
- detector-native inversion present;
- conflicting native versus low-band evidence.

Verify passing evidence does not automatically create slash bass under the chosen profile.

### 24.13 Tuning estimator tests

For known detuning fixtures:

- zero offset;
- ± small offsets;
- larger supported offsets;
- near-half-semitone ambiguity;
- silence;
- percussion-only;
- vibrato;
- multiple instruments with same offset;
- conflicting/microtonal evidence.

Verify sign convention and cents error.

### 24.14 Tonal feature tests

Verify:

- correct pitch-class bin ordering;
- tuning-context effect;
- source-time frame mapping;
- finite values;
- silence/energy mask;
- normalization stability;
- bounded range reads;
- corruption detection;
- cache key changes with tuning/profile.

### 24.15 Global key tests

Use synthetic/known-key fixtures for:

- all supported tonic classes;
- major/minor modes at minimum;
- relative major/minor ambiguity;
- dominant/fifth-related distractors;
- silence;
- chromatic/unstable passage;
- detuned input with/without tuning correction.

### 24.16 Local key-region tests

Create sequences containing:

- one stable key;
- relative-key modulation;
- fifth-related modulation;
- abrupt key change;
- chromatic bridge/no-stable-key region;
- short modulation;
- long gradual ambiguous transition.

Verify boundary ordering, smoothing, and retained alternatives.

### 24.17 Key editing tests

Test:

- branch creation;
- tonic change;
- mode change;
- spelling-only change;
- no-stable-key;
- unknown;
- shared-boundary move;
- split;
- merge;
- insert/delete;
- review state;
- undo/redo;
- stale conflict;
- restart/reopen.

### 24.18 Chord/key spelling interaction tests

Verify:

- key-aware F#/Gb choice changes display only;
- semantic pitch class unchanged;
- explicit chord spelling override wins;
- clearing override restores auto spelling;
- custom text unchanged;
- chord spanning key boundary uses deterministic context policy;
- key edit does not create chord commands.

### 24.19 Staleness tests

Create dependency graph fixtures proving:

- rhythm edit stales refined chord result only;
- separation change stales harmonic-remix result only;
- tuning change stales tonal/key result;
- chord edit does not stale key result;
- key edit does not stale raw chord result;
- complexity/spelling view change stales nothing.

### 24.20 Cache tests

Verify:

- identical run reuses raw model artifact/result;
- decoder profile change reuses raw prediction but creates new decode;
- harmonic-remix source change creates distinct key;
- model hash change invalidates inference cache;
- vocabulary mapping version change invalidates decoded canonical result as necessary;
- cancelled/failed jobs do not produce successful cache hits;
- concurrent identical requests coalesce according to scheduler policy.

### 24.21 Portable-project tests

Test save/open with:

1. Active BTC result.
2. Active ChordMini result.
3. Chordino result.
4. Edited chord branch.
5. Custom chord labels.
6. Slash chords.
7. Active key branch.
8. Manual tuning.
9. Raw score artifact present.
10. Raw score artifact deliberately omitted/missing as optional.
11. Tonal feature artifact missing as optional.
12. Models absent.
13. Native adapters absent.
14. Network disabled.
15. Corrupt optional artifact.
16. Corrupt essential branch data.
17. Unsupported future harmony schema.
18. Unsafe archive path fixture using existing archive protection.

### 24.22 Browser end-to-end tests

Chromium and Firefox:

1. Open a prepared project.
2. Run a deterministic test harmony worker or real adapter in appropriate integration suite.
3. Display chord regions.
4. Switch complexity modes.
5. Rename chord.
6. Move boundary with snapping.
7. Split and merge.
8. Enter slash chord.
9. Mark reviewed.
10. Display key regions.
11. Edit key spelling.
12. Edit tuning.
13. Use linked selection/readout.
14. Undo/redo.
15. Save/reopen.
16. Confirm harmony state persists.

Keep at least one real BTC, one real ChordMini, one real Chordino (when available), and one real key-adapter integration test outside the fast mocked browser suite.

### 24.23 Long-project tests

Generate/use a 60-minute project to verify:

- bounded raw score generation/storage;
- interval-index rendering;
- result list scalability;
- review navigation;
- bounded score range requests;
- key/chord lane responsiveness;
- no full-project DOM materialization.

**Acceptance:** deterministic automated tests cover raw artifacts, label semantics, source mapping, editing, staleness, key/tuning behavior, persistence, and browser interaction independently of subjective listening.

---

## 25. Work package M4.23 — Harmony quality evaluation and model/preset acceptance

### 25.1 Evaluation corpus

Use the main plan's evaluation strategy, expanded for harmony:

- deterministic synthetic chord/inversion fixtures;
- detuned fixtures;
- known-key/local-key fixtures;
- legally usable annotated harmony excerpts where available;
- manually annotated excerpts from the five supplied recordings;
- original-mix and harmonic-remix variants where separation exists.

Keep development/tuning excerpts separate from final evaluation excerpts.

### 25.2 Label normalization for evaluation

Before scoring model outputs:

- map reference and prediction into explicit evaluation vocabularies;
- preserve original detailed labels for detailed metrics;
- define projection rules in the evaluation code;
- document handling of enharmonic equivalents;
- document no-chord/unknown treatment;
- avoid giving a model credit for a detail it cannot represent by silently upgrading its labels.

### 25.3 Duration-weighted chord accuracy

Measure at least:

- detailed-vocabulary duration-weighted accuracy where labels are comparable;
- Standard projection accuracy;
- Simple projection accuracy;
- root accuracy;
- no-chord accuracy/behavior.

Report the exact metric implementation/vocabulary.

### 25.4 Boundary metrics

Measure:

- boundary precision;
- boundary recall;
- F-measure under documented time tolerances;
- median/percentile boundary error;
- over-segmentation/under-segmentation indicators;
- short-region failure behavior.

### 25.5 Inversion metrics

Evaluate separately:

- root-position versus inversion detection;
- slash-bass pitch-class accuracy;
- false inversion rate caused by passing bass;
- performance with/without a separated bass stem.

Do not fold inversion performance invisibly into one overall chord score.

### 25.6 BTC versus ChordMini

On the same evaluation corpus/input profile, measure:

- Simple/Standard/Detailed chord metrics;
- boundary metrics;
- inversion capability where applicable;
- no-chord behavior;
- runtime;
- peak VRAM;
- host RAM;
- raw artifact size;
- correction burden.

### 25.7 Chordino comparison

Measure the same comparable metrics while acknowledging vocabulary/output differences.

Do not force a detailed-vocabulary metric that the adapter cannot represent fairly without clearly specifying the projection.

### 25.8 Original mix versus harmonic remix

For each selected chord adapter:

- compare results on the same annotated excerpts;
- record category/song-specific changes;
- record boundary changes;
- record correction burden;
- retain original mix as default unless evaluation supports a policy change.

Do not infer universal benefit from a small subset.

### 25.9 Rhythm-refinement evaluation

Compare source decoder versus rhythm-refined result on:

- boundary F-measure;
- chord duration accuracy;
- harmful moves;
- off-beat true changes;
- correction burden.

Only enable/refine default behavior if evidence supports it; the main plan's no-mandatory-quantization policy remains.

### 25.10 Tuning evaluation

Measure:

- cents absolute error on known detuning fixtures;
- failure/unknown rate;
- bias;
- behavior near ±50-cent ambiguity;
- impact on downstream key accuracy.

### 25.11 Global key evaluation

Measure:

- exact tonic/mode accuracy;
- relative-major/minor errors separately;
- fifth-related errors separately;
- other errors;
- unknown/no-stable-key behavior.

### 25.12 Local key evaluation

Measure:

- duration-weighted local-key accuracy;
- region-boundary accuracy;
- modulation detection;
- false rapid key-change rate;
- no-stable-key region handling.

### 25.13 Essentia versus profile correlation

Compare on identical input/tuning context:

- global key metrics;
- local key metrics where both paths support local use;
- runtime;
- correction burden;
- confidence/strength usefulness.

Keep both named results if evidence shows complementary tradeoffs.

### 25.14 Confidence usefulness

For chord regions:

- bin events by score/margin/confidence type;
- measure actual correctness/error rate;
- measure whether low-score events require more edits.

For key regions:

- compare candidate margin/strength with correctness;
- compare unstable/no-stable-key flags with annotations.

Do not calibrate unless held-out evaluation supports calibration.

### 25.15 Model disagreement as review signal

Measure whether BTC/ChordMini/Chordino disagreement intervals are disproportionately error-prone.

If useful, disagreement can become a review-priority heuristic with `kind=agreement` or another explicit non-probability confidence kind.

### 25.16 Practical correction burden

On annotated excerpts, record:

- chord renames;
- chord boundary moves;
- splits;
- merges;
- insertions/deletions;
- no-chord/unknown corrections;
- inversion corrections;
- key label corrections;
- key boundary corrections;
- tuning corrections;
- time required to reach acceptable transcription.

This product metric is distinct from benchmark accuracy.

### 25.17 Promotion rule

Use the main plan's promotion principles.

Do not change default from BTC to ChordMini or another adapter merely because of one headline metric.

Require:

- license/reproducibility pass;
- target hardware fit;
- full validation corpus completion;
- no severe regression in important target categories;
- improved harmony metrics and/or correction burden with documented tradeoffs.

If evidence conflicts, keep named presets.

**Acceptance:** default and challenger harmony/key algorithms have measured, reproducible behavior with chord vocabulary, boundary, inversion, key-error type, tuning, runtime, and correction burden reported separately.

---

## 26. Work package M4.24 — Performance, playback coexistence, browser, offline, listening, and failure acceptance

### 26.1 Analysis resource measurements

For BTC and ChordMini record:

- elapsed time per track minute;
- real-time factor;
- peak GPU VRAM;
- peak host RAM;
- CPU utilization;
- raw score artifact bytes per track minute;
- prepared input size;
- cache reuse time.

For Chordino/key adapters record corresponding CPU/RAM/time metrics.

### 26.2 Playback coexistence

While prepared playback is running:

1. Start harmony analysis on an available device.
2. Observe audio underruns.
3. Observe transport timing.
4. Observe API latency.
5. Observe UI frame responsiveness.
6. Observe CPU/GPU contention.
7. Reduce worker concurrency/threading/profile if playback becomes unreliable.

### 26.3 Long-track memory target

Memory growth must be bounded by:

- inference window/context;
- staged output buffers;
- memory-mapped/range-access artifacts;
- visible UI interval data.

Do not require loading a 60-minute raw score matrix and every chord region into multiple browser copies.

### 26.4 Chord/key editor responsiveness

On a 60-minute project:

- pan/zoom remain responsive;
- hit testing uses interval indices;
- region labels are virtualized/clipped to viewport;
- review navigation remains practical;
- playhead update does not redraw all harmony layers;
- complexity switch does not rerun analysis.

### 26.5 Browser coverage

Required for Milestone 4:

- Chromium on Linux.
- Firefox on Linux.

Use existing buffering/security paths.

Actual Safari validation remains Milestone 8.

### 26.6 Offline analysis verification

After required models/adapters are installed:

1. Block external network access.
2. Run BTC on a local project.
3. Run ChordMini where installed.
4. Run Chordino where available.
5. Run key/tuning analysis.
6. Edit harmony.
7. Save portable project.
8. Reopen.
9. Confirm no external request.

### 26.7 Offline reopen without analysis runtimes

On a clean/limited installation:

- remove/unavailable BTC environment;
- remove/unavailable ChordMini environment;
- remove/unavailable Chordino/Essentia;
- block network;
- open a harmony-enabled portable project;
- verify chord/key lanes/readout/editing remain available for stored results;
- verify no model installation is triggered.

### 26.8 Existing five recordings practical workflow

For every supplied recording:

1. Open/import through prior milestones.
2. Use existing rhythm result where available.
3. Run default BTC original-mix chord analysis.
4. Inspect whole-song chord lane.
5. Correct a representative region.
6. Test Simple/Standard/Detailed projection.
7. Test at least one inversion entry where musically relevant.
8. Run tuning/key analysis.
9. Correct a representative key/spelling issue if present.
10. If four stems exist, run harmonic-remix comparison on a representative track/segment or whole track according to resource plan.
11. Use linked selection/readout during playback.
12. Save/reopen.
13. Record runtime, memory, correction burden, and model/editor issues.

Do not claim full-song ground-truth accuracy for unannotated tracks.

### 26.9 Listening/visual alignment review

For representative passages:

- compare audible chord changes with displayed boundaries;
- seek precisely around boundaries;
- verify no systematic model-to-source offset;
- verify key regions align to intended source ranges;
- verify variable playback speed does not change source-time harmony alignment;
- verify loop/metronome use does not shift chord readout.

### 26.10 Failure cases

Verify clear recovery/messages for:

- BTC model not installed;
- ChordMini model not installed;
- worker environment missing/broken;
- GPU unavailable;
- GPU OOM;
- worker crash;
- corrupt raw prediction artifact;
- vocabulary mismatch;
- Chordino host/plugin missing;
- Essentia unavailable;
- harmonic remix unavailable because no drum stem exists;
- selected separation dependency missing;
- selected rhythm dependency missing;
- stale rhythm-refined result;
- silence/no chord evidence;
- no stable key;
- tuning insufficient/ambiguous;
- invalid manual chord interval;
- invalid parser input;
- stale project revision;
- full disk during artifact write;
- portable project missing optional raw arrays.

### 26.11 Failure message contract

Every harmony failure states:

- what failed;
- which previous chord/key/tuning results remain usable;
- whether retry is possible;
- whether another adapter can be chosen;
- whether model installation is required;
- whether a dependency selection must be corrected.

### 26.12 No silent fallback

Do not silently:

- swap BTC to ChordMini;
- swap neural model to Chordino;
- swap GPU to CPU;
- swap original mix to harmonic remix;
- swap selected edited rhythm grid to newest automatic grid;
- replace missing key adapter with a different one while retaining the same result label.

Fallback is explicit and provenance-visible.

**Acceptance:** harmony analysis coexists with practice playback, remains bounded on long tracks, works offline after installation, reopens without runtimes, and exposes recoverable failures without hidden substitutions.

---

## 27. Work package M4.25 — Documentation, diagnostics, troubleshooting, and license inventory

### 27.1 User documentation

Document:

- what BTC/ChordMini/Chordino results represent;
- why models can disagree;
- original mix versus harmonic remix;
- Auto versus Edited chord results;
- no-chord versus unknown;
- Simple/Standard/Detailed display modes;
- why changing display complexity does not rerun analysis;
- how to rename/split/merge/insert/delete chords;
- how slash chords/inversion evidence work;
- why passing bass does not automatically become inversion;
- how snapping affects only manual boundary edits;
- what rhythm-refined chord result means;
- what tuning cents offset means;
- automatic versus manual tuning;
- global versus local key;
- no-stable-key versus unknown;
- why key signature spelling is partly notational;
- key-aware chord spelling and explicit overrides;
- confidence/review badges;
- stale-result warnings;
- offline reopen behavior.

### 27.2 Developer documentation

Document:

- each runtime lock/install command;
- model registry/provenance;
- native Chordino host configuration;
- Essentia boundary;
- canonical chord-label schema;
- detector vocabulary descriptor format;
- raw score artifact format;
- model-frame/source mapping;
- decoder/smoothing profiles;
- harmonic-remix transform;
- rhythm-refinement dependency semantics;
- inversion evidence profile;
- tuning estimator convention;
- tonal feature artifact format;
- key algorithms/window/smoothing profiles;
- chord/key spelling resolver;
- cache keys;
- staleness graph;
- portable-project harmony contents.

### 27.3 Diagnostic command additions

Extend diagnostics without expensive model loading by default to report:

- BTC environment availability;
- ChordMini environment availability;
- registered model installation state;
- last model/device qualification results;
- Chordino host/plugin availability/version;
- Essentia adapter availability/version;
- harmony artifact/cache usage;
- active project chord/key result IDs and stale status when using project-specific diagnostics;
- active tuning context;
- missing optional raw artifact warnings.

### 27.4 Explicit qualification command

If the project already has a model-qualification command pattern, add harmony options to deliberately perform expensive load/inference checks.

Do not make ordinary `basseparate doctor` load every neural model.

### 27.5 Troubleshooting guide

Add entries for:

- chord model not installed;
- neural worker environment broken;
- CUDA qualification failure;
- chord labels appear globally shifted in time;
- too many short chord regions;
- no-chord/unknown confusion;
- custom chord label not parsed;
- harmonic remix unavailable;
- chord result stale after rhythm edit;
- Chordino missing;
- key adapter missing;
- no stable key found;
- key switches too often;
- tuning estimate ambiguous;
- wrong enharmonic spelling;
- explicit chord spelling override behavior;
- optional raw predictions missing after cache cleanup;
- portable project opens but cannot re-decode without raw artifact/model.

### 27.6 License inventory updates

Record separately:

- BTC source revision/license;
- BTC checkpoint provenance/terms;
- ChordMini source revision/license;
- ChordMini checkpoint provenance/terms;
- Chordino code/plugin license and native host dependencies;
- Essentia library license;
- Tonal version/license if newly introduced at this milestone;
- librosa/SciPy/other new direct tonal-analysis dependencies;
- required notices;
- bundled versus separately installed status.

### 27.7 Packaging decision records

Create/update ADRs for:

- isolated chord-model runtimes;
- native Chordino integration choice;
- Essentia isolation/bundling choice;
- canonical chord vocabulary;
- source-time harmony regions;
- optional rhythm refinement rather than mandatory quantization;
- key/chord dependency separation;
- raw prediction artifact retention policy.

### 27.8 Implementation report

At Milestone 4 completion, record:

- exact model/runtime versions;
- actual hashes;
- hardware qualification results;
- runtime/memory measurements;
- model comparison metrics;
- chosen default profiles;
- unresolved limitations;
- packaging/license constraints;
- known adapter incompatibilities;
- user-track practical findings.

**Acceptance:** a developer can reproduce each harmony runtime and interpret every stored artifact/result, while a user can understand common chord/key/tuning failures and correction workflows.

---

## 28. Implementation order and acceptance gates

Execute Milestone 4 through explicit gates.

| Gate | Work packages | Required outcome |
|---|---|---|
| A | M4.1–M4.2 | Stable harmony/key domain schemas and canonical label semantics |
| B | M4.3–M4.4 | Reproducible runtimes, registered models/adapters, deterministic input profiles |
| C | M4.5–M4.8 | BTC/ChordMini/Chordino raw/native output and source-time chord decoding |
| D | M4.9–M4.11 | Immutable results, editable branches, optional rhythm refinement, inversion evidence |
| E | M4.12–M4.14 | Tuning, tonal features, global/local key analysis, safe chord/key interaction |
| F | M4.15–M4.19 | Full chord/key/tuning correction UX, lanes, snapping, selection, readout, review |
| G | M4.17, M4.20–M4.21 | Orchestration, API/contracts, cache/staleness, autosave, portable reopen |
| H | M4.22–M4.25 | Automated evidence, model evaluation, performance/offline acceptance, documentation/licenses |

Do not move a gate to passed based only on mocked output when the gate requires a real adapter/model/native integration.

### 28.1 Gate A — Harmony semantics and schemas

Required evidence:

- all new schemas migrate cleanly;
- canonical chord parser/renderer tests pass in Python and TypeScript;
- every registered detector label mapping is complete;
- no-chord/unknown/custom states round-trip;
- Simple/Standard/Detailed projection is non-destructive;
- source-time interval invariants are enforced.

### 28.2 Gate B — Reproducible local runtimes and inputs

Required evidence:

- BTC environment locks/starts;
- ChordMini environment locks/starts;
- Chordino availability is detected correctly;
- Essentia availability is detected correctly;
- registered model artifacts have verified hashes/provenance;
- original and harmonic input transforms are reproducible;
- no inference-time network request occurs.

### 28.3 Gate C — Automatic chord evidence

Required evidence:

- BTC real raw artifact passes validation;
- ChordMini real raw artifact passes validation;
- Chordino real native result passes normalization where available;
- decoder re-runs from raw artifact without neural inference;
- source boundaries align correctly;
- alternatives/score semantics are preserved.

### 28.4 Gate D — Versioned/correctable chord results

Required evidence:

- immutable automatic results retained;
- first edit creates branch;
- split/merge/boundary/rename/inversion operations pass undo/redo;
- rhythm-refined result is separately identified and dependency-correct;
- passing-bass inversion protection passes fixtures;
- result switching never deletes edits.

### 28.5 Gate E — Key/tuning correctness

Required evidence:

- tuning sign/error tests pass;
- tonal feature mapping passes;
- Essentia and independent key results are retained separately;
- global/local key states are distinct;
- no-stable-key/unknown behavior works;
- key-aware spelling does not mutate semantic chords;
- manual tuning stales only dependent results.

### 28.6 Gate F — Editor workflow

Required evidence:

- chord/key lanes align with waveform/ruler;
- long-project rendering remains responsive;
- linked selection works;
- snapping affects only current edits;
- readout follows audible source position;
- confidence/review navigation works;
- keyboard/accessibility alternatives exist.

### 28.7 Gate G — Integrated persistence

Required evidence:

- run graph dependencies are exact;
- cache keys distinguish all result-changing profiles;
- stale-result rules are selective;
- portable save/open works offline;
- missing optional raw arrays do not destroy corrected state;
- models/native runtimes absent on reopen do not block display/editing.

### 28.8 Gate H — Evidence and release readiness for next milestone

Required evidence:

- synthetic and real annotated evaluation completes;
- BTC/ChordMini/Chordino comparison report exists;
- original versus harmonic-remix results measured;
- key/tuning metrics recorded;
- performance/resource measurements recorded;
- five-track practical review completed;
- documentation/troubleshooting current;
- license inventory/packaging status explicit.

---

## 29. Final completion checklist

### 29.1 Model/runtime integration

- [ ] BTC adapter has a stable ID/version.
- [ ] BTC runtime is locked outside the core backend as required.
- [ ] BTC model artifacts have verified provenance and hashes.
- [ ] BTC model/device qualification succeeds on at least one supported local path.
- [ ] ChordMini adapter has a stable ID/version.
- [ ] ChordMini runtime/model provenance is independently recorded.
- [ ] ChordMini qualifies on at least one supported local path.
- [ ] Chordino adapter availability states are explicit.
- [ ] Chordino native output is preserved/normalized correctly where available.
- [ ] Essentia key adapter is isolated and versioned.
- [ ] No harmony adapter downloads during inference.
- [ ] No project open action installs code/models.
- [ ] CPU fallback is explicit.
- [ ] GPU identity uses stable UUID/device records.
- [ ] Model/native code and checkpoint/license terms are recorded separately.

### 29.2 Chord semantics and artifacts

- [ ] Canonical `ChordLabel` schema supports structured/no-chord/unknown/custom.
- [ ] Root pitch class is separate from spelling.
- [ ] Slash bass pitch class is separate from spelling.
- [ ] Detector raw labels are retained.
- [ ] Every registered detector label maps deterministically.
- [ ] Raw BTC framewise artifact is retained where exposed.
- [ ] Raw ChordMini framewise artifact is retained where exposed.
- [ ] Chordino native output is retained where practical.
- [ ] Raw score semantics/calibration status are explicit.
- [ ] Large raw arrays stay outside project JSON.
- [ ] Bounded raw artifact access works.
- [ ] Raw artifacts can be re-decoded without neural rerun.

### 29.3 Chord decoding/results

- [ ] Source-time mapping is validated.
- [ ] Model alignment convention is documented.
- [ ] Decoder profile is versioned.
- [ ] Temporal smoothing is versioned.
- [ ] No-chord and unknown remain distinct.
- [ ] Region intervals are half-open.
- [ ] Automatic regions do not overlap.
- [ ] Alternatives are retained where available.
- [ ] Automatic results are immutable.
- [ ] Reruns retain old results.
- [ ] Auto/Edited switching works.
- [ ] Edited branches retain parent provenance.

### 29.4 Complexity and spelling

- [ ] Simple projection works without mutating detailed label.
- [ ] Standard projection works without mutating detailed label.
- [ ] Detailed view restores all stored detail.
- [ ] Custom labels survive projection switching.
- [ ] Key-aware spelling changes display only.
- [ ] Explicit chord spelling override wins over key context.
- [ ] Clearing override restores automatic spelling.
- [ ] Enharmonic respelling does not create a semantic chord change unintentionally.

### 29.5 Chord editing

- [ ] Rename structured chord works.
- [ ] Preserve custom text works.
- [ ] Slash chord entry works.
- [ ] Boundary drag works.
- [ ] Shared-boundary drag is atomic.
- [ ] Split works.
- [ ] Merge works.
- [ ] Insert works.
- [ ] Delete/replace semantics are explicit.
- [ ] No-chord assignment works.
- [ ] Unknown assignment works.
- [ ] Alternative selection works.
- [ ] Review state works.
- [ ] Every operation supports undo/redo.
- [ ] Stale-tab edit returns conflict rather than silently overwriting.

### 29.6 Rhythm interaction

- [ ] Default chord result has no mandatory rhythm dependency.
- [ ] Manual chord snapping uses existing visual-radius resolver.
- [ ] Changing snap mode does not move existing chords.
- [ ] Optional rhythm refinement names exact rhythm identity.
- [ ] Rhythm refinement does not blindly quantize all boundaries.
- [ ] Editing referenced rhythm marks refined result stale.
- [ ] Unrefined chord result remains valid.
- [ ] Chord regions remain source-time objects.

### 29.7 Inversion evidence

- [ ] Detector-native inversion semantics are recorded when present.
- [ ] Low-frequency inversion evidence is region-level only.
- [ ] No bass note-event transcription is introduced.
- [ ] Passing-bass fixture does not create false slash chord under default profile.
- [ ] Stable inversion fixtures produce inspectable evidence.
- [ ] User can apply/clear inversion as an edit.
- [ ] Inversion confidence is distinct from chord-root confidence.

### 29.8 Tuning

- [ ] Tuning estimate has explicit sign/reference convention.
- [ ] Known-detuning tests pass within measured tolerance.
- [ ] Insufficient evidence is explicit.
- [ ] Manual tuning edit works.
- [ ] Reset to automatic works.
- [ ] Tuning edit does not change audio samples.
- [ ] Dependent tonal/key results become stale selectively.
- [ ] Tuning state is available for Milestone 5 handoff.

### 29.9 Key analysis

- [ ] Tuning-aware tonal feature artifact exists.
- [ ] Independent profile-correlation key estimator exists.
- [ ] Essentia key adapter exists.
- [ ] Global key result is separate from local regions.
- [ ] Local key windows/sequence are versioned.
- [ ] Relative-major/minor alternatives are retained.
- [ ] Fifth-related errors can be measured.
- [ ] Unknown key is supported.
- [ ] No-stable-key is supported.
- [ ] Key signature/spelling is separate from tonic/mode evidence.
- [ ] Automatic key results are immutable.
- [ ] Editable key branch works.

### 29.10 Key/tuning editing

- [ ] Edit tonic works.
- [ ] Edit mode works.
- [ ] Edit spelling works.
- [ ] Edit key boundary works.
- [ ] Shared key boundary edit is atomic.
- [ ] Split/merge/insert/delete key region works.
- [ ] Mark unknown/no-stable-key works.
- [ ] Choose alternative works.
- [ ] Review state works.
- [ ] Every key/tuning edit supports undo/redo/reopen.

### 29.11 Alternate inputs/models

- [ ] Harmonic non-drum remix uses exact retained stem result.
- [ ] Harmonic remix ignores current mixer state.
- [ ] Harmonic remix cache identity includes every contributing stem.
- [ ] Original-mix result remains separate.
- [ ] BTC result remains separate from ChordMini.
- [ ] Chordino result remains separate.
- [ ] Result selector shows input/model provenance.
- [ ] No silent model/input fallback occurs.

### 29.12 UI, selection, review

- [ ] Chord lane aligns with source waveform.
- [ ] Key lane aligns with source waveform.
- [ ] Waveform chord overlay is optional.
- [ ] Complexity selector is immediate and non-destructive.
- [ ] Tuning status is visible.
- [ ] Alternatives show score type.
- [ ] Low-confidence display does not rely on color alone.
- [ ] Linked selection works chord→waveform/key/bar.
- [ ] Linked selection works key→chord/waveform/bar.
- [ ] Related highlights do not become edit targets automatically.
- [ ] Musical readout shows active chord/key when available.
- [ ] Long-project rendering is virtualized/indexed.
- [ ] Keyboard-accessible edit alternatives exist.

### 29.13 Cache, persistence, portable projects

- [ ] Raw inference cache key includes model/weights/preprocessing.
- [ ] Decoder cache key is separate from neural inference.
- [ ] Rhythm-refinement cache key includes exact rhythm dependency.
- [ ] Key cache includes tuning/feature identity.
- [ ] Manual branches are protected project state.
- [ ] Autosave commits semantic edits immediately.
- [ ] Interrupted analysis never publishes partial result.
- [ ] Portable save includes active harmony state.
- [ ] Model weights are excluded.
- [ ] Raw prediction artifacts have optional/essential classification.
- [ ] Project reopens without harmony runtimes/models.
- [ ] Missing optional raw arrays do not remove edited chords/keys.
- [ ] Corrupt essential branch data is reported explicitly.

### 29.14 Evaluation and evidence

- [ ] Duration-weighted chord metrics are recorded.
- [ ] Simple/Standard/Detailed evaluation projections are documented.
- [ ] Boundary precision/recall is recorded.
- [ ] Inversion accuracy is recorded separately.
- [ ] Original versus harmonic-remix comparison is recorded.
- [ ] BTC versus ChordMini comparison is recorded.
- [ ] Chordino comparison is recorded where available.
- [ ] Tuning cents error is recorded.
- [ ] Global key exact/relative/fifth-related errors are recorded.
- [ ] Local key accuracy/boundary metrics are recorded.
- [ ] Confidence/review usefulness is measured.
- [ ] Correction burden is measured.
- [ ] Runtime/VRAM/RAM is recorded.
- [ ] Five supplied recordings complete practical review.
- [ ] No unannotated full-song reference accuracy is claimed.

### 29.15 Operational behavior and documentation

- [ ] Offline installed-model analysis passes.
- [ ] Offline reopen without models passes.
- [ ] Playback remains responsive during analysis.
- [ ] Failures name recoverable next action.
- [ ] No silent GPU→CPU/model/input fallback.
- [ ] User documentation covers chord/key/tuning semantics.
- [ ] Developer documentation covers artifact formats/cache dependencies.
- [ ] Troubleshooting covers common model/editor/key issues.
- [ ] License inventory is complete for new components.
- [ ] Packaging constraints for GPL/AGPL components are explicit.
- [ ] Milestone implementation report records measured limitations.

---

## 30. Traceability to Section 13 Milestone 4

| Main-plan Milestone 4 item | Detailed coverage |
|---|---|
| 1. Integrate BTC | M4.3, M4.5, M4.17, M4.22–M4.25 |
| 2. Integrate ChordMini challenger | M4.3, M4.6, M4.17, M4.22–M4.25 |
| 3. Integrate Chordino fallback | M4.3, M4.7, M4.17, M4.22–M4.25 |
| 4. Preserve raw prediction artifacts | M4.1, M4.5–M4.8, M4.20–M4.22 |
| 5. Build chord regions | M4.1, M4.8–M4.10 |
| 6. Add chord overlays | M4.18 |
| 7. Add dedicated chord track | M4.18–M4.19 |
| 8. Add split/merge/rename/boundary operations | M4.15, M4.19–M4.20 |
| 9. Add inversion entry | M4.11, M4.15 |
| 10. Add complexity projections | M4.2, M4.18 |
| 11. Integrate tuning/key analysis | M4.12–M4.14, M4.17 |
| 12. Add key-region editor | M4.16, M4.18–M4.20 |
| 13. Add confidence review | M4.18–M4.19, M4.23 |
| 14. Compare original and harmonic-remix inputs | M4.4, M4.17, M4.23 |
| 15. Validate save/open and undo behavior | M4.15–M4.16, M4.21–M4.22, M4.24 |

The main acceptance condition—chords and key are detected, synchronized, and fully correctable—is satisfied only when Gates A–H pass, not merely when one model displays chord labels.

---

## 31. Handoff to Milestone 5 — Bass transcription

Deliver to the bass-transcription milestone:

1. Stable source-frame project timing unchanged by harmony work.
2. Active original/stem separation result identity.
3. A reusable selected bass stem and aligned waveform/playback interfaces from Milestone 2.
4. A corrected/selected rhythm result/branch from Milestone 3 when available.
5. Immutable chord results with source-time regions.
6. Editable chord branches with stable IDs/revisions.
7. Active chord source selection (Auto/Edited) and complexity/display semantics.
8. Global/local key results with source-time regions.
9. Editable key branches with stable IDs/revisions.
10. An explicit active tuning context with reference frequency/cents offset.
11. Tuning sign/reference conventions and evaluation evidence.
12. Tonal/key spelling services that can later help note naming without changing MIDI pitch.
13. A shared linked-selection model already aware of waveform, bar, chord, and key context.
14. Event-boundary snapping provider including chord/key boundaries.
15. Musical readout capable of adding an active bass note field.
16. Confidence/review conventions that preserve machine score versus human correction.
17. Durable analysis/version/cache dependencies suitable for a transcription tied to a specific bass stem and tuning context.
18. Portable-project persistence that reopens chord/key/tuning context without models.
19. Harmony artifacts/results that remain valid even when bass transcription is rerun.
20. Conservative inversion evidence clearly marked as region-level evidence, not bass-note ground truth.

Milestone 5 must:

- explicitly select the bass stem/result it transcribes;
- explicitly select the tuning context used for pitch naming/cents interpretation;
- keep note events source-time based rather than forcing beat quantization;
- keep corrected chord/key context as optional review information unless a transcription algorithm explicitly declares it as an input dependency;
- avoid treating Milestone 4 inversion evidence as a substitute for framewise F0/note segmentation;
- create a new transcription version when any declared upstream bass-stem/tuning dependency changes;
- never rewrite corrected chord/key branches as a side effect of note analysis.

