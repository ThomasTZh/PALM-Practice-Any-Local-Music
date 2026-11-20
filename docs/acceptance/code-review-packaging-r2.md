# Independent packaging release review, round 2

Status: **BLOCKED** (needs_revision) — the checksum/release aggregation bug and
remaining Windows-analysis/documentation inconsistencies need repair before a
conventional release can proceed.

- Reviewer: `reviewer` (independent; no product code edited by this review)
- Task: t157 attempt 1 (`1b0f8f85-94c7-4e7b-977d-3a9dccfdd650`), reviewed t156
- Reviewed revision: `5cd6449` on `t156-release-docs` (t156 `45b0542`,
  `63c4a0c`; head includes the corrected Linux README line).
- Host: Linux x86_64. Native Windows installer/DMG execution remains
  unavailable here; source, tests, workflows and rebuilt Linux/Windows/macOS
  archives were checked.

## Commands and results

```text
make gate                              -> gate: ok; pytest 505 passed, 11 skipped
make package                           -> Linux tar rebuilt at current HEAD (70,441,259 B)
make test-package                      -> PASS (6,553 members; bundled bin/palm --help)
scripts/package_windows.py --check     -> 5,000 entries, required content present
scripts/package_macos.py --check       -> 3,836 entries, required content present
scoped package/licence/setup tests     -> 92 passed, 2 skipped (native tests skip on Linux)
```

**Reproduced blocker:** after building all three platform artifacts in one
`dist/`, `make test-package` fails:

```text
make package
python scripts/package_windows.py --output dist
python scripts/package_macos.py --output dist
make test-package
# FAILED tests/integration/test_package/test_package.py::
#   test_built_tar_checksum_and_contents_if_present
# AssertionError: linux tar digest ... not in
#   'a2ee7bda...  PALM-0.1.0-dev-macos-arm64.zip\n'
```

The final `dist/SHA256SUMS` contains only the macOS ZIP. Re-running
`make package` last restores a Linux-only `SHA256SUMS` and makes
`make test-package` pass, but the Windows/macOS assets are then unchecksummed.
This is a multi-platform packaging bug, not just a test ordering issue.

## What is fixed from the round-1 findings

- **Linux release docs (P1)**: `packaging/README.release.md` now describes the
  control window, managed FFmpeg, installer/DMG packaging and data-preserving
  OS removal; `scripts/package.py:418-447` copies the current
  `packaging/release-notes.md`; Windows/macOS package stages now include
  `RELEASE-NOTES.md` (`scripts/package_windows.py:298`,
  `scripts/package_macos.py:282`). The tar rebuilt from current HEAD no longer
  contains the old terminal/external-FFmpeg/Linux-only/data-deletion text.
- **Windows Vamp UI (P2)**: the deleted `palm-vamp-plugins-win64` bundle is
  removed from `PLATFORM_ASSETS`, the manifest and the download record; Windows
  setup installs Sonic Annotator and reports a plain blocker
  (`tool_assets.py:162-167,300-303`); the setup wizard renders the blocker
  (`SetupWizard.tsx:787-796`) and analysis is disabled (`setup.ts` gates). The
  UAC text and the GUI-pack/manual-DLL path are gone.
- **Release notes/installer wording (M1)**: Linux size/hash duplication, UAC,
  portable-only Windows wording and the terminal instructions are corrected;
  the Windows installer is documented as primary.
- **Tag uploads (M2)**: `windows-package.yml:131-147` now writes
  ZIP+installer+SHA256SUMS and uploads them. `portable.yml` retains the same
  behavior.
- **Installer launch (M3)**: the native test now starts the installed
  `PALM.exe`, waits for `run/server.json` and stops it
  (`test_package_windows.py:188-197`). The interactive delete-data branch is
  documented as a manual step.
- **Custom data root (M4)**: Windows README and acceptance kit now state that
  `PALM_DATA_DIR`/`--data-dir` roots are never removed automatically.
- **Launcher README (L1)** is updated to the control-window/desktop behavior.
- **No custom updater/uninstall**: still absent from source, tests and
  artifacts; Check for updates is instruction-only; stem gating and WinError
  10038 tests pass; artifacts have no FFmpeg/Sonic/Vamp/model/tool payload;
  licence trees, `install.json` and executable modes are correct.

## Blockers

### B1 — `SHA256SUMS` is overwritten per platform and covers only the last builder

**Files:** `scripts/package.py:458-463` (Linux writes only the tar),
`scripts/package_macos.py:377-389` (macOS overwrites `dist/SHA256SUMS` with
ZIP/DMG only), `.github/workflows/macos-package.yml:52-58` (tag upload omits
`SHA256SUMS`), `.github/workflows/windows-package.yml:131-147` (Windows-only
checksum file). `tests/integration/test_package/test_package.py:42-50` asserts
the Linux tar is in `dist/SHA256SUMS`.

**Evidence:** after the three-platform build sequence above, `dist/SHA256SUMS`
is macOS-only and `make test-package` fails. After Linux is rebuilt last,
`dist/SHA256SUMS` is Linux-only though Windows/macOS archives are still present.
The task's verification command therefore depends on build order, and a release
directory cannot provide one `SHA256SUMS` covering all published assets.

**Required fix:** generate one combined checksum file from every release asset
(tar, ZIP, installer, DMG), or use explicit platform-named checksum files and
update CI/docs; add a test that builds/checks more than one platform's assets in
one `dist/`. The macOS tag workflow must upload its checksum file, and the
release aggregation must not overwrite earlier entries.

### B2 — Windows analysis is unavailable and the acceptance/documentation still claims it is installed

**Files:** `src/basseparate/setup/tool_assets.py:162-167,300-303`; smoke UI
`web/src/panels/setup/SetupWizard.tsx:787-796`; `README.md:45,119` (root README
shipped in the Windows/macOS ZIPs) still says "Sonic Annotator and the Vamp
Plugin Pack are installed automatically"; `docs/acceptance/windows-beta.md:86,98,132-133,257`
still require the Vamp pack in the licence/download summary and say recommended
setup completes analysis tools; `packaging/release-notes.md:67-68` still calls
FFmpeg/ffprobe an external prerequisite; `docs/troubleshooting.md:129` repeats
that external prerequisite.

**Evidence:** t154's `plugins-win64-v1` release was deleted; t156 removes the
asset and explicitly blocks Windows Sonic/Vamp analysis (no download, no UAC,
no GUI pack, no manual DLL path). That is a safe product blocker, but the task
acceptance asks for a verified silent Vamp all-plugin install. There is no such
install on Windows now, and the shipped root README, acceptance kit and
troubleshooting/guide fragments contradict the blocker and managed FFmpeg.

**Required fix:** either restore/rehost a verified 64-bit Vamp bundle (and
reintroduce silent installation tests), or explicitly narrow the release and
acceptance to "Windows analysis blocked" and remove all automatic-Vamp/external-
FFmpeg claims from the root README, Windows acceptance kit, release notes and
troubleshooting. The setup UI should not present the Vamp pack as required for
Windows while its blocker is active.

## Medium/low findings

### M1 — Linux artifact-content test misses the exact phrase corrected by 5cd6449

`tests/integration/test_package/test_package.py:124-144` checks
"Linux-only build" but not "Windows and macOS are not packaged". Before
rebuilding at current HEAD, the checked-in `dist` tar still contained the stale
phrase; the source fix is present, and the rebuilt tar is correct. Add the exact
phrase to the stale-text test so a stale artifact cannot pass again.

### M2 — Windows installer delete-data evidence is still manual only

`test_package_windows.py:188-197` now verifies install/launch; the native test
still only exercises silent uninstall with data kept. The interactive "No,
delete data" branch is documented as a manual acceptance step
(`packaging/windows/README.md`), not automated. If "verified with concrete
evidence" requires an executed test, this remains an evidence gap; at minimum
keep the manual step and record its result before release.

### M3 — Setup/docstring still describes Windows Vamp pack generically

`src/basseparate/setup/tool_assets.py:1-7` still says Windows uses the official
Vamp Plugin Pack; `SetupWizard.tsx:784-785` says the pack is required for chord
and tempo analysis without a Windows qualifier. The blocker text below it is
clear, but these lines are stale and should be made platform-aware.

## Limitations

- No native Windows or macOS host: the Inno installer and DMG mount tests skip
  on Linux (`2 skipped`), and no installer `.exe`/`.dmg` exists in this
  workspace. The t156 native tag CI run 44755837163 was not re-run here; its
  workflow/test contracts were inspected.
- `make package` and the Windows/macOS ZIP builds were rebuilt locally at HEAD
  (offline; no installer/DMG generation on Linux). The checksum failure above
  was reproduced with those artifacts.
- No release or tag was created. No product code was edited; the only file added
  by this review is this report.

## Verdict

**needs_revision.** The packaging implementation and most documentation are
substantially improved, but the per-platform checksum overwrite is a concrete
multi-platform release blocker, and the Windows analysis and managed-FFmpeg
story is still inconsistent in shipped/acceptance docs. The Windows analysis
blocker itself is a known upstream-asset limitation; it must either be repaired
or explicitly scoped out of the release acceptance.
