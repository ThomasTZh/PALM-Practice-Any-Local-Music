# Independent review, round 3: all-platform bundled-tools release

Status: **BLOCKED** (needs_revision) — functionality and checksums pass, but two
shipped documentation contradictions remain in the all-bundled artifacts.

- Reviewer: `reviewer` (independent; no product code edited)
- Task: t180 attempt 1 (`be7563a7-b413-43a0-b1c8-842cf7fd2136`), reviewed t179
- Reviewed revision: `4c9052f` (product repair `4bfe728`), held artifacts in
  `/home/thomas/Documents/basseparate/dist`.
- Host: Linux x86_64; native Windows/macOS installer/DMG execution was not
  available here.

## Commands and results

```text
make gate (first run)            -> FAILED on e2e: chromium golden path failed,
                                     firefox flaky; pytest/typecheck/web passed
make e2e                         -> PASS 2 spec files
make gate (second run)            -> PASS: 513 passed, 11 skipped
make test-package                 -> PASS: 6,626 members; bundled launcher help
sha256sum -c dist/SHA256SUMS      -> all five held assets OK
```

The first gate failure was an e2e flake, not a source-test failure; the clean
second run passed all 513 tests and 2 e2e specs. This is noted as a flaky gate
risk, not a deterministic code blocker.

## Verified fixed from t177

- **Linux packaged default analysis** works: bundled Python returned
  `SonicAnnotatorBackend`, C major, 135.999 BPM, 5 chords, 18 beats, 5 bars.
- **Windows UI/gates** expose bundled analysis with no tool download/UAC; the
  old unconditional blocker is gone.
- **Socket/10038 fix:** `_close_if_owned` and the regression test are present;
  the source test suite is green.
- **Artifacts:** all three platforms contain FFmpeg/Sonic/Vamp and
  licence/source archives; the five assets verify against one `SHA256SUMS`; no
  model weights or inference environments are bundled.
- **Tags:** only the historical `legacy-studio` and `v0.1.0-dev` tags remain;
  temporary/plugin tags were deleted. No release was published.
- **Native t179 evidence:** Windows run 45024688700 (7 tests) and macOS run
  45024688678 (8 tests including DMG/Applications/modes) report bundled Sonic
  135.999/C major/5/18; these were not re-run in this Linux review.

## Blockers

### B1 — The main portable guide still says the bundle has no FFmpeg/analysis tools

`docs/portable.md:3-8` still says:

> Every bundle ... does **not** contain FFmpeg, model weights, analysis tools,
> Python environments ... The first run downloads what you choose...

The Linux tar contains FFmpeg/Sonic/Vamp and `licenses/bundled-tools`, and setup
requires no tool download. This stale introduction is copied into the Linux tar
as `docs/portable.md`; a user reading the shipped guide gets the opposite of the
all-bundled behavior. Update the opening to say the tools are bundled, with only
the CPU environment/model downloaded.

### B2 — Release notes contain a dangling old sentence in the macOS section

`packaging/release-notes.md:69-71` now says the tools are bundled/no download,
then immediately says:

> verified by setup; they are not external prerequisites.

That leftover fragment (also in the rebuilt `RELEASE-NOTES.md` artifacts)
contradicts the preceding line and reads like the old managed-download text.
Remove it or rewrite the sentence.

## Medium/low findings

- **Tags:** the task says only `v0.1.0-dev`; `legacy-studio` remains as a
  historical tag. Confirm this is intentional (it is not a new release tag) or
  remove it.
- **Native evidence not re-run:** installer/DMG native checks are t179 CI
  references; the Linux review inspected artifacts and sources but could not
  execute the Windows/macOS apps.
- **Artifact-doc test:** add a package-test assertion for the opening
  `docs/portable.md` wording and the complete `RELEASE-NOTES.md`, since both
  stale passages passed the existing tests.

## Verified working

- All three platforms bundle FFmpeg/Sonic/Vamp with licence/source archives.
- Setup no-download/no-UAC paths and Windows bundled analysis are fixed.
- Linux packaged default analysis, socket ownership fix, checksums, no-model
  audit and package checks pass.
- Native Windows/macOS bundled analysis is reported by t179 CI.
- No release; tags are only historical.

## Verdict

**needs_revision.** The code and artifacts are functionally ready, but the
shipped portable guide and release notes still contain direct contradictions of
the all-bundled behavior. No product code was edited; only this report was
added.
