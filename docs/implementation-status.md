# basseparate — implementation status ledger

Persistent resume point. A fresh agent must be able to continue from this file
plus the repository state. Keep it concise; put long evidence in `docs/evidence/`.

## Current position

- **Milestone:** 0 (Reproducible foundation)
- **Gate:** A (M0.1–M0.2)
- **Work package:** M0.1 (preservation + structure)
- **Next action:** M0.2 — create `pyproject.toml` + `uv.lock`, verify `uv sync --locked`;
  install pnpm via a supported method, scaffold `frontend/`, `pnpm-lock.yaml`,
  verify `pnpm install --frozen-lockfile`.

## Completed requirements (with evidence)

- M0.1.2/2.1: Five user WAVs hashed (SHA-256) in `docs/evidence/m0-file-baseline.md`
  (git-ignored local report). Files left in place at `audio2test/`.
- M0.1: `system-inventory.txt` untouched. Main plan moved to workspace root
  (`basseparate_project_plan.md`) to match intended top-level layout; content unchanged.
- M0.1: No repo instruction files (AGENTS.md/.agents/.codex) exist in workspace.
- M0.1: `.gitignore`, `.editorconfig`, `.python-version` (3.11.15), `.node-version` (22.22.2) created.
- M0.1: Git initialized on branch `main` (no placeholder `.git` existed; workspace writable).
  Repo-local identity set (`basseparate-dev`) because none existed.

## Remaining (Milestone 0)

- M0.2 environments + locks (Gate A) — in progress next.
- M0.3 config/paths/doctor; M0.4 schemas; M0.5 SQLite (Gate B).
- M0.6 API; M0.7 auth (Gate C).
- M0.8 browser shell + generated client (Gate D).
- M0.9 worker probe; M0.10 launcher/dev.py (Gate E).
- M0.11 docs/licenses; M0.12 verification matrix + package smoke (Gate F).

## Environment facts (re-verified 2026-09-29, not from old inventory)

- uv 0.12.0; uv-managed Python 3.11.15 installed at
  `~/.local/share/uv/python/cpython-3.11-linux-x86-64-gnu`.
- Node 22.22.2 (`/usr/bin/node`); npm present; **no pnpm, no corepack** on this system.
- ffmpeg 8.1.2 + ffprobe at `/usr/bin`.
- CPU: 16 threads; RAM ~31 GB.
- `nvidia-smi` WORKS (contrary to old inventory's failed call):
  GPU0 RTX 4080 `GPU-0dab3af3-dd8f-90ac-d715-f565c30f98f6`,
  GPU1 RTX 5060 Ti `GPU-9cccfe8d-0957-ea9b-a1ef-ae4e3a3e899d`.
  CUDA/PyTorch runtime NOT yet qualified (M2+ concern; M0 needs no GPU).
- No Emscripten on PATH (M2 concern).
- Disk: ~399 GB free on `/home`.

## Architectural decisions so far

- Python 3.11.15 via uv, `>=3.11,<3.12`, Hatchling, src layout, console script `basseparate`.
- pnpm to be installed via npm global package (no corepack on system); exact version pinned
  in root `packageManager` field. (Recorded when version resolved.)
- Git is a development aid only; generated-artifact checks must work without it (filesystem comparison).
- App storage via platformdirs (XDG), overridable with `--storage-root`.

## Commands run / results

| Command | Result |
|---|---|
| `sha256sum audio2test/*.wav` | 5 hashes recorded in baseline report |
| `uv python list --only-installed` | 3.14.7 (system), 3.13.14, 3.11.15 (uv) |
| `nvidia-smi -L` | 2 GPUs listed (see above) |
| `git init -b main` | OK |

## Known failures / blockers

- None. (pnpm absence is handled by explicit install in M0.2, not a blocker.)
