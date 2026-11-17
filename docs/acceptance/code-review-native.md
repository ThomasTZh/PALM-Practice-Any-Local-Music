# Independent all-platform code review: native portable flow

Status: **RELEASE BLOCKED** by the blockers below.

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t133 attempt 1 (`abc7e998-43dd-42ac-b798-404c1a2b43f3`)
- Reviewed revision: `4133cb9` on branch `t129-native-windows`, clean working tree
- Review host: Linux x86_64. Windows behaviour was exercised with the **packaged
  Windows CPython 3.11.15** under Wine 11.21. macOS cannot execute on this host,
  so its packaged tree was inspected only; native macOS runtime behaviour is
  listed as unverified.
- Verification run in this review:

```text
make gate         -> gate: ok; pytest 494 passed, 9 skipped
make test-package -> tar structure ok (6,559 members); bundled bin/palm --help ok;
                     container smoke skipped (ubuntu:22.04 image not present offline); OK
```

## Findings summary

| ID | Severity | Platforms | Area |
| --- | --- | --- | --- |
| B1 | blocker | Windows | Every durable write fsyncs a directory; Windows rejects it, so import/save/export fail |
| B2 | blocker | all | A staged update is never installed; the quit-time helper is never launched |
| B3 | blocker | all | Control-window Uninstall looks for `uninstall-helper.py`; the package ships `uninstall_helper.py` |
| B4 | blocker | macOS | Update/uninstall helper discovery looks inside the payload, helpers are outside it |
| B5 | blocker | macOS | Update swap maps `PALM.app/Contents` into the payload root; uninstall leaves the `.app` shell |
| B6 | blocker | Windows, macOS | No analysis backend exists; setup installs Sonic Annotator that nothing uses |
| B7 | high | Windows | Update/uninstall helpers run from `<app_root>/python`; Windows cannot rename/delete that tree |
| B8 | high | Windows release | Tag-triggered Windows package workflow cannot build `PALM.exe` (no MSVC environment) |
| M1 | medium | all | Multipart filenames are decoded as latin-1; non-ASCII upload names become mojibake |
| M2 | medium | Windows, macOS | `--doctor` requires the Linux-only Piper server, so it is permanently "degraded" |
| L1 | low | macOS | Builder README still says Finder opens Terminal.app |
| L2 | low | CI | `portable.yml` still downloads 7-Zip for a stale Vamp extraction report |
| L3 | low | docs | `LAUNCHER.md` says no binary is committed, but `packaging/windows/PALM.exe` is tracked |

## Blocking findings

### B1 Windows: directory fsync makes every durable write fail

**Files:** `src/basseparate/media.py:548-554` (`_fsync_directory`), called from
`media.py:571` (`atomic_write_bytes`), used by the import at `media.py:693`
and `media.py:715`; the same pattern is duplicated at
`src/basseparate/projects.py:216-220` (`_write_json_atomic`),
`src/basseparate/stems.py:463` and `stems.py:470-476`, and
`src/basseparate/export.py:384-390` and `export.py:441`.

**Problem:** each writer opens the destination *directory* with
`os.open(directory, os.O_RDONLY | O_DIRECTORY)` and calls `os.fsync`. POSIX allows
this; Windows does not: CPython's `os.open` does not pass
`FILE_FLAG_BACKUP_SEMANTICS`, so opening a directory raises
`PermissionError [Errno 13]`. `os.O_DIRECTORY` is 0 on Windows, so the
`getattr` fallback does not help. The exception escapes every write path:

- `import_media` writes the peak files and `asset.json` through
  `atomic_write_bytes` after decoding, so **WAV import still fails on Windows**
  (t132 only converted the resulting exception into the generic
  "Import failed unexpectedly" 500; it did not fix the cause).
- `ProjectStore.create`/`save` (`projects.py:257`, used for project creation and
  autosave) fail the same way, as do the analysis cache, the stem-cache publish
  and mixdown export.

**Reproduction** (packaged Windows runtime under Wine; the source tree and the
bundled interpreter are the ones shipped in `dist/PALM-0.1.0-dev-windows-x86_64.zip`):

```text
$ wine dist/palm-0.1.0-dev-windows-x86_64/python/python.exe Z:\tmp\wintest_atomic.py
ATOMIC FAIL PermissionError [Errno 13] Permission denied: 'C:\...\tmp...'

$ wine dist/palm-0.1.0-dev-windows-x86_64/python/python.exe Z:\tmp\wintest_project.py
PROJECT WRITE FAIL PermissionError [Errno 13] Permission denied: 'C:\...\tmp...'

$ wine dist/palm-0.1.0-dev-windows-x86_64/python/python.exe Z:\tmp\wintest_import.py
IMPORT FAIL PermissionError [Errno 13] Permission denied: 'C:\...\assets\5cad4c5066cbace0-8000-1'
```

(`wintest_import.py` calls the real `basseparate.media.import_media` with only
`probe_media`/`decode_to_pcm` stubbed, so the failure is the real write path.)

The same symptoms do not occur on Linux: the packaged Linux app imported a
48 kHz stereo WAV over `POST /api/library/import` with **HTTP 201** in this
review.

**Fix:** add one shared helper (for example `platform_support.fsync_directory`)
that returns immediately on Windows, or wraps only the directory open in
`try/except OSError` while keeping the file-handle fsync everywhere. Use it from
all four modules. Add a Windows test that imports a WAV and saves a project
(unit test with `sys.platform` simulated is not enough; run the import path in a
Windows CI job) so a regression cannot be masked by the generic 500 handler.

### B2 Staged update is never installed (all platforms)

**Files:** `src/basseparate/control.py:239-268`
(`check_for_updates`, `write_plan` at `control.py:265`), `control.py:195-199`
(`quit` only stops the controller and destroys Tk), and
`src/basseparate/updater.py:164-193` (`write_plan`) plus
`updater.py:201-226` (`launch_helper`). The documented behaviour is in
`docs/portable.md:93-98` and `README.md:138-140`.

**Evidence:** nothing ever launches the helper or consumes the plan:

```text
$ grep -rn "launch_helper" src/basseparate
src/basseparate/updater.py:201:def launch_helper(

$ grep -rn "pending" src/basseparate --include=*.py   # only peaks/persist state
src/basseparate/updater.py:172/175                    # plan is written, never read
```

`launch_helper` has no caller outside its unit test; `<data>/updates/pending.json`
is only ever written (`updater.py:175`). Quitting PALM therefore does nothing,
and the message "Update X staged; quit PALM to install and restart" is false on
Linux, Windows and macOS.

**Fix:** when the control window quits, check for
`<data>/updates/pending.json` and call `updater.launch_helper(plan)` before
`root.destroy()` (the helper already waits on the recorded pid); alternatively
launch it from `check_for_updates` with a plan that waits for this process.
Delete the plan when staging/launching fails, surface helper errors, and add a
test that a quit with a pending plan launches the helper.

### B3 Control-window Uninstall cannot find or run its helper (all platforms)

**Files:** `src/basseparate/control.py:306` looks up `uninstall-helper.py`
(hyphen), `control.py:212` repeats the same hyphenated default, while the
package ships `updaters/uninstall_helper.py` (`scripts/package.py:71`,
`scripts/package_windows.py:63`, `scripts/package_macos.py:61`). In addition,
`packaging/updaters/uninstall_helper.py:13` does `from update_helper import main`,
but `control.py:227-236` (`_external_helper`) copies only the single requested
file into `<data>/updates/helpers/`.

**Evidence** (packaged Linux layout in this workspace):

```text
$ ls dist/palm-0.1.0-dev-linux-x86_64/updaters
uninstall_helper.py  update_helper.py

helper: .../dist/uninstall-helper.py exists: False
UpdateError: uninstall helper is missing: .../dist/uninstall-helper.py
```

and, with the correctly named file alone:

```text
$ cp packaging/updaters/uninstall_helper.py /tmp/x/ && python3 /tmp/x/uninstall_helper.py --plan /nonexistent
ModuleNotFoundError: No module named 'update_helper'
```

So the control window reports `Uninstall failed: uninstall helper is missing`
on every platform; even after renaming it, the copied helper cannot import its
sibling. The existing tests use injected `uninstall_action` callbacks or create
the hyphenated file themselves (`tests/unit/test_updater/test_updater.py:255`),
which is why the gate stays green.

**Fix:** use `uninstall_helper.py` consistently (keep a hyphenated fallback only
if an old install may have it), copy both helper files (or make
`uninstall_helper.py` self-contained), and test the real packaged directory:
copy the packaged helper set into a scratch data root, run it with a plan, and
assert the app folder is removed.

### B4 macOS: update/uninstall helper discovery looks in the payload, helpers live outside it

**Files:** `src/basseparate/control.py:227-236` (source
`paths.runtime.app_root / "updaters" / name`, fallback `app_root.parent / name`),
`scripts/package_macos.py:283-287` and `:60-61` (helpers are installed under
`PALM.app/Contents/Resources/updaters`), and the macOS launcher sets
`PALM_APP_ROOT=Contents/Resources/app` (`packaging/macos` launcher in the
artifact). `dist/.../PALM.app/Contents/Resources/app` contains no `updaters/`.

**Evidence:**

```text
app_root: .../PALM.app/Contents/Resources/app
update_helper.py    -> .../PALM.app/Contents/Resources/update_helper.py    exists: False
uninstall_helper.py -> .../PALM.app/Contents/Resources/uninstall_helper.py exists: False
real updaters:      .../PALM.app/Contents/Resources/updaters/{update_helper,uninstall_helper}.py
```

Consequently `check_for_updates` downloads and hashes the asset and then
returns "Update is available but the external update helper is missing", and
Uninstall raises the B3 error. macOS update and uninstall cannot work at all.
The artifact is also inconsistent with the package check that requires
`Contents/Resources/updaters/...`.

**Fix:** give `RuntimePaths` an explicit helper root (preferred), or search
`app_root/"updaters"` and then `app_root.parent/"updaters"`; add a packaging
test that runs the lookup with the real macOS layout (`PALM_APP_ROOT` pointing at
`Contents/Resources/app`).

### B5 macOS: update swap corrupts the payload and uninstall leaves the app shell

**Files:** `packaging/updaters/update_helper.py:43-61` (`_extract`), `:63-104`
(`swap_app`), `:84-91` (rename then move children), `:105-125` (`uninstall`);
`packaging/install.json:12-15` (macOS channel kind `zip` and asset
`PALM-{version}-macos-arm64.zip`); `scripts/package_macos.py:259` (payload at
`Contents/Resources/app`); `control.py:212`/`:306` set the plan `app_root` from
`RuntimePaths.app_root`.

**Problem:** the plan `app_root` is `PALM.app/Contents/Resources/app`, but the
macOS update asset is the whole `PALM.app` ZIP. `_extract` sees one directory
(`PALM.app`) and returns it; `swap_app` then moves that directory's children
(`Contents`) into `Resources/app`, producing
`Resources/app/Contents/{MacOS,Resources,Info.plist}`, and deletes the previous
payload after "success". PALM.app then cannot start (`palm: portable app payload
not found at .../Resources/app`). The rollback path only covers exceptions, not
this wrong-layout success. Equally, `uninstall` runs `shutil.rmtree(app_root)`
against `Resources/app`, so the `.app` bundle (launcher, `Info.plist`,
`updaters/`) is left behind.

**Fix:** make the macOS update unit the bundle: carry a distinct `bundle_root`
(`.../Resources` or `PALM.app`) in the plan and replace/rollback that whole
bundle, or publish a macOS update payload whose archive root is the
`Resources/app` content (and keep the bundle files untouched). Uninstall should
remove the bundle root as well as the payload. Add a macOS packaging test that
applies a fake update ZIP and asserts the resulting
`PALM.app/Contents/Resources/app/bin/palm` exists.

### B6 Windows/macOS: no analysis backend; setup installs tools nothing uses

**Files:** `src/basseparate/analysis_backend.py:203-215`
(`default_backend` raises `AnalysisBackendUnavailable` on every non-Linux
platform); no production caller constructs `SonicAnnotatorBackend`
(`src/basseparate/sonic_annotator.py:257`, binary path at `:52-53` is the Linux
AppImage layout) — only tests do. At the same time the recommended setup
installs Sonic Annotator and the Vamp Plugin Pack on Windows/macOS
(`src/basseparate/setup/tool_assets.py:349-370`), and the beta acceptance
checklists require audio analysis to return key/BPM/chords/bars
(`docs/acceptance/windows-beta.md:138-151,275`;
`docs/acceptance/macos-experimental.md:128-139,266`).

**Evidence:**

```text
$ wine dist/palm-0.1.0-dev-windows-x86_64/python/python.exe Z:\tmp\wintest_analysis.py
ANALYSIS FAIL AnalysisBackendUnavailable no analysis backend is implemented for win32;
the Piper backend is available on Linux
```

The same exception path applies to macOS. The analysis job therefore fails for
any project on both platforms, and the downloaded Sonic Annotator/Vamp tools
are never invoked. `--doctor` also reports the Vamp pack as installed after
setup, which makes the failure look like a random analysis error.

**Fix:** either wire a platform-general Sonic Annotator backend as the default on
Windows/macOS (resolve `sonic-annotator[.exe]` under
`data/tools/sonic-annotator-1.7.0`, point `VAMP_PATH` at
`data/tools/vamp-plugins`, and give it a writable session home), or mark
analysis unsupported there and remove analysis tools from the recommended
install, docs and acceptance checklists until it exists. A platform matrix test
that calls `features.analyze_signal` on a fixture would have caught this.

### B7 Windows: update/uninstall helpers run from inside the tree they replace

**Files:** `src/basseparate/updater.py:214` and `:293` launch the helpers with
`python or sys.executable`; in the packaged Windows app that is
`<app_root>/python/pythonw.exe`. `packaging/updaters/update_helper.py:84`
renames `app_root` and `:116` deletes `app_root` with `shutil.rmtree`. Helper
stdout/stderr are sent to `DEVNULL` (`updater.py:218-224`, `:296-302`), so any
failure is silent.

**Problem:** Windows refuses to rename or delete a directory that contains a
loaded executable image. The helper's own interpreter loads `python311.dll`
and `pythonw.exe` from `<app_root>/python`, so `app_root.rename(backup)` and
`shutil.rmtree(app_root)` fail with a sharing violation even when the app's
server has already stopped; the helper exits non-zero and the user sees the
"Uninstall helper launched" message with nothing removed. (Wine cannot
reproduce Windows sharing semantics — a rename under Wine succeeds — so this
must be validated on native Windows.)

**Fix:** launch the helper from an interpreter that lives outside `app_root`
(copy the minimal runtime under the data root, or use a small `cmd`/PowerShell
script for the Windows swap/delete), and log helper output to
`<data>/logs/updater.log` instead of discarding it. Verify with a native
Windows test that an update and an uninstall actually replace/remove the app
folder.

### B8 Windows tag-release workflow cannot build `PALM.exe`

**Files:** `.github/workflows/windows-package.yml:30-36` runs
`python scripts/package_windows.py --online`; on Windows
`scripts/package_windows.py:236-250` executes
`packaging/windows/build_launcher.ps1`, which throws when `cl.exe` is not on
PATH (`packaging/windows/build_launcher.ps1:13-15`). The workflow never sets up
the MSVC environment, unlike `portable.yml:118-123`
(`ilammy/msvc-dev-cmd@v1`). The build then raises
`PackageError("building PALM.exe from palm_launcher.c failed")`.

**Impact:** the tag-triggered Windows release job fails before producing the
ZIP; the verified `PALM.exe` fix (t129) cannot be released through that
workflow.

**Fix:** add the `ilammy/msvc-dev-cmd@v1` step (arch x64) before
`Build Windows ZIP` in `windows-package.yml`, or make `build_launcher` fall back
to the committed `packaging/windows/PALM.exe` with a logged warning when `cl.exe`
is unavailable. Harden with an assertion that a freshly built `PALM.exe` has the
GUI subsystem.

## Non-blocking findings

### M1 Non-ASCII multipart filenames become mojibake

**Files:** `src/basseparate/api/uploads.py:150` decodes every header line as
latin-1, then `safe_filename` (`uploads.py:70-76`) and
`src/basseparate/api/import_routes.py:182` use the result as the project name.
Browsers send the multipart `filename` parameter as raw UTF-8 bytes, so
`café demo.wav` becomes `cafÃ© demo.wav`. The new test at
`tests/integration/test_import/test_import_errors.py:56` covers only the JSON
path import, not a multipart upload, so the gap is not caught.

**Evidence:** packaged Linux app, `curl -F "file=@/tmp/café demo.wav"` against
`/api/library/import` returned `HTTP 201` with
`"title":"cafÃ© demo"`.

**Fix:** decode the filename value as UTF-8 when the latin-1 bytes form valid
UTF-8 (`raw.encode("latin-1", "strict").decode("utf-8")` with fallback), support
RFC 5987 `filename*`, and add a multipart test with a UTF-8 filename.

### M2 `--doctor` is permanently degraded on Windows/macOS after a successful setup

**Files:** `src/basseparate/doctor.py:111` resolves the Linux-only
`sv/squashfs-root/.../piper-vamp-simple-server`; `_check_piper`
(`doctor.py:341-369`) marks it **required** (unlike the optional native-host and
SDK checks), so no Windows/macOS install can ever satisfy it. Packaged mode
also reports source-only assets as missing (`doctor.py:90-95`, `:120`:
`third_party/emsdk`, `third_party/signalsmith-stretch`, `audio2test`), which
were visible in this review's packaged Linux run.

**Impact:** support diagnostics claim the install is degraded even after setup
succeeds, obscuring real missing pieces (and, on these platforms, the missing
analysis backend).

**Fix:** make the Piper/Vamp-server check Linux-only (or optional), key the
development-only checks on `runtime.mode == "source"` (show "not applicable" in
packaged mode), and add a doctor test for a complete packaged layout.

## Low-severity notes

- **L1** `packaging/macos/README.md:38` still says Finder "opens Terminal.app
  through `osascript` for logs and Ctrl+C". The user-facing docs
  (`docs/portable.md:140`) correctly describe the no-terminal control
  window. This builder README should be updated or removed.
- **L2** `portable.yml:164-176` still downloads `7zr.exe`/`7z2606-extra.7z` for
  a "Windows Vamp extraction report" that does not exercise the product path.
  t130 removed the 7-Zip product path; this CI step and its `dist/vamp-extraction.txt`
  output are stale and keep an unmanifested download in CI.
- **L3** `packaging/windows/LAUNCHER.md:17` says "No binary is committed to
  git", but `packaging/windows/PALM.exe` is tracked (SHA-256
  `44c9acdc…`) and is the non-Windows packaging fallback
  (`scripts/package_windows.py:251-255`). Either state the binary is the
  verified fallback or rebuild it in CI only.

## What was verified as working

- `make gate`: ruff, format, fixtures, models, mypy, pytest (494 passed,
  9 skipped), web typecheck/tests/build, both e2e specs — exit 0.
- `make test-package`: 6,559 members, structure/checksums, bundled
  `bin/palm --help` — OK (container smoke skipped offline).
- Packaged Linux control window: bundled Python + Tk 9.0.3 opened
  `ControlWindow`, started the server, showed `Running at ...`, and quit cleanly.
- Packaged Linux import: real 48 kHz stereo WAV over multipart upload returned
  **201** with decoded peaks/asset file (the B1 symptom is Windows-only).
- Packaged Windows launcher: `PALM.exe` (PE32+ GUI) under Wine started
  `pythonw.exe`, wrote `run/server.json` for a clean data root, and
  `GET /api/health` returned `{"status":"ok","version":"0.1.0-dev","ui":true}`.
  This confirms t129's environment/message-box path at least under Wine;
  native Windows launch still needs the owner checklist.
- Windows ZIP contents: `PALM.exe`, `python/python.exe`, `bin/uv.exe`,
  `updaters/`, `licenses/third_party`, `install.json`; modes/`create_system`
  match the package checks.
- Package audit/licence/update tests in the gate; the manifest, notices and
  media pins cross-checks pass.
- t130's Inno command construction, UAC-denial branch, DLL verification and
  standard-directory fallback are covered by unit tests with a fake runner;
  the live elevated installer cannot be exercised on this host, so native
  Windows UAC/Inno evidence is still required.
- t132's Linux error mapping behaves as designed: missing/non-executable
  ffprobe/ffmpeg return actionable 400s, malformed audio returns 400, and only
  unexpected exceptions produce the generic 500.

## Required before release

1. Fix B1 and add a Windows end-to-end import/save/export test (the Windows
   ZIP must be exercised, not only `tests/unit/test_platform_support` and
   `tests/integration/test_package_windows`).
2. Fix B2, B3, B4 and B7 together, then verify on Linux, Windows and macOS
   that: Check for updates stages, Quit swaps with rollback, the app restarts,
   and Uninstall removes the app while keeping the data root. Helper output must
   be logged, not discarded.
3. Fix B5 and validate with the real macOS bundle layout (update and uninstall).
4. Resolve B6: wire the Sonic Annotator backend on Windows/macOS or declare
   analysis unsupported and remove its tools from the setup/docs/checklists.
5. Fix B8 so the tag workflow produces the Windows artifact.
6. Fix M1/M2, refresh L1/L2/L3, then repeat `make gate`, `make test-package`,
   and the native Windows/macOS acceptance checklists before promoting either
   beta/experimental label or publishing artifacts.

No product code was modified by this review; the only file changed is this
report.

## Review limitations

- macOS runtime, Gatekeeper, Tk window and native uninstall/update were not
  executed (no macOS host). B5 is derived from the packaged tree plus the
  updater/package code, not from a live run.
- Windows UAC consent, the real Inno Setup silent install, and Windows
  executable-image locking (B7) cannot be reproduced under Wine; B7 relies on
  documented Windows sharing semantics and needs native evidence.
- The browser-originated multipart filename behaviour was reproduced with
  `curl`, which sends the same raw UTF-8 `filename` bytes that browsers send;
  it was not exercised through Chrome/Firefox in this review.
- The release manifest URL (`releases/latest/download/release.json`) and the
  GitHub release were not exercised; no release exists yet in this workspace.
