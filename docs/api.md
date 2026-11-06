# API reference

The studio server is a FastAPI application bound to loopback. It has no
authentication and no remote mode: every route is intended for the local UI.
The authoritative OpenAPI document is served at `/api/openapi.json`; an
interactive page is at `/api/docs`. This page describes the shipped routes and
wire formats.

## Conventions

- JSON errors are `{"detail": "message"}`. Status codes are `400` (invalid
  request, media or upload), `404` (unknown project/job/asset/stem or missing
  file), `409` (revision conflict, missing asset on reopen, existing project),
  `416` (PCM byte/range outside the asset) and `422` (FastAPI shape
  validation).
- Project ids match `^[A-Za-z0-9_-]{1,64}$`. Asset ids match
  `^[A-Za-z0-9_-]{1,80}$`.
- Times in JSON are seconds unless a field name ends in `_frame`/`Frame`; PCM
  and loop positions are frame indices at the project rate.
- Binary PCM is **interleaved little-endian float32** (`f32le`), no header.
  Frame ranges are `[start, end)` and `end` defaults to the total frame count.
- Lists are deterministic: projects and library entries are sorted by id/title
  by the store; jobs are in creation order.

## Meta

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `{status, version, data_root, ui}`; `ui` is true when `web/dist/index.html` exists |
| GET | `/api/capabilities` | — | `{sample_rates, default_sample_rate, peak_bucket_sizes, max_upload_bytes, channels, pcm_format}` |
| GET | `/api/doctor` | — | `{status: "ok"\|"degraded", ok, missing, checks: [{id, label, status: "ok"\|"missing", detail, required, path}]}` |
| GET | `/doctor` | — | same doctor payload, operator-friendly alias |
| GET | `/api/openapi.json` | — | OpenAPI 3 document |
| GET | `/api/docs` | — | Swagger UI |

`/api/doctor` is read-only: it probes the local toolchain, data root, model
bundle, Vamp assets, Piper and GPU without network access.

## Library and imports

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/library` | — | `{entries: [{id, title, durationSeconds, sampleRate, channels, importedAt, projectId}]}` |
| POST | `/api/imports` | JSON `{path, name?, sample_rate?}`; `path` must be an absolute existing file | `201` project payload |
| POST | `/api/imports/jobs` | JSON `{path, name?, sample_rate?}` | `202` job payload; result is the project |
| POST | `/api/imports/upload` | multipart field `file`; query `name?`, `sample_rate?` | `201` project payload |
| POST | `/api/library/import` | multipart field `file`; query or form `name?`, `sample_rate?` | `201` `{entry, project}` |

`sample_rate` (query or form) is an integer from 8000 to 384000; the project
rate becomes that value, otherwise the source rate is kept. Import copies the
source into the asset directory, decodes it once to `pcm.f32` at the project
rate, and writes peaks for every supported bucket. Uploads are staged under
`uploads/` and removed when the request finishes.

## Projects and media

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/projects` | — | `{projects: [project]}` |
| GET | `/api/projects/{id}` | — | project payload |
| PUT | `/api/projects/{id}` | JSON `{document?, name?, revision?}` | project payload; `409` on stale revision |
| GET | `/api/projects/{id}/media` | — | the `audio` object: rate, channels, frames, duration, hash, peaks summary |
| GET | `/api/projects/{id}/pcm` | query `start=0`, `end=<frames>`, or HTTP `Range: bytes=<start>-<end>` | interleaved `f32le`; `206` + `Content-Range` for a byte range, `200` for the whole asset, `416` outside it |
| GET | `/api/projects/{id}/peaks/{bucket_size}` | `bucket_size` ∈ {256,1024,4096,16384} | BSPK bytes; `400` for other bucket sizes |
| GET | `/api/assets/{asset_id}` | — | `asset.json` (probe, hash, peaks summary) |
| GET | `/api/assets/{asset_id}/peaks` | query `buckets=1024` | BSPK bytes |

The project payload is the stored JSON plus UI aliases: `title`,
`durationSeconds`, `asset`, `grid`, `key`, `stems`. A project with no analysis
has `grid: null`, `key: null` and an empty `document`.

### Binary formats

PCM responses carry:

```
content-type: application/octet-stream
accept-ranges: bytes
x-frame-start, x-frame-end, x-frame-count,
x-sample-rate, x-channels, x-total-frames
cache-control: private, max-age=3600
```

A `Range: bytes=<first>-<last>` request (inclusive, as HTTP defines it) returns
`206` with `content-range: bytes <first>-<last>/<total>` and the same frame
headers; an unsatisfiable range is `416`. Frame-range query parameters and byte
ranges describe the same interleaved stream; clients may use either.

Peaks use the BSPK container documented in `src/basseparate/peaks.py`:

```
0..3 "BSPK"   4 u8 version=1   5 u8 channels   6..7 u16 reserved
8..11 u32 sample rate  12..15 u32 bucket count  16..19 u32 samples/bucket
then per bucket, per channel: int16 min, int16 max (normalised by 32767)
```

## Practice state, reopen and export

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/projects/{id}/state` | — | `{state, assets: {ok, missing}}`; `400` when the document cannot be read |
| PUT | `/api/projects/{id}/state` | JSON `{state, revision?}`; `state` is `PracticeState` | `{project, state}`; `409` on revision conflict |
| GET | `/api/projects/{id}/reopen` | — | `{project, state, assets: {ok, missing}}`; `409` when the source asset is missing |
| POST | `/api/projects/{id}/exports` | JSON `{mixer?, filename?}` | `201` `{id, project_id, filename, display_name, download_url, frames, sample_rate, channels, bytes, sha256, layers}` |
| GET | `/api/projects/{id}/exports/{export_id}.wav` | — | the WAV file; `404` for unknown ids |

`PracticeState` (also the `state` object) is versioned:

```jsonc
{
  "state_version": 1,
  "sections": [{"id": "section-1", "name": "Section 1", "start_bar": 1, "end_bar": 3, "color": null}],
  "loop": {"start_frame": 96000, "end_frame": 192000, "repeat_count": null, "fade": true},
  "speed": 1.0,
  "pitch_semitones": 0,
  "position_frame": 0,
  "analysis": {"cache_key": "...", "source_sha256": "...", "sample_rate": 48000, "bpm": 120.2, "key": "C major"},
  "mixer": {"bass": {"gain": 1.0, "muted": false, "solo": false, "pan": 0.0}}
}
```

Speed is clamped to 0.25–2.0 and pitch to −12…+12 semitones. Sections are bar
ranges; loops are project frames. Saving rejects a state version newer than the
server supports and preserves unknown document keys.

The export mixer accepts either `stems` or `channels` maps (both are merged;
`stems` wins) with `{gain, muted|mute, solo, pan}` and a top-level
`master_gain`. The output is 16-bit PCM WAV at the project rate with exactly
`audio.frames` frames; disabled/soloed channels are honoured. The SHA-256 in
the response is the hash of the written file.

## First-run setup

The setup routes manage the downloads required by the packaged app. They are
described in plain language in [portable.md](portable.md); the HTTP contract is:

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/setup/status` | — | `{mode, ready, skipped, skip, requires_model_choice, roots, checks, tools, environments, models, registry_error, readiness, setup_complete, state}` |
| POST | `/api/setup/tools` | `{accept_licenses: true, force?}` | `202` setup job; `400` without consent |
| POST | `/api/setup/environments` | `{variant?: "cpu"\|"cuda", variants?: [...], accept_licenses: true, offline?}` | `202` setup job; `400` without consent |
| POST | `/api/setup/models` | `{model_id? / model_ids?, accepted_model_ids: [...], accept_licenses: true, force?}` | `202` setup job; `400` for missing per-model consent or unknown id |
| POST | `/api/setup/skip` | `{skip: true}` | updated setup status |

`status.checks` contains `glibc`, `disk` (free/required bytes; 5 GiB required)
and `ffmpeg`; `tools` contains Sonic Visualiser/Piper and Vamp pack states with
licences; `environments` contains `cpu` and `cuda` paths; `models` contains the
same equal model states as `/api/separation/models`; `readiness` exposes the
individual booleans and `requires_model_choice`. The setup downloads are
ordinary jobs (`setup_tools`, `setup_environments`, `setup_models`) visible at
`/api/jobs/{id}` and streamed at `/api/jobs/{id}/events`.

The setup routes never start a download without explicit consent. Model
downloads use `.part` files under `<data-root>/cache/model-parts/<id>/`, verify
the pinned size and SHA-256, and publish atomically; cancellation removes
staging and keeps resumable parts for retry. Environment creation runs the
bundled `uv` with `UV_PROJECT_ENVIRONMENT` below the data root and cleans its
staging directory on failure/cancel.

## Separation models

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/separation/models` | — | `{default: "htdemucs_ft", models: [model]}`; offline registry state plus install metadata |

Each model entry carries the registry fields (`id`, `name`, `engine`,
`engine_command`, ordered `labels`/`stem_labels`, `sample_rate`, `size_bytes`
and `size`, `source_url`, `license`, `bundled`, `install_dir`,
`install_command`, declared `files` with size/SHA-256), the verified state
(`status`: installed/missing/hash-mismatch, `installed`, `model_dir`, `detail`,
`file_states`), `metrics` from the measured registry (device, fixture seconds,
wall/child seconds, peak RSS) where known, and `default: true` for
`htdemucs_ft`. The response is offline; it never starts a download.

`POST /api/separate` accepts `model_id` (default `htdemucs_ft`). The server
resolves it through `analysis/models.json`, requires the model to be installed
and queues the job; unknown or missing models are `400` with the known ids or
the exact `make models-install ID=...` command. The accepted response is a job
payload plus `params`, `model_id` and the model metadata.

The labels are model-specific: `htdemucs_ft` and `scnet-xl-ihf` expose
`drums, bass, other, vocals`; `bs-roformer-sw` exposes
`bass, drums, other, vocals, guitar, piano`. A project stores the active
`stemModel`; `/projects/{id}/stems` returns `model`, `model_id` and
`active_model` (falling back to the cache metadata for older projects). Stem
PCM and peaks routes accept any label of the active set; an unknown label is
`404`.

## Jobs

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/jobs` | — | `{jobs: [job]}` |
| POST | `/api/jobs` | JSON `{kind, params}` | `202` job payload; `400` for unknown kind or invalid params |
| GET | `/api/jobs/{id}` | — | job payload; `404` when unknown |
| POST | `/api/jobs/{id}/cancel` | — | job payload after the cancel request |
| GET | `/api/jobs/{id}/events` | — | `text/event-stream` of progress/done events plus keep-alives |

Job payload:

```jsonc
{"id": "...", "kind": "analysis|separate|import", "state": "queued|running|succeeded|failed|cancelled",
 "progress": 0.0, "message": "...", "created_at": "...", "updated_at": "...",
 "result": {...} | null, "error": null | "..."}
```

SSE frames use `event: progress` while non-terminal and `event: done` for a
terminal state; the `data:` line is the job JSON, one blank line separates
events, and a comment `: keep-alive` is sent after 10 s without changes. The
stream ends after the terminal event. Closing the stream does not cancel the
job; call the cancel route explicitly.

Job contract:

| kind | params | result |
| --- | --- | --- |
| `import` | `{path, name?, sample_rate?}` | project payload |
| `analysis` | `{project_id, bpb?}`; bpb 2–16, default 4 | `{cached, bpb, bpm, key, chords, beats, bars}` where chords are `[{start_seconds, end_seconds, label}]` and beats/bars are seconds |
| `setup_tools` | `{accept_licenses: true, force?}` | tool status map |
| `setup_environments` | `{variants: ["cpu"\|"cuda"], accept_licenses: true, offline?}` | environment status map |
| `setup_models` | `{model_ids: [...], accepted_model_ids: [...], accept_licenses: true, force?}` | installed model states |
| `separate` | `{project_id, model_id, device?: "auto"\|"cpu"\|"cuda", force?: false}` | stem set payload `{key, cached, sample_rate, channels, frames, device, elapsed_seconds, model, model_id, labels, stems: [{label, frames, channels, sampleRate, key, model, model_id, path, url}]}` |

Analysis jobs also merge `grid`, `key`, `chords` and `analysis` into the
project document before they succeed. Separation jobs merge `stems`,
`stemCacheKey` and `stemModel`. Cancellation leaves the previous project
revision and cache state untouched.

## Stems

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/projects/{id}/stems` | — | `{project_id, key, model, model_id, active_model, stems: [...]}`; empty when no separation has run |
| GET | `/api/projects/{id}/stems/{label}/pcm` | query `start=0`, `end=<frames>`, or HTTP `Range`; label is any label of the active model (`drums`, `bass`, `other`, `vocals`, and `guitar`, `piano` for BS-RoFormer) | interleaved `f32le`; `206`/`Content-Range` for ranges; headers as PCM plus `x-stem-label` |
| GET | `/api/projects/{id}/stems/{label}/peaks` | query `buckets=1024`; valid bucket sizes as for mix peaks | BSPK peaks; `400` unsupported bucket, `404` unknown label or missing stem set |

Stem PCM is always stereo at the project rate and frame count; a missing cache
entry is `404` with a message naming the stem set. Export mixers accept the
active model's channel ids; the legacy four-stem shape remains accepted. The browser falls back to the
mix when a stem fetch fails.

## Static UI

`/` serves `web/dist/index.html` and its assets. Without a build it returns an
HTML placeholder explaining how to build the UI; `/api/*` stays available.
