# Independent review: all-platform bundled-tools release

Status: **BLOCKED** (needs_revision) — the artifacts contain the promised
FFmpeg/Sonic/Vamp payloads, but the packaged Linux default analysis path is
broken, Windows still disables the bundled analysis, and the user docs still
describe the previous download/analysis-blocked behavior.

- Reviewer: `reviewer` (independent; no product code edited)
- Task: t175 attempt 1 (`c408f6ab-5ee9-4853-8e6e-2e8c49bf369b`), reviewed t174
- Reviewed revision: `5b23000` (product tree `590db63`), held artifacts in
  `/home/thomas/Documents/basseparate/dist`.
- Host: Linux x86_64; native Windows/macOS artifacts were not executed here.

## Commands and results

```text
make test-package                         -> PASS: 6,626 members; bundled bin/palm --help
sha256sum -c dist/SHA256SUMS              -> all five assets OK
make gate                                 -> FAILED: 503 passed, 11 skipped, 8 failed
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

The same source tests passed in earlier rounds; the current preserved
`storage/tools` Sonic/plugin set now crashes `--list`. This is a validation
failure in the declared gate, separate from the all-bundled candidate payload.

## Verified working

- **All three artifacts bundle FFmpeg, Sonic Annotator and the Vamp plugins.**
  The Linux tar contains `tools/ffmpeg/{ffmpeg,ffprobe}`,
  `tools/sonic-annotator/...`, `tools/vamp-plugins/*.so`; the Windows ZIP
  contains the FFmpeg executables, Sonic Annotator, QM/NNLS-Chroma DLLs and
  catalogs; the macOS ZIP contains the FFmpeg executables, Sonic Annotator and
  QM/NNLS-Chroma dylibs.
- **Licence/source archives** are present in all platforms:
  `licenses/bundled-tools/` includes the FFmpeg, Sonic, QM and NNLS-Chroma
  notices and source archives; the licence/audit tests pass.
- **No models or inference environments** are bundled. The Linux tar has no
  `environments/`, `.ckpt`, `.th`, `.onnx` or model-weight payload; the only
  `models/` entries are Python `pip._internal.models` modules. The package
  audit passes.
- **One combined checksum manifest** covers all five assets and verifies:
  Linux tar `2ac06984…`, Windows installer `1d2eefa0…`, Windows ZIP
  `f28e90e0…`, macOS ZIP `673151ef…`, macOS DMG `ce2051f0…`.
- **Explicit bundled Sonic analysis works** from the extracted Linux tar:
  C major, 135.999 BPM, 5 chords, 18 beats, 5 bars. Windows/macOS native runs
  45018062350/45018062392 report the same bundled Sonic values; those CI results
  were not re-run here.
- **Setup tool detection/no-download path** exists: `tools_status()` resolves
  `app_root/tools`, and `install_tools()` returns already-installed bundled
  tools without a download or UAC on Windows. Media-tool detection also
  prefers the bundled `app_root/tools/ffmpeg`.

## Blockers

### B1 — Packaged Linux default analysis fails; only an explicit Sonic backend works

**Files:** `src/basseparate/analysis_backend.py:207-209` returns
`PiperBackend` for Linux; `src/basseparate/piper.py:102-113` expects
`<data_root>/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server` and
`<data_root>/tools/plugins`. The all-bundled Linux tar contains
`tools/sonic-annotator`, `tools/vamp-plugins` and `tools/ffmpeg`, but no
`tools/sv` or Piper server.

**Reproduction** with the extracted held tar and its bundled Python:

```text
default_backend() -> PiperBackend
analyze_file(fixture) -> PiperUnavailable:
  Piper server not found at <data>/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server
```

The t173/t174 evidence explicitly says "bundled Sonic backend"; that is not the
product default used by the UI. A normal packaged Linux analysis therefore fails
despite the bundled FFmpeg/Sonic/Vamp payload.

**Fix:** make Linux select the bundled Sonic backend when
`app_root/tools/{sonic-annotator,vamp-plugins,ffmpeg}` exists (or bundle the
Piper host), and add a packaged-tar default-analysis regression test.

### B2 — Windows setup still disables the bundled analysis

**Files:** `web/src/panels/setup/SetupWizard.tsx:781-797` enters the Windows
"Analysis temporarily unavailable" branch unconditionally;
`web/src/state/setup.ts:468-496` sets `windowsAnalysisBlocked = platform ===
"windows"` and returns `canAnalyze=false`; the old tests still assert the
blocker (`SetupWizard.test.tsx:145-150`,
`tests/unit/test_setup/test_platform_tools.py:120-151`).

The Windows artifacts now contain bundled Sonic/Vamp, and the native run
reports bundled Sonic analysis. But a user opening Setup sees the blocker and
the Analyse control remains disabled; the feature is unreachable even though
the backend works. The same applies to the Windows acceptance kit, which still
says analysis is blocked.

**Fix:** remove the unconditional Windows block; show the bundled tools and
their licences/consent, enable analysis when the bundled Sonic/Vamp paths exist,
and update the UI/gate tests and Windows acceptance kit.

### B3 — User documentation still describes the old download/blocked release

All of these still say FFmpeg/Sonic/Vamp are not bundled, are downloaded at
setup, or that Windows analysis is blocked:

- `README.md:44-47` and `:111-124` ("tools, FFmpeg ... not bundled"; Windows
  analysis temporarily blocked; managed FFmpeg downloaded);
- `docs/portable.md:3-8`, `:120-125`, `:155-180` ("does not contain FFmpeg ...
  analysis tools"; setup downloads; Windows analysis blocked);
- `packaging/release-notes.md:46-49` and `:123-135` (downloads; Windows
  analysis unavailable);
- `packaging/windows/README.md:15-21` and `:37-41` ("No FFmpeg, Sonic
  Annotator, Vamp plugins ... bundled"; Windows analysis unavailable);
- `packaging/macos/README.md:46-49` ("No FFmpeg, Sonic Annotator, Vamp plugin
  pack ... bundled"; downloads at setup);
- `docs/troubleshooting.md:129-136` (managed downloads as first-run behavior);
- `docs/acceptance/windows-beta.md:85-91,120-149,257-264` (Vamp/analysis
  blocked, no bundled components);
- `README.md`/portable setup guidance still tells users they need network
  downloads for tools.

The artifacts and t174 native evidence contradict these documents. The task
explicitly requires docs to match all-bundled behavior.

**Fix:** update the user READMEs, portable guide, release notes, troubleshooting,
Windows/macOS packaging READMEs and acceptance kits to say the tools are
bundled, setup performs no tool download/UAC, and Windows analysis uses the
bundled Sonic/Vamp payload. Remove the old Windows-blocker language.

### B4 — `make gate` is red

The gate fails 8 source-checkout Sonic tests with `sonic-annotator --list`:
`*** buffer overflow detected ***: terminated`. This is a validation failure in
the declared command, even though the explicit bundled Sonic backend works.
The preserved `storage/tools` Sonic/plugin set should be repaired or the source
tests should skip/report the environment failure; the gate must be green before
release.

### B5 — A temporary tag remains

`v0.1.0-t171-ci3` (d5b658a) is present. The task says no release/tag; t174
claims the temporary tag was deleted. Remove the temporary tag (and confirm the
pre-existing `legacy-studio`, `plugins-win64-v1`, `v0.1.0-dev` tags are the
intended historical tags) before treating the candidate as held-only.

## Medium/low findings

- **Gate test gap:** `tests/integration/test_package/test_package.py` checks
  that tools and licences exist but does not exercise the packaged default
  backend; the Linux failure above passed the package test suite. Add an
  extracted-tar `default_backend().analyze(...)` assertion.
- **UI test gap:** the Windows UI test asserts the old blocker and no tools;
  after fixing B2 it must assert bundled tools are visible, licences/consent are
  present, and no admin/download path appears.
- **Native limitations:** Inno installer launch/upgrade/uninstall and macOS DMG
  mount/app analysis were reported by t174 runs 45018062350/45018062392 but not
  re-run in this Linux review. The held artifacts and native CI definitions were
  inspected; no local installer/DMG execution was possible.

## Verdict

**needs_revision.** The bundled payloads, source archives, checksums, no-model
payload and native backend evidence are solid, but Linux's packaged default
analysis path is broken, Windows still disables the bundled analysis, the user
docs describe the old release, the gate is red, and a temporary tag remains.
No product code was edited; only this report was added.
