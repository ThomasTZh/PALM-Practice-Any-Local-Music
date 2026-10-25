# Quality baseline (slice 0)

Date: 2026-10-25. This is the pre-UI quality snapshot required by
`EXECUTION_PLAN.md`. It records what passed, what failed, and what is still
unmeasured. A red gate blocks UI work.

## Commands and results

```sh
.venv/bin/python -m pytest tests/unit/test_rhythm_corpus.py \
  tests/unit/test_rhythm_evaluation.py -q
# 37 passed in 1.29 s

BASSEPARATE_RHYTHM_TEST_CHECKPOINT=$PWD/storage/m3.2/data/models/beat_this_final0/final0.ckpt \
.venv/bin/python -m pytest tests/integration/test_rhythm_activation_real.py -q
# 1 passed in 5.42 s

cd frontend
npm run e2e:golden
# 1 passed in 11.9 s (functional path)
```

## Real final0 measurement (5 s synthetic click fixture, 50 ms tolerance)

| Metric | Value | Slice-1 gate | Status |
|---|---|---|---|
| Model frames | 251 | — | — |
| Accepted pulses | 11 | — | — |
| Beat precision / recall / F1 | 0.909 / 1.000 / 0.952 | F1 ≥ 0.90 | **pass** |
| Downbeat precision / recall / F1 | 0.375 / 0.600 / 0.462 | F1 ≥ 0.70 | **fail** |
| Inference time | 0.087 s | no gate yet | — |
| Model load time | 0.206 s | no gate yet | — |

Interpretation: pulse timing is exact on this fixture, but the decoder
over-labels downbeats on simple accent patterns. The beat score passes; the
downbeat score does not.

## Golden path (Firefox)

`frontend/e2e/golden-path.spec.ts` proves:

- launch with an isolated storage root and the installed model;
- import a generated 12 s 120 BPM click track;
- create a ready project through canonical decode;
- run Analyze Rhythm with the real final0 model;
- select 4/4 and render bar lines;
- start the metronome and observe rendered clicks in the worklet;
- create a musical loop from a waveform selection and enable looping;
- select one-bar count-in;
- save a portable project.

It does **not** yet prove audible alignment, loop timing over several passes,
or offline reopen. Those are slices 2 and 3.

## Meter check on the retained 4/4 track

Before the meter-inference correction, the retained activation/features for
the user's 4/4 track selected `7/8 (2+2+3)` by a 0.006 margin. After the
downbeat-evidence and pulse-unit compatibility changes, re-inference on the
same retained inputs selected `4/4`. This is a manual check, not yet a
five-excerpt automated gate.

## Timing gate (not yet automated)

Earlier rendered-click sampling on a 4/4 click track showed intervals of
23,040–25,920 frames at 120 BPM instead of 24,000, and occasionally a missing
beat. The functional test now verifies that clicks render, but the slice-1
timing gate (median error ≤ 5 ms, p95 ≤ 15 ms, no gap > 1.5× beat period) is
**not yet met or automated**.

## Keep / adapt / replace decision

| Subsystem | Decision | Evidence |
|---|---|---|
| Beat This! runtime and beat decoding | Keep | Beat F1 0.952 |
| Downbeat postprocessing | Adapt | Downbeat F1 0.462 |
| Meter scoring (downbeat evidence + pulse-unit filter) | Keep, retest | 4/4 now selected on retained track |
| Tempo map / metronome scheduler | Adapt | Reported interval jitter and dropped beat |
| Media/import/storage/jobs/portable | Keep | Golden path import/save passes |
| Editor lanes / new UI | Defer | Quality gates red/incomplete |

## Slice-0 verdict

Functional golden path: **pass**.

Quality gate: **red** (downbeat accuracy; timing not yet measured/steady).
No new editor UI is permitted until slice 1 closes the downbeat and timing
gates or records an approved exception.
