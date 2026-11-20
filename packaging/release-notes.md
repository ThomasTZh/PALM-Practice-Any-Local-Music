# PALM 0.1.0-dev — platform pre-releases

PALM is a free practice room that runs on your own computer, for music you
already own. It splits a recording into singing, drums, bass and the rest,
shows the chords and the beat, slows the music down without changing how high
or low it sounds, and lets you loop the sections you want to practise.
Everything stays on your computer: no account, no upload and no internet
connection after setup.

**Early version.** This 0.1.0-dev build has limited testing and quality
control. It was checked on Linux, not across every distribution or audio
device. Keep backups of projects you care about. No warranty is provided
beyond the MIT licence.

## Platform pre-releases

These are separate channels. Do not describe Windows or macOS as stable,
signed, notarized or GPU-capable.

| Channel | Asset | Status |
| --- | --- | --- |
| Linux x86_64 | `PALM-0.1.0-dev-linux-x86_64.tar.gz` | Supported Linux build |
| Windows x64 | `PALM-0.1.0-dev-windows-x86_64-installer.exe` (per-user) / `.zip` (portable) | Unsigned beta, CPU only, no admin; acceptance pending laptop evidence |
| macOS Apple Silicon | `PALM-0.1.0-dev-macos-arm64.dmg` (drag to Applications) / `.zip` | Unsigned, non-notarized experimental arm64; acceptance pending one-shot evidence |

Linux is the supported target. The Windows beta is tested on Linux/CI plus
Wine and must not be called Windows-accepted until the laptop checklist is
returned. The macOS app is not notarized and has no stable-support claim until
the Apple Silicon checklist is returned. Neither non-Linux channel supports
CUDA or makes a GPU-performance claim.

## Download: Linux supported build

| File | Size | SHA-256 |
| --- | ---: | --- |
| `PALM-0.1.0-dev-linux-x86_64.tar.gz` | 70,044,949 B | `c1a6edfc75b90ad9540f015395bcc1c68189f43d578bef743f08fea4ae8be408` |
| `SHA256SUMS` | 101 B | contains the line above |

The archive is under 2 GiB. It contains no model weights, analysis tools,
Python environments, recordings, tests, caches or `.git`.

## Windows x64 beta pre-release (separate channel)

- Assets: `PALM-0.1.0-dev-windows-x86_64-installer.exe` (per-user, no admin) and
  `PALM-0.1.0-dev-windows-x86_64.zip` (portable), plus `SHA256SUMS`.
- Unsigned, x64 only, CPU inference only. No CUDA/GPU claim.
- First launch opens the licence/setup screen; managed FFmpeg/FFprobe, analysis
  tools, CPU environment and models are downloaded only after consent. Windows
  Vamp setup may show one UAC prompt; the app needs no administrator rights.
- Check for updates only opens the release page. There is no auto-updater.
- No administrator install: extract below the user profile and run
  **PALM.exe**. The control window starts the server and browser; Quit stops it.
  `palm.cmd` is diagnostic only.
- FFmpeg and ffprobe are not bundled. Use a trusted Windows build and set
  `PALM_FFMPEG`/`PALM_FFPROBE` or the user PATH before setup.
- Setup downloads Sonic Annotator, the Vamp Plugin Pack, one CPU environment
  and one chosen model below `%LOCALAPPDATA%\palm`.
- Acceptance is **pending** the no-admin laptop checklist in
  [docs/acceptance/windows-beta.md](../docs/acceptance/windows-beta.md). Do not
  call this a stable or Windows-accepted release before evidence is supplied.

## macOS Apple Silicon experimental pre-release (separate channel)

- Asset: `PALM-0.1.0-dev-macos-arm64.zip` or `.dmg`, plus `SHA256SUMS`.
- Apple Silicon arm64 only. Unsigned and not notarized. Open the DMG, drag
  **PALM.app** onto **Applications**, then right-click **Open** the first time
  or remove quarantine with `xattr -dr com.apple.quarantine ~/Applications/PALM.app`.
- CPU-first setup. No CUDA/GPU claim. FFmpeg/ffprobe are prerequisites, not
  bundled.
- Data stays in `~/Library/Application Support/palm` unless overridden.
- Acceptance is **pending** the one-shot checklist in
  [docs/acceptance/macos-experimental.md](../docs/acceptance/macos-experimental.md).
  Do not call this stable, signed, notarized or macOS-accepted before evidence
  is supplied.

## Start the Linux build

1. Download the tar and `SHA256SUMS`.
2. Extract the tar.
3. Double-click `bin/palm`, or run `./bin/palm` in a terminal.
4. A terminal opens with the server log; the setup page opens in your browser.
5. Press Ctrl+C in that terminal when you are finished. Closing only the
   browser leaves PALM running.

Press Space anywhere outside a text field to start or pause playback.

Useful commands:

```sh
./bin/palm --status          # running address, data root and process IDs
./bin/palm --stop            # stop a server left by a closed terminal
./bin/palm --data-dir DIR    # keep user data somewhere else
./bin/palm --no-browser      # do not open a browser
```

If no terminal program is available, PALM prints the log location and keeps
running. Use `--stop` afterwards.

## Updating from an older Linux build

Your projects, downloaded models, tools and environments live in the data root,
not in the app folder. Updating replaces only the app folder.

1. Stop the old server: press Ctrl+C in its terminal. If that terminal is gone,
   run `OLD_FOLDER/bin/palm --stop`.
2. Download the new tar and `SHA256SUMS`, then check the archive.
3. Extract the new folder next to the old one. Do not extract over the old
   folder, and do not delete the data root.
4. Start `NEW_FOLDER/bin/palm`. It uses the same default data root, so setup is
   not repeated and models/tools/projects stay available.
5. If the old launch used `--data-dir` or `PALM_DATA_DIR`, pass the same value
   to the new launcher.
6. After checking playback and analysis, delete the old app folder. If you
   installed the desktop entry or `~/.local/bin/palm` symlink, point it at the
   new folder.

Do not remove `~/.local/share/palm` during an update. That directory is your
data, not the application.

## Linux first run

The app is small. The optional pieces are downloaded only after you choose
them and accept their licences:

- **Analysis tools** (needed for chords, key, tempo and bars): Sonic
  Visualiser/Piper and the Vamp plugin pack, from upstream releases.
- **One runtime**: CPU (about 500 MB download) or CUDA (about 3.5 GB, needs an
  NVIDIA card and driver).
- **One separation model**, with no default: Demucs (about 321 MB, four parts),
  SCNet XL IHF (about 204 MB, four parts) or BS-RoFormer-SW (about 667 MB, six
  parts including guitar and piano).

FFmpeg and FFprobe are downloaded and verified by setup (managed), not an
external prerequisite. Setup checks for about 5 GiB
free space before downloading. Setup can be skipped; playback, importing,
sections and the spectrogram work without the optional pieces.

Licence boundaries: Demucs weights are research use only; SCNet weights have
no separate weight licence; the BS-RoFormer-SW mirror has an unknown upstream
licence and is private use only. PALM does not redistribute any of them.

## Where files go, cleanup and uninstall

The Linux default data root is `~/.local/share/palm`; Windows uses
`%LOCALAPPDATA%\palm` and macOS uses `~/Library/Application Support/palm`.
The same layout applies on every platform:

| Folder | Contents |
| --- | --- |
| `projects/`, `assets/`, `uploads/` | your project data |
| `stems/` | generated stems |
| `models/` | downloaded separation models |
| `tools/` | Sonic Visualiser, Piper and Vamp plugins |
| `environments/` | CPU or CUDA runtime |
| `cache/` | download and build cache |
| `logs/`, `run/`, `setup.json` | logs, running instance, setup state |

A source checkout uses `~/.local/share/basseparate`; using both can look like
duplicate downloads. Choose one root with `--data-dir` or `PALM_DATA_DIR`.

Deleting `cache/` is safe. Deleting `models/`, `tools/` or `environments/`
means running setup again. Back up `projects/`, `assets/` and `uploads/` before
removing a data root.

Uninstall (OS-level; no custom uninstaller):

```sh
./bin/palm --stop
rm -rf ~/.local/share/palm
rm -rf /path/to/palm-0.1.0-dev-linux-x86_64
rm -f ~/.local/bin/palm ~/.local/share/applications/palm.desktop
```

The data-root removal deletes projects, so back them up first.

## Verification

- Clean-room and asset evidence: [packaging/VERIFICATION.md](../packaging/VERIFICATION.md)
- Full guide: [docs/portable.md](../docs/portable.md)
- Application licence: [licenses/LICENSE](../licenses/LICENSE)
- Third-party notices: [licenses/NOTICES.md](../licenses/NOTICES.md)

Measured and verified for this build: packaged launcher health and setup page;
real network install of the analysis tools; real CPU environment import
(`torch 2.9.1+cpu`, `msst`, `pydantic`); real analysis with chords, key, tempo
and bars; model install and separation; setup-page scrolling and licence links;
terminal log streaming and Ctrl+C; `--status`/`--stop`; second-launch reuse;
stale-state handling. The full test gate passed with 381 Python tests and 9
skipped, plus the web and browser suites.

Not tested for this Linux build: GPU separation timing, every desktop audio
stack, and a final formal listening pass. Windows and macOS have separate
pre-release channels above and remain pending manual acceptance evidence; they
are not covered by this Linux build's testing claim.

## Build repeatability

Earlier archives were not byte-identical even from the same source because the
compressed file recorded the build time. The builder now uses a fixed archive
timestamp, omits the build-time filename, and normalises ownership and
modification times. Two clean builds from the same source and locked
dependencies produce the same SHA-256. If a rebuild produces a different hash,
something in the source or dependencies changed; the published `SHA256SUMS`
identifies the exact tested file.

## AppImage

The Linux release is tar-only. The AppImage was removed because it was
unreliable across desktops. The setup installer extracts the upstream Sonic
Visualiser AppImage itself, so a desktop AppImage integration tool is not
required. The Windows ZIP and macOS app are separate pre-release channels.
