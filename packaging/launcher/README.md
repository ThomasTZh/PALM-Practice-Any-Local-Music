# PALM launcher packaging

`palm` is the entry point for the portable tar. It sets the
packaged environment (`PALM_MODE=packaged`, `PALM_APP_ROOT`, `PALM_DATA_DIR`)
and executes the Python launcher:

```sh
"$APP_ROOT/python/bin/python3.11" -m basseparate.launcher "$@"
```

Expected app layout:

```
<app_root>/palm                  this wrapper (or <app_root>/bin/palm)
<app_root>/python/bin/python3.11  bundled standalone interpreter
<app_root>/bin/uv                pinned uv
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
environments/{cpu,cuda}/
models/
tools/
projects/ assets/ uploads/ cache/
stems/
```

The launcher starts the existing `basseparate.cli serve` command on loopback,
records the URL in `run/server.json`, opens the browser (unless
`--no-browser`), forwards SIGINT/SIGTERM and removes the run state on exit. A
second launch prints the running URL instead of starting another server.

Supported options: `--no-browser`, `--no-terminal` (also `--detach`),
`--port N`, `--data-dir DIR`, `--setup`, `--doctor`, `--status` and `--stop`;
no writes are made under the read-only app root.

`palm --status` prints the URL, data root and server/launcher pids without
starting anything. `palm --stop` reads `run/server.json`, checks that the pids
still match the launcher/server commands, sends SIGTERM, waits and removes the
state. Stale pids or a state file from another data root are reported and never
used to kill an unrelated process. Use `--data-dir` for a non-default root.

## Terminal-first launch

When `bin/palm` runs in an interactive terminal it streams the server log
lines to that terminal as they arrive and keeps writing `logs/server.log`;
Ctrl+C forwards SIGINT and stops the launcher and server cleanly.

When it is started without a tty from a file manager or desktop, it opens the
first available terminal emulator (`x-terminal-emulator`, `gnome-terminal`,
`konsole`, `xfce4-terminal`, `xterm`, `kitty`, or `alacritty`) attached to the
same launcher invocation. The child carries `PALM_TERMINAL_ACTIVE=1` and
`--no-terminal`, so a terminal/desktop that starts PALM again cannot recurse.
If no emulator is available, PALM prints the log path and continues headless;
`--no-terminal` / `--detach` skip the terminal attempt explicitly.

The desktop entry uses `Terminal=true`, so a desktop launcher also shows the
log stream and supports Ctrl+C. Install the launcher on `PATH` first, for
example:

```sh
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$PWD/bin/palm" ~/.local/bin/palm
install -m644 palm.desktop ~/.local/share/applications/palm.desktop
```

The entry's `Exec=palm` resolves through that symlink. If you keep the tar
somewhere else, use an absolute symlink or update `Exec` to the launcher path.
On a desktop whose file manager ignores `Terminal=true`, run `bin/palm` from a
terminal or add a desktop launcher whose command is `bin/palm`.

### Data roots and cleanup

The packaged default is `${XDG_DATA_HOME:-$HOME/.local/share}/palm`; a source
checkout defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/basseparate`.
Using both can download the same models/tools/environments twice. Choose one
root with `--data-dir` or `PALM_DATA_DIR`/`BASSEPARATE_DATA_DIR`.

Stop PALM before cleanup. `<data>/cache/` is safe to delete (downloads/uv cache
is rebuilt); `<data>/models/`, `<data>/tools/` and `<data>/environments/`
require setup again; `projects/`, `assets/` and `uploads/` are user data and
must be backed up. Uninstall by stopping PALM, removing the app directory and,
only if you accept losing practice data, the data root. Never delete a data
root while PALM is running.
