# Independent packaging release review, round 3

Status: **BLOCKED** (needs_revision) — the gate fails, the checksum repair is not
committed/importable, and the Windows analysis/consent documentation still
contradicts the product.

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t159 attempt 1 (`89fb8944-3a4b-4f27-b146-c492fc86cf2a`), reviewed t158
- Reviewed revision: `ac953e0` plus the current working tree (which contains
  uncommitted packaging changes and an untracked `scripts/release_checksums.py`).
- Host: Linux x86_64; no native Windows/macOS installer/DMG execution.

## Commands and results

```text
make gate                 -> FAILED: 499 passed, 11 skipped, 7 failed
make test-package         -> PASS (6,553 members; bundled bin/palm --help)
scripts/package_windows.py --check -> PASS (5,000 entries)
scripts/package_macos.py --check   -> PASS (3,836 entries)
```

Gate failures:

```text
FAILED tests/integration/test_package/test_package.py::
       test_dist_checksum_manifest_covers_all_present_platform_assets
FAILED tests/integration/test_package_macos/test_package_macos.py::
       test_check_zip_accepts_required_content
FAILED tests/integration/test_package_macos/test_package_macos.py::
       test_zip_writer_records_unix_executable_modes
FAILED tests/integration/test_package_macos/test_package_macos.py::
       test_checksum_file_uses_flat_basenames
FAILED tests/integration/test_package_macos/test_package_macos.py::
       test_built_macos_zip_when_present
FAILED tests/integration/test_package_windows/test_package_windows.py::
       test_check_zip_accepts_required_content
FAILED tests/integration/test_package_windows/test_package_windows.py::
       test_built_zip_has_only_allowed_payload_when_present
```

The macOS/Windows package tests fail loading the scripts:

```text
scripts/package_windows.py:30: ModuleNotFoundError: No module named 'release_checksums'
scripts/package_macos.py:29:   ModuleNotFoundError: No module named 'release_checksums'
```

`make test-package` and the packager `--check` commands still pass when the
scripts are run as processes (their directory is then on `sys.path`), so this is
a test/import-path failure as well as an uncommitted-worktree failure.

## Blockers

### B1 — The t158 checksum repair is not in the commit and cannot be imported by the package tests

**Working tree:** `scripts/package.py:34`, `scripts/package_macos.py:29` and
`scripts/package_windows.py:30` import `release_checksums`; the helper exists as
untracked `scripts/release_checksums.py`; the three packagers are modified in
the working tree but `ac953e0` only contains docs/test changes. `git status`
shows the modifications untracked/unstaged.

**Test path:** `tests/integration/test_package_windows/test_package_windows.py`
and `tests/integration/test_package_macos/test_package_macos.py` load the
scripts with `importlib.util.spec_from_file_location`; the `scripts/` directory
is not on `sys.path`, so every `load_script()` raises `ModuleNotFoundError`.
This is repeated for the macOS checksum test and the built-ZIP tests.

**Effect:** `make gate` fails 7 tests. The committed release branch (`ac953e0`)
does not contain the merge fix at all; the working tree contains the fix but
cannot pass its own gate. `dist/SHA256SUMS` currently happens to be a manually
combined three-platform file, but the code that would produce it is neither
committed nor importable.

**Fix:** commit `scripts/release_checksums.py` and the three packager changes,
then make the helper discoverable when the scripts are loaded by tests (insert
`ROOT/scripts` into `sys.path` before loading, or move the helper into an
importable package/module). Rerun `make gate` and `make test-package`; verify
that building Linux, Windows and macOS in one `dist/` leaves a manifest
covering all assets.

### B2 — Windows silent Vamp installation is still not verifiable and the acceptance kit still expects it

**Files:** `src/basseparate/setup/tool_assets.py:162-167,300-303` (Windows
analysis explicitly blocked; no Windows Vamp asset); `README.md` and
`docs/portable.md` now carry the blocker, and `packaging/release-notes.md:46-49`
does too. However, `docs/acceptance/windows-beta.md:86,98,132-133,257` still
lists the Vamp pack as a downloadable/required component and says recommended
setup completes analysis tools. The task acceptance still asks for a verified
silent all-plugin Vamp install; there is no such install on Windows now.

**Fix:** either restore/rehost a verified 64-bit Vamp bundle and reinstate silent
installation tests, or explicitly amend the release/task acceptance to
"Windows analysis blocked", and update the acceptance kit so it no longer asks
the tester to install or verify Vamp analysis on Windows. The UI blocker and
no-UAC/no-manual-DLL behavior are correct.

## Medium/low findings

### M1 — macOS release notes and troubleshooting still call FFmpeg external

`packaging/release-notes.md:69` says "FFmpeg/ffprobe are prerequisites, not
bundled" for macOS; `docs/troubleshooting.md:129` says the same for first-run
gating. Managed FFmpeg is a setup capability on all platforms. The macOS ZIP and
Linux tar release notes carry the stale line. Fix the wording; managed setup
already covers it.

### M2 — Interactive delete-data remains a manual-only evidence gap

`tests/integration/test_package_windows/test_package_windows.py:188-197` now
launches the installed app; the native uninstall test still uses silent
uninstall with data kept. `packaging/release-notes.md:53-55` explicitly says the
interactive "also delete data" branch is manual and not CI-verified. The task
acceptance asks for uninstall choices with concrete evidence; either add a
native/automation test or attach recorded manual evidence before claiming it.

### L1 — Setup UI still describes the Vamp pack as generally required

`web/src/panels/setup/SetupWizard.tsx:784-785` says Sonic Annotator and the Vamp
pack are required for chord/tempo analysis without a Windows qualifier; the
Windows blocker below it is clear. Make the description platform-aware and
keep the blocker prominent.

## Verified improvements

- Windows blocker is explicitly documented in README/portable/release notes;
  no UAC/GUI-pack/manual-DLL path is offered.
- `README.md` no longer claims Windows automatic Vamp installation.
- macOS tag workflow now uploads `SHA256SUMS` and verifies it
  (`macos-package.yml`).
- Linux stale-text test now asserts "Windows and macOS are not packaged".
- Installer native test launches the installed app and covers silent
  install/upgrade/uninstall/keep-data; the delete branch is documented manual.
- No custom updater/uninstall remains; Check for updates is instruction-only;
  stem gating and WinError 10038 tests pass; artifacts have correct
  `install.json`, licence trees, executable modes and no bundled tools/models.
- **No third-party binaries/tools/models** are bundled.

## Limitations

- No native Windows/macOS host: Inno installer and DMG mount tests skip; no
  installer/DMG exists locally. The t156 native CI run 44755837163 was not
  re-run here.
- `dist/SHA256SUMS` is currently a manually combined three-asset file; the
  production merge code is uncommitted and unimportable as described in B1.
- No release/tag was created. Only this report was added; no product code was
  edited by the review.

## Verdict

**needs_revision.** The gate is red and the checksum repair is not in the
release branch/test path. After B1 is fixed and the Windows analysis acceptance
or docs are resolved, the remaining M1/M2/L1 items should be closed before a
release claim.
