# Milestone 3 — Musical grid: detailed implementation specification

This expands Milestone 3 in Section 13 of `basseparate_project_plan.md`.

It builds on `milestone0.md`, `milestone1.md`, and `milestone2.md`. Those milestones remain authoritative for the foundation, media pipeline, waveform editor, source-time transport, separation workflow, stem mixer, time stretching, source-anchored loops, portable projects, and recovery behavior. Milestone 3 must extend those systems rather than replace or fork them.

This specification fixes implementation details that the main plan intentionally leaves open. Where this document introduces a concrete engineering choice—such as the internal musical-position resolution—it is an implementation decision for Milestone 3, not a change to the main plan's product scope.

---

## 1. Required outcome and milestone boundaries

### 1.1 Complete user workflow

At completion, the user can:

1. Launch basseparate and open an existing imported or separated project.
2. Explicitly install the required Beat This! model if it is not already present.
3. Run beat/downbeat analysis on the original mix.
4. Optionally run rhythm analysis on an existing drum stem as a separate result.
5. See detected beats and downbeats aligned to the source waveform and stems.
6. See an editable bar/beat ruler derived from a tempo map and meter regions.
7. Inspect the estimated local tempo and time signature at the playhead.
8. Correct missing, early, late, or extra beats.
9. Change which pulses are downbeats.
10. Set the first numbered bar.
11. Define pickup material before the first complete numbered bar.
12. Insert, move, delete, and lock tempo anchors.
13. Apply half-time or double-time reinterpretation without moving the source audio.
14. Edit time-signature regions and compound/irregular grouping.
15. Work with 4/4, 3/4, 6/8, the other initial automatic meter candidates, and arbitrary manually entered meters.
16. Use musical snapping for new edits while preserving existing source-anchored edits.
17. Convert or create a loop with musical anchors when desired.
18. Practise source-anchored or musical loops at any Milestone 2 playback speed.
19. Hear a metronome synchronized to the corrected variable-tempo grid.
20. Enable one- or two-bar count-in once or before every repeat.
21. Start a loop on a beat other than beat 1 and receive a count-in with the correct bar phase.
22. Reopen the project without the Beat This! model, without rerunning analysis, and retain the corrected grid and practice state.
23. Undo and redo every manual rhythm, meter, snapping, metronome, count-in, and musical-loop edit introduced in this milestone.

### 1.2 Included work

Milestone 3 includes:

- Isolated Beat This! runtime integration.
- Required `final0` model registration and explicit installation.
- Optional `small0` faster model registration.
- Beat/downbeat activation extraction and retained binary artifacts.
- Beat/downbeat candidate postprocessing.
- Immutable automatic rhythm result versions.
- Editable rhythm branches.
- Tempo-map construction from accepted pulses.
- A source-frame ↔ musical-position mapping.
- Meter candidate generation and sequence decoding.
- Meter uncertainty and alternatives.
- First-downbeat and bar-number origin handling.
- Pickup bars and partial bars.
- Half/double-time reinterpretation.
- Tempo-anchor editing and locking.
- Meter-region editing and grouping.
- Bar/beat/subdivision ruler rendering.
- Musical snapping.
- Beat-anchored loop support.
- Variable-tempo metronome scheduling.
- One-/two-bar count-in.
- Musical readout and bar navigation.
- Persistence, portable-project integration, cache identity, and version retention.
- Synthetic rhythm fixtures, annotated evaluation excerpts, browser tests, timing tests, and practical listening tests.

### 1.3 Deferred work

Do not pull later milestones into Milestone 3.

Still deferred:

- Chord recognition and chord editing.
- Key and tuning analysis.
- Bass-note transcription.
- Note/chord-aware snapping beyond the generic event-boundary mode.
- Six-stem quality-model expansion.
- SCNet/RoFormer comparison UI.
- YouTube import.
- Noncontiguous snippet queues.
- FLAC/MP3 export additions.
- Full analysis-version comparison UI.
- Chord/key/bass fields in the musical readout, except that the UI may show an unavailable placeholder until those milestones exist.

Milestone 3 must not invent chord, key, or bass-note results to make the musical ruler look complete.

### 1.4 Prerequisite state inherited from Milestone 2

Milestone 3 assumes Milestone 2 has delivered:

1. Immutable canonical source audio.
2. Stable project source-frame timing.
3. Original and separated playback representations.
4. A common synchronized transport for all active stems.
5. Variable-speed playback from 0.25× to 2.0×.
6. A transport ledger connecting project/source frames to render time.
7. Saved source-frame loops.
8. Durable jobs and worker subprocesses.
9. A general model registry and explicit model-installation workflow.
10. Immutable analysis results and cache identities.
11. Transactional project commands with revision checks.
12. Working undo/redo.
13. Portable `.basseparate` save/open.
14. Offline reopen and playback without model files.
15. A browser editor capable of adding lanes above aligned waveforms.

A failed prerequisite is recorded and fixed at the owning milestone boundary. Milestone 3 must not hide a transport or persistence defect behind rhythm-specific workarounds.

### 1.5 Definition of the milestone boundary

Milestone 3 is complete only when automatic analysis, manual correction, musical mapping, playback synchronization, persistence, and testing operate as one workflow.

The following are not sufficient by themselves:

- displaying Beat This! timestamps without a correct editable tempo map;
- drawing bar lines from a constant-BPM estimate;
- inferring a meter label without editable regions;
- scheduling metronome clicks from JavaScript animation timers;
- snapping by mutating existing annotations automatically;
- implementing count-in as audio inserted into source time;
- showing 6/8 without clearly distinguishing its displayed tempo unit;
- passing only synthetic 4/4 tests.

---

## 2. Fixed implementation decisions for Milestone 3

| Area | Milestone 3 decision |
|---|---|
| Initial beat/downbeat model | Beat This! `final0` |
| Faster optional preset | Beat This! `small0` |
| Model execution | Dedicated locked analysis environment/subprocess |
| Default analysis input | Original reference mix |
| Optional comparison input | Existing drum stem as a separate result |
| Raw model output | Retain beat and downbeat frame activations |
| Automatic result | Immutable rhythm result version |
| Manual result | Editable branch derived from an automatic result |
| Authoritative source time | Integer project sample frames |
| Musical position | Reduced rational quarter-note positions (`numerator/denominator`) |
| Tempo mapping | Piecewise-linear monotonic map between source frames and musical positions |
| Automatic tempo anchors | One anchor per accepted pulse initially, after pulse-unit interpretation |
| Meter model | Separate inference stage; meter is not implied by beat detection alone |
| Initial automatic meter candidates | 2/4, 3/4, 4/4, 6/8, 9/8, 12/8, 5/4, 7/8 |
| Manual meter entry | Any validated numerator/denominator with explicit grouping where useful |
| Bar/beat ruler | Derived from active tempo map + meter regions; not stored as millions of line objects |
| Snap radius | Approximately 8 CSS pixels |
| Metronome clock | Same AudioContext/AudioWorklet render clock as playback |
| Metronome placement | Generated after time stretching, scheduled from source→output transport mapping |
| Count-in | Output-only transport phase; source time does not advance |
| Existing loop default | Source-frame anchored, unchanged |
| New musical loop mode | Exact musical-position anchored and resolved through active grid |
| Model downloads | Explicit only; no inference-time remote fallback |
| Portable reopen | Does not require Beat This!, weights, GPU, or network |

### 2.1 Exact rational musical position

The main plan requires musical position to remain distinct from source time and permits arbitrary manually entered numerator/denominator meters. Milestone 3 therefore stores authoritative musical position as an exact reduced rational number measured in quarter-note units.

Represent a musical position as:

```text
{ numerator: integer, denominator: positive integer }
```

with the fraction reduced to lowest terms. Examples:

- quarter note = `1/1` quarter-note units;
- eighth note = `1/2`;
- dotted quarter = `3/2`;
- one denominator unit of an unusual `n/7` meter = `4/7`.

This choice:

1. Represents ordinary and unusual manually entered meters exactly.
2. Avoids cumulative floating-point drift in bar-boundary arithmetic.
3. Keeps source-frame timing integer-based as required by the main plan.
4. Allows common meters to use optimized integer fast paths internally without making those fast paths authoritative.
5. Keeps equality at meter/bar boundaries deterministic.

Serialization rules:

- numerator is a signed safe integer;
- denominator is a positive safe integer;
- zero is always serialized as `0/1`;
- normalize sign onto the numerator;
- reduce by greatest common divisor before persistence;
- reject denominator zero;
- reject values whose normalized components exceed the agreed frontend-safe range.

Python may use exact rational arithmetic internally. TypeScript implements the same reduced-fraction operations or uses integer cross-multiplication with overflow guards. Derived display values may use floating point, but persisted musical coordinates and boundary equality do not.

### 2.2 Three independent concepts: pulse, tempo anchor, meter

Keep these separate:

1. **Rhythm pulse** — evidence that a beat/downbeat-like event occurs at a source position.
2. **Tempo anchor** — a control point mapping a source frame to a musical position.
3. **Meter region** — notation/grouping information describing how musical positions form bars and primary pulses.

The automatic pipeline may create linked objects, but their identities remain distinct.

Consequences:

- A low-confidence detected pulse can exist without controlling the active tempo map.
- A manual tempo anchor can exist without a detected pulse.
- A pulse can be reclassified as a downbeat without moving it in source time.
- A meter change can alter bar interpretation without changing audio or pulse positions.
- Correcting the tempo map does not rewrite the immutable activation artifact.

### 2.3 Source time remains authoritative for audio

Milestone 3 does not replace source-frame timing.

- Audio assets remain indexed by project frames.
- Existing markers remain source-frame anchored.
- Existing source loops remain source-frame anchored.
- Transport position remains source-frame based.
- Musical positions are a derived/editable coordinate system layered on top.
- Playback speed changes output time, not source or musical project coordinates.

### 2.4 Grid validity is explicit

The active rhythm branch may contain regions in one of these states:

- `valid` — a monotonic tempo map and meter interpretation exist.
- `uncertain` — a usable grid exists but automatic evidence is ambiguous.
- `unmetered` — tempo anchors may exist, but no stable meter is asserted.
- `unmapped` — no usable musical mapping exists for the interval.

Do not force bars through `unmapped` regions.

A metronome may operate on mapped quarter-note positions in an `unmetered` region without a downbeat accent, but bar-based count-in requires a valid meter context.

### 2.5 Cross-project constraints carried forward

The following decisions from the full project plan remain binding throughout Milestone 3:

1. **Local-first execution:** ordinary analysis, editing, playback, save/open, and practice remain local. Internet access is used only for an explicit model installation action.
2. **Loopback security:** new APIs remain on the authenticated loopback service and do not introduce permissive LAN/CORS behavior.
3. **Source-frame authority:** model timestamps are converted back into project source-frame coordinates; model sample rates never become project time.
4. **Immutable automatic results:** raw activations and automatic rhythm results are versioned artifacts; user corrections live in editable project branches.
5. **Typed confidence:** uncalibrated activation or heuristic scores remain labelled as such; human correction never becomes synthetic model confidence.
6. **Bounded binary artifacts:** long framewise activation/feature arrays stay outside project JSON and are accessed through bounded file/API interfaces.
7. **Durable jobs:** analysis jobs are persisted before execution, support cancellation, and publish artifacts atomically.
8. **GPU isolation:** GPUs are independent memory pools; one heavy job per GPU remains the initial scheduling rule.
9. **Playback priority:** worker concurrency must preserve audio responsiveness; analysis is never allowed to make prepared practice playback routinely underrun.
10. **One transport/clock:** stems, stretched playback, metronome, count-in, loops, and audible-position readout share the existing AudioContext/transport timing model.
11. **Transactional editing:** every semantic correction uses base revision + idempotency semantics and participates in persistent undo/redo.
12. **Cache provenance:** cache identity includes all upstream assets, model/weight versions, preprocessing, algorithm/profile versions, and parameters that can change results.
13. **Portable reopen without inference:** `.basseparate` archives contain the selected project's rhythm state/artifacts but not model weights or runtime environments.
14. **No hidden certainty:** ambiguous meter, half/double-time interpretation, or low-confidence pulse evidence is shown as ambiguous rather than silently forced.
15. **Measured quality:** Beat/downbeat F-measure, half/double errors, meter-region accuracy, tempo-anchor timing error, runtime, and resource use are measured rather than promised.

---

## 3. Work package M3.1 — Verify prerequisites and extend the domain

### 3.1 Prerequisite verification

Before adding rhythm analysis:

1. Run all Milestone 0–2 checks.
2. Open each existing local WAV project used in prior milestones.
3. Verify canonical source frame count and sample rate.
4. Verify original and stem playback remain aligned.
5. Verify variable speed at 0.25×, 1×, and 2×.
6. Verify saved source loops repeat without cumulative drift.
7. Verify the transport ledger survives seeks and rate changes.
8. Verify portable save/open restores playback without model access.
9. Verify project command conflicts still return `409` rather than silently overwriting another tab.
10. Verify separation/model workers can coexist with a model-free backend startup.
11. Record baseline CPU, RAM, and audio-underrun behavior during playback.
12. Do not begin metronome integration until the transport timing baseline is trustworthy.

### 3.2 Add shared musical-position primitives

Define:

- `MusicalPosition`: exact reduced rational quarter-note coordinate.
- `MusicalPosition` values measured in exact quarter-note units.
- `BarNumber`: signed integer display number.
- `MeterNumerator`: positive integer.
- `MeterDenominator`: positive integer denominator; conventional power-of-two values are common, but nonstandard positive denominators remain representable for manual entry.
- `Grouping`: ordered positive integer list whose sum equals the numerator.
- `PulseRole`: `beat`, `downbeat`, `candidate`, `unknown`.
- `GridValidity`: `valid`, `uncertain`, `unmetered`, `unmapped`.
- `AnchorLockState`: unlocked/locked.
- `LoopAnchorMode`: `source` or `musical`.

For frontend-visible integers:

1. Reject nonintegers.
2. Reject values outside the safe-integer range.
3. Validate musical-position ordering independently from source-frame ordering.
4. Permit negative musical positions only for explicit pre-origin/pickup representation where the schema says they are allowed.
5. Never serialize musical positions as floating-point beats.

### 3.3 Rhythm analysis run record

Add a `RhythmAnalysisRun` containing:

- Run ID.
- Project ID.
- Input asset ID/hash.
- Input role: original mix or drum stem.
- Model manifest ID/hash.
- Model preset (`final0` or `small0`).
- Adapter version.
- Worker environment fingerprint.
- Preprocessing profile/version.
- Requested device.
- Actual device/GPU UUID when applicable.
- Precision/profile.
- Start/end timestamps.
- Status.
- Activation artifact ID.
- Decoded-result ID.
- Warnings.
- Runtime metrics.
- Peak device/host memory where available.

### 3.4 Activation artifact metadata

Define a binary-artifact manifest containing:

- Artifact ID and content hash.
- Parent run ID.
- Source asset identity.
- Model frame count.
- Beat activation array reference.
- Downbeat activation array reference.
- Array dtype, initially float32 unless the verified adapter requires otherwise.
- Model frame-hop metadata.
- Model sample-rate metadata.
- Exact preprocessing transform.
- Mapping from model frame positions back to project source frames.
- Model output semantics as documented by the pinned implementation.
- Artifact format version.

Store arrays outside project JSON.

Initial file representation:

- one `.npy`-compatible immutable array for beat activations;
- one `.npy`-compatible immutable array for downbeat activations;
- a compact JSON manifest linking both arrays and provenance.

Do not use compressed containers that prevent efficient range access unless measurements justify the tradeoff later.

### 3.5 Rhythm pulse record

Each pulse contains:

- Pulse UUID.
- Parent automatic result or edited branch ID.
- Source-frame position.
- Original model-frame index where applicable.
- Role: beat/downbeat/candidate.
- Acceptance state: accepted/rejected/candidate.
- Confidence object.
- Automatic/manual provenance.
- Optional linked tempo-anchor ID.
- Human review state.

Do not store bar number directly on a pulse as authoritative state. Bar number is derived from the active tempo/meter interpretation.

### 3.6 Tempo anchor record

Each tempo anchor contains:

- UUID.
- Rhythm branch ID.
- Source-frame position.
- Musical position.
- Lock state.
- Origin: automatic/manual.
- Optional linked pulse ID.
- Confidence/provenance for automatic anchors.
- Creation/update timestamps for edited anchors.

Validation:

1. Source positions strictly increase between adjacent anchors.
2. Musical positions strictly increase between adjacent anchors.
3. No duplicate source position in one active map.
4. No duplicate musical position in one active map.
5. Anchors remain within project source bounds.
6. Manual movement cannot cross neighbors.

### 3.7 Meter region record

Each meter region contains:

- UUID.
- Rhythm branch ID.
- Start musical position.
- Optional end musical position derived from the next region.
- Numerator.
- Denominator.
- Grouping.
- Primary pulse definition.
- Display tempo unit.
- Confidence object.
- Alternative hypotheses for automatic regions.
- Grid validity.
- Origin: automatic/manual.
- Review state.

A region change must begin on an explicit bar boundary under the preceding valid meter interpretation.

### 3.8 Bar-origin and pickup state

Add rhythm-branch state containing:

- `first_numbered_bar_position`.
- `first_bar_number`, default `1`.
- Optional pickup-region definition before that point.
- Optional leading unmapped interval.

Do not force project frame zero to be bar 1 beat 1.

### 3.9 Rhythm branch record

Define:

- Branch UUID.
- Parent automatic rhythm result ID.
- Branch revision.
- Pulse collection/reference.
- Tempo anchors.
- Meter regions.
- Bar-origin state.
- Grid validity summary.
- Created/updated timestamps.
- Human review summary.

Automatic output remains immutable. Edits target a branch.

### 3.10 Project-level active rhythm state

Add:

- Active automatic rhythm result ID.
- Active edited rhythm branch ID.
- Auto/Edited display mode.
- Rhythm lane visibility/height.
- Musical ruler visibility.
- Snap mode.
- Metronome settings.
- Count-in settings.
- Optional last selected rhythm object.

### 3.11 Schema and database migration

1. Increment the database schema through an ordered migration.
2. Update project serialization schema.
3. Update the portable-project schema.
4. Preserve Milestone 0–2 projects with no rhythm state.
5. Add null/default rhythm fields without modifying existing audio/stem assets.
6. Generate updated TypeScript contracts.
7. Add migration fixtures for empty, imported, separated, looped, and portable projects.
8. Reject newer unsupported rhythm schemas without writing them.

**Acceptance:** rhythm analysis, musical mapping, meter, and practice settings can be represented without altering existing source/stem timing.

---

## 4. Work package M3.2 — Integrate the Beat This! runtime and model registry

### 4.1 Isolated runtime

Create a dedicated locked environment for the Beat This! adapter.

Requirements:

1. Use Python 3.11 initially unless the pinned upstream requires a different supported version.
2. Keep its PyTorch and research dependencies outside the core backend environment.
3. Pin the upstream implementation revision.
4. Pin all direct runtime dependencies.
5. Record a lock/environment fingerprint.
6. Launch with an explicit interpreter path.
7. Reuse the existing versioned worker protocol where compatible.
8. Do not import Beat This! or PyTorch in ordinary backend startup.
9. Do not perform model downloads during worker startup.

### 4.2 Model registry entries

Create checked-in registry entries for:

- required quality preset: Beat This! `final0`;
- optional faster preset: Beat This! `small0`.

Each entry records:

- Stable basseparate model ID.
- Upstream repository/revision.
- Model/checkpoint name.
- Download URL or upstream resolver information.
- Expected byte size when determinable.
- SHA-256 hash resolved during implementation.
- Code license.
- Published weight license.
- Required notices.
- Preprocessing requirements.
- Output activation semantics.
- CPU/GPU capability.
- Adapter version compatibility.

Do not invent hashes in the design document. Resolve and commit them only after verifying the official artifacts.

### 4.3 Installation workflow and shared network-download boundary

Milestone 2 needs no online model download because the Demucs baseline is bundled. Milestone 3 therefore establishes the first reusable network-enabled model-download job/worker boundary. It must be separate from inference workers, durable, cancellable, hash-verifying, and reusable by later separately installed model families in Milestones 4, 5 where applicable, and 7. Offline mode disables this worker without affecting bundled Demucs inference.

Reuse the registry/provenance conventions introduced in Milestone 2, but perform Beat This! installation through this new network-download boundary. Because Milestone 0 defaults to offline mode, the UI must show that online installation is disabled while offline mode is active and provide an explicit Settings action to disable offline mode before starting the download; the Install action never silently overrides offline mode.

1. Display model name and purpose.
2. Display expected download size.
3. Display license/provenance summary.
4. Require explicit Install.
5. Download to staging.
6. Report byte progress.
7. Support cancellation.
8. Verify final hash.
9. Publish atomically.
10. Run a short load/inference qualification.
11. Mark installed only after qualification succeeds.

### 4.4 Offline model import

Permit an offline registered-model bundle:

1. Read the registered manifest.
2. Reject unknown arbitrary worker code.
3. Verify checkpoint hashes.
4. Verify manifest identity.
5. Preserve license notices.
6. Install into the managed model store.
7. Qualify with network disabled.

### 4.5 Device qualification

For each usable device:

1. Start the Beat This! worker.
2. Load the selected model.
3. Run a short deterministic fixture.
4. Confirm finite outputs.
5. Record elapsed time.
6. Record host/device memory where available.
7. Record runtime and GPU UUID.
8. Mark model/device pair qualified only after successful inference.

Preferred scheduling order:

1. Qualified RTX 5060 Ti when available for independent rhythm analysis.
2. Qualified RTX 4080 when appropriate and not reserved by a separation job.
3. CPU fallback.

This follows the main architecture's intent to reserve the RTX 4080 primarily for heavy separation while allowing independent analysis on the secondary GPU.

Do not combine VRAM pools.

### 4.6 CPU fallback

1. Support the same adapter on CPU when upstream supports it.
2. Bound CPU threads to preserve playback responsiveness.
3. Label CPU execution as potentially slower.
4. Preserve identical result schemas.
5. Include device profile in cache identity only where it can materially change numerical output; otherwise record it in provenance without needlessly preventing cache reuse.

### 4.7 No hidden downloads

Before inference:

1. Resolve model manifest.
2. Verify local checkpoint presence.
3. Verify hash when integrity is uncertain.
4. Pass explicit local paths to the worker.
5. Disable remote fallback.
6. Fail with `MODEL_NOT_INSTALLED` when required bytes are absent.

Opening an existing rhythm-enabled project must never trigger a model download.

**Acceptance:** `final0` can be installed explicitly, qualified, and run with external network access disabled; existing projects remain usable with the model absent.

---

## 5. Work package M3.3 — Prepare rhythm-analysis input reproducibly

### 5.1 Default input role

Analyze the original reference mix first.

Input selection:

- Mono source: use canonical mono according to the adapter's declared channel requirements.
- Stereo source: use canonical stereo or a documented model-specific downmix if required by the pinned model.
- Multichannel source: use the explicit Milestone 1 monitoring/reference downmix, recording that provenance.

Do not infer rhythm from the separated drum stem by default merely because separation exists.

### 5.2 Optional drum-stem result

When a compatible drum stem is available:

1. Offer `Analyze drums for rhythm comparison` as a separate action/preset.
2. Store it as a distinct analysis run/result.
3. Preserve original-mix rhythm results.
4. Compare pulse agreement only as diagnostic evidence.
5. Never silently replace the original-mix grid with the drum result.
6. Allow the user to choose which automatic result becomes the basis for an edited branch.

### 5.3 Model-declared preprocessing

The adapter reads the pinned implementation's actual requirements rather than copying assumptions into the core application.

Record:

- Model input sample rate.
- Channel transform.
- Amplitude transform/normalization.
- Feature parameters controlled by upstream.
- Frame hop.
- Padding/context rules.
- Output frame alignment.

### 5.4 Continuous preprocessing

1. Read the immutable reference asset.
2. Build or reuse a model-specific analysis representation.
3. Resample continuously, not independently per HTTP chunk.
4. Preserve exact source-to-analysis time mapping.
5. Record endpoint rounding.
6. Validate duration against source duration.
7. Keep the source unmodified.

### 5.5 Long-track behavior

Prefer the pinned Beat This! implementation's supported long-track inference path.

If explicit chunking is required:

1. Define a versioned chunk/context profile.
2. Provide overlap/context sufficient for model receptive field.
3. Remove duplicate/padded frame outputs deterministically.
4. Concatenate activation frames in one monotonic model-time sequence.
5. Verify the chunked result against a short whole-input reference path.
6. Store the actual profile in the cache key.

Do not introduce a custom long-track adaptation without comparison evidence.

### 5.6 Degenerate input handling

Handle:

- Exact silence.
- Near silence.
- Very short audio.
- Percussion-only audio.
- Sustained/nonpercussive passages.
- Long silent intro/outro.

Rules:

1. Silence may yield no accepted pulses.
2. A no-pulse result is valid, not a worker crash.
3. Do not fill silent intervals with a fabricated constant grid.
4. Mark downstream map regions `unmapped` where appropriate.
5. Keep low activation values available for inspection.

### 5.7 Transformation/cache identity

Input transformation key includes:

- Source/reference asset hash.
- Source role.
- Channel/downmix identity.
- Model manifest/hash.
- Adapter version.
- Preprocessing profile/version.
- Analysis interval, if partial analysis is later enabled.

**Acceptance:** the same source and model profile produce a reproducible analysis representation with an auditable source-time mapping.

---

## 6. Work package M3.4 — Run Beat This! and retain frame activations

### 6.1 Worker capability declaration

The Beat This! module declares:

- Stable module ID/version.
- `beat_downbeat_activations` output capability.
- Supported input roles.
- Required model IDs.
- Device support.
- Expected memory class.
- Cancellation behavior.
- Determinism limitations.
- Output artifact schema.
- Confidence semantics.
- License records.

### 6.2 Inference sequence

1. Validate request and model installation.
2. Resolve prepared input.
3. Allocate the selected device.
4. Load the model.
5. Warm up with bounded input if required.
6. Run inference.
7. Emit progress by processed model frames/time where possible.
8. Collect beat activations.
9. Collect downbeat activations.
10. Validate dimensions and finite values.
11. Write arrays into staging artifacts.
12. Write activation manifest/provenance.
13. Hash outputs.
14. Publish artifacts atomically.
15. Release model/device resources according to worker policy.
16. Mark the activation stage complete.

### 6.3 Activation preservation rules

1. Preserve the model's direct frame activations before timestamp postprocessing.
2. Do not threshold them destructively in the retained artifact.
3. Do not convert all frames into JSON objects.
4. Preserve original frame ordering.
5. Preserve enough alignment metadata to map every frame to project time.
6. Do not relabel raw activations as calibrated probabilities unless calibration evidence exists.

### 6.4 Confidence semantics

Until independently established:

- store raw activation scores as model scores;
- use confidence `kind=heuristic` or another explicitly documented non-calibrated kind;
- set `calibrated=false`;
- avoid user-facing text such as `95% correct`.

If the pinned upstream explicitly defines a score as a probability, record that semantics but still keep calibration status distinct.

### 6.5 Progress

Progress phases:

- Preparing input.
- Loading model.
- Running inference.
- Writing activations.
- Validating artifact.
- Decoding pulses.

Use determinate percentage only when a reliable denominator exists.

### 6.6 Cancellation

1. Set job cancelling state.
2. Signal the worker.
3. Check cancellation at bounded inference boundaries.
4. Stop writing further activation frames.
5. Remove incomplete staged artifacts.
6. Preserve previously published rhythm results.
7. Release GPU resources through worker cleanup/process exit if necessary.
8. Keep model installation and prepared input for retry.

### 6.7 Crash recovery

An interrupted activation run restarts from the beginning unless the pinned upstream provides a validated resumable mechanism.

Completed prepared inputs remain reusable.

Never publish a partially written activation artifact as complete.

**Acceptance:** the application retains auditable beat/downbeat activation arrays aligned to source time and can cancel/fail without damaging earlier results.

---

## 7. Work package M3.5 — Decode beat and downbeat candidates

### 7.1 Default postprocessor

Use the pinned Beat This! implementation's documented/default timestamp postprocessing as the initial decoder where practical.

Wrap it behind a basseparate decoder profile so:

- parameters are explicit;
- version changes create a new result identity;
- raw activations remain independent;
- future decoder comparison does not require rerunning neural inference.

### 7.2 Candidate generation

For each decoded candidate:

1. Record model-time/frame location.
2. Map to a source-frame position using the stored preprocessing transform.
3. Classify as beat/downbeat candidate according to decoder output.
4. Sample or aggregate nearby activation evidence.
5. Attach uncalibrated confidence metadata.
6. Retain rejected/low-confidence candidates in the decoded artifact where the decoder exposes them or where a configured candidate threshold permits inspection.

### 7.3 Source-frame rounding

1. Compute model→source mapping in fractional source frames.
2. Round once at the final discrete pulse boundary using one documented rule.
3. Record the pre-rounded value for diagnostics if needed.
4. Clamp only legitimate endpoint rounding.
5. Reject mapping errors that put events materially outside source duration.

If two decoded events collapse to the same project frame after rounding:

- keep the stronger accepted event;
- retain the other as an alternative/collision diagnostic;
- never create two active pulses at the same source frame.

### 7.4 Accepted versus candidate pulses

Keep two layers:

- **accepted pulses** — initial objects used to construct the automatic tempo map;
- **candidate pulses** — lower-confidence or competing events available for review.

The UI may hide candidate pulses by default but must preserve them.

### 7.5 Downbeat handling

1. A downbeat is also a pulse.
2. Downbeat confidence is stored separately from generic beat confidence where available.
3. Do not infer time signature directly from the existence of downbeats.
4. Permit later meter inference to reject or reinterpret downbeat candidates.
5. Preserve the original model's downbeat classification even when the editable branch changes it.

### 7.6 Basic plausibility checks

Flag, but do not automatically destroy, suspicious sequences such as:

- implausibly tiny inter-pulse intervals;
- long gaps surrounded by strong activations;
- repeated half/double-tempo patterns;
- downbeats with no plausible meter periodicity;
- pulses in near-silent regions.

Use flags as meter/tempo evidence and review aids.

### 7.7 Decoder alternatives

The architecture must permit later decoder profiles or ensembles to consume the same activation artifact.

Do not hard-code postprocessing into the neural worker such that activations cannot be re-decoded independently.

**Acceptance:** decoded pulse objects are source-aligned, versioned separately from raw activations, and preserve ambiguous evidence for later correction.

---

## 8. Work package M3.6 — Publish immutable automatic rhythm results and editable branches

### 8.1 Automatic rhythm result

An immutable `RhythmResult` contains:

- Result UUID.
- Parent analysis run ID.
- Activation artifact ID.
- Decoder profile/version.
- Accepted pulse set.
- Candidate pulse set/reference.
- Initial tempo-map result/reference.
- Initial meter result/reference.
- Bar-origin hypothesis.
- Result-level warnings.
- Input role.
- Creation timestamp.
- Validation status.

### 8.2 Progressive publication

Publish stages progressively:

1. Activation artifact available.
2. Decoded pulses available.
3. Tempo map available.
4. Meter hypotheses available.
5. Complete automatic rhythm result validated.

The UI may display beats before meter finishes, but it must label the musical ruler as pending until the grid is valid.

### 8.3 Editable branch creation

When the user first edits an automatic rhythm result:

1. Create an editable branch referencing the immutable parent.
2. Copy or logically overlay the editable pulse/anchor/meter state.
3. Preserve parent IDs/provenance.
4. Record the branch revision.
5. Make the edit transactionally.
6. Keep the automatic result untouched.

### 8.4 Auto/Edited switching

Provide:

- Auto view.
- Edited view.

Switching view:

1. Is undoable when it changes the project's active rhythm source.
2. Does not delete either version.
3. Updates ruler, snapping, metronome, count-in, musical readout, and musical-loop resolution consistently.
4. Does not move source-anchored loops or markers.

### 8.5 Rerunning rhythm analysis

1. Create a new immutable automatic result.
2. Keep older automatic results.
3. Keep all edited branches.
4. Do not merge new automatic pulses into an old edited branch automatically.
5. Let the user select a new result as active or create a new edited branch from it.
6. Mark dependent future analyses stale only when their recorded dependency actually includes the replaced rhythm result/branch.

### 8.6 Result comparison boundary

Milestone 3 only needs a practical selector showing available rhythm results and their provenance.

A full visual multi-result comparison UI remains later work.

**Acceptance:** automatic rhythm output is immutable, manual corrections survive reruns, and every grid-dependent feature follows the selected active rhythm version.

---

## 9. Work package M3.7 — Build the tempo map

### 9.1 Mathematical representation

Represent the tempo map as a strictly monotonic piecewise-linear mapping:

```text
source_frame <-> musical_position
```

Each adjacent pair of anchors defines one segment.

For anchors `(s0, m0)` and `(s1, m1)`:

```text
musical_position(s) = m0 + (s - s0) * (m1 - m0) / (s1 - s0)
```

and the inverse:

```text
source_frame(m) = s0 + (m - m0) * (s1 - s0) / (m1 - m0)
```

Use high-precision intermediate arithmetic.

Round to an integer source frame only when an actual source-frame event/boundary is required.

### 9.2 Pulse-unit hypotheses

Detected pulses are neutral timing evidence until assigned a musical distance.

For each plausible region, consider pulse-unit hypotheses appropriate to the candidate meter, including:

- quarter-note pulse;
- half-note or eighth-note reinterpretation for half/double-time ambiguity;
- dotted-quarter primary pulse for standard compound meter;
- denominator-unit pulses where evidence supports them;
- irregular grouping pulses for meters such as 7/8.

Store the selected interpretation and alternatives.

### 9.3 Initial automatic anchors

1. Start from accepted decoded pulses.
2. Apply the selected pulse-unit hypothesis.
3. Assign monotonically increasing musical positions.
4. Create one tempo anchor per accepted pulse initially.
5. Link anchors to pulses.
6. Preserve natural timing variation rather than fitting one global BPM.

### 9.4 Local BPM

For each anchor segment:

```text
quarter_notes = exact_quarter_note_difference(m1, m0)
seconds = (s1 - s0) / project_sample_rate
quarter_note_BPM = 60 * quarter_notes / seconds
```

Store BPM as a derived value, not authoritative project state.

### 9.5 Summary tempo

Compute a robust summary BPM separately for display/search metadata.

Rules:

- never replace the variable tempo map with the summary;
- identify the tempo unit shown;
- do not average across unmapped regions as though timing were stable;
- preserve local segment values for metronome scheduling.

### 9.6 Compound-meter tempo unit

Each meter region declares its display tempo unit.

For standard 6/8 with grouping `3+3`:

- quarter-note BPM remains mathematically available;
- dotted-quarter pulse BPM may be the musically preferred displayed tempo;
- the UI must label which unit is being shown.

Do not present a dotted-quarter pulse value as unlabeled quarter-note BPM.

### 9.7 Interpolation and extrapolation

Between anchors:

- interpolate linearly.

Outside the first/last anchor:

- do not silently extrapolate an unlimited grid;
- permit a small explicitly defined edge extension only when needed to resolve the project boundary or a pickup/count-in context and when the local tempo is valid;
- mark extrapolated positions distinctly in diagnostics;
- otherwise mark the region unmapped.

### 9.8 Monotonicity validation

Reject edited maps where:

- source frames stop increasing;
- musical positions stop increasing;
- segment duration becomes zero/negative;
- calculated BPM is nonfinite;
- a meter boundary can no longer be resolved because the map is invalid.

### 9.9 Half/double-time reinterpretation

Implement a region-level command that changes the musical position distance assigned to a sequence of pulses while leaving their source frames fixed.

Behavior:

1. User selects a mapped region.
2. Choose half-time or double-time interpretation.
3. Rescale musical position deltas for that region consistently.
4. Preserve anchor source positions.
5. Reconcile the region endpoints with neighboring locked anchors.
6. Recompute bar phase/meter compatibility.
7. Surface conflicts rather than silently shifting locked anchors.
8. Record the operation as one undoable command.

The UI labels the resulting quarter-note BPM so the meaning is explicit.

### 9.10 Locked anchors

Locked anchors:

- remain fixed during automatic local reflow/reinterpretation;
- divide the map into independently adjustable intervals;
- can still be deliberately edited after explicit unlock or direct confirmed manual action;
- retain their lock state through save/open.

### 9.11 Sparse/manual maps

Permit a user-created tempo map even when automatic beat analysis fails.

Minimum usable mapped interval:

- at least two valid tempo anchors with distinct source frames and musical positions.

Without a stable meter:

- musical quarter-position readout may work;
- a neutral quarter-click metronome may work;
- bar numbering and bar-count count-in remain unavailable.

**Acceptance:** the tempo map preserves timing variation, supports half/double interpretation and manual anchors, and maps source↔musical positions reversibly within documented rounding tolerance.

---

## 10. Work package M3.8 — Infer and edit meter regions

### 10.1 Inputs to meter inference

Use:

- beat activation evidence;
- downbeat activation evidence;
- accepted pulse timing;
- inter-pulse intervals;
- accent evidence derived from source audio;
- subdivision onset evidence;
- bar-duration consistency;
- transition penalties discouraging unsupported frequent meter changes.

Do not use separated stems as a mandatory prerequisite.

### 10.2 Lightweight accent/subdivision evidence

Implement a versioned CPU feature extractor over the reference mix for meter scoring.

Initial evidence may include:

- short-time energy/envelope changes;
- spectral-flux-like onset strength;
- low-frequency/percussive emphasis where useful;
- periodicity aggregated around pulse/subdivision positions.

Requirements:

1. Use bounded-memory processing.
2. Store only compact feature arrays/artifacts needed for repeatable scoring.
3. Version the feature profile.
4. Keep this evidence separate from Beat This! activations.
5. Do not claim accent evidence is a semantic instrument label.

### 10.3 Initial meter candidates

Automatic candidate set:

- 2/4.
- 3/4.
- 4/4.
- 6/8.
- 9/8.
- 12/8.
- 5/4.
- 7/8.

Default groupings:

- 2/4 → `2`.
- 3/4 → `3`.
- 4/4 → `4`.
- 6/8 → `3+3` denominator units.
- 9/8 → `3+3+3`.
- 12/8 → `3+3+3+3`.
- 5/4 → no forced single default grouping if evidence is ambiguous; retain candidates such as `3+2` and `2+3`.
- 7/8 → retain plausible groupings such as `2+2+3`, `2+3+2`, and `3+2+2`.

Groupings are notation/metrical interpretations, not changes to source audio.

### 10.4 Hypothesis scoring

For each region/candidate:

1. Align candidate bar starts to plausible downbeat pulses.
2. Score downbeat activation at bar starts.
3. Score beat activation consistency.
4. Score accent agreement with primary pulse/group boundaries.
5. Score subdivision evidence.
6. Score bar-duration stability relative to tempo anchors.
7. Penalize implausible missing/extra pulses.
8. Penalize unnecessary meter changes.
9. Record the total and component scores for diagnostics.

Do not expose the combined score as a calibrated probability unless separately calibrated.

### 10.5 Sequence decoding

Use a deterministic dynamic-programming/Viterbi-style sequence decoder over candidate meter regions.

The decoder must:

- permit meter changes;
- discourage rapid unsupported switching;
- require changes at candidate bar boundaries;
- preserve multiple close alternatives;
- emit `uncertain` when evidence margin is inadequate;
- permit an `unmetered` state rather than forcing a candidate.

### 10.6 Confidence alternatives

For each automatic meter region, retain:

- selected candidate;
- runner-up candidates;
- score margin;
- evidence summary;
- confidence kind/method/calibration flag.

### 10.7 Manual meter entry

The user may enter a meter not in the automatic set.

Validation:

1. Numerator > 0.
2. Denominator > 0. Preserve nonstandard positive denominators rather than silently coercing them to a power of two.
3. Grouping parts are positive.
4. Grouping sum equals numerator.
5. Region begins at a bar boundary.
6. Display tempo unit is compatible with the chosen grouping.

### 10.8 Meter-region boundaries

1. A meter region starts on an explicit bar boundary.
2. Its end is the next meter-region start or project/grid end.
3. Dragging a boundary snaps to valid bar boundaries.
4. A command that would create a non-bar boundary is rejected.
5. Moving a tempo anchor may change the source-frame location of a meter boundary because the boundary is musical-position anchored.

### 10.9 Irregular meter grouping

Grouping affects:

- primary beat positions;
- accent strengths;
- ruler emphasis;
- count-in accents;
- subdivision labels;
- musical readout.

It does not change the denominator-unit duration implied by the tempo map.

### 10.10 Meter uncertainty UI

Automatic uncertain regions:

- use text/hatching in addition to color;
- show alternative meters in the inspector;
- permit one-click selection of an alternative as a manual correction;
- preserve the original automatic choice and scores.

**Acceptance:** meter inference remains separate from beat detection, supports simple/compound/irregular candidates, exposes ambiguity, and permits arbitrary manual correction at bar boundaries.

---

## 11. Work package M3.9 — Construct bars, beats, subdivisions, first downbeat, and pickups

### 11.1 Derived grid

Do not persist every visual grid line as an independent database object.

Derive visible grid events from:

- active tempo map;
- active meter regions;
- bar-origin state;
- requested musical-position range/detail level.

Derived event types:

- bar boundary;
- primary beat/pulse;
- denominator-unit subdivision;
- half-beat;
- quarter-beat;
- optional finer visual subdivision at high zoom.

### 11.2 Deterministic musical-to-source conversion

For each requested grid musical position:

1. Locate the containing tempo-map segment by musical position.
2. Interpolate source position.
3. Preserve a fractional source position internally for rendering.
4. Round to integer source frame only for edit/snap targets.
5. Use one documented rounding rule in backend and frontend.

### 11.3 Shared mapping implementation

Implement equivalent pure mapping libraries in:

- Python backend/domain layer;
- TypeScript frontend/editor layer.

Create shared golden-vector fixtures containing:

- anchors;
- meters;
- musical positions;
- expected source-frame outputs;
- expected inverse mappings;
- bar/beat labels.

Both implementations must pass the same vectors.

Do not rely on hand-maintained duplicated behavior without cross-language tests.

### 11.4 First downbeat

Provide a command `Set first downbeat` that:

1. Selects an existing pulse or an explicit source position.
2. Marks/creates the required downbeat pulse in the editable branch.
3. Establishes bar-phase origin.
4. Preserves source timing.
5. Recomputes bar labels around the origin.
6. Does not automatically delete earlier pulses.

### 11.5 First numbered bar

Allow:

- default first full bar number `1`;
- arbitrary integer number for excerpts or imported references.

Changing the display number:

- does not change musical position spacing;
- does not change source timing;
- is undoable.

### 11.6 Pickup bars

Support partial material before the first complete numbered bar.

Represent pickup state by musical span and bar phase, not by padding the audio.

Behavior:

1. User chooses/edits the first complete bar downbeat.
2. Earlier mapped material can be marked as pickup.
3. A pickup may be shorter than the full meter length.
4. Multiple leading partial/unnumbered bars may be represented when needed for an excerpt.
5. Ruler labels them clearly as pickup/lead-in rather than pretending they are full bar 1.
6. Count-in uses the active bar phase at the loop start even when the project begins with a pickup.

### 11.7 Bar phase through meter changes

At a meter change:

- the new region starts at beat 1 of a new bar;
- bar numbering continues unless manually reset by a future feature;
- the new grouping applies from that boundary onward.

### 11.8 Unmapped gaps

If a grid has an unmapped region:

- stop drawing derived musical lines through the gap;
- show a visible `No grid`/uncertain region indication;
- do not generate snap targets there;
- do not schedule metronome clicks there;
- resume when a later mapped region is explicitly anchored.

### 11.9 Visible-grid generation

Generate only the visible musical range plus a margin.

The frontend requests/derives detail based on zoom:

- far zoom: bar lines only;
- medium zoom: bars + primary beats;
- closer zoom: denominator units/subdivisions;
- very close zoom: optional half/quarter-beat snap lines.

Do not allocate every subdivision for an hour-long project into React state.

**Acceptance:** bar/beat/subdivision positions remain aligned with the tempo map through pickups, meter changes, tempo ramps, and zoom changes.

---

## 12. Work package M3.10 — Implement manual rhythm, anchor, and meter editing

### 12.1 Editing modes

Add editor interactions for:

- pulses;
- downbeat classification;
- tempo anchors;
- meter regions;
- bar origin/pickup state.

Keep selection separate from seek behavior as established previously.

### 12.2 Add beat/pulse

1. User invokes Add Beat at playhead/cursor.
2. Optional snapping is applied only to this edit.
3. Create a manual pulse.
4. Ask/derive its intended musical position from neighboring grid context.
5. Create/link a tempo anchor when needed to preserve mapping.
6. Validate monotonicity.
7. Commit as one command.

### 12.3 Move beat/pulse

Default behavior for an automatically linked pulse/anchor:

1. Drag pulse in source time.
2. Preserve its musical position.
3. Move the linked unlocked tempo anchor to the same source frame.
4. Recalculate adjacent local tempo segments.
5. Reject crossing a neighboring pulse/anchor.
6. Commit one command on pointer release.

If the linked anchor is locked, require explicit unlock/confirmed override rather than silently detaching it.

### 12.4 Delete beat/pulse

For a linked automatic/manual beat:

- default action removes the pulse and linked unlocked anchor from the edited branch;
- recompute mapping between neighboring anchors;
- preserve immutable parent data;
- reject deletion if it would leave a required mapped interval invalid without warning;
- allow undo.

### 12.5 Change downbeat

1. Select a pulse.
2. Toggle/assign downbeat role.
3. Recompute meter/bar-phase consistency.
4. Surface incompatible meter boundaries.
5. Do not move the pulse.
6. Preserve automatic downbeat evidence in provenance.

### 12.6 Insert tempo anchor

1. Choose source position.
2. Infer the musical position from the existing map as the initial value.
3. Let the user edit musical position if needed.
4. Insert between neighboring anchors.
5. Validate both dimensions are monotonic.
6. Mark as manual.
7. Leave pulse set unchanged unless user explicitly creates a beat there.

### 12.7 Move tempo anchor

Allow two explicit edit modes:

- move source position while preserving musical position;
- change musical position while preserving source position.

Do not infer which axis the user intended from a text-field edit.

### 12.8 Lock/unlock tempo anchor

- Lock prevents automatic reflow/reinterpretation from moving it.
- Unlock allows region operations to adjust it.
- Manual direct movement is still possible after explicit user action.
- Lock state is visible in the lane.

### 12.9 Delete tempo anchor

1. Remove anchor from editable branch.
2. If linked pulse remains, clear its link.
3. Interpolate across neighboring anchors.
4. Validate resulting local BPM/mapping.
5. Warn if a large unsupported span results.

### 12.10 Edit meter region

Support:

- change numerator;
- change denominator;
- change grouping;
- choose automatic alternative;
- insert region at bar boundary;
- move region boundary to another bar boundary;
- delete a region and extend neighbor interpretation.

### 12.11 Edit first bar/pickup

Commands:

- set first downbeat;
- set first numbered bar;
- mark/unmark pickup;
- adjust pickup start/phase where valid.

### 12.12 Apply half/double-time

Expose an explicit command on selected mapped range.

Do not hide this inside a BPM text field.

### 12.13 Batch review

Provide:

- accept current automatic pulse/meter region;
- mark corrected;
- next/previous uncertain pulse;
- next/previous uncertain meter region.

### 12.14 Command semantics

Every semantic correction:

- carries command ID;
- carries idempotency key;
- carries base project revision;
- validates against current active branch;
- commits transactionally;
- increments project revision;
- records before/after state;
- is undoable/redoable.

A drag gesture is one command.

### 12.15 Conflict behavior

If a stale browser tab edits an outdated rhythm branch:

- reject with `409`;
- return current revision metadata;
- do not merge silently;
- allow the frontend to reload and preserve the user's uncommitted intended values for manual retry where practical.

**Acceptance:** the user can repair a bad automatic grid locally without destructive global quantization, and every correction survives undo/redo and restart.

---

## 13. Work package M3.11 — Add the rhythm lanes and musical ruler

### 13.1 Editor layout additions

Add above the waveform tracks:

- musical ruler;
- tempo lane;
- meter lane;
- optional beat/downbeat lane;
- rhythm confidence/review controls.

All use the existing horizontal viewport.

### 13.2 Musical ruler layers

Render with separate canvas/DOM layers as appropriate:

1. Bar lines/labels.
2. Primary beat lines.
3. Subdivision lines.
4. Meter-region labels.
5. Tempo labels/curve summaries.
6. Downbeat/pulse markers.
7. Selection/hover/edit handles.

Do not force waveform redraw on every rhythm hover.

### 13.3 Zoom-dependent detail

At distant zoom:

- show sparse bar numbers;
- suppress overlapping labels.

At medium zoom:

- show every bar and primary beat.

At close zoom:

- show denominator/subdivision lines;
- show exact pulse/anchor handles.

At sample-level zoom:

- preserve source-frame alignment;
- do not pretend the musical mapping has sub-sample precision.

### 13.4 Tempo lane

Display:

- local tempo derived from anchor segments;
- anchor handles;
- lock state;
- discontinuities/meter changes;
- uncertain/unmapped spans.

Do not draw a smoothed curve that implies a tempo model different from the actual piecewise mapping unless clearly labeled as display-only.

### 13.5 Meter lane

Display:

- meter label;
- grouping, e.g. `7/8 (2+2+3)`;
- region boundaries;
- automatic uncertainty;
- selected alternative candidates in inspector.

### 13.6 Beat/downbeat lane

Visual rules:

- downbeats emphasized;
- accepted beats distinct from low-confidence candidates;
- manual/corrected pulses identifiable without relying only on color;
- rejected candidates hidden by default but inspectable.

### 13.7 Interaction hit testing

Use viewport-space hit testing with a minimum practical handle width.

Priority near overlapping objects:

1. Active dragged handle.
2. Tempo anchor handle.
3. Meter boundary.
4. Pulse/downbeat marker.
5. Bar/beat ruler.
6. Waveform background.

Provide keyboard alternatives for precise edits.

### 13.8 Inspector

For selected rhythm object, show relevant fields:

- source time/frame;
- musical position/bar/beat;
- automatic vs manual origin;
- confidence type/value/calibration state;
- linked pulse/anchor;
- meter/grouping;
- local quarter-note BPM;
- displayed pulse BPM/unit;
- parent automatic value where corrected;
- review state.

### 13.9 Performance

1. Keep full anchor/pulse collections outside transient React render state where practical.
2. Derive only visible ruler primitives per frame/viewport change.
3. Cache segment searches.
4. Use binary search for source↔musical lookup.
5. Avoid O(total_song_beats) work on every animation frame.
6. Redraw static musical-grid layers only when viewport/grid changes, not on every playhead update.

**Acceptance:** tempo, meter, pulses, bar lines, waveforms, selections, loops, and playhead remain visually aligned at every zoom level.

---

## 14. Work package M3.12 — Implement musical snapping

### 14.1 Snap modes

Support exactly the main plan modes:

- Off.
- Beat.
- Half-beat.
- Quarter-beat.
- Bar.
- Nearest event boundary.

### 14.2 Visual-radius semantics

Use approximately eight CSS pixels as the snap radius.

Algorithm:

1. Convert the 8 CSS-pixel radius to a source-frame tolerance using the current viewport scale.
2. Generate candidate targets near the pointer/edit position only.
3. Measure distance in screen/source position consistently.
4. Snap only when the nearest eligible target is within the radius.
5. Otherwise preserve the user's unsnapped position.

Do not use a fixed millisecond radius because it would feel inconsistent across zoom levels.

### 14.3 Beat target definition

`Beat` snapping targets the active meter region's primary beat/group pulse, not necessarily every denominator unit.

Examples:

- 4/4 default grouping: quarter-note beats.
- 6/8 `3+3`: dotted-quarter primary beats.
- 7/8 `2+2+3`: grouping boundaries.

### 14.4 Half/quarter-beat target definition

Subdivide the local primary beat interval in musical position space.

Then map those exact subdivision positions to source frames through the tempo map.

This keeps snapping correct under variable tempo.

### 14.5 Bar snapping

Snap to derived bar boundaries only in valid metered regions.

No bar target exists in `unmetered` or `unmapped` spans.

### 14.6 Event-boundary snapping

Initially include already implemented source-time boundaries such as:

- markers;
- loop starts/ends;
- selection boundaries;
- rhythm pulses/anchors where applicable.

Future milestones may add chord/note boundaries without changing the snapping architecture.

### 14.7 Temporary override

Provide a platform-appropriate modifier that temporarily inverts snapping for the active drag:

- if snapping is enabled, modifier disables it;
- if snapping is off, modifier may temporarily enable the last non-Off mode.

Document the exact key after frontend shortcut conventions are finalized.

### 14.8 No retroactive quantization

Changing snap mode:

- does not move existing markers;
- does not move existing source loops;
- does not move existing pulses;
- does not move future chord/note events;
- affects only the edit currently being performed.

### 14.9 Server validation

The frontend resolves the snapped source frame for responsive interaction.

The backend:

- validates submitted source/musical positions;
- does not trust an arbitrary browser-provided bar number as authoritative;
- recomputes bar/beat context when needed for validation;
- rejects invalid musical-loop or meter boundaries.

**Acceptance:** snapping feels visually consistent under zoom and variable tempo, and enabling it never alters existing edits by itself.

---

## 15. Work package M3.13 — Add musical/beat-anchored loops

### 15.1 Preserve Milestone 2 loops

Existing loops remain source-anchored by default.

Their start/end source frames do not move when the tempo map is corrected.

### 15.2 Extend loop schema

Add:

- `anchor_mode`: `source` or `musical`.
- For musical mode: start `MusicalPosition` and end `MusicalPosition`.
- Cached/resolved source-frame boundaries for current active grid revision.
- Grid/rhythm branch reference/revision used for the last resolution.

Only one coordinate pair is authoritative according to `anchor_mode`.

### 15.3 Create musical loop

Allow:

1. Select bars/beats in the musical ruler.
2. Create loop from selected musical range.
3. Store musical positions.
4. Resolve to source boundaries through the active map.
5. Preserve exact musical positions through later tempo-anchor edits.

### 15.4 Convert source loop to musical loop

Explicit action:

1. Resolve current source boundaries to musical positions.
2. Display proposed bar/beat positions.
3. Require user confirmation if either boundary is not close to a meaningful grid point.
4. Store musical positions.
5. Change anchor mode as one undoable command.

Do not silently convert all old loops.

### 15.5 Convert musical loop to source loop

1. Resolve current musical boundaries to source frames.
2. Store those source frames as authoritative.
3. Change anchor mode.
4. Future grid edits no longer move it.

### 15.6 Grid edits and musical loops

After any tempo-map edit:

1. Invalidate cached source boundaries for musical loops.
2. Resolve using the updated active rhythm branch.
3. Preserve start/end musical positions.
4. Rebuffer if the active loop boundaries move during playback.
5. Apply boundary changes at a controlled transport transition.

### 15.7 Grid-version switching

When switching Auto/Edited rhythm versions:

- source loops do not move;
- musical loops resolve through the newly active grid;
- if the requested musical range is not mapped in the new grid, disable loop playback and show a clear unresolved-loop state rather than guessing.

### 15.8 Variable-tempo loop behavior

The loop engine continues to operate in source frames after resolving boundaries.

Metronome events inside the loop come from musical grid events and follow each iteration.

At all playback speeds:

- no cumulative source-boundary drift;
- no cumulative metronome-phase drift;
- loop repeat count semantics remain total passes as defined in Milestone 2.

**Acceptance:** the user can choose whether a loop stays fixed to audio samples or follows the corrected musical grid, and both modes remain stable through save/open and variable-speed playback.

---

## 16. Work package M3.14 — Implement the synchronized metronome

### 16.1 Architectural placement

Use the existing single AudioContext and AudioWorklet.

Logical output path:

```text
Aligned source/stem reader
        ↓
Mixer
        ↓
Signalsmith Stretch or aligned 1× bypass
        ↓
Metronome click generator/scheduler
        ↓
Master gain / monitoring limiter
        ↓
Audio output
```

The metronome is scheduled against the same output/render clock and source→output mapping as the audio being heard.

### 16.2 Why clicks are after stretching

Clicks represent practice timing, not source audio.

Placing them after the stretcher means:

- click pitch/timbre is not stretched;
- click timing follows source musical events through the transport mapping;
- speed changes alter click spacing but not click sound;
- metronome latency can be accounted for in the same output domain as audible playback.

### 16.3 Click generation

Generate click sounds locally with project-owned procedural buffers/tables.

Provide at least:

- normal beat click;
- stronger downbeat click;
- optional grouping accent.

Requirements:

1. Precompute click waveform tables outside the audio callback.
2. No network assets.
3. No filesystem access in the callback.
4. No unbounded allocation.
5. Independent metronome volume.
6. Short click duration to avoid masking practice audio excessively.

Exact click timbre is a UI/audio-design parameter, not analysis state.

### 16.4 Grid event schedule

For a bounded lookahead window:

1. Determine upcoming musical grid events from the active tempo/meter map.
2. Convert event musical positions to source positions.
3. Convert source positions into output render positions using the active transport ledger/rate behavior.
4. Send a bounded schedule to the AudioWorklet.
5. Generate clicks at render-frame positions.
6. Discard schedule entries from stale transport generations.

Do not schedule from `setInterval`, `requestAnimationFrame`, or React timers.

### 16.5 Event strengths

Assign click accent level from meter/grouping:

- bar downbeat: strongest;
- primary grouping/beat: normal or secondary accent;
- subdivision: optional weaker click.

For 6/8 `3+3`:

- beat/group starts at 1 and 4 denominator units receive primary pulse emphasis;
- bar start receives downbeat emphasis.

For 7/8 `2+2+3`:

- grouping starts receive optional secondary accents.

### 16.6 Metronome subdivisions

Support:

- primary beats only;
- denominator units where musically distinct;
- selected subdivisions supported by the current grid.

Do not allow a subdivision mode that the local musical position resolution cannot represent exactly without documenting the rounding behavior.

### 16.7 Playback-speed changes

When speed changes:

1. Invalidate future scheduled click events beyond a safe committed render horizon.
2. Recompute source→output mapping for future events.
3. Preserve already committed near-term clicks to avoid double-triggering.
4. Use the transport generation/rate-transition ledger.
5. Verify no phase jump in repeated steady beats.

### 16.8 Seek behavior

On seek:

1. Increment transport generation as already defined.
2. Drop old metronome schedule.
3. Resolve the new musical position.
4. Rebuild upcoming grid events.
5. Do not replay clicks that occurred before the seek target.

### 16.9 Loop behavior

For each loop iteration:

- include iteration identity in scheduled event bookkeeping;
- schedule clicks from resolved grid events inside the loop;
- handle loop-wrap discontinuity explicitly;
- do not accumulate fractional output-rounding error independently each pass.

### 16.10 Unmapped/uncertain regions

- `valid`: schedule normal metronome.
- `uncertain`: permit clicks but show uncertainty; user may disable.
- `unmetered`: permit neutral quarter/pulse clicks if a tempo map exists; no bar accent.
- `unmapped`: schedule no clicks.

### 16.11 Metronome state

Persist:

- enabled/disabled.
- volume.
- click pattern/subdivision.
- grouping-accent preference.

Do not put the momentary next-click position in project history.

### 16.12 Monitoring limiter

Metronome passes through the existing monitoring limiter/master output path as appropriate.

It must not affect raw stem assets or exports.

### 16.13 Offline/internal timing test mode

Provide a deterministic test harness that renders/records the metronome event schedule against a synthetic transport ledger without relying on physical audio hardware.

Use it to compare expected source musical positions to actual render click frames.

**Acceptance:** metronome clicks follow corrected variable tempo, meter grouping, speed changes, seeks, and loop wraps without cumulative phase drift.

---

## 17. Work package M3.15 — Implement one-/two-bar count-in

### 17.1 Count-in settings

Support:

- Off.
- One bar.
- Two bars.
- Apply once when playback/repeat sequence starts.
- Apply before every loop repeat.

Default: Off.

### 17.2 Transport phase

Extend transport state with an explicit count-in phase.

During count-in:

- source position is held at the intended playback start;
- source/stem audio is silent/not consumed;
- metronome clicks advance in output time;
- UI shows count-in status/count;
- transport ledger records a non-source-advancing phase so audible-position mapping remains well-defined.

Count-in is not inserted into project source time.

### 17.3 Determine active meter and tempo

At the intended playback/loop start:

1. Resolve exact source position.
2. Map to musical position.
3. Resolve active meter region.
4. Resolve grouping.
5. Resolve local tempo from the tempo map.
6. Apply current playback-speed scaling to output timing.

If meter is unavailable:

- disable bar-count count-in with an explanation;
- do not guess 4/4.

### 17.4 Count into a loop starting on beat 1

For a loop starting at a bar downbeat:

- generate one or two complete virtual bars using the local tempo active at the target start;
- finish immediately before the target downbeat;
- begin source playback on the target downbeat.

### 17.5 Count into a loop starting mid-bar

For a loop starting on another valid beat:

1. Determine its bar phase/grouping position.
2. Build a count sequence whose final phase leads into that exact beat.
3. Preserve meter accents across the virtual count sequence.
4. Start source playback at the stored loop boundary.
5. Do not move the loop to beat 1.

### 17.6 Off-grid loop starts

A source-anchored loop may start between grid events.

In that case:

- do not silently snap the loop;
- display that count-in targets an off-grid start;
- use the local musical position to create a lead-in ending at the exact source boundary;
- omit a misleading `beat 1` claim.

The user can explicitly snap/convert the loop if desired.

### 17.7 Project-start boundary

If insufficient real pre-start grid context exists:

- count-in remains possible because it is output-only;
- synthesize virtual pre-roll intervals from the local tempo/meter at the target;
- mark this as virtual count-in timing, not source-derived past audio.

### 17.8 Variable tempo near the start

Count-in follows the main plan's rule: use the **local tempo at the intended playback/loop start**.

Therefore:

- resolve the local tempo from the active tempo-map segment at the target source position;
- hold that tempo constant for the one- or two-bar count-in;
- apply the current playback-speed scaling;
- preserve the correct meter/grouping phase for the target beat;
- do not replay an earlier source tempo ramp during count-in;
- keep the source position fixed until playback begins.

This makes count-in predictable even when the song accelerates or slows immediately before the loop start.

### 17.9 Before-every-repeat behavior

At loop end:

1. Finish the current source pass.
2. Enter count-in phase.
3. Reset/prepare loop source buffers and stretcher state according to the existing loop engine.
4. Emit the selected count-in bars.
5. Start the next source pass at the exact loop start.
6. Increment loop iteration only when the source pass begins, not for count-in time.

### 17.10 Finite repeat counts

Repeat count remains total source passes.

Count-in phases do not count as passes.

After the last pass:

- stop at loop end according to Milestone 2 semantics;
- do not add an extra count-in.

### 17.11 User cancellation

During count-in:

- Pause stops count-in and preserves the intended source start.
- Stop cancels count-in and resets as normal.
- Seek cancels the current count-in and resolves a new target.
- Disabling loop or metronome updates future count-in behavior coherently.

### 17.12 UI

Show:

- count-in enabled state;
- one/two bars;
- once/every-repeat;
- current count position during count-in;
- active meter/grouping;
- a warning when bar-count count-in is unavailable.

**Acceptance:** count-in leads into correct musical phase at any supported speed, including mid-bar loop starts, without modifying source time or loop boundaries.

---

## 18. Work package M3.16 — Musical readout, navigation, selection, and shortcuts

### 18.1 Musical readout

Extend the source-time readout to include:

```text
01:32.481 | Bar 42 Beat 3.27 | — | —
```

Until later milestones provide note/chord context, use unavailable placeholders for those fields rather than invented values.

### 18.2 Readout source

Use the latency-compensated audible source position already provided by the transport.

Then:

1. Map source position to musical position through the active rhythm branch.
2. Resolve meter region.
3. Resolve bar number.
4. Resolve primary-beat index and fractional position.
5. Resolve local tempo and display unit.

### 18.3 Compound/irregular readout

For meters where `Beat` could be ambiguous:

- show meter and grouping in the detailed inspector;
- define the compact `Beat` number as the primary grouping pulse;
- show denominator-unit/subdivision position on hover/inspector when needed.

For 6/8 `3+3`, the compact beat index is 1–2 primary pulses, while detailed view can show eighth-note phase 1–6.

### 18.4 Unknown regions

If the playhead is in:

- `unmapped`: show `No grid`.
- `unmetered`: show musical position/tempo if available but no bar number.
- `uncertain`: show the best interpretation with an uncertainty indicator.

### 18.5 Shift+left/right bar seek

Implement the planned shortcut only when a valid grid exists.

Behavior:

- Shift+Left: seek to previous bar boundary.
- Shift+Right: seek to next bar boundary.
- Near project edges: clamp to valid project bounds.
- In unmapped region: show no-grid feedback rather than guessing.

### 18.6 Metronome shortcut

`M` toggles metronome when focus is not inside a text field.

If the grid cannot support the requested click mode:

- show why;
- preserve the user's configured setting for later valid regions.

### 18.7 Linked selection

Extend the shared selection model:

- selecting a bar highlights its source-time range;
- selecting a beat highlights its source position/context;
- selecting a waveform range highlights intersecting bars/pulses;
- related highlights remain non-edit targets until explicitly selected.

### 18.8 Loop creation from musical selection

When a bar/beat selection exists:

- offer `Create musical loop`;
- preserve exact musical positions;
- resolve through active grid.

### 18.9 Accessibility

1. Do not communicate downbeat/uncertainty by color alone.
2. Provide keyboard selection for rhythm objects.
3. Expose bar/meter/tempo labels to assistive technology where DOM semantics permit.
4. Keep focus visible during lane editing.
5. Announce rejected invalid edits with actionable text.

**Acceptance:** source-time and musical readout follow audible playback, and bar navigation/selection work without changing the transport clock.

---

## 19. Work package M3.17 — API, worker, and frontend contract additions

### 19.1 Module identifiers

Add stable module IDs for at least:

- Beat/downbeat activation inference.
- Pulse decoding.
- Tempo-map derivation.
- Meter inference.
- Rhythm pipeline (`Analyze Rhythm`) orchestration.

Individual modules remain invocable where prerequisites exist.

### 19.2 Run graph

Default `Analyze Rhythm` pipeline:

```text
reference mix
    ↓
Beat This! activations
    ↓
pulse decoding
    ↓
tempo-map construction
    ↓
meter inference
    ↓
validated automatic rhythm result
```

Meter inference may consume accent/subdivision evidence in parallel after input preparation.

### 19.3 Project run API

Reuse:

`POST /api/v1/projects/{id}/runs`

Request declares:

- module/pipeline ID;
- input role/result ID;
- model preset;
- device preference;
- decoder/meter profile;
- optional force-rerun flag.

Response returns durable job/run identity.

### 19.4 Rhythm-result APIs

Add:

| Interface | Purpose |
|---|---|
| `GET /api/v1/projects/{id}/rhythm-results` | List immutable automatic rhythm results |
| `GET /api/v1/projects/{id}/rhythm-results/{result_id}` | Result summary/provenance |
| `GET /api/v1/projects/{id}/rhythm-branches` | List editable branches |
| `GET /api/v1/projects/{id}/rhythm-branches/{branch_id}` | Active editable grid data |
| `GET /api/v1/rhythm-activations/{artifact_id}` | Bounded activation-range access for diagnostics/review |

Keep large activation arrays out of normal project snapshots.

### 19.5 Bounded activation endpoint

Parameters:

- activation kind: beat/downbeat;
- start model frame;
- frame count.

Rules:

1. Authenticate.
2. Validate artifact belongs to an accessible local project/result.
3. Limit response size.
4. Return float32 little-endian binary or another explicitly versioned compact binary form.
5. Return alignment metadata in headers/companion JSON.
6. Reject stale/missing artifacts cleanly.

The regular UI does not fetch the whole song's activation arrays by default.

### 19.6 Project commands

Add command types for:

- Select rhythm result.
- Select rhythm branch/Auto vs Edited.
- Add/move/delete pulse.
- Change pulse downbeat role.
- Mark pulse reviewed.
- Insert/move/delete tempo anchor.
- Lock/unlock tempo anchor.
- Apply half-time/double-time interpretation.
- Set first downbeat.
- Set first numbered bar.
- Set/update pickup state.
- Insert/update/delete meter region.
- Set meter grouping.
- Select meter alternative.
- Set snap mode.
- Set metronome enabled.
- Set metronome volume/subdivision/accent settings.
- Set count-in bars/mode.
- Create/update/delete/convert musical loop.

Continue revision/idempotency behavior from earlier milestones.

### 19.7 Frontend domain services

Add non-React services/modules:

- `MusicalMap` source↔musical-position mapping.
- `MeterMap` bar/beat resolution.
- `GridGenerator` visible grid primitives.
- `SnapResolver`.
- `MetronomeScheduleBuilder`.
- `RhythmBranchStore` or equivalent editor state owner.

React components consume these services; they do not reimplement mapping arithmetic.

### 19.8 Transport interface extensions

Extend the frontend audio engine with methods similar to:

- `setMusicalGrid(...)` or compact schedule source.
- `setMetronomeState(...)`.
- `setCountIn(...)`.
- `prepareCountInAndPlay(...)`.
- `invalidateGridSchedule(revision)`.

Keep worklet message details private to the audio-engine layer.

### 19.9 Worker protocol

Reuse the existing job messages where compatible:

- `run`.
- `progress`.
- `completed`.
- `failed`.
- `cancel`.
- `cancelled`.

Declare rhythm-specific request/result schemas in module capabilities.

Increment protocol version only if existing message semantics actually change.

### 19.10 Generated contracts

After schema changes:

1. Regenerate OpenAPI.
2. Regenerate project JSON Schema.
3. Regenerate relevant worker schemas.
4. Regenerate TypeScript API types.
5. Run contract-drift checks.
6. Keep generated files deterministic.

**Acceptance:** backend, worker, browser editor, and audio engine share versioned rhythm contracts with no hand-built endpoint/type divergence.

---

## 20. Work package M3.18 — Cache identity, persistence, autosave, and portable projects

### 20.1 Activation cache key

Include:

- input/reference asset hash;
- source role/downmix identity;
- Beat This! model manifest and weight hash;
- adapter version;
- preprocessing profile/version;
- precision/numerical profile where relevant;
- analysis interval/context profile.

### 20.2 Decoder cache key

Include:

- activation artifact hash;
- decoder implementation/profile version;
- decoder parameters.

Changing pulse postprocessing should not require neural inference again.

### 20.3 Tempo-map automatic cache key

Include:

- decoded accepted-pulse artifact/version;
- tempo-map algorithm/profile;
- pulse-unit hypothesis profile;
- meter evidence dependency where jointly decoded.

### 20.4 Meter cache key

Include:

- activation/decoded pulse identities;
- tempo-map hypothesis/result identity;
- accent/subdivision feature artifact hash;
- meter candidate/profile version;
- transition-penalty profile.

### 20.5 Manual branch persistence

Manual edits are project state, not disposable analysis cache.

Protect:

- rhythm branch records;
- command history;
- source/musical loop anchors;
- active result selection;
- metronome/count-in settings;
- rhythm view state.

Do not evict them under the analysis cache budget.

### 20.6 Working autosave

Commit semantic rhythm commands immediately.

Debounce only view-state fields such as:

- rhythm-lane height;
- visibility;
- last inspector section;
- review filter.

### 20.7 Interrupted analysis recovery

After restart:

- completed activation artifacts remain reusable;
- completed pulse decode remains reusable;
- completed tempo/meter stages remain reusable;
- interrupted current stage becomes interrupted and can restart;
- edited branches remain intact;
- no partial artifact becomes an active result.

### 20.8 Portable project contents

Extend portable save to include:

- automatic rhythm result records;
- editable rhythm branches;
- accepted/candidate pulse data;
- tempo anchors;
- meter regions/groupings;
- bar-origin/pickup state;
- Beat This! run/model provenance;
- metronome/count-in settings;
- source/musical loop anchor data;
- relevant compact rhythm feature artifacts;
- activation artifacts by default under the main plan's analysis-artifact policy, with explicit optional/essential classification.

### 20.9 Essential versus optional rhythm assets

For reopening and practice, essential:

- active rhythm branch/result data;
- tempo anchors;
- meter regions;
- loop anchors;
- project command state.

Rebuildable/optional for practice:

- raw activation arrays;
- auxiliary accent-feature arrays;
- nonactive automatic alternatives.

If optional raw arrays are missing/corrupt:

- retain corrected grid and metronome functionality;
- report reduced re-decoding/review capability;
- do not rerun the model automatically.

### 20.10 Model exclusion

Do not include Beat This! weights or the Python environment in `.basseparate` archives.

### 20.11 Reopen with no model/network

On reopen:

1. Restore active rhythm state.
2. Restore musical loops.
3. Rebuild in-memory mapping indices.
4. Restore metronome/count-in configuration.
5. Remain paused.
6. Permit immediate ruler display and practice playback.
7. Do not check internet/model availability unless the user starts a new analysis.

### 20.12 Cache eviction

Analysis cache cleanup may remove only unreferenced rebuildable automatic artifacts.

Protect artifacts referenced by:

- active projects;
- portable save jobs;
- retained analysis versions;
- edit-branch provenance where required for user review.

**Acceptance:** corrected rhythm projects reopen fully offline and preserve practice behavior even when model files and nonessential raw analysis caches are absent.

---

## 21. Work package M3.19 — Build the rhythm test corpus and automated verification

### 21.1 Deterministic synthetic audio fixtures

Generate local fixtures for:

1. 4/4 clicks at constant tempo.
2. 3/4 clicks at constant tempo.
3. 6/8 with `3+3` grouping.
4. 9/8 and 12/8 compound grouping.
5. 5/4 with at least two grouping patterns.
6. 7/8 with `2+2+3`, `2+3+2`, and `3+2+2`.
7. Linear tempo ramp.
8. Piecewise tempo jump.
9. Humanized/rubato timing around a known map.
10. Half-time/double-time ambiguity.
11. Pickup before bar 1.
12. Project start in the middle of a bar.
13. Meter change 4/4 → 3/4.
14. Meter change 4/4 → 6/8.
15. Long silent intro then rhythm.
16. Internal silent break.
17. Pure silence.
18. Strong syncopation with known downbeats.
19. Click track with intentionally missing beats.
20. Click track with intentionally extra offbeat transients.
21. Long 60-minute variable-tempo fixture generated during tests.

Do not commit unnecessarily large generated audio.

### 21.2 Golden mapping fixtures

Create non-audio fixtures containing:

- project sample rate;
- source length;
- tempo anchors;
- meter regions;
- expected musical positions at source frames;
- expected source frames at musical positions;
- expected bar/beat labels;
- pickup labels;
- expected snap targets.

Use them in both Python and TypeScript test suites.

### 21.3 Activation mapping tests

Verify:

1. First model frame maps correctly.
2. Middle frames map correctly.
3. Final frame remains within source duration.
4. Resampled inputs map back correctly.
5. Chunked inference output does not duplicate frames.
6. Frame arrays remain finite.
7. Model-frame collisions after source rounding are handled deterministically.

### 21.4 Pulse decoder tests

Test:

- accepted beats;
- downbeats;
- low-confidence candidates;
- no-pulse silence;
- duplicate/collision handling;
- deterministic decoder profile identity;
- re-decoding from existing activation artifact with model absent.

### 21.5 Tempo-map unit tests

Verify:

1. Strict monotonicity.
2. Forward/inverse mapping agreement.
3. Exact anchor round-trip.
4. Interpolated round-trip within defined frame rounding tolerance.
5. Constant tempo.
6. Tempo ramp anchors.
7. Half-time reinterpretation.
8. Double-time reinterpretation.
9. Locked-anchor constraints.
10. Insert/move/delete anchor.
11. Invalid crossing edits rejected.
12. Sparse map behavior.
13. Unmapped intervals.
14. Project-edge behavior.

### 21.6 Meter tests

Verify:

- candidate generation for the eight initial automatic meters;
- compound grouping;
- irregular grouping;
- alternative retention;
- transition penalty behavior;
- explicit uncertain/unmetered outcome;
- manual arbitrary meter entry;
- grouping sum validation;
- meter changes only at bar boundaries.

### 21.7 Bar/pickup tests

Verify:

1. First downbeat at source start.
2. First downbeat after source start.
3. Pickup shorter than one bar.
4. Multiple leading partial/unmapped regions.
5. Arbitrary first displayed bar number.
6. Bar numbering through meter change.
7. Derived bars through tempo ramp.
8. No bars through unmapped gap.

### 21.8 Editing/undo tests

For every new command:

- apply;
- persist;
- undo;
- redo;
- reopen;
- verify equivalent state.

Include stale-revision conflict tests for concurrent tabs.

### 21.9 Snapping tests

Test each snap mode under:

- far zoom;
- medium zoom;
- close zoom;
- constant tempo;
- variable tempo;
- 6/8;
- 7/8 grouping;
- no grid;
- near-but-outside 8-pixel radius;
- modifier override.

Verify existing objects never move merely because snap mode changes.

### 21.10 Musical-loop tests

Verify:

- source loop unaffected by grid edit;
- musical loop follows tempo-anchor edit;
- conversion source→musical;
- conversion musical→source;
- unresolved grid state disables musical-loop playback safely;
- save/open retains anchor mode;
- variable-speed repeats do not drift.

### 21.11 Metronome schedule tests

Use deterministic transport ledgers to test:

1. Constant 4/4.
2. 3/4.
3. 6/8 grouping accents.
4. 7/8 grouping accents.
5. Tempo ramp.
6. Sudden manual tempo change.
7. Playback 0.25×, 0.5×, 1×, 1.5×, 2×.
8. Speed change while playing.
9. Seek forward/backward.
10. Loop wrap.
11. 1× bypass ↔ stretched path transition.
12. Unmapped region suppresses clicks.
13. Stale transport generation discards old clicks.

### 21.12 Count-in tests

Verify:

- off/one/two bars;
- once/every repeat;
- 4/4 beat-1 loop start;
- 4/4 beat-3 loop start;
- 6/8 second primary pulse start;
- 7/8 grouped beat start;
- project start with no preceding source audio;
- source loop off-grid start;
- variable tempo before loop start;
- speed changes;
- pause/stop during count-in;
- finite repeat counts.

### 21.13 Portable-project tests

Save/open with:

- automatic result only;
- edited branch;
- manual anchor changes;
- meter change;
- pickup;
- musical loop;
- metronome/count-in settings;
- raw activation arrays removed from model store;
- Beat This! environment absent;
- network disabled.

### 21.14 Browser end-to-end tests

Chromium and Firefox:

1. Open a prepared project.
2. Install/use a test rhythm model fixture or mocked deterministic worker at integration level where full model execution is unsuitable.
3. Run real contract/job path.
4. Display pulses.
5. Edit a beat.
6. Set downbeat.
7. Change meter.
8. Create musical loop.
9. Enable metronome.
10. Enable count-in.
11. Play at variable speed.
12. Save/reopen.
13. Confirm grid/practice state persists.

Keep at least one real Beat This! integration test outside the fast mocked browser suite.

**Acceptance:** deterministic tests cover mapping, editing, snapping, scheduling, count-in, persistence, and failure behavior independently of subjective listening.

---

## 22. Work package M3.20 — Rhythm quality evaluation and model acceptance

### 22.1 Evaluation corpus

Use the main plan's rhythm evaluation strategy:

- synthetic clicks and tempo ramps;
- synthetic meter/grouping fixtures;
- manually annotated excerpts from the five supplied recordings;
- additional legally usable/annotated rhythm material where available.

Separate development/tuning material from final evaluation excerpts.

### 22.2 Beat/downbeat metrics

Measure:

- beat precision/recall/F-measure under a documented timing tolerance;
- downbeat precision/recall/F-measure;
- timing-error distribution;
- missed long gaps;
- extra-pulse rate;
- behavior in silence;
- performance by musical style/excerpt rather than only one global average.

Record the exact metric implementation and tolerance used.

### 22.3 Half/double-tempo errors

Measure separately:

- correct pulse timing but wrong musical-rate interpretation;
- consistent half-time error;
- consistent double-time error;
- region-local reinterpretation errors.

Do not treat a half/double interpretation as a simple beat timestamp miss when the pulses themselves are aligned.

### 22.4 Meter accuracy

Measure:

- meter label accuracy by duration/region;
- boundary accuracy for meter changes;
- grouping accuracy for compound/irregular meters;
- uncertainty behavior when evidence is ambiguous;
- pickup/first-downbeat accuracy separately.

### 22.5 Tempo-map accuracy

For annotated/synthetic maps:

- anchor source-time error;
- local quarter-note BPM error;
- accumulated musical-position error over long passages;
- source↔musical round-trip error;
- ramp tracking.

### 22.6 `final0` versus `small0`

If `small0` is enabled:

Measure on the same corpus:

- beat/downbeat metrics;
- meter downstream metrics;
- runtime;
- peak memory;
- user-visible correction burden.

Keep `final0` as the initial default unless measured evidence supports a different preset policy.

### 22.7 Original mix versus drum stem

When drum results are evaluated:

- compare both against the same annotations;
- record disagreement regions;
- do not select one globally based on a single song;
- keep original mix as the product default unless evidence justifies changing the main plan.

### 22.8 Confidence/review usefulness

Measure whether low activation/meter-margin regions are actually more likely to require correction.

If not, do not present those scores as reliable review priorities.

### 22.9 Practical correction burden

For annotated excerpts, record:

- pulses added;
- pulses deleted;
- pulses moved;
- downbeats changed;
- meter regions corrected;
- half/double reinterpretations;
- time required to reach an acceptable grid.

This is a useful product metric distinct from model benchmark score.

**Acceptance:** the default rhythm pipeline has measured behavior on synthetic and real excerpts, with half/double and meter failures reported separately rather than hidden in one score.

---

## 23. Work package M3.21 — Performance, browser, playback, and listening acceptance

### 23.1 Analysis resource behavior

Measure:

- Beat This! elapsed time per track minute.
- CPU utilization.
- Peak host RAM.
- Peak GPU VRAM where applicable.
- Activation artifact size.
- Meter feature artifact size.
- Cache reuse time.

Do not promise a speed until measured on the target PC.

### 23.2 Playback coexistence

While a prepared song is playing:

1. Start rhythm analysis on an available device.
2. Observe browser audio underruns.
3. Observe API responsiveness.
4. Observe UI frame responsiveness.
5. Verify analysis worker resource limits.
6. Reduce analysis concurrency/profile if playback becomes unreliable.

### 23.3 Ruler/editor responsiveness

On a 60-minute project:

- horizontal pan remains responsive;
- zoom does not materialize every subdivision;
- beat/meter lane hit testing remains practical;
- playhead updates do not redraw full waveform/grid layers;
- snap target generation remains local to the viewport/edit position.

### 23.4 Metronome timing acceptance

Internal/offline schedule tests must show:

- no cumulative event-phase drift over long playback;
- no repeated-loop accumulation error;
- correct behavior across rate transitions;
- stale scheduled events are not emitted after seek/generation changes.

In browser listening tests:

- clicks and audible audio remain perceptually aligned through tempo ramps;
- no systematic double-latency compensation is apparent;
- 1× bypass transitions do not shift metronome phase.

### 23.5 Count-in listening acceptance

Review:

- downbeat accent clarity;
- 6/8 grouping;
- mid-bar entry;
- before-every-repeat flow;
- very slow 0.25× playback;
- fast 2× playback;
- loops near project start.

### 23.6 Browser coverage

Required:

- Chromium on Linux.
- Firefox on Linux.

Use the existing SharedArrayBuffer and transferable-buffer audio paths as applicable.

Milestone 3 must test metronome/count-in under both buffering paths where feasible.

Actual Safari validation remains Milestone 8.

### 23.7 Offline verification

After installation/model preparation:

1. Block external network access.
2. Open a rhythm-enabled project.
3. Edit grid.
4. Use snapping.
5. Play with metronome/count-in.
6. Save portable project.
7. Reopen it.
8. Confirm no external requests are needed.

Run a separate offline analysis test with Beat This! already installed.

### 23.8 Existing five recordings

For every supplied recording:

1. Open/import using prior milestone flow.
2. Run rhythm analysis on original mix.
3. Inspect beats/downbeats.
4. Correct a representative region where needed.
5. Validate bar/beat readout.
6. Create a musical loop.
7. Practise it at a non-1× speed with metronome.
8. Use one-bar count-in.
9. Save/reopen.
10. Record model/runtime/editor issues.

Do not claim ground-truth accuracy for unannotated full songs.

### 23.9 Failure acceptance

Verify clear recovery for:

- model not installed;
- GPU unavailable;
- worker crash;
- activation artifact missing;
- no detected pulses;
- no stable meter;
- invalid manual anchor crossing;
- unresolved musical loop;
- metronome entering an unmapped region;
- count-in requested without valid meter;
- portable project missing optional raw activations.

**Acceptance:** rhythm analysis and musical practice features coexist with long-track playback without timing drift, unbounded UI work, or hidden failure states.

---

## 24. Work package M3.22 — Documentation, diagnostics, and troubleshooting

### 24.1 User documentation

Document:

- what automatic beats/downbeats mean;
- difference between pulse, tempo anchor, and meter;
- source time versus musical position;
- Auto versus Edited rhythm results;
- how to set first downbeat;
- how pickups work;
- how half/double-time reinterpretation works;
- how 6/8 tempo units are displayed;
- how meter grouping works;
- source-anchored versus musical loops;
- snap modes;
- metronome subdivisions;
- count-in once versus every repeat.

### 24.2 Developer documentation

Document:

- Beat This! environment lock and install command;
- model manifest/provenance;
- activation artifact format;
- source↔model frame mapping;
- musical PPQ convention;
- Python/TypeScript mapping invariants;
- meter-decoder profile;
- metronome render-clock scheduling;
- count-in transport phase;
- cache-key composition;
- portable-project rhythm contents.

### 24.3 Diagnostic command additions

Extend local diagnostics to report, without loading a model unless explicitly requested:

- Beat This! environment availability.
- Registered model installation state.
- Last qualification result per device/model.
- Rhythm artifact/cache usage.
- Current active rhythm branch validity summary for a selected project when invoked through a project diagnostic command.

Do not make `basseparate doctor` perform expensive inference by default.

### 24.4 Troubleshooting guide

Add:

- Beat This! model not installed.
- Beat This! worker environment missing/broken.
- CUDA model qualification fails but CPU is available.
- Beats appear at half/double tempo.
- Downbeats are shifted by one or more beats.
- 6/8 tempo appears different from expected because of tempo unit.
- No stable meter found.
- Grid disappears in an unmapped region.
- Tempo anchor cannot cross another anchor.
- Meter change must occur at a bar boundary.
- Musical loop becomes unresolved after grid-version switch.
- Metronome disabled in no-grid region.
- Count-in unavailable without valid meter.
- Optional activation cache missing after cleanup.

### 24.5 License inventory

Update the machine-readable license manifest with:

- Beat This! code revision/license.
- `final0` weight provenance/license.
- `small0` weight provenance/license if supported.
- new direct runtime dependencies.
- any added audio-feature library dependencies.

Keep code and weight licenses separate.

**Acceptance:** a developer can reproduce the rhythm runtime and a user can understand/correct common beat, meter, tempo-unit, snapping, metronome, and count-in problems.

---

## 25. Implementation order and acceptance gates

Execute in this order unless a dependency measurement demonstrates a reason to adjust it.

| Gate | Work packages | Required evidence |
|---|---|---|
| A | M3.1–M3.3 | Migrated schemas, qualified rhythm runtime/model, reproducible analysis input |
| B | M3.4–M3.6 | Retained activations, decoded pulses, immutable automatic result, editable branch |
| C | M3.7–M3.9 | Valid source↔musical map, meter regions, bars/beats/pickups derived correctly |
| D | M3.10–M3.12 | Manual correction, ruler UI, snapping, undo/redo |
| E | M3.13 | Source and musical loop semantics integrated and persistent |
| F | M3.14–M3.16 | Render-clock metronome, count-in, musical readout/navigation |
| G | M3.17–M3.18 | API/worker/frontend contracts, cache, autosave, portable reopen |
| H | M3.19–M3.24 | Automated tests, quantitative evaluation, browser/listening acceptance, documentation |

### 25.1 Gate A — Foundation for rhythm analysis

Required before moving on:

- prior milestone timing baseline passes;
- rhythm schemas/migrations pass;
- `final0` manifest is verified;
- isolated worker runs;
- at least one CPU/GPU model path is qualified;
- no implicit downloads occur;
- analysis input mapping is auditable.

### 25.2 Gate B — Raw and decoded automatic output

Required:

- frame activations are retained;
- artifact hashes/provenance validate;
- pulse decoding can rerun from activations alone;
- candidate/accepted pulses distinguish ambiguity;
- automatic result is immutable;
- edited branch creation preserves parent result.

### 25.3 Gate C — Musical map correctness

Required:

- Python/TypeScript golden mapping fixtures agree;
- constant/variable tempo maps pass;
- half/double reinterpretation passes;
- meter candidate/region rules pass;
- first downbeat/pickup behavior passes;
- unmapped regions are not forced into bars.

### 25.4 Gate D — Correctable editor

Required:

- beat/downbeat/anchor/meter edits work;
- locks work;
- every edit undo/redo/reopen passes;
- ruler stays aligned at all zoom levels;
- snapping obeys visual-radius semantics;
- stale revisions conflict safely.

### 25.5 Gate E — Musical loop integration

Required:

- old source loops remain unchanged;
- musical loops follow grid edits;
- anchor conversion is explicit/undoable;
- unresolved musical loops fail safely;
- loop timing remains stable at speed extremes.

### 25.6 Gate F — Practice synchronization

Required:

- metronome uses render-clock schedule;
- rate changes/seeks/loops invalidate stale events;
- count-in does not advance source time;
- mid-bar count-in phase is correct;
- musical readout follows audible source position;
- bar navigation works.

### 25.7 Gate G — Integrated persistence

Required:

- APIs/contracts regenerated;
- cache identity verified;
- completed stages resume after restart;
- corrected grid survives portable save/open;
- model removal does not break reopening/practice;
- optional raw activation loss is reported but does not destroy grid use.

### 25.8 Gate H — Evidence

Required:

- synthetic test matrix passes;
- browser tests pass;
- five supplied tracks complete practical workflow;
- rhythm metrics recorded;
- timing/performance measurements recorded;
- limitations and uncertain regions are documented;
- license inventory updated.

Do not declare a gate complete based only on mocked model output when the gate explicitly requires a real model/integrated timing path.

---

## 26. Final completion checklist

### 26.1 Model and analysis

- [ ] Beat This! has an isolated locked environment.
- [ ] `final0` is registered with verified provenance and hash.
- [ ] `small0` is either registered/verified or explicitly left optional/unavailable.
- [ ] At least one actual model/device path is qualified.
- [ ] CPU fallback behavior is explicit.
- [ ] Inference performs no hidden downloads.
- [ ] Original mix is the default rhythm input.
- [ ] Drum-stem analysis, if used, remains a separate result.
- [ ] Beat/downbeat frame activations are retained before postprocessing.
- [ ] Activation artifacts have reproducible source-time mapping.
- [ ] Decoder can rerun without neural inference.
- [ ] Low-confidence candidates remain inspectable.

### 26.2 Tempo and meter

- [ ] Musical position uses the documented exact reduced-rational convention.
- [ ] Source↔musical mapping is strictly monotonic.
- [ ] Forward/inverse mapping passes golden tests.
- [ ] Automatic anchors preserve natural timing variation.
- [ ] Summary BPM does not replace the variable map.
- [ ] 6/8 tempo unit is explicit.
- [ ] Half-time and double-time reinterpretation are available and undoable.
- [ ] Tempo anchors can be inserted, moved, deleted, and locked.
- [ ] Meter inference is separate from beat detection.
- [ ] All eight initial automatic meter candidates are supported.
- [ ] Manual arbitrary meter/grouping entry is validated.
- [ ] Meter changes occur only at bar boundaries.
- [ ] Uncertain/unmetered/unmapped states are represented honestly.

### 26.3 Bars, pickups, and editing

- [ ] First downbeat can be corrected.
- [ ] First numbered bar can be set.
- [ ] Pickup material is represented without altering audio.
- [ ] Bar numbering survives meter changes.
- [ ] Beat/downbeat edits are transactional.
- [ ] Tempo-anchor edits are transactional.
- [ ] Meter-region edits are transactional.
- [ ] Every introduced semantic edit supports undo/redo.
- [ ] Automatic output remains immutable after corrections.
- [ ] Rerunning analysis preserves earlier results and edits.

### 26.4 Ruler and snapping

- [ ] Bar/beat ruler derives from active tempo+meter maps.
- [ ] Ruler does not allocate all subdivisions for long tracks.
- [ ] Tempo/meter lanes share waveform horizontal transforms.
- [ ] Beat/downbeat uncertainty is visible without color alone.
- [ ] Snap Off works.
- [ ] Beat snapping works under simple/compound/irregular meter.
- [ ] Half-beat snapping works under variable tempo.
- [ ] Quarter-beat snapping works under variable tempo.
- [ ] Bar snapping works only in valid metered regions.
- [ ] Event-boundary snapping works.
- [ ] Visual snap radius is approximately 8 CSS pixels.
- [ ] Changing snap mode never moves existing objects automatically.

### 26.5 Loops and practice

- [ ] Existing source loops remain source anchored by default.
- [ ] Musical loops can be created from bar/beat ranges.
- [ ] Source↔musical loop conversion is explicit and undoable.
- [ ] Musical loops follow tempo-map edits.
- [ ] Unresolved musical loops fail safely.
- [ ] Metronome is generated locally.
- [ ] Metronome uses the audio render clock, not UI timers.
- [ ] Downbeat accents work.
- [ ] Compound/irregular grouping accents work.
- [ ] Subdivision settings work.
- [ ] Metronome volume is independent.
- [ ] Metronome follows 0.25×–2.0× speed.
- [ ] Metronome follows seeks and manual tempo changes.
- [ ] Metronome remains phase-correct through loop wraps.
- [ ] Count-in Off/1 bar/2 bars work.
- [ ] Count-in once/every repeat works.
- [ ] Mid-bar loop count-in has correct phase.
- [ ] Count-in remains separate from source time.

### 26.6 Readout, persistence, and robustness

- [ ] Musical readout follows latency-compensated audible source position.
- [ ] Bar navigation works when grid exists.
- [ ] No-grid regions are shown explicitly.
- [ ] Rhythm cache keys include model/preprocessing/decoder dependencies.
- [ ] Manual branches are protected from cache eviction.
- [ ] Interrupted analysis preserves completed stages.
- [ ] Working autosave persists rhythm edits immediately.
- [ ] Portable saves include active rhythm/practice state.
- [ ] Model weights are excluded from portable projects.
- [ ] Portable reopen requires no model or network.
- [ ] Missing optional activation caches do not destroy corrected-grid practice.
- [ ] Chromium and Firefox workflows pass.
- [ ] Offline analysis with preinstalled model passes.
- [ ] Offline reopen/practice passes.

### 26.7 Evidence and documentation

- [ ] Synthetic 4/4 fixture passes.
- [ ] Synthetic 3/4 fixture passes.
- [ ] Synthetic 6/8 fixture passes.
- [ ] Tempo-ramp fixture passes.
- [ ] Free/unmapped timing behavior passes.
- [ ] Meter-change fixtures pass.
- [ ] Pickup fixtures pass.
- [ ] Long-duration no-drift tests pass.
- [ ] Beat/downbeat evaluation metrics are recorded.
- [ ] Half/double-tempo error rate is recorded separately.
- [ ] Meter-region accuracy is recorded.
- [ ] Tempo-anchor timing error is recorded.
- [ ] All five supplied recordings complete the practical workflow.
- [ ] Runtime/memory/artifact-size measurements are recorded.
- [ ] User/developer/troubleshooting docs are updated.
- [ ] License manifest covers Beat This! code and selected weights separately.

---

## 27. Traceability to Section 13 Milestone 3

| Main-plan Milestone 3 item | Detailed coverage |
|---|---|
| 1. Integrate Beat This! | M3.2–M3.4 |
| 2. Retain frame activations | M3.1, M3.4, M3.18 |
| 3. Build beat/downbeat objects | M3.5–M3.6 |
| 4. Implement tempo-map conversion | M3.7, M3.9 |
| 5. Implement meter hypotheses | M3.8 |
| 6. Add bar/beat ruler | M3.9, M3.11 |
| 7. Add first-downbeat editing | M3.9–M3.10 |
| 8. Add pickup bars | M3.9–M3.10 |
| 9. Add tempo-anchor editing | M3.7, M3.10 |
| 10. Add meter-region editing | M3.8, M3.10 |
| 11. Implement snapping | M3.12 |
| 12. Add metronome | M3.14 |
| 13. Add one-/two-bar count-in | M3.15 |
| 14. Add musical readout | M3.16 |
| 15. Verify 4/4, 3/4, 6/8, tempo ramps, and free timing | M3.19–M3.21 |

The main acceptance condition—correctable grid plus variable-tempo loop practice with synchronized metronome—is covered across M3.10–M3.16 and verified in M3.19–M3.21.

---

## 28. Handoff to Milestone 4

Deliver to the harmony milestone:

1. Immutable original-mix rhythm analyses with retained raw activations.
2. Editable rhythm branches with stable IDs/revisions.
3. A validated source-frame ↔ exact musical-position mapping.
4. Bar/beat/subdivision derivation across variable tempo.
5. Meter regions with grouping and uncertainty.
6. First-downbeat, pickup, and bar-number semantics.
7. Musical snapping infrastructure that later chord boundaries can use without retroactive quantization.
8. Musical-loop anchors.
9. A render-clock metronome/count-in implementation.
10. A musical readout that can later incorporate active chord/key fields.
11. Cache/result-version dependencies suitable for chord analysis variants that optionally consume rhythm context.
12. Portable-project persistence of rhythm artifacts and manual corrections.
13. Quantitative beat/downbeat/meter evaluation results.
14. A documented distinction between source time, musical position, pulse evidence, tempo anchors, and meter interpretation.
15. A clean insertion point for chord detection, chord-region editing, chord complexity display, inversion evidence, key analysis, and harmony-aware linked selection.

Milestone 4 must consume the selected rhythm version explicitly when it uses beat/bar context. It must not assume the latest automatic rhythm run is the user's corrected grid.
