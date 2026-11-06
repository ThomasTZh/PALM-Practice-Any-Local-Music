# PALM 0.1.0-dev — portable Linux release

PALM (Practice Any Local Music) is a local practice studio for recordings you
own. This is the portable Linux x86_64 tar build.

**Early version, limited testing and quality control.** This 0.1.0-dev build
has not had broad platform testing or a formal listening pass. The tar was
smoke-tested in a minimal Linux root fallback, not across distributions.
Expect setup failures, download and environment edge cases, and model or
licence surprises. Keep backups of projects you care about. No warranty is
provided beyond the MIT licence.

## Asset

| Asset | Size | SHA-256 |
| --- | ---: | --- |
| `PALM-0.1.0-dev-linux-x86_64.tar.gz` | TAR_SIZE B | `TAR_SHA256` |
| `SHA256SUMS` | — | contains the line above |

The tar is 66.8 MiB, well under 2 GiB. No model weights, analysis tools,
Python environments, caches, recordings, tests, `.git` or virtual environments
are included. The app tree is read-only; all setup downloads and projects stay
under the data root.

## Run it

```sh
tar -xzf PALM-0.1.0-dev-linux-x86_64.tar.gz
cd PALM-0.1.0-dev-linux-x86_64
./bin/palm
```

`bin/palm` starts the existing server, prints and opens
`http://127.0.0.1:<port>/`, keeps one instance per data root, writes
`logs/launcher.log`/`logs/server.log`, records `run/server.json`, and forwards
SIGINT/SIGTERM. Options: `--no-browser`, `--port N`, `--data-dir DIR`,
`--setup`, `--doctor`. The bundle contains a standalone Python 3.11 and `bin/uv`,
so no system Python or Node is required.

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
run state, setup state and projects.

## Verification and licences

- Clean-room and asset evidence: [VERIFICATION.md](VERIFICATION.md)
- Full guide: [../docs/portable.md](../docs/portable.md)
- Application source is MIT: [../licenses/LICENSE](../licenses/LICENSE)
- Third-party notices: [../licenses/NOTICES.md](../licenses/NOTICES.md)

Licence boundaries: Demucs code is MIT but its weights are research use only;
SCNet/MSST code is MIT and SCNet weights have no separate weight licence; the
BS-RoFormer-SW mirror has an unknown weight licence and is private use only.
Nothing is uploaded by the application.

## Known limitations in this build

- The clean-room check used the bubblewrap minimal-root fallback because no
  Ubuntu 22.04 image was available locally; the literal container path is
  CI-only and not evidenced here.
- The setup environment installer currently accepts an `offline` option but
  runs `uv` online; do not rely on offline environment creation.
- Multi-model installation is not transactional: if a later model fails, an
  earlier one may remain installed without setup state being recorded.
- Replacing an existing analysis environment can lose the old target if the
  publish step is interrupted.
- Setup readiness does not yet include tool readiness in every combination.
- GPU separation, playback on all desktop audio stacks, and a final listening
  pass were not tested for this build.
