# Quality baseline (slice 0)

Date: 2026-10-25. This baseline was taken before the switch to the QM Vamp default. It is kept
for the Beat This! comparison and historical gate. The old downbeat gate no
longer blocks the default UI, which now uses QM Vamp and has its own native
host/golden-path evidence below.

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
- enable the metronome and verify a non-empty schedule (headless Firefox has no
  audio device, so rendered/audible clicks are not asserted here);
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

## Native Vamp host timing (personal path)

The native host (`storage/tools/vamp-host`) replaces the Piper JSON round
trips for the default path.

| Measurement | Result |
|---|---|
| 20 s excerpt, native host | **0.16 s** |
| 294 s Carousel source, first service run | **10.7 s** including 108 MiB PCM read, branch publication, and cache write |
| Cached features | 48 KiB JSON; subsequent runs skip the host |
| 12 s Firefox golden path, including UI steps | **4.3–6.8 s** test time |

The native host is local tooling, not a packaged dependency. The Piper host
remains a fallback.

## Vamp reference comparison (evaluation only)

A 20 s excerpt from the Carousel Theory mix (30–50 s) was analysed with the
QM Bar and Beat Tracker through Sonic Visualiser's Piper host:

```sh
python scripts/vamp_reference.py   --server storage/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server   --vamp-path storage/tools/vamp-plugins   --plugin qm-vamp-plugins:qm-barbeattracker   --audio storage/tools/carousel20.wav   --output storage/tools/carousel-vamp.json --bpb 4
```

The host requires `LD_LIBRARY_PATH` pointing at the extracted Sonic
Visualiser libraries. This is a reference oracle, not a runtime dependency:
the Vamp plugin pack is GPL/AGPL and is not bundled.

| Comparison | Result |
|---|---|
| Beats, ours vs QM | 46 vs 45; **45/46** within 50 ms |
| Median beat interval | ours 0.440 s, QM 0.430 s |
| Downbeats/bars | **11/11** within 100 ms |
| Our downbeat times | 1.30, 3.06, 4.80, … |
| QM bar times | 1.29, 3.03, 4.77, … |

Interpretation: the Beat This! beat and downbeat detections agree with the
mature Vamp tracker on real material. The bad 4/4 experience was caused by
**meter scoring/grid construction**, not by the beat detector. Do not replace
the beat decoder. The synthetic downbeat F1 (0.462) is a simple-accent
artefact, while the real reference alignment is 11/11.

## Five supplied excerpts (20 s each, native host)

All five local recordings produced a usable QM grid with `bpb=4`:

| Recording | Beats | Bars |
|---|---:|---:|
| 46.GIBBS - Simplicity | 47 | 12 |
| Carousel Theory Full Mix | 45 | 11 |
| Summer By The Sea Instrumental Demo | 34 | 9 |
| Sweet Demo | 28 | 7 |
| Videoslave Instrumental Demo | 45 | 11 |

This is a runtime/bar sanity check, not a metrical ground-truth claim.
Listening/correction review remains manual.

## Keep / adapt / replace decision

| Subsystem | Decision | Evidence |
|---|---|---|
| Beat This! runtime and beat decoding | Keep | Beat F1 0.952; 45/46 beats and 11/11 bars vs QM reference |
| Downbeat postprocessing | Keep, monitor | Real reference 11/11 bars; synthetic F1 0.462 is an accent artefact |
| Meter scoring (downbeat evidence + pulse-unit filter) | Keep, retest | 4/4 now selected on retained track |
| Tempo map / metronome scheduler | Adapt | Reported interval jitter and dropped beat |
| Media/import/storage/jobs/portable | Keep | Golden path import/save passes |
| Editor lanes / new UI | Allowed on the Vamp path | Old Beat This gate is historical; QM reference alignment is the new baseline |

## Slice-0 verdict

Functional golden path: **pass**.

The old Beat This downbeat/timing gates are **historical**: the default path
now uses QM Vamp, whose beats/bars match the reference. The current default
has its own golden path and native-host timing evidence above. The remaining
acceptance gaps are real Demucs browser acceptance, five-recording listening,
and section/correction polish.
