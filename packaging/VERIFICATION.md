# Clean-room verification

Status: **PASSED**

- Date: 2026-11-06T19:46:58Z
- Mode: bubblewrap minimal root (Ubuntu 22.04 image unavailable offline)
- Asset: `PALM-0.1.0-dev-linux-x86_64.tar.gz` (69978654 bytes)
- SHA256SUMS: verified
- /api/health: `{"status":"ok","version":"0.1.0-dev","data_root":"/data","ui":true}`
- setup page: HTTP 200, contains `id="root"`
- /api/setup/status: HTTP 200, packaged mode
- app root: unchanged (7b6e0a38afb0ba2af1a5e33ade174bc3d5aaaa14912bb21de84330eecaf9eb93  -)
- data-root files:

```text
logs/launcher.log 70
logs/server.log 79
run/launcher.lock 0
```

- AppImage: not shipped; documented fallback: PALM AppImage was not built: appimagetool is not available. Install the pinned appimagetool (see packaging/build-manifest.toml) or run `make package PACKAGE_ARGS="--appimage --online"` in CI. The tar.gz remains the supported portable asset. 
- Python in clean container: not checked

## Commands run

```sh
make test-package
tar -xzf /home/thomas/Documents/basseparate/dist/PALM-0.1.0-dev-linux-x86_64.tar.gz
bwrap --ro-bind <minimal-root> / ... /palm/bin/palm --no-browser --port 38379
curl http://127.0.0.1:38379/api/health
curl http://127.0.0.1:38379/
curl http://127.0.0.1:38379/api/setup/status
```

The full command/output transcript is retained in the build log while
this script runs. The container path is preferred; the bubblewrap
fallback is used only when no Ubuntu 22.04 image is available offline.
