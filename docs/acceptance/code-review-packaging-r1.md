# Independent packaging release review: installer, DMG and lifecycle

Status: **RELEASE BLOCKED** — packaging documentation and Windows Vamp consent
still contradict the shipped product; two blockers plus release-evidence gaps.

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t152 attempt 1 (`d3765000-bfbc-4312-9a31-a0fd092a919e`), reviewed task t146
- Reviewed revision: `7d1ca91` on branch `plugins-win64-t154` (all packaging
  dependency commits are ancestors: t145 `16dacbb`, t146 `74fc78c`, t147
  `eb8ae73`/DMG, t148 `ce4c8b2`, t149 `b997ca8`, t150 `ea8a325`, t151 `58e60c3`,
  t154 `7d1ca91`).
- Review host: Linux x86_64. Native Windows/macOS installers could not be run
  here; their contracts, scripts and CI definitions were inspected, and the
  rebuilt Linux/Windows/macOS artifacts were checked directly.

## Commands and results

```text
make gate                      -> gate: ok; pytest 508 passed, 11 skipped
make test-package              -> tar structure ok (6,553 members); bundled bin/palm --help ok; OK
scripts/package_windows.py --check -> 4,999 entries, required content present
scripts/package_macos.py --check   -> 3,835 entries, required content present
scoped packaging/licence/lifecycle pytest -> 90 passed, 2 skipped
  (native Inno installer test and native DMG mount test are platform-skipped on Linux)
```

## What was verified as correct

- **No custom updater/uninstaller remains in the runtime or packages.**
  `src/basseparate/updater.py`, `packaging/updaters/` and their tests are gone;
  the control window exposes only Open browser, View logs, Quit and Check for
  updates; all three artifacts contain no `updater`/`uninstall-helper` entries.
- **Check for updates is instruction-only.** `control.py:160-199` reads
  `install.json`, opens the matching release/tag page and never downloads,
  swaps or restarts; `test_check_for_updates_opens_release_page` covers it.
- **Linux tar**: 6,553 members, `bin/palm`/`bin/uv` 0755, `install.json`,
  `licenses/LICENSE`, `NOTICES.md`, `licenses/third_party/manifest.json`;
  `make test-package` and `bin/palm --help` pass; no tools/models/helpers.
- **Windows ZIP**: 4,999 entries, `PALM.exe`/`python.exe`/`uv.exe` 0755,
  `install.json`, full licence tree, no FFmpeg/Sonic/Vamp/model payload;
  `package_windows.py --check` passes.
- **macOS ZIP**: 3,835 entries, `Contents/MacOS/palm`, `bin/palm`, `bin/uv`,
  `python/bin/python3.11` all 0755, `install.json`, licence tree, no
  tools/models; `package_macos.py --check` passes. DMG build code creates the
  `Applications` symlink and the native mount test asserts it and the wrapper
  mode.
- **Windows installer contract**: `PALM.iss` uses
  `PrivilegesRequired=lowest`, `{localappdata}\Programs\PALM`, stable `AppId`,
  Start Menu/desktop shortcuts, `CloseApplications`, optional launch, and an
  interactive uninstall choice that defaults to keeping data; silent uninstall
  never deletes data. `package_windows.py` builds it from the same staged
  payload as the ZIP; static tests and the native CI contract test cover the
  script.
- **Separation gating**: `separation_setup_problem`/`SeparationSetupError` give
  Open Setup 409s for missing managed environment/worker/model/media tools,
  Demucs falls back to the managed CPU environment, and partial media-tool
  recovery reuses installed tools. `tests/integration/test_stems/test_setup_gate.py`
  and media recovery tests pass.
- **WinError 10038**: `_safe_close`/`_closed_socket_error` suppress only
  closed-socket/EBADF cases, re-raise unrelated errors, log context, and browser
  launch OSErrors are logged; scoped tests pass.
- **Windows Vamp**: t154 installs the pinned `vamp-plugins-win64.zip`
  (SHA-256 verified, PE32+ x86-64 check, required QM/Chordino DLLs and catalogs,
  Sonic `--list` plugin-id verification) with no GUI installer/UAC. The
  manifest/licence audit and setup tests pass.

## Blockers

### P1 — Linux release artifact ships obsolete README and release notes

**Files:** `packaging/README.release.md:18,60-61,126-135,149`;
`scripts/package.py:303` copies it to `stage/README.md`;
`scripts/package.py:418-447` generates `RELEASE-NOTES.md` (terminal launch at
`:426-429`).

**Evidence** (extracted from the current
`dist/PALM-0.1.0-dev-linux-x86_64.tar.gz`):

```text
README.md contains:
  "3. A terminal window opens with the server log..."
  "`ffmpeg` and `ffprobe` must already be installed."
  "rm -rf ~/.local/share/palm"            # presented as the uninstall step
  "Linux x86_64 only in this build. Windows and macOS are not packaged."
RELEASE-NOTES.md contains:
  "Launch: bin/palm ... It opens a terminal..."
```

This contradicts the supported flow: the Linux launcher opens the control
window, managed FFmpeg/FFprobe are installed by setup, Windows installer/DMG
assets exist, and uninstall is OS-level with the data root preserved unless the
user explicitly removes it. Following the packaged README can make users
install an unnecessary external FFmpeg and delete projects during "uninstall".
The Windows/macOS packages correctly use the updated root `README.md`
(`package_windows.py:298`, `package_macos.py:282`); only the Linux artifact is
stale.

**Fix:** copy the root `README.md` (or update `README.release.md`) for the Linux
tar, regenerate `RELEASE-NOTES.md` from the current docs/build, and add an
artifact-content test asserting the packaged README does not contain the stale
terminal/external-FFmpeg/Linux-only/data-deletion statements.

### P2 — Windows Vamp consent/UI still describes the retired GUI pack and UAC

**Files:** `web/src/panels/setup/SetupWizard.tsx:787-790` (UAC prompt),
`web/src/panels/setup/SetupWizard.tsx:784-785` (GPL/AGPL pack);
`web/src/state/setup.ts:110-112` (AGPL licence + c4dm source links);
`src/basseparate/setup/tools.py:44-47,81-85` (tool status says AGPL pack);
`packaging/windows/README.md:40-41`; `packaging/release-notes.md:49`;
`docs/acceptance/windows-beta.md:122`.

The actual Windows setup downloads the pinned PALM `vamp-plugins-win64.zip`
(`src/basseparate/setup/tool_assets.py:73-83`) containing `qm-vamp-plugins.dll`
and `nnls-chroma.dll`, verifies PE32+ and the Sonic plugin ids
(`tool_assets.py:184-186,247-281`), and never runs an Inno/UAC installer or the
GUI Vamp Plugin Pack. The licence manifest correctly lists
`palm-vamp-plugins-win64` as GPL-2.0-or-later with the project source offer
(`licenses/third_party/manifest.json:250+`, `THIRD_PARTY_DOWNLOADS.md:110`), but
the setup page tells users to approve a UAC prompt and links an AGPL pack and
c4dm/qm source that is not what is installed. The UI test at
`SetupWizard.test.tsx:145-148` enshrines the stale UAC text.

**Fix:** make the tool name/licence/source links platform-aware (Windows:
GPL-2.0-or-later PALM bundle and its release/source offer; Linux/macOS: existing
pack metadata), remove the UAC note and its test, and update the Windows README,
acceptance kit and release notes accordingly.

## High/medium findings

### M1 — Release notes are stale and internally contradictory

**File:** `packaging/release-notes.md:36,49,51-55,68`.

- Linux asset is listed as 70,044,949 B / `c1a6edfc…`; the current
  `dist/PALM-0.1.0-dev-linux-x86_64.tar.gz` is 70,439,210 B /
  `a819423c…` (`dist/SHA256SUMS`).
- Windows says "Vamp setup may show one UAC prompt" (false after t154) and
  "extract below the user profile and run PALM.exe" (the installer is the
  primary asset).
- Windows and macOS sections still call FFmpeg/ffprobe "prerequisites" or
  "not bundled — use a trusted build", contradicting managed setup and the
  root README/docs.

**Fix:** regenerate the release notes from the final build (or make CI produce
them) and remove the external-FFmpeg/UAC/portable-only statements; add a check
that the hashes/sizes match `dist/SHA256SUMS`.

### M2 — Tag Windows workflow builds the installer but uploads nothing

**Files:** `.github/workflows/windows-package.yml:36-129` builds `PALM.exe`,
installs Inno, packages and smoke-tests, but has no upload step;
`.github/workflows/portable.yml:124-215` installs Inno, writes
`SHA256SUMS` including the installer and uploads ZIP+installer+SHA. The tag
workflow also does not upload the ZIP, so a release based on it has no Windows
assets at all.

**Fix:** either make `windows-package.yml` upload ZIP/installer/SHA like
`portable.yml`, or declare/point the release process at the `portable` matrix
and remove the duplicate tag workflow; add the installer to the tag artifact
contract.

### M3 — Installer launch and delete-data branch lack native evidence

**Files:** `tests/integration/test_package_windows/test_package_windows.py:162-206`
(native test covers silent install, upgrade, silent uninstall, Start Menu and
data kept; it does not launch the installed app and never exercises the
interactive "No" delete-data branch); `packaging/windows/PALM.iss:62-82` is the
only evidence for that branch (static contract at `test_package_windows.py:136-159`).

The task asks for tested install/launch/uninstall/data choice. The payload is
launched by the ZIP smoke and the delete branch is simple, but the exact
installer behaviors are not executed in CI. Either add a native
launch-after-install step and an interactive delete-data test (or an
explicitly documented manual step), or narrow the acceptance claim.

### M4 — Installer delete-data ignores custom data roots

**File:** `packaging/windows/PALM.iss:80-83` deletes only
`%LOCALAPPDATA%\palm`. Users who set `PALM_DATA_DIR` or `--data-dir` (documented
advanced overrides) keep their data when choosing "No"; the dialog wording
implies the practice data is removed. Document the limitation or resolve the
actual configured data root.

## Low findings

- **L1** `packaging/launcher/README.md:67-68,76-80,84-85` still describes terminal-emulator
  launch as the no-tty fallback; the normal file-manager/desktop path now opens
  the control window.
- **L2** `docs/portable.md:32` says every release provides
  `RELEASE-NOTES.md`; the Windows/macOS ZIPs do not contain it (only the Linux
  tar generates one), and the tag workflows do not upload it.
- **L3** `packaging/VERIFICATION.md` retains historical helper-era artifacts and
  hashes; it is evidence history, not shipped, but should be labelled as such if
  kept in the release tree.

## Limitations

- No native Windows or macOS host was available: the Inno installer and DMG
  mount tests skip on Linux. The t146/t147/t154 native CI results referenced in
  the task notes were not re-run here; their workflow definitions and test
  contracts were inspected.
- No installer `.exe` or `.dmg` is present in this workspace (`dist/` contains
  only the Linux/Windows/macOS archives), so native install/launch/upgrade/
  uninstall automation could not be exercised locally.
- The artifacts in `dist/` were rebuilt for this revision (no updater entries;
  correct modes/install.json), but no release was published.

No product code was modified by this review; the only file added is this report.
