# Portable release guide

PALM ships as platform-specific portable builds. Every bundle contains the
application, the built UI, the analysis workers/registry, environment
definitions, the launcher and licences. It does **not** contain FFmpeg, model
weights, analysis tools, Python environments, caches, recordings, tests, `.git`
or a virtual environment. The first run downloads what you choose and verifies
every file.

## Support matrix

| Platform | Status | Architecture | Inference | GPU claim |
| --- | --- | --- | --- | --- |
| Linux | **Supported** | x86_64 | CPU or CUDA | Linux CUDA path only |
| Windows | **Beta** | x64 | CPU only | No CUDA/GPU support |
| macOS | **Experimental** | Apple Silicon arm64 | CPU-first | No CUDA/GPU support |

Linux is the supported platform. The Windows build is an unsigned beta for a
normal user account; Windows acceptance is pending the laptop checklist at
[docs/acceptance/windows-beta.md](acceptance/windows-beta.md). The macOS build
is an unsigned, non-notarized experimental app for Apple Silicon; it has no
stable-support claim until the one-shot checklist at
[docs/acceptance/macos-experimental.md](acceptance/macos-experimental.md) is
completed. Do not describe either as stable, signed, notarized or GPU-capable.

| Platform | Asset | Launcher |
| --- | --- | --- |
| Linux x86_64 | `PALM-<version>-linux-x86_64.tar.gz` | desktop entry / `bin/palm` control window |
| Windows x64 beta | `.exe` installer or portable `.zip` | per-user install / double-click `PALM.exe` |
| macOS arm64 experimental | `PALM-<version>-macos-arm64.zip` / `.dmg` | double-click `PALM.app` |

Each release also provides `SHA256SUMS` and `RELEASE-NOTES.md`. Source release
notes: [../packaging/release-notes.md](../packaging/release-notes.md).
Clean-room evidence: [../packaging/VERIFICATION.md](../packaging/VERIFICATION.md).

## Normal launch: control window

### Linux

Extract the tar, install the included desktop entry if desired, and launch
PALM from the desktop menu or by double-clicking `bin/palm`. The control window
opens; no console is required. The window starts the existing server, waits for
health, opens the browser once and offers **Open browser**, **View logs**,
**Quit** and **Check for updates**. The server listens on
loopback only and writes `run/server.json`, `logs/launcher.log` and
`logs/server.log` below the data root.

### Windows beta

Extract the ZIP under your user profile and double-click **`PALM.exe`**. It is
a GUI-subsystem launcher: no console window is required, and no administrator
rights are used. `palm.cmd` is only the diagnostic fallback in the appendix.

### macOS experimental

Open the DMG and drag **`PALM.app`** onto the **Applications** shortcut, then
double-click it. If Gatekeeper
blocks the unsigned app, right-click **Open** or use System Settings > Privacy
& Security > **Open Anyway**. Finder starts the control window directly, with no
Terminal.app window.

## Appendix: diagnostic console and recovery commands

Normal users do not need this section. These options are recovery/diagnostics
only, not part of installation or first run. From a terminal in a Linux
extraction:

| Option | Meaning |
| --- | --- |
| `--no-browser` | print the URL without opening a browser |
| `--port N` | fixed port; `0` (default) asks the kernel for a free loopback port |
| `--data-dir DIR` | writable data root (default below) |
| `--setup` | create the data layout and record setup state, then exit |
| `--doctor` | print the read-only dependency report, then exit |
| `--status` | print the URL, data root and recorded pids without starting anything |
| `--stop` | stop the recorded launcher/server, remove run state and report |

`bin/uv` is included for setup's environment installation; `bin/palm` uses the
bundled `python/` tree, so no system Python or Node is required.

Click **Quit** in the control window to stop the server cleanly; closing only
the browser does **not** stop it. The window shows the URL, data root and logs.

`palm --status` prints the recorded URL, data root and pids without starting
anything. `palm --stop` validates the recorded pids against their command lines,
terminates the launcher/server gracefully and removes `run/server.json`; stale
or unrelated records are reported and never kill an arbitrary process. Use
`--data-dir` if the instance is not on the default root.

## Updates and OS-level removal

Your projects, models, tools and environments live in the data root, not the
app folder, so replacing the app does not download them again.

**Check for updates** reads `install.json`, identifies the installed channel
and version, and opens the matching release/download page in the browser with
manual instructions. It does not download, stage, swap or replace the app;
there is no custom update helper and no automatic updater.

To update, quit PALM, download the matching asset and `SHA256SUMS`, verify it,
and replace the app folder/bundle. The data root is unchanged. There is no
custom Uninstall button; remove the app with the OS tools and preserve the data
root unless you explicitly choose to delete your projects.

## Windows beta

The unsigned x64 Windows build is available as a per-user Inno Setup installer
(`PALM-<version>-windows-x86_64-installer.exe`) and as a portable ZIP. The
installer uses `PrivilegesRequired=lowest`, installs below
`%LOCALAPPDATA%\Programs\PALM`, creates per-user Start Menu/desktop shortcuts
and an uninstall entry. No administrator shell, service or machine-wide PATH
change is required. The portable ZIP can be extracted under the user profile and
launched with **`PALM.exe`**. Both paths start the GUI control window with no
console.
`PALM.exe` starts the control window, which starts the server, waits for health,
opens the browser once and offers Open browser, View logs, Quit, Check for
updates. `PALM_DATA_DIR` defaults to `%LOCALAPPDATA%\palm`; paths
with spaces and non-ASCII characters are handled by the native launcher.

FFmpeg and ffprobe are **not** an external prerequisite: setup downloads managed
FFmpeg/FFprobe after licence consent, plus Sonic Annotator and the Vamp Plugin
Pack automatically. Windows setup offers **CPU only**; CUDA is hidden. The beta
is unsigned, so SmartScreen may ask for confirmation. The installed uninstaller
offers app-only removal (default, keeps data) or also deleting
`%LOCALAPPDATA%\palm`; silent uninstall never deletes data. `palm.cmd` and
terminal flags are diagnostic fallbacks in the appendix, not normal steps. Full no-admin steps and evidence capture are in
[docs/acceptance/windows-beta.md](acceptance/windows-beta.md). Stable Windows
support is not claimed.

## macOS experimental app

`PALM.app` is an unsigned Apple Silicon arm64 app. Extract it under
`~/Applications` and right-click **Open** the first time; macOS may require
confirming **Open** or removing quarantine with
`xattr -dr com.apple.quarantine ~/Applications/PALM.app`. It is not signed or
notarized. The DMG contains `PALM.app` and an `Applications` symlink; the ZIP
contains the same app. Place the app's payload at `Contents/Resources/app` if
you assemble it manually; the packaged ZIP/DMG already contains it.

The wrapper sets `PALM_MODE=packaged`, `PALM_APP_ROOT`, the native
`PALM_DATA_DIR` (`~/Library/Application Support/palm` unless overridden) and
`PYTHONPATH`, then executes `Contents/Resources/app/bin/palm --window`. Finder
starts the control window directly, with no Terminal.app window. The control
window starts the
server, waits for health, opens the browser once and
offers Open browser, View logs, Quit and Check for updates.
`--status`, `--stop`, `--no-browser`, `--no-terminal` and `--data-dir` remain
advanced recovery flags.

Managed FFmpeg/FFprobe, Sonic Annotator and the Vamp Plugin Pack are installed
by setup after licence consent, under the data root. `PALM_FFMPEG` and
`PALM_FFPROBE` are advanced overrides only. Setup is CPU-first; CUDA is hidden
on macOS. The app is experimental and has no stable support, GPU or
notarization claim until
[docs/acceptance/macos-experimental.md](acceptance/macos-experimental.md) is
completed on Apple Silicon.

## First run: network, disk, ffmpeg

The first-run wizard installs three independent pieces. Nothing is downloaded
until you press Install and accept the relevant licence.

Installed tools live under `<data>/tools`; in packaged mode Piper and the Vamp
plugin pack are resolved there, not from the read-only app tree.

1. **Managed FFmpeg/FFprobe** (required for import/decode): downloaded and
   SHA-256 verified into `<data>/tools/ffmpeg`; no external install or
   `PALM_FFMPEG` override is needed.
2. **Analysis tools** (required for analysis): Sonic Annotator and the Vamp
   Plugin Pack (AGPL-3.0; individual plugins GPL/AGPL) are installed
   automatically into the data root after their group consent.
3. **One inference environment**: CPU (about **500 MB download**, works
   everywhere) or CUDA (about **3.5 GB download**, needs an NVIDIA GPU and
   driver). PyTorch wheels come from the pinned CPU or cu128 index.
4. **At least one separation model**: all three are equal cards, with no
   default and no bundled model:
   - `htdemucs_ft` — 321.0 MiB, four stems (drums, bass, other, vocals)
   - `scnet-xl-ihf` — 204.2 MiB, four stems
   - `bs-roformer-sw` — 667.0 MiB, six stems (bass, drums, other, vocals,
     guitar, piano)

**FFmpeg and FFprobe are managed by setup**, not external prerequisites. The
**Install recommended setup** flow downloads both after consent, verifies the
pinned SHA-256 and records them under `<data>/tools/ffmpeg`. `PALM_FFMPEG` and
`PALM_FFPROBE` remain advanced overrides for a custom binary, not normal setup.

Windows is CPU-only. macOS Apple Silicon is CPU-first. CUDA is a Linux-only
option and is hidden from setup on Windows/macOS.

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
| Linux tar | extracted directory | `~/.local/share/palm` (or `PALM_DATA_DIR` / `--data-dir`) |
| Windows ZIP | extracted `palm-*-windows-x86_64` | `%LOCALAPPDATA%\palm` (or `PALM_DATA_DIR` / `--data-dir`) |
| macOS app | `PALM.app/Contents/Resources/app` | `~/Library/Application Support/palm` (or `PALM_DATA_DIR` / `--data-dir`) |

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

**Two roots can duplicate downloads.** Linux packaged builds default to
`~/.local/share/palm`; Windows uses `%LOCALAPPDATA%\palm`; macOS uses
`~/Library/Application Support/palm`; a source checkout defaults to
`~/.local/share/basseparate`. Models, tools and environments live under
whichever root is active. If both modes or platforms are used, the same model
can be downloaded twice. Pick one root and pass `--data-dir` to source
commands, or set `PALM_DATA_DIR` (packaged) and `BASSEPARATE_DATA_DIR` (source)
to the same path. `palm --status` shows which root the running launcher uses.
Do not run two servers against one data root; the launcher lock prevents it.

### Safe cleanup

Stop PALM with **Quit** in the control window. Then:

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

- **ffmpeg missing / import fails**: open **Setup** and install managed
  media tools; setup downloads/verifies FFmpeg and FFprobe under the data root.
  Do not install a system FFmpeg as the normal fix; `PALM_FFMPEG` overrides are
  advanced only.
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

**Upgrade:** use **Check for updates** to open the release page, quit PALM,
download and verify the asset, then replace the app folder/bundle. The data root
is preserved.

**Uninstall:** quit PALM and remove the app with the OS (Windows Installed
apps/Explorer, macOS Trash, Linux file manager) or the commands below for a
portable folder. Moving `PALM.app` to the Trash leaves
`~/Library/Application Support/palm` (projects, models and tools) in place. Projects, models and tools remain in the data root; delete it
only if you explicitly intend to remove practice data after backing up:

```sh
# Linux
rm -rf ~/.local/share/palm
# macOS
rm -rf "$HOME/Library/Application Support/palm"
# Windows PowerShell
Remove-Item "$env:LOCALAPPDATA\palm" -Recurse -Force
```

Also remove any `--data-dir`/`PALM_DATA_DIR` environment override you added.
Back up `projects/`, `assets/` and `uploads/` first; deletion is permanent.
Nothing is installed system-wide. Removing only the app leaves the data
untouched for a later reinstall.

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
