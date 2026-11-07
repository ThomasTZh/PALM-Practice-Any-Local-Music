# Portable release guide

PALM ships as a self-contained Linux x86_64 tar. It contains the application,
the built UI, the analysis workers/registry, environment definitions, the
launcher, the desktop entry/icon and licences. It does **not** contain model
weights, analysis tools, Python environments, caches, recordings, tests, `.git`
or any virtual environment. The first run downloads what you choose and
verifies every file.

- Release assets: `PALM-<version>-linux-x86_64.tar.gz`, `SHA256SUMS`,
  `RELEASE-NOTES.md`
- Source release notes: [../packaging/release-notes.md](../packaging/release-notes.md)
- Clean-room evidence: [../packaging/VERIFICATION.md](../packaging/VERIFICATION.md)

## Run the tar

```sh
tar -xzf PALM-<version>-linux-x86_64.tar.gz
cd PALM-<version>-linux-x86_64
./bin/palm
```

The launcher prints `palm: running at http://127.0.0.1:<port>/` and opens your
browser. It starts the existing server, keeps one instance per data root,
records `run/server.json`, writes `logs/launcher.log` and `logs/server.log`,
and forwards SIGINT/SIGTERM. The application listens on loopback only.

Launcher options:

| Option | Meaning |
| --- | --- |
| `--no-browser` | print the URL without opening a browser |
| `--port N` | fixed port; `0` (default) asks the kernel for a free loopback port |
| `--data-dir DIR` | writable data root (default below) |
| `--setup` | create the data layout and record setup state, then exit |
| `--doctor` | print the read-only dependency report, then exit |
| `--status` | print the URL, data root and recorded pids without starting anything |
| `--stop` | stop the recorded launcher/server, remove run state and report |

`bin/uv` is included for the setup's environment installation; `bin/palm` uses
the bundled `python/` tree, so no system Python or Node is required.

## Stop, status and terminal lifecycle

`palm --status` is read-only. It prints the URL recorded in
`<data>/run/server.json`, the data root and the server/launcher pids, and exits
1 for missing, stale or invalid state. It never starts a server.

`palm --stop` validates the recorded pids against their command lines, sends
SIGTERM to the launcher (which forwards it to the server), waits, and removes
`run/server.json`. If a pid is gone, the command no longer matches, or the
recorded data root is different, it reports the stale record and does not kill
an unrelated process. Use `--data-dir` if the instance is not on the default
root.

Closing only the browser does **not** stop the server. The terminal stays open
with live logs and Ctrl+C, or `palm --stop` stops it later. A file-manager
double-click on `bin/palm` opens an attached terminal and leaves it open for the
same reason; if no terminal emulator exists, it prints the log path and runs
headless. Install the desktop entry and a `palm` symlink as described in
[packaging/launcher/README.md](../packaging/launcher/README.md) so a desktop
launch uses `Terminal=true` without typing commands.

## First run: network, disk, ffmpeg

The first-run wizard installs three independent pieces. Nothing is downloaded
until you press Install and accept the relevant licence.

Installed tools live under `<data>/tools`; in packaged mode Piper and the Vamp
plugin pack are resolved there, not from the read-only app tree.

1. **Analysis tools** (optional for practice, required for analysis): Sonic
   Visualiser/Piper (GPL-2.0-or-later) and the Vamp Plugin Pack (AGPL-3.0;
   individual plugins GPL/AGPL). These are downloaded from their pinned
   upstream releases.
2. **One inference environment**: CPU (about **500 MB download**, works
   everywhere) or CUDA (about **3.5 GB download**, needs an NVIDIA GPU and
   driver). PyTorch wheels come from the pinned CPU or cu128 index.
3. **At least one separation model**: all three are equal cards, with no
   default and no bundled model:
   - `htdemucs_ft` — 321.0 MiB, four stems (drums, bass, other, vocals)
   - `scnet-xl-ihf` — 204.2 MiB, four stems
   - `bs-roformer-sw` — 667.0 MiB, six stems (bass, drums, other, vocals,
     guitar, piano)

**FFmpeg and ffprobe must already be installed** (`ffmpeg -version`); they are
used for import/decode and are not bundled. The setup page reports this check
and links back here.

**Disk:** setup requires at least **5 GiB free** (it checks before downloading);
the three models together are about 1.2 GiB, so choose only the model(s) you
need. The CPU/CUDA environments and downloaded models live under the data root.

**Network:** use a working connection for the first-run downloads. If the tools,
models and environment are already present (for example on a machine restored
from a backup), setup recognises them and no download is needed. The app itself
never uploads audio or contacts the network after setup.

**Skip path:** `Skip setup` returns to the library. Import, Analyse and Separate
then show plain-language reasons and an `Open setup` link; nothing is silently
disabled. You can reopen the wizard from the Setup button. A skip is recorded
in the setup state and does not block a later complete setup.

### Choosing a model

There is no implicit model. The mixer's `Choose a model` selector stays
unselected until you pick one; missing models are disabled with their size and
install command. Separation requires an explicit installed model. A project
reopens with its recorded `stemModel`; if that model is no longer installed the
UI falls back to requiring a new choice rather than guessing Demucs.

## Where files live

| Mode | App root (read-only) | Data root (writable) |
| --- | --- | --- |
| Source checkout | repository checkout | `~/.local/share/basseparate` (or `PALM_DATA_DIR` / `BASSEPARATE_DATA_DIR`) |
| Packaged tar | extracted directory | `~/.local/share/palm` (or `PALM_DATA_DIR` / `--data-dir`) |

The data root contains:

```
projects/ assets/ uploads/ tmp/ .locks/    library and decoded audio
stems/                                   separated stem PCM, keyed by model/cache
models/                                  verified model weights (chosen models)
tools/                                   Sonic Visualiser/Piper and Vamp plugins
environments/cpu/ environments/cuda/     inference environments
cache/                                   download parts and caches
logs/launcher.log logs/server.log        launcher/server logs
run/launcher.lock run/server.json         single-instance lock and URL
setup.json                               setup choices/skip state
```

In packaged mode the app tree is read-only by contract; setup writes only below
the data root. In source mode the checkout and data root are separate too, but
`make models-*`/`make bootstrap` retain the preserved developer assets.

**Two roots can duplicate downloads.** The packaged app defaults to
`~/.local/share/palm`; a source checkout defaults to
`~/.local/share/basseparate`. Models, tools and environments live under
whichever root is active. If both modes are used, the same model can be
downloaded twice. Pick one root and pass `--data-dir "$HOME/.local/share/palm"`
to source commands, or set `PALM_DATA_DIR` (packaged) and
`BASSEPARATE_DATA_DIR` (source) to the same path. `palm --status` shows which
root the running launcher uses. Do not run two servers against one data root;
the launcher lock prevents it.

### Safe cleanup

Stop PALM first (`palm --stop`, Ctrl+C, or close the terminal). Then:

- Safe to delete: `<data>/cache/` (downloads, uv cache; rebuilt or re-downloaded
  on demand), `<data>/logs/` (diagnostics), stale `<data>/run/server.json`.
- Keep unless you accept a download/setup: `<data>/models/`, `<data>/tools/`,
  `<data>/environments/`. Deleting them requires reinstalling through setup.
- Keep your work: `<data>/projects/`, `assets/` and `uploads/`. Back these up
  before any cleanup. Never delete `<data>` while PALM is running.

## First-run setup API

The wizard is a client of these routes; they are also usable with `curl`.
Consent is explicit on the request (Boolean flags are accepted for
compatibility; the UI sends `accept_licenses`/`accepted_model_ids`).

| Method | Path | Request | Result |
| --- | --- | --- | --- |
| GET | `/api/setup/status` | — | mode, roots, checks (glibc/disk/ffmpeg), tools, both environment variants, all model states, readiness, skip/state |
| POST | `/api/setup/tools` | `{accept_licenses:true, force?}` | `202` setup job id |
| POST | `/api/setup/environments` | `{variant:"cpu"\|"cuda", accept_licenses:true, offline?}` or `variants: [...]` | `202` setup job id |
| POST | `/api/setup/models` | `{model_ids:[...], accepted_model_ids:[...], accept_licenses:true, force?}` | `202` setup job id |
| POST | `/api/setup/skip` | `{skip:true}` | updated status |
| GET | `/api/jobs/{id}` / `/events` | — | progress/SSE and terminal result |

Missing consent is `400`; a missing `model_id` at separation is `422`; an
unknown or uninstalled model is `400` with a setup hint. Model downloads resume
from stable `.part` files under the data root's `cache/model-parts/`; staging is
cleaned after success or cancel, and parts are kept for retry after interruption.
The downloaded size/SHA-256 must match the registry pins.

## Troubleshooting first-run failures

- **ffmpeg missing / import fails**: install `ffmpeg` and `ffprobe` from your
  distribution, then reload. The setup checks report the exact missing command.
- **Not enough disk / disk check fails**: free space under the data root; setup
  requires 5 GiB. Models are installed one at a time; remove unused models with
  `make models-*` only in source mode, or delete their directories in the data
  root when PALM is stopped.
- **Download fails, hash mismatch, or connection drops**: retry the same card.
  `.part` files resume; a complete file is verified against the pinned size and
  SHA-256 before publication. A hash mismatch is reported, not installed.
- **Environment installation fails**: the error includes the captured `uv`
  output. Check the data root is writable and the network reaches the pinned
  PyTorch index; CPU is the safe fallback. Cancelling stops the `uv` child and
  removes staging.
- **Tools install fails**: the Sonic Visualiser/Vamp downloads are independent;
  retry after checking network/disk. Tools are optional for playback but
  required for chord/key/BPM analysis.
- **Setup says ready but a feature is gated**: checks, environment, and at least
  one model are required; tools are required for analysis. Use the Setup button
  or `GET /api/setup/status` to see the exact reason.
- **Permission errors**: choose a writable `--data-dir`; the app root is
  intentionally read-only. Do not run the tar as root.

## Upgrade and uninstall

**Upgrade:** stop PALM with `palm --stop`, replace the extracted app directory
with the new release, and keep the data root. Models, tools, environments, setup
state and projects stay valid; if a pinned download changed, setup reports the
affected item and offers a verified reinstall. Do not copy the old app tree over
the new one.

**Uninstall:** stop PALM first (`palm --stop` or Ctrl+C), then remove the app
directory. To remove practice data as well, delete the data root
(`~/.local/share/palm` for the packaged build,
`~/.local/share/basseparate` for source). Back up `projects/`/`assets/` first;
deletion is permanent. Nothing is installed system-wide. Removing only the app
leaves the data untouched for a later reinstall.

## Licence boundaries

PALM application source is **MIT** (`licenses/LICENSE`). The bundled Python and
uv have their own permissive licences. The first-run tools and model weights
are **not** covered by MIT:

- Sonic Visualiser/Piper: GPL-2.0-or-later; Vamp Plugin Pack: AGPL-3.0 with
  individual plugin licences.
- Demucs code: MIT; the `htdemucs_ft` weights are research-use only.
- SCNet/MSST code: MIT; SCNet weights are distributed by MSST with no separate
  weight licence.
- BS-RoFormer-SW: mirror has an unknown upstream weight licence and is treated
  as **private use only**; do not redistribute the weights.

Full notices, hashes and source pins: [licenses/NOTICES.md](../licenses/NOTICES.md)
and [../licenses/LICENSE](../licenses/LICENSE).


## Build repeatability

Earlier portable archives were not byte-identical even when built from the same
source, because the compressed archive recorded the build time in its header.
The builder now fixes the archive timestamp, omits the build-time filename and
normalises ownership and modification times. Two clean builds from the same
source and locked dependencies produce the same SHA-256. The published
`SHA256SUMS` identifies the exact file that was tested; a different hash means
the source or dependency set changed.

## AppImageLauncher

PALM no longer ships an AppImage. The setup installer downloads the upstream
Sonic Visualiser AppImage and extracts it into the data root itself; a desktop
AppImage integration tool such as AppImageLauncher is not required. If an old
AppImageLauncher intercepts the download during setup on a particular desktop,
disable that integration for the setup run or install the tools manually under
`<data>/tools`.
