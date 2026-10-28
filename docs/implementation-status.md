# Implementation status — local practice studio

Date: 2026-10-25. This is the current resume point. The previous 4,910-line
ledger is archived at
[`archive/implementation-status-2026-10-24.md`](archive/implementation-status-2026-10-24.md).
Product goals: [`GOALS.md`](../GOALS.md). Plan:
[`EXECUTION_PLAN.md`](../EXECUTION_PLAN.md).

## Position

The default path is now local file → Demucs stems → local Vamp QM bar/beat
grid → editable Song Map sections → section/range loops → speed control.

Beat This! and the custom meter pipeline remain in the repository for
comparison, but they are not required by the default UI or the golden path.

## Working evidence

- Firefox golden path (`frontend/e2e/golden-path.spec.ts`):
  import → ready → Analyze Rhythm (Vamp) → 4/4 bars → metronome schedule →
  0.75× speed → musical loop → section → section loop → count-in → portable
  save. Last run: **passed**, 4.3 s test time.
- Native QM analysis on the 294 s Carousel source: **701 beats / 176 bars /
  4/4 branch**, about 10.7 s including the first 108 MiB PCM read and branch
  publication; the 48 KiB feature cache is reused after that.
- Full backend suite: **1726 passed, 2 skipped** (the skips require an
  explicitly configured legacy checkpoint or native host). Frontend suite:
  **624 passed, 54 files**.
- QM reference comparison on a 20 s excerpt: 45 beats / 11 bars; our prior
  Beat This! beats matched 45/46 within 50 ms and downbeats 11/11 within
  100 ms.
- Section commands: add/update/split/delete/set-active/loop, non-overlap and
  duration validation, linked loop updates, undo/redo.
- Stem separation panel starts the existing Demucs run, polls the durable
  job, and activates the newest valid result set. Real Demucs acceptance is
  still manual.
- Frontend component tests cover the analysis panel, section panel, and stem
  panel.

## Architecture decisions

- Browser stays the frontend.
- QM Vamp analysis is the primary grid. The native host consumes interleaved
  f32 PCM and writes only beats/bars; the Piper JSON host is the fallback.
- `bpb` is a manual beats-per-bar hint (2/3/4/6/7, default 4). No automatic
  meter inference in this slice.
- Sections live in `PracticeState`; no new database table. `PracticeLoop`
  optionally links to a section through `section_id`, so section edits update
  the linked loop atomically.
- Sections are ordered and non-overlapping. A section range is a source-frame
  range; loop ranges spanning sections use the existing loop path.
- A section chain/playlist is deferred; only the active section and selected
  ranges are looped now.

## Known limitations

- The stem panel has unit tests but no full Demucs browser acceptance run.
- Portable save/open includes sections through `practice_state`; the portable
  open test round-trips a section and its linked loop.
- The native Vamp host path is local tooling under `storage/tools/` and is not
  packaged into a distributable app. Personal Linux use only.
- Beat This! is still present behind the historical code/tests; its model is
  not needed for the current golden path.
- Automatic section suggestions are not implemented; manual editing is the
  current workflow.
- No correction UI for pulses/downbeats/meter.
- No Chromium/Safari/mobile target.

## Verification commands

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/basseparate
.venv/bin/python scripts/check_contract.py
cd frontend && npm test -- --run
cd frontend && npm run format:check && npm run build
cd frontend && npm run e2e:golden
BASSEPARATE_VAMP_NATIVE_HOST_PATH=$PWD/storage/tools/vamp-host \
BASSEPARATE_VAMP_PLUGIN_PATH=$PWD/storage/tools/vamp-plugins \
  .venv/bin/python -m pytest tests/integration/test_vamp_native_real.py -q
```

## Next actions

1. Run a real Demucs separation through the new panel on one supplied track
   and record the result.
2. Add a portable section round-trip test.
3. Update `docs/quality-baseline.md` with the native-host timing and current
   gate status.
4. Run the five-recording practice review before adding correction or
   automatic-section UI.
