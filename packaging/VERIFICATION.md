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
