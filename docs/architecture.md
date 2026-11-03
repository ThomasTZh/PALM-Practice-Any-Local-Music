# Architecture

The studio is a local, single-user application. A Python server owns the files
and the analysis workers; a browser owns playback and the practice UI. Nothing
leaves the machine: no accounts, no cloud calls, no downloads.

This document describes the shipped code, not a future design. Every measured
number quoted here is attached to the command that produced it; the full build
log is [progress.md](progress.md).

## Processes

| Process | Started by | Responsibility |
| --- | --- | --- |
| Browser SPA | `basseparate serve` serving `web/dist` | Library, waveform, spectrogram, chords, sections, mixer, practice controls and the transport |
| AudioWorklet | Browser, one node per player | Mixes the canonical mix and four stems, runs Signalsmith Stretch, renders the metronome/count-in |
| Web Workers | Browser | Ranged PCM fetching (`fetch-worker.ts`) and spectrogram STFT (`spectrogram.worker.ts`) |
| HTTP server | `basseparate serve` (uvicorn + FastAPI) | Projects, assets, ranged PCM/peaks, jobs, analysis, separation, autosave, exports, `/doctor` |
| Piper children | Server, per analysis run | Three `piper-vamp-simple-server` sessions (Chordino, Key Detector, Bar and Beat Tracker) |
| Demucs child | Server, per separation run | `analysis/.venv/bin/python analysis/separate_track.py` with `htdemucs_ft` |
| MSST child | Server, per separation run with SCNet/BS-RoFormer | `analysis-models/.venv/bin/python analysis/separate_msst.py --model-id …` |
| Model registry | Server/CLI, no torch | `analysis/models.json`; installed/missing/hash-mismatch states from declared sizes and SHA-256 |
| `ffmpeg` / `ffprobe` | Server, per import/analysis | Probe metadata, decode to project-rate f32 PCM, resample for analysis |

The server binds loopback only (`127.0.0.1`, `localhost` or `::1`) and refuses a
non-loopback host. `--port 0` asks the kernel for a free port; the CLI prints the
working bootstrap URL as `bootstrap: http://127.0.0.1:<port>/`.

The HTTP server keeps jobs in process memory: an import/analysis/separation runs
in a thread, streams progress over SSE, and is cancellable through
`POST /api/jobs/{id}/cancel`. There is no external queue and no database.

## Data root

`BASSEPARATE_DATA_DIR` or `--data-root` selects one directory (default: the
platform per-user data directory). Everything the server owns lives below it:

```
<data-root>/
  projects/<project_id>.json           one atomic, revisioned project document
  projects/.locks/<project_id>.lock    per-project advisory lock for writers
  assets/<asset_id>/
    asset.json                         probe, content hash, peaks summary
    source.<ext>                       untouched copy of the imported file
    pcm.f32                            interleaved float32 at the project rate
    peaks-256.bin, peaks-1024.bin, peaks-4096.bin, peaks-16384.bin
  analysis/<cache-key>/                beats.json key.json chords.json meta.json
  stems/<cache-key>/                   <label>.f32 per active model + stems.json
  exports/<project_id>/<export-id>.wav
  uploads/                             per-upload staging, removed after import
  tmp/                                 temporary server files
```

An asset id is `sha256(source)[:16]-<project-rate>-<channels>`; a project id is
a UUID hex string matching `^[A-Za-z0-9_-]{1,64}$`. Identical source bytes at the
same project settings share one asset directory.

## Project document (the API and autosave model)

`projects/<id>.json` stores media facts plus the practice document. The media
side is fixed at import; the document is versioned and autosaved:

```jsonc
{
  "schema_version": 1,
  "id": "<uuid>", "name": "...", "created_at": "...", "updated_at": "...",
  "revision": 7,
  "audio": {
    "asset_id": "...", "sample_rate": 48000, "channels": 2, "frames": 960000,
    "duration_seconds": 20.0, "source_name": "...", "source_format": "wav",
    "content_sha256": "...", "codec": "pcm_s16le",
    "peaks": { "256": {"bucket_size": 256, "count": 3750, ...} }
  },
  "document": {
    "state_version": 1,
    "sections": [{"id": "section-1", "name": "Section 1", "start_bar": 2, "end_bar": 4}],
    "loop": {"start_frame": 96000, "end_frame": 192000, "repeat_count": null, "fade": true},
    "speed": 1.0, "pitch_semitones": 0, "position_frame": 0,
    "mixer": {"mix": {"gain": 1.0, "muted": true, "solo": false, "pan": 0}},
    "key": "C major",
    "grid": {"bpb": 4, "bpm": 120.246, "meter": {"numerator": 4, "denominator": 4},
             "offsetSeconds": 0.011604, "beats": [0.011604, ...], "bars": [0.011604, ...]},
    "chords": [{"start_seconds": 0.17, "end_seconds": 7.98, "label": "C"}],
    "analysis": {"schema_version": 1, "cache_key": "<sha>", "bpm": 120.246,
                 "key": "C major", "cached": false, "sample_rate": 48000,
                 "duration_seconds": 16.0, "bpb": 4, "lead_in_seconds": 0,
                 "elapsed_seconds": 1.9, "source_sha256": "<sha>",
                 "plugins": [{"role": "Chordino", "display_name": "Chordino", "version": "2"}]},
    "stems": [{"label": "bass", "frames": 960000, "channels": 2,
               "sample_rate": 48000, "url": "/api/projects/<id>/stems/bass/pcm"}],
    "stemCacheKey": "<sha>"
  }
}
```

Sections are stored in **bar numbers**, because they are manual, bar-snapped
edits; loops are stored in **project frames**, because playback is frame-exact.
The UI converts bars to seconds through the analysed grid for the lane, and
seconds to frames for the transport.

Writes are atomic (`mkstemp` + `fsync` + `os.replace`) and serialised per
project with `fcntl.flock`. `PUT /api/projects/{id}/state` and the project
update route accept an optional `revision`; a mismatch is `409`, so a stale
autosave never overwrites a newer analysis or edit. Unknown document keys are
preserved. A future `state_version` is rejected with a readable error; a
document without the marker is migrated additively.

## Time model

There are three coordinate systems; mixing them is the main source of bugs this
codebase guards against:

| Coordinate | Unit | Where |
| --- | --- | --- |
| Source/project frame | integer sample at the project rate | project JSON, PCM ranges, loops, playback |
| Seconds | float | analysis beats/bars/chords, UI ruler, section editor |
| Stream frame | integer sample at the output rate | the AudioWorklet's consumed stream, which may be faster (0.5x) or slower (1.5x) than project frames |

- The project rate is the imported file's rate unless an import call passes an
  explicit `sample_rate` (supported 44.1/48/88.2/96 kHz; input accepted from
  8 kHz to 384 kHz).
- Imported audio is decoded once to interleaved `f32le` at the project rate;
  all playback, analysis, separation and export work from that canonical file.
- Analysis returns beat/bar/chord times in seconds. `beats[0]` is the grid
  offset. `bpm` is derived as `60 / median(positive beat intervals)`.
- Playback positions are project frames. The worklet reports `(stream frame,
  context time, rate)` anchors; the transport extrapolates with the audio clock
  and maps loop stream coordinates back to project frames. A seek bumps a
  generation, and the fetch layer rejects chunks from older generations.
- At 0.5x/1.5x the transport consumes more/less source audio per wall-clock
  second; the metronome and count-in are scheduled in stream frames through the
  loop mapping so they follow the performance.
- Export renders exactly `audio.frames` frames at `audio.sample_rate`.

## Playback path

1. `main.tsx` builds the shell API, the analysis job client and one
   `createStudioPlayer` runtime, then renders `App` with them.
2. `studio-player.ts` loads `mix` plus `drums/bass/other/vocals` as one aligned
   group (same rate and frame count). The canonical mix is muted by default when
   stems exist, so the same performance is not heard twice. A missing stem set
   falls back to the mix with the notice `Stems unavailable; playing the mix.`
3. `transport.ts` fetches ranged PCM for each channel with HTTP
   `Range: bytes=<start>-<end>`; the server answers `206 Partial Content` with
   `Content-Range` and `Accept-Ranges: bytes` (range requests outside the asset
   are `416`). The transport writes into a shared ring when
   `crossOriginIsolated` is true and uses transferable chunks otherwise. `mix-processor.js` (an AudioWorklet module plus the
   committed Signalsmith WASM) mixes sources with per-source gain/pan/mute/solo,
   applies rate/pitch through the stretcher, renders clicks and emits anchors.
4. The UI maps the engine's seven transport states onto the shell's player
   states: unloaded→idle, loading/seeking/buffering→loading, playing/paused/error
   unchanged, ended only after a natural end at duration (never during a seek,
   buffering or an active loop).
5. Mixer changes are posted as per-source parameters and ramp over 5 ms; they
   never seek or restart playback.

The scalar WASM artifact is fetched from `web/src/player/stretch/dist/` and is
committed with its build manifest and export map (`stretch/BUILD.md`). The
spectrogram uses a hand-written radix-2 FFT (Hann 2048) in
`spectrogram.worker.ts`; its PCM loads only when the pane is expanded, with a
bounded LRU cache keyed by `(start, width, FFT)`.

## Caching

| Cache | Key | Publication | Invalidation |
| --- | --- | --- | --- |
| Waveform peaks | asset id + fixed bucket sizes | written during import | new import of different bytes creates a new asset |
| Analysis | SHA-256 over source bytes + actual rate + bpb + lead-in + ordered plugin display names/parameters + `ANALYSIS_VERSION` | four JSON files written in a private dir, then one `rename` | key changes when any input changes; corrupt entries read as a miss and are replaced |
| Stems | v2 SHA-256 over decoded PCM, rate, channels, window/overlap/shifts, model id, ordered labels and the declared weight/config hashes | worker writes a staging dir, validated, then renamed | same; `force` re-runs and replaces; v1 Demucs-only cache entries remain readable |
| Browser spectrogram | start/width/FFT | LRU in the worker client | bounded cache, no persistence |

Cached analysis directories also record plugin names, keys, versions, framing
and elapsed time in `meta.json`. **The cache key does not include plugin
versions**: the offline pack is frozen, so a version bump requires raising
`ANALYSIS_VERSION` in `features.py` to avoid stale reuse. Stems record the
checkpoint manifest hash in the key, so a model change is a cache miss.

## Analysis pipeline

`POST /api/jobs {"kind":"analysis","params":{"project_id":..., "bpb":4}}`
enqueues a job. The worker reads the project's canonical PCM (mono downmix, no
re-decode), decodes short clips with a 2 s silent lead/tail, then starts three
Piper sessions in parallel: Chordino, Key Detector and Bar and Beat Tracker.
Each plugin keeps its preferred block framing; raw features are parsed into
beats, bars, key label/tonic/mode and raw chord regions. A successful job
publishes the cache entry and merges `grid`, `key`, `chords` and `analysis` into
the project document with a revision-checked retry. Cancellation kills all
children and publishes nothing.

## Separation pipeline

`POST /api/separate {"project_id":..., "model_id": "htdemucs_ft", "device":"auto"}`
enqueues a `separate` job. The route resolves `model_id` through the registry
and requires the model to be installed before queueing; a missing or unknown
model is a 400 with an install/known-id message. `stems.py` builds a v2
content-addressed key and dispatches by engine:

- **demucs** (default): `analysis/.venv/bin/python analysis/separate_track.py`
  verifies the four `htdemucs_ft` checkpoints against
  `analysis/checkpoints.json` *before* importing torch, converts project PCM to
  44.1 kHz stereo, runs windowed `apply_model` (120 s windows, 8 s overlap,
  `shifts=0`, OOM ladder 7.5/5/3 s), resamples back and trims/pads every stem.
- **msst** (SCNet XL IHF, BS-RoFormer-SW): `analysis-models/.venv/bin/python
  analysis/separate_msst.py --model-id …` validates the requested instruments
  exactly against `analysis/models.json`, loads the model through MSST, forces
  CPU when CUDA is unavailable, then resamples and trims/pads each label. The
  worker writes atomic float32 stems plus `meta.json` with model, labels, device,
  elapsed time and peak RSS.

Both children run with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`HF_DATASETS_OFFLINE=1` and `PYTHONNOUSERSITE=1`, and stream JSONL stage
progress. Cancellation writes a cancel flag/SIGTERM, waits a grace period and
kills the child; no partial stem directory is published and the previous
project revision is kept. A successful job publishes the cache entry and merges
`stems` and `stemModel` into the project. CPU-only on this machine (see
limitations).

## Separation models

`analysis/models.json` is the stdlib-only registry: id, display name, engine,
engine command, ordered stem labels, sample rate, exact install size, pinned
HTTPS source and licence, and per-file size/SHA-256 pins. `model_registry.py`
reports `installed`, `missing` or `hash-mismatch` per file without importing
torch; `doctor` and `/api/doctor` expose the same states.

`scripts/models.py list|verify|install` backs `make models-list`,
`models-verify` and `models-install ID=<id>` (or `make models-install <id>`).
`list`/`verify` never touch the network. `install` downloads each pinned file to
a `.part` staging path, checks size and SHA-256, publishes it atomically inside
a staging model directory, swaps the whole directory into place and re-verifies;
a failure leaves the previous directory or nothing. Model weights stay under
the untracked `models/` tree and are never committed.

The optional models inference environment is isolated in `analysis-models/`
(Python 3.11, `torch==2.9.1` from the cu128 index, `msst[bs-roformer]==0.1.0`,
committed `uv.lock`). `make models-env` runs `uv sync --offline --directory
analysis-models` against the preserved `storage/tmp-uv-cache`; the application
environment never imports torch or MSST, and a missing/broken environment is
reported by the failed job with the worker stderr tail.

Default `htdemucs_ft` is bundled. `scnet-xl-ihf` (4 labels) installs 204.2 MiB;
`bs-roformer-sw` (6 labels: bass, drums, other, vocals, guitar, piano) installs
667.0 MiB. Measured CPU on the 8 s stereo fixture: Demucs 19.24 s,
SCNet 58.20 s (3.9 GiB peak RSS), BS-RoFormer 67.35 s (3.0 GiB peak RSS);
linear 60 s estimates are about 7.3 and 8.4 minutes. Licences are recorded in
[../licenses/NOTICES.md](../licenses/NOTICES.md).

## API surface

The server exposes its own OpenAPI document at `/api/openapi.json` and an
interactive page at `/api/docs`; [api.md](api.md) summarises the routes. The UI
is mounted at `/` from `web/dist`; without a build it serves an explanatory
placeholder page.

## Verification

The local gate and acceptance runs used for this document are recorded in
[progress.md](progress.md) and [acceptance/report.md](acceptance/report.md):
`make gate` (lint/format/types/fixtures/models verify, 299 backend tests with
8 skipped, 53 web test files / 524 tests, production build, two-browser golden
path with two specs) and
`make accept` (five recordings; the committed report records 5/5 analysed,
1103.98 s of audio and the per-file wall times of that run). The e2e suite runs
the real FastAPI server with an isolated temporary data root per run; in the
final run both Firefox and Chromium advanced the transport, changed speed,
wrapped the section loop and completed the export.
