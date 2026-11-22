# Independent review, round 2: all-platform bundled-tools release

Status: **BLOCKED** (needs_revision) — the t175 functionality gaps are mostly
fixed, but the declared gate is red and several shipped user/release documents
still describe the old download-based behavior.

- Reviewer: `reviewer` (independent; no product code edited)
- Task: t177 attempt 1 (`99e6ed37-3960-405a-abad-cbceed519df5`), reviewed t176
- Reviewed revision: `78bb80c` (product repair `3664d7c`), held artifacts in
  `/home/thomas/Documents/basseparate/dist`.
- The working tree also contains unrelated in-flight changes
  (`src/basseparate/cli.py`, `tests/unit/test_launcher/test_launcher.py`); they
  were not edited by this review.

## Commands and results

```text
make test-package                    -> PASS: 6,626 members; bundled bin/palm --help
sha256sum -c dist/SHA256SUMS         -> all five held assets OK
make gate                            -> FAILED: 504 passed, 11 skipped, 8 failed
```

Gate failures are the source-checkout Sonic tests:

```text
FAILED tests/integration/test_analysis/test_sonic_parity.py::
       test_plugin_identities_and_versions
FAILED tests/integration/test_analysis/test_sonic_parity.py::
       test_piper_and_sonic_match[...] (5 fixtures)
FAILED tests/integration/test_analysis/test_sonic_real.py::
       test_sonic_backend_returns_chords_key_beats_and_bars
# sonic-annotator --list failed: *** buffer overflow detected ***: terminated
```

The all-bundled explicit Sonic path works, so this is a source-checkout tool
failure, but it is still a failure of the declared verification command.

## Verified fixed from t175

- **Linux packaged default analysis works.** Rebuilt tar, bundled Python:
  `default_backend()` now returns `SonicAnnotatorBackend`; `analyze_file` returned
  **C major, 135.999 BPM, 5 chords, 18 beats, 5 bars**. `analysis_backend.py`
  selects Sonic when `app_root/tools/{sonic-annotator,vamp-plugins,ffmpeg}`
  exists.
- **Windows bundled analysis is exposed.** The unconditional Windows blocker is
  gone; the setup UI shows bundled tools/licences/source links, hides the
  download/consent/install controls for bundled Windows tools, and
  `setupGates` only reports the old blocker when `status.tools` is empty.
  `SetupWizard.test.tsx` now checks bundled tools/no blocker; the old source
  tests were updated.
- **All platforms bundle tools/licences/sources.** Linux tar, Windows ZIP and
  macOS ZIP/DMG contain FFmpeg/Sonic/Vamp; `licenses/bundled-tools` contains
  notices and five source archives.
- **Checksums/no-model audit:** the five held assets verify with one
  `SHA256SUMS`; no environments or model-weight payload is present; package
  audits pass.
- **Tags:** only the pre-existing `legacy-studio` and `v0.1.0-dev` tags remain;
  the temporary/plugin tags are deleted. No release was published.
- Native t176 Windows run 45022455087 (7 tests) and macOS run 45022455096
  (8 tests including DMG/Applications/modes) report bundled Sonic
  135.999/C major/5/18; these runs were not re-executed here.

## Blockers

### B1 — `make gate` is still red

The task's explicit verify command fails 8 tests with
`sonic-annotator --list failed: *** buffer overflow detected ***: terminated`
using the preserved source-checkout `storage/tools` Sonic/plugin set. The held
artifacts' bundled Sonic backend works, but the gate must be green before a
release. Repair/skip the source tool set or make the test report the environment
failure explicitly, then rerun `make gate`.

The working tree also has unrelated uncommitted `cli.py`/launcher-test changes;
the gate result is for the current tree, not a clean t176 checkout. Those
changes must not be mixed into this release review.

### B2 — Several user/release documents still describe the old download model

The all-bundled release docs are only partially updated. These current files
still contradict the artifacts:

- `packaging/README.release.md:32-47` (copied into the Linux tar as `README.md`)
  says the analysis tools/FFmpeg are downloaded at setup and require network.
- `docs/portable.md:3-8` says the bundle does **not** contain FFmpeg/analysis
  tools and that first run downloads them.
- `packaging/release-notes.md:69-70` says macOS managed FFmpeg is downloaded;
  `:123-135` describes Linux analysis tools/FFmpeg as setup downloads.
- `packaging/windows/README.md:15-21` says no FFmpeg/Sonic/Vamp is bundled
  (then later says they are).
- `docs/acceptance/macos-experimental.md:30-34` says tools are bundled in one
  line but says setup downloads FFmpeg/analysis tools immediately after.

The artifacts and t176 native evidence require: bundled tools, no tool
download/UAC, and Windows analysis enabled. Rewrite these remaining sections
and rebuild the docs into the artifacts.

## Medium/low findings

- **Artifact document check:** the Linux tar README/portable/release-notes are
  generated from the stale sources above, so the user-facing artifact is still
  wrong even though `README.md` was fixed.
- **Native evidence not reproduced:** Windows installer and macOS DMG/app tests
  were not run in this Linux review; t176 CI evidence was used, with no
  independent native execution. This remains a limitation, not a code finding.
- **Test coverage:** the new packaged-default analysis test is excellent;
  extend it to assert the docs embedded in the Linux tar say tools are bundled
  and no download is needed.

## Verified working

- Artifacts include FFmpeg/Sonic/Vamp and licence/source archives on all three
  platforms.
- No models or inference environments are bundled.
- Combined checksums verify.
- Linux packaged default analysis, Windows UI/gates and packaged Sonic tool
  paths are fixed.
- Native t176 evidence reports bundled analysis on Windows/macOS.
- No release/tag; temporary tags removed.

## Verdict

**needs_revision.** Functionality is largely fixed, but the declared gate is
red and shipped documentation still tells users to download tools that are now
bundled. No product code was edited; only this report was added.
