# Cross-platform portable release review

Status: **NEEDS MANUAL EVIDENCE — Linux supported; Windows x64 beta and macOS
Apple Silicon experimental remain unaccepted; Windows/macOS artifacts are held.**

Reviewer: audio. Reviewed task: t116; final gate task: t119.

This is not an acceptance of Windows or macOS. The packages build and the
automated checks pass, but the required real laptop/Mac checklist evidence is
absent and the user-facing guide still describes the pre-no-terminal UX.

## Support labels

- Linux x86_64 tar: **Supported**.
- Windows x64 ZIP: **Beta, CPU only, unsigned, no-admin, acceptance pending**.
- macOS Apple Silicon app: **Experimental, CPU-only, unsigned/not notarized,
  acceptance pending**.
- The Windows and macOS acceptance kits are `Status: NOT RUN`. Do not promote
  either label or publish either artifact until the owner supplies the
  checklist evidence.

## Automated evidence

```text
make gate          -> 486 passed, 9 skipped, exit 0
make test-package  -> 6,559 members, bundled bin/palm --help, OK
```

The gate included the licence/package/update audits, the platform tests, the
control-window wiring tests, web tests/build and both browser e2e specs.

Package contents checked in the local final build:

| Artifact | Contents evidence |
| --- | --- |
| Linux tar | bundled Python/uv, `bin/palm`, `install.json`, update/uninstall helpers, full `licenses/third_party` tree |
| Windows ZIP | `PALM.exe`, `palm.cmd` diagnostic fallback, embedded `python.exe`/`uv.exe`, `install.json`, updaters, full licence tree |
| macOS ZIP | `PALM.app`, `Contents/MacOS/palm`, embedded arm64 Python/uv, `install.json`, updaters, full licence tree |

No model weights, FFmpeg/FFprobe binaries, Sonic Annotator/Vamp plugins or
Python inference environments are bundled. The licence screen and bundled
component texts are covered by the web tests; managed FFmpeg and automatic
Vamp installation are covered by setup tests. `run_control` now supplies real
update and uninstall callbacks, and the control tests cover no-update, network
error, verified staging, uninstall confirmation/cancel and Quit.

The CI run reported in `packaging/VERIFICATION.md` (43972664919) built and
smoke-tested the Linux, Windows and macOS artifacts, but it is build/CI
evidence, not the owner's manual acceptance run.

## Blocking findings

1. **No real Windows laptop or Apple Silicon Mac evidence.** Both acceptance
   kits are explicitly `Status: NOT RUN`. There is no manual evidence for
   double-click launch without a terminal, licence/consent flow, managed
   FFmpeg, automatic Vamp install, setup, CPU analysis, separation, browser
   playback, control-window Quit, update check or uninstall on native hardware.
   Windows: [windows-beta.md](windows-beta.md). macOS:
   [macos-experimental.md](macos-experimental.md).
2. **The user-facing guide still describes the previous terminal/FFmpeg UX.**
   [docs/portable.md](../portable.md) says to run `palm.cmd` (line 104), opens a
   console (lines 110-112), requires the user to install FFmpeg and set
   `PALM_FFMPEG`/`PALM_FFPROBE` (lines 116-118 and 168-172), and says macOS
   opens Terminal.app (lines 135-138). [README.md](../../README.md) still says
   Windows users should run `palm.cmd` (line 70) and that FFmpeg/ffprobe must
   already be installed (lines 82-85). This contradicts the no-terminal
   `PALM.exe`/`PALM.app` control-window UX and the managed-FFmpeg acceptance
   criterion, and would lead users to do manual work the product now removes.
3. **No native data-preservation/rollback evidence for update and uninstall.**
   The code and CI tests stage an update outside the app and launch an external
   helper; the unit tests cover callbacks and staging. There is no real
   Windows/macOS run showing an update swap/rollback, or an uninstall that
   preserves projects/models/tools by default. Treat the control-window update
   and uninstall as unaccepted until that evidence exists.
4. **No native no-terminal launch confirmation.** `PALM.exe`/`PALM.app` and the
   control window are present in the packages and the Linux/CI fakes pass, but
   no real desktop run has shown the window opening without a terminal, the
   browser opening, or the process stopping cleanly. This is part of blocker 1,
   called out separately because it is the central UX promise.

## Required before promotion

1. Update [docs/portable.md](../portable.md) and [README.md](../../README.md)
   to the no-terminal `PALM.exe`/`PALM.app` control-window flow, managed
   FFmpeg/FFprobe and automatic analysis-tool installation. Remove the
   `palm.cmd`, external-FFmpeg and macOS-Terminal instructions from the normal
   path.
2. Run [windows-beta.md](windows-beta.md) on the owner's Windows laptop and
   [macos-experimental.md](macos-experimental.md) on Apple Silicon. Attach
   screenshots, View logs tails, exact artifact hashes and every PASS/FAIL item.
3. Include a native update-check result and a native uninstall that preserves
   data, plus the rollback/recovery result if an update is installed.
4. Only after those pass, promote the labels and publish the Windows/macOS
   assets with checksums. Until then the labels remain beta/experimental and
   the artifacts remain held.
