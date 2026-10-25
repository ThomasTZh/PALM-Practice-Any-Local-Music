# Implementation status — rebaselined

Date: 2026-10-25. This is the current resume point. The previous 4,910-line
milestone ledger is archived at
[`archive/implementation-status-2026-10-24.md`](archive/implementation-status-2026-10-24.md);
it is history, not a plan.

## Position

- Product goals: [`GOALS.md`](../GOALS.md).
- Requirements: [`requirements/`](../requirements/README.md) (archived
  milestone specs; old work-package plans under `requirements/archive/`).
- Execution order and gates: [`EXECUTION_PLAN.md`](../EXECUTION_PLAN.md).
- Current slice: **Slice 0 — re-baseline and golden path**.
- No new editor UI until the quality gates in `docs/quality-baseline.md`
  pass or an exception is recorded.

## What is currently reliable

- Import, canonical decode, waveform, playback, monitoring, export.
- Demucs separation and portable project save/open for M2 workflows.
- Durable jobs, restart recovery, migrations, generated contracts.
- Rhythm domain, activation artifacts, decoded pulses, branches, grids,
  metronome/count-in plumbing, portable rhythm rows.

These are retained. A measured failure in one subsystem does not justify
rewriting the foundation.

## Slice-0 evidence

- `frontend/e2e/golden-path.spec.ts` passes on Firefox: import → ready →
  Analyze Rhythm → 4/4 bars → rendered metronome clicks → musical loop →
  count-in setting → portable save.
- `tests/unit/test_rhythm_corpus.py` + `test_rhythm_evaluation.py`: 37 pass.
- Real final0 synthetic fixture: beat F1 **0.952**; downbeat F1 **0.462**
  on simple synthetic accents.
- Vamp reference on a real 20 s Carousel excerpt: **45/46 beats within
  50 ms** and **11/11 bars within 100 ms** against the QM tracker. This
  points to meter/grid construction, not beat detection, as the failure.
- Meter re-inference on the retained 4/4 track now selects 4/4; this needs a
  five-excerpt automated gate.
- Rendered-click timing on a 4/4 fixture has shown ±20–40 ms jitter and an
  occasional dropped beat; the timing gate is not yet automated or met.

Full detail: [`quality-baseline.md`](quality-baseline.md).

## Keep / adapt / replace

| Subsystem | Decision |
|---|---|
| Storage, jobs, media, import, portable, transport, semantic domain | Keep |
| Beat This! runtime and beat decoding | Keep |
| Downbeat postprocessing | Adapt (quality gate fails) |
| Meter scoring | Keep after correction; retest on corpus |
| Tempo map / metronome scheduling | Adapt (timing gate fails) |
| Editor lanes | Defer until quality gates pass |

## Verification commands

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/basseparate
.venv/bin/python scripts/check_contract.py
cd frontend && npx vitest run && npx tsc -b --force
cd frontend && npm run format:check && npm run build
cd frontend && npm run e2e:golden
```

The last full backend count before this rebaseline was 1,686 passed, 1
skipped; the frontend suite was 617 passed across 51 files. Re-run both after
any code change rather than trusting these numbers.

## Known limitations

- Downbeat quality on synthetic accents is below the planned gate.
- Metronome clicks can jitter or drop; timing gate pending.
- 4/4 meter was misread as 7/8 before the correction; retest on all five
  recordings.
- Editor lanes are read-only; correction workflow is slice 4 and is blocked
  on quality.
- Separation has no first-class UI path in the current frontend; do not
  assume it during acceptance.
- Portable archives are schema-version coupled; pre-M3.18 archives need the
  matching build.
- Chromium/Safari and mobile are deferred; Firefox/Linux is the target.

## Next action

Slice 1 only: close the downbeat and metronome timing gates on ordinary 4/4
material, add the five-excerpt 4/4 selection check, and rerun the golden path.
Do not add UI before that.
