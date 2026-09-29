
# Milestone 2 — Bass practice workflow: detailed implementation specification

This expands Milestone 2 in Section 13 of [basseparate_project_plan.md](/home/thomas/Documents/localLLM playground/opencodetest/basseparate/projectPlans/basseparate_project_plan.md).

It builds on [milestone0.md](/home/thomas/Documents/localLLM playground/opencodetest/basseparate/projectPlans/milestone0.md) and [milestone1.md](/home/thomas/Documents/localLLM playground/opencodetest/basseparate/projectPlans/milestone1.md). Those documents currently describe planned foundations; their implementation must pass its acceptance gates before dependent Milestone 2 work is considered complete.

## 1. Required outcome and milestone boundaries

### 1.1 Complete user workflow

At completion, the user can:

1. Import a song.
2. Verify that the bundled pinned Demucs baseline is present and qualified; no network model installation is required for the baseline.
3. Select a supported GPU or CPU.
4. Separate bass and accompaniment, or four instrument groups.
5. Inspect every separated waveform on one timeline.
6. Mute, solo, adjust volume, and pan individual stems.
7. Select and save a practice loop.
8. Play it repeatedly.
9. Slow down or speed up playback while preserving pitch.
10. Export aligned WAV stems.
11. Save a self-contained `.basseparate` project.
12. Reopen it without the original source path, installed model, or network access.
13. Continue practising with the saved mixer, loop, and viewport state.

### 1.2 Included work

- Isolated Demucs runtime.
- Pinned `htdemucs_ft` bundled-baseline provisioning and integrity verification.
- GPU discovery and explicit device selection.
- Separation progress, cancellation, and recovery.
- Bass/residual and four-stem modes.
- Immutable separation result versions.
- Analysis-result caching.
- Stem waveform and playback preparation.
- Synchronized multi-stem mixing.
- Saved source-time loops.
- Pitch-preserving playback from 0.25× to 2.0×.
- Latency-compensated transport.
- WAV stem export.
- Portable project save/open.
- Undo/redo for new manual settings and loop edits.
- Offline, timing, resource, and listening tests.

### 1.3 Deferred work

Keep these in their existing later milestones:

- Guitar/piano six-stem mode.
- SCNet and RoFormer comparisons.
- Automatic model-quality selection.
- Beat/downbeat/bar detection.
- Musical snapping.
- Tempo maps and time signatures.
- Count-in and metronome.
- Chord, key, and bass-note recognition.
- Noncontiguous snippet queues.
- YouTube import.
- FLAC/MP3 export.
- Stretched-audio export.
- Full comparison UI for multiple analysis versions.

The data model preserves separation versions now; the larger comparison interface remains later work.

### 1.4 Hardware qualification status

The previously inspected PC contains an RTX 4080 and RTX 5060 Ti. The saved inventory reports 16 GB VRAM on each.

A fresh `nvidia-smi` check still failed in the current environment. Do not assume GPU inference is working until a real PyTorch/model test passes.

The application must remain usable for reopening and playing existing projects when no analysis device is available.

---

## 2. Fixed implementation decisions

| Area | Milestone 2 decision |
|---|---|
| Initial model | Demucs `htdemucs_ft` |
| Initial engine | Pinned maintained Demucs release, starting evaluation with 4.1.0 |
| Model execution | Dedicated Python subprocess/environment |
| Default precision | Float32 |
| Default device | RTX 4080 when available and qualified |
| Secondary device | RTX 5060 Ti selectable after its own qualification |
| GPU concurrency | One separation job total initially |
| Separation modes | Bass + Others; Vocals/Drums/Bass/Other |
| Model outputs retained | Full four-stem result for reuse |
| Analysis storage | Float32 PCM at project sample rate |
| Mixing | All stems read from one source position |
| Stretching | One stereo stretcher after mixing |
| Speed | 0.25×–2.0×, pitch preserved |
| Loop anchor | Integer source-frame boundaries |
| WAV export | Full-length aligned stems; 24-bit default |
| Portable project | ZIP64, versioned manifest, project-only SQLite snapshot |
| Portable-project model weights | Excluded; application-bundled Demucs weights remain outside `.basseparate` archives |
| Save behavior | Background archive job with atomic publication |
| Reopen behavior | No inference, model installation, or network access required |

The maintained Demucs repository documents its fine-tuned preset and current packaging. Treat it as the initial baseline, not as proof that it is the final best model for every recording. [Demucs upstream](https://github.com/adefossez/demucs)

---

## 3. Work package M2.1 — Confirm prerequisites and extend the domain

### 3.1 Prerequisite checks

1. Import and reopen each existing local WAV through Milestone 1.
2. Verify canonical source hashes and frame counts.
3. Verify source-rate and browser-rate playback.
4. Verify waveform tiles and sample-level rendering.
5. Verify rapid-seek generation handling.
6. Verify interrupted-job recovery.
7. Verify command history and revision conflicts.
8. Verify local-only startup and playback.
9. Record any failed prerequisite before proceeding with dependent work.

### 3.2 Separation-run record

Add a record containing:

- Run ID.
- Project ID.
- Input asset and transformation hashes.
- Requested mode.
- Model manifest ID and hash.
- Engine version.
- Adapter version.
- Requested parameters.
- Effective parameters.
- Random seed.
- Device type and GPU UUID.
- Runtime/driver versions.
- Start/end timestamps.
- Status.
- Result-set ID.
- Warnings.
- Timing and peak-memory metrics.

Separate requested parameters from effective parameters so memory-recovery retries remain auditable.

### 3.3 Separation result set

Define:

- Result-set UUID.
- Parent run ID.
- Project source identity.
- Output sample rate.
- Output channel count.
- Output frame count.
- Available stem roles.
- Stem asset references.
- Bass-residual reference.
- Input/reference-mix identity.
- Reconstruction metrics.
- Validation status.
- Creation timestamp.

A result set becomes available only after its required audio assets pass validation.

### 3.4 Stem record

Each stem contains:

- UUID.
- Result-set ID.
- Instrument role.
- Display name.
- Audio asset ID.
- Sample rate.
- Channel count/layout.
- Frame count.
- Project alignment offset, normally zero.
- Waveform-cache reference.
- Playback-representation references.
- Confidence structure.
- Provenance.

Use the instrument role from the model’s declared source labels, not a hard-coded tensor index.

### 3.5 Mixer and practice state

Add:

- Playback mode: `original`, `bass_pair`, or `four_stems`.
- Active separation result-set ID.
- Per-track gain, mute, solo, balance, visibility, and display height.
- Master gain.
- Monitoring limiter setting.
- Playback speed.
- Saved loops.
- Active loop ID.
- Loop-enabled state.

### 3.6 Versioning

1. Increment database schema through a tested migration.
2. Update project serialization schema.
3. Preserve old empty/import-only projects.
4. Add defaults when migrating projects without mixer or loop state.
5. Keep existing imported source assets untouched.
6. Generate updated frontend types.

**Acceptance:** a result set, its audio, and its playback settings can be represented without modifying the original source record.

---

## 4. Work package M2.2 — Create the isolated Demucs runtime

### 4.1 Environment boundaries

1. Create a separately locked analysis environment.
2. Keep the backend’s core environment free of mandatory PyTorch imports.
3. Pin Python 3.11 for this worker initially.
4. Pin Demucs, PyTorch, and related runtime packages together.
5. Install only inference requirements.
6. Record the resolved lock and environment fingerprint.
7. Run the worker using its explicit interpreter path.
8. Keep environment installation separate from ordinary application startup.

### 4.2 PyTorch/CUDA qualification

1. Select an official wheel combination supporting both GPU architectures.
2. Confirm compatibility against the current PyTorch release matrix.
3. Check the actual driver against the selected wheel’s requirements.
4. Run a small tensor computation on each GPU.
5. Run representative convolution and FFT operations.
6. Load and run a short Demucs input.
7. Record success or the exact incompatibility.
8. Mark devices usable only after the model test succeeds.

Do not infer compatibility solely from the locally installed CUDA toolkit version. [PyTorch release matrix](https://github.com/pytorch/pytorch/blob/main/RELEASE.md)

### 4.3 CPU path

1. Support CPU inference in the same adapter.
2. Limit CPU compute threads to four initially.
3. Label CPU as potentially slow.
4. Require explicit CPU selection after a GPU failure.
5. Keep the UI responsive while CPU inference runs.
6. Measure CPU progress rather than estimating from GPU timings.

### 4.4 Device records

Expose:

- GPU UUID.
- Display name.
- Total and currently free VRAM.
- Runtime compatibility.
- Last qualification result.
- Unavailability reason.

Refresh free VRAM before a job starts.

### 4.5 Device selection

Default order:

1. Qualified RTX 4080.
2. Qualified RTX 5060 Ti.
3. No selected accelerator; offer CPU explicitly.

If the user previously selected a device, preserve that preference by UUID.

Do not silently move a requested GPU job to CPU or combine both GPUs into a presumed 32 GB memory pool.

**Acceptance:** unavailable analysis hardware produces a clear status while normal playback remains functional.

---

## 5. Work package M2.3 — Pin and provision the bundled Demucs baseline

### 5.1 Model manifest

Create a checked-in registry entry containing:

- Stable model ID.
- Human-readable name.
- Engine requirement.
- Upstream revision.
- Model configuration hash.
- All checkpoint names.
- Official upstream artifact URLs/resolvers for provenance and developer refresh.
- Bundle-relative artifact paths used by development/release packaging.
- Expected byte sizes.
- SHA-256 hashes.
- Input sample rate/channel requirements.
- Output labels.
- Code and weight license evidence.
- Required notices.

Resolve and record exact artifact hashes during implementation. Do not invent unverified hashes in this plan.

### 5.2 Fine-tuned model composition

The `htdemucs_ft` configuration contains four component models with source-specific weights. Bundling, integrity verification, and cache identity must identify the whole configuration and its component artifacts. [Fine-tuned preset configuration](https://github.com/adefossez/demucs/blob/main/demucs/remote/htdemucs_ft.yaml)

Implementation steps:

1. Resolve the pinned preset configuration.
2. Enumerate all referenced checkpoints.
3. Verify labels and ensemble weights.
4. During development, obtain every required artifact once through an explicit developer provisioning step and place it in an ignored workspace model directory.
5. Verify each hash.
6. Verify the manifest hash.
7. Copy the verified artifact set into the personal release bundle during packaging.
8. Verify the packaged copies against the same manifest before the release is considered valid.
9. Mark the bundled baseline available only after the entire preset is present and verified.

### 5.3 Bundled-baseline provisioning workflow

1. Keep the verified `htdemucs_ft` artifact set in an ignored development-workspace model directory, separate from source control.
2. Record model name, expected bundled size, license/provenance information, and all hashes in the registry.
3. Have the release build copy the exact verified artifact set into a deterministic bundle-relative model directory.
4. Verify packaged bytes after copying; packaging fails on any missing or mismatched artifact.
5. On application diagnostics/model-catalog load, distinguish `bundled_available`, `bundled_missing`, and `bundled_corrupt` states.
6. Run a short local load/inference qualification with network access disabled.
7. Do not present an online Install action for the bundled Demucs baseline.
8. Record bundled provenance and qualification status so Milestone 7 can display it in the unified model manager.

### 5.4 Local repair/development bundle import

A registered local bundle may be used for developer provisioning or to repair a damaged personal installation:

1. Accept a local model bundle containing the registered manifest and artifacts.
2. Validate it against the application’s expected bundled Demucs registry entry.
3. Verify all hashes.
4. Preserve license notices.
5. Provision/repair without internet access.
6. Reject arbitrary executable plugins embedded in a model bundle.
7. Do not make this repair path a prerequisite for normal first-run use; the release already contains the baseline artifacts.

### 5.5 No implicit retrieval during inference

1. Pass Demucs the explicit bundle-relative/local verified model repository.
2. Disable remote fallback.
3. Check required files and hashes before spawning inference when integrity is uncertain.
4. Fail with `BUNDLED_MODEL_MISSING` or `BUNDLED_MODEL_CORRUPT` if the packaged baseline is unusable.
5. Never fetch weights because inference was requested or a saved project was opened.

### 5.6 License handling

Retain Demucs notices and record selected checkpoint provenance separately. The code repository uses MIT licensing; that does not justify assuming unrelated future checkpoint terms. [Demucs license](https://github.com/adefossez/demucs/blob/main/LICENSE)

**Acceptance:** a normal personal release contains the complete pinned Demucs preset, verifies it locally, and loads/runs it with external network access disabled and without any user model-download step.

---

## 6. Work package M2.4 — Prepare separation input consistently

### 6.1 Reference mix

Define the mixture against which separation is evaluated:

- Stereo source: canonical stereo PCM.
- Mono source: canonical mono PCM, duplicated only for model input.
- Multichannel source: the explicit Milestone 1 stereo downmix.

The UI must identify a multichannel separation as a separation of the stereo downmix.

Do not claim that stereo stems reconstruct the original multichannel channels.

### 6.2 Input transformation

1. Resolve the reference-mix asset.
2. Verify its hash and metadata.
3. Read model sample-rate requirements.
4. Resample the entire continuous reference once.
5. Convert to model channel layout.
6. Store or reuse the transformed input asset.
7. Record transform/version identity.
8. Preserve source-time mapping.
9. Verify duration within the expected resampling-rounding tolerance.

### 6.3 Normalization

Demucs performs internal signal normalization and reverses it after inference. Keep this internal operation distinct from exported-stem normalization. [Demucs API implementation](https://github.com/adefossez/demucs/blob/main/demucs/api.py)

For bounded processing:

1. Calculate global normalization statistics in a streaming pass.
2. Use the same statistics for every processing window.
3. Use float64 accumulation for statistics.
4. Record the normalization-profile version.
5. Restore output scale before publication.
6. Do not independently peak-normalize stems.

### 6.4 Degenerate inputs

Handle explicitly:

- Exact silence.
- Near silence.
- Constant/DC signal.
- Strong anti-phase stereo.
- Nonfinite input, which should already have failed import.

Rules:

1. Exact zero input may produce zero stems without inference.
2. Mark that outcome as an exact-silence shortcut.
3. If channel-average variance is too small relative to full-channel variance, use a documented full-channel normalization fallback.
4. Keep epsilon handling versioned.
5. Test that fallback against anti-phase fixtures.
6. Never divide by a near-zero value and produce unbounded model input.

**Acceptance:** identical source/reference transforms yield the same prepared input and normalization identity.

---

## 7. Work package M2.5 — Implement bounded Demucs separation

### 7.1 Initial quality parameters

Use:

- `htdemucs_ft`.
- Float32.
- Split inference enabled.
- Internal segment length: 7.5 seconds, subject to the pinned model’s validated maximum.
- Internal overlap: 0.5.
- Shift averaging: 2.
- Fixed recorded seed.
- One active model computation at a time.

These are initial quality-oriented engineering defaults, not measured optimal settings.

### 7.2 Bounded long-track processing

Do not hold an entire long song and every output tensor in RAM.

Implement a versioned windowed adapter:

1. Process 120-second outer windows.
2. Use eight seconds of overlap between adjacent windows.
3. Apply the same global normalization statistics to each window.
4. Use Demucs’s internal segment handling inside each outer window.
5. Seed each window reproducibly from run seed and window index.
6. Restore the output scale.
7. Blend overlapping outer-window outputs with complementary raised-cosine weights.
8. Accumulate weights and divide after overlap-add.
9. Write finalized samples incrementally to staged output files.
10. Keep only the active window and overlap buffers in memory.

This outer-window policy is a basseparate adaptation. It must be benchmarked against whole-track upstream inference on short tracks; it is not assumed bit-identical.

### 7.3 Reference implementation

Maintain a short-input reference runner using upstream behavior for comparison.

Test:

1. Output labels.
2. Output shape.
3. Scale.
4. Alignment.
5. Numerical differences.
6. Boundary artifacts.
7. Bass continuity around outer-window transitions.

If the adapter introduces audible boundary defects, increase context/overlap through a new profile and re-run the comparison gate before release.

### 7.4 Model progress

Calculate progress across:

- Outer windows.
- Component models.
- Shift passes.
- Internal segments.

Use actual completed work units. Do not treat completion of the first component model as completion of the whole preset.

Upstream inference exposes callbacks and handles segmented processing; use the pinned implementation’s facilities rather than scraping terminal progress bars. [Demucs inference implementation](https://github.com/adefossez/demucs/blob/main/demucs/apply.py)

### 7.5 Memory-error recovery

1. Record the failure and effective parameters.
2. Stop the worker.
3. Release GPU resources through process exit.
4. Retry once with a smaller validated internal segment, initially five seconds.
5. Retry once more at three seconds if supported.
6. Restart the complete run under the new effective profile.
7. Use a distinct cache identity.
8. Stop after bounded retries.
9. Offer another device or explicit CPU execution.

Never mix stems generated under different retry profiles into one unrecorded result.

### 7.6 Cancellation

1. Check cancellation between model segments.
2. Raise the adapter’s cancellation signal.
3. Stop remaining queued work.
4. Allow a bounded graceful exit.
5. Terminate the worker if it fails to stop.
6. Remove incomplete staged outputs.
7. Preserve existing published result sets.
8. Keep the source and verified bundled model assets available for retry.

### 7.7 Crash recovery

An interrupted separation restarts from the beginning in this milestone.

Completed shared input transforms can be reused. Do not advertise resumable inference until intermediate checkpoints are implemented and tested.

**Acceptance:** a long recording processes with bounded host memory, cancellation works, and outer-window boundaries pass listening tests.

---

## 8. Work package M2.6 — Validate and publish stems

### 8.1 Restore project representation

For every output:

1. Resample continuously back to project sample rate.
2. For mono projects, collapse the model’s stereo output to mono using a documented average.
3. Retain stereo for stereo/downmixed projects.
4. Remove model padding according to known transform metadata.
5. Validate alignment.
6. Match the canonical project frame count.
7. Permit only documented resampling endpoint rounding.
8. Treat larger unexplained length discrepancies as failure.

Do not “fix” a significant offset by blindly trimming until lengths match.

### 8.2 Required validation

Check:

- Correct stem roles.
- Correct frame count.
- Correct channel count.
- Correct sample rate.
- Finite samples.
- Valid content hash.
- No missing output.
- No accidental clipping or normalization.
- No unexplained timeline offset.

### 8.3 Four-stem mode

Publish:

- Vocals.
- Drums.
- Bass.
- Other.

Preserve the raw model estimates.

Compute:

```text
reconstruction_error = reference_mix − sum(four_stems)
```

Store RMS and maximum error as diagnostics.

Do not claim exact reconstruction for raw four-stem output.

### 8.4 Bass-plus-Others mode

1. Use the same validated bass stem.
2. Calculate the residual at project rate:

   `others = reference_mix − bass`

3. Compute in bounded chunks.
4. Use higher-precision intermediate subtraction if helpful.
5. Store float32 residual PCM.
6. Verify reconstruction within float32 rounding tolerance.
7. Label the residual “Others,” distinct from the model’s “Other” stem.

### 8.5 Reuse between modes

Retain all four model outputs even when the user requests Bass + Others.

Consequences:

- Switching to four stems does not rerun the model.
- Bass + Others can be derived from a cached four-stem result.
- The UI should not promise that bass mode runs faster.

### 8.6 Confidence

For separation:

- Preserve the standard confidence object.
- Use `unavailable` for an unsupported prediction-confidence probability.
- Show reconstruction and processing diagnostics separately.
- Do not interpret low reconstruction error as proof of clean instrument separation.

### 8.7 Atomic result publication

1. Publish validated audio assets.
2. Create the complete result-set record.
3. Commit all result references transactionally.
4. Mark the run complete.
5. Queue peaks/playback representations.
6. Make audio available while optional waveform preparation continues.

**Acceptance:** every published stem is aligned and independently playable; Bass + Others reconstructs its reference mix within stated numerical tolerance.

---

## 9. Work package M2.7 — Analysis caching and version retention

### 9.1 Cache key

Include:

- Canonical/reference asset hashes.
- Stream/downmix identity.
- Model manifest and every weight hash.
- Engine and adapter versions.
- Input resampling profile.
- Normalization profile.
- Outer-window settings.
- Internal segment/overlap settings.
- Shift count and seed.
- Precision and relevant numerical flags.
- Device execution profile.
- Output transformation profile.

### 9.2 Cache behavior

1. Look up a matching completed result before scheduling.
2. Verify required assets still exist.
3. Validate recorded hashes when integrity is in doubt.
4. Return the existing result on a valid hit.
5. Never treat partial files as cache hits.
6. Coalesce identical concurrently requested jobs.
7. Publish only one completed result for an identical pending request.
8. Keep cancelled and failed jobs out of successful cache lookup.

### 9.3 Effective-parameter handling

If memory recovery changes parameters:

1. Record the new profile.
2. Store under its actual key.
3. Show that a smaller-segment result was used.
4. Do not mislabel it as the originally requested configuration.

### 9.4 Version retention

1. Reruns create new result sets.
2. Existing results remain immutable.
3. Switching active result sets is an undoable command.
4. Never delete a result merely because it becomes inactive.
5. Persist the active result selection.

### 9.5 Cache limits

1. Extend the existing 50 GiB configurable cache policy.
2. Count model storage separately.
3. Pin assets referenced by working projects.
4. Pin assets referenced by retained edit history.
5. Evict only unreferenced rebuildable results/caches.
6. Protect assets currently being saved/exported.
7. Display reclaimable size before explicit cleanup.

**Acceptance:** identical separation requests reuse results, and edits never disappear because a cache entry was reclaimed.

---

## 10. Work package M2.8 — Add aligned tracks and the stem mixer

### 10.1 Track layout

1. Keep original audio as a reference track.
2. Show either the bass pair or four stems as the active stem group.
3. Display all active waveforms simultaneously.
4. Share horizontal scroll and zoom.
5. Preserve independent lane height and amplitude zoom.
6. Label generated stems and source provenance.
7. Reuse Milestone 1 tiled waveform endpoints.
8. Fetch only visible tiles.
9. Keep hiding a waveform separate from muting audio.

### 10.2 Mixer controls

For each track:

- Mute.
- Solo.
- Gain in dB.
- Stereo balance, or mono pan where applicable.
- Visibility.
- Color.
- Height.

Default:

- Gain: 0 dB.
- Pan/balance: center.
- Mute: off.
- Solo: off.

### 10.3 Gain and pan behavior

1. Convert gain with `10^(dB/20)`.
2. Offer gain range from −60 dB to +12 dB.
3. Provide mute for exact silence.
4. Preserve stereo channels at centered balance.
5. Attenuate the opposite side when balancing stereo.
6. Use an equal-power pan law for mono.
7. Apply parameter ramps of approximately five milliseconds.
8. Avoid changing sample storage.

### 10.4 Solo semantics

1. Allow multiple soloed tracks.
2. If any solo is active, only soloed tracks are eligible to sound.
3. Mute overrides solo.
4. Do not make hidden tracks silent automatically.
5. Keep original and stem playback groups mutually exclusive.
6. Provide an explicit Original/Stem Group selector.

### 10.5 Common timeline

1. Prepare every active stem at the same AudioContext sample rate.
2. Use identical project-to-playback mapping.
3. Validate matching output lengths.
4. Use one read cursor.
5. Advance all stems together.
6. Buffer muted stems too, within the active group, so unmute can be immediate and aligned.
7. If any required stream underruns, buffer the whole active group.

### 10.6 Monitoring safety

1. Add output peak meters.
2. Add a switchable monitoring limiter.
3. Default the limiter on.
4. Use a documented ceiling of −1 dBFS.
5. Include any limiter delay in transport latency.
6. Make limiter state visible.
7. Keep it out of raw-stem exports.

**Acceptance:** stems never drift relative to each other, and control changes do not introduce clicks or unexpected doubling.

---

## 11. Work package M2.9 — Integrate the time-stretch engine correctly

### 11.1 Architecture

Use a buffer-driven processing path:

```text
Aligned stem buffers
        ↓
Shared source reader
        ↓
Per-stem gain/pan/mute/solo
        ↓
Stereo sum
        ↓
Signalsmith Stretch
        ↓
Master gain / monitoring limiter
        ↓
Audio output
```

The stretch engine must control how many source frames are consumed.

A fixed-rate live-input node followed by a rate setting is insufficient: Signalsmith’s documented live-input mode ignores rate and loop controls. [Signalsmith Web Audio interface](https://github.com/Signalsmith-Audio/signalsmith-stretch/blob/main/web/release/README.md)

### 11.2 Implementation choice

Integrate Signalsmith’s C++ core through a small project-owned WASM wrapper inside the existing AudioWorklet.

This wrapper owns:

- Input demand.
- Variable source consumption.
- Stereo processing.
- Priming and tail handling.
- Reset.
- Reported latency.
- Rate-transition state.

Reuse upstream DSP rather than implementing a phase vocoder from scratch.

### 11.3 Reproducible WASM build

1. Pin a Signalsmith commit.
2. Preserve its MIT notices.
3. Pin an Emscripten SDK release.
4. Add an explicit developer setup command.
5. Build optimized WASM and the wrapper.
6. Produce scalar and SIMD variants.
7. Select SIMD only after capability detection.
8. Avoid requiring WASM threads.
9. Record build versions and artifact hashes.
10. Bundle runtime artifacts locally.
11. Verify application launch requires no compiler.

Use the official SDK installation workflow, pinned to a recorded version rather than a moving `latest` target. [Emscripten installation](https://emscripten.org/docs/getting_started/downloads.html)

### 11.4 Processing contract

Expose:

- Create/configure stereo processor.
- Report input/output latency.
- Process specified input/output frame counts.
- Set rate.
- Reset.
- Flush tail.
- Destroy.

Allocate processing buffers before audio starts. Do not grow the WASM heap from the audio callback.

### 11.5 Initial settings

1. Start with Signalsmith’s default quality configuration.
2. Keep pitch shift at zero semitones.
3. Disable unrelated formant manipulation.
4. Measure latency and audio-thread cost.
5. Record the chosen configuration in the engine profile.

Signalsmith documents separate input and output latency and the need to account for both when processing finite signals. [Signalsmith Stretch](https://github.com/Signalsmith-Audio/signalsmith-stretch)

### 11.6 Speed controls

Provide:

- Slider from 0.25× to 2.0×.
- Numeric entry.
- Fine steps of 0.01×.
- Presets: 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0.
- Reset to 1×.

Clamp invalid input and preserve the current value after validation failure.

### 11.7 Rate changes

1. Schedule changes against the audio render clock.
2. Smooth over approximately 50 ms.
3. Use a fractional source-consumption accumulator.
4. Preserve cumulative source position.
5. Update transport mapping for the transition.
6. Do not change pitch.
7. Do not rewrite source or annotations.
8. Coalesce slider gestures into one undoable setting change.

**Acceptance:** speed changes preserve pitch and source-time alignment without discontinuous source jumps.

---

## 12. Work package M2.10 — Latency, bypass, and transport mapping

### 12.1 Three time domains

Track separately:

1. Project/source frames.
2. AudioContext render frames.
3. Estimated audible output time.

Do not derive source position as “elapsed wall time × current speed” after rate changes or loops.

### 12.2 Transport ledger

Record bounded mapping segments containing:

- Generation.
- Output-frame start/end.
- Source-position start/end.
- Rate behavior.
- Loop iteration.
- Playback state.
- Processing latency profile.

Retain enough history to map currently audible output even after a recent seek or loop wrap.

### 12.3 Priming

1. Determine required pre-roll from configured DSP latency.
2. Read available source context before the requested position.
3. Pad only when the source boundary requires it.
4. Process priming frames without emitting them as selected audio.
5. Start audible output at the requested source boundary.
6. Account for output latency once.
7. Test impulses to detect double compensation.

### 12.4 1× bypass

1. Provide an exact-speed path that bypasses stretching.
2. Keep its delay aligned with the stretched path.
3. When entering/leaving 1×, prepare the target path at the same source position.
4. Use a short aligned transition.
5. Never combine differently timed dry and stretched audio.
6. If the transition cannot be prepared without underrun, enter the explicit buffering state rather than emit misaligned audio.

### 12.5 Mixer changes through the stretcher

Already processed audio cannot respond retroactively to mute or solo.

1. Keep DSP lookahead bounded.
2. Apply mixer changes to the next unprocessed source frames.
3. Report control-response latency in diagnostics.
4. Test that it remains consistent with configured processing latency.
5. Apply master volume after stretching for immediate output control.

### 12.6 EOF

1. Stop consuming source frames at canonical EOF.
2. Flush the stretcher’s valid tail.
3. Trim priming/tail according to source-to-output mapping.
4. Do not append an audible extra blank segment.
5. Set the playhead to source end.
6. Transition to `ended`.

### 12.7 UI synchronization

1. Use output timestamps where available.
2. Map through the ledger.
3. Show original source time at every speed.
4. Handle source-position discontinuity at loop wrap explicitly.
5. Keep drawing timers separate from playback.
6. Freeze source advancement during buffering.

**Acceptance:** cursor, source readout, rate changes, and loop wraps follow the audio actually being heard.

---

## 13. Work package M2.11 — Saved practice loops

### 13.1 Loop schema

Each loop contains:

- UUID.
- Name.
- Start source frame.
- End source frame, exclusive.
- Color.
- Repeat count or null for infinite.
- Boundary-fade setting.
- Creation/update timestamps.

Project state stores active loop ID and whether looping is enabled.

Count-in and musical anchors are deferred.

### 13.2 Creation and editing

1. Create from current waveform selection.
2. Enter boundaries numerically.
3. Drag start/end handles.
4. Move the complete interval.
5. Rename.
6. Change color.
7. Duplicate.
8. Delete.
9. Select as active.
10. Toggle with `L`.

### 13.3 Validation

1. Require `0 ≤ start < end ≤ source_length`.
2. Permit saved intervals shorter than 100 ms.
3. Require at least 100 ms for repeated practice playback in this milestone.
4. Explain the minimum when an interval is too short.
5. Do not silently expand the interval.
6. Preserve exact frame boundaries.

### 13.4 Playback behavior

1. Enabling a loop does not immediately start playback.
2. Pressing Play while outside an enabled loop starts at loop start.
3. Enabling a loop during playback inside it continues from the current position.
4. Enabling it while playing outside performs a synchronized seek to loop start.
5. Seeking outside an active loop disables looping but retains the saved loop.
6. At finite repeat completion, stop at loop end.
7. Pressing Play after completion starts a new repeat sequence.

Define repeat count as total passes, not “extra repeats.”

### 13.5 Loop buffering

1. Pin the loop-start pre-roll and initial playback buffers.
2. Keep the upcoming loop-end data ready.
3. Cache the complete loop only when it fits the configured byte budget.
4. Stream long loops using the ordinary bounded window.
5. Do not fetch data on the audio thread.
6. If the next pass is not ready, buffer coherently.

### 13.6 Boundary treatment

1. Default to short five-millisecond output fades at the join.
2. Limit fades to a fraction of short-loop duration.
3. Preserve loop duration.
4. Do not shorten the loop through overlapping crossfades.
5. Offer fades off for exact boundary audition.
6. Keep the stored audio unchanged.

### 13.7 Looping through the stretcher

1. Present the selected source interval as a periodic input stream.
2. Provide periodic pre-roll at the first start.
3. Keep processing state continuous across subsequent wraps.
4. Exclude samples outside the selected interval from the loop’s context.
5. Use cumulative fractional output-duration accounting.
6. Do not independently round every iteration’s duration.

At constant rate, output duration per iteration is based on:

```text
loop_source_frames × output_rate / project_rate / speed
```

### 13.8 Undo/redo

Make all loop edits undoable. During playback, apply a loop-boundary edit at the next controlled transport transition, with rebuffering when needed.

**Acceptance:** short passages repeat at all supported speeds without cumulative boundary drift.

---

## 14. Work package M2.12 — Extend buffering and resource limits

### 14.1 Source-buffer sizing

At 2× speed, eight seconds of output lookahead requires approximately sixteen seconds of source audio.

Update Milestone 1’s limits:

1. Size lookahead according to playback speed.
2. Keep a byte cap and a source-duration cap.
3. Allow up to 24 seconds per active stem initially.
4. Account separately for loop-head pinned buffers.
5. Limit pinned loop data to 64 MiB across the active group.
6. Reuse immutable buffers when possible.

### 14.2 Group readiness

1. Treat all active-group stems as one synchronized set.
2. Start only when all required buffers are ready.
3. Keep muted stems aligned.
4. Discard outdated group-generation data.
5. On a single-stem failure, stop/buffer the group.
6. Never let unaffected stems continue advancing alone.

### 14.3 Thread/resource separation

- API process: requests and metadata.
- Analysis worker: model execution.
- Media worker: resampling/peaks/export.
- Browser worker: fetching/deinterleaving.
- AudioWorklet: deterministic mixing/stretching.

Initially allow one analysis job plus one bounded media job, subject to memory limits. Give playback preparation priority over background waveform work.

### 14.4 Diagnostics

Collect locally:

- Buffered frames per stem.
- Underrun count.
- Audio callback duration.
- Stretcher configuration/latency.
- Worker CPU/RAM.
- GPU memory peak.
- Separation elapsed time.
- Current job phase.

Do not add telemetry.

**Acceptance:** separation and waveform generation can run while an already prepared song plays without routine audio dropouts.

---

## 15. Work package M2.13 — WAV stem export

### 15.1 Initial export scope

Export:

- Bass.
- Others residual.
- Individual four-stem outputs.
- All stems in a selected group.

Milestone 2 exports full source duration at original speed.

Selection, mixer-rendered, loop-queue, and stretched exports remain later additions.

### 15.2 Options

- WAV 16-bit.
- WAV 24-bit, default.
- WAV float32.
- Original project sample rate, default.
- Optional 44.1 kHz or 48 kHz.
- Normalization off, default.
- Optional linked peak normalization to −1 dBFS.

Do not independently normalize multiple selected stems by default.

### 15.3 Export sequence

1. Select an immutable result set.
2. Resolve selected stem assets.
3. Verify alignment and availability.
4. Estimate disk space.
5. Resolve an app-managed export staging destination and a browser download filename; do not require an arbitrary browser-selected server filesystem path.
6. Generate safe filenames.
7. Prevent silent overwrite.
8. Apply continuous resampling if requested.
9. Determine whether integer output would clip.
10. If clipping would occur, offer float32 or linked normalization.
11. Apply triangular dither when reducing to integer PCM.
12. Encode with FFmpeg.
13. Use RF64-compatible WAV output when size requires it.
14. Verify rate, channels, and decoded frame count.
15. Publish the verified export artifact atomically inside managed local export storage.
16. Return artifact/download IDs and authenticated download URLs; deliver the file with `Content-Disposition` so the browser/user chooses the final filesystem destination.

### 15.4 Export semantics

- Mixer mute, solo, pan, and monitoring volume do not affect raw stem export.
- Monitoring limiter does not affect export.
- Playback speed does not affect these exports.
- Every exported stem begins at the same source origin.
- Filename sanitization never changes the source track itself.

### 15.5 Export report

Store:

- Source result-set ID.
- Selected stems.
- Encoding settings.
- Normalization gain, if used.
- Dither setting.
- Output hashes.
- Managed export artifact IDs and download filenames/URLs; the browser's final filesystem path is not authoritative project state.
- Completion/failure status.

**Acceptance:** exported stems line up when imported into a DAW and match the intended raw or explicitly normalized samples.

---

## 16. Work package M2.14 — Define the portable project format

### 16.1 Container layout

Use ZIP64 with a versioned manifest:

```text
song.basseparate
├── manifest.json
├── project.sqlite
├── assets/
│   └── sha256/...
├── caches/
│   └── waveforms/...
└── provenance/
    ├── separation-runs.json
    └── model-manifests.json
```

Use stored compression for large media/PCM and deflate for compact text/metadata.

Python’s ZIP support provides ZIP64 and streamed member handling; do not load the complete archive into memory. [Python ZIP documentation](https://docs.python.org/3.11/library/zipfile.html)

### 16.2 Included contents

By default include:

- Original imported file.
- Canonical source PCM.
- Reference downmix when applicable.
- All retained separation result sets referenced by the project.
- Residual stem.
- Existing waveform caches.
- Markers.
- Loops.
- Mixer and playback settings.
- View state.
- Command history and redo state.
- Analysis provenance.

Playback representations at specific device sample rates may be excluded because they are reproducible caches. Opening may regenerate them, but never rerun separation.

### 16.3 Excluded contents

- Model weights.
- Python environments.
- Authentication tokens.
- Logs.
- Browser session data.
- Unrelated projects.
- Unreferenced global cache entries.
- Partial job outputs.
- Executable plugins.

### 16.4 Manifest fields

Include:

- Format identifier.
- Container format version.
- Project schema version.
- Application version.
- Project ID.
- Saved revision.
- Save timestamp.
- Asset list.
- Per-member uncompressed sizes.
- Per-member hashes.
- Essential/optional classification.
- Model/run provenance references.

### 16.5 Project-only database

Milestone 0 uses a shared working database. Do not copy that entire database into the archive.

1. Open a consistent read transaction.
2. Select the target project and its dependency closure.
3. Copy only required rows into a newly created portable database.
4. Preserve internal IDs within the portable snapshot.
5. Include only relevant history and result references.
6. Validate foreign keys.
7. Ensure no unrelated project names, paths, or records remain.

Use SQLite’s consistent backup/snapshot facilities where appropriate; do not copy a live database file without handling its WAL state. [SQLite backup documentation](https://www.sqlite.org/backup.html)

**Acceptance:** the archive contains everything required for the selected project and nothing from unrelated projects.

---

## 17. Work package M2.15 — Save portable projects safely

### 17.1 Save workflow

1. Flush pending manual commands.
2. Capture a stable revision.
3. Acquire temporary references preventing asset eviction.
4. Build the project-only database snapshot.
5. Enumerate referenced assets.
6. Verify essential assets exist.
7. Estimate final size and temporary disk requirement.
8. Create a temporary archive inside managed portable-export staging on the same filesystem as its managed publication location.
9. Stream each member into it.
10. Hash bytes while copying.
11. Write the final manifest.
12. Close and flush the archive.
13. Verify member integrity and manifest consistency.
14. Retain one previous successful managed portable-export artifact when configured.
15. Atomically publish the verified archive into managed export storage.
16. Flush the managed publication directory where supported.
17. Expose an authenticated browser download with `Content-Disposition`; the browser/user chooses the final filesystem destination.
18. Release temporary asset references.
19. Record the saved revision and managed artifact identity.

### 17.2 Edits during save

1. Allow continued editing.
2. Save the captured revision consistently.
3. Do not mix later edits into an earlier database snapshot.
4. If current revision advances, show that newer changes remain unsaved to the portable file.
5. Keep working autosave active.

### 17.3 Save during analysis

1. Include only fully published results.
2. State that an in-progress run is not yet included.
3. Allow a later save when it completes.
4. Do not archive partial stem files.

### 17.4 Cancellation/failure

1. Stop writing.
2. Close the temporary archive.
3. Remove only the app-owned incomplete temporary output.
4. Keep the previous successful managed portable-export artifact intact; browser-downloaded copies are never modified by a failed generation job.
5. Keep the working project intact.
6. Report the failure and retry action.

### 17.5 Working save versus portable save

Display separate states:

- Working changes saved locally.
- Portable file saved through revision X.
- Portable file has newer unsaved changes.
- Portable save in progress.

Do not imply every slider movement rewrites a multi-gigabyte archive.

**Acceptance:** interrupted saves never destroy the last valid `.basseparate` file.

---

## 18. Work package M2.16 — Open portable projects

### 18.1 Browser-compatible input

Support a normal file picker and drag-and-drop for `.basseparate`.

Transfer the archive to localhost using the bounded upload mechanism. Do not require browser-specific filesystem APIs. Use a dedicated configurable `max_project_archive_bytes` transfer cap, independent of Milestone 1's 20 GiB local-media limit; set its initial default from long-project/archive stress testing and available-disk safety rather than inheriting the media-import value; keep the existing separate total-uncompressed-size/member-count safeguards for ZIP extraction.

### 18.2 Validate before import

1. Read the ZIP directory.
2. Enforce configurable total uncompressed-size and member-count limits.
3. Read a bounded manifest.
4. Validate format and schema versions.
5. Reject absolute paths.
6. Reject traversal components.
7. Reject duplicate normalized member names.
8. Reject symlinks and unexpected file types.
9. Reject unsupported encrypted members.
10. Check destination free space.
11. Validate every essential member’s size and hash.

Do not rely on a blind `extractall()` call.

### 18.3 Database handling

Treat the embedded SQLite file as untrusted data:

1. Open read-only with extensions disabled.
2. Validate expected tables and schema version.
3. Use explicit column queries.
4. Do not execute SQL text from the archive.
5. Validate records through application schemas.
6. Import into the working database through normal repository operations.

### 18.4 Asset restoration

1. Stage essential assets.
2. Verify hashes.
3. Reuse existing identical content-addressed objects.
4. Publish missing objects atomically.
5. Import the project records transactionally.
6. Remap IDs when necessary to avoid conflicts.
7. Validate all references.
8. Expose the project only after successful commit.

### 18.5 Existing project ID

Default to “Open as a new working copy” when the ID already exists.

Preserve the archived identity as provenance, generate a new working ID, and remap dependent references consistently. Do not overwrite an open project silently.

### 18.6 Optional cache failures

- Missing/corrupt waveform cache: rebuild.
- Missing playback-rate cache: regenerate.
- Missing model: no problem for playback.
- Missing essential source/stem: reject full restoration and explain the damaged member.

### 18.7 Restore state

1. Restore active result set.
2. Restore mixer settings.
3. Restore saved loops and active loop.
4. Restore speed.
5. Restore viewport and markers.
6. Restore last source position.
7. Remain paused.
8. Prepare playback representations when needed.

**Acceptance:** the project opens and plays on a clean app installation with all model directories absent and network access disabled.

---

## 19. Work package M2.17 — API and command additions

### 19.1 Analysis/model interfaces

| Interface | Purpose |
|---|---|
| `GET /api/v1/hardware` | Device qualification and availability |
| `GET /api/v1/models` | Registered/bundled model state and qualification |
| `POST /api/v1/models/{id}/verify` | Verify/qualify bundled baseline artifacts; no network install in Milestone 2 |
| `POST /api/v1/projects/{id}/runs` | Request separation |
| `GET /api/v1/projects/{id}/separation-results` | List immutable result sets |
| Existing job status/cancel routes | Track separation, export, save/open, and qualification work |

### 19.2 Project interfaces

- Existing project commands for mixer/loop/result selection.
- Existing undo/redo routes.
- `POST /api/v1/projects/{id}/exports`.
- `POST /api/v1/projects/{id}/save`.
- `POST /api/v1/projects/open`.
- `GET /api/v1/downloads/{artifact_id}` for authenticated `Content-Disposition` delivery of completed export/portable artifacts from managed storage.

Long operations return job IDs, not a blocking HTTP request lasting minutes.

### 19.3 New commands

- Select separation result.
- Select playback mode.
- Set track mute.
- Set track solo.
- Set track gain.
- Set track pan/balance.
- Set master volume.
- Set monitoring limiter.
- Set playback speed.
- Create/update/delete loop.
- Set active loop.
- Toggle looping.
- Change track layout.

Continue using revision checks and idempotency keys.

### 19.4 Frontend transport interface

Extend with:

- `loadTrackGroup(...)`.
- `setMixerState(...)`.
- `setRate(...)`.
- `setLoop(...)`.
- `setLoopEnabled(...)`.

Keep DSP implementation details out of React components.

### 19.5 Worker compatibility

Reuse Milestone 1 protocol version 2 where messages remain compatible. Declare separation-specific parameter/result schemas in module capabilities.

Increment protocol version only if changing existing message semantics.

**Acceptance:** frontend, worker, and persistence contracts are generated, versioned, and tested together.

---

## 20. Work package M2.18 — Test matrix

### 20.1 Bundled model provisioning and integrity

Test:

1. Complete bundled artifact set present.
2. One bundled artifact missing.
3. One bundled artifact hash mismatch/corruption.
4. Missing component checkpoint.
5. Corrupt configuration.
6. Packaging fails on missing/mismatched model bytes.
7. Local repair/development bundle import.
8. Inference/qualification with network blocked.
9. No automatic retrieval on project open or inference.

### 20.2 Separation correctness

Test:

- Mono and stereo.
- 44.1/48/96 kHz source.
- Exact silence.
- Near silence.
- DC offset.
- Anti-phase stereo.
- Shorter-than-model-segment input.
- Outer-window boundaries.
- Long recordings.
- Four-stem labels.
- Bass/residual reconstruction.
- Frame-count preservation.
- Nonfinite-output rejection.

### 20.3 Worker/device failures

Test:

- GPU unavailable.
- Selected GPU removed/unusable.
- CUDA compatibility failure.
- OOM recovery.
- Cancellation.
- Unexpected worker exit.
- Application restart during inference.
- Disk full during stem publication.
- Playback while analysis runs.

### 20.4 Mixer timing

Use synthetic aligned tracks containing:

- Impulses.
- Identical sine waves.
- Opposite-polarity signals.
- Distinct channel tones.

Verify:

1. Sample-aligned starts.
2. No relative drift.
3. Correct mute/solo truth table.
4. Correct gain/pan laws.
5. Centered stereo remains unchanged.
6. Original and stems are not accidentally doubled.
7. Group-wide buffering.
8. Gain ramps prevent abrupt steps.

### 20.5 Stretching

Test at:

- 0.25×.
- 0.5×.
- 0.75×.
- 1×.
- 1.25×.
- 1.5×.
- 2×.

Verify:

- Expected duration.
- Preserved pitch.
- Low-B sustained tone.
- Bass transients.
- Dense drums.
- Stereo phase/image.
- Speed transitions.
- 1× bypass transitions.
- Pause/seek/reset.
- Priming and EOF tail.
- Audible-position mapping.

### 20.6 Loops

Test:

- Start at zero.
- End at EOF.
- 100 ms minimum active loop.
- Long streamed loop.
- Finite and infinite repetitions.
- Loop at each speed.
- Speed change inside loop.
- Boundary edit during playback.
- Toggle off during playback.
- Seek outside loop.
- Missing loop-start buffer.
- Hundreds of repetitions without accumulated rounding drift.

### 20.7 Portable projects

Test:

1. Save/open round trip.
2. Save during continued editing.
3. Save while separation is running.
4. Interrupted save.
5. Previous-save recovery.
6. ZIP64-size project.
7. Missing optional cache.
8. Corrupt essential stem.
9. Wrong hash.
10. Unsafe archive paths.
11. Duplicate member names.
12. Unsupported future schema.
13. Duplicate project ID.
14. Unrelated-project data exclusion.
15. Reopen without original path.
16. Reopen without models.
17. Reopen offline.

### 20.8 WAV export

Verify:

- 16-/24-bit and float32.
- Source and alternate rates.
- Exact common origin.
- Expected frame count.
- Dither behavior.
- Clipping warning.
- Linked normalization.
- Large RF64 output.
- No mixer/speed processing in raw export.

---

## 21. Performance and practical acceptance targets

These are targets to measure during implementation, not current benchmark results.

### 21.1 Analysis

- Complete all five supplied recordings on a qualified GPU.
- Record wall time, real-time factor, peak VRAM, and peak host RAM.
- Keep long-track host memory bounded by windowing.
- Publish actual observed device/profile requirements.
- Do not promise a fixed separation time before measurement.

### 21.2 Playback

- No cumulative relative stem drift.
- No source-time drift across speed changes.
- No skipped content after buffering.
- Playhead generally within approximately 30 ms of estimated audible output in foreground operation.
- Smooth mute/solo/gain transitions.
- Correct repeated-loop duration.
- Stable memory use during a 60-minute playback test.

### 21.3 Responsiveness

- Mixer changes acknowledged promptly.
- Audible mixer response bounded by documented DSP lookahead.
- Cached play/seek remain within Milestone 1 targets where processing latency permits.
- Long separation/export/save operations do not block the browser.
- Cancellation is acknowledged immediately even if worker cleanup takes several seconds.

### 21.4 Listening review

For every supplied recording:

1. Listen to bass solo.
2. Listen to Others solo.
3. Compare their sum against the reference.
4. Inspect bass attacks and sustained notes.
5. Listen around outer-window joins.
6. Practise a selected passage at 0.5× and 0.75×.
7. Test a short repeated loop.
8. Check stereo image at normal and changed speed.
9. Export stems and verify alignment.
10. Save, close, reopen, and repeat playback.

Separation artifacts must be reported as model limitations, not concealed by normalization or postprocessing.

---

## 22. Implementation order and gates

| Gate | Work packages | Required outcome |
|---|---|---|
| A | M2.1–M2.4 | Qualified runtime, verified model, reproducible input |
| B | M2.5–M2.7 | Validated separation, residual, caching, retained versions |
| C | M2.8 | Aligned waveform tracks and synchronized mixer |
| D | M2.9–M2.10 | Pitch-preserving speed with tested latency mapping |
| E | M2.11–M2.12 | Reliable saved loops and bounded buffering |
| F | M2.13 | Verified aligned WAV exports |
| G | M2.14–M2.16 | Safe self-contained save/open |
| H | M2.17–M2.21 | Integrated interfaces and full acceptance evidence |

### Final completion checklist

- [ ] Pinned Demucs runtime installs independently of the core app.
- [ ] Every required bundled Demucs artifact has verified provenance and hash, remains outside source control during development, and is copied into the release bundle deterministically.
- [ ] At least one real local inference path is qualified.
- [ ] GPU selection uses stable device identity.
- [ ] CPU fallback is explicit.
- [ ] Separation progress covers the full preset.
- [ ] Cancellation does not damage existing results.
- [ ] Long-track processing has bounded memory.
- [ ] All stems have matching project timing.
- [ ] Bass + Others reconstructs its reference within numerical tolerance.
- [ ] Four-stem reconstruction error is measured honestly.
- [ ] Identical requests reuse cached outputs.
- [ ] Reruns preserve previous results.
- [ ] All active waveforms share one timeline.
- [ ] Mixer semantics are tested.
- [ ] Stems share one source clock.
- [ ] Speed control preserves pitch from 0.25× to 2×.
- [ ] Latency and 1× bypass transitions are verified.
- [ ] Saved loops repeat without cumulative drift.
- [ ] New manual edits support undo/redo.
- [ ] WAV stems export with common alignment.
- [ ] Portable saves contain only the selected project.
- [ ] Failed saves preserve the last successful file.
- [ ] Portable reopen works without model files or original paths.
- [ ] Offline analysis with the bundled Demucs baseline and offline playback pass.
- [ ] All five user recordings complete the practical acceptance workflow.
- [ ] Actual timing, memory, and quality limitations are documented.

### Handoff to Milestone 3

Deliver:

1. A complete bass-practice workflow.
2. Immutable, aligned stem assets.
3. Reusable separation-module and result-cache contracts.
4. A transport that handles variable speed and loop iterations.
5. Saved source-time loops.
6. Project-only portable snapshots.
7. Verified export and recovery paths.
8. A clear insertion point for beat/downbeat analysis, tempo maps, musical rulers, snapping, metronome, and count-in.

