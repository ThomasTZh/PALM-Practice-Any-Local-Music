# Review round 3: native blockers after the third repair

Status: **PASS — no remaining release blockers.**

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t144 attempt 1 (`2fcdc7b0-9e4d-452d-bbec-59682bd4e7c7`), re-review of t143
- Reviewed revision: `325615d` on branch `t143-runtime` (working tree clean at start)
- Review host: Linux x86_64. Windows behaviour was exercised with the rebuilt
  packaged Windows CPython 3.11.15 under Wine 11.21; macOS cannot execute here,
  so real macOS payloads were exercised with the packaged helper scripts and
  artifacts.

## Commands and results

```text
make gate          -> gate: ok; pytest 518 passed, 9 skipped
make test-package  -> tar structure ok (6,557 members); bundled bin/palm --help ok; OK
pytest scoped      -> tests/unit/test_updater tests/unit/test_control
                      tests/unit/test_doctor tests/integration/test_analysis/test_sonic_platform.py
                      -> 37 passed
```

All three artifacts were rebuilt by t143 and contain the new lifecycle code
(`_external_python`, `_copy_helper_runtime`, `_mark_failed`, ZIP mode restore,
failed-plan retry, stem-publish smoke). `make test-package` passes on them.

## Re-test results

| Item | Original | Result |
| --- | --- | --- |
| N1 external helper runtime path | blocker | **FIXED**. `control.py:253-305` now uses `executable.relative_to(source)` and catches `ValueError`. Packaged Linux and packaged Windows runs produced an external interpreter outside both `app_root` and the data root, and the copied interpreter ran (`COPIED OK`). |
| N2 macOS ZIP executable modes | blocker | **FIXED**. `update_helper.py:67-84` restores `ZipInfo.external_attr` modes after extraction. Swapping the **real** `PALM-0.1.0-dev-macos-arm64.zip` through the helper left `Contents/MacOS/palm`, `bin/palm`, `bin/uv` and `python/bin/python3.11` at **0755** and executable; a synthetic restart marker was created after the swap. |
| N3 helper runtime outside data root | medium | **FIXED**. Runtime is copied to `<data_root>.parent/.palm-helper-runtime`; delete-data removes the data root and attempts runtime cleanup. POSIX delete-data removed app, data and runtime; Windows/Wine removed app and data. Residual: the running runtime cannot be fully deleted on Windows/Wine (see residual notes). |
| N4 failed swap marker/retry | medium | **FIXED**. A failed swap removes `pending.json.launched`, writes `pending.json.failed`, keeps the plan and staged asset, rolls back, and the next quit retries; a successful retry clears the plan, `.failed` and `.launched`. Launch failures are shown in the control detail (`control.py:204-224`, test `test_quit_surfaces_pending_update_launch_failure`). |
| N5 minimal runtime copy/logging | medium | **FIXED in substance**. Only interpreter/shared libraries/stdlib are copied (no site-packages): measured 129.5 MiB Linux and 98.3 MiB Windows (full trees are 154/196 MiB); copy is logged to `updater.log`; it is reused on later calls. Residual size/copy-time note below. |
| N6 Windows native write coverage | medium | **Met in substance**. `windows-package.yml:45-91` runs a packaged-interpreter project/save/stem-publish/export smoke (CI run 44188416906 reported passing; the same pattern passes under Wine). The fake-Windows import test covers the fsync/atomic-write path; `stems._publish` itself was independently verified under the packaged Windows interpreter (final cache dir created, stage renamed). No HTTP import smoke or native stem-cache publish smoke was added; see residual notes. |

## Status of the original B1-B8 / M / L findings

- **B1 Windows directory fsync: fixed/re-verified.** Packaged Windows
  `import_media`, `ProjectStore.create/get` and `import_routes.import_source`
  succeed under Wine; stems cache publish and export succeed; no 500 path.
- **B2 update lifecycle: fixed.** Packaged Linux: stage -> quit launch -> helper
  swaps -> restart marker -> plan/.launched/asset cleanup -> second quit reports
  no pending update; corrupt asset rolls back and retries. Windows: external
  runtime, helper swap/restart, keep/delete uninstall verified under Wine.
- **B3 uninstall helper: fixed.** Both helpers are copied to the data root and
  the copied uninstall helper runs with a real plan; app removed and data kept.
- **B4 macOS helper discovery: fixed.** Real macOS payload resolves
  `Contents/Resources/updaters`; install root is the `.app` bundle.
- **B5 macOS app handling: fixed.** Whole-bundle swap keeps the wrapper and
  restores executable modes; uninstall removes the bundle, keeps data.
- **B6 Windows/macOS Sonic analysis: fixed/unchanged.** Packaged Windows
  `default_backend()` returns `SonicAnnotatorBackend` with data-root binary and
  plugin paths; missing-tools message names PALM Setup; fake-Sonic server tests
  pass for win32/darwin.
- **B7 Windows helper path: fixed.** Helpers run from the external minimal
  runtime (not the app root); `_alive` uses OpenProcess/WaitForSingleObject
  (verified non-destructive under packaged Windows Python: a live child stayed
  alive through a 1 s wait timeout).
- **B8 tag Windows workflow: fixed.** `windows-package.yml` keeps the MSVC setup,
  builds `PALM.exe` from source before packaging and smoke-launches the native
  exe; the project/export/stem smoke was added in the same workflow.
- **M1 UTF-8 names, M2 platform doctor, L1 macOS builder README, L2 7-Zip CI:
  fixed/unchanged** (gate and file inspection).

## Residual non-blocking observations

These do not block the release gate but are worth a follow-up:

1. **R-a (low/medium): delete-data leaves a partial helper runtime on Windows.**
   `update_helper.py:158-186` runs `shutil.rmtree(runtime, ignore_errors=True)`
   while the helper itself is executing from that runtime. On Windows (and
   reproduced under Wine) the directory survives with locked files; the data
   root itself is removed. Keep-data uninstall also leaves the 98-130 MiB runtime
   under the data-root parent. Consider moving the helper runtime to the system
   temp directory and deleting it best-effort on the next start.
2. **R-b (low): swap failures are visible only in the log/.failed file.** The
   control window surfaces launch failures (`control.py:204-224`) but a helper
   swap failure happens after the control process has exited; the next start does
   not display `pending.json.failed`. The next quit retries (verified), so the
   update is recoverable, but the user gets no notice of the earlier failure.
3. **R-c (medium): uninstall while an update is pending launches both helpers.**
   `ControlWindow.uninstall` schedules `quit` (`control.py:159-172`), and `quit`
   runs `_quit_action` (`control.py:204-224`), which calls
   `launch_pending_update`. If a plan is staged, the update helper is launched
   alongside the uninstall helper and both wait for the same pid. Under Wine and
   by code inspection the normal single-helper flows work; the combination can
   race (on Windows an update restart can hold the app directory while the
   uninstall helper tries to delete it). Consider clearing the pending plan/asset
   on uninstall or skipping the quit-time update launch while uninstalling.
4. **R-d (low): persistent update-launch failure keeps the window open with the
   server stopped.** `quit` resets `_quitting` and returns without destroying the
   window when the message contains "could not be launched", so a persistent
   failure (e.g., read-only data parent) has no quit-without-update path.
5. **R-e (medium coverage): native Windows CI still lacks an HTTP import smoke
   and an actual stem-cache publish smoke.** The added CI stem step calls
   `publish_project_stems` (project document metadata), not
   `stems._publish`/`atomic_write_bytes`. The fake-Windows import test and the
   Wine `stems._publish` run cover the same primitives; adding the two smokes
   would make the N6 wording literal.
6. **R-f (low): copied runtime is still large and copied on the Tk thread.**
   129.5 MiB (Linux) / 98.3 MiB (Windows) on first update/uninstall; the copy
   blocks the control window while it runs (it happens on Quit or the Uninstall
   button). A smaller stdlib-only layout or progress feedback would help.

## Acceptance assessment

- **Re-test every B1-B8 finding:** done; all are fixed with evidence above.
- **Windows durable writes and import/project/stem/export under a Windows-like
  fake and native CI; no 500:** met in substance. The fake-Windows test covers
  import/atomic writes; the native Windows CI smoke covers project save, stem
  metadata publication and export (run 44188416906 per t143); independent Wine
  runs cover import, project save, actual stem cache publish and export with no
  500 path. Literal native import/stem-cache CI smokes are still missing (R-e).
- **Update/uninstall launch, swap, rollback, data preservation, macOS `.app`
  and Windows helper path:** verified on packaged Linux and Windows (Wine) and
  the real macOS artifact; residual race/cleanup notes are non-blocking.
- **Windows/macOS Sonic analysis:** fixed; native execution remains a documented
  manual-acceptance limitation.
- **Tag Windows workflow builds PALM.exe:** fixed.
- **Report with file:line findings, exact commands, no product edits:** this
  report.

Native Windows and macOS manual acceptance checklists remain required by the
existing acceptance documents before promoting the beta/experimental labels or
publishing artifacts; that is a release-process requirement, not a code blocker.

## Limitations

- No native Windows or macOS host was available. Windows was exercised with the
  packaged Windows CPython under Wine (which cannot fully reproduce Windows
  file locking); macOS payloads were exercised on Linux.
- The t143 CI run 44188416906 was not re-run here; the workflow content and the
  equivalent Wine smokes were checked instead.
- `make test-package` validates the rebuilt artifacts; no release was published.

No product code was modified by this review; the only file added is this report.
