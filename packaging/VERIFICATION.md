# Clean-room verification

Status: **PASSED**

- Date: 2026-11-06T21:28:06Z
- Mode: bubblewrap minimal root (Ubuntu 22.04 image unavailable offline)
- Asset: `PALM-0.1.0-dev-linux-x86_64.tar.gz` (70038235 bytes)
- SHA256SUMS: verified
- /api/health: `{"status":"ok","version":"0.1.0-dev","data_root":"/data","ui":true}`
- setup page: HTTP 200, contains `id="root"`
- /api/setup/status: HTTP 200, packaged mode
- app root: unchanged (542f132dfa2d8e208626fe8beccaf14294c00e45d04cff9c5c3b41248b5a10bd  -)
- data-root files:

```text
logs/launcher.log 70
logs/server.log 79
run/launcher.lock 0
```

- Python in clean container: not checked

## Commands run

```sh
make test-package
tar -xzf /home/thomas/Documents/basseparate/dist/PALM-0.1.0-dev-linux-x86_64.tar.gz
bwrap --ro-bind <minimal-root> / ... /palm/bin/palm --no-browser --port 48791
curl http://127.0.0.1:48791/api/health
curl http://127.0.0.1:48791/
curl http://127.0.0.1:48791/api/setup/status
```

The full command/output transcript is retained in the build log while
this script runs. The container path is preferred; the bubblewrap
fallback is used only when no Ubuntu 22.04 image is available offline.

## t79 packaged setup repair verification (2026-11-06)

Status: **PASSED** after the t79 repairs. Real network downloads were used.

- Tar: `PALM-0.1.0-dev-linux-x86_64.tar.gz`, 70,038,235 B,
  `c2574e35ec33ed776b83a91e84f73feb406cb62671c49d0715ff1f47b770030b`
- Fresh extracted app and a fresh data root with no tools/models/environments
  directories.
- `./bin/palm --no-browser --port 0 --data-dir <fresh>` served the setup page;
  `/api/setup/status` reported packaged mode and no missing-script/interpreter
  error.

### F1: fresh-root tools

The tools job succeeded without any manual directory creation:

```text
tools running 0.05 installing Sonic Visualiser
tools running 0.6  installing Vamp plugin pack
tools succeeded 1.0 finished
```

`tools_status` paths exist: `data/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server`
and `data/tools/vamp-plugins/qm-vamp-plugins.so`; 141 files, 119 MiB.

### F2: CPU environment

The CPU lock is CPU-only and the environment installs from the packaged tar:

```text
grep whl/cpu analysis/envs/cpu/uv.lock -> download.pytorch.org/whl/cpu
env running 0.1 creating cpu environment
env running 0.25 uv sync running
env succeeded 1.0 finished
data/environments/cpu/bin/python -c "import torch, msst, pydantic"
  -> imports ok 2.9.1+cpu
```

The command no longer forces a CPU-only `--index-url` over PyPI; the project
uses its pinned CPU index for torch and resolves msst/pydantic normally.

### F3: model and separation

The first model download hit a transient read timeout after a 20,971,520-byte
`.part`. Retrying the same request resumed the part and installed
`scnet-xl-ihf` (checkpoint 214,063,778 B plus config 5,906 B). `ready=true`
with tools, CPU environment and model installed.

Separation of the 8 s fixture completed:

```text
POST /api/separate {project_id, model_id:"scnet-xl-ihf", device:"cpu"}
job succeeded 1.0
result model_id=scnet-xl-ihf, cached=false
stems drums, bass, other, vocals
```

The packaged runtime resolved `data/environments/cpu/bin/python`, which exists
and launches the worker; no `environments/msst` path is required.

### F4: browser at 1280x720

Independent headless Chromium against a fresh packaged data root:

```text
viewport 1280x720
.setup-page clientHeight 720, scrollHeight 1271, scrollTop 0 -> 551 (at bottom)
warning: "Early version 0.1.0-dev: limited testing and quality control. Keep backups of projects you care about."
warning visible: true (initial and after scrolling)
headings include Optional GPL tools, Inference environment, Separation models
links: 10, all https target=_blank rel="noopener noreferrer", 0 invalid
Secondary portable-image offer: none
```

### Commands

```text
make package      -> exit 0, tar 70,038,235 B, SHA256SUMS written
make test-package -> exit 0, 6,488 members, required env/installer, checksums,
                     bundled bin/palm --help
make gate         -> exit 0, 369 passed/9 skipped, web 61.2 s, e2e 54.7 s
./packaging/verify-clean-room.sh -> exit 0, health/setup page/data-root evidence
```

## t80 independent packaged-setup verification (2026-11-06)

Status: **PASSED** for the packaged setup path; one environment-specific
AppImageLauncher workaround is recorded below. Real network downloads were
used.

- Tar: `dist/PALM-0.1.0-dev-linux-x86_64.tar.gz`, 70,038,235 B,
  `4580345993eae93eba9826b9d48731998e2a896233579b1d6728841fafb3e453`,
  matching `dist/SHA256SUMS`.
- Extracted app: `storage/t80-verification/app/palm-0.1.0-dev-linux-x86_64`.
- Fresh data root: `storage/t80-verification/data` (tools/models/environments
  absent at start).
- Launch command:

```sh
APPIMAGELAUNCHER_DISABLE=1 APPIMAGELAUNCHER_FORCE_HEADLESS=1 DISPLAY= \
PALM_MODE=packaged PALM_APP_ROOT=$PWD \
PALM_DATA_DIR=<data> ./bin/palm --no-browser --port 0 --data-dir <data>
```

`/api/health` returned `ok`; `/` returned 200 with the setup page.
`/api/setup/status` returned mode `packaged`, packaged roots, checks all ok,
tools/env missing and all three models missing. No missing-script or
missing-interpreter error.

### Tools

The first tools attempt stalled because this host's AppImageLauncher
intercepts AppImage execution. Relaunching the packaged server with
`APPIMAGELAUNCHER_DISABLE=1 APPIMAGELAUNCHER_FORCE_HEADLESS=1 DISPLAY=` made
the pinned Sonic Visualiser AppImage extract normally. The tools job then
succeeded:

```text
tools: running 0.05 installing Sonic Visualiser
tools: running 0.6  installing Vamp plugin pack
tools: succeeded 1.0 finished
```

`tools_status` paths exist and match the installed files:
`data/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server` (executable) and
`data/tools/vamp-plugins/qm-vamp-plugins.so`; 141 files, 119 MiB.

### CPU environment

`POST /api/setup/environments {"variant":"cpu","accept_licenses":true}`
completed. The packaged interpreter is
`app/python/bin/python3.11`; the project is `app/analysis/envs/cpu`. Import
check:

```text
data/environments/cpu/bin/python -c "import torch, msst, pydantic"
3.11.15 2.9.1+cpu 0.1.0 2.13.5
imports ok
```

Environment size: 1.2 GiB.

### Model and separation

`POST /api/setup/models` installed `scnet-xl-ihf` (checkpoint 214,063,778 B,
config 5,906 B; 205 MiB). The job reported progress and succeeded. Final
status: `ready=true`, tools ready, CPU environment ready, SCNet installed.

A generated 2.0 s 48 kHz stereo fixture was imported and separated:

```text
POST /api/separate {"project_id":...,"model_id":"scnet-xl-ihf","device":"cpu"}
queued -> running 0.05 loading -> 0.2 separating -> succeeded 1.0
result model_id=scnet-xl-ihf, cached=false
stems drums, bass, other, vocals (four 768,000-byte f32 files)
```

Total data root after setup/separation: 2.8 GiB.

### Browser at 1280x720

Independent Playwright Chromium against a second fresh packaged data root:

```text
viewport 1280x720
.setup-page clientHeight 720, scrollHeight 1266, scrollTop 0 -> 545.7 (max 546)
headings: System checks, Optional GPL tools, Inference environment, Separation models
early warning rect top=68.07 at load (visible); at max scroll top=-477.63 (not sticky)
BS-RoFormer model card visible at max scroll: true
licence/source links: 10, all https, target=_blank, rel="noopener noreferrer", bad=0
AppImage text in page: false
horizontal overflow: false
```

The early-version warning is visible on the initial 1280x720 setup page but
scrolls out of view at the bottom; it is not sticky.

### Commands and build verification

```text
make package      -> exit 0, tar 70,038,235 B, SHA256SUMS written
make test-package -> exit 0, 6,488 members, bundled bin/palm --help, OK
make gate         -> exit 0, 369 passed/9 skipped, web/e2e pass
```

## t81 packaged Piper/analysis verification (2026-11-07)

Status: **PASSED (intermediate local build; superseded by t85)**

The 70,038,314 B / a4f088... tar below is a local test build only. The
published v0.1.0-dev assets and tag remain unchanged until the combined t85
rebuild.

- Tar: 70,038,314 B, sha256
  `a4f088622a69d90e9d43bcdbaccc9b2c568cf7d0c0f99b7003458e5f365c6326`.
- Reused the t80 data root with tools installed by the setup job; extracted the
  new app over it and launched packaged mode.
- `PiperPaths.for_project()` resolved:
  - server `data/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server`
  - plugins `data/tools/plugins`
  - libraries `data/tools/sv/squashfs-root/usr/lib`
- Real packaged analysis of `tests/fixtures/audio/chords_c_am_f_g.wav`:
  job succeeded, key `C major`, 135.999 BPM, bpb 4, 5 chord entries,
  18 beats and 5 bars. No `PiperUnavailable`.
- Packaged missing-asset validation names the data-root
  `tools/sv/squashfs-root` path; source-checkout and BASSEPARATE_* override
  tests remain green.
- Scoped `make test-backend TESTS="tests/unit/test_piper
  tests/integration/test_analysis"` -> 38 passed.

Local verification for t81:

```text
make test-backend TESTS="tests/unit/test_piper tests/integration/test_analysis"
  -> 39 passed
make package      -> exit 0, tar 70,038,314 B, sha256 a4f08862...
make test-package -> exit 0, 6,488 members, bundled bin/palm --help
make gate         -> exit 0, 372 passed/9 skipped, web/e2e pass
```

The published release/tag were intentionally not modified.

## t85 final tar integration QA (2026-11-07)

Status: **PASSED** on the rebuilt final tree.

- Tar: `PALM-0.1.0-dev-linux-x86_64.tar.gz`, 70,039,107 B,
  `93840590ba9ac75181e008f407877d7ad31c04cf57f0f98bbd6ac931d61522b0`
- Fresh extraction and data root; launched `bin/palm --no-browser --no-terminal
  --port 0`; `/api/health` ok, `/api/setup/status` packaged and initially
  ready=false.

### Tools and real analysis

Tools installed from the package (141 files, 119 MiB); `tools_status` paths
match `data/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server` and
`data/tools/vamp-plugins/qm-vamp-plugins.so`.

The 8 s `chords_c_am_f_g.wav` fixture was imported and analysed through the
packaged server. The analysis job succeeded with no `PiperUnavailable`:

```text
bpm 135.999
key C major
chords 5
beats 18
bars 5
```

### CPU environment and model install

CPU environment creation succeeded; imports:

```text
torch 2.9.1+cpu
msst ok
pydantic ok
```

`scnet-xl-ihf` installed (205 MiB). Setup status: ready=true, tools ready,
CPU installed, scnet installed.

### Model picker without reload

Browser setup was opened on a data root with tools/CPU installed and the model
missing. The model card was selected and its licence accepted; the model install
button was clicked. Without navigating or reloading, the setup wizard detached
at the same URL and the library model select showed:

```text
Choose a model (disabled)
Demucs htdemucs_ft (disabled)
SCNet XL IHF (enabled, selected)
BS-RoFormer-SW (disabled)
```

### Launcher

PTY smoke of the packaged `bin/palm`: bootstrap lines appeared in the terminal
stream and `logs/server.log`, Ctrl+C exited 0 and removed `run/server.json`.
No-TTY launch without a graphical session printed `running in the background`
with the `server.log` path and still served the app; the terminal spawn path is
covered by unit tests.

### Commands

```text
make package      -> exit 0, tar 70,039,107 B, SHA256SUMS
make test-package -> exit 0, 6,488 members, checksums, bin/palm --help
make gate         -> exit 0, 376 passed/9 skipped, web/e2e pass
```


## t87 lifecycle integration QA (2026-11-07)

Status: **PASSED** on the rebuilt tar.

- Tar: `PALM-0.1.0-dev-linux-x86_64.tar.gz`, 70,041,725 B,
  `9d6a9617aa98be68353e68212a044000a33225a0647687579740571f7250f1b4`
- Fresh extraction and data roots. `bin/palm` was tested with an explicit
  `--data-dir` and with the default XDG data root (`XDG_DATA_HOME`).

### PTY and single instance

PTY launch streamed bootstrap/log lines to the terminal; a second launch with
`--no-terminal` printed `palm: already running at <url>` and exited 0 without
changing the recorded server pid or starting another server. Ctrl+C exited 0,
retained `logs/server.log`, and removed `run/server.json`.

### Status, stop and roots

`palm --status --data-dir <explicit>` and `palm --status` with XDG printed URL,
data root and pids and exited 0. `palm --stop` stopped the launcher and removed
state in both cases. Two live roots reported distinct URLs; stopping one left
the other running. A hand-written stale state with dead pids returned 1 from
`--status` with a stale message; `--stop` removed it (exit 0) and a fresh launch
then started normally.

### Docs

The data layout documents `<data>/{projects,assets,uploads,tmp,stems,models,
tools,environments,cache,logs,run,setup.json}`, the packaged palm vs old
basseparate root duplication, safe cache cleanup, setup-required directories,
project backup warnings and complete uninstall steps.

### Commands

```text
make package      -> exit 0, tar 70,041,725 B
make test-package -> exit 0, 6,488 members, checksums, bin/palm --help
make gate         -> exit 0
```

## t103 required psutil and packaged-runtime evidence (2026-11-15)

- `psutil==7.2.2` is pinned in `pyproject.toml` and
  `packaging/app-runtime/pyproject.toml`; root `uv.lock` and
  `packaging/app-runtime/uv.lock` contain `psutil` 7.2.2.
- Local package build: `PALM-0.1.0-dev-linux-x86_64.tar.gz`, 70,334,324 B,
  sha256 `6607bb0d27983e31415ee37c4ea58fcb7a8ce88385eefce32f9da6c3c52afc7a`.
- Extracted bundled interpreter import:

```text
$ tar -xzf PALM-0.1.0-dev-linux-x86_64.tar.gz -C <scratch>
$ <scratch>/palm-0.1.0-dev-linux-x86_64/python/bin/python3.11 \
    -c 'import psutil; print("packaged psutil", psutil.__version__)'
packaged psutil 7.2.2
```

- Platform tests also run a child Python with `psutil` blocked and assert a
  non-zero exit containing `PALM requires psutil 7.2.2 ...`.
- No release asset was published for this build.

## t126 final clean-checkout and native artifact verification

Status: **PASSED** on the curated `portable-final` branch.

- Clean checkout at the CI commit contains 19/19 files under
  `licenses/third_party`; `git check-ignore` does not ignore the manifest.
  `tests/unit/test_licenses` + `tests/integration/test_package_audit` passed 12
  (package archive skipped only because that clean worktree had no dist).
- Control wiring: `run_control` supplies real update/uninstall callbacks;
  scoped control/updater tests passed 18.
- GitHub Actions run **43972664919** succeeded from branch `portable-final`:
  Linux full gate/tar, Windows ZIP/package, macOS arm64 app/package; Intel
  manual-only and skipped.
- Downloaded final CI artifacts and verified flat checksums:
  - `PALM-0.1.0-dev-linux-x86_64.tar.gz` 88,419,888 B,
    SHA-256 `f25f6f6fde72f736c9ee6bb92191809b10396963ad0d3d13c330fcbb5264fac9`
  - `PALM-0.1.0-dev-windows-x86_64.zip` 79,622,676 B,
    SHA-256 `29336f1c24ac6243e91dca4cb2dc74900f99909d0d4c855cd06e3aaab892fc01`
  - `PALM-0.1.0-dev-macos-arm64.zip` 69,372,886 B,
    SHA-256 `67af69eaee36581019b29a94644d7bf06620436c064ffafb92e63ef463f1d99f`
  - `PALM-0.1.0-dev-macos-arm64.dmg` 81,636,504 B,
    SHA-256 `ea9cb69ba2339109180420cdefd3d5baa5efcdd614af7d603dca4314e1466d7c`
- All three SHA256SUMS verified from flat artifact directories. Windows
  PALM.exe/python.exe and macOS wrapper/python are executable Unix entries.
- Package launch/health/stop, install.json/licence-tree checks and no-terminal
  control smoke are in the Linux/Windows/macOS jobs. No third-party tools,
  models or environments are bundled. No release was published.

## t140 final native rebuild after t144 PASS

Status: **PASSED**, artifacts held only.

- t144 review at `docs/acceptance/code-review-native-r4.md` reports no
  release-blocking findings; reviewed HEAD 325615d.
- Fresh artifacts rebuilt from the final tree (Linux tar, Windows ZIP, macOS
  ZIP/DMG) and verified locally.
- Clean-runner GitHub Actions run **44191562921** succeeded on branch
  `t143-runtime`: Linux full gate/tar, Windows ZIP/package/smoke, macOS arm64
  app/package/smoke; Intel skipped.
- Windows job verified native PALM.exe launch/health, packaged update and
  uninstall helpers with real plans, packaged project save/stem-publish/export,
  licence/package audit and archive modes.
- macOS job verified package build/check, native app/health/status/stop,
  `.app` executable modes and flat artifact checksums.
- Linux job verified full gate, tar package, install.json/licence tree,
  no-terminal control launch, health/stop and checksums.
- Downloaded CI artifacts verified from flat SHA256SUMS:
  - Linux tar 88,422,211 B, SHA-256
    `f0d311ae1bab52cfe7de83a5462fd69a346b80218f826083f0f7c896269233b7`
  - Windows ZIP 79,692,002 B, SHA-256
    `491991f6543c0c0144bd6d0491a01a5e28263ae44df949efc41c80248550b27d`
  - macOS ZIP 69,376,308 B, SHA-256
    `c8dabcfcf1782e71d858b195bebb541c817e3aa71c66eae12ad6a0725dac8474`
  - macOS DMG 82,687,128 B, SHA-256
    `7a44bc6293422767f720994ae222cf6958974d191295646df5ecb42d5063c4f0`
- Windows PALM.exe is a Unix 0777 archive entry; macOS Contents/MacOS/palm is
  0755. No release/tag/asset was published; all artifacts remain held.

Residual non-blocking observations: delete-data can leave a partial helper
runtime on Windows/Wine; a swap failure is reported in updater.log and
pending.json.failed rather than the already-closed control detail; uninstall
auto-quit can also launch a pending update helper; a persistent update-launch
failure leaves the window open with the server stopped; native CI lacks an HTTP
import smoke with managed FFmpeg.

## t140 final clean-runner rerun

Clean-runner GitHub Actions run **44194142489** succeeded on branch
`t143-runtime`:
- Linux full gate/tar, Windows ZIP/package/smoke, macOS arm64 app/package/smoke;
  Intel skipped.
- Windows: native PALM.exe launch/health/browser, packaged update and uninstall
  helpers with real plans, packaged WAV import (`packaged WAV import ok 800`),
  packaged project/save/stem-publish/export, licence/package audit.
- macOS: 12 Sonic adapter tests passed, app health/status/stop, artifact
  executable-mode check and checksum verification.
- Final held artifacts (flat SHA256SUMS verified):
  - Linux tar 88,422,211 B,
    `f0d311ae1bab52cfe7de83a5462fd69a346b80218f826083f0f7c896269233b7`
  - Windows ZIP 79,692,002 B,
    `db1d3960d5ead858ea0779e2ea73cfa973522cb56a1e99fdb3eda8a497e906cb`
  - macOS ZIP 69,376,308 B,
    `c8dabcfcf1782e71d858b195bebb541c817e3aa71c66eae12ad6a0725dac8474`
  - macOS DMG 83,342,360 B,
    `31ee8fe39f5649ddc0ce61df3582530b0613140001645401bf627249d445aba5`
- Windows PALM.exe archive entry is 0777/Unix; macOS wrapper mode is checked by
  the artifact-mode step. No release/tag/asset was created; candidates remain
  held.


## t145 helper retirement

The custom updater/uninstall helper system was retired after t140. The runtime
no longer ships `updater.py`, `packaging/updaters`, pending plans, helper
runtimes, swap/restart code or a custom Uninstall button. Check for updates now
opens the matching release/download page; removal is OS-level and keeps the
data root by default. Historical t140 entries above describe the held artifacts
built before this retirement.

## t162 final held artifacts (analysis-blocked beta)

Product tree: 202ee3f (review report), built at CI checkout c0b2de9, which adds
only Windows/macOS workflow assertions. Clean-runner portable run
**44765809960** succeeded Linux, Windows and macOS arm64 jobs (Intel skipped).

Artifacts held in `/home/thomas/Documents/basseparate/dist/`:

| Asset | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| PALM-0.1.0-dev-linux-x86_64.tar.gz | 88,417,381 | `3f17975de1e111a462e3ffd66d038dcce137005610cab7e7c7b69e76ca3f4876` |
| PALM-0.1.0-dev-windows-x86_64-installer.exe | 50,573,744 | `e129cbe2ee57da3583e5675ca0e7907dfa59bfb9d34af812d28343b4029c9b26` |
| PALM-0.1.0-dev-windows-x86_64.zip | 79,688,568 | `a86a3c5095120b0235d1aa79e11964597c6ca020c04496f3ce69748bbbb01185` |
| PALM-0.1.0-dev-macos-arm64.zip | 69,372,901 | `886aad3a87c0e39168845879a375282ef6a14143eec79c6946e3b50758a27e11` |
| PALM-0.1.0-dev-macos-arm64.dmg | 83,741,939 | `f72ed5f457714be239cba53787a9601c2db77d196c83fc35236d43e7abda9d63` |

`dist/SHA256SUMS` is one combined manifest for all five assets; `sha256sum -c`
passes.

Native evidence:
- Windows: Inno Setup built the 50,573,744 B installer from the shared stage;
  native package tests 7 passed (silent per-user install, Start Menu shortcut,
  installed PALM.exe launch, upgrade, app-only uninstall keeping data). The
  Windows smoke queried `/api/setup/status`: platform windows, `tools` empty,
  and media/environment/model paths present; Windows analysis is blocked.
- macOS: 24 package tests passed, including native DMG mount, Applications
  symlink, PALM.app/0755 checks; native app health/browser smoke passed.
- Linux: full gate/tar/control smoke passed.
- No custom updater/uninstall helper is present. No Vamp/Sonic/FFmpeg/model
  payload is shipped; only licence notices are included. `PALM.exe` is 0777 in
  the ZIP and the macOS wrapper is 0755.
- No release or tag was published; the temporary CI tag was deleted. The
  analysis-blocked Windows label and managed-FFmpeg wording are in the shipped
  README/release notes.

## t165 final bundled-tools candidates (HEAD caac212)

Held in `/home/thomas/Documents/basseparate/dist/`; one combined SHA256SUMS
verified with `sha256sum -c`.

| Asset | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Windows installer | 137,522,877 | `e98efbaea8e783c8c1b25a57b934b3f317b3994a26cf446dee1ecadab1a07164` |
| Windows ZIP | 190,872,685 | `7af64b2429648bad6d814d6a2894ec64428788ffd5ce62a3bc41034aa97bf7ac` |
| macOS ZIP | 165,191,206 | `e268211a31d643f96fda07efc36182647e73e714857397be06719eab7989bbe2` |
| macOS DMG | 190,076,602 | `e883e83eef746f70cc29c17b317b125b1d719c66b3a50e9cc1d841a1acf2833c` |
| Linux tar | 203,613,487 | `2ac0698479a14f2ae1d910c774fcd3ac62722e4baed340abad604fa856804624` |

CI evidence:
- Windows package run 45011234446: 7 native install/launch/upgrade/uninstall
  tests; setup detected bundled Sonic/Vamp; Sonic 135.999 BPM/C major/5
  chords/18 beats; installer 137,529,977 B in that run.
- macOS package run 45015090102: plugin build and app passed; 8 package tests
  incl DMG mount/Applications/modes; Sonic 135.999 BPM/C major/5 chords/18
  beats; app health/status/stop.
- caac212 portable run 45015090089 built Linux/Windows/macOS artifacts above.

All three platforms now include pinned tools, licences and source archives;
Linux setup resolves the bundled Sonic/FFmpeg/Vamp payload. No release/tag.


## t173 Linux bundled tools

Linux tar stages FFmpeg/FFprobe 9.0.2, extracted Sonic 1.7 AppRun, QM and
NNLS-Chroma plugins, licence texts and five source archives under `tools/` and
`licenses/bundled-tools/`. Extracted tar analysis with the bundled Sonic backend
returned 135.999 BPM, C major, 5 chords and 18 beats. Package/audit tests pass;
no models or environments are bundled.

## t174 final all-platform bundled candidates (HEAD 590db63)

Held in `/home/thomas/Documents/basseparate/dist/`; combined SHA256SUMS
verified with `sha256sum -c`.

| Asset | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Linux tar | 203,613,487 | `2ac0698479a14f2ae1d910c774fcd3ac62722e4baed340abad604fa856804624` |
| Windows installer | 137,528,786 | `1d2eefa0e06f1630e385e6d97715e387090b2048d1f224ff20b666273c8b6f6c` |
| Windows ZIP | 190,872,713 | `f28e90e0402faea5d112db450488130d735120c9c155d51ad9cb4e242c474bd4` |
| macOS ZIP | 165,191,526 | `673151eff0fc0794b869c5dec937a1890a71acfabbf2657ed3182aa64dba4862` |
| macOS DMG | 188,361,201 | `ce2051f0a9470724db55034cfb2dc2c2cc4653d6d3e1b094228626017c0fea81` |

Evidence:
- Windows package run 45018062350: 7 native install/launch/upgrade/uninstall
  tests; setup detected bundled Sonic/Vamp; bundled Sonic 135.999 BPM,
  C major, 5 chords, 18 beats.
- macOS package run 45018062392: 8 package tests including DMG
  mount/Applications/modes, app smoke, bundled Sonic 135.999 BPM/C major/5/18.
- Linux tar from t173: bundled FFmpeg/Sonic/Vamp, licences and five source
  archives; extracted-tar bundled Sonic returned the same analysis values.
- No models/environments; no release or persistent tag.

## t176 all-bundled analysis candidate (HEAD 3664d7c)

Held in `dist/` with one combined SHA256SUMS verified:

| Asset | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Linux tar | 203,613,456 | `7b700a73443a11cc30dcc8d3db24e1e78b689e4942f0003e4d99cef82a6a7ee8` |
| Windows installer | 137,523,417 | `25c294d9b6b3917dd34b7057c4d1b274defa70f7eea582c2848008166d4118d4` |
| Windows ZIP | 190,872,575 | `382c6704d1bc258581cb8228708247e117f3c704add6b62e5625b63c44650b60` |
| macOS ZIP | 165,202,321 | `af201f57c8a7327948a3ae5aaa8cf3804b5b90d59b314446b4166d0a99a6bcde` |
| macOS DMG | 186,395,264 | `664cfacc90a8c560c0e2be7f7dca6b5b4fc2e2f9e4f93b0cd16cb26252e3e0d6` |

- Linux default_backend selects bundled Sonic when `app_root/tools` exists;
  extracted-tar analysis test and runtime analysis return 135.999 BPM,
  C major, 5 chords, 18 beats.
- Windows run 45022455087: 7 native tests, bundled tools detected, Sonic same
  analysis. macOS run 45022455096: 8 package tests incl DMG/modes/app smoke,
  Sonic same analysis.
- Windows setup UI now shows bundled tools/licences without download/UAC and
  allows analysis. Docs/acceptance kits updated. No models/environments.
- Source Sonic tests pass in gate; only `v0.1.0-dev` historical tag remains.
  No release/tag.
