# Milestone 5 — Bass transcription: detailed implementation specification

This expands Milestone 5 in Section 13 of [`basseparate_project_plan.md`](../product/basseparate_project_plan.md).

It builds on `milestone0.md`, `milestone1.md`, `milestone2.md`, `milestone3.md`, and `milestone4.md`. Those milestones remain authoritative for the application foundation, immutable source/stem timing, waveform editor, synchronized playback, separation versions, musical grid, chord/key/tuning context, project commands, portable projects, and recovery behavior. Milestone 5 extends those systems; it must not fork or replace them.

The main-plan Milestone 5 scope is: pitch-analysis views; bass-stem-specific tuning estimation as a separate result; torchcrepe; pYIN; low-register auxiliary inference; candidate fusion; silence/voicing logic; attack detection; note segmentation; slide/bend retention; two synchronized note views; note editing; linked selection; bass MIDI export; and validation of low B, drop tunings, tuning offsets, repeated notes, and slides.

---

## 1. Required outcome and milestone boundaries

### 1.1 Complete user workflow

At completion, the user can:

1. Open an imported project with a compatible separated bass stem.
2. Choose the exact separation result and bass stem to transcribe.
3. Inspect the active project tuning context inherited from Milestone 4.
4. Run or reuse a bass-stem-specific tuning estimator tied to the exact selected bass stem, and inspect its immutable tuning result.
5. Select the tuning interpretation used by transcription: the compatible bass-stem estimate by default when valid, or an explicit Milestone 4/manual override.
6. Run bass transcription without changing the source audio, stem audio, musical grid, chords, or key.
7. See progress for bass-stem tuning estimation, pitch extraction, low-register auxiliary analysis, fusion, attack detection, and note decoding.
8. Inspect framewise pitch-analysis evidence aligned to the bass waveform.
9. Compare torchcrepe, pYIN, auxiliary low-register, fused F0, voicing, onset, and ambiguity evidence.
10. See discrete bass notes drawn above the bass waveform.
11. See synchronized scientific-pitch note text in a dedicated lane below the bass waveform.
12. Click a note in either view and select the same note, waveform interval, active chord, bar/beat context, and key context.
13. Audition a selected note interval against the separated bass stem or current practice mix.
14. Move a note start or end in source time.
15. Change a note's nominal pitch by direct entry, semitone, or octave operations.
16. Insert and delete notes.
17. Split and merge notes.
18. Correct octave errors without changing neighboring note timing unintentionally.
19. Mark a detected event as unpitched or unknown.
20. Inspect and edit retained continuous slide/bend information.
21. Review low-confidence or ambiguous notes using next/previous navigation.
22. Keep automatic transcription immutable while corrections live in an editable branch.
23. Switch between automatic and edited transcription views without destroying either.
24. Re-run transcription on another bass-stem version while keeping earlier results and edits.
25. Export the selected automatic or edited transcription as bass MIDI.
26. Reopen the project without torchcrepe, PyTorch, the separation model, or network access and retain the complete saved transcription, evidence needed for display, edits, and MIDI export.
27. Undo and redo every note-editing operation introduced in this milestone.

### 1.2 Included capabilities

Milestone 5 includes:

- Bass-stem selection and explicit transcription dependencies.
- Bass-stem-specific tuning estimation as a separate immutable result tied to the selected stem, with explicit selection/fallback to project tuning context.
- A reusable bass-transcription analysis input.
- torchcrepe integration using an isolated analysis runtime when required.
- librosa pYIN integration.
- The main plan's analysis-only double-speed/one-octave-up auxiliary path.
- Native framewise pitch and confidence/evidence preservation.
- A canonical fused pitch-evidence timeline.
- Silence and voicing classification with hysteresis.
- Octave-candidate comparison and correction evidence.
- Energy-envelope and spectral-flux attack evidence.
- Same-pitch repeated-note preservation.
- Note onset, sustain, release, and discrete event segmentation.
- Continuous F0-trajectory retention for slides and bends.
- Ambiguous/polyphonic-region flags.
- Immutable automatic transcription results.
- Editable transcription branches.
- Pitch-analysis diagnostic views.
- Bass-note waveform overlay.
- Synchronized note-text lane.
- Bass-note inspector and editing operations.
- Linked selection with waveform, chord, key, and rhythm context.
- Confidence/review workflow for pitch and note events.
- Bass MIDI export.
- API, job, cache, staleness, persistence, and portable-project integration.
- Low-B, drop-tuning, repeated-note, slide, silence, synth-bass, and long-track validation.

### 1.3 Explicitly deferred capabilities

Do not pull Milestone 6 or later scope into this milestone.

Still deferred unless an earlier milestone already supplied the general mechanism:

- Complete command coverage for every project feature outside bass transcription.
- The Milestone 6 final persistent undo/redo hardening across all modules.
- Full application-wide Auto/Edited/model-version comparison UI beyond the practical bass selector required here.
- General downstream stale-result dashboard across all modules.
- Snippet queues.
- Full remappable keyboard map beyond bass-editor shortcuts needed locally.
- FLAC/MP3 expansion and general export presets.
- General CSV/JSON analysis-export suite.
- Cache-management UI expansion.
- SCNet/RoFormer quality-model integration.
- Six-stem guitar mode.
- YouTube import.
- Whole-pipeline `Analyze All` integration if it has not already been implemented by the owning milestone.
- Automatic tablature or string/fret inference.
- Fingering optimization.
- Chord rewriting from bass-note evidence.
- Automatic chord-inversion rewriting from the transcription.
- Polyphonic bass transcription as a promised supported mode.

Milestone 5 may expose data that later milestones use, but it must not silently implement their editing or workflow semantics.

### 1.4 Inherited prerequisites

Milestone 5 assumes earlier milestones provide:

1. Immutable canonical source audio and project source-frame timing.
2. Durable media and analysis jobs.
3. Immutable separation results with stable stem identities.
4. A separated bass stem aligned to project source time.
5. Bass-stem waveform peaks and playback representations.
6. Shared waveform viewport and source-frame selection.
7. Source-time transport with latency-compensated audible-position mapping.
8. Variable-speed practice playback independent of stored event timing.
9. Project commands, revisions, idempotency keys, and basic undo/redo.
10. Portable `.basseparate` save/open with analysis artifacts.
11. Immutable automatic analysis-result semantics.
12. Editable-branch semantics.
13. Rhythm result/branch selection and musical readout when Milestone 3 exists.
14. Chord/key result/branch selection and linked context when Milestone 4 exists.
15. Explicit tuning context, including reference frequency/cents offset conventions, from Milestone 4.
16. Model registry, explicit installation, worker isolation, and device qualification patterns from prior model milestones.
17. Shared confidence and human-review schema.

If an owning prerequisite fails, fix it at that milestone boundary rather than hiding it inside a bass-specific workaround.

### 1.5 Definition of the milestone boundary

Milestone 5 is complete only when framewise evidence, fused F0, discrete note events, continuous pitch gestures, editing, linked display, persistence, export, and evaluation work as one coherent workflow.

The following are not sufficient:

- showing raw torchcrepe F0 without note segmentation;
- producing note names from pYIN without preserving framewise evidence;
- rounding every frame directly to a MIDI note and merging equal labels;
- treating silence as an F0 value;
- deleting low-confidence frames so they cannot be reviewed;
- forcing all pitch to equal-tempered centers;
- quantizing notes to beats automatically;
- representing a slide only as a start note and end note;
- splitting every pitch fluctuation into a new note;
- merging repeated same-pitch attacks into one long note;
- reporting torchcrepe periodicity or pYIN voiced probability as calibrated note correctness;
- exporting MIDI from automatic output when the user explicitly selected the edited branch;
- making a transcription independent of the specific bass stem that produced it.

---

## 2. Fixed implementation decisions for Milestone 5

| Area | Milestone 5 decision |
|---|---|
| Default input | A selected separated bass stem/result-set version |
| Authoritative event time | Integer project source frames |
| Primary neural pitch evidence | torchcrepe `full` |
| Independent low-frequency evidence | librosa pYIN |
| Low-register auxiliary | Analysis-only factor-2 time compression / octave-up neural path, mapped back to source time and frequency |
| Initial pitch range | Approximately 25–800 Hz |
| Initial fused frame hop | Approximately 10 ms, represented in project time without making milliseconds authoritative |
| pYIN low-frequency window | Approximately 128 ms initial profile |
| Pitch representation | Continuous Hz/F0 plus nominal MIDI pitch and cents deviation |
| Voicing | Explicit voiced/unvoiced/ambiguous state; never encoded as zero-Hz pitch |
| Automatic result | Immutable transcription result version |
| Manual result | Editable branch derived from one automatic result |
| Beat snapping | Optional edit-time behavior only; never mandatory analysis quantization |
| Chord/key context | Review/display context by default; not a decoder dependency unless a future named profile explicitly declares it |
| Tuning context | Bass-stem-specific immutable tuning estimate is preferred when valid; Milestone 4/manual tuning remains an explicit fallback/override. The selected tuning interpretation is a decode dependency |
| Slide/bend | Continuous source-aligned contour retained separately from nominal note identity |
| Monophonic editing | Default; overlapping manual notes rejected unless explicit overlapping-note representation is enabled |
| MIDI export | Explicitly Auto or Edited; source-time note timing mapped to MIDI ticks using selected project tempo map when available, with a documented fallback when no grid exists |
| Model downloads | Explicit only; no inference-time remote fallback |
| Portable reopen | No pitch model, separation model, GPU, or internet required |

### 2.1 Three layers of transcription data

Keep three different layers explicit:

1. **Raw/native estimator evidence**
   - torchcrepe native F0/periodicity outputs;
   - pYIN F0/voiced evidence;
   - low-register auxiliary neural evidence;
   - energy/spectral evidence.
2. **Fused framewise pitch state**
   - one source-aligned evidence timeline used by the decoder;
   - selected F0 candidate;
   - alternatives;
   - voicing state;
   - ambiguity/octave flags;
   - attack evidence.
3. **Discrete bass-note events**
   - onset/end source frames;
   - nominal MIDI pitch;
   - cents/tuning information;
   - note-level confidence/evidence summaries;
   - continuous contour/gesture reference;
   - review/edit state.

Do not collapse these layers into one mutable table.

### 2.2 Source time remains authoritative

All event boundaries are integer source frames at the project's selected source rate.

Model sample rates, native frame hops, downsampled representations, and time-compressed auxiliary input are preprocessing details only.

Every estimator adapter must map its evidence back to source-frame coordinates before cross-estimator fusion.

Playback speed never changes note boundaries or transcription timing.

### 2.3 Pitch identity and tuning deviation are separate

For a voiced note/event retain:

- continuous fundamental-frequency evidence in Hz;
- nominal equal-tempered MIDI pitch identity;
- continuous cents deviation relative to the selected tuning-reference convention;
- optional summary tuning offset within the note;
- continuous contour for bends/slides.

Changing a note's nominal MIDI pitch is an edit to transcription semantics.

Changing either the project tuning context or the selected bass-stem tuning result does not pitch-shift audio. Because the decoder profile uses the selected tuning interpretation for pitch-class interpretation and cents assignment, a transcription decoded under a different tuning interpretation is a distinct result identity. Raw estimator artifacts that do not depend on tuning may remain reusable.

### 2.4 Scientific note naming

Use scientific pitch notation in the UI, with MIDI 69 corresponding to A4 under the project convention.

Displayed enharmonic spelling may use the active key/spelling context from Milestone 4 when available, but:

- semantic MIDI pitch remains unchanged;
- user spelling overrides remain separate;
- a key edit must not silently alter the transcription's note timing or MIDI pitch;
- spelling-only display changes need not force neural re-analysis.

### 2.5 Continuous gestures are not new discrete notes by default

A pitch trajectory may move substantially during one sounding event.

The decoder distinguishes:

- stable note;
- bend/vibrato-like deviation within a note;
- slide/glissando connecting pitches;
- repeated attack on the same nominal pitch;
- genuinely new discrete note.

Boundary decisions use attack/release evidence and trajectory structure, not only nearest-semitone changes.

### 2.6 Rhythm and harmony are context, not hidden priors

Initial Milestone 5 decoding does not require:

- beat positions;
- chord labels;
- key labels.

These may be shown in the editor and used by a human reviewer.

Optional snapping during manual edits uses the selected active grid at edit time only.

A future decoder may explicitly consume rhythm/harmony context under a new profile/version, but that dependency must then enter the cache key and staleness graph.

### 2.7 Cross-project constraints carried forward

The following remain binding:

1. Local-first execution.
2. Authenticated loopback APIs.
3. Immutable source/stem assets.
4. Integer project-source timing.
5. Immutable automatic outputs.
6. Editable branches for corrections.
7. Typed confidence with explicit calibration semantics.
8. Framewise arrays stored as bounded binary artifacts rather than project JSON.
9. Durable jobs published atomically.
10. One heavy job per GPU initially.
11. Playback responsiveness takes priority over analysis throughput.
12. Models are explicitly installed and hash-verified.
13. GPUs remain separate memory pools.
14. Result cache identities include all declared dependencies and algorithm profiles.
15. Portable reopen requires no inference.
16. Failed reruns never destroy a usable earlier transcription.
17. Stale results remain inspectable until replaced.
18. Human corrections never become synthetic model confidence.
19. Editing one module must not rewrite another module's corrected branch as a side effect.
20. Accuracy is measured on appropriate labeled data rather than implied by UI polish.

---

## 3. Work package M5.1 — Verify prerequisites and extend the domain

### 3.1 Prerequisite verification

Before implementing transcription:

1. Run all Milestone 0–4 acceptance checks relevant to imported audio, separation, transport, commands, and portable projects.
2. Open each existing test project used in prior milestones.
3. Verify canonical source frame count and sample rate.
4. Verify the selected bass stem's project alignment offset and frame count.
5. Verify bass stem playback remains aligned at 0.25×, 1×, and 2×.
6. Verify waveform and sample-level rendering for the bass track.
7. Verify project commands still detect stale base revisions.
8. Verify model-worker startup remains independent of ordinary backend startup.
9. Verify portable reopen works with models unavailable.
10. Verify active tuning context can be read without running key analysis again.
11. Verify linked selection already returns waveform/chord/key/rhythm context where those modules exist.
12. Record baseline CPU/RAM/audio-underrun behavior during prepared playback before adding pitch analysis.

### 3.2 Transcription analysis run

Define `BassTranscriptionRun` containing at least:

- run UUID;
- project UUID;
- selected separation result-set UUID;
- selected bass-stem UUID;
- bass-stem audio asset ID/hash;
- selected tuning interpretation kind (`bass_stem_estimate`, `project_tuning`, or explicit manual override);
- selected bass-stem tuning-result ID/version when used;
- project/manual tuning-context ID/version when used;
- requested pitch profile;
- torchcrepe model/weight identity;
- pYIN profile version;
- low-register auxiliary profile version;
- fusion profile version;
- voicing profile version;
- attack profile version;
- decoder/segmentation profile version;
- requested device;
- actual device/GPU UUID where applicable;
- worker environment fingerprint;
- requested/effective parameters;
- run seed where any nondeterministic path exists;
- start/end timestamps;
- status;
- artifact IDs for native/fused evidence;
- decoded transcription result ID;
- warnings;
- runtime metrics;
- peak host/device memory where available.

### 3.3 Native estimator artifact manifest

Define a versioned binary-artifact manifest that can reference:

- torchcrepe native frame positions;
- torchcrepe F0 array;
- torchcrepe periodicity/score array;
- pYIN native frame positions;
- pYIN F0 array;
- pYIN voiced flag/probability where supplied;
- auxiliary-path native frame positions;
- auxiliary F0 array;
- auxiliary periodicity/score array;
- source-to-model mapping metadata;
- dtype/shape/endianness;
- source asset hash;
- estimator/profile versions;
- content hashes.

Use immutable binary arrays suitable for bounded reads. Do not serialize one JSON object per pitch frame.

### 3.4 Fused pitch-evidence artifact

Define a canonical fused evidence timeline containing per frame:

- source-frame center position;
- optional represented source interval;
- selected F0 in Hz or null;
- selected nominal MIDI candidate before note segmentation;
- cents deviation;
- voicing state;
- selected-candidate source (`torchcrepe`, `pyin`, `aux`, `agreement`, or `none`);
- estimator-specific scores/evidence;
- alternative candidate frequencies/pitches;
- octave-conflict flag;
- ambiguity flag;
- energy evidence;
- spectral-flux/attack evidence;
- silence evidence;
- interpolation/missing-evidence flag where applicable.

Keep sufficient estimator evidence to explain why a fused frame chose one candidate over another.

### 3.5 Bass-note event record

Each automatic `BassNoteEvent` contains:

- event UUID;
- parent transcription result ID;
- start source frame;
- end source frame, exclusive;
- nominal MIDI pitch or null for unpitched/unknown;
- display-note spelling state;
- representative F0 in Hz;
- median/robust cents deviation;
- pitch-contour artifact/reference and source range;
- gesture classification/state;
- slide/bend metadata;
- onset-evidence summary;
- release-evidence summary;
- voicing-evidence summary;
- ambiguity/polyphony flags;
- confidence object;
- automatic provenance;
- review state.

Validation:

1. `0 <= start < end <= source_frame_count`.
2. Events are source-time ordered.
3. Default monophonic result has no overlapping active pitched notes.
4. MIDI pitch, when present, is within the declared supported numeric range.
5. Nonfinite F0/cents values are rejected.
6. Unknown/unpitched events use explicit state rather than an arbitrary pitch number.
7. Contour references remain inside the event interval except for documented decoder context.

### 3.6 Pitch gesture record

Represent retained continuous pitch movement explicitly rather than flattening it into the event label.

A gesture may contain:

- type: `stable`, `bend`, `slide`, `vibrato`, `uncertain`;
- start/end source frames within the note;
- start/end or min/max cents relative to nominal note;
- optional destination nominal pitch for a slide;
- direction;
- confidence/evidence semantics;
- reference to the underlying fused contour.

Do not require every natural vibrato fluctuation to become an editable gesture object. Store high-resolution contour once and create gesture summaries only when the decoder identifies musically useful structure.

### 3.7 Automatic transcription result

Define immutable `BassTranscriptionResult` containing:

- result UUID;
- parent run ID;
- bass-stem identity/hash;
- selected tuning-interpretation identity/version, including bass-stem tuning-result ID when used;
- native estimator artifact ID;
- fused evidence artifact ID;
- decoder profile/version;
- note-event collection/reference;
- unvoiced/ambiguous region summaries;
- validation status;
- result warnings;
- creation timestamp;
- evaluation/diagnostic metrics when available.

### 3.8 Editable transcription branch

Define a branch containing:

- branch UUID;
- parent automatic transcription result UUID;
- branch revision;
- editable note events;
- manual gesture overrides;
- optional overlapping-note-mode setting;
- branch-level review summary;
- created/updated timestamps.

The automatic result remains immutable.

### 3.9 Project-level bass-transcription state

Add:

- active bass-transcription result ID;
- active edited branch ID;
- Auto/Edited display mode;
- selected pitch-analysis diagnostic layer(s);
- pitch-view visibility/height/scale;
- note-overlay visibility;
- note-text-lane visibility/height;
- confidence threshold/view settings;
- last selected note ID;
- editor monophonic/overlap mode;
- preferred note spelling source;
- bass MIDI export defaults local to this module if needed.

### 3.10 Schema/database migration

1. Increment database schema through an ordered migration.
2. Update project serialization schema.
3. Update portable-project schema.
4. Preserve Milestone 0–4 projects with no bass transcription.
5. Add null/default transcription state without modifying existing audio/stem/harmony assets.
6. Generate updated TypeScript contracts.
7. Add migration fixtures for imported-only, separated, rhythm-enabled, harmony-enabled, and portable projects.
8. Reject newer unsupported transcription schemas without writing them.

**Acceptance:** the domain can represent raw estimator evidence, fused F0, discrete note events, continuous gestures, immutable automatic results, editable branches, and explicit upstream dependencies without altering the source or bass stem.

---

## 4. Work package M5.2 — Establish the pitch-analysis runtime and module contract

### 4.1 Runtime isolation

Use the existing worker architecture rather than importing research ML code into the backend process.

Requirements:

1. Keep ordinary backend startup free of mandatory torchcrepe/PyTorch imports.
2. Reuse a compatible already-locked analysis environment only when dependency versions genuinely coexist.
3. Otherwise create a dedicated locked bass-pitch environment.
4. Pin Python and direct runtime dependencies.
5. Record environment fingerprint and exact resolved versions.
6. Start the worker with an explicit interpreter path.
7. Do not download weights on worker startup.
8. Do not access the network during inference.
9. Preserve license/provenance records for torchcrepe code and bundled/published weights separately.
10. Keep pYIN/librosa version identity in the profile/cache key.

### 4.2 Module capability declaration

Declare a stable bass-transcription module with:

- module ID/version;
- supported input role: separated bass stem;
- optional diagnostic support for manually chosen alternative compatible stem only if explicitly allowed;
- output schema versions;
- parameter schema;
- model/weight requirements;
- CPU/GPU support;
- expected memory class;
- cancellation granularity;
- determinism limitations;
- confidence/evidence semantics;
- artifact formats;
- license records.

### 4.3 Device qualification

For each candidate device:

1. Start the pitch worker.
2. Load torchcrepe full.
3. Run a short deterministic low/mid-bass fixture.
4. Confirm finite F0/score outputs.
5. Verify the low-register auxiliary representation can run through the same model path.
6. Measure elapsed time.
7. Measure host/device memory where available.
8. Record runtime versions and GPU UUID.
9. Mark the model/device pair qualified only after successful inference.

Prefer the secondary GPU for independent pitch work when it is qualified and available, consistent with the broader scheduler's separation priority, but do not hard-code device indices.

### 4.4 CPU behavior

1. Support CPU pitch inference when the selected implementation permits it.
2. Bound CPU threads to protect playback responsiveness.
3. Preserve the same output schemas.
4. Record actual device.
5. Do not silently fall back from a failed requested GPU to potentially much slower CPU execution.
6. Offer explicit retry on CPU.

### 4.5 Cancellation and failure behavior

The worker must:

- check cancellation at bounded inference/batch boundaries;
- stop before writing additional staged arrays after cancellation;
- remove incomplete staged artifacts;
- preserve completed upstream artifacts;
- release GPU memory through cleanup/process exit when necessary;
- report structured failure without deleting an earlier transcription.

### 4.6 No hidden model download

Before a torchcrepe run:

1. Resolve the registered model/weight identity.
2. Verify local bytes and expected hash/provenance.
3. Pass explicit local weight access into the worker as supported by the selected integration.
4. Disable or avoid remote fallback.
5. Fail clearly when required weights are unavailable.

Opening a saved project never triggers a pitch-model download.

**Acceptance:** pitch analysis can be qualified and run in an isolated worker with network disabled, while the application remains fully usable for playback/editing when the pitch runtime is unavailable.

---
## 5. Work package M5.3 — Select the transcription input and tuning interpretation explicitly

### 5.1 Input-selection policy

Bass transcription consumes a specific separated bass stem, not an abstract `current bass` alias.

The request records:

- separation result-set ID;
- bass stem ID;
- bass audio asset hash;
- project sample rate/frame count;
- stem alignment offset;
- selected tuning interpretation kind and referenced tuning-result/context ID/version;
- transcription profile.

If no compatible bass stem exists, the UI explains that separation must be completed first.

### 5.2 Stem validity

Before analysis:

1. Verify the result set is complete and validated.
2. Verify the role is `bass` according to the separation result's declared labels.
3. Verify asset bytes exist.
4. Verify content hash when integrity is uncertain.
5. Verify finite PCM metadata.
6. Verify sample rate/channel count/frame count.
7. Verify project alignment offset.
8. Reject unexplained frame-count mismatch.
9. Record whether the stem came from a stereo source, downmixed multichannel reference, or mono source.
10. Preserve source/separation provenance in the transcription run.

### 5.3 Multiple separation versions

When several bass stems/results exist:

- show model/result provenance;
- show creation date and active/inactive state;
- allow explicit selection;
- default to the project's currently active compatible separation result when unambiguous;
- never silently move an existing transcription branch to a different bass stem.

Selecting a different bass stem for a new run creates a different transcription result identity.

### 5.4 Tuning-interpretation selection

For a selected bass stem, prefer the latest compatible validated `BassStemTuningEstimate` produced from that exact stem. If no usable bass-stem estimate exists, fall back explicitly to the active Milestone 4 tuning context; a user may also choose the project tuning or a module-local manual override even when a bass-stem estimate exists. Never silently substitute a tuning result from another stem/version.

Display at least:

- tuning source/kind;
- exact source stem/result identity for a bass-stem estimate;
- reference convention;
- estimated/manual offset;
- estimator/profile version and evidence summary where applicable;
- provenance/review state;
- whether it is automatic or corrected/overridden.

A transcription-run override does not rewrite the project's Milestone 4 key/tuning branch.

### 5.5 Tuning dependency split

Separate bass-stem tuning estimation, reusable pitch-estimator work, and tuning-dependent decoding:

- `BassStemTuningEstimate` depends on the exact selected bass-stem audio asset plus its own estimator/profile version;
- raw F0 in Hz from pYIN/torchcrepe may be independent of the selected tuning interpretation;
- nominal MIDI/cents interpretation and fusion thresholds expressed in cents depend on the selected tuning interpretation/reference convention;
- decoded note results therefore record the exact tuning-result/context identity explicitly;
- changing the selected tuning interpretation may reuse raw F0 artifacts while forcing fusion/decoder re-evaluation under a new cache key.

### 5.6 Optional rhythm/chord/key context

Load these for display/review only by default:

- active rhythm branch/result;
- active chord branch/result;
- active key branch/result.

Do not include them in the default transcription cache key unless the decoder actually consumes them.

### 5.7 Source replacement/staleness

If the project's source or selected bass stem becomes unavailable/corrupt:

- keep transcription metadata visible as unavailable/stale where safe;
- do not rebind the result to a different similarly named stem;
- preserve portable-project references and diagnostics;
- require explicit regeneration/reselection.

**Acceptance:** every transcription can be traced to one exact bass-stem asset and one explicit tuning interpretation; a bass-stem estimate can never be silently reused for a different stem, and no active-result alias can make provenance ambiguous.

---

## 6. Work package M5.4 — Build a reproducible mono bass-analysis representation

### 6.1 Purpose

Create a stable analysis signal that all pitch/attack modules can consume without repeatedly inventing channel/downmix rules.

### 6.2 Channel handling

For mono bass stem:

- reuse mono samples directly.

For stereo bass stem:

1. Preserve the original stereo stem unchanged.
2. Build a dedicated mono analysis representation.
3. Use a documented phase-aware or channel-combination policy chosen during implementation testing.
4. Do not assume `(L + R) / 2` is always safe for anti-phase material without validation.
5. Record the transform profile/version.

The analysis representation is not a playback replacement.

### 6.3 Phase-cancellation guard

Before accepting a simple stereo sum/average profile:

1. Measure left/right energy.
2. Measure sum and difference energy over bounded windows.
3. Detect material where averaging would cancel substantial bass content.
4. In such cases choose a documented fallback, such as stronger-channel or energy-preserving combination, under a versioned profile.
5. Record a warning and effective transform.

Do not alter the stored stem.

### 6.4 Sample-rate representations

Each estimator declares its required input sample rate.

For each required representation:

1. Resample continuously from the mono analysis signal.
2. Use a versioned resampling profile.
3. Preserve exact source-time mapping.
4. Record endpoint rounding.
5. Cache by source hash + mono-transform profile + sample-rate profile.
6. Never independently resample each inference chunk without overlap/context handling.

### 6.5 Amplitude handling

1. Preserve relative dynamics.
2. Do not peak-normalize the bass stem merely for transcription.
3. Apply estimator-required normalization only inside its adapter/profile.
4. Record every normalization step.
5. Protect zero/near-zero signals from division by very small values.

### 6.6 Analysis interval

Initial Milestone 5 supports full-track transcription.

The internal architecture may accept an explicit source interval for tests/future partial analysis, but the production UI need not advertise partial transcription unless fully integrated.

If interval support exists in the worker contract, cache identity includes:

- requested source interval;
- context padding;
- trimming/mapping profile.

### 6.7 Long-track processing

All representations are streamed/chunked with bounded memory.

Do not load a multi-hour float32 stem and every derived array into RAM simultaneously.

Target behavior:

- sequential preprocessing;
- memory-mapped or chunk-addressable arrays where appropriate;
- staged binary output;
- bounded estimator batches;
- final manifests only after validation.

### 6.8 Degenerate inputs

Explicitly handle:

- exact digital silence;
- near silence;
- DC-heavy signal;
- short clips;
- strong stereo anti-phase content;
- clipped but finite bass stem;
- sparse notes separated by long silence.

Exact silence may skip expensive pitch inference and produce an all-unvoiced evidence artifact under an explicit shortcut profile.

**Acceptance:** every estimator receives a reproducible, bounded-memory representation whose source-time mapping and channel transform are auditable.

### 6.9 Bass-stem-specific tuning estimator

Run a dedicated tuning estimator on the selected mono bass-analysis representation before pitch-class/note decoding. This estimator is distinct from Milestone 4 whole-mix/project tuning analysis.

Initial requirements:

1. Derive a dedicated high-resolution spectral/harmonic tuning-evidence stream directly from the mono bass-analysis signal; this estimator does not require pYIN, torchcrepe, or the Milestone 4 tuning result to run.
2. Estimate stable frequency candidates from harmonic/spectral peaks and convert their residual pitch positions into cents modulo one semitone, so octave choice does not change the global tuning-offset estimate.
3. Exclude or down-weight silence, attacks, strong bends/slides, low-harmonicity frames, and spectrally unstable frames.
4. Aggregate residuals with robust circular statistics and reject strongly multimodal/unstable evidence rather than averaging incompatible offsets.
5. Support whole-track estimation plus optional diagnostic interval summaries, while publishing one selected global bass-stem tuning result for the initial decoder profile.
6. Record estimator/profile version, source stem asset hash, analyzed interval coverage, reference frequency, cents offset, evidence count/coverage, dispersion/stability metrics, warnings, and score semantics.
7. Treat low evidence or multimodal/unstable offsets as `uncertain`/`no_stable_tuning` rather than forcing a precise value.
8. Never modify or retune audio samples and never overwrite the Milestone 4 project tuning branch automatically.

### 6.10 `BassStemTuningEstimate` result

Publish the estimator output as an immutable analysis result with its own ID and cache identity. At minimum store:

- result ID;
- selected separation result/stem ID and audio asset hash;
- analysis-representation transform/profile identity;
- tuning-estimator/profile version;
- reference frequency/convention;
- estimated cents offset or null;
- validity state: `valid`, `uncertain`, or `no_stable_tuning`;
- evidence/coverage and dispersion summaries;
- warnings;
- creation timestamp and provenance.

A different bass stem/version always produces a distinct tuning-result identity even when its numerical offset happens to match. Failed reruns do not delete earlier valid estimates.

**Acceptance:** bass-stem tuning is independently inspectable, cacheable, versioned, and selectable as a transcription decoding dependency without rewriting project-level tuning state.

---

## 7. Work package M5.5 — Integrate pYIN low-frequency pitch evidence

### 7.1 Role

pYIN is an independent low-frequency estimator and voicing source, not merely a fallback error handler.

Initial configured range follows the main plan: approximately 25–800 Hz.

### 7.2 Profile

Create a versioned `pyin_bass_v1` profile containing at least:

- minimum frequency;
- maximum frequency;
- sample rate;
- frame/hop parameters;
- approximately 128 ms low-frequency analysis-window policy from the main plan;
- center/padding behavior;
- fill/unvoiced semantics;
- any probability/threshold settings actually used;
- librosa/version identity.

Resolve exact library-compatible values during implementation and commit them as profile data/tests rather than leaving hidden defaults.

### 7.3 Execution

1. Open the prepared mono analysis representation.
2. Process in bounded windows or through a whole-array path only when memory remains bounded for supported track lengths.
3. Preserve native pYIN frame positions.
4. Collect F0 values.
5. Collect voiced flag/probability outputs exposed by the pinned implementation.
6. Validate finite voiced F0 values.
7. Map native frame centers to source-frame coordinates.
8. Preserve unvoiced as null F0 plus voicing evidence.
9. Publish immutable arrays and metadata.

### 7.4 Frequency validation

For voiced pYIN output:

- reject nonpositive/nonfinite F0;
- flag values outside the configured range;
- do not clamp an invalid pitch into range;
- preserve boundary-near estimates for diagnostics.

### 7.5 Time mapping

Map each pYIN frame to project source time using the exact preprocessing ratio and frame-centering convention.

Do not derive timing by accumulating rounded 10 ms increments.

### 7.6 Silence behavior

pYIN unvoiced output is evidence, not final truth.

The fusion stage combines it with:

- energy;
- torchcrepe periodicity;
- auxiliary evidence;
- temporal hysteresis.

Do not discard a potentially valid low-B frame solely because one estimator reports unvoiced.

### 7.7 Tests

Include:

- sine tones near B0 and E1;
- detuned tones;
- amplitude fades;
- silence transitions;
- repeated plucks;
- slides across semitone boundaries;
- synthetic octave-confusion mixtures;
- known source-frame impulse/tone boundaries for timing.

**Acceptance:** pYIN produces reproducible source-aligned low-frequency F0 and voicing evidence with explicit native-frame semantics and no fabricated pitch in unvoiced frames.

---

## 8. Work package M5.6 — Integrate torchcrepe full neural pitch evidence

### 8.1 Role

Use torchcrepe `full` as the initial neural monophonic pitch estimator.

Its output is evidence for fusion; it does not directly define note events.

### 8.2 Model manifest

Register the exact torchcrepe model/weight artifacts used by the application with:

- stable basseparate model ID;
- implementation version/revision;
- weight provenance;
- expected hash resolved during implementation;
- input sample-rate requirements;
- supported frequency behavior;
- output score semantics;
- code/weight license evidence;
- required notices.

Do not infer weight licensing from wrapper licensing.

### 8.3 Inference profile

Create a versioned quality profile containing:

- model size `full`;
- requested pitch range where supported;
- native hop/batch settings;
- decoder choice exposed by the implementation, if applicable;
- padding/centering semantics;
- filtering behavior;
- precision;
- device/batch policy.

### 8.4 Bounded execution

1. Load the registered local model.
2. Process bounded batches/windows.
3. Preserve enough context to avoid artificial edge changes.
4. Collect native F0 estimates.
5. Collect periodicity or equivalent model score.
6. Preserve native frame positions/order.
7. Validate dimensions and finite values.
8. Map each native frame to project source time.
9. Write staged binary arrays incrementally where practical.
10. Publish only after complete validation.

### 8.5 Silence caveat

The main plan explicitly notes that silence can yield misleadingly strong neural pitch predictions.

Therefore:

- torchcrepe periodicity cannot by itself define voiced state;
- low-energy/silence evidence must be consulted;
- isolated strong periodicity in silent/near-silent regions is flagged;
- no UI score is labelled `pitch correctness probability` unless separately calibrated.

### 8.6 Range-limited behavior

Ordinary torchcrepe does not cover the entire requested low-bass range reliably according to the main plan's design assumption.

Consequences:

- do not force a neural result for frames below its validated range;
- preserve pYIN and auxiliary candidates;
- expose which estimator contributed each fused frame;
- evaluate low-B separately.

### 8.7 Device batching and OOM recovery

1. Start with a validated batch profile.
2. Record requested and effective batch size.
3. On GPU OOM, stop the worker/release resources.
4. Retry with a smaller validated batch profile at most a bounded number of times.
5. Record effective parameters and distinct cache identity if numerical behavior can change.
6. Do not mix array segments produced under incompatible undocumented profiles.
7. Offer another device or CPU explicitly after bounded failure.

### 8.8 Determinism

Record any sources of nondeterminism.

Where practical:

- use deterministic evaluation mode;
- disable training behavior;
- keep random seeds fixed if random behavior exists;
- measure repeatability tolerance rather than promising bit identity across GPUs.

### 8.9 Tests

Test at least:

- E1/A1/D2/G2 reference tones;
- upper bass register;
- B0/very-low input to characterize limitation;
- silence;
- low-level noise;
- distorted/synth-like tones;
- vibrato;
- slides;
- repeated attacks;
- CPU/GPU result tolerance.

**Acceptance:** torchcrepe full runs locally with preserved source-aligned F0/periodicity evidence, bounded resource use, explicit low-register limitations, and no silence-as-confidence shortcut.

---

## 9. Work package M5.7 — Implement the low-register auxiliary neural path

### 9.1 Purpose

Provide additional neural evidence for notes whose fundamental frequency is below ordinary torchcrepe's useful range, especially low B and lower drop tunings.

This is an engineering adaptation proposed by the main plan, not a claimed upstream guarantee.

### 9.2 Transform definition

Create an analysis-only factor-2 time-compressed representation:

- source duration becomes approximately one half;
- frequencies become approximately two times higher;
- timestamps map back by multiplying auxiliary time by two;
- predicted frequency maps back by dividing by two.

The transform must be represented as an exact rational time mapping where possible rather than inferred from nominal duration.

### 9.3 Audio-generation method

Use a deterministic resampling/time-compression operation that changes both duration and pitch together.

Do not use pitch-preserving time stretching for this auxiliary path; preserving pitch would defeat the purpose.

Record:

- source asset hash;
- transform ratio `2:1`;
- resampler/version profile;
- output sample rate representation;
- output frame count;
- exact endpoint mapping.

### 9.4 Mapping formulas

For an auxiliary estimate at transformed frequency `f_aux` and transformed time/frame position `t_aux`:

```text
f_source = f_aux / 2
source_time = t_aux * 2
```

Implement the mapping using integer/rational frame relationships before final source-frame rounding.

### 9.5 Valid range

Only use auxiliary predictions in the source-frequency region where:

- transformed frequencies fall inside the validated neural estimator range;
- the mapped source frequency is inside the configured bass range;
- transform-edge context is valid.

Do not let the auxiliary path override higher-register direct neural evidence merely because it exists.

### 9.6 Source-time alignment validation

Use synthetic tones and impulses to verify:

1. transformed onset maps back to the original onset;
2. transformed offset maps back to the original offset;
3. steady F0 halves back correctly;
4. slides preserve trajectory direction and timing;
5. endpoint rounding does not accumulate drift.

### 9.7 Auxiliary artifact

Store:

- transformed-input asset/transform key;
- native torchcrepe auxiliary F0;
- periodicity/score;
- native auxiliary frame positions;
- mapped source-frame positions;
- mapped source F0;
- transform profile/version.

### 9.8 Evaluation requirement

Before treating the auxiliary path as useful:

- compare low-register pitch accuracy with and without it;
- measure octave-error rate;
- test B0 and lower drop-tuning examples;
- test higher-register false overrides;
- test attacks/slides after mapping;
- retain an option/profile that disables it if measurements show regression.

**Acceptance:** the auxiliary path maps frequency and time back correctly, improves or at least provides independently inspectable evidence in the target low register, and is never presented as guaranteed superior without measured validation.

---

## 10. Work package M5.8 — Preserve and serve framewise pitch-analysis artifacts

### 10.1 Artifact families

Maintain at least these immutable artifact families:

1. Prepared mono analysis representation metadata.
2. pYIN native pitch/voicing arrays.
3. Direct torchcrepe native pitch/periodicity arrays.
4. Auxiliary torchcrepe native and mapped arrays.
5. Energy/envelope feature arrays.
6. Spectral-flux/onset feature arrays.
7. Canonical fused pitch-evidence timeline.
8. Optional contour/gesture derived artifact.

### 10.2 Binary format principles

For every framewise artifact:

- use fixed typed arrays or another documented binary representation;
- store version, dtype, dimensions, and byte order;
- keep a compact JSON manifest;
- hash complete immutable bytes;
- support bounded range access;
- reject truncated/mismatched arrays;
- avoid per-frame JSON.

### 10.3 Canonical fused grid

Use an approximately 10 ms target evidence hop from the main plan, but represent grid positions as exact project-frame mappings.

For source sample rate `R`, do not assume `0.010 * R` is always an integer without defining the mapping/rounding policy.

Recommended implementation:

- define target analysis timestamps as rational seconds or source-frame phase accumulation;
- map each target center to nearest valid project frame using one documented rule;
- avoid cumulative rounding drift;
- retain native estimator positions separately.

### 10.4 Resampling estimator evidence onto fused grid

For each fused target frame:

- locate neighboring native estimator frames in source time;
- use estimator-appropriate interpolation only for continuous F0/score evidence;
- do not interpolate across large unvoiced gaps as though pitch were continuous;
- preserve missing evidence explicitly;
- retain the chosen native-neighbor indices for diagnostics where useful.

### 10.5 API range access

Add bounded endpoints or extend the existing analysis-artifact API so the browser can request:

- manifest/metadata;
- source-frame range;
- requested evidence fields/layers;
- decimated data for overview views where needed.

Do not send full-track frame arrays to the browser by default.

### 10.6 Decimation for display

At low horizontal zoom:

- aggregate voiced density;
- F0 min/max or robust envelope;
- confidence/periodicity range;
- ambiguity count;
- onset maximum;
- note-event boundaries.

At close zoom:

- return individual fused/native frames.

Display decimation must not replace authoritative stored evidence.

### 10.7 Corruption recovery

If a rebuildable evidence artifact is missing/corrupt:

- keep decoded note results if their stored event data remains valid;
- label diagnostic pitch view unavailable/rebuildable;
- do not automatically run a model on project open;
- allow explicit re-analysis when the model/runtime is available.

**Acceptance:** framewise evidence can be inspected over long recordings with bounded browser/network memory and without inflating project JSON.

---
## 11. Work package M5.9 — Fuse pitch candidates and control octave errors

### 11.1 Purpose

Create one source-aligned F0 evidence sequence from multiple estimators without erasing disagreement.

The fusion stage is deterministic for a fixed input artifact set, tuning context, and fusion profile.

### 11.2 Candidate set per fused frame

Potential candidates include:

- direct torchcrepe F0;
- pYIN F0;
- auxiliary-path mapped F0;
- octave-related transforms of a candidate considered only as hypotheses, not synthetic estimator outputs;
- no-voiced-pitch state.

Each candidate carries:

- frequency;
- nominal MIDI/cents under selected tuning context;
- estimator source;
- source-specific score/evidence;
- source-frame distance to native evidence;
- voicing support;
- energy/silence support;
- continuity relation to recent accepted frames.

### 11.3 Agreement scoring

Compute pairwise agreement in cents for simultaneously available candidates.

Classify evidence such as:

- close agreement;
- near-octave disagreement;
- other large disagreement;
- single-estimator evidence;
- no usable candidate.

Do not average frequencies from candidates separated by approximately an octave.

### 11.4 Octave hypotheses

For a candidate frequency `f`, compare plausible octave relatives within the configured bass range:

- `f/2`;
- `f`;
- `2f`.

Use octave hypotheses only for scoring consistency across estimators and time.

Do not manufacture confidence by duplicating one estimator into three candidates.

### 11.5 Fusion evidence

Initial fusion may consider:

1. Direct torchcrepe periodicity/score.
2. pYIN voiced probability/flag.
3. Auxiliary neural score.
4. Agreement between independent estimators.
5. Energy/silence state.
6. Temporal continuity.
7. Expected bass-range limits.
8. Attack proximity, used carefully because a real new note can legitimately jump.

Every term and weight/threshold belongs to a named versioned fusion profile.

### 11.6 Continuity is a soft preference

The main plan requires continuity as a soft preference.

Therefore:

- continuity can break a tie between plausible candidates;
- continuity can discourage isolated octave flips;
- continuity cannot suppress a strongly supported new attacked note simply because it is far from the preceding pitch;
- continuity penalties reset or relax across unvoiced gaps and strong attacks.

### 11.7 Candidate-state decoder

Implement fusion as a local-scoring plus temporal-decoding problem rather than a sequence of irreversible if-statements where practical.

Candidate states per frame may include:

- unvoiced;
- candidate A;
- candidate B;
- candidate C;
- ambiguous.

Transitions encode soft costs for:

- large unsupported jumps;
- octave flips without attack evidence;
- brief voiced islands inside silence;
- brief unvoiced holes inside sustained evidence;
- switching estimator source when pitch remains equivalent.

Keep the actual score design transparent and versioned.

### 11.8 Ambiguity preservation

If top candidates remain too close in support:

- preserve the selected best hypothesis for downstream decoding if needed;
- set ambiguity flag;
- retain alternatives and score margin;
- lower note-level confidence later;
- expose the disagreement in the inspector.

### 11.9 Tuning-aware interpretation

Convert candidate F0 to continuous semitone/MIDI coordinates under the selected tuning convention.

Store:

- nearest nominal MIDI note;
- signed cents deviation;
- raw F0.

Do not quantize the fused F0 itself to the note center.

### 11.10 Boundary/range policy

Near the configured 25–800 Hz analysis limits:

- preserve valid estimator evidence;
- flag range-edge conditions;
- do not clip an out-of-range F0 to exactly 25 or 800 Hz;
- allow decoder to mark unknown when evidence lies outside supported range.

### 11.11 Fusion diagnostics

Per frame or aggregated segments, preserve reason codes such as:

- `estimators_agree`;
- `direct_aux_octave_conflict`;
- `pyin_neural_disagree`;
- `silence_override`;
- `continuity_preference`;
- `attack_allows_jump`;
- `single_estimator_only`;
- `ambiguous`.

Reason codes are diagnostics, not user-facing promises of correctness.

### 11.12 Tests

Construct fixtures for:

- stable low B;
- octave-error alternation;
- harmonic-dominant bass tone where second harmonic is stronger;
- sudden octave jump with real attack;
- slide over one octave;
- silence gap followed by a distant note;
- two estimators agreeing while the third disagrees;
- direct neural unavailable below range but pYIN+aux agree.

**Acceptance:** fused F0 reduces isolated octave errors without suppressing real attacked jumps, and all estimator disagreement remains inspectable.

---

## 12. Work package M5.10 — Implement silence detection and voicing hysteresis

### 12.1 Purpose

Prevent pitch estimators from turning silence/noise into fake notes and prevent unstable voiced/unvoiced flicker from fragmenting sustained bass notes.

### 12.2 Independent energy evidence

Compute a source-aligned amplitude/energy feature using bounded processing.

Retain at least:

- local RMS or equivalent energy;
- optional peak/envelope;
- robust long-term reference/noise-floor statistics where useful;
- source-frame mapping;
- feature-profile version.

### 12.3 Silence classification

Silence/near-silence classification must not rely on one global absolute threshold for all recordings.

Use a documented profile combining, as appropriate:

- absolute floor guard;
- relative local energy;
- robust track/region statistics;
- estimator voicing evidence.

Resolve actual threshold values through validation corpus tuning and commit them as profile parameters.

### 12.4 Voicing states

Use at least:

- `unvoiced`;
- `voiced`;
- `ambiguous`.

Optional internal states may include `entering_voiced`/`leaving_voiced` for hysteresis, but persisted semantics should remain simple and explicit.

### 12.5 Hysteresis

Require stronger or sustained evidence to enter voiced state than to remain voiced, and similarly avoid dropping out on one weak frame.

The profile may include:

- entry score/energy conditions;
- exit conditions;
- minimum voiced-run evidence;
- maximum bridgeable weak-evidence gap;
- attack-based entry assistance;
- release-based exit assistance.

Do not use hysteresis to bridge a clearly silent multi-note gap.

### 12.6 Silence versus muted fundamental

A low-energy fundamental can still be musically audible through harmonics.

Therefore energy is not a hard veto unless the signal is genuinely near the validated silence floor.

Estimator agreement and spectral evidence may sustain voiced state above near-silence.

### 12.7 No zero-Hz pitch convention

Represent unvoiced F0 as null/masked, not `0 Hz`.

This prevents logarithmic pitch conversion errors and semantic confusion.

### 12.8 Long silence

For long unvoiced intervals:

- permit sparse run-length/region summaries for display;
- keep fused-grid mask representation as needed;
- do not create unknown note events unless there is an actual ambiguous sounding event requiring review.

### 12.9 Tests

Test:

- digital silence;
- background noise only;
- fade in/out;
- palm-muted notes;
- long sustain decay;
- gap between repeated notes;
- reverb tail after note release;
- distorted sustained bass;
- synth bass with low fundamental energy.

**Acceptance:** silence does not generate stable fake notes, sustained notes do not fragment from one-frame score dips, and weak real bass remains reviewable rather than hard-deleted.

---

## 13. Work package M5.11 — Detect attacks, repeated notes, and releases

### 13.1 Purpose

Provide timing evidence independent of pitch change so the decoder can separate repeated notes on the same pitch and retain meaningful articulations.

### 13.2 Feature families

Use the main plan's:

- amplitude-envelope evidence;
- spectral-flux evidence.

Additional simple derived evidence may be used when it does not expand scope, but it must be named/versioned.

### 13.3 Analysis source

Compute onset features from the selected bass analysis signal, not the full mix, unless a separately named experimental profile explicitly says otherwise.

### 13.4 Envelope feature

Calculate a smoothed amplitude/envelope timeline with:

- bounded frame processing;
- attack-sensitive rise evidence;
- release-sensitive fall evidence;
- explicit source-frame centers;
- normalization independent of playback gain.

### 13.5 Spectral flux

Compute a bass-appropriate spectral-change measure.

Record:

- FFT/window/hop profile;
- frequency weighting/range if applied;
- normalization method;
- source-time mapping.

Do not assume broadband high-frequency flux is always relevant for low bass.

### 13.6 Combined attack score

Create a versioned attack score from:

- envelope rise;
- spectral flux;
- voiced-state transition;
- abrupt F0 trajectory change;
- estimator confidence change.

Pitch change alone is not required for an attack.

### 13.7 Repeated same-pitch notes

A strong attack after a sustained/weak transition can split a note even when nominal MIDI pitch before and after is identical.

Requirements:

1. Preserve the attack candidate.
2. Look for local energy dip/release evidence when present.
3. Allow repeated plucks with little/no silence.
4. Avoid splitting every vibrato cycle or noise spike.
5. Record the split reason/evidence.

### 13.8 Release evidence

Detect potential note release from:

- energy decay/drop;
- voiced-to-unvoiced transition;
- loss of consistent F0;
- next attack.

Do not place offset solely at the next onset if the previous note clearly ended earlier.

### 13.9 Candidate timing precision

Keep attack/release candidate positions in source frames.

If feature hops are coarse, optionally refine boundaries using nearby higher-resolution envelope samples without inventing sub-source-sample precision.

### 13.10 Minimum event policy

Do not hard-code a musically arbitrary minimum note duration without evaluation.

Use profile parameters to suppress obvious one-frame glitches while preserving short real notes in fast bass passages.

### 13.11 Tests

Include:

- repeated eighth/sixteenth notes on one pitch;
- legato same-string transition;
- ghost-like low-energy attack;
- slap/pop transient followed by stable pitch;
- soft fingerstyle attacks;
- sustained note with vibrato;
- note ending into reverb/noise;
- two notes separated by a tiny gap.

**Acceptance:** same-pitch repeated attacks are detectable without exploding sustained notes into false fragments, and onset/release evidence remains independently inspectable.

---

## 14. Work package M5.12 — Decode discrete bass-note events

### 14.1 Decoder objective

Convert fused framewise evidence into musically useful monophonic note events while preserving continuous pitch variation and ambiguity.

### 14.2 Decoder inputs

Default decoder consumes only declared bass-analysis artifacts:

- fused F0 timeline;
- voiced/unvoiced state;
- estimator alternatives/conflicts;
- attack score/candidates;
- energy/envelope;
- release evidence;
- tuning context/profile.

Rhythm/chord/key are not default decoder inputs.

### 14.3 Initial event formation

1. Find voiced runs after hysteresis.
2. Break runs at sufficiently supported attacks.
3. Identify stable/continuous pitch regions.
4. Estimate nominal MIDI pitch robustly from the event trajectory.
5. Preserve raw/fused trajectory separately.
6. Determine onset and release boundaries.
7. Compute note-level evidence summaries.
8. Classify ambiguous/polyphonic/problematic events.

### 14.4 Nominal pitch estimation

Use robust statistics over stable parts of the event rather than the first frame alone.

Exclude or downweight as appropriate:

- onset transients;
- clearly unvoiced frames;
- slide transition portions when destination/source identity is being determined;
- isolated octave-conflict frames.

Keep the chosen method/version in the decoder profile.

### 14.5 New-note decision

Create a new discrete note when evidence supports one or more of:

- a strong attack;
- a meaningful unvoiced/release gap;
- a stable transition to a new pitch with articulation evidence;
- a slide that resolves into a distinctly re-attacked or newly stable note according to profile rules.

Do not create a new note solely because continuous F0 crosses the midpoint between semitones during a bend.

### 14.6 Repeated pitch

Permit consecutive note events with the same MIDI pitch when an attack/release split is supported.

Never auto-merge adjacent equal-pitch events just because their labels match.

### 14.7 Octave correction during decoding

If a short segment flips by exactly/approximately one octave while neighboring frames and independent estimators support continuity:

- prefer the consistent octave under fusion/decoder rules;
- retain a correction diagnostic;
- do not alter raw estimator artifacts.

A sustained octave change with attack evidence remains a legitimate new note.

### 14.8 Unknown/unpitched events

If there is clear sounding/attack evidence but no stable pitch hypothesis:

- optionally create an `unknown` or `unpitched` event;
- retain time boundaries;
- preserve evidence/alternatives;
- do not invent a MIDI pitch.

This supports manual correction without losing the event timing.

### 14.9 Ambiguous/polyphonic flag

Flag passages where:

- estimators disagree persistently;
- evidence suggests more than one pitch source;
- separation leakage is strong;
- F0 alternates rapidly without plausible monophonic continuity;
- confidence margin remains poor.

The flag is a review aid, not proof of polyphony.

### 14.10 Note confidence

Derive note-level confidence as a labelled heuristic/agreement score unless independently calibrated.

Possible summary evidence:

- fraction of voiced frames;
- estimator agreement;
- periodicity/voiced evidence;
- octave-conflict rate;
- ambiguity margin;
- onset confidence;
- pitch stability appropriate to gesture class.

Do not penalize a correct slide simply for low pitch stability.

### 14.11 Event ordering and overlaps

Default automatic transcription is monophonic:

- adjacent event intervals may touch;
- active pitched events may not overlap;
- unknown/unpitched event policy is defined explicitly;
- any decoder overlap is treated as a validation failure or ambiguity requiring resolution before publication.

### 14.12 Decoder versioning

Any change to:

- thresholds;
- state transitions;
- note-pitch summarization;
- attack split logic;
- slide handling;
- octave-control policy;
- minimum-run rules;

creates a new decoder profile version and cache/result identity.

**Acceptance:** discrete notes preserve repeated attacks and genuine pitch changes while avoiding one-note-per-frame quantization and retaining ambiguous events for review.

---

## 15. Work package M5.13 — Retain and summarize slides, bends, and continuous pitch

### 15.1 Continuous contour is authoritative evidence

For every pitched event, retain access to the fused continuous F0/cents trajectory over its interval.

The note label is a summary, not a replacement for that trajectory.

### 15.2 Gesture categories

Initial summary categories:

- stable;
- bend;
- slide;
- vibrato-like modulation;
- uncertain.

These are engineering/editor categories, not a promise of complete performance-technique recognition.

### 15.3 Bend representation

For a bend-like gesture store, as applicable:

- start/end frame;
- baseline nominal note;
- signed cents trajectory summary;
- maximum upward/downward deviation;
- optional target cents/pitch if stable;
- confidence/review state.

### 15.4 Slide representation

For a slide-like gesture store, as applicable:

- source note/event ID;
- gesture start/end within event or across linked transition;
- source nominal pitch;
- destination pitch hypothesis if resolved;
- direction;
- continuous contour reference;
- whether a new attack occurs at destination.

Do not force every slide into two discrete notes if no clear second attack/stable event exists.

### 15.5 Vibrato handling

Small periodic modulation around one nominal pitch should generally remain inside one note.

Do not segment on repeated semitone-boundary crossings caused by wide vibrato unless independent attack evidence exists.

### 15.6 Slide versus note transition

Use multiple cues:

- continuous trajectory without unvoiced gap;
- attack evidence at destination;
- local F0 derivative/smoothness;
- duration/stability before and after transition.

Keep ambiguous cases reviewable.

### 15.7 Gesture editing

The note inspector/editor supports:

- mark/remove slide;
- mark/remove bend;
- adjust gesture start/end within valid note interval;
- edit destination/extent metadata;
- reset to automatic gesture evidence;
- view underlying contour.

Edits do not rewrite the raw F0 artifact.

### 15.8 MIDI implication

Bass MIDI export should preserve ordinary note events first.

Pitch-bend MIDI data may be exported only when the chosen export profile defines:

- pitch-bend range;
- mapping from cents contour to MIDI bend values;
- channel behavior;
- reset semantics.

If robust pitch-bend export is not implemented in this milestone, retain slide/bend in the project but export discrete notes with a clear limitation. Do not silently encode incorrect bends.

### 15.9 Tests

Include:

- half-step slide;
- multi-semitone slide;
- upward/downward bend;
- wide vibrato;
- legato transition without re-attack;
- slide followed by clear destination attack;
- synth portamento;
- estimator octave glitch inside a slide.

**Acceptance:** the project retains the continuous pitch information needed to inspect and correct expressive bass gestures rather than flattening them into quantized note centers.

---
## 16. Work package M5.14 — Publish immutable automatic transcription results and editable branches

### 16.1 Publication stages

Publish progressively when safe:

1. Native estimator artifacts complete.
2. Fused evidence complete.
3. Attack/voicing evidence complete.
4. Discrete note result decoded.
5. Gesture summaries validated.
6. Complete transcription result atomically attached to the project.

The UI may display diagnostic pitch evidence before final note decoding, but it must label the transcription result as pending until note validation completes.

### 16.2 Atomic automatic result publication

Before marking a result complete:

- validate all required artifact hashes;
- validate note-event intervals;
- validate monophonic overlap rules;
- verify referenced bass stem and selected bass-stem tuning result/project tuning context still exist;
- commit result metadata and project references transactionally;
- only then expose the result as selectable.

### 16.3 First edit creates branch

When the user first changes an automatic note result:

1. Create an editable branch referencing the immutable automatic parent.
2. Copy or overlay note/gesture state.
3. Apply the semantic edit in the same transaction.
4. Increment project and branch revision.
5. Preserve automatic confidence/provenance.
6. Set human review/correction state separately.

### 16.4 Auto/Edited switching

Provide a practical selector for:

- Auto;
- Edited, when a branch exists.

Switching active transcription source:

- is an undoable project-state command if earlier command infrastructure supports it;
- updates overlay, text lane, readout, linked selection, and MIDI export consistently;
- does not alter source/stem audio;
- does not rewrite chords, key, or rhythm.

### 16.5 Rerunning transcription

A rerun:

- creates a new immutable result;
- does not overwrite earlier automatic results;
- does not merge new notes into an existing edited branch automatically;
- keeps branches tied to their original parent result;
- may reuse compatible raw estimator artifacts based on cache identity;
- permits explicit creation of a new edited branch from the new result.

### 16.6 Result selector metadata

Show enough provenance to distinguish versions:

- source bass stem/separation model;
- transcription profile/version;
- selected tuning interpretation and bass-stem tuning-result identity where applicable;
- creation date;
- device if useful diagnostically;
- warning status;
- Auto/Edited availability.

### 16.7 Stale state

If a declared upstream dependency changes:

- keep old transcription available;
- mark it stale relative to current upstream selection;
- do not silently replace it;
- allow viewing/export with an explicit stale warning;
- offer rerun/redecode using the new dependency set.

**Acceptance:** automatic output remains immutable, manual corrections survive reruns, and the active note display always corresponds to an explicit result/branch.

---

## 17. Work package M5.15 — Implement pitch-analysis diagnostic views

### 17.1 Purpose

Provide a technical view for understanding failures and correcting notes, without requiring the user to inspect raw binary artifacts externally.

### 17.2 Available layers

Allow toggling layers such as:

- fused F0 contour;
- direct torchcrepe F0;
- pYIN F0;
- auxiliary mapped F0;
- nominal semitone centers;
- torchcrepe periodicity;
- pYIN voicing evidence;
- fused voiced/unvoiced state;
- octave-conflict markers;
- ambiguity markers;
- attack score/candidates;
- note onset/offset boundaries;
- slide/bend contour highlights.

Do not enable every layer by default.

### 17.3 Coordinate system

Use the shared project source-frame viewport.

Horizontal x mapping is identical to waveform/chord/rhythm tracks.

Vertical pitch axis supports:

- logarithmic frequency representation;
- note/MIDI-oriented labeling;
- user-visible note names;
- optional cents-grid detail at high zoom.

### 17.4 Vertical range

Default to a bass-focused view covering the configured analysis range, with controls to fit visible evidence or use fixed pitch range.

Do not crop evidence silently when outside the default range; indicate out-of-view/out-of-range data.

### 17.5 Decimation

At overview zoom:

- request aggregated pitch envelopes/density;
- render note events more prominently than individual 10 ms frames.

At close zoom:

- show individual evidence samples/contour points as useful.

### 17.6 Confidence visualization

Use shape/opacity/hatching/text in addition to color.

Examples:

- dashed contour where ambiguity is high;
- gap for unvoiced/null F0;
- explicit octave-conflict marker;
- tooltip naming estimator and score type.

### 17.7 Inspector interaction

Hover/selecting evidence can show:

- exact source time/frame;
- F0;
- nearest MIDI note;
- cents deviation;
- estimator source;
- native score/periodicity/voicing evidence;
- alternatives;
- fusion reason code.

Diagnostic evidence itself is not directly edited; edits target note events/gestures.

### 17.8 Performance

- tile/range request evidence;
- cancel obsolete requests after navigation;
- keep a byte-bounded cache;
- avoid React re-rendering for every frame;
- draw dense contours on Canvas rather than thousands of DOM nodes.

**Acceptance:** users can inspect why a note was decoded incorrectly without loading the whole track's framewise evidence into the browser.

---

## 18. Work package M5.16 — Display bass notes above the waveform

### 18.1 Note overlay

Add a bass-note overlay aligned to the selected bass waveform track.

Each note region shows, depending on zoom:

- start/end boundary;
- note name;
- optional cents summary;
- review/confidence state;
- gesture indicator;
- selected/related state.

### 18.2 Layout

Place note blocks above the waveform or in a tightly coupled overlay lane so they do not obscure waveform amplitude excessively.

All positioning derives from shared source-frame transform.

### 18.3 Zoom-dependent labels

At overview:

- prioritize note blocks/boundaries;
- suppress overlapping text labels.

At closer zoom:

- show note names;
- show cents/gesture badges;
- show editable handles.

### 18.4 Ambiguous/unknown event rendering

Use explicit labels/icons/patterns for:

- unknown pitch;
- unpitched event;
- ambiguous/polyphonic flag;
- stale result.

Do not display unknown as a normal note name.

### 18.5 Gesture rendering

For bend/slide:

- optionally draw compact contour/arrow inside or above event;
- never imply exact notation that was not decoded;
- tooltip opens contour evidence.

### 18.6 Boundary handles

When an editable note is selected:

- show start/end handles;
- use source-frame boundaries;
- obey monophonic neighbor constraints;
- support snapping modes from the shared editor when enabled;
- preview boundary movement without committing until gesture completion.

### 18.7 Hit testing

At overlapping visual positions, hit-test by:

- visible event geometry;
- selected branch/version only;
- explicit z-order for handles versus body.

Related context highlights must not intercept note-edit gestures.

### 18.8 Playhead relationship

The active note at the playhead is determined from the selected active transcription branch/result and latency-compensated source position.

**Acceptance:** notes stay aligned with the bass waveform under all zoom/pan states and provide a precise editable source-time representation.

---

## 19. Work package M5.17 — Add the synchronized note-text lane below the waveform

### 19.1 Purpose

Implement the second requested note view: synchronized note text below the bass waveform.

This is not a separate transcription dataset. It renders the same active note IDs as the overlay.

### 19.2 Lane contents

For each visible note, display as space permits:

- scientific pitch name;
- optional cents deviation;
- optional duration at close zoom;
- confidence/review indicator;
- gesture marker;
- unknown/unpitched label.

### 19.3 Horizontal alignment

Each text item's horizontal extent follows the note's source-frame interval.

Selection, boundary edits, and playhead active state are shared with the overlay.

### 19.4 Dense passages

When note labels would overlap:

- truncate or hide secondary metadata first;
- keep event boundaries/selection affordances usable;
- use tooltip/inspector for full text;
- do not shift labels horizontally away from their note intervals in a way that breaks timing interpretation.

### 19.5 Keyboard/focus behavior

The text lane must support keyboard navigation between notes without turning every rendered note into an uncontrolled focus-performance problem.

Use a managed focus/selection model and only render accessible text for visible events.

### 19.6 Shared IDs

Selecting note `N` in the text lane selects the exact same object `N` in:

- overlay;
- inspector;
- linked waveform highlight;
- readout;
- confidence-review navigator.

### 19.7 Source/display spelling

The text lane uses the same note-spelling service as the overlay.

Changing display spelling does not duplicate or mutate note events.

**Acceptance:** the below-waveform text lane and above-waveform overlay remain perfectly synchronized because they are two views of the same event objects.

---

## 20. Work package M5.18 — Implement the bass-note editor

### 20.1 Editing principles

Every semantic edit:

- targets the active editable branch;
- includes base project/branch revision;
- has an idempotency key;
- validates against source bounds/monophonic rules;
- becomes one undoable command/transaction;
- preserves parent automatic evidence.

### 20.2 Select note

Clicking a note selects it without seeking by default, consistent with the project-wide selection model.

Provide explicit audition/seek actions separately.

### 20.3 Move start boundary

1. Begin drag from start handle.
2. Preview source-frame candidate.
3. Apply snap if enabled.
4. Clamp to source bounds.
5. Prevent crossing the note end.
6. In monophonic mode, prevent invalid overlap with prior note according to branch policy.
7. Commit one command on release.

### 20.4 Move end boundary

Apply symmetric validation against note start and following event.

Do not move a neighboring boundary automatically unless the user invokes a specific shared-boundary action.

### 20.5 Change pitch

Support:

- direct note-name/MIDI entry;
- +1/-1 semitone;
- +12/-12 semitone octave correction;
- optional cents/tuning summary override only where semantically clear.

Changing nominal pitch does not rewrite the underlying automatic contour.

### 20.6 Insert note

Insert requires:

- valid source interval;
- pitched/unknown/unpitched type;
- optional nominal pitch;
- monophonic overlap validation.

New manual notes have manual provenance and unavailable model confidence, while retaining human review state.

### 20.7 Delete note

Deleting from edited branch:

- removes/hides branch event;
- does not delete automatic parent event;
- is undoable.

### 20.8 Split note

Split at explicit source position/playhead:

- create two branch events;
- preserve nominal pitch by default on both;
- split contour/gesture references logically at boundary;
- clear/recompute gesture summaries crossing the split as needed;
- preserve parent provenance links.

### 20.9 Merge notes

Merge adjacent/compatible selected notes:

- new interval spans earliest start to latest end;
- reject intervening conflicting note in monophonic mode;
- choose nominal pitch explicitly when labels differ, rather than silently guessing;
- for equal-pitch notes, retain that pitch by default;
- combine contour references over merged interval;
- mark gesture summary for recomputation/manual review.

### 20.10 Correct octave error

Provide dedicated octave up/down actions.

These modify nominal pitch by 12 semitones and preserve timing.

Inspector continues to show automatic F0/alternative evidence so the correction remains auditable.

### 20.11 Unknown/unpitched

Allow conversion to:

- unknown pitched event;
- unpitched event;
- normal pitched note.

Do not use special fake MIDI values.

### 20.12 Slide/bend editing

Support:

- set/clear gesture type;
- adjust gesture interval within note/event transition;
- adjust target/extent metadata;
- reset to automatic summary;
- inspect continuous contour.

### 20.13 Audition

Provide `Audition note` action:

- seek to small pre-roll before note start when available;
- play bass stem or selected practice group according to chosen audition mode;
- stop at note end plus optional small tail;
- do not alter saved loop unless explicitly requested.

### 20.14 Mark reviewed

Review states follow shared schema:

- unreviewed;
- accepted;
- corrected.

Accepting an automatic note does not change its model confidence.

### 20.15 Monophonic overlap mode

Default edited branch enforces monophonic pitched events.

If explicit overlapping-note representation is enabled:

- make the mode visible;
- define hit-testing/rendering;
- allow overlaps intentionally;
- do not imply the automatic pipeline is truly polyphonic.

### 20.16 Batch operations

Permit carefully scoped batch actions such as:

- octave shift selected notes;
- mark selected reviewed;
- delete selected notes.

Group as one transaction and one undo step.

### 20.17 Validation errors

Return specific errors for:

- stale revision;
- missing note;
- invalid interval;
- boundary crossing;
- overlap violation;
- invalid MIDI pitch;
- invalid gesture interval;
- attempt to edit immutable automatic result directly.

**Acceptance:** every note-edit operation in the main plan is available, undoable, source-time precise, and does not destroy automatic evidence.

---

## 21. Work package M5.19 — Integrate linked selection, snapping, inspector, and musical readout

### 21.1 Shared selection extension

Extend the existing selection model so a selected bass note contributes:

- selected note ID(s);
- source-time range;
- focused bass track/lane;
- selection origin;
- related intersecting chord IDs;
- related key region;
- related rhythm bar/beat context;
- related waveform/stem range.

### 21.2 Selection behavior

Selecting a bass note:

- highlights its waveform interval;
- highlights related chord/key/bar context as related objects;
- does not convert those related objects into edit targets;
- updates inspector/readout.

Selecting a chord/bar/waveform range highlights intersecting bass notes as related selection.

### 21.3 Inspector fields

For selected note show:

- source start/end/duration;
- note name/MIDI pitch;
- representative F0;
- cents deviation;
- selected tuning interpretation, including bass-stem estimate provenance when applicable;
- automatic confidence/evidence type;
- estimator agreement summary;
- octave-conflict status;
- onset/release evidence;
- ambiguity/polyphony flags;
- slide/bend summary;
- parent automatic value when edited;
- review state;
- parent bass stem/separation result;
- active chord/key/bar context.

### 21.4 Snapping

Reuse project snap modes:

- Off;
- Beat;
- Half-beat;
- Quarter-beat;
- Bar;
- Nearest event boundary.

For note boundary edits, snapping applies only during the user edit.

Correcting the rhythm grid later never moves existing source-anchored note events.

### 21.5 Event-boundary snap provider

Include bass-note starts/ends in nearest-event-boundary snapping for other compatible editor operations once the active transcription exists, without circular self-snapping during the same boundary drag.

### 21.6 Musical readout

Complete the note field in the shared readout:

```text
01:32.481 | Bar 42 Beat 3.27 | D2 | Gmaj7
```

Rules:

- use latency-compensated audible source position;
- query active Auto/Edited transcription;
- show active note name when one contains the position;
- show `unknown` for an unknown event;
- show dash when no note is active/unavailable;
- use current selected chord/grid context independently.

### 21.7 Multi-note edge cases

If overlapping-note mode is enabled and several notes cover the playhead:

- show a compact multi-note readout or primary + count;
- do not arbitrarily hide the condition.

### 21.8 Review navigation

Implement next/previous uncertain bass-note navigation using configurable module threshold and/or ambiguity flags.

Navigation:

- selects the note;
- brings it into view;
- does not automatically seek/play unless configured explicitly.

**Acceptance:** bass-note selection is fully integrated with waveform, harmony, rhythm, inspector, snapping, and the shared musical readout without coupling their edit semantics.

---

## 22. Work package M5.20 — Add bass MIDI export

### 22.1 Export source

User explicitly chooses:

- active Auto transcription;
- active Edited branch;
- another retained transcription version if the selector supports it.

The export records/embeds provenance where practical in side metadata or project log.

### 22.2 Timing source

Bass notes are stored in source frames, while Standard MIDI Files use ticks in musical time.

When a valid active tempo map exists:

1. Map note start/end source frames to musical quarter-note positions through the selected rhythm branch/result.
2. Convert exact/rational musical positions to MIDI ticks at a chosen PPQN.
3. Export tempo events needed to preserve source-time correspondence.
4. Export meter events where representable/useful.
5. Preserve note order and minimum positive duration after tick rounding.

### 22.3 No valid grid fallback

When no valid musical grid exists, do not invent a fixed BPM without disclosure.

Provide a documented fallback profile, for example:

- create a constant-tempo MIDI timeline chosen only as a transport mapping convention;
- map source seconds to ticks under that declared tempo;
- include a warning/metadata that the MIDI musical timing is not a detected beat grid.

The exact fallback tempo convention must be explicit and stable in implementation documentation.

### 22.4 MIDI note mapping

For each pitched event:

- use nominal MIDI pitch;
- choose velocity from a documented profile (fixed default or derived from attack/energy only if defined/tested);
- preserve source order;
- omit unknown/unpitched events or encode only under an explicitly supported percussion/marker profile.

Do not invent pitched notes for unknown events.

### 22.5 Note-off behavior

Ensure:

- end tick > start tick;
- adjacent same-pitch notes have valid note-off/note-on ordering;
- repeated notes remain distinct;
- no stuck notes at EOF.

### 22.6 Pitch bends

If pitch-bend export is implemented:

1. Choose an explicit bend range.
2. Emit setup/controller data needed for that range where appropriate.
3. Convert retained cents contour to bend values.
4. Reset bend at safe note transitions.
5. Test repeated notes and overlapping mode carefully.

If not implemented robustly, export discrete nominal notes only and state that bends/slides remain in the `.basseparate` project but are not represented in this MIDI profile.

### 22.7 Tuning context

Nominal MIDI note numbers remain standard semitone identities.

If the source is globally detuned, do not shift every MIDI note number simply to mimic tuning offset.

Optional pitch-bend/tuning metadata may represent detuning only under a documented export profile.

### 22.8 File validation

After export:

- reopen/parse generated MIDI in tests;
- verify note count/pitches;
- verify tick ordering;
- verify source-time round-trip within tolerance through exported tempo map;
- verify repeated notes;
- verify EOF note-off;
- verify Auto versus Edited selection.

### 22.9 Export job behavior

Use existing export/publication conventions:

- write staging file;
- validate;
- flush/close;
- atomically publish;
- report final path;
- preserve previous successful export on failure.

**Acceptance:** corrected bass-note timing/pitches export reproducibly to MIDI, with variable-tempo mapping when available and no hidden invented beat grid when it is not.

---
## 23. Work package M5.21 — Add Basic Pitch as an optional note-event comparison adapter

### 23.1 Scope

The main project plan calls for Basic Pitch as an optional comparison for note events, while explicitly stating that it must not be the sole low-bass solution because its published frequency bounds do not cover the full requested range.

Treat it as a comparison/challenger path, not part of the required default fusion pipeline.

### 23.2 Adapter boundary

If integrated in Milestone 5:

- run it in an isolated compatible environment if dependencies conflict;
- register exact implementation/model identity and license records;
- preserve its native note/event outputs;
- map all times to project source frames;
- record its supported frequency range;
- never silently fill unsupported low-register notes from its absence.

### 23.3 Result semantics

Store a Basic Pitch comparison result independently from the primary hybrid transcription.

Do not merge it into the default automatic result unless a future named fusion profile explicitly declares that dependency.

### 23.4 Comparison metrics

Compare against the primary decoder on:

- note onset F-measure;
- onset-plus-offset F-measure;
- octave-error rate;
- low-B/drop-tuning subset;
- repeated same-pitch notes;
- slides/bends where event representation permits comparison;
- runtime/memory.

### 23.5 UI boundary

A minimal result selector/provenance panel is sufficient.

A full multi-transcription visual comparison interface remains later workflow scope.

### 23.6 Promotion rule

Do not promote Basic Pitch to default solely because it performs well on mid-register examples.

Any promotion must pass the full bass evaluation corpus, including the low-register subsets that motivated the hybrid design.

**Acceptance:** Basic Pitch can be evaluated as an optional independent note-event challenger without weakening or obscuring the default low-bass-capable pipeline.

---

## 24. Work package M5.22 — Extend local API, commands, jobs, and WebSocket events

### 24.1 Module/run APIs

Extend existing analysis interfaces rather than creating a second bass-specific transport protocol.

Support actions equivalent to:

- list bass-transcription module capability;
- inspect required/installed pitch model state;
- create a bass-transcription run for a selected project/stem/tuning interpretation, running/reusing bass-stem tuning estimation when the default profile requests it;
- get run/job status;
- cancel run;
- list retained transcription results;
- select active result/branch;
- create/edit branch through project commands;
- request bounded evidence ranges;
- export MIDI.

### 24.2 Run request

A run request includes:

- project ID;
- base project revision when required for selection state;
- selected separation result/bass stem ID;
- selected tuning interpretation kind and referenced bass-stem tuning-result/project-context ID/version;
- transcription profile ID;
- requested device or device preference;
- optional diagnostic/estimator toggles if supported;
- idempotency key.

The backend resolves asset hashes and actual effective parameters; the browser does not supply trusted filesystem paths.

### 24.3 Validation before queueing

Validate:

1. project exists;
2. bass stem/result belongs to project;
3. stem is complete/validated;
4. requested tuning interpretation is valid, or the default policy can run/reuse a compatible bass-stem tuning estimate and fall back explicitly to project/manual tuning when needed;
5. required model is installed;
6. selected device/profile is available or request can remain queued;
7. enough disk space is plausibly available;
8. identical completed cache result is not already usable;
9. identical pending job can be coalesced.

### 24.4 Durable job graph

Represent transcription as dependent stages such as:

```text
resolve bass stem
  -> prepare mono analysis representation
  -> run/reuse bass-stem tuning estimate
  -> resolve selected tuning interpretation
  -> prepare estimator-rate representations
  -> pYIN evidence
  -> direct torchcrepe evidence
  -> low-register auxiliary evidence
  -> energy/onset evidence
  -> fusion + voicing
  -> note segmentation
  -> gesture summarization
  -> validation/publication
```

Independent CPU/GPU stages may run concurrently only when scheduler/resource policy permits and playback responsiveness remains acceptable.

### 24.5 Progressive reuse

If a run fails after completed reusable stages:

- keep published prepared representations/native estimator artifacts when valid;
- do not publish a half-decoded transcription result;
- allow retry from cached completed dependencies;
- record which stage failed.

### 24.6 Progress semantics

Report named phases:

- Resolving bass stem.
- Preparing analysis audio.
- Estimating/resolving bass-stem tuning.
- Running pYIN.
- Running neural pitch analysis.
- Running low-register auxiliary analysis.
- Computing attack/energy evidence.
- Fusing pitch candidates.
- Detecting notes.
- Detecting slides/bends.
- Validating/publishing.

Use determinate percentages only for stages with reliable denominators.

### 24.7 Cancellation

Cancellation request:

1. persists cancelling state;
2. signals active worker(s);
3. prevents later stages from being scheduled;
4. terminates app-owned subprocesses after bounded graceful timeout if needed;
5. removes only incomplete staging files;
6. leaves completed reusable artifacts and earlier results intact;
7. ends in `cancelled` state.

### 24.8 Evidence-range endpoint

A bounded pitch-evidence request specifies:

- transcription/evidence artifact ID;
- start/end source frame or start + frame count;
- requested layer set;
- desired decimation/resolution profile.

Response includes immutable artifact identity/version so the browser cannot combine bytes from different results.

### 24.9 Project commands

Add command types for:

- create edited transcription branch;
- select active transcription result;
- switch Auto/Edited source;
- insert note;
- delete note;
- move start/end;
- change pitch;
- split note;
- merge notes;
- set unknown/unpitched;
- edit gesture;
- mark reviewed;
- set overlap mode;
- bass-view state where it belongs in history.

Continuous drags coalesce into one command.

### 24.10 Error codes

Define stable application errors for cases such as:

- `BASS_STEM_REQUIRED`;
- `BASS_STEM_NOT_FOUND`;
- `BASS_STEM_INVALID`;
- `PITCH_MODEL_NOT_INSTALLED`;
- `PITCH_DEVICE_UNAVAILABLE`;
- `TRANSCRIPTION_RESULT_NOT_FOUND`;
- `TRANSCRIPTION_STALE_DEPENDENCY`;
- `NOTE_NOT_FOUND`;
- `NOTE_OVERLAP_CONFLICT`;
- `INVALID_NOTE_INTERVAL`;
- `IMMUTABLE_RESULT_EDIT`;
- `PITCH_EVIDENCE_UNAVAILABLE`;
- `MIDI_EXPORT_GRID_UNAVAILABLE` when an export profile requires a musical grid.

Use the existing standard error envelope.

### 24.11 Events

Publish WebSocket/project events for:

- job queued/running/progress/completed/failed/cancelled;
- transcription result published;
- edited branch created/changed;
- active transcription selection changed;
- stale status changed;
- evidence artifact rebuilt/unavailable;
- MIDI export complete.

Use event IDs/recovery semantics already established by the application.

**Acceptance:** transcription uses the same durable local API/job/command architecture as other modules, with no browser-owned model execution or hidden filesystem access.

---

## 25. Work package M5.23 — Define cache identity, reuse, and dependency staleness

### 25.1 Prepared mono cache key

Include:

- bass-stem content hash;
- channel-combination profile/version;
- any resampling profile/version;
- representation format version.

### 25.2 pYIN cache key

Include:

- prepared input hash;
- librosa/pYIN implementation version;
- frequency bounds;
- frame/window/hop parameters;
- padding/centering behavior;
- threshold/probability parameters;
- adapter version.

### 25.3 Direct torchcrepe cache key

Include:

- prepared input hash;
- model/weight hash;
- implementation/adapter version;
- model size;
- input sample rate;
- hop/batch/profile parameters that affect outputs;
- precision/numerical flags where material.

Do not include device identity merely to prevent reuse unless measured/declared numerical differences require separate result identity; always record device in provenance.

### 25.4 Auxiliary cache key

Include:

- prepared input hash;
- factor-2 transform profile/version;
- resampler identity;
- torchcrepe model/weight/adapter profile;
- mapping profile.

### 25.5 Feature cache keys

Energy/onset features include:

- source analysis hash;
- feature algorithm/version;
- frame/window/hop parameters;
- normalization/weighting profile.

### 25.6 Fusion/decoder cache key

Include:

- hashes/IDs of all declared upstream evidence artifacts;
- selected tuning-interpretation identity/version, including bass-stem tuning-result ID/hash when used;
- fusion profile/version;
- voicing profile/version;
- attack profile/version;
- decoder/segmentation profile/version;
- gesture-summary profile/version.

Default rhythm/chord/key result IDs are not included because they are not decoder inputs.

### 25.7 Cache reuse rules

1. Reuse only complete validated artifacts.
2. Verify bytes/hashes when integrity is uncertain.
3. Coalesce identical concurrent requests.
4. Keep failed/cancelled staging out of cache hits.
5. Permit raw estimator reuse when only tuning-dependent decode changes.
6. Permit re-decoding without neural inference when upstream evidence remains valid.
7. Keep cache objects immutable.

### 25.8 Staleness graph

A transcription becomes stale relative to current project state when a declared dependency changes, including:

- selected bass stem/separation result;
- bass-stem bytes/hash;
- selected tuning interpretation when used by its decoder identity, including a different bass-stem tuning-result ID/version;
- decoder/profile/version change when user expects current defaults.

It does **not** become stale merely because:

- a chord label is manually corrected;
- key spelling changes for display only;
- rhythm anchors move, under the default source-time decoder;
- a waveform view changes;
- playback speed changes.

### 25.9 Derived display staleness

Note spelling may depend on active key spelling for display.

Treat a spelling refresh as display derivation, not transcription invalidation, when semantic MIDI pitch/timing is unchanged.

### 25.10 Future dependency safety

If a future named decoder uses beat/chord/key context, its manifest must declare those dependencies explicitly, causing appropriate cache/staleness behavior.

Do not change the meaning of the default Milestone 5 profile retroactively.

### 25.11 Cache eviction

Follow existing policy:

- pin artifacts referenced by working projects and retained histories;
- protect artifacts being saved/exported;
- treat model storage separately;
- evict only unreferenced rebuildable cache objects;
- preserve project-essential decoded note data inside portable save even if framewise diagnostics are optionally rebuildable according to project-save policy.

**Acceptance:** re-decoding and reruns reuse expensive pitch evidence safely, while staleness is triggered only by genuine declared dependencies.

---

## 26. Work package M5.24 — Integrate persistence, autosave, and portable projects

### 26.1 Working database

Persist:

- transcription runs;
- automatic results;
- branch metadata/revisions;
- active result/branch selection;
- editable note events/commands;
- gesture overrides;
- evidence artifact references;
- staleness/dependency records;
- bass view state.

Keep dense framewise arrays outside SQLite rows.

### 26.2 Semantic edit persistence

Every completed note edit commits atomically with:

- project revision increment;
- branch revision increment;
- command history record;
- updated note/gesture records;
- updated review state if applicable.

A crash after the transaction either retains the whole edit or none of it.

### 26.3 View persistence

Persist/debounce:

- pitch diagnostic layer visibility;
- pitch vertical range;
- note overlay visibility;
- note text-lane height;
- confidence threshold;
- last selected bass result/branch where appropriate.

Transient hover/playhead state is not persisted as semantic edit history.

### 26.4 Portable-project contents

A `.basseparate` project containing bass transcription includes, for selected/retained project state according to save policy:

- bass stem/result references and included stem asset;
- transcription result metadata;
- discrete automatic note events;
- editable branches and commands/history required for reopen;
- selected tuning-interpretation dependency and retained bass-stem tuning result(s) referenced by the project;
- estimator/fusion/decoder provenance;
- framewise evidence artifacts needed to preserve the promised diagnostic view, subject to explicit project archive policy;
- gesture/contour artifacts;
- bass view/selection settings where persisted;
- MIDI export settings only as state, not generated export unless explicitly included by generic export policy.

Do not include torchcrepe model weights.

### 26.5 Offline reopen

Opening a saved project:

1. validates manifest/schema;
2. verifies included bass/transcription assets;
3. restores automatic/edited note views;
4. restores evidence/contour diagnostic views if artifacts are included and valid;
5. restores active selection/version;
6. permits note editing;
7. permits MIDI export from saved note data;
8. does not import torchcrepe/PyTorch;
9. does not run pYIN;
10. does not contact the network.

### 26.6 Missing optional evidence

If note events exist but optional diagnostic arrays are missing/corrupt:

- open project with note events preserved;
- show diagnostics unavailable;
- identify which artifact is missing;
- allow explicit rebuild only when source/stem/model/runtime requirements are present;
- never discard manual note edits because an automatic evidence cache is missing.

### 26.7 Migration fixtures

Test portable/database migration from:

- Milestone 4 project with no transcription;
- automatic transcription only;
- edited transcription;
- multiple transcription versions;
- slide/bend edits;
- stale transcription tied to older bass separation;
- project with missing optional pitch-evidence cache.

### 26.8 Save consistency

Portable save selects one stable project revision.

If a transcription job completes while save is collecting assets:

- it belongs to a later project revision unless already committed before snapshot;
- the archive remains internally consistent;
- save does not mix branch metadata from one revision with evidence references from another.

**Acceptance:** automatic and corrected bass transcriptions reopen offline with intact timing, pitches, gesture data, provenance, and selected views, independent of model availability.

---

## 27. Work package M5.25 — Build the bass-transcription evaluation corpus

### 27.1 Corpus categories

Create versioned fixtures covering the main plan's required categories:

1. Low-B scales/arpeggios.
2. Standard EADG bass range.
3. Five-string low register.
4. Six-string/upper register where available.
5. Drop tunings below standard E.
6. Globally detuned bass.
7. Repeated same-pitch notes.
8. Fast passages.
9. Long sustains.
10. Slides up/down.
11. Bends/vibrato.
12. Synth bass.
13. Distorted/effected bass.
14. Silence/near silence.
15. Percussion leakage/no-bass regions.
16. Harmonic-dominant tones prone to octave errors.
17. Separation leakage/polyphonic ambiguity.
18. Long-form tracks for performance.

### 27.2 Synthetic/reference fixtures

Generate deterministic audio for:

- pure/complex tones at known F0;
- tones with dominant second harmonic;
- exact onset/offset times;
- repeated note sequences;
- continuous linear/exponential pitch slides;
- vibrato/bend contours;
- detuning offsets;
- silence/noise transitions.

These support exact timing/F0 assertions.

### 27.3 Recorded/labeled bass fixtures

Use licensed or project-owned material with manually annotated:

- onset;
- offset;
- nominal MIDI pitch;
- optional framewise F0/gesture references where feasible;
- tuning context.

Keep development/tuning subsets separate from final evaluation subsets.

### 27.4 Existing five tracks

Create manually annotated excerpts from the supplied project corpus for practical listening/review.

For these tracks without isolated ground-truth note events, do not claim reference-based objective accuracy unless annotations have been created specifically for that purpose.

### 27.5 End-to-end separated-bass subset

Evaluate both:

- clean/reference bass input where available;
- separated bass stems generated by the application's separation pipeline.

This distinguishes transcription-model errors from separation-induced errors.

### 27.6 Tuning subsets

Include:

- A4=440/reference-aligned material;
- known positive cents offset;
- known negative cents offset;
- sparse/low-evidence bass where `uncertain` or `no_stable_tuning` may be correct;
- slides/bends and harmonic-dominant material that should not bias the global offset;
- manually selected alternate project/manual tuning context for transcription override testing.

### 27.7 Low-register subset

Explicitly report B0 and lower drop-tuning performance separately rather than letting higher notes dominate aggregate metrics.

### 27.8 Repeated-note subset

Include same-pitch notes with:

- clear silence gap;
- no silence but clear new attack;
- soft repeated articulation;
- fast repetition.

### 27.9 Slide subset

Annotate continuous source/destination/time behavior sufficiently to assess whether:

- the event remains continuous when appropriate;
- destination attacks create new notes when appropriate;
- octave artifacts do not break the slide.

### 27.10 Corpus metadata

Record:

- source/license/provenance;
- sample rate;
- tuning;
- instrument/string count where known;
- style/technique tags;
- clean versus separated input;
- annotation method;
- evaluator split.

**Acceptance:** the evaluation corpus isolates low-register, onset, octave, voicing, repeated-note, gesture, and separation effects instead of hiding them in one average.

---

## 28. Work package M5.26 — Define quantitative accuracy and quality gates

### 28.1 Main metrics

Measure the main plan's bass metrics separately:

- voicing precision;
- voicing recall;
- pitch accuracy within 50 cents;
- octave-error rate;
- note-onset F-measure;
- note onset-plus-offset F-measure;
- repeated-note detection;
- low-B/drop-tuning subset performance;
- slide continuity;
- end-to-end error after separation.

### 28.2 Bass-stem tuning metrics

Measure the separate tuning estimator with:

- absolute cents-offset error on known-detuned fixtures;
- median/95th-percentile error across valid tuning cases;
- valid/uncertain/no-stable classification accuracy where labels exist;
- sensitivity to silence, attacks, bends/slides, harmonic dominance, and separation leakage;
- stability across excerpt versus whole-track analysis where both are tested.

Do not hide tuning-estimation error inside downstream note-pitch metrics.

### 28.3 F0 metrics

Also record useful frame-level diagnostics such as:

- gross pitch error;
- mean/median absolute cents error on correctly voiced frames;
- estimator agreement rate;
- low-register direct versus auxiliary contribution;
- voiced/unvoiced transition timing error.

Do not collapse all into one headline score.

### 28.4 Note metrics

Report note metrics under clearly stated onset/offset tolerances.

Keep at least:

- onset-only correctness;
- onset+offset correctness;
- pitch correctness;
- octave-specific error.

### 28.5 Repeated-note metric

Evaluate whether adjacent ground-truth notes of the same MIDI pitch are emitted as distinct events with appropriate onset timing.

Track:

- missed repeated attacks;
- false splits of sustained notes.

### 28.6 Slide continuity metric

Define a versioned evaluation procedure for slide fixtures, such as:

- contour coverage over annotated slide interval;
- absence of spurious octave discontinuity;
- preserved continuous event when no re-attack is annotated;
- correct new-event boundary when destination re-attack is annotated.

Do not claim a standard metric where the project defines its own engineering measure; label it clearly.

### 28.7 Low-register auxiliary ablation

Compare:

- pYIN only;
- direct torchcrepe + pYIN;
- direct + pYIN + auxiliary;
- full fusion/decoder.

Measure whether the auxiliary path improves the target subset without material regression elsewhere.

### 28.8 Fusion ablation

Measure effects of:

- continuity term;
- octave-control term;
- silence/voicing hysteresis;
- attack detection;
- repeated-note logic.

This prevents accidental improvements in one metric from masking regressions in another.

### 28.9 Confidence usefulness

For note-level confidence/review ranking:

- compare lower scores against actual error frequency on held-out labeled data;
- measure ranking/discrimination usefulness;
- leave `calibrated=false` unless true calibration is established;
- do not compare pitch confidence numerically with chord or beat confidence.

### 28.10 Practical listening/review

For the user's existing tracks:

- inspect bass separation leakage;
- inspect low notes;
- inspect note attacks;
- inspect sustained-note stability;
- inspect slides;
- inspect repeated notes;
- record qualitative issues with source timestamps.

Do not convert subjective listening into pseudo-objective percentages.

### 28.11 Release gate philosophy

Milestone 5 passes when:

- all required workflows work;
- no severe systematic low-B failure is hidden;
- repeated notes and slides are meaningfully preserved;
- automatic output is correctable;
- measured limitations are documented.

The plan does not promise a particular accuracy number before implementation measurements exist.

**Acceptance:** bass quality is measured with decomposed metrics and target subsets, not one misleading average.

---
## 29. Work package M5.27 — Validate resource use, long tracks, playback coexistence, and offline operation

### 29.1 Host-memory targets

Design for bounded memory throughout:

- chunked/memory-mapped analysis representations;
- bounded estimator batches;
- binary artifacts on disk;
- range-based browser retrieval;
- no full-track per-frame JSON;
- no simultaneous loading of all stem/evidence variants unless measurements justify it.

Record peak RAM for representative short and long tracks.

### 29.2 GPU-memory behavior

For torchcrepe:

- measure peak VRAM per batch profile;
- keep one heavy job per GPU initially;
- release worker resources after job/profile policy dictates;
- record OOM recovery attempts;
- never treat two GPUs as pooled memory.

### 29.3 CPU contention

pYIN, spectral analysis, fusion, and decoding can compete with audio playback.

Scheduler rules:

1. Limit numerical worker threads.
2. Keep backend event loop free of CPU-heavy loops.
3. Deprioritize optional diagnostics relative to active playback preparation.
4. Measure AudioWorklet underruns while analysis runs.
5. Reduce analysis concurrency if playback suffers.

### 29.4 Long-track test

Use at least one long-form recording to verify:

- preparation remains bounded;
- estimator arrays write incrementally or without excess RAM;
- progress remains responsive;
- cancellation cleans up;
- browser pitch view requests only visible ranges;
- save/open does not require re-analysis;
- evidence indexing does not overflow frontend safe integers.

### 29.5 Browser responsiveness

While pitch analysis is running:

- waveform pan/zoom remains interactive;
- playback controls respond;
- existing notes/results remain viewable;
- progress polling/events do not flood rendering;
- result publication causes one coherent state update rather than thousands of component updates.

### 29.6 Offline analysis

After required model/runtime installation:

1. Disable external network access.
2. Start application.
3. Open project.
4. Run pYIN/torchcrepe/auxiliary analysis.
5. Decode/edit notes.
6. Export MIDI.
7. Save portable project.
8. Reopen.

Assert that no analysis/model-fetch HTTP request occurs.

### 29.7 Model-absent reopen

Remove/disable pitch model runtime after saving a completed project.

Verify:

- project opens;
- notes render;
- text lane renders;
- contour diagnostics included in archive render;
- edits work;
- undo/redo for saved transcription commands works to the degree guaranteed by prior milestones;
- MIDI export works from saved events;
- rerun is disabled with clear model/runtime status.

### 29.8 GPU failure

Simulate/induce:

- unavailable requested GPU;
- worker crash;
- OOM;
- device lost between qualification and run.

Verify:

- earlier result remains available;
- job fails clearly;
- no silent CPU fallback;
- explicit alternative device/CPU retry is possible;
- staged files are cleaned safely.

### 29.9 Disk-full behavior

Before and during evidence output:

- estimate expected storage;
- enforce free-space reserve;
- detect write failure;
- do not publish partial artifacts;
- preserve source/stem and earlier results;
- report reclaim/retry path.

### 29.10 Corrupt evidence behavior

Corrupt one rebuildable framewise artifact and verify:

- project still opens when essential event data is intact;
- corrupt artifact is rejected;
- note edits are preserved;
- diagnostics identify rebuild requirement;
- no automatic network/model activity occurs.

**Acceptance:** bass analysis does not undermine the project's local playback reliability, bounded-memory design, or offline reopen guarantees.

---

## 30. Work package M5.28 — Automated test matrix

### 30.1 Unit tests

Cover:

- F0-to-MIDI/cents conversion;
- tuning-reference conversion;
- source/model frame mapping;
- factor-2 auxiliary time/frequency inverse mapping;
- cents/octave candidate distance;
- candidate agreement classification;
- voicing hysteresis transitions;
- onset/release feature combination;
- note interval validation;
- monophonic overlap rules;
- split/merge semantics;
- slide/bend validation;
- confidence schema;
- MIDI tick mapping;
- note-off ordering;
- cache-key determinism;
- staleness dependency logic.

### 30.2 Estimator integration tests

With small deterministic fixtures:

- pYIN executes and publishes valid arrays;
- torchcrepe executes on CPU and qualified GPU where available;
- auxiliary path maps correctly;
- cancellation removes incomplete output;
- bad/missing model produces structured error;
- native artifact manifests round-trip.

### 30.3 Fusion/decoder tests

Test:

- estimator agreement;
- one-octave disagreement;
- low-register auxiliary selection;
- genuine octave jump with attack;
- silence false-positive suppression;
- sustained-note gap bridging;
- repeated same-pitch split;
- legato pitch change;
- unknown/unpitched event;
- slide continuity;
- vibrato non-segmentation.

### 30.4 Storage/API tests

Test:

- run creation/idempotency;
- result listing;
- active result selection;
- branch creation;
- command conflicts;
- bounded evidence reads;
- stale artifact ID rejection;
- unauthorized route rejection;
- cancellation/restart recovery;
- atomic result publication.

### 30.5 Frontend component tests

Test:

- note overlay rendering;
- note-text lane synchronization;
- selected note shared ID;
- unknown/unpitched rendering;
- confidence indicator text;
- inspector fields;
- Auto/Edited switch;
- stale warning;
- model missing state;
- diagnostic layer toggles.

### 30.6 Browser end-to-end tests

Automate:

1. Open project with completed transcription fixture.
2. Select note in overlay.
3. Verify text lane selects same ID.
4. Verify waveform range highlight.
5. Move note boundary.
6. Change pitch by octave.
7. Split note.
8. Undo/redo.
9. Switch Auto/Edited.
10. Navigate next uncertain note.
11. Audition selected note.
12. Export MIDI.
13. Save/reopen project.
14. Verify corrected note persists.

### 30.7 Visual alignment tests

Use deterministic screenshot/geometry assertions where practical to ensure:

- waveform/note source-frame x coordinates agree;
- playhead active note changes at exact event boundaries;
- text lane/overlay boundaries align;
- zoom/pan does not drift;
- HiDPI canvas handling remains correct.

### 30.8 MIDI tests

Parse exports and assert:

- correct note numbers;
- note count;
- repeated-note distinction;
- note ordering;
- no stuck note;
- variable-tempo event mapping when grid exists;
- fallback warning/profile when grid does not exist;
- edited branch export differs correctly from automatic result.

### 30.9 Portable-project tests

Save/open cases:

- automatic result;
- edited branch;
- multiple results;
- gestures;
- diagnostic evidence;
- stale result;
- pitch model absent;
- missing optional artifact.

### 30.10 Regression tests against earlier milestones

Re-run critical tests for:

- original/stem playback alignment;
- variable-speed transport;
- loops/metronome;
- chord/key editor;
- linked selection;
- project save/open;
- worker lifecycle.

Milestone 5 must not regress earlier workflows.

**Acceptance:** automated tests cover math, inference boundaries, decoding, editing, API, rendering, export, persistence, and regression behavior rather than only happy-path model output.

---

## 31. Work package M5.29 — Manual listening and correction acceptance sessions

### 31.1 Required manual sessions

For each target category, perform an editor-based listening session:

- standard 4-string bass passage;
- five-string low-B passage;
- drop-tuned low passage;
- repeated notes;
- slide/bend passage;
- synth bass;
- sparse/silent passage;
- separation-leakage passage.

### 31.2 Review procedure

For each excerpt:

1. Listen to bass stem alone.
2. Inspect waveform.
3. Inspect automatic note overlay/text lane.
4. Inspect pitch evidence around errors.
5. Check onset/offset.
6. Check nominal pitch/octave.
7. Check slide/bend behavior.
8. Correct using editor.
9. Replay corrected interval.
10. Undo/redo correction.
11. Save/reopen.
12. Export MIDI and audition externally where practical.

### 31.3 Issue log

Record each important defect with:

- project/source timestamp;
- bass stem/result ID;
- transcription profile;
- error category;
- relevant estimator disagreement;
- screenshot/evidence if helpful;
- whether manual correction is possible;
- proposed owning work package.

### 31.4 Acceptance principle

A model error is not automatically a milestone blocker if:

- limitation is measured/documented;
- user can identify it;
- user can correct it precisely;
- persistence/export honor the correction.

A systematic workflow failure is a blocker, such as:

- low B always mapped one octave high;
- repeated same-pitch attacks cannot be represented;
- slide editing loses contour;
- overlay/text views disagree;
- corrections disappear after reopen.

**Acceptance:** practical listening confirms that the two requested note views are genuinely useful for finding and correcting model errors against audio.

---

## 32. Implementation order and milestone gates

Implement in dependency order rather than UI order.

### Gate A — Domain and prerequisite integrity

Complete:

- M5.1 domain/migrations;
- selected bass-stem/tuning-interpretation dependency model, including `BassStemTuningEstimate` identity;
- schema/type generation;
- migration fixtures.

Pass when:

- old projects migrate;
- no source/stem asset is modified;
- a transcription run can identify exact upstream dependencies.

### Gate B — Reproducible raw pitch evidence

Complete:

- M5.2 runtime;
- M5.3 input selection;
- M5.4 mono/preprocessing;
- M5.5 pYIN;
- M5.6 direct torchcrepe;
- M5.7 auxiliary path;
- M5.8 binary evidence artifacts.

Pass when:

- all native estimators produce auditable source-aligned evidence;
- low-register mapping tests pass;
- cancellation/failure never publishes partial arrays;
- analysis works offline after installation.

### Gate C — Fused F0 and voicing

Complete:

- M5.9 fusion/octave handling;
- M5.10 silence/voicing.

Pass when:

- silence fixtures produce no stable fake notes;
- octave-conflict fixtures improve or remain inspectable;
- low-B subset shows the intended auxiliary evidence behavior;
- fusion remains deterministic/versioned.

### Gate D — Note-event decoding and gestures

Complete:

- M5.11 attack/release;
- M5.12 segmentation;
- M5.13 slides/bends.

Pass when:

- repeated same-pitch notes are representable;
- sustained notes are not over-split;
- slides remain continuous where appropriate;
- automatic events validate as monophonic/source-bounded.

### Gate E — Immutable/edited version workflow

Complete:

- M5.14 result/branch publication;
- cache/staleness essentials.

Pass when:

- rerun preserves earlier automatic/edited versions;
- editing never mutates automatic result;
- bass-stem/tuning changes mark only genuine dependencies stale.

### Gate F — Requested two-view editor

Complete:

- M5.15 pitch diagnostics;
- M5.16 note overlay;
- M5.17 note text lane;
- M5.18 note editor;
- M5.19 linked selection/readout.

Pass when:

- both requested views show identical note IDs/timing;
- all main-plan note-edit operations work;
- linked context is synchronized;
- every edit is undoable/persistent.

### Gate G — MIDI export and portable reopen

Complete:

- M5.20 MIDI export;
- M5.22 APIs/jobs;
- M5.23 cache/staleness;
- M5.24 persistence.

Pass when:

- Auto and Edited export correctly;
- variable-tempo timing maps correctly when available;
- no-grid fallback is explicit;
- saved project reopens/export works with pitch model unavailable.

### Gate H — Quality and reliability

Complete:

- optional Basic Pitch comparison where implemented;
- M5.25 corpus;
- M5.26 metrics;
- M5.27 resource/offline tests;
- M5.28 automated suite;
- M5.29 listening sessions.

Pass when:

- required target subsets are measured;
- no critical systematic workflow defect remains;
- limitations are documented;
- earlier milestones remain regression-clean.

---

## 33. Detailed completion checklist

Milestone 5 is not complete until all applicable items below pass.

### Architecture and dependencies

- [ ] Transcription is tied to an exact separation result/bass stem.
- [ ] Tuning context is explicit.
- [ ] Source-frame timing remains authoritative.
- [ ] torchcrepe/PyTorch do not become mandatory backend imports.
- [ ] Model/weight provenance is registered.
- [ ] No inference-time hidden downloads occur.
- [ ] CPU/GPU device behavior is explicit.
- [ ] GPU indices are not treated as stable identity.
- [ ] Two GPUs are not pooled.

### Input/preprocessing

- [ ] Bass-stem asset/hash is validated.
- [ ] Stereo-to-mono analysis transform is versioned.
- [ ] Anti-phase/cancellation case is handled.
- [ ] Estimator sample-rate representations are source-time mapped.
- [ ] Long input processing is bounded-memory.
- [ ] Silence/near-silence preprocessing is safe.

### Bass-stem tuning estimator

- [ ] Uses a dedicated source-aligned spectral/harmonic evidence profile independent of Milestone 4 tuning.
- [ ] Publishes immutable `BassStemTuningEstimate` results tied to exact bass-stem identity.
- [ ] Positive/negative known detuning offsets are measured quantitatively.
- [ ] Silence, bends/slides, harmonic dominance, and low-evidence cases do not force false precision.
- [ ] `uncertain` and `no_stable_tuning` states are tested.
- [ ] Switching to project/manual tuning changes decode identity without rerunning raw neural F0 unnecessarily.

### pYIN

- [ ] Approximately 25–800 Hz profile is represented.
- [ ] Low-frequency window policy is versioned.
- [ ] Native F0 and voicing outputs are retained.
- [ ] Unvoiced is null/masked, not 0 Hz.
- [ ] pYIN timing maps to source frames correctly.

### torchcrepe

- [ ] `full` model is integrated.
- [ ] F0 and periodicity/native score are retained.
- [ ] Silence score caveat is respected.
- [ ] Low-register limitation is not hidden.
- [ ] GPU/CPU qualification works.
- [ ] OOM recovery is bounded.

### Low-register auxiliary

- [ ] Factor-2 time-compression transform is deterministic.
- [ ] Frequency maps back by /2.
- [ ] Time maps back by *2.
- [ ] Endpoint/source-frame mapping is tested.
- [ ] B0/drop-tuning subset is evaluated.
- [ ] Higher-register regression is checked.

### Fusion/voicing

- [ ] Estimator candidates remain inspectable.
- [ ] Octave disagreements are explicitly represented.
- [ ] Continuity is a soft preference.
- [ ] Real attacked octave jumps remain possible.
- [ ] Silence does not become fake pitch.
- [ ] Hysteresis avoids one-frame fragmentation.
- [ ] Ambiguous frames retain alternatives.

### Attack/segmentation

- [ ] Energy envelope exists.
- [ ] Spectral-flux evidence exists.
- [ ] Repeated same-pitch attacks can split notes.
- [ ] Sustained notes do not split on ordinary vibrato.
- [ ] Releases are represented.
- [ ] Unknown/unpitched events are possible.
- [ ] Automatic result is monophonic by default.

### Slides/bends

- [ ] Continuous contour is retained.
- [ ] Slide/bend summaries do not replace raw contour.
- [ ] Vibrato does not cause semitone-fragmentation by default.
- [ ] Slide destination re-attack can create a new note.
- [ ] Gesture edits are persistent/undoable.

### Results/versioning

- [ ] Automatic transcription is immutable.
- [ ] First correction creates an editable branch.
- [ ] Rerun preserves prior branches.
- [ ] Active Auto/Edited source drives every bass-note view.
- [ ] Stale results remain available.
- [ ] Display-only harmony/rhythm changes do not over-stale transcription.

### Pitch-analysis view

- [ ] Fused F0 can be shown.
- [ ] Direct neural F0 can be shown.
- [ ] pYIN F0 can be shown.
- [ ] Auxiliary F0 can be shown.
- [ ] Voicing/ambiguity/onset evidence can be inspected.
- [ ] Visible-range requests are bounded.
- [ ] Dense frames do not create thousands of React DOM nodes.

### Note overlay/text lane

- [ ] Notes display above waveform.
- [ ] Note text displays below waveform.
- [ ] Both views use the same IDs.
- [ ] Both views share exact source-frame boundaries.
- [ ] Unknown/unpitched states are explicit.
- [ ] Selection in one view selects the other.
- [ ] Zoom/pan alignment remains exact.

### Editing

- [ ] Move start boundary.
- [ ] Move end boundary.
- [ ] Change pitch directly.
- [ ] Semitone shift.
- [ ] Octave correction.
- [ ] Insert note.
- [ ] Delete note.
- [ ] Split note.
- [ ] Merge notes.
- [ ] Set unknown/unpitched.
- [ ] Edit slide/bend.
- [ ] Audition note range.
- [ ] Mark reviewed.
- [ ] Default monophonic overlap protection works.
- [ ] Commands use revisions/idempotency.

### Linked selection/readout

- [ ] Selected note highlights waveform interval.
- [ ] Related chord context highlights.
- [ ] Related key context highlights.
- [ ] Related bar/beat context highlights.
- [ ] Related highlights are not edit targets.
- [ ] Musical readout shows active bass note.
- [ ] Unavailable note displays dash/unknown appropriately.
- [ ] Next/previous uncertain-note navigation works.

### MIDI

- [ ] Auto export works.
- [ ] Edited export works.
- [ ] Variable-tempo mapping uses active grid when valid.
- [ ] No-grid fallback is explicit.
- [ ] Repeated same-pitch notes remain distinct.
- [ ] No stuck notes.
- [ ] Unknown events do not become invented pitches.
- [ ] Bend export is either correctly profiled or explicitly omitted.

### Persistence/offline

- [ ] Working autosave preserves transcription edits.
- [ ] Portable save contains required result/edit state.
- [ ] Model weights are excluded.
- [ ] Reopen does not run pitch analysis.
- [ ] Notes remain editable with model absent.
- [ ] MIDI export works with model absent.
- [ ] Optional missing evidence does not delete corrected notes.
- [ ] Stale older transcription remains inspectable.

### Evaluation

- [ ] Voicing precision/recall measured.
- [ ] Pitch accuracy within 50 cents measured.
- [ ] Octave-error rate measured.
- [ ] Note-onset F-measure measured.
- [ ] Onset+offset F-measure measured.
- [ ] Repeated-note detection measured.
- [ ] Low-B subset reported separately.
- [ ] Drop-tuning subset reported separately.
- [ ] Slide continuity evaluated.
- [ ] End-to-end separated-bass performance evaluated.
- [ ] Resource/runtime metrics recorded.
- [ ] Confidence remains uncalibrated unless calibration is proven.

---

## 34. Direct traceability to Section 13 Milestone 5

| Main-plan Milestone 5 item | Detailed coverage |
|---|---|
| 1. Implement pitch-analysis views | M5.8, M5.15 |
| 2. Integrate torchcrepe | M5.2, M5.6 |
| 3. Integrate pYIN | M5.5 |
| 4. Add low-register auxiliary inference | M5.7 |
| 5. Add candidate fusion | M5.9 |
| 6. Add silence/voicing logic | M5.10 |
| 7. Add attack detection | M5.11 |
| 8. Add note segmentation | M5.12 |
| 9. Add slide/bend retention | M5.13 |
| 10. Display notes above the waveform | M5.16 |
| 11. Display synchronized note text below it | M5.17 |
| 12. Add note editing | M5.18 |
| 13. Add linked selection | M5.19 |
| 14. Add bass MIDI export | M5.20 |
| 15. Validate low B, drop tunings, repeated notes, and slides | M5.25–M5.29 |

The main-plan acceptance condition—bass notes can be inspected and corrected against the audio in both requested views—is satisfied only when Gates A–H pass. A raw F0 plot or a MIDI file alone is not sufficient.

---

## 35. Handoff to Milestone 6 — Complete persistence and workflow

Deliver to Milestone 6:

1. Stable automatic bass-transcription result versions.
2. Stable editable bass-transcription branches with revisioned note commands.
3. Explicit result/branch selection state.
4. Complete bass-note command types and inverse/redo data needed for persistent history hardening.
5. Bass transcription dependency/staleness records tied to the exact bass stem and selected tuning interpretation, including bass-stem tuning-result identity where used.
6. Reusable native estimator and fused evidence artifacts.
7. Pitch-analysis view state.
8. Shared linked-selection support for bass notes.
9. Musical readout note integration.
10. Event-boundary snapping support from note starts/ends.
11. MIDI export as the first bass analysis export.
12. Portable-project persistence for automatic/edited transcription.
13. Recovery behavior for missing optional evidence artifacts.
14. Multiple retained transcription versions suitable for broader Auto/Edited/model-version switching UI.
15. Confidence/review state suitable for application-wide uncertain-event navigation.
16. Measured runtime/storage information suitable for cache inspection and cleanup UI.
17. Test fixtures for database/project migration involving transcription state.
18. Clearly declared stale conditions that the Milestone 6 global stale-result UI can surface.
19. All note-edit operations represented through the common command system rather than component-local state.
20. A documented limitation set for low-register, ambiguity, slide/bend, and separated-bass failure cases.

Milestone 6 must not reinterpret bass-transcription semantics. It should complete application-wide persistence/workflow features around the stable objects produced here:

- persistent undo/redo across restart;
- unified Auto/Edited/model-version switching;
- global revision/conflict hardening;
- crash-recovery UX;
- global stale-result indicators;
- snippet queues;
- complete keyboard mapping;
- general export presets and analysis exports;
- cache inspection/cleanup;
- migration/corruption handling.

Bass-note corrections created in Milestone 5 must survive those workflow upgrades unchanged.

---

## 36. Milestone 5 final acceptance statement

Milestone 5 is complete when a user can select a real separated bass stem, run or reuse a separately versioned bass-stem tuning estimate, select the tuning interpretation, run the hybrid low-register-capable transcription pipeline locally, inspect estimator and fused pitch evidence, see synchronized note events above and below the waveform, correct timing/pitch/octave/gesture errors through revisioned edits, navigate those notes with the shared waveform/chord/key/rhythm context, export the selected result as MIDI, save/reopen the complete work offline, and demonstrate through the defined evaluation suite that low B, drop tunings, repeated notes, silence, octave conflicts, and slides are tested explicitly rather than assumed to work.
