# basseparate: detailed implementation plan

## 1\. Summary and agreed decisions

Build **basseparate** as a local music-analysis and practice application with a browser interface, GPU-accelerated analysis, editable musical timelines, and portable project files.

The complete project includes all 35 requested features. Delivery will proceed through usable milestones rather than waiting until everything is finished.

### Confirmed preferences

- Target your **Nobara Linux PC first**.
- Support Chrome/Chromium and Firefox on Linux.
- Design for Safari compatibility and test Safari separately on macOS.
- Prioritize analysis quality, particularly bass separation and transcription.
- Provide faster presets as alternatives.
- Bundle the pinned Demucs `htdemucs_ft` baseline with the personal release; keep its verified artifacts in an ignored development-workspace model directory and copy them into the release bundle. Other models and requested YouTube audio use explicit network-enabled retrieval only when requested.
- Keep audio processing, analysis, project storage, and playback local.
- Support 4-, 5-, and 6-string bass, low B, drop tunings, synth bass, slides, and tuning offsets.
- Save self-contained `.basseparate` projects by default.

### Hardware discovered

| Component | Observed configuration | Planning consequence |
|---|---|---|
| OS | Nobara Linux 44, x86-64 | Linux installation and packaging first |
| CPU | Intel Core i5-12600K, 10 cores / 16 threads | Suitable for decoding, feature extraction, and fallback inference |
| RAM | Approximately 32 GB | Stream long recordings; avoid loading every stem into RAM |
| GPU 1 | NVIDIA RTX 4080 | Preferred heavy separation device |
| GPU 2 | NVIDIA RTX 5060 Ti | Secondary analysis device |
| VRAM | Saved inventory reports 16 GB per GPU | Treat as two separate memory pools |
| Storage | Approximately 399 GB currently free on workspace volume | Enough for initial models and projects, with configurable cache limits |

The current session’s `nvidia-smi` call failed. PCI inspection found both GPUs, and the saved inventory reports successful CUDA operation previously. GPU access therefore needs verification during implementation; it is not yet a measured working inference environment.

Five existing WAV files are available as an initial local listening corpus. They contain stereo audio at 44.1 kHz or 48 kHz and range from approximately 69 to 313 seconds. They have not been analyzed or used to measure model quality.

### What “best available” means

Choose models using four requirements:

1. Downloadable, usable implementation and weights.
2. Suitable licensing for the intended private use.
3. Successful execution within your hardware limits.
4. Measured usefulness on bass, rhythm, and harmony—not merely a model’s headline benchmark.

No single model reliably provides the best result for every instrument and musical style. The architecture must permit model replacement and comparison without rewriting the editor.

This plan specifies initial defaults and a repeatable process for promoting better models. Model speed and accuracy figures must be measured during implementation; they are not promised here.

***

## 2\. Languages, application structure, and dependencies

### 2\.1 Main technology choices

| Area | Choice | Purpose |
|---|---|---|
| Analysis/backend | Python 3.11 initially | Broad compatibility with audio research implementations |
| Local API | FastAPI, Pydantic, Uvicorn | Typed local service and generated API documentation |
| Neural inference | PyTorch with compatible CUDA wheels | Run separation, beat tracking, and pitch models |
| Frontend | TypeScript, React, Vite | Browser application with typed editing logic |
| Frontend state | Zustand; explicit command/history layer | Selection, transport, editor state, undo/redo |
| Waveforms | Custom tiled Canvas 2D renderer | Shared timeline, multiple resolutions, controlled memory use |
| Playback | Web Audio, AudioWorklet, WebAssembly | Synchronized stems, variable speed, metronome |
| Time stretching | Signalsmith Stretch | Pitch-preserving playback speed changes |
| Media handling | FFmpeg and ffprobe executables | Decode containers, extract audio, export stems |
| Numerical processing | NumPy, SciPy, librosa | Resampling support, features, pitch and rhythm utilities |
| Working database | SQLite | Project metadata, edit history, job persistence |
| Portable project | ZIP64 container with manifest and assets | Self-contained `.basseparate` file |
| Python dependency management | uv with committed locks | Reproducible installations |
| Frontend dependency management | pnpm with committed lockfile | Reproducible frontend builds |
| Tests | pytest, Vitest, Playwright | Backend, editor, and browser validation |

FastAPI and React are established open-source foundations for these roles. Their upstream repositories identify their licenses. [FastAPI](<https://github.com/fastapi/fastapi>), [React](<https://github.com/react/react>)

Use Python for research-model integration and TypeScript for browser behavior. Use existing C++ compiled to WebAssembly for the time stretcher. Do not introduce MATLAB, a separate Rust service, or a desktop webview wrapper into the initial implementation.

### 2\.2 Process structure

Run four kinds of local process:

1. **Launcher**
   - Starts the backend.
   - Opens the browser.
   - Handles shutdown and diagnostics.
2. **Backend service**
   - Owns projects, revisions, jobs, and assets.
   - Serves the frontend.
   - Coordinates worker processes.
3. **Analysis workers**
   - Execute independent analysis modules.
   - Load models on assigned GPUs.
   - Report progress and write immutable result artifacts.
4. **Browser**
   - Renders the editor.
   - Plays locally streamed PCM.
   - Sends edits to the backend.
   - Does not execute the large analysis models.

Serve frontend and API from the same loopback origin.

### 2\.3 Repository organization

Create logical packages for:

- Backend API and project services.
- Musical timeline and edit-domain logic.
- Analysis plugin interfaces and implementations.
- Worker supervision and GPU scheduling.
- Browser editor.
- Browser audio engine and WebAssembly build.
- Shared schemas and generated client types.
- Test fixtures and evaluation tools.
- Packaging, licenses, and documentation.

Keep model weights, source audio, generated stems, working databases, and caches outside version control. The bundled Demucs baseline is stored in an ignored development-workspace model directory and copied into release artifacts by the packaging process; bundling it does not make the weight files source-controlled.

### 2\.4 Initial setup steps

1. Preserve the existing WAV files and inventory.
2. Inspect repository instructions before creating code.
3. Initialize project metadata and dependency locks.
4. Pin Python 3.11 for the initial application environment.
5. Pin a supported Node LTS release for frontend builds.
6. Add formatting, static checks, and type checking.
7. Create a health endpoint and minimal browser shell.
8. Generate TypeScript API types from backend schemas.
9. Establish separate runtime environments for plugins whose dependencies conflict.
10. Add a reproducible WebAssembly build for the audio engine.
11. Record exact dependency versions in build metadata.
12. Verify startup without loading a model.

Do not require every research package to coexist in one Python environment.

***

## 3\. Model, algorithm, plugin, and license selection

### 3\.1 Source separation

#### Initial supported models

| Model or implementation | Planned role | Important limit |
|---|---|---|
| Demucs `htdemucs_ft` | Initial quality baseline for vocals, drums, bass, other | Established baseline; must still be compared against newer models |
| Demucs `htdemucs` | Faster four-stem preset | Quality/speed tradeoff |
| Demucs `htdemucs_6s` | Initial guitar-capable six-stem preset | Guitar/piano quality is uneven |
| SCNet XL IHF | Quality challenger for four-stem separation | Must benchmark VRAM and bass quality |
| BS-RoFormer multistem | Quality challenger | Architecture name alone does not identify checkpoint quality |
| Mel-Band RoFormer | Optional specialist separation | Many available checkpoints target vocals rather than bass |

The maintained Demucs repository documents four-stem and experimental six-stem operation, including limitations of the additional instrument outputs. Use the maintained upstream, with a pinned release. [Demucs](<https://github.com/adefossez/demucs>)

The MSST project provides model implementations and a checkpoint catalog including SCNet XL IHF and multistem BS-RoFormer. Its reported results justify evaluating both; they do not establish a universal winner for your recordings. [MSST](<https://github.com/ZFTurbo/Music-Source-Separation-Training>), [checkpoint catalog](<https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/docs/pretrained_models.md>)

#### Concrete comparison set

Start with:

- `htdemucs_ft`.
- `htdemucs_6s`.
- SCNet XL IHF: `model_scnet_ep_36_sdr_10.0891.ckpt`, with its matching published configuration.
- BS-RoFormer: `model_bs_roformer_ep_17_sdr_9.6568.ckpt`, with its matching published configuration.

For every checkpoint, verify availability, provenance, license terms, configuration pairing, and SHA-256 before inclusion.

Do not silently replace a missing file with an identically named community mirror.

#### Integration choice

- Integrate Demucs through a dedicated adapter.
- Integrate SCNet/RoFormer through an isolated MSST adapter.
- Keep `python-audio-separator` as an optional adapter for additional model families.
- Expose only local inference paths.

`python-audio-separator` offers a convenient local API, but also contains remote functionality. Basseparate must not expose or invoke those remote paths. [Audio Separator](<https://github.com/nomadkaraoke/python-audio-separator>)

#### Additional research candidates

- BS-RoFormer-SW for six-stem separation.
- MVSep Mega for broader instrument discovery.
- SAM Audio for prompted separation.

These are optional later adapters, not initial dependencies. Their checkpoint licensing, resource use, and musical accuracy require independent checks. A large stem vocabulary does not imply better bass extraction. SAM Audio uses a custom license and gated weights. [BS-RoFormer inference toolkit](<https://github.com/openmirlab/bs-roformer-infer>), [SAM Audio](<https://github.com/facebookresearch/sam-audio>)

### 3\.2 Beats and downbeats

Use **Beat This\! `final0`** as the initial model.

- Extract beat and downbeat activation curves.
- Retain activations before timestamp postprocessing.
- Derive tempo and meter in separate modules.
- Offer `small0` as a faster option.
- Evaluate the other published final checkpoints as optional alternatives.
- Do not assume an ensemble will improve results without testing.

The upstream provides framewise outputs and explicitly licenses both code and published weights under MIT. [Beat This\!](<https://github.com/CPJKU/beat_this>)

Keep madmom as an optional comparison adapter, not a mandatory dependency. Its code and model/data licensing differ, and dependency compatibility needs separate handling. [madmom](<https://github.com/CPJKU/madmom>)

### 3\.3 Chord recognition

Implement three adapters:

1. **BTC large-vocabulary model** as the initial neural baseline.
2. **ChordMini BTC continual-learning checkpoint** as the primary newer challenger.
3. **Chordino** as a deterministic, CPU-friendly comparison and fallback.

BTC exposes small and larger vocabulary operation. ChordMini publishes named checkpoints and inference instructions, making it more concrete to integrate than a paper without verified deployable weights. [BTC](<https://github.com/jayg996/BTC-ISMIR19>), [ChordMini](<https://github.com/ptnghia-j/ChordMini>)

Chordino uses NNLS chroma and chord templates with temporal smoothing. Its own documentation does not claim current state-of-the-art performance. [Chordino](<https://isophonics.net/nnls-chroma>), [source and license](<https://github.com/c4dm/nnls-chroma>)

Treat **ChordFormer** as research to monitor. The paper reports promising large-vocabulary recognition, but this research pass did not establish an authoritative, ready-to-integrate checkpoint and inference package. Do not substitute a different repository merely because it shares the name. [ChordFormer paper](<https://arxiv.org/abs/2502.11840>)

#### Detailed chord policy

- The editor accepts rich chord names regardless of detector vocabulary.
- Each detector declares the labels it can actually recognize.
- Simple mode projects supported chords into simpler displayed labels.
- Detailed mode preserves supported extensions and inversion information.
- Unsupported extensions remain unknown or manual.
- Do not manufacture `Am9` from an `Am` prediction.
- A bass note can support an inversion hypothesis, but a passing bass note must not automatically become the slash bass of a chord.

### 3\.4 Bass transcription

Use a hybrid initial implementation:

- **torchcrepe full** for neural monophonic pitch evidence.
- **librosa pYIN** for an independent low-frequency estimate.
- Spectral-flux and amplitude-envelope evidence for note attacks.
- A bass-specific temporal decoder for note segmentation and octave-error control.

torchcrepe exposes periodicity and documents that silence can produce misleadingly strong pitch predictions, so explicit silence handling is required. [torchcrepe](<https://github.com/maxrmorrison/torchcrepe>)

pYIN provides a useful alternative pitch estimator and voiced-probability output. [librosa pitch implementation](<https://github.com/librosa/librosa/blob/main/librosa/core/pitch.py>)

#### Low-bass handling

Ordinary CREPE’s lower pitch range does not directly cover all requested bass notes. Implement and evaluate:

1. pYIN over approximately 25–800 Hz.
2. Ordinary torchcrepe inference where its range is suitable.
3. An additional analysis-only octave-up, double-speed version:
   - Frequencies double.
   - Duration halves.
   - Map predicted frequencies back by dividing by two.
   - Map timestamps back by multiplying by two.
4. Combine candidates with octave-consistency and voicing checks.

This double-speed path is a proposed engineering adaptation, not a published guarantee of improved bass accuracy.

Include **Basic Pitch** as an optional comparison for note events. Do not use it as the sole low-bass solution: its published frequency bounds do not cover the entire requested range. [Basic Pitch](<https://github.com/spotify/basic-pitch>), [frequency constants](<https://github.com/spotify/basic-pitch/blob/main/basic_pitch/constants.py>)

### 3\.5 Key and tuning

Use:

- Essentia `KeyExtractor` as the initial key-analysis adapter.
- An independent chroma/profile correlation implementation for comparison.
- Tuning estimation before pitch-class aggregation.
- Separate global-key and local-key-region results.

Essentia provides configurable key extraction from tonal features. Its library and model licensing must be handled separately. No Essentia neural model is required for this initial key module. [KeyExtractor](<https://essentia.upf.edu/reference/std_KeyExtractor.html>), [Essentia licensing](<https://essentia.upf.edu/licensing_information.html>)

Key signature is not uniquely recoverable from audio. Store tonic/mode evidence separately from the user’s preferred spelling and displayed key signature.

### 3\.6 Playback and other useful libraries

- **Signalsmith Stretch:** default pitch-preserving speed engine; MIT; official Web Audio/WebAssembly integration exists. [Signalsmith](<https://signalsmith-audio.com/code/stretch/>), [Web Audio integration](<https://github.com/Signalsmith-Audio/signalsmith-stretch/blob/main/web/release/README.md>)
- **Rubber Band:** optional offline stretch comparison; GPL or commercial licensing. [Rubber Band](<https://breakfastquay.com/rubberband/>)
- **Tonal:** frontend chord parsing, note spelling, and music-theory utilities. It does not analyze audio. [Tonal](<https://github.com/tonaljs/tonal>)
- **Vamp/Sonic Annotator:** optional native plugin hosting for Chordino and comparable analysis plugins.
- **WaveSurfer:** useful reference/prototyping option, but not the production transport owner. Its documentation highlights memory issues with large decoded files and recommends precomputed peaks. [WaveSurfer](<https://wavesurfer.xyz/>)

### 3\.7 License manifest

Maintain a machine-readable license record for every dependency and model containing:

1. Component name.
2. Exact version or commit.
3. Official source URL.
4. Code license.
5. Weight license, separately.
6. Download URL.
7. Checkpoint hash.
8. Required notices.
9. Restrictions or unresolved questions.
10. Whether it is bundled or separately installed.

Working license summary:

| Component | Published license position |
|---|---|
| Demucs, MSST, Audio Separator | MIT code; verify selected weight terms |
| Beat This\! | MIT code and published weights |
| BTC | MIT code; retain checkpoint provenance |
| ChordMini | MIT source/configuration/documentation; inspect checkpoint terms separately |
| torchcrepe | MIT code; record bundled weight provenance |
| Basic Pitch | Apache-2.0 project |
| librosa | ISC |
| Chordino | GPL |
| Essentia | AGPL-based library licensing |
| Signalsmith Stretch | MIT |
| Rubber Band | GPL or commercial |
| yt-dlp | Unlicense source; packaged dependencies can add obligations |
| FFmpeg | LGPL/GPL depending on build configuration |

Private noncommercial use does not make every downloadable checkpoint automatically permitted. Do not infer a weight license from a wrapper’s license or from the training dataset’s license.

FFmpeg licensing depends on how it is built; record the actual installed build configuration. [FFmpeg licensing](<https://ffmpeg.org/legal.html>)

***

## 4\. Core architecture and public interfaces

### 4\.1 Data flow

```
┌─────────────────────────────────────────┐
│ Local media or requested YouTube audio  │
│                                         ├─────┐
└─────────────────────────────────────────┘     │
                                                │
                                                │
┌─────────────────────────────────────────┐     │
│ Probe, decode, hash                     │     │
│                                         ├◄────┘
│                                         ├───────┐
└─────────────────────────────────────────┘       │
                                                  │
                                                  │
┌─────────────────────────────────────────┐       │
│ Immutable source audio                  │       │
│                                         ├◄──────┘
│                                         ├─────────┐
│                                         ├─────────╪─┐
│                                         ├─────────╪─╪─┐
│                                         ├─────────╪─╪─╪─┐
└─────────────────────────────────────────┘         │ │ │ │
                                                    │ │ │ │
                                                    │ │ │ │
┌─────────────────────────────────────────┐         │ │ │ │
│ Waveform pyramid and PCM streaming      │         │ │ │ │
│                                         ├◄────────┘ │ │ │
│                                         ├───────────╪─╪─╪─────────────────┐
└─────────────────────────────────────────┘           │ │ │                 │
                                                      │ │ │                 │
                                                      │ │ │                 │
┌─────────────────────────────────────────┐           │ │ │                 │
│ Separation module                       │           │ │ │                 │
│                                         ├◄──────────┘ │ │                 │
│                                         ├─────────────╪─╪─┐               │
│                                         ├─────────────╪─╪─╪───┐           │
│                                         ├─────────────╪─╪─╪───╪───────────╪─┐
└─────────────────────────────────────────┘             │ │ │   │           │ │
                                                        │ │ │   │           │ │
                                                        │ │ │   │           │ │
┌─────────────────────────────────────────┐             │ │ │   │           │ │
│ Beat and downbeat module                │             │ │ │   │           │ │
│                                         ├◄────────────┘ │ │   │           │ │
│                                         ├───────────────╪─╪─┐ │           │ │
└─────────────────────────────────────────┘               │ │ │ │           │ │
                                                          │ │ │ │           │ │
                                                          │ │ │ │           │ │
┌─────────────────────────────────────────┐               │ │ │ │           │ │
│ Chord and key modules                   │               │ │ │ │           │ │
│                                         ├◄──────────────┘ │ │ │           │ │
│                                         ├◄────────────────╪─╪─┘           │ │
│                                         ├─────────────────╪─╪───┐         │ │
└─────────────────────────────────────────┘                 │ │   │         │ │
                                                            │ │   │         │ │
                                                            │ │   │         │ │
┌─────────────────────────────────────────┐                 │ │   │         │ │
│ Bass transcription                      │                 │ │   │         │ │
│                                         ├◄────────────────┘ │   │         │ │
│                                         ├───────────────────╪───╪─┐       │ │
└─────────────────────────────────────────┘                   │   │ │       │ │
                                                              │   │ │       │ │
                                                              │   │ │       │ │
┌─────────────────────────────────────────┐                   │   │ │       │ │
│ Tempo and meter modules                 │                   │   │ │       │ │
│                                         ├◄──────────────────┘   │ │       │ │
│                                         ├───────────────────────╪─╪─┐     │ │
└─────────────────────────────────────────┘                       │ │ │     │ │
                                                                  │ │ │     │ │
                                                                  │ │ │     │ │
┌─────────────────────────────────────────┐                       │ │ │     │ │
│ Immutable automatic result versions     │                       │ │ │     │ │
│                                         ├◄──────────────────────┘ │ │     │ │
│                                         ├◄────────────────────────┘ │     │ │
│                                         ├◄──────────────────────────┘     │ │
│                                         ├─────────────────────────────┐   │ │
└─────────────────────────────────────────┘                             │   │ │
                                                                        │   │ │
                                                                        │   │ │
┌─────────────────────────────────────────┐                             │   │ │
│ Editable project revision               │                             │   │ │
│                                         ├◄────────────────────────────┘   │ │
│                                         ├───────────────────────────────┐ │ │
│                                         ├───────────────────────────────╪─╪─╪─┐
└─────────────────────────────────────────┘                               │ │ │ │
                                                                          │ │ │ │
                                                                          │ │ │ │
┌─────────────────────────────────────────┐                               │ │ │ │
│ Browser timelines and practice playback │                               │ │ │ │
│                                         ├◄──────────────────────────────┘ │ │ │
│                                         ├◄────────────────────────────────┘ │ │
│                                         ├◄──────────────────────────────────┘ │
└─────────────────────────────────────────┘                                     │
                                                                                │
                                                                                │
┌─────────────────────────────────────────┐                                     │
│ Portable project and exports            │                                     │
│                                         ├◄────────────────────────────────────┘
└─────────────────────────────────────────┘
```

### 4\.2 Shared time representation

1. Give each source a project sample rate equal to its decoded source rate.
2. Store event boundaries as integer project sample positions.
3. Store model preprocessing rates separately.
4. Convert model timestamps back into project positions in the adapter.
5. Preserve audio start offsets and decoder-delay handling.
6. Use half-open intervals: `[start, end)`.
7. Keep source time independent of playback speed.
8. Keep musical position separate from source time.
9. Derive seconds for display.
10. Validate all event positions against source duration.

### 4\.3 Core data objects

| Object | Required contents |
|---|---|
| Project | ID, schema version, source, revisions, settings, active result versions |
| Asset | Hash, relative location, format, sample rate, channels, sample count |
| Stem | Instrument role, asset, source alignment, separation run |
| Analysis run | Module, model, hashes, parameters, device, dependencies, status |
| Beat | Sample position, pulse role, confidence, provenance |
| Tempo anchor | Sample position, musical position, lock state |
| Meter region | Start, numerator, denominator, grouping, confidence |
| Chord region | Start/end, root, quality, extensions, bass, text label, confidence |
| Bass note | Start/end, MIDI pitch, tuning/bend information, confidence |
| Key region | Start/end, tonic, mode, spelling, confidence |
| Marker/section | Position or interval, label, color |
| Loop | Start/end anchors, repetitions, count-in, name |
| Edit command | Type, target IDs, before/after values, base revision |
| View state | Zoom, scroll, track order/heights, overlays, selection |
| Mixer state | Mute, solo, gain, pan, master settings |

Store framewise model arrays as binary artifacts. Do not inflate the main project JSON with millions of pitch or activation samples.

### 4\.4 Confidence representation

Use:

- `value`: numeric score or null.
- `kind`: probability, periodicity, heuristic, agreement, unavailable.
- `method`: description/version.
- `calibrated`: boolean.
- `alternatives`: optional candidates and scores.
- `review_state`: unreviewed, accepted, corrected.

Every automatic result must carry this confidence structure.

When a model does not provide meaningful confidence, use an explicitly labeled heuristic or `unavailable`. Never display an invented probability. Separation quality is particularly unsuitable for an unsupported “95% accurate” badge.

### 4\.5 Local API

Implement these interface groups:

| Interface | Purpose |
|---|---|
| `GET /api/v1/health` | Runtime readiness |
| `GET /api/v1/hardware` | CPU/GPU availability and memory |
| `GET /api/v1/modules` | Installed modules and capabilities |
| `GET /api/v1/models` | Model installation and license state |
| `POST /api/v1/imports` | Local media import |
| `POST /api/v1/imports/youtube` | Explicit YouTube retrieval |
| `POST /api/v1/projects` | Create project |
| `GET /api/v1/projects/{id}` | Project snapshot |
| `POST /api/v1/projects/{id}/commands` | Transactional manual edits |
| `POST /api/v1/projects/{id}/undo` | Undo command |
| `POST /api/v1/projects/{id}/redo` | Redo command |
| `POST /api/v1/projects/{id}/runs` | Run module or pipeline |
| `POST /api/v1/jobs/{id}/cancel` | Cancel job |
| `GET /api/v1/jobs/{id}` | Durable job status |
| `GET /api/v1/assets/{id}/pcm` | Bounded PCM range |
| `GET /api/v1/assets/{id}/peaks` | Waveform tiles |
| `POST /api/v1/projects/{id}/save` | Save portable project |
| `POST /api/v1/projects/open` | Open project |
| `POST /api/v1/projects/{id}/exports` | Create export |
| `/api/v1/events` | WebSocket job/revision events |

All edits include a base revision and idempotency key. Reject stale edits with a conflict response; do not silently overwrite another tab’s changes.

WebSocket messages carry event IDs. Reconnection retrieves missed status from the backend rather than assuming the connection was continuous.

### 4\.6 Analysis-module contract

Each module declares:

1. Stable identifier and version.
2. Supported input roles.
3. Output schema.
4. Parameter schema.
5. Model requirements.
6. CPU/GPU support.
7. Expected memory class.
8. Prerequisites.
9. Confidence capabilities.
10. Cancellation behavior.
11. Determinism limitations.
12. License records.

Each worker supports:

- Inspect capabilities.
- Validate request.
- Load model.
- Run analysis.
- Report progress.
- Cancel.
- Release resources.

Use versioned JSON messages for control and file-backed artifacts for large data. GPU tensors never cross process boundaries through the API.

### 4\.7 Job scheduling

1. Persist queued jobs before starting workers.
2. Resolve dependency graphs.
3. Check cache before scheduling.
4. Run at most one heavy job per GPU initially.
5. Assign separation to the RTX 4080 by default.
6. Assign compatible independent analysis to the RTX 5060 Ti.
7. Limit CPU worker concurrency to preserve playback responsiveness.
8. Use GPU UUIDs rather than unstable device indices.
9. Record actual GPU assignment.
10. Reduce batch/chunk sizes on supported out-of-memory recovery paths.
11. Keep retries bounded.
12. Report failure without destroying previous results.
13. Publish completed artifacts atomically.
14. Resume pipelines from completed nodes after restart.

Do not combine the two GPUs into an assumed 32 GB device.

***

## 5\. Import, audio storage, and waveform generation

### 5\.1 Supported inputs

Target these common formats through FFmpeg:

- WAV, FLAC, MP3.
- AAC/M4A, Ogg Vorbis, Opus.
- AIFF.
- MP4, MOV, MKV, WebM.
- Other formats supported by the installed decoder build.

“Popular formats” means supported, unencrypted audio streams; protected or corrupt media can fail with an explicit explanation.

### 5\.2 Import sequence

1. Accept drag-and-drop or a browser file picker.
2. Transfer the selected file only to the loopback backend.
3. Stream it into a temporary import location.
4. Enforce configurable size and disk-space limits.
5. Compute the source-file SHA-256.
6. Probe actual contents with ffprobe.
7. List audio streams if the container contains more than one.
8. Let the user select the audio stream.
9. Ignore video frames for analysis.
10. Record source metadata.
11. Decode to immutable float32 PCM at the original audio sample rate.
12. Preserve original channels.
13. Generate a documented stereo analysis downmix when needed.
14. Reject files with no usable audio.
15. Preserve the original imported file in the portable project by default.
16. Generate waveform data progressively.
17. Make playback available before expensive analysis completes.

Do not normalize the source during import.

### 5\.3 YouTube input

Use yt-dlp, FFmpeg, and a supported local JavaScript runtime. Current yt-dlp documentation identifies JavaScript-runtime support as part of full YouTube operation. [yt-dlp](<https://github.com/yt-dlp/yt-dlp>), [EJS setup](<https://github.com/yt-dlp/yt-dlp/wiki/EJS>)

Implementation steps:

1. Accept a single YouTube video URL.
2. Validate the URL and supported host.
3. Retrieve metadata locally.
4. Display title and duration.
5. Download the selected audio stream.
6. Preserve the downloaded stream without unnecessary lossy re-encoding.
7. Run the same import/decode path as local files.
8. Store URL and retrieval date as provenance.
9. Reuse the downloaded asset when reopening.
10. Support cancellation and interrupted-download recovery.
11. Show actionable retrieval errors.
12. Keep extractor updates separate from model updates.

Default boundaries:

- No playlist downloading in the first release.
- No automatic browser-cookie extraction.
- No bypassing access controls.
- No automatic redownload when a project opens.
- YouTube fetching requires internet access, but processing remains local.

### 5\.4 Analysis copies

For each model:

1. Read its declared channel and sample-rate requirements.
2. Generate a cached resampled/downmixed view.
3. Record the exact transform.
4. Preserve source-time mapping.
5. Pass the view into the worker.
6. Convert outputs back to project coordinates.

Never overwrite the source with a model-specific resampling.

### 5\.5 Waveform pyramid

1. Scan PCM in bounded chunks.
2. Compute signed minima and maxima per channel.
3. Begin with approximately 64 source samples per bucket.
4. Build successively coarser levels by powers of four.
5. Store levels in fixed-size tiles.
6. Store sample rate, sample count, and format version.
7. Select the level providing roughly one or two buckets per screen pixel.
8. Fetch only visible tiles plus a small margin.
9. Cache recently viewed tiles.
10. At close zoom, fetch actual PCM samples.
11. Render sample lines or points at sample-level zoom.
12. Evict offscreen data under memory pressure.

Use separate canvas layers for waveforms, musical annotations, selection, and the playhead.

Vertical zoom changes visual amplitude scale only. Mixer gain remains a distinct control.

***

## 6\. Analysis pipelines

### 6\.1 Separation processing

1. Select bass-only, four-stem, or six-stem mode.
2. Resolve the selected model.
3. Validate installed weights.
4. Estimate memory needs from model configuration.
5. Prepare the required audio representation.
6. Process with the model’s supported overlap/chunk strategy.
7. Preserve stereo phase relationships.
8. Assemble chunks with the model-appropriate overlap-add.
9. Remove padding and account for latency.
10. Resample stems back to project rate.
11. Enforce the source sample count.
12. Save float32 analysis stems.
13. Generate peaks for each stem.
14. Record model version and processing parameters.
15. Publish the result as a new separation version.

For bass-plus-others:

- Produce a bass estimate.
- Compute `others = original − bass` at the same rate and alignment.
- Store the residual as a distinct derived stem.

This provides a reconstructing two-part split. It does not guarantee that the bass estimate is free of leakage.

Do not independently normalize analysis stems.

For multi-stem output, retain raw model stems and measure reconstruction error. If offering mixture-consistency correction, save it as a separate derived result.

### 6\.2 Beat and downbeat processing

1. Analyze the original mix first.
2. Retain beat and downbeat activations.
3. Convert candidates into source sample positions.
4. Preserve low-confidence candidates for inspection.
5. Optionally analyze the drum stem as another result.
6. Compare original/drum agreement.
7. Avoid silently replacing original timing with drum-stem timing.
8. Save raw and decoded outputs separately.

### 6\.3 Tempo-map processing

Use a monotonic mapping between source samples and musical quarter-note positions.

1. Start from detected pulse positions.
2. Determine pulse-unit hypotheses with the meter module.
3. Convert chosen pulse positions into quarter-note positions.
4. Create an anchor for each accepted beat.
5. Interpolate linearly between anchors.
6. Derive local quarter-note BPM:

   `BPM = 60 × change_in_quarter_notes / change_in_seconds`
7. Retain natural timing variation.
8. Compute a robust summary BPM separately.
9. Support half-time/double-time reinterpretation.
10. Permit anchor insertion, movement, deletion, and locking.
11. Validate that time and musical position remain increasing.
12. Support manual first-downbeat placement and pickup bars.
13. Mark unsupported or ambiguous regions instead of forcing a constant grid.

In 6/8, display the tempo unit explicitly. Quarter-note BPM and dotted-quarter pulse BPM must not be confused.

### 6\.4 Time-signature processing

Implement a separate meter-inference module using:

- Beat/downbeat activations.
- Accent patterns.
- Subdivision onset evidence.
- Bar-duration consistency.
- A penalty for excessive meter changes.

Initial candidate set:

- 2/4.
- 3/4.
- 4/4.
- 6/8.
- 9/8.
- 12/8.
- 5/4.
- 7/8.

Processing:

1. Generate plausible pulse-grouping hypotheses.
2. Score simple and compound interpretations.
3. Decode a sequence of meter regions.
4. Retain competing candidates and score margins.
5. Emit “uncertain” where evidence is inadequate.
6. Allow arbitrary manually entered numerator/denominator pairs.
7. Allow grouping such as `2+2+3`.
8. Permit meter changes at explicit bar boundaries.
9. Support partial pickup bars.

Beat detection does not by itself prove the notated time signature. Automatic meter labels must remain editable and visibly uncertain when appropriate.

### 6\.5 Chord processing

1. Select the original mix as the default input.
2. Generate the model-specific spectral representation.
3. Run overlapping inference windows.
4. Merge window outputs in their original time coordinates.
5. Save framewise logits or scores where available.
6. Decode chord regions.
7. Preserve `no chord` separately from `unknown`.
8. Retain candidate alternatives.
9. Apply configurable temporal smoothing.
10. Avoid mandatory beat quantization.
11. Optionally analyze a harmonic remix of available stems.
12. Store that as a separate result version.
13. Use sustained bass evidence to propose inversions.
14. Mark inversion evidence separately from chord-root confidence.

Chord complexity settings:

- **Simple:** major/minor-oriented display.
- **Standard:** supported sevenths, diminished, augmented, and suspended types.
- **Detailed:** all supported labels, extensions, and inversion candidates.

Complexity changes must preserve the underlying detailed prediction.

### 6\.6 Key processing

1. Estimate tuning offset.
2. Calculate tonal features.
3. Run global key estimation.
4. Run overlapping-window local key estimation.
5. Smooth unstable changes.
6. Distinguish relative-major/minor alternatives.
7. Permit “unknown” and “no stable key.”
8. Suggest enharmonic spelling.
9. Allow manual spelling and mode changes.
10. Preserve all automatic alternatives.

Key changes affect labels and analysis context. They do not transpose the audio.

### 6\.7 Bass transcription processing

1. Select a bass stem version.
2. Generate a mono analysis signal.
3. Detect silence and low-energy sections.
4. Estimate a bass-stem-specific tuning offset as its own immutable analysis result, tied to the selected bass stem.
5. Select the tuning interpretation for transcription—prefer the compatible bass-stem tuning result when valid, with the Milestone 4 project tuning context available as an explicit fallback/override—and record that dependency.
6. Run pYIN over the configured bass range.
7. Run neural pitch analysis.
8. Run the low-register auxiliary path.
9. Map all candidates into source time.
10. Compare octave-related candidates.
11. Apply voicing hysteresis.
12. Use continuity as a soft preference.
13. Detect attacks from energy and spectral changes.
14. Preserve repeated attacks on the same pitch.
15. Detect sustained notes and releases.
16. Preserve continuous pitch bends/slides.
17. Segment discrete note events.
18. Store MIDI pitch and cents deviation.
19. Retain framewise F0 and confidence.
20. Flag polyphonic or ambiguous passages.
21. Save transcription as an independent version.

Initial analysis defaults:

- Approximate pitch range: 25–800 Hz.
- Frame hop: approximately 10 ms.
- Low-frequency pYIN window: approximately 128 ms.
- No mandatory beat snapping.
- No destructive pitch correction.
- Scientific pitch notation, with A4 = MIDI 69.

Changing note labels or boundaries edits the transcription only.

### 6\.8 Whole-pipeline execution

The **Analyze All** button:

1. Checks required models.
2. Shows missing installations.
3. Imports/decodes only if needed.
4. Generates peaks.
5. Runs separation.
6. Runs original-mix rhythm and harmony analysis when resources permit.
7. Runs/reuses bass-stem-specific tuning estimation after bass separation, then runs bass transcription with the selected tuning interpretation.
8. Derives tempo, meter, and bar positions.
9. Publishes available results progressively.
10. Preserves successful results if another module fails.
11. Reports completion, warnings, and skipped modules.

Individual buttons remain available for every module.

***

## 7\. Browser audio engine and practice features

### 7\.1 One transport and one clock

Use one `AudioContext` and one authoritative transport.

AudioWorklet executes audio processing separately from the main UI thread. SharedArrayBuffer requires the appropriate cross-origin-isolation headers; provide a transferable-buffer fallback. [AudioWorklet](<https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet>), [cross-origin isolation](<https://developer.mozilla.org/en-US/docs/Web/API/WorkerGlobalScope/crossOriginIsolated>)

Implementation:

1. Resume audio after a user gesture.
2. Request bounded PCM blocks from localhost.
3. Resample consistently to the actual AudioContext sample rate.
4. Fill per-stem buffers.
5. Drive all stems from the same source position.
6. Mix with shared sample-accurate boundaries.
7. Pass the stereo mix through one time stretcher.
8. Schedule metronome clicks against the same transport.
9. Report latency-compensated source position to the UI.
10. Use animation frames only for drawing.
11. Handle audio-device changes by rebuilding the output path.
12. Preserve project time across playback-rate changes.

Mixing before one stereo stretcher avoids independent stem processors developing different timing behavior.

### 7\.2 Streaming and buffering

1. Use approximately one-second network chunks.
2. Prefetch approximately eight seconds ahead.
3. Retain approximately two seconds behind.
4. Expand lookahead when required by playback speed or stretch latency.
5. Bound each stem’s retained PCM.
6. Preload both sides of a loop.
7. Cancel obsolete fetches after seeks.
8. Discard old responses using a transport-generation ID.
9. Pause coherently if required audio is unavailable.
10. Resume only when all audible stems are ready.

A muted stem must either remain buffered or join only when synchronized data is available.

### 7\.3 Mixer

Per stem:

- Mute.
- Solo.
- Gain.
- Pan.
- Color.
- Visibility.
- Waveform height.

Behavior:

1. Multiple solos are allowed.
2. With any solo active, only soloed, unmuted stems sound.
3. Mute overrides solo for that stem.
4. Apply short gain ramps to prevent clicks.
5. Keep hidden tracks audible unless muted.
6. Keep the original mix separate from the stem sum.
7. Default to either original playback or stem playback, avoiding accidental doubling.
8. Provide an output clipping indicator.
9. Provide a switchable monitoring limiter.

The monitoring limiter does not alter stored stems.

### 7\.4 Speed control

1. Support 0.25×–2.0× initially.
2. Default to preserving pitch.
3. Provide common speed presets.
4. Allow fine adjustment.
5. Keep source timestamps unchanged.
6. Update metronome timing with speed.
7. Smooth speed transitions.
8. Compensate stretcher latency.
9. Retain a source-to-output mapping across rate changes.
10. Validate sustained bass, drums, stereo imaging, and loops at each extreme.

At 1×, bypass unnecessary stretching with an aligned transition.

### 7\.5 Loops and snippets

1. Create a loop by dragging a waveform range.
2. Create a loop from selected notes, chords, beats, bars, or sections.
3. Enter start/end times numerically.
4. Name and save loops.
5. Adjust boundaries independently.
6. Set finite repeats or repeat indefinitely.
7. Queue multiple noncontiguous snippets.
8. Reorder the queue.
9. Prebuffer the next snippet.
10. Use short boundary fades to avoid clicks.
11. Keep displayed loop boundaries exact.
12. Permit sample-anchored and beat-anchored loops.

Default loops use fixed source positions. Beat-anchored loops follow subsequent tempo-map edits.

### 7\.6 Count-in

1. Offer off, one bar, or two bars.
2. Default count-in to off.
3. Offer count-in once or before every repeat.
4. Use the meter active at the loop start.
5. Use the local tempo at the loop start.
6. Apply playback-speed scaling.
7. Count into the correct beat when a loop begins mid-bar.
8. Accentuate downbeats and optional grouping accents.
9. Keep count-in separate from source time.
10. Display count-in state clearly.

### 7\.7 Metronome

1. Generate clicks locally.
2. Schedule from the selected tempo map.
3. Accent downbeats.
4. Support compound-meter grouping.
5. Offer subdivisions.
6. Provide independent volume.
7. Follow manual tempo changes.
8. Follow playback speed.
9. Rebuild future events after seeks and edits.
10. Never derive audio clicks from animation timers.

***

## 8\. Editor behavior and manual correction

### 8\.1 Main layout

Provide:

- Import/project controls.
- Transport and speed controls.
- Analysis-module buttons.
- Overview waveform.
- Seconds and musical ruler.
- Tempo/meter lane.
- Key lane.
- Editable chord lane.
- Original and separated waveform tracks.
- Bass-note overlay.
- Bass-note text lane below the bass waveform.
- Markers/sections and loops.
- Inspector for the selected object.
- Job progress and confidence-review panel.

All tracks share horizontal scroll and zoom.

### 8\.2 Zoom and navigation

1. Support horizontal zoom around the cursor.
2. Support zoom around the playhead.
3. Support fit-song and fit-selection.
4. Support per-track vertical amplitude zoom.
5. Support independent track heights.
6. Offer follow-playhead and stationary-playhead scrolling.
7. Suspend automatic following when the user pans.
8. Provide a visible return-to-playhead control.
9. Preserve zoom and scroll in the project.
10. Virtualize vertically offscreen tracks.

### 8\.3 Chord editor

1. Select a region.
2. Rename its chord.
3. Enter slash chords such as `C/E`.
4. Drag its start or end.
5. Drag a shared boundary without creating accidental gaps.
6. Split at the playhead.
7. Merge adjacent regions.
8. Insert a missing chord.
9. Delete a region.
10. Assign no-chord or unknown.
11. Choose an alternative prediction.
12. Toggle snapping.
13. Mark the region reviewed.
14. Show the original automatic label in the inspector.
15. Preserve unsupported custom text labels.

For a merged region, retain the leftmost chord label by default; the action is immediately undoable.

### 8\.4 Bass-note editor

1. Select notes from either overlay or text lane.
2. Move note boundaries.
3. Change pitch numerically or by semitone/octave.
4. Insert/delete notes.
5. Split/merge notes.
6. Correct octave errors.
7. Mark unpitched or unknown events.
8. Edit slide/bend information.
9. Audition the corresponding audio range.
10. Mark notes reviewed.

In monophonic mode, overlapping edits are rejected unless the user explicitly enables overlapping-note representation.

### 8\.5 Rhythm, meter, key, and tuning editors

Support:

- Add/delete/move beats.
- Mark or change downbeats.
- Insert/delete/move tempo anchors.
- Lock correct anchors.
- Set the first numbered bar.
- Add pickup bars.
- Apply half/double-time interpretation.
- Edit time-signature regions and grouping.
- Edit key-region boundaries, tonic, mode, and spelling.
- Edit tuning reference and tuning offset.

Every correction creates a project command.

### 8\.6 Linked selection

Use one selection model containing:

- Selected object IDs.
- A source-time range.
- Focused track.
- Selection origin.
- Related intersecting objects.

Behavior:

1. Selecting a note highlights corresponding waveform time and chord/bar context.
2. Selecting a chord highlights intersecting notes and waveform ranges.
3. Selecting a bar highlights all intersecting events.
4. Selecting a waveform range highlights related timeline objects.
5. Related highlights do not automatically become edit targets.
6. Clicking selects by default.
7. Seeking remains a separate explicit gesture or shortcut.

### 8\.7 Musical readout

Display:

`01:32.481 | Bar 42 Beat 3.27 | D2 | Gmaj7`

Use:

- Latency-compensated source position.
- Selected edited/automatic timeline version.
- Active note at the playhead.
- Active chord region.
- Current meter and tempo-map interpretation.

Show a dash or “unknown” where a value is unavailable.

### 8\.8 Snapping

Offer:

- Off.
- Beat.
- Half-beat.
- Quarter-beat.
- Bar.
- Nearest event boundary.

Use a fixed visual snap radius, approximately eight CSS pixels. Provide a temporary modifier-key override.

Snapping changes an edit only when the user performs the edit. Correcting the beat grid must not silently quantize existing source-anchored notes or chords.

### 8\.9 Confidence display

1. Add low-confidence badges or hatching.
2. Avoid relying on color alone.
3. Show score type in tooltips.
4. Separate model confidence from human review.
5. Provide next/previous uncertain-event navigation.
6. Allow per-module thresholds.
7. Show unknown confidence explicitly.
8. Preserve corrected objects’ original model confidence.
9. Do not relabel a human correction as model confidence 1.0.

### 8\.10 Keyboard shortcuts

Default mapping:

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
| Escape | Cancel active gesture or close editor |

Make shortcuts remappable. Disable transport/edit shortcuts when typing into text fields.

***

## 9\. Undo, analysis versions, projects, and caching

### 9\.1 Undo/redo

1. Represent edits as explicit commands.
2. Record previous and next values.
3. Group a drag into one command.
4. Group batch edits into one transaction.
5. Persist commands with project revisions.
6. Undo commands in reverse order.
7. Redo undone commands.
8. Clear the active redo branch after a new edit.
9. Preserve named historical revisions separately.
10. Include mixer, marker, loop, and view changes in history.
11. Coalesce continuous slider/zoom gestures.
12. Exclude transient playhead movement from edit history.

Analysis jobs themselves are not “undone.” Changing which result version is active is undoable.

### 9\.2 Automatic and edited versions

For editable symbolic/annotation analysis families—rhythm/grid, chord/key/tuning state where manual correction is defined, and bass transcription:

- Preserve immutable machine output.
- Create an editable branch from a selected output.
- Allow Auto/Edited switching.
- Permit multiple named model outputs.
- Preserve source/model provenance.
- Never overwrite corrections when rerunning analysis.
- Mark downstream results stale when inputs change.
- Keep stale results available until replaced.

Separation is different: separated audio result sets remain immutable and support retained model/result-version selection, but there is no generic Edited-separation branch that mutates machine-generated stem audio. Mixer state is editable project state, not an edited separation result.

Selecting a new bass separation does not silently replace the transcription tied to the old bass stem.

### 9\.3 Portable `.basseparate` format

Use a versioned ZIP64 container containing:

- Manifest.
- Consistent project database snapshot.
- Original imported media.
- Canonical audio.
- Separated stems.
- Analysis artifacts.
- Manual edits/history.
- Model provenance.
- Waveform caches.
- Mixer/view/loop/marker state.

Do not include model weights, including the Demucs baseline that may be bundled with the application release. Portable projects remain independent of application/model installation state.

Detailed save procedure:

1. Choose a stable project revision.
2. Create a consistent SQLite snapshot.
3. Collect referenced assets.
4. Verify referenced assets exist.
5. Write a new temporary archive.
6. Hash included assets.
7. Write the manifest.
8. Close and flush the archive.
9. Verify the archive can be read.
10. Atomically publish the verified archive inside managed local portable-export storage.
11. Expose it through an authenticated browser download with `Content-Disposition`; the browser/user chooses the final filesystem destination. Retain one previous successful managed portable-export artifact when configured.

Opening:

1. Read and validate the manifest.
2. Check schema compatibility.
3. Reject unsafe archive paths.
4. Enforce extraction-size limits.
5. Verify asset hashes.
6. Restore into a managed working directory.
7. Load cached peaks and existing results.
8. Restore view and mixer state.
9. Open without invoking a model.
10. Report missing/corrupt optional caches separately from essential assets.

### 9\.4 Working storage and autosave

Use a managed working directory for active editing.

1. Commit each completed semantic edit transaction.
2. Debounce frequent view-state saves to approximately two seconds.
3. Use SQLite WAL during active work.
4. Write bulk analysis results outside the database.
5. Commit references only after artifact completion.
6. Record the last clean shutdown.
7. Offer recovery after an interrupted session.
8. Avoid rebuilding a large archive after every edit.
9. Keep explicit portable save separate from fast working autosave.
10. Display “saved,” “saving,” or “recovery available” accurately.

### 9\.5 Cache identity

Include:

- Source-file hash.
- Selected audio stream.
- Decode/downmix/resample configuration.
- Upstream asset hashes.
- Module and model versions.
- Weight hash.
- Parameters.
- Precision mode.
- Relevant preprocessing version.
- Analysis interval and context padding.

Use immutable content-addressed cache objects.

### 9\.6 Cache management

1. Reuse identical completed jobs.
2. Keep temporary/incomplete artifacts separate.
3. Protect assets referenced by saved or active projects.
4. Set an initial 50 GiB cache budget.
5. Offer adjustable limits.
6. Display project, model, and cache usage separately.
7. Evict unreferenced least-recently-used cache objects.
8. Never evict installed model files as ordinary analysis cache.
9. Warn before a job exceeds available disk space.
10. Provide explicit cleanup with a size preview.

***

## 10\. Export

### 10\.1 Audio export options

Support:

- Individual stems.
- Selected stems together.
- Original audio.
- Current mixer output.
- Active selection.
- Named loop/snippet queue.

Formats:

- WAV: 16-bit, 24-bit, float32.
- FLAC: supported integer depths.
- MP3: selectable bitrate, including 320 kb/s when supported.

Default stem export:

- WAV.
- 24-bit.
- Original source sample rate.
- Full original duration.
- Normalization off.

### 10\.2 Export procedure

1. Select source/stem result version.
2. Select full duration or region.
3. Choose format and compatible sample rate.
4. Preserve common start position across stems.
5. Choose original speed or practice speed.
6. Apply mixer state only for mix exports or explicit processed-stem exports.
7. Apply normalization only when selected.
8. Offer linked normalization across stems to preserve balance.
9. Offer independent normalization as a separately labeled option.
10. Dither when reducing to integer bit depth.
11. Check clipping.
12. Encode through FFmpeg.
13. Verify output duration and stream metadata.
14. Publish completed export artifacts atomically inside managed local export staging/storage.
15. Deliver them through authenticated browser downloads with `Content-Disposition`; the browser/user controls the final filesystem destination. Do not require a browser to expose an arbitrary destination path to the backend.

MP3 cannot preserve every possible source sample rate or exact PCM round-trip timing. Present compatible output choices rather than promising an unsupported combination.

### 10\.3 Analysis export

Also provide:

- Bass MIDI.
- Chords as timestamped `.lab`.
- Chords/notes/beats as CSV.
- Complete analysis as JSON.
- Tempo and time-signature events in MIDI where representable.
- Marker/loop interval lists.

Export either Auto or Edited explicitly. Include provenance in JSON exports.

***

## 11\. Locality, reliability, and operational behavior

### 11\.1 Local-only operation

1. Bind the backend to loopback.
2. Serve all fonts, scripts, icons, and WASM locally.
3. Use no telemetry or analytics.
4. Make no automatic model-download calls during inference.
5. Separate network-enabled download workers from analysis workers. The bundled Demucs baseline requires no network job; this boundary applies to optional model installation/update and YouTube retrieval.
6. Provide offline mode.
7. Disable YouTube/non-bundled-model retrieval in offline mode while keeping bundled Demucs inference available.
8. Avoid external thumbnail or embedded-player requests.
9. Never send audio, fingerprints, or analysis to an external service.
10. Verify locality with network-observation tests.

The browser’s local transfer to the backend remains on your PC.

### 11\.2 Loopback service protection

1. Validate Host and Origin.
2. Use a per-session authentication mechanism.
3. Require protection for mutating requests.
4. Restrict CORS.
5. Validate WebSocket origins.
6. Address assets by opaque IDs.
7. Constrain filesystem operations to permitted project locations.
8. Pass subprocess arguments as arrays.
9. Validate archive extraction paths.
10. Use explicit plugin installation; opening a project never installs code.

### 11\.3 Model integrity

1. Download only registered model artifacts.
2. Pin revisions.
3. Verify hashes.
4. Preserve license notices.
5. Prefer safe tensor formats when available.
6. Use restricted weight loading where supported.
7. Isolate legacy checkpoint loading.
8. Reject arbitrary remote code execution hooks.
9. Keep credentials out of logs and projects.

### 11\.4 Failure behavior

Handle:

- Missing GPU.
- Incompatible CUDA/PyTorch build.
- GPU memory exhaustion.
- Missing model.
- Interrupted download.
- Corrupt audio.
- No audio stream.
- Full disk.
- Worker crash.
- Browser refresh.
- Audio-device loss.
- Project-version mismatch.
- Missing optional plugin.

Every failure must state:

- What failed.
- Which results remain available.
- Whether retry is possible.
- What action resolves it.

Never silently replace failed GPU processing with a potentially hours-long CPU run.

***

## 12\. Model benchmarking and acceptance criteria

### 12\.1 Hardware qualification

1. Recheck driver access outside the restricted session if necessary.
2. Enumerate GPUs through PyTorch.
3. Verify computation on each GPU independently.
4. Verify the selected PyTorch build supports both architectures.
5. Record driver/runtime versions.
6. Run a short inference for each selected model.
7. Measure peak VRAM.
8. Measure wall time.
9. Measure host RAM.
10. Verify repeatability within documented tolerances.

Use a currently supported PyTorch/CUDA combination verified against its official support matrix. Blackwell support makes old CUDA-wheel assumptions inappropriate. [PyTorch release matrix](<https://github.com/pytorch/pytorch/blob/main/RELEASE.md>)

### 12\.2 Evaluation corpus

Create:

1. Synthetic clicks and tempo ramps.
2. Synthetic meter/grouping fixtures.
3. Bass scales including low B and lower drop tuning.
4. Repeated-note and slide examples.
5. Silence and percussion-only examples.
6. Known chord/inversion fixtures.
7. Detuned examples.
8. Licensed multitrack mixtures with ground-truth stems.
9. Manually annotated excerpts from your five supplied tracks.
10. Long-form audio for memory and playback tests.

Keep development/tuning material separate from final evaluation material.

### 12\.3 Separation evaluation

Measure:

- Per-stem SDR or SI-SDR with reference stems.
- Bass leakage.
- Missing note attacks.
- Sustained-note artifacts.
- Reconstruction error.
- Stereo preservation.
- Downstream bass transcription accuracy.
- Runtime and memory.

Use listening comparisons on your own tracks, where no reference stems are available. Do not report reference-based accuracy metrics for those tracks.

### 12\.4 Promotion rule

Retain the initial default unless a challenger:

1. Passes license and reproducibility checks.
2. Fits the measured memory budget.
3. Completes the whole validation corpus.
4. Does not materially regress bass note-event accuracy.
5. Improves bass separation metrics or documented blinded listening results.
6. Has no severe regression on a target category.

If evidence conflicts, keep both as named presets. Do not hide the tradeoff behind “best.”

### 12\.5 Chord and rhythm evaluation

Measure:

- Duration-weighted chord accuracy.
- Accuracy under simple and detailed vocabularies.
- Boundary precision/recall.
- Inversion accuracy separately.
- Beat/downbeat F-measure.
- Half/double-tempo errors.
- Meter-region accuracy.
- Tempo-anchor timing error.
- Key accuracy, including relative and fifth-related errors.

### 12\.6 Bass evaluation

Measure:

- Voicing precision/recall.
- Pitch accuracy within 50 cents.
- Octave-error rate.
- Note onset F-measure.
- Note onset-plus-offset F-measure.
- Repeated-note detection.
- Low-B/drop-tuning subsets.
- Slide continuity.
- End-to-end error after separation.

Do not collapse all bass performance into one average.

### 12\.7 Confidence evaluation

1. Compare model scores with labeled correctness.
2. Measure whether low-score events are actually more error-prone.
3. Calibrate only on suitable held-out data.
4. Preserve uncalibrated labels otherwise.
5. Do not compare scores from unrelated modules as though they share a scale.

### 12\.8 Software acceptance targets

These are implementation targets, not measured results:

- No cumulative relative stem drift.
- Untreated stems begin on the same output sample.
- Audio/metronome scheduling follows the same render clock.
- Foreground visual playhead generally within approximately 30 ms of audible position after latency compensation.
- No steadily increasing visual drift.
- Six-stem 60-minute playback uses bounded buffering.
- Zoom and selection remain responsive on long projects.
- Portable reopen requires no model inference.
- Crash recovery preserves committed edits.
- Offline operation performs no external requests.
- All manual edits round-trip through save/open and undo/redo.

***

## 13\. Detailed implementation milestones

### Milestone 0 — Reproducible foundation

1. Create repository/package structure.
2. Record hardware and dependency requirements.
3. Preserve existing media.
4. Add dependency locks.
5. Add development commands.
6. Create backend health route.
7. Serve a local browser shell.
8. Add loopback protection.
9. Create project and asset schemas.
10. Add schema-version handling.
11. Create worker message schema.
12. Add unit-test infrastructure.
13. Add browser-test infrastructure.
14. Establish the license manifest.
15. Verify startup and shutdown.

**Acceptance:** one command opens a local application; no analysis model is required.

### Milestone 1 — Import, waveform, and original playback

1. Implement streaming file import.
2. Implement ffprobe inspection.
3. Implement audio-stream selection.
4. Implement canonical decoding.
5. Implement source hashing.
6. Implement asset storage.
7. Build waveform pyramids.
8. Build tiled rendering.
9. Add horizontal zoom.
10. Add vertical amplitude zoom.
11. Add source PCM streaming.
12. Implement the shared transport.
13. Add play/pause/seek.
14. Add readout and follow-playhead.
15. Add basic markers and selection.
16. Implement working-project persistence.
17. Test all target input formats.

**Acceptance:** a local audio/video file opens, displays, zooms, and plays accurately.

### Milestone 2 — Bass practice workflow

1. Implement the Demucs worker.
2. Verify and use the pinned bundled Demucs `htdemucs_ft` baseline from the ignored development-workspace model directory/release bundle; do not require a network install for this baseline.
3. Add GPU selection.
4. Add progress/cancellation.
5. Add bass/residual separation.
6. Add four-stem separation.
7. Generate stem waveforms.
8. Display aligned tracks.
9. Add mute/solo/gain/pan.
10. Add waveform loop selection.
11. Add saved loops.
12. Integrate Signalsmith Stretch.
13. Add variable-speed controls.
14. Validate latency handling.
15. Export WAV stems.
16. Implement analysis caching.
17. Save/open self-contained projects.

**Acceptance:** import a song, isolate bass, slow it down, loop a passage, and reopen without rerunning separation.

### Milestone 3 — Musical grid

1. Integrate Beat This\!.
2. Retain frame activations.
3. Build beat/downbeat objects.
4. Implement tempo-map conversion.
5. Implement meter hypotheses.
6. Add bar/beat ruler.
7. Add first-downbeat editing.
8. Add pickup bars.
9. Add tempo-anchor editing.
10. Add meter-region editing.
11. Implement snapping.
12. Add metronome.
13. Add one-/two-bar count-in.
14. Add musical readout.
15. Verify 4/4, 3/4, 6/8, tempo ramps, and free timing.

**Acceptance:** the user can correct a grid and practise variable-tempo loops with a synchronized metronome.

### Milestone 4 — Harmony analysis and editing

1. Integrate BTC.
2. Integrate ChordMini challenger.
3. Integrate Chordino fallback.
4. Preserve raw prediction artifacts.
5. Build chord regions.
6. Add chord overlays.
7. Add dedicated chord track.
8. Add split/merge/rename/boundary operations.
9. Add inversion entry.
10. Add complexity projections.
11. Integrate tuning/key analysis.
12. Add key-region editor.
13. Add confidence review.
14. Compare original and harmonic-remix inputs.
15. Validate save/open and undo behavior.

**Acceptance:** chords and key are detected, synchronized, and fully correctable.

### Milestone 5 — Bass transcription

1. Implement pitch-analysis views.
2. Add bass-stem-specific tuning estimation as a separate immutable result.
3. Integrate torchcrepe.
4. Integrate pYIN.
5. Add low-register auxiliary inference.
6. Add candidate fusion.
7. Add silence/voicing logic.
8. Add attack detection.
9. Add note segmentation.
10. Add slide/bend retention.
11. Display notes above the waveform.
12. Display synchronized note text below it.
13. Add note editing.
14. Add linked selection.
15. Add bass MIDI export.
16. Validate low B, drop tunings, repeated notes, slides, and bass-stem tuning-offset estimation.

**Acceptance:** bass notes can be inspected and corrected against the audio in both requested views.

### Milestone 6 — Complete persistence and workflow

1. Complete command coverage for all manual edits.
2. Harden and unify persistent undo/redo across all editable domains introduced in Milestones 1–5.
3. Add unified retained-result/model/input version switching, with Auto/Edited switching only for analysis families that define editable branches.
4. Add revision conflict handling.
5. Add crash recovery.
6. Add downstream stale-result indicators.
7. Add snippet queues.
8. Add full keyboard mapping.
9. Add export presets.
10. Add FLAC and MP3.
11. Add analysis exports.
12. Add cache inspection/cleanup.
13. Add project migration tests.
14. Add missing-asset/corruption handling.

**Acceptance:** analysis and practice state survive crashes, reopening, and model changes.

### Milestone 7 — Quality models and YouTube

1. Integrate SCNet and RoFormer adapters.
2. Verify checkpoint/license records.
3. Benchmark the defined comparison set.
4. Publish named quality/speed presets.
5. Add six-stem guitar mode.
6. Consolidate the project-wide model manager across bundled and separately installed models; the bundled Demucs baseline is visible/verifiable/qualifiable but not treated as a removable downloaded model.
7. Generalize explicit download progress for non-bundled model families and other registered network retrievals.
8. Add yt-dlp/EJS integration.
9. Add YouTube import errors and cancellation.
10. Add independent extractor updating.
11. Add whole-pipeline execution.
12. Verify cache reuse across module runs.

**Acceptance:** local high-quality model choices and YouTube import work through the same project workflow.

### Milestone 8 — Browser validation and release

1. Test Chromium and Firefox on Nobara.
2. Test automated WebKit behavior.
3. Test actual Safari on macOS.
4. Validate user-gesture audio startup.
5. Validate WebAssembly and buffer fallback.
6. Test browser refresh/reconnection.
7. Test long tracks and large projects.
8. Test offline operation.
9. Test GPU failure and CPU fallback selection.
10. Produce Linux launcher and desktop entry.
11. Package local frontend assets.
12. Provide offline model-import instructions.
13. Document model and cache locations.
14. Provide backup/recovery instructions.
15. Complete all feature acceptance cases.
16. Publish a versioned build and license inventory.

Safari validation is a separate acceptance gate; WebKit automation alone does not prove Safari audio correctness. A Mac is not currently available in this inspected environment.

***

## 14\. Feature coverage and completion checklist

| Requested features | Planned implementation |
|---|---|
| 1, 17 | Separation adapters and synchronized stem mixer |
| 2 | Local React browser interface |
| 3, 25 | Shared tiled waveform renderer, peak/sample modes, horizontal/vertical zoom |
| 4 | FFmpeg import and audio-stream extraction |
| 5, 6, 21, 22 | Chord models, overlays, editable chord lane, complexity settings |
| 7 | Global/local key analysis and signature spelling |
| 8, 32 | Shared audio transport and musical playhead readout |
| 9, 24 | Timestamp selections, saved loops, snippet queue, count-in |
| 10, 18, 19, 20 | Beats, downbeats, bars, variable tempo map, meter regions |
| 11, 12 | Pitch-preserving speed and tempo-map metronome |
| 13, 26 | All analysis editors and persistent command history |
| 14, 15 | Bass pitch/note pipeline, overlay, synchronized text lane |
| 16 | Explicit yt-dlp YouTube import |
| 23 | Typed confidence and review workflow |
| 27, 28 | Portable projects, working autosave, content-addressed caching |
| 29 | Loopback architecture and offline processing |
| 30 | WAV/FLAC/MP3 exports |
| 31 | Remappable keyboard shortcuts |
| 33 | Shared selection across views |
| 34 | Immutable automatic versions and editable branches |
| 35 | Independent modules, job graph, individual buttons, Analyze All |

### Final completion conditions

The project is complete when:

1. Every row above has an implemented and tested workflow.
2. Your existing five tracks can be imported, analyzed, edited, practised, exported, and reopened.
3. Long recordings do not require loading every stem into browser memory.
4. Slow/fast playback, loops, waveforms, chords, notes, and metronome share coherent timing.
5. Every automatic result can be reviewed and corrected.
6. Rerunning analysis preserves earlier outputs and manual edits.
7. Saved projects reopen without model execution.
8. Local analysis remains functional with internet access disabled.
9. Model choices have recorded versions, licenses, hashes, and measured hardware behavior.
10. Accuracy limitations remain visible instead of being presented as certainty.

The first implementation deliverable should preserve this plan as the project’s versioned design document, accompanied by a task checklist, model registry, license inventory, and acceptance-test matrix.
