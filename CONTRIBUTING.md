# Contributing to basseparate

basseparate is a private, unpublished project. This file records the working
agreements for implementation sessions.

## Ground rules

1. The design documents in `projectPlans/` (and the top-level
   `basseparate_project_plan.md`) are the authoritative specification.
   Implement the earliest incomplete milestone; do not pull later milestones'
   features forward.
2. `docs/implementation-status.md` is the persistent resume ledger. Update it
   before ending a session and at every milestone gate.
3. User-supplied recordings in `audio2test/` are never modified, deleted, or
   committed. Their SHA-256 baseline is in `docs/evidence/m0-file-baseline.md`.
4. The service binds loopback only. Never add LAN-facing endpoints or
   permissive CORS.
5. Dependencies change only through deliberate, locked updates:
   - Python: edit `pyproject.toml`, then `uv lock`, then `uv sync --locked`.
   - Frontend: edit `frontend/package.json`, then `pnpm install --frozen-lockfile`
     must still pass after a deliberate `pnpm install` to update the lock.
6. Generated artifacts (`contracts/openapi.json`, `frontend/src/api/schema.ts`,
   `licenses/components.json`) are regenerated with `scripts/dev.py contracts`
   / `scripts/dev.py licenses`, never hand-edited.
7. Tests must prove behavior. Do not weaken a test to make it pass; fix the
   implementation.
8. No network access at runtime. Only `dev.py setup` and explicit
   model/download operations may use the network.

## Verification before declaring work done

```sh
uv run --locked python scripts/dev.py check
uv run --locked python scripts/dev.py test
```

plus the milestone's gate-specific evidence (see `projectPlans/milestoneN.md`).
