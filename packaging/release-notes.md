# PALM 0.1.0-dev — portable Linux release (draft)

PALM (Practice Any Local Music) is a local practice studio for recordings you
own. This is the portable Linux x86_64 build; it is a draft until explicitly
approved for publication.

## Assets

| Asset | Size | SHA-256 |
| --- | ---: | --- |
| `PALM-0.1.0-dev-linux-x86_64.tar.gz` | 69,979,096 B | `dfef052077aa50ca60289ef58fd3f4184deee9c3c45c680b33422981d0ced27d` |
| `PALM-0.1.0-dev-x86_64.AppImage` | 64,518,648 B | `61b0ecf7b8e94cd09deb6b63aa72c6ca9a4bc1bc7640ee59def5ccdf6a249233` |
| `SHA256SUMS` | — | contains both lines above |
| `RELEASE-NOTES.md` | — | this file |

No model weights, analysis tools, Python environments, caches, recordings,
tests, `.git` or virtual environments are in either asset. Each asset is well
under 2 GiB.

## Run it

```sh
tar -xzf PALM-0.1.0-dev-linux-x86_64.tar.gz
cd PALM-0.1.0-dev-linux-x86_64
./bin/palm
```

or, for the AppImage:

```sh
./PALM-0.1.0-dev-x86_64.AppImage
# no FUSE? extract instead:
./PALM-0.1.0-dev-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

The launcher prints and opens `http://127.0.0.1:<port>/`, keeps one instance per
data root, writes logs under the data root, and forwards SIGINT/SIGTERM.
Options: `--no-browser`, `--port N`, `--data-dir DIR`, `--setup`, `--doctor`.

## First run: network, disk, ffmpeg, choices

The app contains no models or tools. The first-run wizard offers three
independent pieces; nothing downloads until you press Install and accept the
licence:

1. **Analysis tools** (optional for playback, required for chords/key/BPM):
   Sonic Visualiser/Piper and the Vamp Plugin Pack. GPL/AGPL; downloaded from
   pinned upstream releases.
2. **One inference environment**: CPU (about **500 MB** download, works
   everywhere) or CUDA (about **3.5 GB**, needs an NVIDIA GPU and driver).
3. **At least one equal model card** — there is no default:
   - `htdemucs_ft` — 321.0 MiB, four stems
   - `scnet-xl-ihf` — 204.2 MiB, four stems
   - `bs-roformer-sw` — 667.0 MiB, six stems (adds guitar/piano)

`ffmpeg` and `ffprobe` must already be installed; they are not bundled. Setup
requires at least **5 GiB free** under the data root (checked before download).
The app itself does not upload audio or contact the network after setup.

`Skip setup` returns to the library. Import, Analyse and Separate then explain
what is missing and offer `Open setup`; a later setup can be completed from the
Setup button. Separation requires an explicitly installed model.

The data root defaults to `~/.local/share/palm`; override with `--data-dir` or
`PALM_DATA_DIR`. It holds models, tools, CPU/CUDA environments, caches, logs,
run state, setup state and projects. The app tree is read-only.

## Verification and licences

- Clean-room and asset evidence: [../packaging/VERIFICATION.md](VERIFICATION.md)
- Full guide: [../docs/portable.md](../docs/portable.md)
- Application source is MIT: [../licenses/LICENSE](../licenses/LICENSE)
- Third-party notices: [../licenses/NOTICES.md](../licenses/NOTICES.md)

Licence boundaries: Demucs code is MIT but its weights are research use only;
SCNet/MSST code is MIT and SCNet weights have no separate weight licence; the
BS-RoFormer-SW mirror has an unknown weight licence and is private use only.
Nothing is uploaded by the application.
