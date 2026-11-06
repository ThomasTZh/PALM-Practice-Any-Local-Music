# Troubleshooting

Everything here is local and offline. Start with the machine report, then the
gate; both name the failing piece instead of downloading anything.

```sh
make doctor        # toolchain, data root, Vamp pack, Piper, model bundle, GPU
make gate-lite     # fast lint/format/types/fixtures/tests
make gate          # full gate, including the browser golden path
make accept        # five-recording analysis report
```

## Environment and setup

### `make bootstrap` says a package is missing from `node_modules/.pnpm`

The web dependencies are preserved in the pnpm virtual store. Bootstrap links
`web/node_modules` from it and refuses to guess a version. If the store was
deleted, restore the preserved `node_modules/.pnpm`; do not run
`pnpm install` (it cannot fetch offline and the sandbox blocks its store lock).
The app `.venv` is likewise preserved: bootstrap verifies its imports and skips
it, and reports a readable failure if it is missing.

### `make doctor` reports `MISSING` for a required tool

Install nothing from the network. The supported machine is the one with the
preserved assets: Python 3.11 in `.venv`, Node 22 with linked
`web/node_modules`, FFmpeg/ffprobe, GNU Make, uv, `storage/tools` and
`models/htdemucs_ft`. `make doctor` exits non-zero only for required missing
items; GPU absence is informational.

### The UI is an HTML placeholder

`basseparate serve` serves `web/dist`. Build it first:

```sh
make build-web
```

`make e2e` builds it automatically. During frontend work, Vite's proxy targets
`http://127.0.0.1:8765`; start the API on that fixed port and Vite separately:

```sh
.venv/bin/basseparate serve --no-browser --port 8765 --data-root ./.data-dev
cd web && ./node_modules/.bin/vite
```

(`make dev` starts Vite plus an API on an ephemeral port; that is fine for
viewing panels but proxied `/api` calls need the fixed port above.)

### `cannot bind 127.0.0.1:<port>` or the port is busy

Stop the old server or ask for a free port: `basseparate serve --port 0`
prints the actual `bootstrap:` URL. `make e2e` picks a free port itself.

### `Read-only file system` when the server writes its data root

The default data root is the per-user application directory. In a sandboxed or
read-only home, pass an explicit writable root:

```sh
.venv/bin/basseparate serve --no-browser --port 0 --data-root ./.data-dev
```

`make e2e` and the tests already use temporary/scratch roots.

## Analysis (chords, key, BPM, bars)

### `Vamp plugin pack not found at ...`

The Piper fallback needs the preserved pack under `storage/tools/plugins` and
the Sonic Visualiser extraction under `storage/tools/sv`. Restore them; the
server never downloads plugins. `make analysis-check` reports which asset is
missing. The same check covers the native host and the model bundle.

### `Piper server not found at ...` or `Piper server is not executable`

Restore `storage/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server` and
its execute bit, or point `BASSEPARATE_PIPER` at a preserved copy. The library
directory (`BASSEPARATE_PIPER_LIBS`) must also exist.

### Analysis fails with a plugin name

Plugins are resolved by display name (`Chordino`, `Key Detector`, `Bar and Beat
Tracker`), falling back to the recorded embed keys. If the pack has different
names, the error lists what it found. `make analysis-check` verifies the pack
before a long job.

### BPM is 135.999 on a chord-pad fixture

That fixture is four sustained triads with no beat-level onsets; QM Bar and
Beat Tracker estimates 136 BPM and five bars on it. The preserved native host
returns the same 18 beats/5 bars/135.999, so the pipeline is faithfully
reporting the plugin. The metronome fixtures (`click_120.wav`,
`progression_120.wav`) prove 120 BPM and are the tempo evidence. Do not add a
fixture-specific correction; use material with a pulse.

### Key label looks odd, or `tonic` values surprise you

`qm-keydetector` emits a 1-based tonic in this pack: C=1, A=10, mode
0=major/1=minor, with the human label in `key`. Consumers must use the label
(`key` / `key_label`), not the raw tonic as a 0-based MIDI pitch class. Chords
keep Chordino's raw text (`C`, `Am`, `N`, `C:maj`); the UI normalises for
display, the analysis cache keeps the raw labels.

### A second analysis starts Piper again

It should not: the result is content-addressed by source hash, project rate,
bpb, lead-in and plugin parameters, and a cached run starts no server. If the
cache was cleared, or the pack/parameters changed, the key changes. When the
frozen plugin pack is upgraded, raise `ANALYSIS_VERSION` in `features.py`; the
cache key intentionally omits plugin versions.

### Analysis is slow or times out

Piper analyses roughly real time on this machine: the committed acceptance
report records individual recordings between about 8 and 76 s (five
recordings, 1103.98 s of audio, 213.32 s wall in that run). Long jobs can be
cancelled; the child is killed and no partial cache is published. A cancelled
job leaves the previous project revision untouched.

## Portable release and first run

The release is a read-only app tree plus a writable data root. [portable.md](portable.md)
covers the launcher, assets, setup API, upgrade/uninstall and licences in full.

### First run: ffmpeg, disk, network or setup gating

`ffmpeg` and `ffprobe` are prerequisites and are not bundled. Setup also checks
for at least 5 GiB free under the data root and for glibc. If a feature is
gated, `GET /api/setup/status` lists the exact check/tool/environment/model that
is missing; use the Setup button or `Skip setup` (skip never hides the reason,
it returns to the library and leaves the Open setup links visible).

### Tool/model download fails or resumes from .part

Retry the same card. Model downloads verify the pinned size and SHA-256 and
resume from `<data-root>/cache/model-parts/<id>/`; a checksum mismatch is
reported and never installed. Tools are independent of models. Check the data
root is writable and the network reaches the pinned HTTPS sources. Cancelling
stops the child and removes staging; retry resumes.

### Environment install fails (uv/torch/network)

Choose CPU as the safe fallback (about 500 MB) when CUDA is unavailable or the
about-3.5 GB download is too large. The error includes the captured `uv` output.
Environment creation writes only under `<data-root>/environments/` and cleans
staging after failure/cancel. In packaged mode the bundled `bin/uv` and
`bin/python` are used; a missing/corrupt app tree is a reinstall, not a data-root
repair.

### Missing model or consent rejection

Separation requires an explicitly installed model; there is no default. Missing
per-model consent returns `400`, and an uninstalled model returns `400` with the
install hint. Install the model in Setup or run `make models-install ID=<id>` in
a source checkout.

### Upgrade or uninstall

Stop PALM first. Upgrade replaces the app directory and keeps the data
root (projects/models/tools/environments/setup state). Uninstall removes the app
and, if desired, the data root; nothing is installed system-wide. Do not delete
the data root while PALM is running.

## Separation (stems)

### `model <id> is not installed` / missing model in the selector

Run `make models-list` to see installed, missing and hash-mismatch states. Install
with the exact command shown, for example:

```sh
make models-install ID=scnet-xl-ihf
make models-install bs-roformer-sw
make models-verify
```

`htdemucs_ft` is bundled and needs no install. The mixer selector disables a
missing model and shows its size and install command. `POST /api/separate`
validates the registry and installed state before queueing, so an unknown id
returns the known ids and a missing model returns the install command; it never
starts a download during a separation request.

### `hash-mismatch` / partial model files

`make models-verify` checks every declared file's size and SHA-256 against
`analysis/models.json` without network access. A partial or corrupted install
appears as missing/hash-mismatch; rerun `make models-install ID=<id>` (the
installer stages `.part` files, verifies, publishes atomically and re-verifies)
or restore the preserved `models/<id>` directory. Do not edit weights in place
and do not commit them. The cache key includes the declared model hashes, so a
repaired/replaced checkpoint cannot reuse stale stems.

### MSST model fails to start (torch/msst import error)

The optional models run in the isolated `analysis-models/.venv`, never in the
application or Demucs environment. Rebuild it offline from the preserved uv
cache:

```sh
make models-env
analysis-models/.venv/bin/python -c "import torch, msst; print(torch.__version__)"
```

`make models-env` runs `uv sync --offline --directory analysis-models` against
`storage/tmp-uv-cache`; it requires the preserved cache and `uv.lock`, and does
not download. A failed job includes the worker stderr tail. If torch reports
CUDA unavailable, the MSST worker falls back to CPU by design.

### Separation takes a long time

All separation is CPU-only here: `make doctor` reports the NVIDIA driver
unavailable and `torch.cuda.is_available()` false. Measured on the 8 s stereo
fixture: Demucs 19.24 s, SCNet XL IHF 58.20 s (3.9 GiB peak RSS), BS-RoFormer-SW
67.35 s (3.0 GiB peak RSS); linear 60 s estimates are about 7.3 and 8.4 minutes.
Demucs is the fast default; the optional six-stem BS model is the slowest.
Long jobs stream stage progress and can be cancelled.

### Cancel or failed separation

`POST /api/jobs/{id}/cancel` or the mixer Cancel marks the job cancelled; the
server writes the cancel flag/SIGTERM, waits a grace period and kills the child.
No partial stem directory is published and the previous project revision and
existing stems remain usable. A cancellation requested before the POST returns
cannot cancel anything because no job id exists yet.

### `project has no stem set` / `stems ... missing or incomplete`

Run separation first; stems are cached under `<data-root>/stems/<key>/` with
the model-specific labels. If the cache was deleted, re-run (a cached set for
the same model is reused), or pass `force: true` to the `separate` job. The
browser falls back to the mix with the notice
`Stems unavailable; playing the mix.` when a stem request fails. Old v1
Demucs-only cache entries remain readable and are reported as `htdemucs_ft`.

## Playback and practice

### No audible sound, or *Playing* with a frozen position

The player needs a user gesture (the Play button) to resume the audio context.
Playback also depends on ranged PCM: the browser sends `Range: bytes=…` and the
server must answer `206` with `Content-Range` (and `Accept-Ranges: bytes`); a
plain `200` with the whole asset makes the worklet drop chunks and the position
stick at 0. If the position is frozen, check the network response headers for
`/api/projects/{id}/pcm` and `/stem/.../pcm`. The current commit answers ranges;
older builds ignored them. Headless runs never claim audible verification, and
the browser result recorded by the final `make e2e` is the only browser claim
this documentation makes (see [progress.md](progress.md)).

### `Stems unavailable; playing the mix.`

The project advertises stems but at least one stem PCM request failed. The mix
is unmuted and playback continues. Re-run separation or remove the stale stem
set from the project document; the notice is informational, not an error.

### Position jumps or a seek looks late

Positions are extrapolated from worklet anchors with the AudioContext clock;
the transport refreshes at 50 ms and the acceptance target is a 30 ms error
after a seek. A large jump usually means the browser suspended the audio
context or a new seek generation discarded in-flight chunks. Check the
diagnostics (`underruns`, `droppedChunks`, `latencySeconds`) and try Chromium.

### Count-in or metronome does not match the song

The grid comes from the persisted analysis (`grid.beats`, `bpb`,
`offsetSeconds`). If analysis finished while the project was already open, the
engine is updated through `updateGrid`; older servers needed a reopen. Verify
the key/BPM readout and the bar/beat display; if the grid is wrong, re-run
analysis with the right beats-per-bar hint.

### Autosave status stays empty or says `save failed`

Autosave is debounced and writes only while the transport is not playing
(pause/stop flushes the position). A `409` means a stale revision: another
writer saved the project; reload it before editing. A failed write leaves the
previous JSON intact; check the data root is writable.

## Projects, export and acceptance

### `reopen` returns 409

The project references a source asset that is no longer under
`<data-root>/assets/...`. Restore the asset directory or re-import the file.
The project JSON itself is still readable through `GET /api/projects/{id}`.

### Export fails with 400

Export needs the canonical PCM and, for a stem mixdown, every referenced stem
file. Re-import or re-separate. The response is a 16-bit WAV at the project
rate with exactly `audio.frames` frames; the SHA-256 is returned for checking.

### `make accept` reports missing recordings

It prints a `missing` row per expected `audio2test` file and exits non-zero; it
never substitutes numbers. Restore the recording or pass
`--recordings-dir` to a directory that contains it. Extra `.wav` files are
analysed and added with their own rows.

### `make e2e` cannot find a browser

The config uses the installed system Chrome (`channel: "chrome"`) and the
preserved Playwright Firefox revision found under
`~/.cache/ms-playwright` (or `PLAYWRIGHT_FIREFOX_EXECUTABLE`). It never
downloads. If Chrome is missing, install it outside this offline workflow;
Chromium is required for the full transport assertions.

### A test result changed between runs

Times in `docs/acceptance/report.md` are wall-clock measurements and vary with
load; musical values (BPM, key, bars, chords) are stable. No document quotes a
result that was not produced by the committed command; consult the final gate
and acceptance entries in [progress.md](progress.md).
