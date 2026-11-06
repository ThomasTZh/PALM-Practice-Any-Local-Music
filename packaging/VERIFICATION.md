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
AppImage text: false
```

### Commands

```text
make package      -> exit 0, tar 70,038,235 B, SHA256SUMS written
make test-package -> exit 0, 6,488 members, required env/installer, checksums,
                     bundled bin/palm --help
make gate         -> exit 0, 369 passed/9 skipped, web 61.2 s, e2e 54.7 s
./packaging/verify-clean-room.sh -> exit 0, health/setup page/data-root evidence
```
