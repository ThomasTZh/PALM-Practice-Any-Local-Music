# Re-review: native blockers after repairs

Status: **RELEASE STILL BLOCKED** — 2 blockers remain plus update-lifecycle defects.

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t139 attempt 1 (`1baaa723-4b85-44ee-b4b0-14979a411d20`), re-review of t133
- Reviewed revision: `27bdf3a` on branch `t137-windows-tag` (working tree clean at start)
- Review host: Linux x86_64. Windows code paths were exercised with the packaged
  Windows CPython 3.11.15 under Wine 11.21; macOS cannot execute here, so its
  packaged tree and lifecycle were exercised with the real macOS payload layout.
- Commands run in this review:

```text
make gate          -> gate: ok; pytest 510 passed, 9 skipped
make test-package  -> tar structure ok (6,557 members); bundled bin/palm --help ok; OK
pytest scoped      -> tests/unit/test_updater tests/unit/test_control
                      tests/unit/test_doctor tests/integration/test_analysis/test_sonic_platform.py
                      -> 29 passed
```

## Re-test results

| Item | Original severity | Re-test result |
| --- | --- | --- |
| B1 Windows directory fsync | blocker | **FIXED**. `platform_support.fsync_directory` is a no-op off POSIX; media/projects/stems/export use it. Import, project save and the import route now succeed under packaged Windows Python. Fake-Windows tests added. Native Windows CI coverage is still missing (see R6). |
| B2 staged update never installed | blocker | **FIXED on POSIX, still blocked on Windows by B7**; restart is still missing (R3) and the pending plan is not cleared (R4). |
| B3 uninstall helper filename | blocker | **NOT FIXED**. The hyphenated name is gone, but a fresh install copies only `uninstall_helper.py`; its `from update_helper import main` still fails (R1). |
| B4 macOS helper discovery | blocker | **FIXED**. `_external_helper` finds `Contents/Resources/updaters`; `_install_root` selects the `.app`; restart command points at `Contents/MacOS/palm`. Verified against the real macOS packaged tree. |
| B5 macOS update swap/uninstall | blocker | **FIXED**. Whole-`PALM.app` swap keeps the shell, wrapper and new payload; uninstall removes the bundle and keeps data. Verified with a synthetic whole-app ZIP through the real helper. |
| B6 Windows/macOS Sonic analysis | blocker | **FIXED**. `default_backend()` selects `SonicAnnotatorBackend` on win32/darwin with data-root binary and plugin paths; missing tools show the PALM Setup message. Reproduced under packaged Windows Python; fake-Sonic-through-server tests pass. Native execution remains unverified. |
| B7 Windows helper lifecycle | high | **STILL BLOCKING**. Helpers still run with the app-root interpreter, `wait_for_exit` kills the app on Windows, and Quit launches the helper before stopping the server (R2). |
| B8 tag Windows workflow | high | **FIXED**. `windows-package.yml` adds `ilammy/msvc-dev-cmd`, builds `PALM.exe` from source before packaging, and the smoke launches the native exe. Verified by workflow inspection; the run quoted in t137 was not re-run here. |
| M1 UTF-8 upload names | medium | **FIXED**. `decode_upload_text` recovers raw UTF-8 and percent-encoded names. Reproduced: both raw UTF-8 `café demo.wav` and percent-encoded `caf%C3%A9%20demo.wav` names produce `café demo` over HTTP 201. |
| M2 doctor on Windows/macOS | medium | **FIXED**. Doctor checks `sonic-annotator[.exe]` and the platform plugin suffix on Windows/macOS, Piper only on Linux; new tests cover both and the packaged-Linux run still reports Piper. |
| L1 stale macOS builder README | low | **STILL PRESENT**. `packaging/macos/README.md:38` still says Finder opens Terminal.app. |
| L2 7-Zip CI step | low | **STILL PRESENT**. `portable.yml:164-176` still downloads 7-Zip for the stale Vamp extraction report (t137's "no 7-Zip/Vamp CI steps" applies only to `windows-package.yml`). |
| L3 LAUNCHER.md committed binary | low | **FIXED**. It now documents the tracked `packaging/windows/PALM.exe` rebuilt from checked-in source. |

## Remaining blockers

### R1 (B3): fresh-install Uninstall still cannot run its helper (all platforms)

**Files:** `src/basseparate/control.py:280-297` (`_external_helper` copies only the
requested file at `:289`), `control.py:265` and `control.py:375` request only
`uninstall_helper.py`, `packaging/updaters/uninstall_helper.py:13`
(`from update_helper import main`).

**Evidence** (current source, real packaged Linux layout):

```text
$ PALM_MODE=packaged PALM_APP_ROOT=$PWD/dist/palm-0.1.0-dev-linux-x86_64 \
  PALM_DATA_DIR=$(mktemp -d) PYTHONPATH=$PWD/src .venv/bin/python - <<'PY'
... helper = control._external_helper(paths, "uninstall_helper.py")
... subprocess.run([sys.executable, str(helper), "--plan", plan])
PY
copied: .../updates/helpers/uninstall_helper.py
siblings: ['uninstall_helper.py']
exit: 1
stderr tail: ModuleNotFoundError: No module named 'update_helper'
```

On a fresh install the helpers directory contains only the uninstall helper; the
sibling import fails and, because the helper's stderr is `DEVNULL`
(`updater.py:302`), the control window still reports "Uninstall helper
launched; your data is kept." Uninstall therefore does nothing on every
platform unless a previous update check happened to copy `update_helper.py`.
The new test `tests/unit/test_control/test_control.py` copies both helpers
sequentially before checking existence, so it does not exercise this path.

**Fix:** copy both packaged helpers whenever either is externalised (or make
`uninstall_helper.py` self-contained, or import the sibling by explicit path),
and add a test that runs the copied helper with a real `--plan` on a fresh data
root.

### R2 (B7): Windows update/uninstall lifecycle is still incorrect

**Files:** `src/basseparate/updater.py:216` and `:295`
(`executable = str(python or sys.executable)`), `control.py:199-211` (`quit`
launches the pending helper before `controller.stop()`), `control.py:239-252`
(`launch_pending_update`), `packaging/updaters/update_helper.py:28-40`
(`wait_for_exit`, `os.kill(pid, 0)` at `:36`), `:105-125` (`uninstall`,
`shutil.rmtree(app_root)` at `:116`), and helper stderr to `DEVNULL`
(`updater.py:223`, `:302`).

**Problem:** in the packaged Windows app the control process is
`<app_root>\python\pythonw.exe`, so `sys.executable` is inside the tree the
helper replaces or deletes. Windows refuses to delete a directory containing
the running interpreter (the uninstall helper's own `python311.dll`/`pythonw.exe`
are open and cannot be unlinked), so `shutil.rmtree(app_root)` fails and can
leave a partially deleted app. On Quit the update helper also runs
`wait_for_exit(control_pid)`, and on Windows `os.kill(pid, 0)` calls
`TerminateProcess`: it kills the control process instead of probing it, before
`controller.stop()` has stopped the server. The helper then swaps while the old
server is still running and never restarts it. The helper's output is discarded,
so every failure is silent.

**Evidence:**

```text
$ wine dist/palm-0.1.0-dev-windows-x86_64/python/python.exe Z:\tmp\r2_win_helper.py
MESSAGE  Update helper launched; PALM will swap and restart after Quit.
COMMAND  Z:\...\dist\palm-0.1.0-dev-windows-x86_64\python\python.exe   # app-root interpreter
SYSEXEC  Z:\...\dist\palm-0.1.0-dev-windows-x86_64\python\python.exe
WAIT RAISED SystemError ...            # after os.kill(pid, 0)
CHILD POLL 0                           # the "waited for" child was terminated
```

Wine maps deletes to POSIX `unlink`, so it cannot reproduce the Windows
file-lock failure; that part needs native Windows evidence, but the interpreter
location and the kill behaviour are proven above.

**Fix:** run the helpers with an interpreter outside `app_root` (or use a native
`cmd`/PowerShell move/delete helper on Windows), use a non-destructive liveness
check on Windows (`OpenProcess`/`WaitForSingleObject` via `ctypes`, or
`psutil.Process(pid).is_running()` loaded before the swap), stop the server
before launching the quit-time helper (or pass both pids and wait for both),
and send helper output to `<data>/logs/updater.log` instead of `DEVNULL`.

## Remaining lifecycle defects (not separate original findings)

### R3 (high): updates are installed but never restarted

**Files:** `packaging/updaters/update_helper.py:128-135` (`main` calls
`swap_app(payload)` without a restart callback), `:68` and `:92` (`restart`
defaults to `None`), `control.py:252` and `docs/portable.md:98` claim a restart.

The plan written by `control.py:327` contains the correct restart command
(verified: `['.../bin/palm', '--window']` on Linux and the `.app` wrapper on
macOS), but `swap_app` only invokes a restart callback it never receives.
Reproduced: helper exit 0, new payload present, `restart-marker` not created.

**Fix:** pass a detached `subprocess.Popen(plan["restart"], ...)` (POSIX:
`start_new_session`; Windows: detached/no-window) from `main` after a
successful swap, and keep a restart failure out of the rollback decision or
record it in the log.

### R4 (high): the staged plan is never cleared, so every later Quit re-applies it

**Files:** `src/basseparate/control.py:239-252` and
`packaging/updaters/update_helper.py:128-135`.

After a successful swap the helper leaves `<data>/updates/pending.json` and the
staged asset in place. Reproduced: the next `launch_pending_update` launched the
same helper again ("launches again: True"), which re-swaps (or fails, or kills
the app on Windows) on every subsequent Quit. `launch_pending_update` also does
not check the plan version against the installed `install.json`.

**Fix:** remove the plan and staged asset after a successful swap (and after a
launch failure, record why); ignore plans whose target version is not newer than
the installed version; add a test for "second quit after update does not
relaunch the helper".

### R5 (medium): uninstall helper may time out while the control window is still open

**Files:** `packaging/updaters/update_helper.py:28-40` (60 s default),
`src/basseparate/control.py:374-377` (`uninstall_action` launches the helper and
returns while the window stays open).

The helper waits only 60 s for the control process to exit. The Uninstall
button does not quit the window, so a user who does not click Quit within a
minute gets a helper that exits 1 with nothing removed (and no visible error,
because output is discarded).

**Fix:** quit the control window automatically after launching the uninstall
helper, or let the helper wait on the plan pid without a short wall-clock
timeout and report progress.

### R6 (medium): no native Windows coverage for the durable write paths

**Files:** `.github/workflows/windows-package.yml:47` and
`.github/workflows/portable.yml:132-135` run only
`tests/integration/test_package_windows`, `tests/unit/test_platform_support`
and the updater/licence audits; the smoke checks only health. No Windows CI job
imports a WAV, saves a project, publishes stems or exports a mixdown, and the
new fake-Windows test covers only the import path
(`tests/integration/test_import/test_import_errors.py`).

The t139 contract expects import/project/stem/export to work "under a
Windows-like fake and native CI". The code path is fixed (see B1 evidence), but
the native-CI half is not covered; add a Windows job that runs a no-FFmpeg
`atomic_write_bytes`/project-save/stem-publish/export test with the packaged
interpreter, or an HTTP import smoke with a pinned FFmpeg.

## Low-severity notes

- **L1** `packaging/macos/README.md:38` still says Finder opens Terminal.app
  via `osascript`; the product docs (`README.md:33`, `docs/portable.md:59,142`)
  now describe the control window and the `--no-terminal` override correctly.
- **L2** `.github/workflows/portable.yml:164-176` still downloads `7zr.exe` and
  `7z2606-extra.7z` for the "Windows Vamp extraction report"; t137 removed the
  equivalent step only from `windows-package.yml`.

## Artifact note

The `dist/` artifacts are not all rebuilt from `27bdf3a`:

- Linux tar/Windows ZIP at `dist/` contain the B1 and control/updater fixes but
  not the t138 UTF-8/doctor changes (`import_routes.py` has no
  `decode_upload_text`).
- The macOS ZIP predates the repairs entirely (no `fsync_directory` in its
  payload).

Rebuild all three artifacts after the remaining fixes and re-run
`make test-package` before publishing; the packaged-layout checks in this review
used the real updater locations (Linux `updaters/`, Windows `updaters/`,
macOS `Contents/Resources/updaters`) with current source.

## Verified working in this review

- `make gate`: ruff, format, fixtures, models, mypy strict, pytest (510 passed,
  9 skipped), web typecheck/tests/build, both e2e specs — exit 0.
- `make test-package`: 6,557 members, archive checks, bundled `bin/palm --help`
  — OK (container smoke skipped offline).
- Scoped updater/control/doctor/Sonic-platform tests: 29 passed.
- Update lifecycle on a packaged Linux layout: staging writes the correct plan
  (`app_root`, restart `[bin/palm, --window]`, helper under data root), Quit
  launches the helper, the helper swaps the new payload, and a corrupt asset
  rolls back to the old app. Uninstall plan uses the same install root.
- macOS layout: helper discovery from `Contents/Resources/updaters`, install
  root `PALM.app`, whole-bundle swap preserves the wrapper and installs the new
  payload, uninstall removes the bundle and keeps the data root.
- B1 Windows write path: with the packaged Windows Python under Wine,
  `import_media`, `ProjectStore.create/get`, and `import_routes.import_source`
  all succeed (no `PermissionError`, no generic 500 path).
- B6: packaged Windows `default_backend()` returns `SonicAnnotatorBackend` with
  `<data>/tools/sonic-annotator-1.7.0/sonic-annotator.exe` and
  `<data>/tools/vamp-plugins`, and the missing-tools error names PALM Setup; the
  fake-Sonic server test passes for win32 and darwin.
- M1: packaged/current-source server returns `café demo` for raw UTF-8 and
  percent-encoded multipart filenames with HTTP 201.

## Required before release

1. Fix R1 (copy both helpers / self-contained uninstall helper) and re-run the
   fresh-install uninstall flow end to end, including data preservation.
2. Fix R2 (helper interpreter outside `app_root`, Windows-safe liveness check,
   stop the server before the quit-time helper, log helper output) and verify on
   native Windows that update swaps with rollback and uninstall removes the app
   without deleting data.
3. Fix R3/R4 (restart execution and plan/asset cleanup) and R5 (auto-quit or
   longer wait); add tests for second-quit behaviour and restart.
4. Add the native Windows durable-write smoke (R6), fix L1/L2, rebuild all three
   artifacts and re-run `make gate` / `make test-package`.
5. Re-run the native Windows/macOS acceptance checklists before promoting the
   beta/experimental labels or publishing.

No product code was modified by this review; the only file added is this report.

## Limitations

- No native Windows or macOS host was available. Windows behaviour was tested
  with the packaged Windows CPython under Wine; Wine cannot reproduce Windows
  executable-image locking, so R2's delete/rename failure is reasoned from
  Windows semantics and needs native evidence.
- Real UAC/Inno Setup, SmartScreen, macOS Gatekeeper/Tk and native analysis
  execution were not run.
- The t137 CI run referenced in its note was not re-run here (no network); B8 was
  verified from the workflow and packaging code only.
- `dist/` artifacts are partially stale (see Artifact note); `make test-package`
  validates them, not a fresh package from `27bdf3a`.
