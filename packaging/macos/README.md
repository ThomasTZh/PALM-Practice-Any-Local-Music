# macOS app wrapper

`PALM.app` is a Finder launcher for the portable tar. It expects the extracted
tar at `PALM.app/Contents/Resources/app`:

```sh
cp -R PALM-<version>-linux-x86_64 /Applications/PALM.app/Contents/Resources/app
open /Applications/PALM.app
```

The `Contents/MacOS/palm` wrapper sets `PALM_MODE=packaged`, `PALM_APP_ROOT`,
`PYTHONPATH` and executes `Contents/Resources/app/bin/palm` with the same
arguments. Finder starts it without a tty, so the Python launcher opens
Terminal.app through `osascript` (logs stay visible and Ctrl+C works) and then
opens the browser. `--status`, `--stop`, `--no-browser`, `--no-terminal` and
`--data-dir` pass through the wrapper. Spaces and non-ASCII paths are quoted by
the wrapper and the launcher's Terminal command. No native `.app` package is
built by `make package`; this is a launcher wrapper only.
