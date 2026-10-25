# Milestone 7 — Quality models and YouTube: detailed implementation specification

This expands Milestone 7 in Section 13 of [`basseparate_project_plan.md`](../product/basseparate_project_plan.md).

It builds on `milestone0.md` through `milestone6.md`. Those milestones remain authoritative for the application foundation, immutable source assets, waveform/playback timing, Demucs separation, practice transport, musical grid, harmony analysis, bass transcription, persistent command history, retained analysis versions, dependency/staleness state, crash recovery, exports, migrations, and cache management. Milestone 7 must extend those systems rather than introduce a parallel model, download, import, or pipeline architecture.

The scope of this milestone is exactly the main plan's “Quality models and YouTube” milestone: add SCNet and RoFormer separation adapters; verify their checkpoints and licenses; benchmark the defined comparison set; publish named quality/speed presets; add six-stem guitar mode; consolidate the shared model manager across bundled and separately installed models and generalize explicit download progress for non-bundled artifacts; integrate yt-dlp/EJS YouTube retrieval with robust cancellation and update handling; add whole-pipeline execution; and prove cache reuse across module runs.

---

## 1. Required outcome and milestone boundaries

### 1.1 Complete user workflow

At completion, the user can:

1. Launch basseparate and open any existing Milestone 0–6 project without installing or downloading a model.
2. Open one central model manager and inspect all registered model families required by separation, rhythm, harmony, and transcription.
3. See exact installation state, model/checkpoint version, expected download size, disk use, license/provenance state, hardware qualification state, and supported analysis capabilities.
4. Explicitly install a registered non-bundled separation model or model bundle with byte-level progress, cancellation, integrity checking, and atomic publication; the bundled Demucs baseline requires no download/install action.
5. Import a registered model bundle offline using the existing trusted-manifest mechanism.
6. Remove a separately installed model that is not in use without damaging any saved project or retained analysis result; bundled Demucs is not removable through ordinary model management.
7. Run the existing Demucs quality baseline.
8. Run the faster Demucs preset where available.
9. Run the pinned SCNet XL IHF comparison model locally.
10. Run the pinned BS-RoFormer multistem comparison model locally.
11. Compare retained separation result versions without overwriting older Demucs results.
12. See measured runtime, peak VRAM/RAM, stem quality diagnostics, downstream bass-transcription metrics, and provenance for benchmarked model profiles.
13. Choose named quality/speed presets whose exact model/checkpoint/profile identities are visible.
14. Run the six-stem Demucs guitar-capable mode and receive all validated model output roles, including guitar when the pinned model declares it.
15. Display, mix, solo, mute, practise, export, and retain six-stem result sets through the existing multi-stem workflow.
16. Paste a single supported YouTube video URL into the import workflow.
17. Retrieve YouTube metadata before committing to a download.
18. See title, duration, selected audio format information, and retrieval requirements without embedding a remote player or thumbnail.
19. Explicitly start the audio retrieval.
20. Observe durable progress for metadata retrieval and media download.
21. Cancel an in-progress YouTube retrieval and leave the target project recoverable.
22. Receive actionable errors for unavailable, private, unsupported, age-/authentication-gated, extractor-broken, network, disk, and FFmpeg failures without bypassing access controls.
23. Resume/retry only where the verified retrieval implementation can do so safely.
24. Feed the completed downloaded media into the same hash/probe/decode/waveform/import path used for local files.
25. Reopen the resulting project later without re-fetching YouTube media and without network access.
26. Update the yt-dlp extractor/runtime independently of analysis-model updates through an explicit maintenance action.
27. Press **Analyze All** and receive an explicit preflight plan describing required models, reusable cached stages, scheduled modules, skipped modules, devices, and estimated storage/resource needs.
28. Install any missing required models explicitly before the pipeline begins; Analyze All never silently downloads them.
29. Run one dependency-aware pipeline that reuses the existing separation, rhythm, tempo/meter, harmony/key, and bass-transcription modules.
30. See partial results progressively as nodes complete.
31. Preserve successful results if another pipeline node fails or is cancelled.
32. Retry only failed/stale nodes while reusing exact cache hits from successful nodes.
33. Continue using individual analysis buttons; Analyze All is orchestration, not the only way to run analysis.
34. Save the project as a self-contained `.basseparate` archive and reopen it without any model weights, source URL access, or network connection.
35. Use all Milestone 6 undo/redo, version-selection, stale-result, export, cache, and recovery behavior unchanged across the new model families and YouTube sources.

### 1.2 Included capabilities

Milestone 7 includes:

- An isolated MSST-compatible separation runtime.
- A concrete SCNet XL IHF adapter for the checkpoint named in the main plan.
- A concrete BS-RoFormer multistem adapter for the checkpoint named in the main plan.
- Exact model/configuration/checkpoint registry records and hashes resolved during implementation.
- Independent code-license and weight/checkpoint-license verification.
- Hardware qualification for each new model/device pair.
- Long-track bounded-memory inference profiles for each new adapter.
- Validation and atomic publication into the existing immutable `SeparationResultSet` model.
- Six-stem `htdemucs_6s` integration through the existing Demucs worker.
- Six-stem waveform, mixer, playback, project, cache, and export integration.
- A project-wide model manager built on the model registries introduced by earlier milestones, representing bundled Demucs as bundled/verifiable/qualifiable and non-removable through ordinary model cleanup.
- Durable network-download jobs for model artifacts.
- Explicit byte progress, cancellation, safe resumption where supported, hashing, and atomic publication.
- Separate model-store accounting from rebuildable analysis cache accounting.
- The project plan's separation benchmark and promotion procedure.
- Stable named separation presets and explicit exact-model disclosure.
- yt-dlp integration.
- A supported local JavaScript runtime / EJS path required by the selected yt-dlp build.
- Single-video YouTube URL validation and metadata retrieval.
- Explicit audio-stream retrieval without unnecessary lossy re-encoding.
- Retrieval provenance, cancellation, recovery, and actionable failure states.
- Independent extractor/runtime updating.
- A dependency-aware whole-pipeline execution graph.
- Pipeline preflight, resource scheduling, progressive publication, failure isolation, cancellation, restart, and cache reuse.
- API/schema/database/portable-project updates needed for these capabilities.
- Automated tests, benchmark reports, listening evaluation, failure injection, and documentation.

### 1.3 Explicitly deferred capabilities

Milestone 7 does **not** add:

- Playlist or channel downloading.
- Automatic bulk retrieval from YouTube.
- Browser-cookie extraction.
- Authentication bypass, access-control bypass, DRM bypass, or private-content circumvention.
- Automatic re-download of a missing YouTube source when a project opens.
- Remote cloud inference.
- Remote audio upload for analysis.
- Remote thumbnails or embedded YouTube players.
- Arbitrary URL downloading from unsupported hosts.
- An automatic claim that SCNet or RoFormer is universally “best.”
- Automatic model-family replacement based only on benchmark headline numbers.
- Experimental SAM Audio, MVSep Mega, BS-RoFormer-SW, or other research candidates from the main plan's optional-research list.
- New chord, beat, key, or bass-transcription algorithms beyond selecting/running the implementations already delivered by earlier milestones.
- New editing semantics; existing editors and Milestone 6 command history remain authoritative.
- Release packaging, final Chromium/Firefox/Safari acceptance, or installer publication. Those belong to Milestone 8.

### 1.4 Prerequisite state inherited from Milestone 6

Before Milestone 7 is considered valid, the application must already provide:

1. Immutable source, canonical PCM, and derived audio assets.
2. Stable project source-frame timing.
3. Demucs `htdemucs_ft` separation and retained result versions.
4. Persistent separation result selection and stale-result propagation.
5. Multi-stem synchronized playback, mixing, loops, and time stretching.
6. Rhythm, tempo/meter, harmony/key, and bass-transcription modules.
7. Persistent semantic command history and undo/redo.
8. Named project revisions/checkpoints.
9. Unified automatic/edited/model/input result selection.
10. Dependency and staleness tracking.
11. Durable jobs and worker subprocess supervision.
12. Crash recovery and staging-ownership conventions.
13. Asset validation and atomic publication.
14. Portable project save/open with model weights excluded.
15. Export presets and durable WAV/FLAC/MP3/analysis exports.
16. Cache inventory, reference pinning, LRU cleanup, and separate model-storage accounting.
17. Missing/corrupt/rebuildable asset classification.
18. Project migration fixtures and rollback-safe schema updates.
19. Authenticated loopback APIs and local-only ordinary operation.
20. Regression coverage for the five existing local recordings.

Milestone 7 must repair failures at their owning boundary rather than hiding them with model-specific workarounds.

### 1.5 Definition of the milestone boundary

Milestone 7 is complete only when quality-model selection, model installation, YouTube retrieval, and Analyze All operate as first-class extensions of the existing project workflow.

The following are **not** sufficient:

- making an SCNet script run from a terminal without producing a normal retained separation result;
- loading a RoFormer checkpoint without proving its matching configuration and provenance;
- listing model names in the UI without verified local artifact identities;
- reporting a benchmark winner without downstream bass-transcription and resource measurements;
- exposing “Quality” while hiding the concrete model/checkpoint selected;
- treating six-stem output as an unrelated second mixer implementation;
- invoking yt-dlp and leaving its file outside the normal import/content-addressed storage path;
- embedding a remote YouTube player instead of locally retrieving the requested audio;
- automatically installing models when Analyze All is clicked;
- rerunning modules that already have exact valid cache hits;
- discarding successful pipeline nodes because a later node failed;
- opening a project and automatically reconnecting to YouTube or downloading weights.

---

## 2. Fixed implementation decisions for Milestone 7

| Area | Milestone 7 decision |
|---|---|
| Existing separation baseline | Demucs `htdemucs_ft` remains the baseline until benchmark/promotion evidence justifies a different named default |
| Fast four-stem option | Demucs `htdemucs` where the pinned Demucs runtime exposes it and qualification passes |
| Six-stem option | Demucs `htdemucs_6s` |
| SCNet comparison model | SCNet XL IHF checkpoint `model_scnet_ep_36_sdr_10.0891.ckpt` with its matching verified published configuration |
| RoFormer comparison model | BS-RoFormer checkpoint `model_bs_roformer_ep_17_sdr_9.6568.ckpt` with its matching verified published configuration |
| SCNet/RoFormer engine | Dedicated isolated MSST adapter/runtime |
| Model result semantics | Every run produces an immutable separation result version; new models never overwrite Demucs results |
| Preset semantics | Named preset = explicit immutable model/checkpoint/adapter/parameter profile, not an opaque “best” switch |
| Promotion rule | Follow Section 12.4; keep multiple named presets when evidence conflicts |
| Six-stem handling | Use the same `SeparationResultSet`/Stem/mixer/transport/export architecture with six declared roles |
| Model downloads | Explicit network-enabled durable jobs for non-bundled models; bundled Demucs requires no download. Never inference-time implicit downloads |
| Model storage | Separately installed model storage is distinct from rebuildable cache; bundled Demucs lives inside the application bundle. Neither is subject to ordinary LRU cache eviction |
| Download publication | Staging + hash/config verification + atomic publication |
| YouTube scope | One supported YouTube video URL at a time |
| YouTube retrieval | yt-dlp + FFmpeg + supported local JS/EJS runtime |
| YouTube media preservation | Preserve the selected downloaded stream without unnecessary lossy re-encoding, then pass through normal import/decode |
| YouTube reopen | Never re-fetch automatically |
| Extractor maintenance | Independent explicit updater; separate from model manager/update actions |
| Offline mode | Disables non-bundled model retrieval, extractor updating, and YouTube retrieval; bundled Demucs inference and existing projects/analysis/playback remain usable |
| Analyze All | Orchestrator over existing module contracts/jobs; not a second analysis implementation |
| Pipeline result policy | Publish nodes progressively; preserve successful nodes after partial failure |
| Pipeline cache | Exact existing per-module cache identities remain authoritative |
| Individual module buttons | Remain available |
| Project save | Includes retrieved source media/provenance/results according to existing portable-project rules; excludes model weights/runtimes |

### 2.1 No universal “best model” abstraction

The main plan explicitly requires measured usefulness rather than treating an architecture name or headline benchmark as proof of superiority. Therefore:

1. Preserve exact model identity in every run and preset.
2. Keep baseline, challenger, and six-stem profiles independently selectable.
3. Record benchmark results by corpus/category and device.
4. Do not convert one aggregate metric into an unsupported universal ranking.
5. If SCNet improves one target category but regresses another, keep both profiles visible.
6. If RoFormer provides better listening results but worse downstream bass-note accuracy, record the tradeoff explicitly.
7. A “Recommended Quality” alias may exist only after promotion gates pass and must show the exact target profile.
8. Changing the alias target in a later release does not alter old project provenance or cache identities.

### 2.2 New models join the existing separation contract

SCNet, BS-RoFormer, and `htdemucs_6s` must output the same project-level abstractions used by Milestone 2:

- `SeparationRun`;
- `SeparationResultSet`;
- validated `Stem` records;
- aligned project-rate audio assets;
- waveform-cache references;
- playback representations;
- reconstruction/diagnostic metrics where meaningful;
- provenance and confidence semantics;
- immutable result identity.

Adapter-native tensors, source-ordering conventions, model sample rates, chunk policies, and checkpoint formats remain behind adapters.

### 2.3 YouTube is a retrieval source, not a second media model

YouTube retrieval has one architectural endpoint: a committed immutable source-media asset entering the same import path as a local upload.

Consequences:

- the browser never streams analysis audio directly from YouTube;
- all analysis still operates on local managed assets;
- the downloaded stream receives normal hashing/probing/decoding;
- content deduplication uses actual bytes/transformation identity rather than URL alone;
- the source URL is provenance, not the authoritative source after retrieval;
- project reopen uses saved local assets;
- a dead/deleted/changed YouTube URL cannot rewrite the project's source;
- a later manual re-fetch is a new explicit import/retrieval action.

### 2.4 Analyze All is a graph planner over existing modules

The pipeline planner must use module contracts and dependency identities already established by earlier milestones.

It must not:

- call private adapter functions directly;
- construct hidden untracked results;
- bypass cache lookup;
- bypass durable job storage;
- bypass device scheduling;
- bypass dependency/staleness recording;
- make silent model substitutions;
- mutate manual edited branches.

### 2.5 Network-enabled work is isolated

Ordinary application startup, project opening, playback, editing, cached analysis, and inference remain network-independent.

Network-enabled operations are limited to explicit actions such as:

- install a registered model;
- update the registered yt-dlp/extractor runtime;
- retrieve explicitly requested YouTube media.

They use distinct job types and clear network-required UI states.

---

## 3. Work package M7.1 — Verify Milestone 0–6 prerequisites and establish regression baseline

### 3.1 Full prerequisite verification

Before adding new model families:

1. Run the Milestone 0–6 automated suites.
2. Launch the application with network disabled and no Milestone 7 model installed.
3. Open each existing test project.
4. Verify original playback and waveform rendering.
5. Verify the Demucs baseline result can still be selected and played.
6. Verify rhythm, harmony, and transcription retained results reopen.
7. Verify persistent undo/redo after restart.
8. Verify stale-result status for a transcription tied to a non-active bass stem.
9. Verify portable save/open without models.
10. Verify cache cleanup does not delete installed model storage.
11. Verify WAV/FLAC/MP3 and analysis exports.
12. Verify recovery after an intentionally interrupted ordinary analysis job.
13. Record baseline startup time, memory, project-open time, and prepared-playback underrun behavior.
14. Record all failures before Milestone 7 implementation.

### 3.2 Baseline separation benchmark

Freeze a reproducible baseline report for the existing Demucs implementation before challengers are integrated:

- exact Demucs runtime/version;
- exact `htdemucs_ft` model identity;
- adapter/profile version;
- device/GPU UUID;
- runtime;
- peak VRAM;
- host RAM;
- stem validation diagnostics;
- reference separation metrics on the licensed evaluation subset;
- downstream bass-transcription metrics;
- blinded listening form/results where already available.

This baseline becomes the comparison anchor; do not re-create it with a changed runtime after challenger results are known.

### 3.3 Benchmark environment identity

Record:

- application commit/version;
- OS/kernel;
- CPU;
- RAM;
- GPU names and UUIDs;
- driver version;
- PyTorch/CUDA runtime identity;
- worker environment fingerprints;
- FFmpeg build;
- evaluation corpus manifest hash.

**Acceptance:** Milestone 7 begins from a known regression-clean state and a frozen baseline comparison environment.

---

## 4. Work package M7.2 — Extend model registry and installation-state contracts

### 4.1 Registry entry schema

Generalize the existing model registry into a project-wide checked-in registry where every installable model entry can declare:

- stable `model_id`;
- display name;
- model family;
- analysis module(s) served;
- adapter/runtime ID;
- adapter-compatible version range;
- upstream repository/revision;
- configuration identity;
- one or more artifact records;
- artifact URL/resolver information;
- expected byte sizes where authoritative;
- SHA-256 hashes resolved during implementation;
- model input requirements;
- output vocabulary/roles;
- precision support;
- CPU/GPU support;
- expected memory class;
- code license record;
- weight/checkpoint license record;
- required notices;
- redistribution/bundling status;
- qualification-fixture identity;
- optional deprecation/replacement metadata.

### 4.2 Artifact record

Each downloadable artifact has:

- artifact ID;
- filename treated as display metadata, not identity;
- expected size;
- expected SHA-256;
- official source/resolver;
- configuration relationship;
- required/optional role;
- license/provenance linkage;
- safe-load policy;
- publication relative path within managed model storage.

### 4.3 Distribution and installation state

Represent distribution state separately as `bundled` or `separately_installed`. For bundled models, expose `bundled_available`, `bundled_missing`, or `bundled_corrupt` and do not route them through install/remove state transitions.

For separately installed models, represent installation state explicitly:

- `not_installed`;
- `partial`;
- `downloading`;
- `verifying`;
- `installed_unqualified`;
- `installed_qualified`;
- `corrupt`;
- `incompatible_runtime`;
- `license_unresolved`;
- `unavailable_source`;
- `deprecated`.

Do not collapse every failure into “not installed.”

### 4.4 Qualification state is per model/runtime/device profile

A model can be installed but not qualified on a particular GPU.

Persist or derive:

- model manifest hash;
- runtime fingerprint;
- device UUID/type;
- qualification fixture hash;
- pass/fail;
- timestamp;
- failure reason;
- observed runtime;
- observed peak device memory;
- relevant warnings.

### 4.5 Registry compatibility

Existing Demucs, Beat This!, BTC/ChordMini, and torchcrepe records should migrate or adapt to the generalized registry without invalidating old project provenance. Demucs `htdemucs_ft` is represented with distribution state `bundled`; separately installed models retain install/remove state.

Do not change historical model IDs casually. Use explicit aliases/migrations where required.

**Acceptance:** all model families can be represented through one typed registry with explicit distribution state; bundled Demucs and separately installable families share provenance/qualification contracts without forcing bundled assets through download/remove semantics or changing analysis-specific result schemas.

---

## 5. Work package M7.3 — Add SCNet and BS-RoFormer registry records with verified checkpoint/configuration pairing

### 5.1 Required SCNet record

Create a checked-in record for the main plan's concrete challenger:

- family: SCNet XL IHF;
- checkpoint: `model_scnet_ep_36_sdr_10.0891.ckpt`;
- matching published configuration verified during implementation;
- MSST adapter/runtime requirement;
- input/output roles from the verified configuration;
- checkpoint hash;
- configuration hash;
- code license evidence;
- checkpoint/weight license evidence;
- official provenance URL(s);
- required notices;
- model size;
- expected memory class.

Do not register the checkpoint until its configuration pairing is verified.

### 5.2 Required BS-RoFormer record

Create a checked-in record for:

- family: BS-RoFormer multistem;
- checkpoint: `model_bs_roformer_ep_17_sdr_9.6568.ckpt`;
- matching published configuration verified during implementation;
- MSST adapter/runtime requirement;
- declared stem roles;
- checkpoint/config hashes;
- license/provenance data;
- size and memory class.

### 5.3 Missing or changed upstream artifact

If an exact planned artifact is no longer obtainable from its authoritative source:

1. Do not silently substitute an identically named mirror.
2. Mark the registry entry unavailable.
3. Record what could not be verified.
4. Keep the baseline Demucs implementation available.
5. Require an explicit design/registry change to adopt an alternative artifact.
6. Give the replacement a distinct identity and benchmark it independently.

### 5.4 License gate

A challenger cannot be exposed as installable until:

- code license is recorded;
- checkpoint/weight terms are recorded separately;
- restrictions/unresolved terms are explicit;
- required notices are known;
- the intended private-use installation path is consistent with the recorded terms.

**Acceptance:** each challenger has a reproducible exact model+configuration identity; filenames or architecture names alone never determine the model.

---

## 6. Work package M7.4 — Create the isolated MSST separation runtime

### 6.1 Environment boundary

Create a dedicated locked environment for SCNet/RoFormer inference.

Requirements:

1. Keep the core FastAPI environment free from mandatory MSST/PyTorch imports.
2. Pin the Python version compatible with the chosen MSST revision.
3. Pin MSST revision and inference dependencies.
4. Pin a supported PyTorch/CUDA combination.
5. Record the full lock and environment fingerprint.
6. Launch through an explicit interpreter path.
7. Never run package installation during normal application startup.
8. Never download model weights during worker startup/inference.
9. Keep remote/training functionality outside the exposed worker capability.
10. Disable or refuse any adapter path that invokes an external inference service.

### 6.2 Worker capability declaration

The runtime describes:

- stable worker/runtime ID;
- protocol version;
- supported adapter versions;
- supported model families;
- CPU/GPU support;
- supported precision modes;
- cancellation granularity;
- expected memory classes;
- supported source roles;
- output role discovery;
- runtime fingerprint;
- safe checkpoint-loading policy.

### 6.3 Checkpoint-loading safety

Where the upstream format requires legacy pickle-like checkpoint loading:

1. Accept only registered managed artifacts with verified hashes.
2. Load in the isolated worker, never in the backend process.
3. Disable arbitrary remote-code hooks.
4. Avoid user-supplied arbitrary checkpoint paths.
5. Record the loader/profile used.
6. Treat an unregistered checkpoint as unsupported rather than trying it automatically.

### 6.4 Qualification command

Add a developer/user-facing diagnostic path that can test:

- runtime launch;
- model loading;
- short inference;
- output shape/roles;
- finite output;
- GPU memory allocation;
- cleanup.

**Acceptance:** MSST adapters can run without adding imports or network behavior to ordinary backend startup and without trusting arbitrary checkpoint files.

---

## 7. Work package M7.5 — Implement the SCNet separation adapter

### 7.1 Adapter contract

Implement a stable adapter ID/version that maps the verified SCNet configuration into the shared separation-module contract.

The adapter declares:

- input channel/sample-rate requirements;
- output role vocabulary;
- required model artifact IDs;
- supported devices;
- supported precision;
- memory class;
- native chunk/window parameters;
- determinism limits;
- progress capability;
- cancellation behavior;
- provenance/license records.

### 7.2 Input preparation

Reuse existing separation-reference rules:

- stereo canonical source for stereo projects;
- duplicated mono only when required for model input;
- explicit monitoring/reference downmix for multichannel projects;
- continuous resampling to model rate;
- exact transform identity;
- no independent source normalization outside the adapter's documented processing profile.

### 7.3 Native inference first

Before inventing custom outer-window logic:

1. Determine the pinned implementation's supported long-track inference path.
2. Run short whole-input references.
3. Measure host/GPU memory.
4. Use native segmentation/chunking when it is suitable and bounded.
5. Only add a basseparate outer-window adaptation if required by measured memory or track-length constraints.
6. Version any custom adaptation separately.
7. Compare custom output against short native reference cases.

### 7.4 Progress

Map adapter-native work into stable progress stages:

- preparing input;
- loading model;
- inference;
- assembling output;
- project-rate conversion;
- validation;
- publication.

Do not scrape terminal-format progress when structured callbacks/work units are available.

### 7.5 Cancellation

Cancellation must:

- stop scheduling new chunks;
- allow bounded cleanup;
- terminate the worker if cleanup exceeds its limit;
- remove incomplete staging outputs;
- preserve previously published results and shared transforms;
- free device memory through process cleanup when necessary.

### 7.6 OOM recovery

If the verified adapter has safe smaller-chunk settings:

1. Record the failed effective profile.
2. Restart the model worker after releasing GPU memory.
3. Retry only through documented bounded profiles.
4. Give changed effective parameters a distinct cache identity.
5. Stop after a finite retry set.
6. Never silently switch to CPU.

**Acceptance:** SCNet can process short and long supported tracks into aligned shared result objects with bounded resource behavior and deterministic provenance.

---

## 8. Work package M7.6 — Implement the BS-RoFormer separation adapter

### 8.1 Stable adapter

Implement BS-RoFormer through the same MSST worker boundary but with a distinct adapter ID/version and model-specific parameter schema.

Do not assume SCNet and RoFormer have identical preprocessing, chunking, overlap, normalization, or output ordering.

### 8.2 Verified configuration drives behavior

Read from the registered/pinned configuration rather than hard-coding architecture assumptions in the backend:

- model sample rate;
- channel requirements;
- target instruments;
- STFT/mel/band configuration where needed by the worker;
- inference chunk size;
- overlap;
- normalization/scaling policy;
- checkpoint architecture parameters.

### 8.3 Long-track processing

Follow the same decision hierarchy as SCNet:

1. Prefer verified upstream inference behavior.
2. Measure boundedness.
3. Add versioned outer-window logic only if necessary.
4. Validate boundaries against whole-input references where feasible.
5. Perform listening checks around any introduced window boundaries.

### 8.4 Output role mapping

Map model-native output names into canonical stem roles using the verified model configuration.

Never map by tensor index without checking the declared label ordering.

### 8.5 Failure/cancellation/publication

Use the same shared staging, cancellation, result validation, and atomic-publication rules as every separation adapter.

**Acceptance:** BS-RoFormer produces a normal immutable `SeparationResultSet`, with no model-family-specific project or mixer state.

---

## 9. Work package M7.7 — Qualify every new model/device pair

### 9.1 Hardware enumeration

Reuse stable GPU UUID/device records from earlier milestones.

Refresh:

- device availability;
- total/free VRAM;
- driver/runtime status;
- current heavy-job occupancy.

### 9.2 Qualification matrix

Qualify at minimum:

- SCNet on RTX 4080 if runtime support succeeds;
- SCNet on RTX 5060 Ti if runtime support succeeds;
- BS-RoFormer on RTX 4080 if supported;
- BS-RoFormer on RTX 5060 Ti if supported;
- CPU only if the adapter genuinely supports it and the runtime is practical enough to expose as an explicit option;
- `htdemucs_6s` on supported Demucs devices.

### 9.3 Qualification fixture

Use a short deterministic stereo fixture that includes:

- bass;
- drums/transients;
- vocals or midrange harmonic content;
- guitar-like content where six-stem qualification is relevant;
- silence boundaries.

Verify:

- worker starts;
- weights load;
- outputs have declared roles;
- outputs are finite;
- timing/shape is valid;
- cleanup returns device memory;
- no network access occurs during inference.

### 9.4 Store measurement, not assumptions

Record actual:

- load time;
- inference time;
- peak VRAM;
- host RAM;
- warnings;
- model/device runtime fingerprint.

Do not assume the second GPU can run a model merely because it has a nominally similar VRAM size.

**Acceptance:** only successfully qualified model/device combinations are selectable for ordinary inference.

---

## 10. Work package M7.8 — Generalize separation input transformations and cache identity

### 10.1 Shared transformation object

Create/reuse a typed separation-input transformation record containing:

- source/reference asset hash;
- source role/downmix identity;
- target sample rate;
- target channels/layout;
- resampling profile;
- amplitude/normalization preprocessing identity;
- adapter version;
- transformation version;
- resulting asset/hash;
- source-time mapping.

### 10.2 Reuse across models only when truly identical

If SCNet and RoFormer require the exact same transformed input bytes/profile, they may reuse the same prepared asset.

If any parameter differs, they receive separate transformation identities.

Do not reuse based only on matching sample rate.

### 10.3 Cache key

A new separation run cache identity includes at minimum:

- reference source hash;
- transformation hash/profile;
- model manifest hash;
- every checkpoint/configuration hash;
- runtime/adapter version;
- inference parameters;
- precision;
- chunk/window/overlap profile;
- normalization profile;
- seed/determinism controls where relevant;
- output-transform profile.

Device identity belongs in the successful result provenance and enters the cache key only where device/profile can materially change result semantics according to the adapter's reproducibility policy.

### 10.4 Old Demucs caches remain valid

Adding generalized fields must not invalidate old Demucs results unless the actual identity schema changes in a way requiring a versioned migration.

**Acceptance:** cache reuse is exact and cross-model prepared-input reuse occurs only with provably identical transforms.

---

## 11. Work package M7.9 — Validate and publish challenger outputs through the existing separation result model

### 11.1 Project-rate conversion

For every new model output:

1. Validate native role list.
2. Convert continuously back to project sample rate.
3. Restore the intended project channel representation.
4. Remove known adapter padding/latency based on explicit transform metadata.
5. Align to project frame zero.
6. Match the canonical project frame count within defined endpoint-rounding tolerance.
7. Reject unexplained offsets or length mismatches.

### 11.2 Required validation

Check:

- all required stem roles present;
- no unexpected missing/duplicate role;
- sample rate;
- channel count/layout;
- frame count;
- finite samples;
- content hash;
- maximum amplitude diagnostics;
- timing offset;
- reconstruction diagnostic where meaningful.

### 11.3 Raw estimates remain raw

Do not silently normalize each output, enforce mixture consistency, or derive a corrected set unless the profile explicitly declares that behavior.

If a consistency correction is offered later, publish it as a separate derived result/profile.

### 11.4 Bass + Others derivation

For any four-stem result that exposes a validated bass estimate, allow the existing Bass + Others representation to derive:

`others = reference_mix - bass`

at project rate, with its existing reconstruction validation and distinct “Others” role.

Do not confuse a model's `other` stem with the residual `others` stem.

### 11.5 Atomic result publication

Use the same transaction pattern:

1. Publish validated audio assets.
2. Create full immutable result set.
3. Attach stem records transactionally.
4. Mark run complete.
5. Queue waveform/playback cache jobs.
6. Emit result/version events.

**Acceptance:** challenger outputs are indistinguishable from Demucs at the project abstraction boundary except for declared roles/provenance/metrics.

---

## 12. Work package M7.10 — Add `htdemucs_6s` six-stem guitar-capable mode

### 12.1 Model registry

Add/complete the registered Demucs six-stem preset with:

- exact maintained Demucs runtime revision;
- `htdemucs_6s` identity;
- all component/model artifact identities required by the pinned release;
- hashes;
- declared source roles from the model itself;
- code/weight provenance;
- known quality limitations from upstream documentation recorded as user-facing notes.

### 12.2 Do not hard-code unverified role ordering

The adapter maps outputs by declared source labels.

The expected user-facing purpose is a guitar-capable six-stem result; however, publication uses exactly the roles exposed by the pinned verified model rather than assuming tensor ordering.

### 12.3 Inference profile

Qualify:

- supported segment length;
- overlap;
- shift count;
- precision;
- long-track outer-window policy inherited from the Demucs adapter;
- memory recovery profiles.

### 12.4 Result compatibility

Publish six-stem results through the existing result-set record with variable-length role collections.

Remove any lingering four-stem-only assumptions from:

- schema validation;
- project selector;
- waveform lane generation;
- mixer construction;
- buffering;
- portable project collection;
- exports;
- UI track ordering;
- cache accounting.

**Acceptance:** the six-stem model is a normal separation preset, not a special project mode requiring a different editor or transport.

---

## 13. Work package M7.11 — Extend mixer, editor, playback, and exports for six-stem results

### 13.1 Track construction

Generate active tracks from the selected result's declared roles.

Do not construct a fixed four-row UI and append guitar/piano as special cases.

### 13.2 Default role ordering

Define a presentation-order map for known canonical roles, but preserve unknown/future declared roles after known roles rather than dropping them.

### 13.3 Per-track state

Use the existing per-track settings:

- gain;
- mute;
- solo;
- pan/balance;
- visibility;
- display height;
- amplitude zoom;
- color.

Project state is keyed by result/stem identity rather than role alone where needed to avoid leaking settings between different result versions.

### 13.4 Playback buffering

Validate bounded playback for six simultaneous stems:

- one shared cursor;
- common underrun behavior;
- speed-dependent lookahead;
- loops;
- time stretching;
- mixer control latency;
- memory caps.

### 13.5 Export

Existing stem export presets must enumerate selected result roles dynamically.

Allow:

- export all stems;
- export selected stems;
- individual role export;
- mixer output.

Metadata records exact result/model provenance.

### 13.6 Downstream bass transcription

When a six-stem result exposes a canonical bass role:

- it is eligible as a transcription input;
- selecting it can create a new transcription dependency chain;
- an old transcription remains tied to its old bass-stem identity;
- switching active separation must never silently retarget the old transcription.

**Acceptance:** six-stem projects practise and export with the same timing guarantees as four-stem projects, and downstream analyses preserve exact dependencies.

---

## 14. Work package M7.12 — Define separation benchmark corpus, protocol, and reproducibility

### 14.1 Evaluation corpus

Use the main plan's corpus classes:

- licensed multitrack mixtures with reference stems;
- manually selected excerpts from the five existing tracks for blinded listening;
- low-B and lower/drop-tuned bass material;
- repeated-note bass passages;
- slides/sustained bass;
- dense full-band mixtures;
- guitar-forward mixtures for six-stem evaluation;
- percussion-heavy material;
- quiet/sparse passages;
- long-form audio for memory/runtime.

Keep development/tuning material separate from final evaluation material.

### 14.2 Frozen corpus manifest

Record:

- fixture IDs;
- file hashes;
- permitted use/license status;
- source sample rates/channels;
- reference stem identities;
- evaluation excerpts/time ranges;
- annotation version;
- train/development/final-evaluation role.

### 14.3 Comparison set

Benchmark at minimum:

1. `htdemucs_ft` baseline.
2. `htdemucs` fast preset if included.
3. `htdemucs_6s` for its relevant stem set and guitar-specific evaluation.
4. SCNet XL IHF exact registered checkpoint/configuration.
5. BS-RoFormer exact registered checkpoint/configuration.

Do not include unverified community checkpoints in the official comparison table.

### 14.4 Controlled settings

For a fair model-level comparison:

- use documented quality-oriented default profiles;
- disclose all chunk/overlap/shift settings;
- run on a declared device profile;
- separate model quality comparison from speed-tuned variants;
- record any OOM fallback profile separately;
- do not mix results from different effective parameters under one label.

**Acceptance:** every benchmark row is reproducible from a corpus manifest, model manifest, adapter profile, and hardware/runtime record.

---

## 15. Work package M7.13 — Measure separation quality, downstream utility, and resource behavior

### 15.1 Reference metrics

Where licensed ground-truth stems exist, measure per target/model:

- SDR or SI-SDR according to the established evaluation implementation;
- bass-specific separation metric;
- vocal/drum/other metrics where applicable;
- guitar metric for six-stem fixtures where reference exists;
- reconstruction error;
- alignment error;
- stereo preservation diagnostics.

### 15.2 Bass-specific listening/analysis diagnostics

Measure or annotate:

- bass leakage from kick/low percussion;
- missing note attacks;
- sustained-note warbling/modulation;
- low-B retention;
- drop-tuning behavior;
- synth-bass behavior;
- slide continuity;
- octave-like contamination.

### 15.3 Downstream transcription metric

Run the same pinned Milestone 5 transcription profile on each model's bass stem for the defined transcription evaluation subset.

Measure:

- voicing precision/recall;
- pitch accuracy;
- octave error rate;
- onset accuracy;
- note-event F-measure;
- low-register subset;
- repeated-note subset;
- slide subset.

This prevents selecting a separator that improves one stem metric while materially harming the application's primary bass-practice workflow.

### 15.4 Runtime/resource metrics

For every model/profile/device:

- wall time;
- real-time factor;
- model load time;
- peak VRAM;
- peak host RAM;
- staging disk overhead;
- final stem disk size;
- worker startup/cleanup time;
- OOM/retry behavior.

### 15.5 Long-track benchmark

Use at least one long recording to verify:

- bounded RAM;
- bounded VRAM;
- no output-length drift;
- no boundary discontinuity from custom chunking;
- cancellation latency;
- storage estimate accuracy.

**Acceptance:** quality comparisons include musical usefulness and resource cost, not only a single separator metric.

---

## 16. Work package M7.14 — Run blinded listening comparisons on non-reference tracks

### 16.1 Listening protocol

For the five existing tracks where reference stems are unavailable:

1. Render matched loudness-monitoring excerpts without altering stored stems.
2. Randomize anonymized result labels for listening sessions.
3. Use fixed source excerpts across models.
4. Evaluate bass isolation, attack clarity, sustained-note stability, low-end leakage, musical naturalness, and artefacts.
5. Record listener and session metadata without claiming ground-truth accuracy.
6. Preserve raw ratings/comments.

### 16.2 Avoid unsupported reference claims

Do not report SDR, precision, or “accuracy” for these tracks without references.

### 16.3 Category-level review

Summarize disagreement by material class rather than averaging away severe regressions.

A model that excels on rock guitars but fails synth bass should retain that explicit tradeoff.

**Acceptance:** private-track listening evidence is clearly distinguished from reference-based metrics and is reproducible enough for future model promotion decisions.

---

## 17. Work package M7.15 — Define promotion rules and named quality/speed presets

### 17.1 Promotion gate

Use the main plan's rule. A challenger is eligible to replace an existing default only when it:

1. Passes license/reproducibility checks.
2. Fits measured memory limits.
3. Completes the evaluation corpus.
4. Does not materially regress bass note-event accuracy.
5. Improves bass separation metrics or documented blinded listening outcomes.
6. Has no severe regression on a target category.

### 17.2 No forced single winner

If evidence conflicts:

- keep multiple named presets;
- expose purpose/tradeoff;
- do not fabricate a total ordering.

### 17.3 Preset record

Define a stable `SeparationPreset` containing:

- preset ID/version;
- display name;
- intended purpose: speed, balanced/default, quality, six-stem, comparison;
- model ID/manifest hash;
- adapter/runtime profile;
- requested parameters;
- preferred device class, if any;
- expected stem roles;
- benchmark-report reference;
- known limitations;
- status: experimental/available/recommended/deprecated.

### 17.4 Suggested naming policy

Use descriptive names that do not overclaim, for example:

- `Demucs Fast — 4 stem`;
- `Demucs Fine-tuned — 4 stem`;
- `SCNet XL IHF — 4 stem quality challenger`;
- `BS-RoFormer — multistem quality challenger`;
- `Demucs 6-stem — guitar/piano experimental`.

If a benchmark-validated generic alias such as `Quality` or `Fast` is published, its detail panel must show the exact underlying preset.

### 17.5 Historical stability

A project run records the concrete preset/model/profile, not merely the alias.

If `Quality` points to a different model in a future release, old results remain reproducible and correctly labeled.

**Acceptance:** preset labels communicate intent and tradeoff while preserving exact provenance and avoiding unsupported universal rankings.

---

## 18. Work package M7.16 — Build the project-wide model manager service

### 18.1 Model catalog endpoint/service

The backend exposes a merged model catalog containing:

- registered model identity;
- capabilities;
- distribution state (`bundled` or `separately_installed`) plus applicable availability/installation state;
- bundled/installed bytes;
- application-bundle or managed-model-store path category without exposing arbitrary filesystem paths to the browser;
- license/provenance summary;
- version/hash;
- qualification state by device;
- update/deprecation status;
- jobs currently using the model.

### 18.2 User actions

Support:

- Inspect distribution state: bundled or separately installed.
- Install non-bundled models.
- Cancel/retry non-bundled installs.
- Verify integrity.
- Qualify on a selected device.
- Import registered offline bundles for separately installed models or registered repair bundles where explicitly supported.
- Remove separately installed local model bytes.
- Refuse ordinary removal of application-bundled Demucs bytes and direct the user to application repair/reinstall if they are missing/corrupt.
- Open license/provenance details.
- Inspect storage use.

Do not add arbitrary unregistered model installation through this interface.

### 18.3 Model removal

For separately installed models, removing weights:

1. Does not delete analysis results.
2. Does not delete project history.
3. Does not invalidate portable projects.
4. Prevents new runs requiring that model until reinstalled.
5. Refuses/defers removal while a job is actively using the files.
6. Removes only managed registered model bytes.
7. Leaves registry metadata and old run provenance intact.

### 18.4 Installation prerequisites

Distinguish:

- model bytes missing;
- runtime missing;
- runtime incompatible;
- license unresolved;
- insufficient disk space;
- network disabled;
- download source unavailable.

### 18.5 Model-store accounting

Display application-bundled model bytes and separately installed model storage as distinct categories, both separate from:

- project assets;
- rebuildable analysis cache;
- waveform/playback caches;
- staging/temp data.

**Acceptance:** one model manager accurately describes bundled and separately installed registered model artifacts without coupling model presence to project integrity or exposing bundled Demucs to ordinary install/remove semantics.

---

## 19. Work package M7.17 — Implement durable explicit model-download jobs

### 19.1 Network-job boundary

Downloads for separately installed models run as durable network-enabled jobs separate from inference workers. The bundled Demucs baseline bypasses this path because its verified artifacts are already part of the application bundle.

A download job records:

- model ID/manifest hash;
- artifact list;
- source URLs/resolvers;
- expected bytes;
- received bytes;
- per-artifact state;
- overall state;
- staging paths/ownership manifest;
- retry metadata;
- resume metadata;
- errors;
- timestamps.

### 19.2 Download state machine

Use explicit states such as:

`queued -> resolving -> downloading -> verifying -> publishing -> qualifying -> completed`

with branches to:

- `cancelling -> cancelled`;
- `failed`;
- `interrupted`.

### 19.3 Progress

Expose:

- total expected bytes when known;
- total downloaded bytes;
- per-artifact bytes;
- transfer rate as informational only;
- current artifact;
- verification phase;
- qualification phase.

Do not display a fake percentage when the server/source does not provide a reliable content length.

### 19.4 Safe resumption

Resume a partial artifact only when the source's response metadata allows the client to prove that the remote object is the same expected object.

Otherwise restart that artifact from zero.

Never append bytes to an unverified changed remote object.

### 19.5 Hash verification

After each artifact completes:

1. Close/flush staging output.
2. Verify byte count where known.
3. Compute SHA-256.
4. Compare with the registered hash.
5. Reject mismatches.
6. Preserve diagnostic metadata but do not publish corrupt bytes.

### 19.6 Atomic model publication

Publish the entire registered model/preset atomically enough that inference never sees a half-installed bundle.

For multi-file models:

- place verified artifacts in an installation staging directory;
- verify manifest/configuration relationships;
- write installation metadata;
- rename/switch managed installation pointer atomically;
- mark installed only afterward.

### 19.7 Cancellation/recovery

On cancellation/interruption:

- stop network reads;
- close files;
- preserve resumable partials only when ownership/identity is clear;
- remove unsafe temp files;
- leave previous installed model version untouched;
- never mark partial install as complete.

**Acceptance:** non-bundled model installation is observable, cancellable, integrity-checked, crash-safe, and never implicit; bundled Demucs is independently visible, integrity-checkable, and qualifiable without entering the download/install state machine.

---

## 20. Work package M7.18 — Complete offline model import and model-integrity operations

### 20.1 Offline bundle format

Reuse/generalize earlier model-bundle behavior:

- registered manifest identity;
- artifact bytes;
- hashes;
- license notices;
- no executable plugin code supplied by the bundle;
- optional qualification fixture metadata.

### 20.2 Import flow

1. Select bundle locally.
2. Validate bundle structure.
3. Resolve expected registered model.
4. Reject unknown/unregistered arbitrary model IDs unless a future developer-mode mechanism explicitly owns that scope.
5. Verify all hashes.
6. Verify configuration/checkpoint pairing.
7. Preserve notices.
8. Publish atomically.
9. Qualify explicitly or mark installed-unqualified.

### 20.3 Integrity scan

The model manager can verify:

- expected files present;
- sizes;
- hashes;
- installation metadata;
- registry-version compatibility.

### 20.4 Repair

Repair means reinstall/reimport the exact registered model; it does not modify historical result provenance.

**Acceptance:** a user can provision all Milestone 7 models on an offline machine without inference-time network access.

---

## 21. Work package M7.19 — Integrate model storage with Milestone 6 cache/storage management

### 21.1 Separate accounting

Milestone 6 deliberately keeps model storage outside the 50 GiB rebuildable cache policy. Preserve that rule.

### 21.2 Storage overview

Expose:

- installed model bytes by family;
- partial-download bytes;
- old/deprecated registered versions if retained;
- analysis cache bytes;
- project asset bytes;
- staging bytes.

### 21.3 Cleanup

Model removal is an explicit model-manager action.

Ordinary cache cleanup must never delete:

- checkpoint files;
- model configurations;
- runtime environments;
- license notices.

### 21.4 Partial download cleanup

Allow cleanup of:

- cancelled non-resumable partial downloads;
- stale interrupted partials whose remote identity can no longer be proven;
- orphaned staging directories after recovery classification.

Always show what will be deleted.

**Acceptance:** model installations remain safe under cache pressure and storage cleanup is explainable by category.

---

## 22. Work package M7.20 — Add YouTube retrieval runtime and dependency qualification

### 22.1 Toolchain

Use the main plan's selected approach:

- yt-dlp;
- FFmpeg/ffprobe;
- a supported local JavaScript runtime;
- EJS support as required by the selected yt-dlp version for complete YouTube extraction.

### 22.2 Isolation

Keep YouTube retrieval dependencies out of ordinary analysis workers.

A dedicated retrieval worker/process boundary should:

- invoke registered executables with argument arrays;
- avoid shell interpolation;
- use bounded stdout/stderr capture;
- emit structured progress/events;
- support cancellation;
- have no access to arbitrary browser-provided filesystem paths.

### 22.3 Runtime qualification

`basseparate doctor` or a dedicated diagnostics section reports:

- yt-dlp version;
- executable/runtime source;
- JavaScript runtime availability/version;
- EJS support state;
- FFmpeg availability;
- offline mode;
- whether YouTube retrieval is currently usable.

### 22.4 No automatic runtime bootstrap

Do not download/update yt-dlp or a JavaScript runtime merely because the user opens the YouTube dialog.

Install/update remains explicit.

### 22.5 Pinned operational identity

Record the exact retrieval toolchain version in every completed retrieval provenance record.

**Acceptance:** YouTube support has a diagnosable, explicit local runtime and never becomes a hidden dependency of ordinary application startup.

---

## 23. Work package M7.21 — Define YouTube retrieval records and state machine

### 23.1 Retrieval record

Add a durable `ExternalMediaRetrieval` or `YouTubeRetrieval` record containing:

- retrieval UUID;
- target project ID;
- normalized/sanitized source URL metadata;
- provider type: YouTube;
- video ID when successfully resolved;
- requested operation;
- metadata snapshot;
- selected audio-format identity;
- yt-dlp/runtime versions;
- FFmpeg version;
- retrieval start/end timestamps;
- state;
- bytes received/expected when known;
- temporary/staged asset ownership;
- completed source asset ID when published;
- provenance fields;
- warnings/errors;
- cancellation state.

### 23.2 State machine

Use stages such as:

`created -> resolving_metadata -> awaiting_confirmation -> downloading -> verifying -> importing -> completed`

with failure/cancellation/interruption branches.

### 23.3 Project state boundary

A retrieval attempt does not make the project source-ready until the downloaded media has successfully entered the ordinary import pipeline and the target project/source transaction completes.

### 23.4 Retry identity

Retrying a failed retrieval creates a new job attempt or well-defined retry record while preserving prior diagnostic history.

Do not overwrite the prior failure silently.

**Acceptance:** retrieval has durable lifecycle state and a failed network action cannot corrupt the project/source record.

---

## 24. Work package M7.22 — Validate YouTube URLs and retrieve metadata explicitly

### 24.1 Accepted input

Accept one user-supplied YouTube video URL.

Validate:

- URL syntax;
- supported host/domain variants;
- single-video intent;
- no playlist-only request;
- no arbitrary shell/extractor options supplied by the browser.

### 24.2 Metadata resolution

Use yt-dlp structured metadata output to obtain only needed fields such as:

- video ID;
- title;
- duration;
- uploader/channel display metadata where useful;
- availability status;
- candidate audio formats;
- selected format information after resolution.

### 24.3 Privacy/locality

Do not fetch/display external thumbnails in the browser.

Do not embed a remote player.

Do not send project/audio information to external services other than the explicit YouTube retrieval request itself.

### 24.4 Confirmation view

Before download, show:

- title;
- duration;
- provider;
- selected retrieval strategy/format summary;
- estimated size when available;
- local storage destination category;
- notice that internet access is required only for retrieval;
- cancellation option.

### 24.5 Unsupported/access-controlled cases

Return structured errors for cases such as:

- invalid/unrecognized URL;
- no longer available;
- private/restricted;
- authentication required;
- unsupported extractor state;
- no usable audio format;
- metadata timeout/network failure.

Do not add cookie extraction or access-control bypass to “fix” them.

**Acceptance:** metadata resolution is explicit, safe, and provides enough information for the user to decide whether to retrieve the media.

---

## 25. Work package M7.23 — Select and download the YouTube audio stream without unnecessary lossy re-encoding

### 25.1 Format-selection policy

Select an available audio-only stream where practical, prioritizing preservation of the retrieved encoded audio rather than transcoding during download.

If a muxed source must be used, extract/remux the audio stream without unnecessary lossy re-encoding where supported.

### 25.2 Retrieval destination

Write only to an app-owned staging location associated with the durable retrieval record.

Never let the URL/title determine an arbitrary destination path.

### 25.3 Progress

Capture structured yt-dlp progress where supported:

- bytes downloaded;
- total/estimated bytes;
- fragment counts when relevant;
- phase;
- transfer state.

Rate/ETA may be shown as approximate informational fields, not durable correctness criteria.

### 25.4 Cancellation

Cancellation must terminate app-owned yt-dlp/FFmpeg children, reap them, and classify partial files.

### 25.5 Completed download validation

Before entering import:

1. Confirm process success.
2. Confirm output exists and is nonempty.
3. Compute SHA-256.
4. Probe locally with ffprobe.
5. Confirm at least one usable audio stream.
6. Record exact selected format/container/codec.
7. Record retrieval tool versions.

### 25.6 Source URL is provenance only

The committed downloaded file bytes become the source-media identity.

Two URLs yielding identical bytes may deduplicate through ordinary asset hashing while retaining each retrieval's provenance as appropriate.

**Acceptance:** requested audio is downloaded into managed local storage with bounded process control and without avoidable lossy transcode.

---

## 26. Work package M7.24 — Feed YouTube downloads into the existing import/decode pipeline

### 26.1 Reuse Milestone 1 import internals

After retrieval verification, invoke the same backend media-ingest stages used for a completed local upload:

- source-file registration/content hashing;
- ffprobe inspection;
- audio-stream handling;
- canonical PCM decode;
- monitoring downmix if needed;
- waveform generation;
- playback representation;
- project source attachment.

### 26.2 Avoid browser re-upload

The already-local downloaded staging file should enter the backend import service directly; do not send it back through the browser upload protocol.

### 26.3 Deduplication

Reuse an existing identical source asset when the content hash and relevant source metadata policies permit it.

### 26.4 Provenance

Attach retrieval provenance separately from source-media content identity:

- original URL;
- resolved video ID;
- title at retrieval time;
- retrieval date;
- yt-dlp version;
- selected remote format ID(s);
- downloaded container/codec;
- retrieval job ID.

### 26.5 Portable project

When the standard portable-project policy includes the original imported media, include the completed downloaded media bytes exactly as the source asset.

Do not require the URL to remain live.

**Acceptance:** after retrieval, no analysis/playback code needs to know whether the source originally came from a local file or YouTube.

---

## 27. Work package M7.25 — Implement YouTube failure, cancellation, interruption, and recovery behavior

### 27.1 Failure taxonomy

Map retrieval problems into actionable codes, for example:

- `YOUTUBE_URL_INVALID`;
- `YOUTUBE_UNSUPPORTED_URL`;
- `YOUTUBE_VIDEO_UNAVAILABLE`;
- `YOUTUBE_ACCESS_RESTRICTED`;
- `YOUTUBE_AUTH_REQUIRED`;
- `YOUTUBE_EXTRACTOR_FAILED`;
- `YOUTUBE_JS_RUNTIME_MISSING`;
- `YOUTUBE_NETWORK_ERROR`;
- `YOUTUBE_TIMEOUT`;
- `YOUTUBE_NO_AUDIO_FORMAT`;
- `YOUTUBE_DOWNLOAD_FAILED`;
- `YOUTUBE_FFMPEG_FAILED`;
- `YOUTUBE_DISK_FULL`;
- `YOUTUBE_CANCELLED`.

### 27.2 Error UX

Every failure states:

- what failed;
- whether any local source bytes were committed;
- whether the project remains empty/unchanged;
- whether retry is reasonable;
- whether tool update may help;
- whether the condition requires account/access that basseparate intentionally does not bypass.

### 27.3 Cancellation semantics

If cancellation occurs before source publication:

- target project remains in its prior valid state;
- partial retrieval bytes remain only if safely resumable/classified;
- no source asset reference points at incomplete media.

### 27.4 Crash recovery

On application restart:

1. Mark active retrieval jobs interrupted.
2. Inspect ownership manifests.
3. Reuse only complete verified downloaded files.
4. Preserve safe resumable state only when identity can be proven.
5. Remove or classify partial temp files.
6. Never auto-restart network retrieval without explicit user action.

### 27.5 Existing project isolation

A failed retrieval into one empty/new project must not affect other projects, model files, analysis results, or history.

**Acceptance:** YouTube errors behave like controlled import failures rather than project corruption.

---

## 28. Work package M7.26 — Add independent yt-dlp/extractor updating

### 28.1 Separate update domain

Extractor/tool updates are not model updates.

Keep separate:

- registry/update channel;
- UI action;
- version display;
- storage category;
- rollback record;
- license notices.

### 28.2 Explicit check/update

Provide explicit actions such as:

- Check retrieval-tool status/version.
- Update yt-dlp/extractor component.
- Verify JavaScript runtime compatibility.
- Roll back to the previous known-working managed version where the packaging strategy supports it.

Do not update on startup or before every YouTube request automatically.

### 28.3 Managed update strategy

The exact mechanism depends on final packaging, but Milestone 7 must define a reproducible development/runtime strategy that:

- verifies the downloaded update source/artifact;
- stores exact version;
- does not overwrite unrelated system packages;
- leaves the prior version recoverable until the new version passes a metadata-resolution smoke test;
- records required notices.

### 28.4 Update qualification

After update:

1. Run `--version`/equivalent.
2. Verify JavaScript/EJS support.
3. Resolve metadata for a controlled public test fixture URL where network test execution is allowed.
4. Do not download full media for a basic extractor qualification unless required.
5. Mark the toolchain qualified or roll back/disable it.

### 28.5 Offline behavior

When offline mode is enabled:

- update check/action is disabled with a clear explanation;
- installed retrieval tools remain inspectable;
- existing downloaded projects remain fully usable.

**Acceptance:** extractor maintenance can respond to YouTube changes without coupling it to analysis-model releases or ordinary application startup.

---

## 29. Work package M7.27 — Enforce YouTube security and locality boundaries

### 29.1 No bypass behavior

Explicitly prohibit implementation paths that:

- auto-extract browser cookies;
- request user passwords;
- bypass DRM;
- bypass account/access restrictions;
- scrape unrelated private browser state;
- execute arbitrary yt-dlp options from the browser;
- accept arbitrary executable postprocessor commands.

### 29.2 Process execution

Always:

- use argument arrays;
- disable shell interpolation;
- sanitize/validate accepted URL input;
- use app-owned staging directories;
- bound logs;
- redact sensitive query parameters/tokens if ever encountered;
- keep retrieval logs local.

### 29.3 Network observation tests

Verify:

- ordinary startup makes no external requests;
- opening a YouTube-derived project makes no external requests;
- model inference makes no external requests;
- only explicit model install/update/YouTube actions create network traffic.

### 29.4 Frontend isolation

Do not load:

- remote thumbnails;
- remote fonts;
- remote player scripts;
- analytics.

**Acceptance:** YouTube support changes only explicitly requested retrieval behavior and does not weaken the local-only architecture.

---

## 30. Work package M7.28 — Define the whole-pipeline execution graph

### 30.1 Pipeline object

Add a durable `AnalysisPipelineRun` containing:

- pipeline UUID;
- project ID;
- base project revision;
- selected pipeline preset/profile;
- requested module selections;
- selected model/preset identities;
- resolved dependency graph;
- node records;
- cache-hit records;
- device/resource plan;
- start/end timestamps;
- overall state;
- warnings;
- skipped-node reasons;
- failure summary.

### 30.2 Node object

Each pipeline node records:

- node ID;
- module ID/version;
- operation/profile;
- declared dependencies;
- selected model/preset;
- input identities;
- expected output family;
- cache key;
- job ID if executed;
- node state;
- progress;
- output/result IDs;
- skip/cache-hit/failure reason.

### 30.3 Default Analyze All graph

The default plan follows the main plan while using existing module ownership:

1. Confirm/import/decode source only if not already ready.
2. Ensure waveform/peaks required for normal editor use.
3. Run selected separation preset.
4. Run original-mix rhythm analysis.
5. Decode/build tempo map and meter/bar positions from rhythm output.
6. Run original-mix harmony/chord analysis.
7. Run tuning/key analysis according to the existing Milestone 4 profile.
8. Run or reuse the bass-stem-specific tuning estimator after the selected separation produces a bass stem, then run bass transcription using the selected tuning interpretation; fall back explicitly to project/manual tuning only when selected or when no valid bass-stem estimate exists.
9. Publish results progressively.

Resource-independent nodes may execute concurrently when scheduler limits allow.

### 30.4 Optional graph branches

Do not automatically schedule every comparison model.

Optional pipeline presets may add, explicitly:

- challenger separation comparison;
- drum-stem rhythm comparison;
- harmonic-remix chord comparison;
- Basic Pitch comparison;
- other already-defined optional analysis branches.

These must be visible before run.

### 30.5 Individual modules remain first-class

Every pipeline node corresponds to an operation that can also be run through the module's individual UI/API.

No result may be available only through Analyze All.

**Acceptance:** Analyze All is a persisted, inspectable DAG of normal module runs and result identities.

---

## 31. Work package M7.29 — Implement pipeline preflight and explicit plan review

### 31.1 Preflight inputs

Before starting a pipeline, resolve:

- project source readiness;
- selected separation preset;
- selected rhythm/harmony/key/transcription profiles;
- required model installations;
- required runtimes;
- valid cached results;
- stale results;
- devices and current availability;
- expected temporary/final disk needs;
- offline/network state;
- optional nodes.

### 31.2 Preflight output

Show a plan containing:

- nodes to reuse from cache;
- nodes to run;
- nodes blocked by missing model/runtime;
- nodes that will wait on dependencies;
- candidate device assignments;
- expected stem roles;
- explicit optional/skipped modules;
- disk/resource warnings.

### 31.3 Missing models

If required models are missing:

- do not begin hidden downloads;
- show the specific models;
- provide explicit Install actions;
- allow the user to rerun preflight after installation;
- where a module is optional, allow explicit skip.

### 31.4 No silent fallback substitution

If the requested SCNet preset is missing, do not silently run Demucs.

If the requested GPU is unavailable, do not silently launch an hours-long CPU job.

Any fallback must be selected explicitly or defined by a visible user-configured pipeline policy.

### 31.5 Revision handling

Preflight records the project/source state it resolved.

If a hard dependency changes before execution begins, recompute affected nodes or reject the stale plan rather than executing against mismatched identities.

**Acceptance:** the user can understand exactly what Analyze All will execute before expensive work begins.

---

## 32. Work package M7.30 — Schedule pipeline nodes across GPUs/CPU while preserving playback responsiveness

### 32.1 Dependency scheduling

A node becomes runnable only when:

- prerequisites completed or were valid cache hits;
- required model/runtime is available;
- required inputs are valid/current for the selected plan;
- a suitable resource slot exists.

### 32.2 GPU policy

Carry forward the architecture:

- GPUs are independent memory pools;
- one heavy job per GPU initially;
- use GPU UUIDs;
- separation prefers the RTX 4080 when that matches the selected model qualification/profile;
- independent analysis may use the RTX 5060 Ti when qualified;
- never combine VRAM into a fictional 32 GB device.

### 32.3 Example concurrency

When resources/qualification permit:

- selected heavy separation can run on one GPU;
- original-mix Beat This!/chord analysis may run on the other GPU;
- CPU-only tonal/key postprocessing may run with bounded CPU threads;
- playback remains higher priority than batch CPU saturation.

This is a scheduler possibility, not a guaranteed fixed assignment.

### 32.4 Resource reservations

Before dispatch:

- refresh free VRAM;
- account for model resident memory estimates;
- avoid oversubscription;
- use adapter-specific memory class/qualification data;
- queue rather than thrash between OOM failures.

### 32.5 CPU limits

Coordinate CPU threads across simultaneous workers so two GPU jobs do not each monopolize all CPU decode/preprocessing threads.

### 32.6 Playback priority

When prepared playback is active:

- retain enough CPU/I/O headroom for PCM delivery;
- prefer delaying nonurgent preprocessing over causing routine underruns;
- record underrun/performance diagnostics during pipeline stress tests.

**Acceptance:** Analyze All can exploit two GPUs without violating per-GPU memory isolation or making normal practice playback unusable.

---

## 33. Work package M7.31 — Progressive publication, partial success, and failure isolation

### 33.1 Node publication

Each module publishes according to its normal atomic result rules.

The pipeline does not hold all outputs until the final node finishes.

### 33.2 Partial success

If separation and rhythm succeed but chord analysis fails:

- separation remains available;
- rhythm/tempo/meter remains available;
- downstream nodes that do not depend on chords may continue;
- chord-dependent optional nodes are skipped/blocked;
- pipeline finishes as partial/warnings rather than rolling back valid results.

### 33.3 Failure state

Overall pipeline states may include:

- queued;
- running;
- completed;
- completed_with_warnings;
- failed;
- cancelling;
- cancelled;
- interrupted.

### 33.4 Skipped node reasons

Distinguish:

- already satisfied by cache;
- user skipped;
- missing optional model;
- dependency failed;
- dependency unavailable/stale;
- unsupported input;
- insufficient device/resources;
- cancelled;
- not applicable.

### 33.5 Existing results are immutable

A failed rerun never deletes or corrupts older successful result versions.

### 33.6 UI

The pipeline view shows node-level status rather than one undifferentiated progress bar.

**Acceptance:** one module failure does not destroy unrelated completed work, and the user can identify exactly which nodes succeeded or failed.

---

## 34. Work package M7.32 — Verify exact cache reuse across pipeline and individual runs

### 34.1 One cache system

Analyze All must call the same cache lookup used by individual module runs.

There is no pipeline-only cache namespace.

### 34.2 Required reuse scenarios

Test:

1. Demucs result created individually, then Analyze All reuses it.
2. Rhythm result created individually, pipeline reuses activations/decoded/grid stages as permitted by exact identities.
3. Analyze All creates chord result, later individual chord action returns the same cache hit.
4. SCNet result exists; rerunning the same SCNet profile returns it.
5. Switching to RoFormer schedules a new separation while preserving SCNet.
6. Bass transcription tied to Demucs bass is not reused for SCNet bass.
7. Prepared input transform shared between two models only when exact transform identity matches.
8. Pipeline restart after a failed late node reuses all successful upstream outputs.
9. Changing only an output/export setting does not rerun analysis.
10. Changing a model checkpoint/profile invalidates only dependent nodes.

### 34.3 Cache-hit validation

Before reuse:

- result status complete;
- referenced assets exist;
- hashes/metadata valid when integrity requires recheck;
- dependencies match exactly;
- result is not corrupt/incomplete.

### 34.4 Stale versus reusable

A retained result may be stale relative to the project's current active upstream selection but still remain a valid immutable result for its own recorded dependencies.

Pipeline planning must determine whether it satisfies the requested pipeline identities, not delete it because it is not currently active.

**Acceptance:** module cache identities behave identically whether work is requested individually or through Analyze All.

---

## 35. Work package M7.33 — Implement pipeline cancellation, restart, and crash recovery

### 35.1 Cancel whole pipeline

A whole-pipeline cancel action:

1. Marks the pipeline cancelling.
2. Prevents new nodes from starting.
3. Sends cancellation to currently running child jobs.
4. Allows each module's bounded cleanup policy.
5. Preserves all already completed/published nodes.
6. Leaves valid shared cache assets intact.
7. Marks not-yet-started nodes cancelled/skipped appropriately.

### 35.2 Cancel one node

If UI supports node-level cancellation:

- cancel that module job;
- block dependent nodes;
- allow independent nodes to continue if the user/pipeline policy permits.

### 35.3 Application crash/restart

After restart:

- running pipeline becomes interrupted;
- durable child jobs follow existing recovery rules;
- completed result nodes remain complete;
- interrupted inference restarts according to its owning module policy rather than pretending to resume unsupported internal tensors;
- pipeline can be explicitly resumed/replanned using cache hits.

### 35.4 Model-download interaction

Model download jobs are not implicitly part of an already-started pipeline.

If preflight requires installation, installations complete explicitly before analysis plan execution.

### 35.5 Project edits during pipeline

Manual edits do not mutate immutable automatic jobs in flight.

At completion:

- automatic result is attached with its recorded dependencies;
- dependency/staleness logic determines whether it is current relative to newer edits/selections;
- never rewrite the job inputs after it started.

**Acceptance:** pipeline cancellation/recovery follows existing module semantics and cannot roll back committed results.

---

## 36. Work package M7.34 — Add API and shared-contract support

### 36.1 Model-manager APIs

Extend the authenticated `/api/v1/models` family to support operations such as:

- list model catalog/status;
- inspect one model;
- start install;
- import registered offline bundle;
- cancel install job;
- verify integrity;
- qualify model/device;
- remove installed bytes.

Use durable job IDs for long operations.

### 36.2 YouTube APIs

Add/complete:

- create metadata/retrieval request for a single URL;
- get retrieval state;
- confirm/start download;
- cancel retrieval;
- retry where supported.

Do not expose arbitrary yt-dlp command arguments.

### 36.3 Pipeline APIs

Add:

- preflight/plan endpoint;
- start pipeline;
- get pipeline status/details;
- cancel pipeline;
- retry/replan failed pipeline nodes as a new/resumed execution record according to the selected semantics.

### 36.4 Typed event stream

Use existing job/project event infrastructure for:

- download progress;
- model state changes;
- retrieval progress;
- pipeline node progress;
- result publication;
- warnings/failures.

Reconnection must recover durable state from the backend; WebSocket delivery is not authoritative storage.

### 36.5 Error envelopes

Keep standard project error envelopes and request IDs.

### 36.6 Contract generation

Regenerate:

- OpenAPI;
- TypeScript types;
- project/model/pipeline/retrieval schemas;
- portable-project schema if changed.

Run deterministic contract-drift checks.

**Acceptance:** all Milestone 7 functions are available through typed authenticated loopback interfaces with no browser-specific hidden logic.

---

## 37. Work package M7.35 — Add database migrations and persistence records

### 37.1 New persistence areas

Add schema support as needed for:

- generalized model installation state;
- model qualification records;
- network download jobs/artifacts;
- YouTube retrieval records;
- pipeline runs and node records;
- separation preset/version registry metadata if persisted beyond checked-in configuration;
- benchmark report references/metadata.

### 37.2 Migration rules

Use Milestone 6 migration framework:

- ordered migrations;
- backup existing nonempty DB before schema mutation;
- transactional schema changes;
- `user_version`/schema-version update after success;
- rollback on failure;
- old projects remain unchanged at the content level.

### 37.3 Historical compatibility

Old separation runs remain readable even if their model registry entry evolves.

Persist sufficient snapshot provenance on each run so a registry change cannot relabel history incorrectly.

### 37.4 Newer-version handling

Continue refusing to write unsupported future schemas.

**Acceptance:** existing Milestone 0–6 working databases migrate without losing history/results and new network/pipeline records recover after restart.

---

## 38. Work package M7.36 — Integrate new models and YouTube provenance with portable projects

### 38.1 What portable projects include

Continue including the selected project's required source/media, stems/results, analysis artifacts needed for offline review, edit state, history/checkpoints according to Milestone 6 reachability rules.

For YouTube-derived projects, source media is the locally downloaded immutable source asset.

### 38.2 What portable projects exclude

Do not include:

- model weights;
- MSST runtime environment;
- yt-dlp executable/runtime environment;
- JavaScript runtime;
- external login/cookie state;
- requirement to contact the original URL.

### 38.3 Provenance manifest

Portable project may retain nonessential provenance fields such as:

- original YouTube URL;
- video ID;
- retrieval date;
- title snapshot;
- selected format ID;
- retrieval tool version;
- separation model/checkpoint identities.

These are informational and must not trigger network behavior.

### 38.4 Save during running pipeline

Follow Milestone 6 revision-freezing rules.

A save includes only result assets reachable/committed for the frozen project revision and does not wait for unrelated unfinished pipeline nodes unless the user explicitly chooses such behavior.

**Acceptance:** every Milestone 7 project reopens and practises offline with no model/tool/source-server dependency.

---

## 39. Work package M7.37 — Build model-manager frontend UX

### 39.1 Model manager view

Provide filterable sections by capability/family, for example:

- Separation;
- Rhythm;
- Harmony;
- Bass transcription;
- Installed;
- Available;
- Needs attention.

### 39.2 Model card/details

Show:

- model display name;
- stable ID/version/checkpoint;
- purpose/capability;
- installed state;
- download size;
- installed size;
- license/provenance status;
- qualified devices;
- known limitations;
- benchmark link/summary where available;
- Install/Verify/Remove/Qualify actions.

### 39.3 Progress UI

For downloads:

- durable progress survives page navigation/reload;
- cancellation is explicit;
- verification and qualification are separate phases;
- failures show the offending artifact/error without discarding valid existing model versions.

### 39.4 Separation preset selector

In the project analysis UI:

- list named presets;
- show expected stem count/roles;
- show installed/qualified state;
- show exact model under an alias;
- show benchmark-derived purpose/limitations;
- allow device selection consistent with qualification state.

### 39.5 Result version UI

Reuse Milestone 6 version selector for Demucs/SCNet/RoFormer/six-stem result sets.

Do not build model-specific result tabs.

**Acceptance:** users can understand exactly what they are installing and running without needing to inspect configuration files.

---

## 40. Work package M7.38 — Build YouTube import frontend UX

### 40.1 Entry point

Add YouTube as a deliberate import source next to local file import.

### 40.2 URL form

Include:

- one URL field;
- validation feedback;
- metadata lookup action;
- offline/network-required indication;
- no playlist toggle in this milestone.

### 40.3 Metadata confirmation

After lookup show:

- title;
- duration;
- audio/container/format summary;
- estimated download size where reliable;
- provenance notice;
- Download/Cancel.

Avoid remote thumbnails.

### 40.4 Download/import progress

Show stages distinctly:

- resolving metadata;
- downloading;
- verifying;
- inspecting;
- decoding;
- building waveform;
- ready.

The transition from network retrieval to local import should be visible without implying that processing remains online.

### 40.5 Error/retry UX

Errors must distinguish extractor/tool problems from access restrictions and network problems.

Offer relevant actions such as:

- Retry metadata;
- Retry download;
- Check/update extractor;
- Use local file instead;
- Cancel.

Do not suggest access-control bypass.

**Acceptance:** a YouTube import behaves like a durable local workflow rather than a terminal-wrapper dialog.

---

## 41. Work package M7.39 — Build Analyze All frontend UX

### 41.1 Analyze All action

Add a project-level action without removing individual module controls.

### 41.2 Preflight dialog/panel

Show:

- selected analysis preset;
- separation model/preset;
- module list;
- cache hits;
- required installations;
- blocked/skipped modules;
- candidate devices;
- disk warning;
- optional comparison branches.

### 41.3 Running view

Render a node list/DAG-like status summary with:

- pending;
- running;
- cached;
- completed;
- warning;
- failed;
- skipped;
- cancelled.

Display overall progress only as a summary; node states remain authoritative.

### 41.4 Progressive editor updates

As normal results publish:

- waveform/stems may appear;
- rhythm lane may appear;
- musical grid may become available;
- chord/key lanes may appear;
- transcription appears after dependencies complete.

Do not block the editor behind a modal until the full pipeline ends.

### 41.5 Retry

Offer a retry/replan action focused on failed/blocked/stale nodes while showing which upstream results will be reused.

**Acceptance:** Analyze All is understandable, cancellable, and transparent about partial success and reuse.

---

## 42. Work package M7.40 — Integrate Milestone 7 actions with command history and revision conflict rules

### 42.1 Automatic results versus manual commands

Model installation, downloads, retrieval jobs, and analysis job execution are operational jobs, not ordinary reversible project-edit commands.

However, user-visible project-state choices such as:

- selecting active separation result;
- selecting a preset as project preference;
- attaching a newly retrieved source to an empty project when that operation is modeled as project mutation;
- selecting pipeline-result versions;

must follow the existing semantic command/revision rules where applicable.

### 42.2 No destructive result overwrite

Completing a new SCNet/RoFormer result adds a retained result.

It must not automatically delete or rewrite the active Demucs result.

If policy makes a newly completed result active, that state transition must be explicit and revision-safe; default to preserving current active selection unless the initiating action clearly requested activation.

### 42.3 Stale tab behavior

A browser tab with an old revision cannot silently change active model/result selection after another tab edited the project.

### 42.4 YouTube source attachment

Only allow source attachment into project states supported by the import model, initially an empty project as established in Milestone 1.

Do not replace an existing populated project's source through a YouTube action unless a later explicit source-replacement design owns that scope.

**Acceptance:** Milestone 7 operational jobs coexist with Milestone 6 transactional editing without weakening revision guarantees.

---

## 43. Work package M7.41 — Extend dependency/staleness rules for new separation results

### 43.1 Separation result identity

A result dependency includes the exact:

- source/reference asset;
- model manifest/checkpoint;
- adapter/runtime;
- preprocessing;
- inference profile.

### 43.2 Downstream dependencies

Existing downstream results keep their recorded upstream identities.

Examples:

- bass transcription depends on a specific bass stem asset/result;
- optional harmonic-remix chord analysis depends on specific selected stem assets;
- original-mix rhythm/chord analysis does **not** become stale merely because active separation changed;
- source-derived key analysis does **not** become stale because separation changed unless its declared input was a stem/remix.

### 43.3 Switching active separation

Selecting SCNet instead of Demucs:

- changes active playback/mixer source as requested;
- exposes old bass transcription as stale/not-matching-active-separation where appropriate;
- does not rewrite its input stem ID;
- does not automatically delete it;
- allows user to run/reuse a matching transcription for the new bass stem.

### 43.4 Six-stem downstream behavior

Only downstream modules that declare a dependency on the new guitar/piano/etc. stems are affected by changes to those stems.

### 43.5 Explainability

Stale UI can explain:

“Transcription was generated from Demucs Fine-tuned bass; active separation is SCNet XL IHF.”

rather than generic “out of date.”

**Acceptance:** model switching produces selective, explainable downstream staleness and never hidden retargeting.

---

## 44. Work package M7.42 — Add benchmark report artifacts and developer promotion workflow

### 44.1 Report artifact

Store benchmark output in a versioned developer/evaluation artifact containing:

- environment identity;
- corpus manifest;
- model/preset identities;
- per-track/per-stem metrics;
- downstream transcription metrics;
- runtime/memory metrics;
- listening results/notes;
- failures/OOM profiles;
- aggregate summaries with methodology.

### 44.2 No runtime dependency

The application can expose concise benchmark-derived metadata, but normal inference does not require raw benchmark files.

### 44.3 Promotion review

Create a repeatable developer command/workflow that:

1. Validates all required benchmark rows exist.
2. Applies noncontroversial hard gates such as license/qualification/completion.
3. Produces a comparison report.
4. Requires an explicit maintainer decision to change a named default/alias.
5. Records the decision and evidence reference.

Do not auto-promote a model from one scalar metric.

### 44.4 Regression on future model updates

Any new checkpoint/revision is a new model identity and must rerun the relevant benchmark/promotion gates before becoming a recommended preset.

**Acceptance:** named defaults are auditable engineering decisions rather than hidden application heuristics.

---

## 45. Work package M7.43 — Extend diagnostics, health, and operational commands

### 45.1 `basseparate doctor`

Add sections for:

- model registry validity;
- model store accessibility;
- partial/corrupt installs;
- MSST runtime availability;
- per-GPU model qualification summary;
- yt-dlp version;
- JS/EJS runtime state;
- retrieval capability;
- offline mode;
- pipeline scheduler readiness.

### 45.2 Developer commands

Add explicit commands/scripts as useful for:

- model registry validation;
- model artifact hash verification;
- model qualification;
- benchmark execution/report generation;
- YouTube retrieval diagnostics;
- extractor/runtime qualification;
- pipeline plan dump;
- cache-key explain/diff for a pipeline node.

### 45.3 Safe behavior

Diagnostics do not download models/media or update tools unless the command explicitly requests the network operation.

**Acceptance:** model/retrieval/pipeline failures can be diagnosed without enabling hidden network behavior or reading internal database tables manually.

---

## 46. Work package M7.44 — Unit and contract tests for registry, adapters, retrieval, and pipeline planning

### 46.1 Model-registry tests

Test:

- valid registry entries;
- duplicate model IDs;
- missing artifact hash;
- mismatched configuration relationship;
- unresolved license gate;
- invalid output roles;
- incompatible adapter range;
- migration/alias handling.

### 46.2 Download-state tests

Test:

- known content length;
- unknown content length;
- interrupted transfer;
- safe resume;
- unsafe resume restart;
- hash mismatch;
- cancellation;
- multi-artifact partial failure;
- atomic publication;
- existing installed version preservation.

### 46.3 Adapter tests

Use small deterministic tensors/audio to test:

- preprocessing metadata;
- role mapping;
- output validation;
- source-time alignment;
- parameter serialization;
- cache-key stability;
- OOM-profile identity;
- cancellation cleanup.

### 46.4 YouTube parser/state tests

Without network, test:

- URL validation;
- supported host recognition;
- playlist rejection policy;
- metadata schema parsing fixtures;
- progress-event parsing;
- structured error mapping;
- state transitions;
- provenance serialization.

### 46.5 Pipeline planner tests

Test graph construction for:

- empty project;
- source-ready project;
- existing cached separation;
- cached rhythm only;
- missing model;
- optional node skip;
- new active separation causing transcription mismatch;
- exact cache hits;
- stale but reusable historical result;
- partial failure/retry plan.

**Acceptance:** core correctness can be tested deterministically without downloading models or contacting YouTube.

---

## 47. Work package M7.45 — Integration tests for SCNet, RoFormer, and six-stem separation

### 47.1 Installed-model integration suite

When registered model bytes are available, test each model on a bounded fixture:

- installation verification;
- qualification;
- actual inference;
- role mapping;
- project-rate conversion;
- atomic publication;
- waveform generation;
- playback preparation;
- retained result selection.

### 47.2 Long-input tests

For each model/profile:

- memory remains bounded;
- output frame count matches;
- cancellation works;
- no unbounded staging growth;
- boundary listening/metric checks pass.

### 47.3 Model switching

Run Demucs and challenger on the same project:

- both result sets remain present;
- switching is explicit;
- mixer updates roles appropriately;
- downstream stale status is correct;
- switching back restores prior track state where designed.

### 47.4 Six-stem

Verify:

- all declared roles;
- six-stem mixer;
- loops/speed;
- selected-stem export;
- portable save/open;
- bounded browser memory.

**Acceptance:** every official Milestone 7 separation preset completes the normal project workflow, not only worker-level inference.

---

## 48. Work package M7.46 — Network-enabled YouTube integration tests

### 48.1 Controlled public fixture policy

Maintain a small set of legally usable public test URLs or a documented developer-supplied fixture strategy.

Do not make CI depend on arbitrary popular videos that can disappear unpredictably.

### 48.2 Metadata test

Verify:

- metadata lookup;
- title/duration parse;
- selected format;
- no remote thumbnail fetch from frontend;
- provenance storage.

### 48.3 Download/import test

Verify end-to-end:

- download;
- hash;
- local probe;
- import;
- canonical decode;
- waveform;
- playback;
- project save/reopen offline.

### 48.4 Failure tests

Where feasible, cover:

- nonexistent ID;
- unavailable video;
- access-restricted fixture/recorded error parsing;
- network disconnect;
- disk-space failure;
- cancellation;
- extractor incompatibility fixture;
- missing JS runtime;
- FFmpeg failure.

### 48.5 No automatic redownload

After successful import:

1. Disable network.
2. Reopen the project.
3. Play/analyze/export.
4. Verify no retrieval request occurs.

**Acceptance:** the actual retrieval toolchain works end-to-end while offline reopen remains independent of the source server.

---

## 49. Work package M7.47 — Whole-pipeline integration and cache-reuse tests

### 49.1 Cold run

On a prepared source with required models installed:

- preflight finds no cache;
- pipeline schedules expected nodes;
- progressive results appear;
- all successful outputs carry correct dependencies;
- final state is complete/warnings as appropriate.

### 49.2 Warm identical run

Run the same pipeline again:

- all eligible nodes are cache hits;
- no unnecessary inference jobs start;
- completion is substantially faster;
- result IDs are reused rather than duplicated where cache semantics specify reuse.

### 49.3 One-profile-change run

Change only separation preset:

- new separation runs;
- original-mix rhythm/harmony/key cache hits remain reusable;
- bass transcription reruns or uses a matching cached result for the new bass stem;
- unrelated manual edits remain intact.

### 49.4 Partial failure

Inject chord-worker failure:

- separation/rhythm persist;
- independent downstream work continues;
- pipeline reports warning/failure node;
- retry executes only missing/blocked nodes after fix.

### 49.5 Cancellation

Cancel during separation while another independent node completed:

- completed result remains;
- separation staging removed;
- dependent bass transcription does not start;
- retry reuses completed independent result.

### 49.6 Restart

Terminate application mid-pipeline, restart, and verify:

- interrupted state;
- completed nodes intact;
- explicit resume/replan;
- valid cache hits reused;
- unsupported internal inference is restarted from its owning module's safe boundary.

**Acceptance:** Analyze All demonstrates exact dependency-aware reuse and robust partial progress across failure/restart.

---

## 50. Work package M7.48 — Browser/E2E tests for Milestone 7 workflows

### 50.1 Model manager browser tests

Automate:

- open manager;
- inspect model status;
- simulated install progress;
- cancel;
- verification failure;
- successful installed state;
- device qualification display;
- removal without project loss.

### 50.2 Separation browser tests

Automate with fixtures/mocked heavy backend where necessary:

- preset selector;
- missing-model state;
- multiple result versions;
- six-stem layout;
- active result switching;
- stale downstream transcription indicator.

### 50.3 YouTube browser tests

Automate:

- invalid URL;
- metadata pending;
- confirmation;
- progress;
- cancellation;
- error state;
- transition to local import stages;
- ready project.

### 50.4 Analyze All browser tests

Automate:

- preflight;
- missing-model display;
- cache-hit display;
- running node status;
- progressive lane appearance;
- failure/retry;
- cancellation;
- page reload/reconnection.

### 50.5 Accessibility

Ensure:

- progress is conveyed with text, not color only;
- model/install actions have accessible names;
- focus behavior is correct for dialogs;
- keyboard navigation works;
- long model names/versions remain readable.

**Acceptance:** core Milestone 7 workflows are usable in the real frontend and survive reload/reconnection through durable backend state.

---

## 51. Work package M7.49 — Performance, storage, and stress tests

### 51.1 Model-manager scale

Test dozens of registry entries without expensive eager model probing on every UI render.

### 51.2 Download storage pressure

Test:

- insufficient free disk before download;
- disk fills during download;
- multi-gigabyte artifact staging;
- cancellation cleanup;
- model store on the configured local data volume.

### 51.3 Six-stem playback

Use long-form audio to verify:

- bounded PCM buffering;
- waveform-tile fetch limits;
- transport responsiveness;
- speed extremes;
- loop behavior;
- mixer UI responsiveness.

### 51.4 Pipeline stress

Run simultaneous qualified jobs within scheduler limits and measure:

- API latency;
- audio underruns;
- CPU load;
- RAM;
- VRAM per GPU;
- disk I/O;
- event update rate.

### 51.5 Long YouTube-derived source

Use a controlled long media fixture where permitted to test retrieval/import disk estimates and transition into local processing.

**Acceptance:** Milestone 7 does not regress bounded-memory playback or make ordinary editing unresponsive under intended two-GPU analysis load.

---

## 52. Work package M7.50 — Security and offline acceptance tests

### 52.1 Offline project workflow

With network blocked:

- launch;
- open local and YouTube-derived projects;
- playback;
- practise;
- select existing SCNet/RoFormer result versions;
- edit;
- undo/redo;
- export;
- save portable project;
- open portable project.

### 52.2 Offline model behavior

Verify:

- missing model shows unavailable installation state;
- no automatic request is attempted;
- cached results remain usable;
- offline model bundle import works.

### 52.3 Network trigger audit

Network observation confirms only explicit:

- model install/update;
- extractor update;
- YouTube metadata/download

may contact external hosts.

### 52.4 Injection/path tests

Test malicious-looking:

- URL strings;
- titles/filenames;
- model artifact filenames;
- archive paths;
- yt-dlp option-like strings.

They must never become shell commands or unmanaged paths.

### 52.5 Model loading

Verify only registered verified hashes are accepted by production adapter paths.

**Acceptance:** Milestone 7 retains the project's local/security guarantees despite adding explicit network-enabled workflows.

---

## 53. Work package M7.51 — Documentation and operational guidance

### 53.1 User documentation

Document:

- separation presets and what their names mean;
- how to install/remove/verify models;
- why model weights are not inside `.basseparate` projects;
- model-storage versus cache-storage distinction;
- model qualification/device selection;
- six-stem mode limitations;
- YouTube single-video import workflow;
- what YouTube cases are intentionally unsupported;
- extractor updates;
- offline behavior;
- Analyze All preflight, partial success, and retry;
- cache reuse and stale downstream results.

### 53.2 Developer documentation

Document:

- model registry schema;
- adding a new registered model;
- MSST runtime lock/build/install;
- SCNet adapter profile;
- RoFormer adapter profile;
- six-stem Demucs profile;
- benchmark corpus/report process;
- preset promotion workflow;
- download-job state machine;
- YouTube retrieval process/runtime;
- pipeline DAG/planner/scheduler;
- cache-key explanation;
- failure injection tests.

### 53.3 Troubleshooting

Cover:

- model hash mismatch;
- missing/failed GPU qualification;
- OOM;
- model download interruption;
- missing JS runtime/EJS support;
- extractor failure after a YouTube site change;
- unavailable/restricted video;
- pipeline partial failure;
- stale transcription after switching bass separator;
- disk-space pressure.

**Acceptance:** Milestone 7 can be maintained and operated without rediscovering model/download/pipeline invariants from source code.

---

## 54. Implementation order and milestone gates

Milestone 7 should proceed through explicit gates. Do not build Analyze All on unvalidated model/download identities, and do not publish quality aliases before benchmark evidence exists.

### Gate A — Regression baseline and schema foundations

Complete:

- M7.1 prerequisite/baseline checks;
- M7.2 generalized registry contracts;
- M7.3 exact challenger registry records;
- M7.35 persistence/migrations as needed.

Pass when:

- Milestone 0–6 regression suite is green;
- every challenger has an exact model/configuration/provenance identity;
- database/schema updates preserve old projects.

### Gate B — Challenger runtime and adapters

Complete:

- M7.4 isolated MSST runtime;
- M7.5 SCNet adapter;
- M7.6 BS-RoFormer adapter;
- M7.7 model/device qualification;
- M7.8 transformation/cache identity;
- M7.9 validation/publication.

Pass when:

- each challenger runs locally with network disabled;
- outputs publish through normal separation results;
- long-track resource policy is bounded;
- cancellation/cleanup works.

### Gate C — Six-stem integration

Complete:

- M7.10 six-stem model;
- M7.11 editor/mixer/export integration.

Pass when:

- six declared stem roles flow through waveform, playback, mixer, loops, exports, portable project, and downstream bass selection;
- no four-stem-only assumptions remain in shared code paths.

### Gate D — Benchmark and presets

Complete:

- M7.12 corpus/protocol;
- M7.13 metrics/resource measurements;
- M7.14 listening comparisons;
- M7.15 promotion/presets;
- M7.42 benchmark artifacts/workflow.

Pass when:

- full defined comparison set is measured;
- downstream bass transcription is included;
- named presets expose concrete identities/tradeoffs;
- no unsupported universal “best” claim is used.

### Gate E — Model manager and explicit downloads

Complete:

- M7.16 manager service;
- M7.17 durable downloads;
- M7.18 offline import/integrity;
- M7.19 storage integration;
- M7.37 frontend;
- diagnostics/tests.

Pass when:

- installs are explicit, cancellable, hash-verified, atomic;
- model storage is separate from cache eviction;
- removing weights does not break saved projects/results.

### Gate F — YouTube retrieval

Complete:

- M7.20 runtime;
- M7.21 retrieval records;
- M7.22 metadata;
- M7.23 download;
- M7.24 import handoff;
- M7.25 errors/recovery;
- M7.26 extractor update;
- M7.27 security;
- M7.38 UI.

Pass when:

- one public supported video can be retrieved into the ordinary import pipeline;
- cancellation/recovery works;
- project reopens offline;
- no playlist/cookie/access-control bypass behavior exists;
- extractor updating is independent of models.

### Gate G — Whole-pipeline orchestration

Complete:

- M7.28 graph;
- M7.29 preflight;
- M7.30 scheduling;
- M7.31 progressive publication;
- M7.32 cache reuse;
- M7.33 cancellation/recovery;
- M7.39 UI;
- M7.41 staleness.

Pass when:

- Analyze All is a DAG of normal module runs;
- exact cache hits are reused;
- partial failures preserve successful nodes;
- individual module actions still work;
- no hidden downloads/fallbacks occur.

### Gate H — Full regression, security, and operational acceptance

Complete:

- M7.34 APIs/contracts;
- M7.36 portable project;
- M7.40 revision integration;
- M7.43 diagnostics;
- M7.44–M7.52 tests/stress/security;
- M7.53 documentation.

Pass when:

- all prior milestone workflows remain regression-clean;
- offline/network trigger audit passes;
- five existing tracks can use retained/new separation models, analysis, practice, exports, save/open;
- no known data-loss, hidden-network, cache-identity, or model-provenance defect remains.

---

## 55. Detailed milestone completion checklist

### 55.1 Registry and provenance

- [ ] General model registry schema exists.
- [ ] Historical model IDs remain stable/migrated explicitly.
- [ ] SCNet exact checkpoint is registered.
- [ ] SCNet matching configuration is verified.
- [ ] SCNet checkpoint/config hashes are recorded.
- [ ] SCNet code license is recorded.
- [ ] SCNet checkpoint/weight terms are recorded separately.
- [ ] BS-RoFormer exact checkpoint is registered.
- [ ] BS-RoFormer matching configuration is verified.
- [ ] BS-RoFormer checkpoint/config hashes are recorded.
- [ ] BS-RoFormer code/weight licensing is recorded separately.
- [ ] No community mirror is silently substituted for an unavailable artifact.
- [ ] `htdemucs_6s` registry record is complete.
- [ ] Model output roles come from verified model configuration/labels.
- [ ] Required notices are retained.

### 55.2 MSST runtime/adapters

- [ ] MSST runtime is isolated from core backend.
- [ ] Runtime lock/fingerprint is recorded.
- [ ] SCNet adapter has stable ID/version.
- [ ] BS-RoFormer adapter has stable ID/version.
- [ ] Inference uses explicit local model paths.
- [ ] No inference-time remote fallback exists.
- [ ] Unregistered checkpoint paths are rejected in production flow.
- [ ] Checkpoint loading occurs in isolated worker.
- [ ] Cancellation is bounded.
- [ ] Worker exit releases GPU memory.
- [ ] OOM retries are finite and profile-versioned.
- [ ] CPU fallback is never silent.

### 55.3 Separation output correctness

- [ ] Project-rate output conversion is defined/tested.
- [ ] Frame count is validated.
- [ ] Timeline offset is validated.
- [ ] Samples are finite.
- [ ] Role list is validated.
- [ ] Assets are hashed.
- [ ] Result publication is atomic.
- [ ] Old result sets are immutable.
- [ ] Bass + Others derivation distinguishes residual `Others` from model `other`.
- [ ] Prepared-input reuse requires exact transform identity.
- [ ] Cache keys include checkpoint/config/profile identity.

### 55.4 Six-stem mode

- [ ] `htdemucs_6s` qualifies on at least one supported device.
- [ ] Six-stem result schema supports declared roles.
- [ ] Waveforms render for all stems.
- [ ] Mixer supports all stems.
- [ ] Solo/mute/gain/pan work.
- [ ] Time stretching stays synchronized.
- [ ] Loops work.
- [ ] Long playback remains bounded.
- [ ] Stem export is dynamic by role.
- [ ] Portable save/open retains six stems.
- [ ] Bass stem can feed transcription.
- [ ] Old transcription is never silently retargeted after active separation changes.

### 55.5 Benchmark and presets

- [ ] Evaluation corpus manifest is frozen/versioned.
- [ ] Development and final-evaluation material are separated.
- [ ] Demucs baseline is measured.
- [ ] Demucs fast preset is measured if published.
- [ ] SCNet is measured.
- [ ] BS-RoFormer is measured.
- [ ] Six-stem/guitar mode is measured on relevant fixtures.
- [ ] Reference separation metrics are recorded where ground truth exists.
- [ ] Bass leakage/attack/sustain diagnostics are recorded.
- [ ] Downstream bass-transcription metrics are recorded.
- [ ] Runtime is recorded.
- [ ] Peak VRAM/RAM is recorded.
- [ ] Long-track behavior is recorded.
- [ ] Listening results on five existing tracks are explicitly non-reference evidence.
- [ ] Promotion gate is applied.
- [ ] Conflicting evidence keeps multiple presets.
- [ ] Named presets expose exact model identity.
- [ ] Historical runs do not depend on moving alias targets.

### 55.6 Model manager

- [ ] One catalog covers registered installable models.
- [ ] Installation state is explicit.
- [ ] Installed-but-unqualified is distinct from installed-qualified.
- [ ] Device qualification state is visible.
- [ ] License/provenance summary is visible.
- [ ] Install action is explicit.
- [ ] Download bytes/progress are visible.
- [ ] Verification phase is visible.
- [ ] Cancellation works.
- [ ] Retry works.
- [ ] Offline bundle import works.
- [ ] Integrity verification works.
- [ ] Removal does not delete analysis results/history.
- [ ] Removal is blocked/deferred while model is in use.
- [ ] Model storage is accounted separately from analysis cache.
- [ ] Ordinary cache cleanup never evicts model files.

### 55.7 Model downloads

- [ ] Download jobs are durable.
- [ ] Staging ownership is recorded.
- [ ] Known byte totals produce real progress.
- [ ] Unknown byte totals remain indeterminate.
- [ ] Per-artifact progress is available.
- [ ] Safe resume is implemented only with proven remote identity.
- [ ] Unsafe partials restart instead of appending.
- [ ] Hash mismatch prevents publication.
- [ ] Multi-artifact install publishes atomically.
- [ ] Existing installed version survives failed update/install.
- [ ] No model is downloaded on project open.
- [ ] No model is downloaded on inference start.

### 55.8 YouTube runtime

- [ ] yt-dlp version is explicit.
- [ ] FFmpeg is qualified.
- [ ] supported JS runtime is qualified.
- [ ] EJS support state is diagnosable.
- [ ] retrieval tools are separate from ordinary startup.
- [ ] tool update is explicit.
- [ ] tool update is separate from model updates.
- [ ] previous known-working tool can remain available/rollback strategy is documented where feasible.

### 55.9 YouTube metadata/retrieval

- [ ] One YouTube URL is accepted.
- [ ] Unsupported/non-YouTube URL is rejected.
- [ ] Playlist scope is rejected/not offered.
- [ ] Metadata is retrieved before download.
- [ ] Title/duration are shown.
- [ ] No remote thumbnail is loaded.
- [ ] No remote player is embedded.
- [ ] Audio format strategy is visible.
- [ ] Download is explicit.
- [ ] Retrieval progress is visible.
- [ ] Cancellation works.
- [ ] Downloaded bytes are hashed.
- [ ] Local ffprobe validation occurs.
- [ ] Selected format/codec is recorded.
- [ ] Downloaded media enters the normal import pipeline.
- [ ] Original source URL/retrieval date are provenance.
- [ ] Project reopens without network.
- [ ] Project open never re-fetches source.
- [ ] No automatic browser-cookie extraction exists.
- [ ] No access-control/DRM bypass exists.

### 55.10 YouTube failure/recovery

- [ ] Invalid URL has clear error.
- [ ] unavailable video has clear error.
- [ ] access-restricted/auth-required case has clear error.
- [ ] extractor failure is distinct from access restriction.
- [ ] missing JS runtime has clear error.
- [ ] network timeout/failure has clear error.
- [ ] no-audio-format error exists.
- [ ] disk-full error leaves project valid.
- [ ] cancellation leaves no published partial source.
- [ ] crash marks retrieval interrupted.
- [ ] safe complete local download can be recovered/imported.
- [ ] network retrieval never auto-restarts after crash.

### 55.11 Analyze All graph

- [ ] Pipeline run record exists.
- [ ] Node record exists.
- [ ] Graph dependencies are explicit.
- [ ] Default graph checks source/decode/peaks as needed.
- [ ] Selected separation runs.
- [ ] original-mix rhythm runs.
- [ ] tempo/meter derives from rhythm.
- [ ] harmony/key runs according to existing profile.
- [ ] bass transcription waits for selected bass stem/tuning context.
- [ ] optional comparison branches are opt-in.
- [ ] individual module actions remain available.

### 55.12 Analyze All preflight/scheduling

- [ ] Required models are resolved.
- [ ] Missing installations are listed.
- [ ] No hidden installation occurs.
- [ ] Exact cache hits are listed.
- [ ] blocked/skipped nodes are explained.
- [ ] device assignment candidates are visible.
- [ ] disk/resource warnings are shown.
- [ ] GPUs remain separate memory pools.
- [ ] one heavy job/GPU policy is enforced initially.
- [ ] CPU concurrency preserves playback headroom.
- [ ] no silent GPU-to-CPU fallback occurs.

### 55.13 Pipeline publication/failure

- [ ] Results publish progressively.
- [ ] Completed node survives later node failure.
- [ ] dependent node blocks after dependency failure.
- [ ] independent node may continue according to policy.
- [ ] pipeline can end completed-with-warnings.
- [ ] skipped reasons are explicit.
- [ ] old results are never overwritten.
- [ ] cancellation stops new scheduling.
- [ ] completed outputs remain after cancellation.
- [ ] restart marks pipeline interrupted.
- [ ] resume/replan reuses valid cache hits.

### 55.14 Pipeline cache reuse

- [ ] Individual Demucs result is reused by Analyze All.
- [ ] Individual rhythm result is reused by Analyze All.
- [ ] Analyze All chord result is reused by individual action.
- [ ] SCNet exact rerun is cache hit.
- [ ] RoFormer selection is a distinct cache identity.
- [ ] Bass transcription cache is stem-specific.
- [ ] New separation does not invalidate original-mix rhythm/harmony cache.
- [ ] Prepared analysis input is reused only when transform identities match.
- [ ] Partial pipeline retry reuses completed upstream results.

### 55.15 Persistence/portable project

- [ ] New DB migrations are transactional.
- [ ] Old project migration fixtures pass.
- [ ] Model weights remain excluded from `.basseparate`.
- [ ] YouTube retrieval runtime remains excluded.
- [ ] Downloaded source media is included according to source policy.
- [ ] retrieval provenance is preserved.
- [ ] exact separation-model provenance is preserved.
- [ ] six-stem results reopen offline.
- [ ] SCNet/RoFormer results reopen offline.
- [ ] undo/redo/history remains valid.

### 55.16 Dependency/staleness

- [ ] Downstream result records exact separation stem dependency.
- [ ] Active model switching does not rewrite dependency IDs.
- [ ] transcription mismatch becomes explainable stale state.
- [ ] original-mix rhythm is unaffected by separation switch.
- [ ] original-mix harmony/key is unaffected unless explicit dependency exists.
- [ ] optional harmonic remix follows exact stem dependencies.
- [ ] stale historical results remain selectable/inspectable.

### 55.17 Locality/security

- [ ] ordinary startup emits no external traffic.
- [ ] project open emits no external traffic.
- [ ] inference emits no external traffic.
- [ ] only explicit model install/update can fetch model artifacts.
- [ ] only explicit extractor update can fetch retrieval-tool update.
- [ ] only explicit YouTube retrieval contacts YouTube/extractor endpoints.
- [ ] argument arrays are used for processes.
- [ ] no browser-supplied shell options are accepted.
- [ ] titles/filenames cannot escape staging paths.
- [ ] unregistered checkpoints are not loaded by production paths.

### 55.18 Testing/documentation

- [ ] unit/contract tests pass.
- [ ] SCNet integration tests pass on a qualified device.
- [ ] RoFormer integration tests pass on a qualified device.
- [ ] six-stem integration tests pass.
- [ ] benchmark report is complete.
- [ ] model manager browser tests pass.
- [ ] YouTube controlled-network test passes.
- [ ] YouTube offline-reopen test passes.
- [ ] Analyze All cold/warm/partial-failure/restart tests pass.
- [ ] storage/performance stress tests pass.
- [ ] offline/network audit passes.
- [ ] user documentation is updated.
- [ ] developer/troubleshooting documentation is updated.

---

## 56. Direct traceability to Section 13 Milestone 7

| Main-plan Milestone 7 item | Detailed coverage |
|---|---|
| 1. Integrate SCNet and RoFormer adapters | M7.2–M7.9, M7.44–M7.47 |
| 2. Verify checkpoint/license records | M7.2–M7.3, M7.18, M7.42, M7.55.1 |
| 3. Benchmark the defined comparison set | M7.1, M7.12–M7.14, M7.42, M7.55.5 |
| 4. Publish named quality/speed presets | M7.15, M7.37, M7.42 |
| 5. Add six-stem guitar mode | M7.10–M7.11, M7.47, M7.49 |
| 6. Consolidate project-wide model manager for bundled and separately installed models | M7.16, M7.18–M7.19, M7.37, M7.43 |
| 7. Generalize explicit download progress for non-bundled models/retrievals | M7.17, M7.37, M7.55.7 |
| 8. Add yt-dlp/EJS integration | M7.20, M7.22–M7.24, M7.46 |
| 9. Add YouTube import errors and cancellation | M7.21, M7.25, M7.38, M7.46 |
| 10. Add independent extractor updating | M7.26, M7.43, M7.53 |
| 11. Add whole-pipeline execution | M7.28–M7.33, M7.39, M7.47 |
| 12. Verify cache reuse across module runs | M7.8, M7.32, M7.47, M7.55.14 |

The main-plan acceptance condition—**local high-quality model choices and YouTube import work through the same project workflow**—is satisfied only when Gates A–H pass. A worker-level model demo, standalone yt-dlp script, or one-shot Analyze All function is not sufficient.

---

## 57. Handoff to Milestone 8 — Browser validation and release

Deliver to Milestone 8:

1. A regression-clean application containing all Milestone 0–7 project features.
2. A unified model registry covering every shipped/available model family.
3. Exact hashes, code licenses, checkpoint/weight terms, required notices, and installation status semantics.
4. A model manager that represents the bundled Demucs baseline plus separately installed models, supports explicit online installation/offline registered bundle import for non-bundled models, and provides verification/qualification with removal only where distribution state permits it.
5. Separate model-storage and analysis-cache accounting.
6. Qualified SCNet and BS-RoFormer adapters on every locally supported device profile.
7. A qualified six-stem Demucs guitar-capable preset.
8. Stable named separation presets with benchmark-backed purpose/limitations and concrete underlying model identity.
9. A versioned benchmark report for the defined separation comparison set.
10. Downstream bass-transcription evaluation across separator choices.
11. Six-stem waveform/mixer/playback/loop/export support with bounded memory.
12. A durable YouTube single-video retrieval workflow using the pinned/managed yt-dlp + JS/EJS + FFmpeg toolchain.
13. YouTube provenance and local immutable source integration.
14. Explicit YouTube cancellation/recovery/error states.
15. Independent extractor/runtime update mechanism.
16. Verified offline reopen of YouTube-derived projects.
17. An Analyze All DAG using the same module contracts, durable jobs, result identities, device scheduler, and cache as individual runs.
18. Pipeline preflight showing missing models, cache hits, devices, skipped nodes, and resource warnings.
19. Progressive publication and partial-failure retention.
20. Verified exact cache reuse across individual/pipeline runs.
21. Selective downstream staleness after changing separator/model.
22. Portable projects that remain independent of model/runtime/source-server availability.
23. API/contract/database migrations and complete E2E tests for all new workflows.
24. Security/network-observation tests proving no hidden network access.
25. Updated user, developer, license, model-location, cache-location, and troubleshooting documentation.

Milestone 8 must treat the Milestone 7 model/download/pipeline implementations as functionally complete and concentrate on cross-browser validation, final Linux packaging/launcher integration, Safari validation on actual macOS hardware, long-project release testing, offline installation instructions, backup/recovery documentation, and versioned release/license inventory.

Specific Milestone 8 concerns inherited from this milestone:

- Chromium/Firefox/WebKit/Safari UI must render six-stem and model-manager states consistently.
- Browser refresh/reconnect must recover model download, YouTube retrieval, and Analyze All state from durable backend records.
- User-gesture audio rules must still work after six-stem project loading.
- long six-stem projects must remain bounded in browser memory.
- release packaging must include or clearly provision the managed yt-dlp/JS/EJS strategy without enabling automatic hidden updates;
- offline model-import instructions must cover the generalized registry/bundle format;
- release license inventory must distinguish code/runtime/checkpoint licenses;
- packaged model/extractor locations must match the storage UI/documentation;
- a released project open must never contact model or YouTube servers automatically.

---

## 58. Milestone 7 final acceptance statement

Milestone 7 is complete when basseparate can treat multiple high-quality separation engines, six-stem guitar-capable separation, explicit model installation, YouTube retrieval, and end-to-end analysis orchestration as ordinary parts of the same durable local project system: SCNet XL IHF and BS-RoFormer run through isolated verified adapters and publish normal immutable separation result sets; checkpoint/configuration provenance and licensing are recorded exactly; the defined Demucs/SCNet/RoFormer comparison set is measured on a frozen evaluation corpus with bass-specific, downstream transcription, runtime, memory, and listening evidence; named quality/speed/six-stem presets expose their concrete model identities and do not claim a universal winner where evidence conflicts; six-stem results flow through existing waveform, mixer, transport, loops, export, cache, and portable-project paths; one model manager represents bundled Demucs plus separately installed models, provides explicit cancellable hash-verified installations for non-bundled artifacts, and keeps separately installed model storage distinct from rebuildable cache; YouTube retrieval uses an explicit local yt-dlp + JS/EJS + FFmpeg toolchain, accepts one supported video URL, retrieves metadata before download, preserves the selected audio stream without unnecessary lossy re-encoding, handles cancellation/errors/recovery, and feeds completed bytes into the same immutable import/decode pipeline as local files; extractor updating is explicit and independent of model updates; Analyze All is a transparent durable DAG over existing modules, reports missing installations and cache hits before execution, schedules work across independent GPU/CPU resources without merging VRAM or sacrificing playback responsiveness, publishes results progressively, preserves successful nodes after failure/cancellation, and reuses exact per-module cache identities on retry; model switching never rewrites older results or silently retargets downstream transcription; all projects, including YouTube-derived and SCNet/RoFormer/six-stem projects, reopen offline without model execution or source re-fetch; and every Milestone 0–6 editing, history, staleness, recovery, export, cache, migration, and security guarantee remains regression-clean.
