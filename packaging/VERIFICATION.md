# Clean-room verification

Status: **PASSED**

- Date: 2026-11-06T21:12:53Z
- Mode: bubblewrap minimal root (Ubuntu 22.04 image unavailable offline)
- Asset: `PALM-0.1.0-dev-linux-x86_64.tar.gz` (70034673 bytes)
- SHA256SUMS: verified
- /api/health: `{"status":"ok","version":"0.1.0-dev","data_root":"/data","ui":true}`
- setup page: HTTP 200, contains `id="root"`
- /api/setup/status: HTTP 200, packaged mode
- app root: unchanged (db201f4d670fd5327d499a6dd54c6c27aa9832cd3ac660fb36d98ac5d37b52a2  -)
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
bwrap --ro-bind <minimal-root> / ... /palm/bin/palm --no-browser --port 33581
curl http://127.0.0.1:33581/api/health
curl http://127.0.0.1:33581/
curl http://127.0.0.1:33581/api/setup/status
```

The full command/output transcript is retained in the build log while
this script runs. The container path is preferred; the bubblewrap
fallback is used only when no Ubuntu 22.04 image is available offline.

## Packaged setup end-to-end QA (t75, 2026-11-06)

Status: **FAILED** for the setup acceptance checks; the basic clean-room checks
above still pass. Real network downloads were used; there was no network
blocker.

Environment:
- Tar: `dist/PALM-0.1.0-dev-linux-x86_64.tar.gz` (70,034,673 B,
  `306430d2941a317cf99f8c10a3f5ce9b238579da61c87fe44ece7b3150046e36`)
- Extracted app: `.tmp-t75/app/palm-0.1.0-dev-linux-x86_64`
- Fresh data root: `.tmp-t75/data` (only launcher-created `logs/` and `run/`
  initially; tools/models/environments/cache absent)
- Launch: `./bin/palm --no-browser --port 0 --data-dir <data>`
- `/api/setup/status`: `mode=packaged`, `ready=false`, `registry_error=null`;
  checks glibc/disk/ffmpeg all ok; roots resolve to the packaged app and data
  root; no missing-script or missing-interpreter error is reported.

### Tools

Fresh data root, first attempt:

```text
POST /api/setup/tools {"accept_licenses":true} -> 202
job failed: SetupInstallError: tool installation failed: [Errno 2] No such file or directory:
/home/thomas/Documents/basseparate/.tmp-t75/data/tools/basseparate-sv-12cxhxq2
```

The packaged setup did not create `<data>/tools`. After creating that directory
manually, the same request succeeded:

```text
tools running 0.05 installing Sonic Visualiser
tools running 0.6  installing Vamp plugin pack
tools succeeded 1.0 finished
```

`/api/setup/status.tools` then reported installed Sonic Visualiser
(`data/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server`, GPL-2.0-or-later)
and Vamp pack (`data/tools/vamp-plugins/qm-vamp-plugins.so`, AGPL-3.0) with
141 files / 119 MiB. This is a fresh-root packaging blocker, not a network
limit.

### CPU environment

```text
POST /api/setup/environments {"variant":"cpu","accept_licenses":true} -> 202
env running 0.1 creating cpu environment
env failed 0.25 failed
SetupInstallError: uv sync failed (1):      requirements are unsatisfiable.
```

Manual reproduction with the bundled `bin/uv` and `python/bin/python3.11`:

```text
DEBUG Resolving despite existing lockfile due to mismatched requirements
  Requested torch ... index https://download.pytorch.org/whl/cpu
  Existing  torch ... index https://download.pytorch.org/whl/cu128
DEBUG No compatible version found for: msst[bs-roformer]
```

`analysis/envs/cpu/uv.lock` pins torch and its registry to the CUDA index
(`download.pytorch.org/whl/cu128`), while the CPU project/setup requests the CPU
index. `uv` rejects the lock and cannot resolve `msst` from the CPU-only index.
No CPU environment was created, so the import check could not run.

### Model and separation

`scnet-xl-ihf` installed successfully through the packaged setup:

```text
model running ... downloading model_scnet_ep_36_sdr_10.0891.ckpt
model succeeded 1.0 finished
data/models/scnet-xl-ihf/model_scnet_ep_36_sdr_10.0891.ckpt  214,063,778 B
data/models/scnet-xl-ihf/config_musdb18_scnet_xl_more_wide_v5.yaml      5,906 B
```

`make test-package` passes and status reports the model installed. Separation of
the 8 s fixture then failed:

```text
StemError: separation interpreter is missing or not executable:
/home/thomas/Documents/basseparate/.tmp-t75/data/environments/msst/bin/python
```

The packaged runtime looks for `environments/msst/bin/python`, while setup
creates `analysis/envs/cpu` at `environments/cpu`. Even with a CPU environment,
separation would not find it.

### Browser QA at 1280x720

Independent headless Chromium (not the shared browser):

```text
viewport 1280x720
.setup-page clientHeight 720, scrollHeight 1220, scrollTop 0 -> 500 (at bottom)
headings: Set up the studio, System checks, Optional GPL tools,
          Inference environment, Separation models, Demucs htdemucs_ft,
          SCNet XL IHF, BS-RoFormer-SW
links: 10, all https with target=_blank rel="noopener noreferrer"; 0 invalid
AppImage text: false
early-version warning: false
```

The page scrolls to the licence and model sections and offers no AppImage, but
the early-version warning is not rendered on the setup page.

### Required commands

```text
make test-package
  package-check: tar structure ok (6488 members)
  package-check: bundled bin/palm --help ok
  package-check: container smoke skipped (ubuntu:22.04 image not present offline)
  package-check: OK

./packaging/verify-clean-room.sh
  /api/health {"status":"ok",...}
  GET / HTTP 200
  /api/setup/status HTTP 200
  data-root files: logs/launcher.log, logs/server.log, run/launcher.lock
  clean-room verification passed
```

The clean-room script exercises launch/health only; it does not install setup
tools, environments or models. The blockers above are in packaged setup:
missing `tools` directory creation on a fresh root, a CPU lock pinned to the
CUDA index and an `msst` path that does not match the new CPU environment path.
