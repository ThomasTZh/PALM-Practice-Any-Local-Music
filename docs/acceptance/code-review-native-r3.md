# Review round 2: native blockers after the second repair

Status: **RELEASE STILL BLOCKED** — two blockers remain (N1, N2).

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t142 attempt 1 (`2c23191a-d8ab-490d-831a-99e2f027138b`), re-review of t141
- Reviewed revision: `5880cd1` on branch `t141-lifecycle` (working tree clean at start)
- Review host: Linux x86_64. Windows behaviour was exercised with the rebuilt
  packaged Windows CPython 3.11.15 under Wine 11.21; macOS cannot execute here,
  so real macOS layouts were exercised with the packaged payload and helper
  scripts.

## Commands and results

```text
make gate          -> gate: ok; pytest 514 passed, 9 skipped
make test-package  -> tar structure ok (6,557 members); bundled bin/palm --help ok; OK
pytest scoped      -> tests/unit/test_updater tests/unit/test_control
                      tests/unit/test_doctor tests/integration/test_analysis/test_sonic_platform.py
                      -> 33 passed
```

All three artifacts were rebuilt by t141 and contain the new lifecycle code
(`_external_python`/`_clear_pending` in `control.py`, `_alive`/`_clear_plan`/
`_restart` in `update_helper.py`). `make test-package` passes on those artifacts.

## Re-test results

| Item | Original | Re-test result |
| --- | --- | --- |
| R1 (B3) fresh-install Uninstall helper | blocker | **FIXED** (code). `_external_helper` now copies both helpers; a fresh packaged-layout data root got `update_helper.py` + `uninstall_helper.py`, and running the copied helper with a real uninstall plan (external interpreter) exited 0, removed the app and kept data. The packaged control flow is still blocked by N1 before this point. |
| R2 (B7) Windows helper path/liveness/order | blocker | **PARTIALLY FIXED, STILL BLOCKING via N1**. Quit now stops the server before the helper; helper output goes to `<data>/logs/updater.log`; `_alive` uses OpenProcess/WaitForSingleObject and is non-destructive (verified under packaged Windows Python: a live child stayed alive through a 1 s timeout). However the new helper-runtime path fails on every packaged platform (N1), so update/uninstall cannot launch at all. |
| R3 restart | high | **Fixed in the helper, but blocked by N2 on macOS**. A plan restart command executes after a successful swap: on the Linux layout the new app's `bin/palm` ran (restart-marker created). On the macOS layout the restart failed with `Permission denied` because the extracted bundle lost its executable bits (N2). |
| R4 pending plan/asset cleanup | high | **FIXED for the success path**. After a successful swap the helper removed `pending.json`, `pending.json.launched` and the staged asset; a second quit reported "No pending update." A failed swap still leaves the plan, marker and asset (N4). |
| R5 uninstall auto-close / wait | medium | **FIXED in code**. `ControlWindow.uninstall` schedules `quit` after a successful helper launch (`control.py:172`), so the helper no longer depends on a user click within 60 s. Real-flow verification is blocked by N1. |
| R6 native Windows write coverage | medium | **PARTIALLY FIXED**. `windows-package.yml` now runs a packaged-interpreter project-save/export smoke, and that exact pattern passes under Wine (`packaged project/save/stem/export ok`). There is still no native/fake coverage of stem-cache publication, and native import coverage is absent (the fake-Windows test covers import only). |
| L1 macOS builder README | low | **FIXED**. `packaging/macos/README.md` now describes the control window / no Terminal.app. |
| L2 stale 7-Zip CI step | low | **FIXED**. No `7z`/`vamp-extraction` steps remain in `.github/workflows/`. |

## Status of the original B1-B8 / M findings

- **B1 Windows directory fsync: fixed.** `fsync_directory` is POSIX-only; the
  fake-Windows import test and the rebuilt packaged Windows interpreter still
  pass (`import_media`, `ProjectStore.create/get`, `import_routes.import_source`
  all succeed under Wine).
- **B4 macOS helper discovery: fixed.** Real packaged payload resolves helpers
  from `Contents/Resources/updaters`, install root from the `.app` bundle.
- **B5 macOS swap/uninstall: fixed for the swap mapping and uninstall**, but the
  updated bundle loses executable bits during ZIP extraction (N2), so the
  updated app is not launchable.
- **B6 Sonic backend: fixed/unchanged.** Packaged Windows `default_backend()`
  returns `SonicAnnotatorBackend` with
  `<data>/tools/sonic-annotator-1.7.0/sonic-annotator.exe` and
  `<data>/tools/vamp-plugins`; fake-Sonic server tests pass.
- **B8 tag Windows workflow: fixed/unchanged.** MSVC setup, source build of
  `PALM.exe`, and a ZIP smoke that launches the native executable; the new
  project/export smoke is in the same workflow.
- **M1 UTF-8 names, M2 platform doctor: fixed/unchanged** (tests in the gate).

## Remaining blockers

### N1 (blocker, all packaged platforms): the external helper runtime is never resolvable

**File:** `src/basseparate/control.py:261`

```python
relative = executable.relative_to(app_root)      # returns a RELATIVE path
...
copied = destination / relative.relative_to(source)   # source is ABSOLUTE
```

`Path.relative_to()` returns a relative path, but `source` is absolute
(`executable.parent` or `.parent.parent`), so `relative.relative_to(source)`
always raises `ValueError` when the packaged app's interpreter is inside
`app_root`. All packaged Linux, Windows and macOS apps run from exactly that
layout.

**Reproduction 1 — packaged Linux interpreter**
(`/home/.../.cache/palm-r3app/python/bin/python3.11`, current source):

```text
EXTERNAL FAIL ValueError 'python/bin/python3.11' is not in the subpath of
'/home/.../.cache/palm-r3app/python' OR one path is relative and the other is absolute.
copied runtime exists: True
```

**Reproduction 2 — packaged Windows interpreter under Wine**
(`dist/palm-0.1.0-dev-windows-x86_64/python/python.exe`):

```text
EXTERNAL FAIL ValueError 'python\python.exe' is not in the subpath of
'Z:\...\dist\palm-0.1.0-dev-windows-x86_64\python' OR one path is relative and
the other is absolute.
```

**Impact:** `_external_python` is called from `launch_pending_update`
(`control.py:298`) and `uninstall_app` (`control.py:338`). In a packaged app:

- Quit with a staged update: `launch_pending_update` raises `ValueError`, which
  is not in its `(UpdateError, OSError, JSONDecodeError)` handler; the control
  window catches it only as a printed stderr message and exits. The update is
  never launched and no helper log is written.
- Uninstall: `uninstall_app` raises `ValueError`; `ControlWindow.uninstall`
  shows "Uninstall failed: ..." and the app is left running.

So the lifecycle repairs in t141 cannot execute on any packaged platform, and
the first call also copies the 133-196 MB bundled Python into the data root
before failing.

**Fix:** compute the copied path from the absolute path:
`copied = destination / executable.relative_to(source)` (and keep the existing
`relative` only for the `app_root` containment check). Add tests that call
`_external_python` with an interpreter inside a synthetic packaged app root for
each layout (`python/python.exe`, `python/bin/python3.11`, macOS payload), not
only with the test runner's interpreter outside the app.

### N2 (blocker, macOS update): extracted `.app` loses executable bits

**File:** `packaging/updaters/update_helper.py:67-75` (`_extract`), zip branch at
`:71`.

`zipfile.ZipFile.extractall` does not restore Unix modes. The macOS update asset
is the whole `PALM-*.macos-arm64.zip`; after extraction every file is created
with default permissions, so `PALM.app/Contents/MacOS/palm`, `bin/palm`,
`bin/uv` and `python/bin/python3.11` become non-executable.

**Reproduction** (current helper, synthetic macOS bundle ZIP with a 0755
wrapper; real helper swap path):

```text
stored external_attr: 0o100755
extracted mode: 0o644 executable: False

wrapper preserved: True | mode: 0o644 | executable: False
restart marker: False
updater log: restart failed after swap: [Errno 13] Permission denied:
             '.../PALM-Old.app/Contents/MacOS/palm'
```

The swap is recorded as successful and the plan/asset are removed, but the
replacement bundle cannot be launched by Finder or by the restart command.
`_extract` has the same issue for any other ZIP channel whose payload contains
executables.

**Fix:** restore each member's mode after extraction
(`os.chmod(destination / info.filename, (info.external_attr >> 16) & 0o777)`),
or ship the macOS update as a tar.gz payload preserving modes (the Linux path
already uses `tarfile`). Add a macOS update test that applies a real ZIP with
0755 wrappers/binaries and asserts `Contents/MacOS/palm` and `bin/palm` remain
executable and that the restart command runs.

## Medium findings

### N3: explicit delete-data uninstall cannot remove the copied runtime on Windows

**Files:** `packaging/updaters/update_helper.py:142-166` (`uninstall`,
`shutil.rmtree(data_root)` at `:165`), `src/basseparate/control.py:245-264`
(`_external_python` copies into `<data>/updates/runtime/python`).

With N1 fixed, the uninstall helper runs from
`<data>/updates/runtime/python/python.exe` on Windows. The optional
`delete_data` plan then calls `shutil.rmtree(data_root)`, which cannot delete
that running interpreter/DLLs: the call raises, the app has already been
removed, and the data root is partially deleted. The keep-data default is
unaffected but leaves a 133-196 MB runtime copy in the data root.

**Fix:** place the helper runtime outside the data root (or use a native
delete helper), and make delete-data skip the runtime directory, removing it
best-effort after the helper exits. Add a delete-data test with the runtime
inside/outside the data root.

### N4: a failed swap leaves a "launched" marker that blocks retry

**Files:** `src/basseparate/control.py:279-306` (`marker.write_text`),
`packaging/updaters/update_helper.py:94-139` (failure path returns without
clearing the plan/marker).

When `swap_app` rolls back, it logs the failure but leaves `pending.json`,
`pending.json.launched` and the staged asset. Reproduced with a corrupt staged
asset: helper exit 1, old app intact, plan+marker+asset remain, and the next
quit returns "Update helper has already been launched." The only recovery is a
new Check for updates (which clears the marker when it stages again); the user
gets no visible failure.

**Fix:** on a failed swap, remove the marker and either clear or mark the plan
as failed so the next quit can retry; surface the failure in the control window
detail; add a failed-swap retry test.

### N5: the runtime copy is large and happens on the UI thread before validation

`_external_python` copies the complete bundled Python tree into
`<data>/updates/runtime/python` on the first update/uninstall: 154 MB on Linux,
196 MB on Windows, 133 MB on macOS (measured from the rebuilt artifacts). On a
Quit this blocks the Tk callback while copying, and keep-data uninstall leaves
the copy behind. With N1 present, the copy happens before the `ValueError`, so
every attempt also wastes that copy.

**Fix:** after fixing N1, use a minimal helper runtime (python executable,
DLL/dylib, stdlib zip) or copy only on demand with progress; document/clean the
runtime directory.

### N6: native Windows CI still misses import and stem publication

**Files:** `.github/workflows/windows-package.yml:45-84` (new project/export
smoke), `.github/workflows/portable.yml:132-135` (platform/package/updater
tests only).

The new smoke covers project save and mixdown export (verified with the same
pattern under Wine), but not WAV import (only the fake-Windows integration test
on Linux) or stem-cache publication (`stems.py:463` `fsync_directory` +
`stage.rename`). The acceptance call for import/project/stem/export under a
Windows-like fake and native CI is therefore still only partially met.

**Fix:** add a packaged-interpreter smoke for `stems._publish` and either an
HTTP import smoke with a pinned FFmpeg or a Windows-marked import test.

## Verified working in this review

- `make gate`: ruff, format, fixtures, models, mypy strict, pytest (514 passed,
  9 skipped), web typecheck/tests/build and both e2e specs — exit 0.
- `make test-package`: 6,557 members, archive checks, bundled `bin/palm --help`
  — OK (container smoke skipped offline).
- Scoped updater/control/doctor/Sonic-platform tests: 33 passed.
- Windows packaged write path (Wine): `import_media`, project create/get,
  import route, and the project-save/export/stem-read smoke all succeed.
- Windows helper liveness: `_alive()` is non-destructive; `wait_for_exit`
  timed out while the live child stayed alive.
- Linux lifecycle with an external interpreter: stage → quit launch → swap →
  restart → plan/marker/asset cleanup → second quit "No pending update";
  corrupt-asset rollback restores the old app; fresh copied uninstall helper
  removes the app and keeps data; delete-data removes data on POSIX.
- macOS layout: helper lookup, `.app` install root, whole-bundle swap (new
  payload, wrapper preserved), bundle removal on uninstall, data kept, and the
  restart command is invoked (fails only on the N2 permission issue).
- B6 packaged Windows Sonic resolution (data-root binary/plugin paths) is
  unchanged and correct; fake-Sonic server tests pass.
- L1/L2 fixed as described above.

## Required before release

1. Fix N1 and add packaged-interpreter tests for all three layouts; re-run the
   update and uninstall flows on the rebuilt Linux/Windows/macOS artifacts.
2. Fix N2 with a macOS ZIP-mode test; verify the updated `PALM.app` launches and
   restarts after a swap.
3. Fix N3 (delete-data runtime placement) and N4 (failed-swap retry); re-run
   keep-data and delete-data uninstall, and a failed-update retry.
4. Add the missing Windows native/fake coverage for import and stem publication
   (N6), then rebuild artifacts and re-run `make gate` / `make test-package`
   and the native Windows/macOS acceptance checklists.

No product code was modified by this review; only this report was added.

## Limitations

- No native Windows or macOS host was available. Windows was exercised with the
  packaged Windows CPython under Wine (which cannot reproduce Windows
  executable-image locking); macOS payloads were exercised on Linux, so macOS
  Mach-O execution and Gatekeeper behaviour remain unverified.
- The t137/t141 CI run 44184416370 referenced by the captain was not re-run here
  (no network); the workflow content and the equivalent Wine smoke were checked
  instead.
- `make test-package` validates the rebuilt artifacts, not a freshly published
  release; no release was published.
