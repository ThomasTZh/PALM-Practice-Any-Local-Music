# Clean-room verification

Status: **PASSED**

- Date: 2026-11-06T21:04:42Z
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
bwrap --ro-bind <minimal-root> / ... /palm/bin/palm --no-browser --port 58901
curl http://127.0.0.1:58901/api/health
curl http://127.0.0.1:58901/
curl http://127.0.0.1:58901/api/setup/status
```

The full command/output transcript is retained in the build log while
this script runs. The container path is preferred; the bubblewrap
fallback is used only when no Ubuntu 22.04 image is available offline.
