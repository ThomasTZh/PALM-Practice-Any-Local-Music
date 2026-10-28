# basseparate execution plan

This is the current local practice-studio plan. Product goals:
`GOALS.md`. Requirements: `requirements/`. Resume point:
`docs/implementation-status.md`.

## Operating rules

1. Vertical slices with a checkable user outcome.
2. The Firefox golden path stays green.
3. Reuse mature tools; do not rebuild Vamp beat tracking or Demucs.
4. One decision lives in one place.
5. No new dependency without a licence/size/offline/measured-benefit review.
6. Record keep/adapt/replace decisions from measurements, not test counts.

## Fixed architecture

- Browser React/TypeScript frontend; no Qt/Sonic Visualiser fork.
- Local files only; no YouTube, cloud, accounts, or mobile in this scope.
- Demucs for stems through the existing durable job/result-set system.
- **QM Vamp Bar and Beat Tracker is the default grid engine.** The native
  host is preferred; the Piper JSON host is a fallback.
- `bpb` is a manual beats-per-bar hint (2/3/4/6/7; default 4). No automatic
  meter inference in this slice.
- Song Map sections live in `PracticeState`; linked section loops use the
  optional `PracticeLoop.section_id`.
- Beat This! remains experimental and is not required by the golden path.

## Progress

| Slice | Status | Evidence |
|---|---|---|
| 0. Re-baseline, goals, requirements, golden path | **done** | goals/plan/quality baseline; Firefox path |
| 1. Song Map sections, commands, persistence | **done** | section domain/commands tests; undo/redo; non-overlap |
| 2. Vamp host/parser/branch/API/cache | **done** | fixture/grid/service/route tests; real native host test; 294 s analysis |
| 3. Vamp analysis UI | **done** | `SongAnalysisPanel`; Firefox path shows 4/4 |
| 4. Song Map UI and section loops | **done core** | lane/list; add/split/rename/delete/loop; E2E section + loop |
| 5. Stem separation UI | **done** | real 8 s CPU Demucs browser run, four-track mixer, 1.1 min |
| 6. Hardening and five-recording acceptance | **in progress** | real stem run, portable sections, docs, manual listening |

## Reuse map

| Need | Use | Notes |
|---|---|---|
| Beat/bar/tempo | QM Vamp plugins via native host | Primary; reference-matched |
| Stem separation | Demucs in `analysis/.venv` | Existing accepted backend |
| Playback/stretch | Existing AudioWorklet + Signalsmith | Keep |
| Waveform/editor | Existing React/canvas editor | Keep |
| Jobs/storage/portable | Existing FastAPI/SQLite modules | Keep |
| Metrics/reference | `scripts/vamp_reference.py`, QM/Sonic Visualiser | Evaluation only |
| Beat This! | `rhythm/.venv` | Experimental comparison; not default |

## Slice details and remaining acceptance

### Slice 1 — sections

Done:

- `SongSection` and `PracticeState.sections/active_section_id`.
- Non-overlap, ordering, duration and active-id validation.
- Commands: add/update/delete/split/set-active/loop-section.
- Linked loop updates; section delete clears linked active loop.
- Undo/redo.

Portable section + linked-loop round-trip test added to
`tests/integration/test_portable_open.py`.

### Slice 2 — Vamp

Done:

- `VampAnalysis` parser and monotonic validation.
- `build_branch_from_vamp` creates a valid 4/4 branch with tempo anchors,
  downbeats, and meter region.
- Native host (fast) and Piper fallback.
- Content-addressed feature cache; per-project lock; API error mapping.
- Real native host test and 294 s user-project analysis.

Remaining: package/document the native host path; decide whether to provide
a build script for a fresh machine.

### Slice 3 — analysis UI

Done:

- `SongAnalysisPanel` with bpb selection, error/status, cache hint.
- Old Beat This panel remains unused; default doctor no longer needs its
  model for the golden path.
- Firefox path analyzes without a model.

### Slice 4 — Song Map and practice controls

Done:

- Section lane aligned to the shared view.
- Section list: add from selection, rename, color, split at playhead, delete,
  select, loop.
- Section loop uses the linked PracticeLoop; 0.75× speed verified.
- Arbitrary range loop still available.

Remaining: visual polish; optional section suggestions later.

### Slice 5 — stems

Done:

- `startSeparation`/`getMediaJob` client.
- Separation panel starts a run, polls progress, activates newest valid set,
  and switches to four stems.
- Component tests.

Real browser run passed on an 8 s tone through the panel: 1.1 min CPU,
four track rows. GPU selection and mixed/stem portable save remain.

### Slice 6 — release acceptance

Required evidence:

- Five recordings: import → stems → Vamp grid → sections → loop → speed →
  save/reopen. QM grid analysis on all five 20 s excerpts is automated;
  the audible practice review remains human.
- Portable project with sections and linked loops.
- Golden path green on the release commit.
- Backend/frontend/type/lint/format/contract gates.
- Known limitations documented.

## Verification

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/basseparate
.venv/bin/python scripts/check_contract.py
cd frontend && npm test -- --run
cd frontend && npm run format:check && npm run build
cd frontend && npm run e2e:golden
```

## Next action

Run a real Demucs separation through the UI, then add the portable section
round-trip test and complete the five-recording review.
