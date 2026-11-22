# PALM: Practice Any Local Music

PALM is a free practice room that runs on your own computer, for music you
already own. It splits a recording into singing, drums, bass and the rest,
shows the chords and the beat, slows the music down without changing how high
or low it sounds, and lets you loop the sections you want to practise.
Everything stays on your computer: no account, no upload and no internet
connection.

**Early version.** This is a 0.1.0-dev build with limited testing and quality
control. Keep your own backup of any project you care about. Expect rough
edges, especially around setup and less common audio devices.

## Start it

1. Extract the tar folder.
2. Launch the included desktop entry, or double-click `bin/palm`.
3. The PALM control window opens; it starts the server, opens the browser once
   and offers **Open browser**, **View logs**, **Quit** and **Check for updates**.

Quit stops the server. Closing only the browser leaves it running. Check for
updates opens the matching release page with manual instructions; PALM does not
update itself. Remove the app with the file manager or desktop uninstaller;
your data root is preserved.

Press Space anywhere outside a text field to start or pause playback.

Recovery options are in `docs/portable.md`; normal use does not need a terminal.

## First time: what setup asks for

FFmpeg/FFprobe 9.0.2, Sonic Annotator 1.7 and the required Vamp plugins are
bundled in the app payload with licence/source archives. Setup detects them;
there is no tool download, UAC or manual plugin install. Only these pieces are
downloaded after you choose them and accept their licences:

1. **One analysis runtime**: CPU (about 500 MB download, works everywhere) or
   CUDA (about 3.5 GB, needs an NVIDIA card and driver).
2. **At least one separation model**, with no default:
   - Demucs (about 321 MB, four parts)
   - SCNet XL IHF (about 204 MB, four parts)
   - BS-RoFormer-SW (about 667 MB, six parts, including guitar and piano)

You need a network connection only for the runtime/model you choose. Bundled
FFmpeg/FFprobe, Sonic Annotator and Vamp plugins need no download and are not
external prerequisites. Setup checks for about 5 GiB free space
before downloading. You can skip setup and use playback, importing, sections
and the spectrogram without the optional pieces; the Analyse and Separate
buttons will explain what is missing and link back to setup.

Some downloads carry their own terms: Demucs weights are research use, SCNet
weights have no separate weight licence, and the BS-RoFormer-SW mirror has an
unknown licence and is private use only. PALM does not redistribute any of
them.

## Where your files go

By default the app keeps user data in `~/.local/share/palm`:

| Folder | What it holds |
| --- | --- |
| `projects/` | your project files |
| `assets/` | imported audio |
| `stems/` | generated stems (can be regenerated) |
| `models/` | downloaded separation models |
| `tools/` | writable overrides for bundled FFmpeg/Sonic/Vamp |
| `environments/` | CPU or CUDA analysis runtime |
| `cache/` | download and build cache |
| `logs/` | launcher and server logs |
| `run/` | the running instance record |
| `setup.json` | setup choices and licence acceptance |

A source-checkout install uses `~/.local/share/basseparate` instead. Using both
can look like duplicate downloads; pick one data folder with `--data-dir` or
`PALM_DATA_DIR`.

The app itself does not need to be installed system-wide. If you install the
desktop entry, PALM also places a `palm` link in `~/.local/bin` and a menu entry
in `~/.local/share/applications`.

## Updating from an older PALM

Your projects, downloaded models, tools and environments live in the data root,
not in the app folder. Updating replaces only the app folder.

1. Quit the old PALM control window (or use the recovery `--stop` option).
2. Download the new tar and `SHA256SUMS`, then check the archive.
3. Extract the new folder next to the old one. Do not extract over the old
   folder, and do not delete the data root.
4. Launch the new folder's desktop entry or `bin/palm`. It uses the same default
   data root, so setup is not repeated and models/tools/projects stay available.
5. If the old launch used `--data-dir` or `PALM_DATA_DIR`, pass the same value
   to the new launcher.
6. After checking playback and analysis, delete the old app folder. If you
   installed the desktop entry or `~/.local/bin/palm` symlink, point it at the
   new folder.

Do not remove `~/.local/share/palm` during an update. That directory is your
data, not the application.

## Close, clean up, uninstall

- Closing the browser does not stop the server. Click **Quit** in the control
  window. Recovery: run `./bin/palm --stop`.
- Deleting `cache/` is safe; setup downloads again if needed.
- Deleting `models/`, `tools/` or `environments/` means running setup again.
- Do not delete `projects/`, `assets/` or `uploads/` unless you mean to lose
  those projects. Back them up first.

To remove the application, quit PALM, delete the app folder and remove the
desktop entry/symlink. The data root is separate and is kept by default:

```sh
rm -rf /path/to/palm-0.1.0-dev-linux-x86_64
rm -f ~/.local/bin/palm ~/.local/share/applications/palm.desktop
```

Only if you intend to remove practice data, delete
`~/.local/share/palm` (or your custom `--data-dir`) after backing up
`projects/`, `assets/` and `uploads/`. Back up `projects/` and
`assets/` first if you need them.

## What it does

- Imports local audio or video and stores one decoded copy with waveform peaks.
- Separates stems with one of three equal choices; none is preselected.
- Reads chords, key, beats and bars through the local Vamp tools.
- Plays with 0.25–2x speed while keeping the pitch, with metronome, count-in,
  loops and bar-snapped sections.
- Shows a mix waveform, synced stem lanes, a chord ribbon and a note-labelled
  spectrogram.

## Known limitations

- Linux x86_64 is the supported build. Windows has a separate unsigned CPU-only beta installer/ZIP; macOS has a separate unsigned experimental Apple Silicon app/DMG.
- The server listens only on the local machine. There are no accounts, cloud
  processing or multi-user features.
- Pitch shifting is not offered; speed changes keep the pitch.
- Analysis depends on the Vamp plugins. Relative major/minor ambiguity and the
  tempo estimate on beatless material are plugin behaviour, not PALM bugs.
- GPU separation works in principle, but this build has no GPU timing or final
  listening evidence.
- The AppImage was removed because it was not reliable across desktops. This
  tar is the supported download.
- **Build repeatability:** earlier builds were not byte-identical even from the
  same source, because the compressed archive recorded the build time. That is
  fixed: the archive now uses a fixed timestamp and no build-time filename, so
  the same source and locked dependencies produce the same hash. The published
  `SHA256SUMS` always identifies the exact file that was tested. If a rebuild
  produces a different hash, something in the source or dependencies changed;
  do not assume the old download is broken.

## What is inside

The folder contains the app, the built web page, analysis workers, setup code,
the launcher, desktop entry/icon, licence notices and a bundled Python runtime.
It does not contain model weights, inference environments,
analysis runtimes, ffmpeg, recordings or tests.

Licences: the PALM source is MIT (`licenses/LICENSE`). Third-party components
and their terms are listed in `licenses/NOTICES.md`; bundled tools and
weights keep their own terms. The full portable guide is in
`docs/portable.md`.
