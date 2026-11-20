# Final packaging release review: analysis-blocked beta

Status: **PASS** — no release blockers for the stated scope: a conventional
Linux/Windows/macOS packaging release where **Windows analysis is explicitly
blocked** while the 64-bit Vamp bundle is rebuilt. The task contract explicitly
does not require a Vamp bundle or silent Windows analysis for this beta.

- Reviewer: `reviewer` (independent; no product code edited)
- Task: t161 attempt 1 (`3f1869f6-2a3c-4c7f-a015-760c85306b94`), reviewed t160
- Reviewed revision: `75347b4` on `t156-release-docs`; tree clean apart from
  temporary logs.
- Scope: Windows beta is analysis-blocked; Windows install/playback/separation
  are expected, Windows chord/key/BPM/bar analysis is explicitly out of scope.

## Commands and results

```text
make gate                              -> PASS: 506 passed, 11 skipped
make test-package                      -> PASS: 6,553 members; bundled bin/palm --help
scripts/package_windows.py --check     -> PASS: 5,000 entries
scripts/package_macos.py --check       -> PASS: 3,836 entries
scoped package/setup/licence tests     -> 65 passed, 2 skipped (native-only)
```

All three portable archives were rebuilt at `75347b4` and inspected directly.

## t159 residuals verified fixed

### 1. Windows setup no longer offers Vamp/Sonic

- `tools_status()` returns an empty mapping on Windows
  (`src/basseparate/setup/tools.py:70-77`).
- `install_tools()` refuses Windows with the analysis-blocked message
  (`src/basseparate/setup/tools.py:116-123`).
- The Windows branch of `SetupWizard` renders only **Analysis temporarily
  unavailable** (`web/src/panels/setup/SetupWizard.tsx:781-797`); it does not
  render the tool list, AGPL/Vamp links, or GPL/AGPL consent checkbox.
- Licence components exclude the tool group on Windows
  (`web/src/state/setup.ts:390-...`).
- The Windows UI test asserts no Vamp/Sonic component, AGPL text or consent.
- `docs/acceptance/windows-beta.md:85-91` lists only managed FFmpeg, CPU and
  Demucs and states no Vamp/Sonic component or licence is offered; the checklist
  (`:257-264`) expects import/playback/separation and an analysis blocker, not
  analysis. UI and kit agree.

### 2. Managed FFmpeg wording

- `packaging/release-notes.md:69-70` and `docs/troubleshooting.md:129-130`
  describe managed FFmpeg/FFprobe downloaded and verified by setup, not external
  prerequisites.
- The root README, `docs/portable.md`, macOS/Windows packaging READMEs and the
  rebuilt `RELEASE-NOTES.md` files all use managed wording; no positive
  "install FFmpeg first" claim remains.
- Rebuilt artifacts contain no external-prerequisite text.

### 3. Analysis-blocked beta labels

The release is consistently labelled a Windows analysis-blocked beta:

- `README.md:46-48,121-124` (Windows analysis temporarily blocked; Linux/macOS
  tools only);
- `docs/portable.md:120-123,156-178` (Windows analysis explicitly unavailable);
- `packaging/release-notes.md:46-49,69-70` (Windows analysis unavailable;
  managed FFmpeg on macOS);
- `packaging/windows/README.md:37-41` (blocker; no admin/GUI/manual path);
- `docs/acceptance/windows-beta.md:89-91,120-125,137-149,261-264` (blocker,
  import/playback/separation only; no chord/key/BPM claim);
- setup UI Windows branch shows the blocker and no tools.

No document claims Windows analysis is available or that a GUI pack/UAC path is
supported.

### 4. Checksums and release payloads

- `scripts/release_checksums.py` is committed; all three packagers merge/prune a
  shared `dist/SHA256SUMS` instead of overwriting it.
- Sequential Linux + Windows + macOS builds produced one manifest containing
  all three assets:
  `PALM-...-linux-x86_64.tar.gz`, `PALM-...-windows-x86_64.zip`,
  `PALM-...-macos-arm64.zip`; `test_dist_checksum_manifest_covers_all_present_platform_assets`
  passes.
- `make test-package` passes on the Linux tar (6,553 members; bundled launcher
  help).
- Windows/macOS ZIP checks pass (5,000/3,836 entries); `install.json` channels
  are `windows-x86_64`/`macos-arm64`/`linux-x86_64`; executable modes are 0755
  for `bin/palm`, `bin/uv`, `PALM.exe` and the macOS wrapper/binaries.
- No updater/uninstall-helper, FFmpeg, Sonic Annotator, Vamp plugin, model or
  tool payload is present outside the licence tree.
- Licence trees and manifest are present in all artifacts; package/licence
  audit tests pass.
- The macOS tag workflow uploads and verifies `SHA256SUMS`; the Windows tag
  workflow writes/uploads ZIP+installer+SHA; `portable.yml` retains the
  cross-platform artifact upload.

### 5. Installer/DMG/tar, no-helper, native checks

- `PALM.iss` remains the per-user installer (lowest privileges, localappdata,
  stable AppId, shortcuts, app-only default uninstall, optional launch); the
  native installer test is present and skips on Linux.
- macOS `build_dmg` creates the `Applications` link and preserves modes; the
  native mount test skips on Linux.
- Linux tar is rebuilt and checked.
- No custom updater/uninstall helper exists in source, tests or artifacts;
  control Check for updates is instruction-only.
- Stem gating and WinError 10038 tests remain green in the full gate.

### 6. No release/tag

No new tag or release was created; only the pre-existing
`legacy-studio`/`plugins-win64-v1`/`v0.1.0-dev` tags exist. No installer/DMG
artifact is committed or present in `dist` (they are built by CI on their native
runners).

## Residual limitations (non-blocking)

- No native Windows/macOS host in this review. The Inno installer and DMG mount
  tests skip locally; the t156 native tag CI run 44755837163 was not re-run.
  Installer/DMG contracts, source and CI definitions were inspected; the rebuilt
  portable archives were checked directly.
- The interactive "also delete data" uninstall choice remains a documented
  manual acceptance step; the automated native test covers install, launch,
  upgrade, silent uninstall and keep-data. This is explicit in the release notes
  and Windows README and is not a blocker for the analysis-blocked beta.
- `dist/` is rebuilt for validation only; no release artifact was published.

## Verdict

**PASS.** All t159 residuals are fixed, checksums/portable payloads/no-helper
policy and the analysis-blocked Windows scope are coherent, and no release
blocker remains for the stated scope. No product code was edited; this report is
the only file added by the review.
