# basseparate execution plan

This plan replaces the milestone/work-package execution order. The
requirements remain in `requirements/`; this file controls **what is built
next, in what order, and what evidence closes a slice**.

## Operating rules

1. **Vertical slices, not horizontal packages.** Every slice ends at a
   user-visible behaviour, not at a layer or a test count.
2. **The golden path stays green.** No new UI or subsystem is merged while
   the Firefox golden-path test fails.
3. **Quality before feature breadth.** Measure beat/downbeat/meter/timing
   quality before adding more editor surface. A red quality gate blocks UI
   work.
4. **Reuse before invention.** Prefer established libraries and existing
   project modules. A custom replacement needs a measured failure, not a
   preference.
5. **A slice is done only with evidence.** Unit tests alone do not close a
   slice. The evidence listed for the slice must exist and be reproducible.
6. **No new dependency without a decision.** Evaluate licence, size,
   offline behaviour, and measured benefit against the current approach.
   Installing an unplanned package requires explicit approval.
7. **Keep/adapt/replace is recorded.** The decision table below is updated
   whenever a measurement changes the verdict.

## Current baseline (2026-10-25)

- M0–M2 foundation is accepted and retained: import, media pipeline,
  transport, separation, loops, export, portable projects.
- M3 code exists but had integration and quality defects discovered by real
  Firefox/manual use: upload serialization, missing decode job, relative
  storage paths, silent/doubled metronome, slow finalizing, and wrong meter
  selection on a 4/4 track.
- The recent fixes are in place (see `docs/implementation-status.md`), but a
  fresh golden-path and quality baseline must be recorded before any new UI.
- The old milestone ledger is archived; it is history, not a resume point.

## Reuse map

| Need | Use | Notes |
|---|---|---|
| Beat/downbeat inference | Beat This! (`rhythm/.venv`, pinned checkpoints) | Keep; measure quality before considering a replacement |
| Bass separation | Demucs in `analysis/.venv` | Keep; accepted in M2 |
| DSP/arrays | NumPy + established libraries | Do not hand-write resampling, FFT, or peak detection unless a library is unsuitable |
| Playback/stretch | Existing AudioWorklet + Signalsmith Stretch | Keep |
| Waveform/editor | Existing React/canvas editor | Keep; extend only in the correction slice |
| Jobs/storage/portable | Existing FastAPI/SQLite/portable modules | Keep; fix defects, do not rewrite |
| Contracts | Pydantic + generated OpenAPI/TS | Keep; regenerate after API changes |
| Quality metrics | Existing `rhythm/evaluation.py` and corpus | Extend; do not create a second metrics stack |
| Beat/tempo/meter research baseline | Evaluate `librosa`, `scipy.signal`, `madmom`/`essentia` if installable | Offline evaluation only until a measured benefit and licence/size review; no runtime download |
| MATLAB (optional) | Audio/Signal Processing toolboxes for offline cross-checks | Only if licensed and installed; never a runtime dependency |

## Keep / adapt / replace

| Subsystem | Verdict | Trigger for change |
|---|---|---|
| Media import/decode, storage, jobs, portable format | **Keep** | Only a reproducible correctness failure |
| Domain timing/grid/meter models | **Keep** | Only a requirement mismatch |
| Beat This! runtime/adapter | **Keep** | Replace only if beat F1 stays below gate after postprocessing |
| Meter scoring | **Adapted** (downbeat evidence + pulse-unit compatibility) | Revisit if 4/4 accuracy < 5/5 |
| Tempo map / metronome scheduling | **Adapt only where measured** | Jitter/dropped-click gate in slice 1 |
| Editor lanes | **Defer** until slices 1–3 pass | Editing UI is not a quality substitute |
| Chromium/Safari support | **Defer** until Firefox release gate | No browser expansion before the core path is stable |

## Slice 0 — Re-baseline and golden path

**Outcome:** one reproducible Firefox path proves the current product works
end to end, and a quality baseline exists before any new feature.

**Scope**

- Golden-path E2E: launch → import a short real/click fixture → ready project
  → Analyze Rhythm → 4/4 bars → metronome renders clicks → count-in setting →
  portable save.
- Quality-baseline report: corpus structure, decoder/evaluation metrics,
  real-model synthetic metrics, known failures.
- Decide keep/adapt/replace from measurements, not test counts.

**Non-goals:** new editor controls, new models, browser expansion, UI polish.

**Acceptance evidence**

- `npm run e2e:golden` (in `frontend/`) passes on Firefox.
- `pytest tests/unit/test_rhythm_corpus.py tests/unit/test_rhythm_evaluation.py`
  passes; report recorded in `docs/quality-baseline.md`.
- Real final0 run (`BASSEPARATE_RHYTHM_TEST_CHECKPOINT=...`) passes and its
  beat/downbeat metrics are recorded there.
- `docs/quality-baseline.md` lists every failing gate with a keep/adapt/replace
  decision and no new UI is started while a gate is red.

## Slice 1 — Trustworthy 4/4 musical core

**Outcome:** for ordinary 4/4 songs, the inferred grid is correct, the
metronome is steady, and the readout agrees with what the user hears.

**Scope**

- 4/4 beat/downbeat/meter accuracy; no 7/8 or 12/8 false selection on
  quarter-note pulse tracks.
- Steady rendered clicks: no dropped beats, no duplicate clicks, bounded
  timing error.
- Tempo-map smoothing/regularisation only if the measured timing gate fails.
- Readout/bar navigation checks against the same grid.

**Non-goals:** 5/4, 7/8, rubato-heavy material, editing UI.

**Acceptance evidence**

- 5/5 supplied 4/4 excerpts select 4/4 (or a documented, manually verified
  exception).
- Beat F1 ≥ 0.90 and downbeat F1 ≥ 0.70 on the evaluation set.
- Rendered click intervals over 60 s: median absolute error ≤ 5 ms, 95th
  percentile ≤ 15 ms, no gap > 1.5 × the local beat period.
- Count-in and bar readout agree with the grid in the same run.
- Evidence in `docs/quality-baseline.md` and the Firefox golden path.

## Slice 2 — Complete practice session

**Outcome:** the user can practise a section without leaving the page:
selection → musical loop → count-in (once/every repeat) → speed change →
playback, with controls and state agreeing.

**Scope**

- Musical loop creation and loop playback at 0.5×/0.75×/1×/1.25×/1.5×.
- Count-in click counts (grouping-aware), accents, stop/pause cancellation.
- Metronome alignment after seek and loop wrap.
- Portable save of the resulting project.

**Non-goals:** lane editing, additional browsers, separation UI.

**Acceptance evidence**

- Firefox E2E creates a loop from a waveform selection, enables it, plays
  three passes at 0.75×, and verifies loop state and rendered click cadence.
- Count-in E2E/unit checks record the exact click counts for 4/4 and the
  grouped meters used by the supplied excerpts.
- Portable archive saves and lists its revision in the same run.
- No new UI beyond what the controls already provide.

## Slice 3 — Offline portability and durability

**Outcome:** a saved project reopens on a fresh installation with no model or
network and retains the practice state.

**Scope**

- Save → download → open in a second storage root with no models.
- Restore grid, active branch, loops, metronome/count-in, position/view state.
- Verify missing optional activation arrays do not block practice.
- Interrupted-run recovery messaging.

**Non-goals:** cross-version archive upgrades (documented limitation), cloud.

**Acceptance evidence**

- `pytest tests/integration/test_portable_rhythm.py` and the golden-path
  reopen step pass in Firefox.
- No network requests during reopen; model absence is reported only when the
  user starts a new analysis.
- A seeded project with a deleted optional activation directory still opens
  and plays.

## Slice 4 — Correction workflow

**Outcome:** when the automatic grid is wrong, the user can correct bars,
beats, downbeats, and meter in the editor without losing practice state.

**Scope**

- Minimal lane editing: move/add/delete pulse, set downbeat, edit meter region,
  undo/redo, save.
- Correcting a 4/4 song misread as another meter.
- Grid and metronome follow the corrected branch.

**Non-goals:** batch editing, automatic re-analysis of every correction,
mobile gestures.

**Acceptance evidence**

- Firefox E2E: load a deliberately wrong branch, correct it, verify bar
  readout/metronome/loop follow, undo/redo, save/reopen.
- Editing commands are idempotent and conflict-safe (existing command tests).
- No correction path silently mutates the automatic result.

## Slice 5 — Broader musical material

**Outcome:** 3/4, 6/8, 9/8, 12/8, 5/4, 7/8, tempo changes, pickups, and
meter changes meet their own gates instead of being hidden in one average.

**Scope**

- Corpus by meter/grouping and tempo behaviour.
- Meter alternatives/pickups/downbeat evidence.
- Tempo ramps and unmapped regions.
- Half/double-time reporting kept separate from beat misses.

**Acceptance evidence**

- Per-meter corpus report with label/grouping/boundary accuracy.
- No regression on the 4/4 gate.
- Documented uncertainty behavior for ambiguous material.

## Slice 6 — Firefox release hardening

**Outcome:** the Firefox practice product is dependable for the supplied
recordings and the remaining limitations are explicit.

**Scope**

- Five-recording acceptance (analysis, correction, loop, metronome/count-in,
  save/reopen).
- Performance budgets: finalize time, no playback underruns, bounded memory.
- Failure messages: missing model, no pulses, no grid, missing artifacts,
  portable archive without optional arrays.
- Documentation and troubleshooting refresh; remove superseded docs.

**Non-goals:** Chromium/Safari, mobile, accounts, streaming downloads.

**Acceptance evidence**

- Completed five-recording checklist.
- Golden path green on the release commit.
- `pytest tests/ -q`, frontend suite, Firefox E2E, type/lint/format, contract
  drift all green.
- Release notes list known limitations (browser scope, archive compatibility,
  model quality boundaries).

## Immediate next action

Slice 0 only. Do not add editor features until the golden-path test and the
quality baseline are recorded and reviewed.
