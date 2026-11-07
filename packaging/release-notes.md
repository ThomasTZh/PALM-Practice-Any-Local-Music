# PALM 0.1.0-dev — portable Linux release

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

## Download

| File | Size | SHA-256 |
| --- | ---: | --- |
| `PALM-0.1.0-dev-linux-x86_64.tar.gz` | 70,044,734 B | `c26baa055af16228b9a023070354184b889dafc3cc065cd3770ea834596fc0ba` |
| `SHA256SUMS` | 101 B | contains the line above |

The archive is under 2 GiB. It contains no model weights, analysis tools,
Python environments, recordings, tests, caches or `.git`.

## Start it

1. Download the tar and `SHA256SUMS`.
2. Extract the tar.
3. Double-click `bin/palm`, or run `./bin/palm` in a terminal.
4. A terminal opens with the server log; the setup page opens in your browser.
5. Press Ctrl+C in that terminal when you are finished. Closing only the
   browser leaves PALM running.

Useful commands:

```sh
./bin/palm --status          # running address, data root and process IDs
./bin/palm --stop            # stop a server left by a closed terminal
./bin/palm --data-dir DIR    # keep user data somewhere else
./bin/palm --no-browser      # do not open a browser
```

If no terminal program is available, PALM prints the log location and keeps
running. Use `--stop` afterwards.

## First run

The app is small. The optional pieces are downloaded only after you choose
them and accept their licences:

- **Analysis tools** (needed for chords, key, tempo and bars): Sonic
  Visualiser/Piper and the Vamp plugin pack, from upstream releases.
- **One runtime**: CPU (about 500 MB download) or CUDA (about 3.5 GB, needs an
  NVIDIA card and driver).
- **One separation model**, with no default: Demucs (about 321 MB, four parts),
  SCNet XL IHF (about 204 MB, four parts) or BS-RoFormer-SW (about 667 MB, six
  parts including guitar and piano).

`ffmpeg` and `ffprobe` must already be installed. Setup checks for about 5 GiB
free space before downloading. Setup can be skipped; playback, importing,
sections and the spectrogram work without the optional pieces.

Licence boundaries: Demucs weights are research use only; SCNet weights have
no separate weight licence; the BS-RoFormer-SW mirror has an unknown upstream
licence and is private use only. PALM does not redistribute any of them.

## Where files go, cleanup and uninstall

The default data root is `~/.local/share/palm`:

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

Uninstall:

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

Not tested for this build: GPU separation timing, every desktop audio stack,
non-Linux systems, and a final formal listening pass.

## Build repeatability

Earlier archives were not byte-identical even from the same source because the
compressed file recorded the build time. The builder now uses a fixed archive
timestamp, omits the build-time filename, and normalises ownership and
modification times. Two clean builds from the same source and locked
dependencies produce the same SHA-256. If a rebuild produces a different hash,
something in the source or dependencies changed; the published `SHA256SUMS`
identifies the exact tested file.

## AppImage

This release is tar-only. The AppImage was removed because it was unreliable
across desktops. The setup installer extracts the upstream Sonic Visualiser
AppImage itself, so a desktop AppImage integration tool is not required.
