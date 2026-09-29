# basseparate architecture (Milestone 0 state)

This document describes the architecture as implemented. It is updated as
later milestones extend it. The authoritative product specification is
`basseparate_project_plan.md`.

## Process structure

1. **Launcher** (`basseparate` CLI): parses configuration, verifies frontend
   assets, acquires the storage-root instance lock, binds the loopback socket,
   starts the backend, opens one browser tab, and handles shutdown.
2. **Backend service** (single process in M0): FastAPI/Uvicorn on
   `127.0.0.1:8765`. Owns configuration, SQLite working storage, the project
   and asset repositories, and serves the built frontend and `/api/v1` from
   the same origin.
3. **Analysis workers** (M0: probe only): separate Python subprocesses
   speaking newline-delimited JSON over stdio (protocol version 1). The M0
   probe worker validates the boundary without any model. Real analysis
   workers, job persistence, and GPU scheduling arrive with the first real
   job milestone.
4. **Browser**: React/TypeScript shell. Talks to the API through a generated
   client (openapi-fetch over generated types). No analysis code runs in the
   browser.

## Contracts

Pydantic models in `src/basseparate/domain/` are the single source of truth.
Generated artifacts:

- `contracts/openapi.json` — HTTP API contract.
- `contracts/project.schema.json`, `contracts/asset.schema.json`,
  `contracts/worker.schema.json` — JSON Schemas.
- `frontend/src/api/schema.ts` — TypeScript types (openapi-typescript).

Regenerate with `scripts/dev.py contracts`; verify drift with
`scripts/dev.py contracts --check`. Generated files are never hand-edited.

## Time representation

Authoritative project time is integer source sample frames at the decoded
source sample rate, with half-open intervals `[start_sample, end_sample)`.
Seconds are derived for display; model frame rates and playback speed are
derived coordinate systems. An empty project has no sample rate until a
source is imported.

## Storage

- Working database: SQLite (stdlib `sqlite3`), WAL mode, `synchronous=FULL`,
  schema version in `PRAGMA user_version`, ordered transactional migrations.
- Directories via platformdirs (XDG): config, data, cache, state, runtime.
  `--storage-root` overrides the root for tests and portable development.
- Assets are stored relative to managed storage; absolute paths and `..`
  traversal are rejected; containment is verified before access.

## Security

- Loopback-only binding (`127.0.0.1`); the bind address is not configurable
  to a LAN address.
- Per-session random bearer token (≥256 bits) created at startup, delivered
  in the browser URL fragment, moved to `sessionStorage`, sent only in the
  `Authorization` header.
- Host and Origin validation; no wildcard CORS; conservative rate limiting on
  failed authentication; minimal unauthenticated health route.
- Static responses carry CSP and related hardening headers.

## WebAssembly boundary (planned)

Time stretching will use Signalsmith Stretch compiled to WebAssembly with
Emscripten. Milestone 0 records this boundary only: no Emscripten toolchain,
no WASM compilation, and no stretcher integration exist yet. The WASM build
starts in Milestone 2, where it can be tested against real playback
requirements, and the compiled artifact will be a pinned, versioned frontend
asset. Emscripten was not on PATH in the M0 environment (re-verified
2026-09-29).

## GPU and models (future)

Independent GPUs are independent memory pools; scheduling will use GPU UUIDs.
Milestone 0 installs no ML packages and performs no model downloads; this is
enforced by the locked dependency set and the offline-start test.
