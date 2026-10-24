# basseparate architecture (Milestones 0-2)

This document describes the architecture as implemented. It is updated as
later milestones extend it. The authoritative product specification is
`basseparate_project_plan.md`; the resume ledger is
`docs/implementation-status.md`.

## Process structure

1. **Launcher** (`basseparate` CLI): parses configuration, verifies frontend
   assets, acquires the storage-root instance lock, binds the loopback socket,
   starts the backend, opens one browser tab, and handles shutdown.
2. **Backend service**: FastAPI/Uvicorn on `127.0.0.1:8765`. Owns
   configuration, SQLite working storage and repositories, the job manager
   (two priority queues), the HTTP API, and the built frontend, all on one
   origin.
3. **Media worker**: one long-lived subprocess started with the job manager
   (`sys.executable -m basseparate.worker.media_worker`) speaking
   newline-delimited JSON over stdio (protocol version 2). It runs probe,
   canonical decode, monitoring downmix, playback-rate resampling, waveform
   pyramid builds, and WAV export. It never touches the database.
4. **Analysis worker**: a separate subprocess started on demand for
   separation jobs as `analysis/.venv/bin/python analysis/worker.py`, using
   the same protocol. It runs the Demucs `htdemucs_ft` pipeline through
   `analysis/separate.py` and is stopped when the analysis queue is idle. The
   application environment never imports torch.
5. **Browser**: React/TypeScript. Talks to the API through a generated client
   (openapi-fetch over generated types). Waveform rendering is canvas-based.
   Playback runs in an AudioWorklet: a fetch worker produces PCM into shared
   memory when cross-origin isolation permits `SharedArrayBuffer`, otherwise
   into transferable chunks. Signalsmith Stretch runs as a WASM worklet for
   0.25x to 2x playback rates. No analysis code runs in the browser.

Job classes are durable. Media jobs (probe, decode, downmix, playback rate,
waveform, export) are scheduled separately from separation analysis jobs, so
a long separation cannot block playback preparation. Publishers run before a
job is marked complete, so a completed job always has its references
committed. On startup, jobs left running are marked `interrupted`.

## Contracts

Pydantic models in `src/basseparate/domain/` are the single source of truth.
Generated artifacts:

- `contracts/openapi.json` — HTTP API contract (47 routes as of M2.21).
- `contracts/project.schema.json`, `contracts/asset.schema.json`,
  `contracts/worker.schema.json` — JSON Schemas.
- `frontend/src/api/schema.ts` — TypeScript types (openapi-typescript).

Regenerate with `scripts/dev.py contracts`; verify drift with
`scripts/dev.py contracts --check` (or `scripts/check_contract.py`).
Generated files are never hand-edited.

## Time representation

Authoritative project time is integer source sample frames at the decoded
source sample rate, with half-open intervals `[start_sample, end_sample)`.
Seconds are derived for display. Model frame rates, playback-rate
representations, and stream positions are derived coordinate systems. An
empty project has no sample rate until a source is imported. Stretch and loop
transport keep explicit mappings between project frames and the unbounded
stream coordinate.

## Storage

- Working database: SQLite (stdlib `sqlite3`), WAL mode, `synchronous=FULL`,
  schema version in `PRAGMA user_version`, ordered transactional migrations
  (current `DATABASE_SCHEMA_VERSION` is 12; project schema version 4).
- Directories via platformdirs (XDG): config, data, cache, state, runtime.
  `--storage-root` overrides the root for tests and portable development.
  Data and runtime directories are owner-only.
- Assets are stored relative to managed storage; absolute paths and `..`
  traversal are rejected; containment is verified before access.
- Audio assets are content-addressed (`data/assets/<sha256>.pcm`), with a
  content hash plus a transformation-key identity. Decoded PCM is f32le;
  monitoring and playback representations are separate derived assets.
- Waveform pyramids live in `cache/waveforms/<source_hash>/` as an atomic
  manifest plus progressive 4096-bucket tiles; the on-disk manifest is the
  source of truth for tile availability.
- Separation requests are cached by a deterministic versioned key. Results
  are immutable stem assets plus a result-set row; reruns retain earlier sets
  and an undoable command selects the active set. A configurable storage
  policy (default 50 GiB) reports reclaimable space and supports pinning and
  explicit LRU reclaim without deleting records.
- Portable projects are ZIP64 archives under
  `data/portable/<project_id>/<revision>-<sha12>.basseparate`, built from a
  project-only database and dependency closure, verified member by member,
  then published atomically; one previous archive is retained.
- Staging for workers lives under `runtime/`; export and portable builds use
  the same staged, verify-then-rename discipline.

## Security

- Loopback-only binding (`127.0.0.1`); the bind address is not configurable
  to a LAN address.
- Per-session random bearer token (at least 256 bits) created at startup,
  delivered in the browser URL fragment, moved to `sessionStorage`, sent only
  in the `Authorization` header.
- Host and Origin validation; no wildcard CORS; conservative rate limiting on
  failed authentication; minimal unauthenticated health route.
- Static responses carry CSP and related hardening headers, including COOP
  and COEP for cross-origin isolation.
- No network access at runtime. Only explicit setup and model-install
  operations may use the network.

## WebAssembly boundary

Time stretching uses Signalsmith Stretch compiled to WebAssembly with
Emscripten. Two committed variants (`stretch-scalar.wasm` and
`stretch-simd.wasm`) are selected at runtime; the pinned toolchain
(emsdk 4.0.23), source commits, profile, and fixed WASM memory are recorded
in `frontend/src/playback/stretch/` (`BUILD.md`, `stretch-profile.ts`). The
audio callback never grows the WASM heap.

## Models and inference

- The bundled Demucs baseline is `htdemucs_ft`: four 84,141,271-byte
  checkpoints plus the 149-byte preset YAML, 336,565,233 bytes in total.
  Hashes, sizes, upstream URLs, provenance, and the weight-license notice are
  checked in at `src/basseparate/models/registry.py`.
- The development bundle lives in the gitignored `models/htdemucs_ft`; a
  release copy is provisioned separately. The runner verifies every artifact
  before loading and sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`
  before importing torch.
- Inference runs only in the isolated `analysis/.venv`
  (Python 3.11.15, demucs 4.1.0, torch 2.9.1+cu128, soundfile 0.14.0). Device
  choice uses stable GPU identity (UUID) with an explicit `cpu` fallback;
  windowed inference bounds memory on long tracks.
