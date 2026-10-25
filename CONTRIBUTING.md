# Contributing to basseparate

basseparate is a private, unpublished project. This file records the working
agreements for implementation sessions.

## Ground rules

1. `GOALS.md` defines the product outcome. `requirements/` holds the
   archived milestone requirements; `EXECUTION_PLAN.md` controls the current
   order and acceptance evidence. Do not treat historical work-package plans
   as current.
2. `docs/implementation-status.md` is the persistent resume point. Update it
   at slice boundaries and whenever a quality gate changes.
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
7. Tests must prove behavior at the user boundary. A green unit suite does
   not close a slice; the golden-path and quality evidence in
   `EXECUTION_PLAN.md` must also pass.
8. No network access at runtime. Only `dev.py setup` and explicit
   model/download operations may use the network.
9. A new dependency needs a measured benefit, licence/size/offline review, and
   explicit approval. Prefer existing project modules and established
   libraries over new custom DSP.

## Verification before declaring work done

```sh
uv run --locked python scripts/dev.py check
uv run --locked python scripts/dev.py test
```

plus the golden-path/quality evidence for the current slice (see
`EXECUTION_PLAN.md` and `docs/quality-baseline.md`).
