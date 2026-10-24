# rhythm — isolated Beat This! environment (M3.2)

Dedicated runtime for Beat This! inference. The application never
imports torch or `beat_this`; it launches this environment by explicit
interpreter path (`rhythm/.venv/bin/python`).

## Pinned versions

- Python 3.11.15 (uv-managed)
- `beat-this==1.1.0` (upstream tag `v1.1.0`)
- torch / torchaudio `2.9.1+cu128` from the `pytorch-cu128` index
- `soxr`, `einops`, `rotary-embedding-torch` resolved by `uv.lock`

The CUDA wheels also run on CPU when no driver is loaded.

## Create or update

```sh
cd rhythm
uv sync --locked
```

The application environment is unchanged; this is a separate project.

## Install a model

Models are never bundled and never downloaded automatically. The app
must have offline mode off for an online install:

```sh
BASSEPARATE_OFFLINE_MODE=false \
  ../.venv/bin/basseparate models install beat_this_final0 --yes
```

Offline bundle import:

```sh
../.venv/bin/basseparate models import-bundle beat_this_final0 <bundle-dir>
```

A bundle directory contains the registered `manifest.json` and the
checkpoint file. The install service verifies identity, size, and
SHA-256 before publishing into the managed store.

## Qualify

```sh
rhythm/.venv/bin/python rhythm/qualify.py \
  --model-id beat_this_final0 \
  --checkpoint <storage>/data/models/beat_this_final0/final0.ckpt \
  --device cpu --threads 4
```

The script sets the offline flags before importing torch, passes an
explicit local checkpoint, runs the deterministic fixture twice, and
writes a JSON report next to the checkpoint. Exit code 0 means
qualified.

## Worker

`worker.py` is the protocol-v2 activation worker launched by the backend:

```sh
rhythm/.venv/bin/python rhythm/worker.py
```

It accepts one `rhythm_activation` run at a time, writes `beat.npy` and
`downbeat.npy` into the assigned staging directory, and reports progress
and peak memory. The backend validates and publishes the artifact; the
worker never touches the database or the final artifact store. It is not
a standalone CLI.

## Notes

- The application never downloads on startup, project open, or
  `doctor`.
- GPU qualification requires a loaded NVIDIA driver; record the GPU UUID
  and device profile in the report when available.
- Activation semantics: framewise logits at 50 fps (22,050 Hz, hop 441);
  apply sigmoid in the decoder, never store it as calibrated confidence.
