# Troubleshooting (current)

This file lists the failures likely to occur in the current Firefox/Linux
workflow. Historical M0/M1 troubleshooting is archived at
`docs/archive/troubleshooting-2026-10-24.md`.

## Port already in use

```sh
ss -ltnp | grep 18800
```

Stop the old server with `Ctrl+C`, or choose another port with
`basseparate serve --port 18801`.

## Server starts but the browser has no session

Use the bootstrap URL printed by `serve` (it contains `#token=...`). If the
tab was closed, restart the server and open the new URL. Do not reuse a URL
from a previous run.

## Relative storage root or missing worker paths

`--storage-root storage/foo` is supported; the resolved root and every derived
path are absolute. If a decode job fails with “path must be absolute”, the
running server is an older build: restart it from this checkout.

## Model not installed

Check and install explicitly while online:

```sh
.venv/bin/basseparate models verify beat_this_final0 \
  --storage-root storage/m3-ff-acceptance
BASSEPARATE_OFFLINE_MODE=false .venv/bin/basseparate models install \
  beat_this_final0 --yes
```

Existing playback, editing, and portable work do not need the model.

## Beat This! runtime missing

```sh
cd rhythm && uv sync --locked
```

The rhythm environment is separate from the application and Demucs
environments.

## Import finishes but the project is empty

The transfer completed without the canonical-decode job. A current frontend
shows **Prepare audio** in the empty project and waits for the decode job. If
not, rebuild the frontend and reload:

```sh
cd frontend && npm run build
```

## Import fails at offset 0

`CHUNK_CONFLICT` at offset 0 usually means an old frontend sent a JSON
placeholder instead of binary bytes. Rebuild the frontend
(`npm run build`), hard-reload Firefox, and retry. The failed session has no
acknowledged bytes.

## Metronome is silent or doubled

1. Hard-reload Firefox after a frontend rebuild.
2. Confirm the ruler has bar lines (a grid is required).
3. Check **Monitoring volume**, **Metronome** enabled, and metronome volume.
4. Seek to a dense section; the intro may be unmapped.
5. If clicks are rough/doubled, the running frontend is old. Current code
   keeps one render frame per source click and reports rendered clicks.

## Metronome sounds grouped rather than one per beat

`Clicks: Primary beats` follows the inferred grouping. A `7/8 (2+2+3)` label
produces a long-short grouped pattern by design. Choose **Denominator units**
for an even subdivision. If the meter is wrong (for example 7/8 on a 4/4
song), click **Re-analyze** after restarting with the current build.

## Finalizing takes minutes

The old tempo-map lookup rebuilt every segment per mapping and made meter
scoring take about 63 s for five minutes. Current code caches segments and
uses binary search. Restart the server and **Re-analyze** an old run.

## Portable project does not open

Archives are schema-version coupled. Use the build that wrote the archive, or
export a fresh archive with the current build. Do not edit the archive
database by hand.

## GPU unavailable

The host driver can be present while the agent sandbox hides
`/dev/nvidia*`. CPU analysis remains available. Do not reinstall the driver
solely because `nvidia-smi` fails inside the sandbox.

## Frontend build missing

```sh
cd frontend && npm run build
```

The backend serves `frontend/dist`; there is no runtime CDN.
