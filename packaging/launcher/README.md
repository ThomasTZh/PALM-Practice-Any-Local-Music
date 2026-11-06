# PALM launcher packaging

`palm` is the entry point for the portable tar and AppImage. It sets the
packaged environment (`PALM_MODE=packaged`, `PALM_APP_ROOT`, `PALM_DATA_DIR`)
and executes the Python launcher:

```sh
"$APP_ROOT/bin/python" -m basseparate.launcher "$@"
```

Expected app layout:

```
<app_root>/palm                  this wrapper (or <app_root>/bin/palm)
<app_root>/bin/python            packaged interpreter
<app_root>/src/basseparate/      application package
<app_root>/analysis/             workers, models.json, checkpoints.json
<app_root>/web/dist/             built UI
```

Everything writable lives below the data root, by default
`${XDG_DATA_HOME:-$HOME/.local/share}/palm`:

```
logs/launcher.log
logs/server.log
run/launcher.lock
run/server.json
setup.json
environments/{demucs,msst}/
models/
tools/
projects/ assets/ uploads/ cache/
```

The launcher starts the existing `basseparate.cli serve` command on loopback,
records the URL in `run/server.json`, opens the browser (unless
`--no-browser`), forwards SIGINT/SIGTERM and removes the run state on exit. A
second launch prints the running URL instead of starting another server.

Supported options: `--no-browser`, `--port N`, `--data-dir DIR`, `--setup`
and `--doctor`. The AppImage should install `palm.desktop` and call the same
wrapper; no writes are made under the read-only app root.
