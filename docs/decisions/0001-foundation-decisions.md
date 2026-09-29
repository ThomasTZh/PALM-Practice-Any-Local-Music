# ADR 0001 — Milestone 0 foundation decisions

Status: accepted (2026-09-29). Scope: Milestone 0 only; later milestones extend these.

## 1. Python backend, TypeScript frontend

Python 3.11 owns the service, storage, analysis workers, and contract source of
truth. TypeScript/React owns the browser. Rationale: research-model ecosystem
(PyTorch, Demucs, librosa) is Python-native; the editor is a browser app.

## 2. Local browser application with loopback service

One FastAPI/Uvicorn service binds `127.0.0.1` only and serves both the API and
the built frontend from the same origin. No LAN exposure, no permissive CORS,
per-session bearer token.

## 3. Single backend process in Milestone 0

No worker pool, no job scheduler in M0. A single process serves the API and
static assets. The probe worker (M0.9) is a supervised child used only to
validate the process boundary.

## 4. Separate future model workers

Heavy analysis runs in separate subprocesses speaking newline-delimited JSON
over stdio (protocol version 1). M0 validates this boundary with a model-free
probe worker only; scheduling/GPU assignment arrives with real jobs.

## 5. SQLite working storage

Standard-library `sqlite3`, explicit SQL, small repository layer, no ORM, no
separate DB server. WAL mode, `synchronous=FULL`, `PRAGMA user_version` for
schema versioning, transactional ordered migrations.

## 6. Python-owned contracts with generated TypeScript

Pydantic models are authoritative. OpenAPI, project/asset/worker JSON Schemas,
and TypeScript types are generated artifacts. A drift check regenerates into a
temporary directory and compares; generated files are never hand-edited.

## 7. Source-sample-based timing

Authoritative project time is integer source sample frames at the decoded
source sample rate, half-open intervals `[start, end)`. Seconds, model frame
rates, and playback speed are derived coordinate systems, never stored as the
timeline.

## 8. No network activity during ordinary startup

`serve`, project open, editing, and playback make no external requests.
Network is used only by explicit setup/install operations (`dev.py setup`,
future model installation, future YouTube retrieval). Verified by an
offline-start test in M0.12.
