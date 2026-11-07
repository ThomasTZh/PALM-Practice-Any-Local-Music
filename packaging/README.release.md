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

1. Extract the folder next to this README.
2. Double-click `bin/palm`. If your file manager asks, choose **Run**.
3. A terminal window opens with the server log. The setup page opens in your
   browser.

If double-clicking does not run it, open a terminal in this folder and run:

```sh
./bin/palm
```

The launcher starts the server, prints the web address, and opens the browser.
Closing the browser leaves the server running. Press **Ctrl+C** in the terminal
to stop it.

Useful commands:

```sh
./bin/palm --status          # show the running address and process IDs
./bin/palm --stop            # stop a server left by a closed terminal
./bin/palm --data-dir DIR    # keep user data somewhere else
./bin/palm --no-browser      # do not open a browser
```

If no terminal program is available, PALM prints the log location and keeps
running without a terminal window. Use `./bin/palm --stop` later.

## First time: what setup asks for

The app is small. The parts that cannot legally be bundled are downloaded only
after you choose them and accept their licences:

1. **Analysis tools** (optional; needed for chords, key, tempo and bars).
   Sonic Visualiser/Piper and the Vamp plugin pack, from their upstream
   releases.
2. **One analysis runtime**: CPU (about 500 MB download, works everywhere) or
   CUDA (about 3.5 GB, needs an NVIDIA card and driver).
3. **At least one separation model**, with no default:
   - Demucs (about 321 MB, four parts)
   - SCNet XL IHF (about 204 MB, four parts)
   - BS-RoFormer-SW (about 667 MB, six parts, including guitar and piano)

You need a network connection for whichever pieces you choose. `ffmpeg` and
`ffprobe` must already be installed. Setup checks for about 5 GiB free space
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
| `tools/` | Sonic Visualiser, Piper and Vamp plugins |
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

## Close, clean up, uninstall

- Closing the browser does not stop the server. Press **Ctrl+C** in the
  terminal, or run `./bin/palm --stop`.
- Deleting `cache/` is safe; setup downloads again if needed.
- Deleting `models/`, `tools/` or `environments/` means running setup again.
- Do not delete `projects/`, `assets/` or `uploads/` unless you mean to lose
  those projects. Back them up first.

To uninstall, stop the server, then remove:

```sh
rm -rf ~/.local/share/palm
rm -rf /path/to/palm-0.1.0-dev-linux-x86_64
rm -f ~/.local/bin/palm ~/.local/share/applications/palm.desktop
```

That deletes all PALM data, including projects. Back up `projects/` and
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

- Linux x86_64 only in this build. Windows and macOS are not packaged.
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
It does not contain model weights, Sonic Visualiser/Piper, Vamp plugins,
analysis runtimes, ffmpeg, recordings or tests.

Licences: the PALM source is MIT (`licenses/LICENSE`). Third-party components
and their terms are listed in `licenses/NOTICES.md`; downloaded tools and
weights keep their own terms. The full portable guide is in
`docs/portable.md`.
