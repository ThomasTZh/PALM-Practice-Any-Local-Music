# Troubleshooting

Common failures and their resolutions. The application is at Milestone 2
(import, waveform editing, separation, practice playback, export, and
portable projects); see `docs/implementation-status.md` for the current
status.

## Port already in use

**Symptom:** `serve` exits with an error mentioning the port, or the browser
shows a connection-refused page.

**Cause:** Another process is listening on the requested port (default 8765).

**Fix:**

```sh
# Find what is using the port:
ss -tlnp | grep 8765

# Stop it, or start basseparate on a different port:
uv run --locked basseparate serve --port 8766
```

basseparate never kills a process that occupies the preferred port.

## Read-only storage directory

**Symptom:** `serve` or `doctor` reports `storage directory is not writable`.

**Cause:** The storage root (default `~/.local/share/basseparate`) is on a
read-only filesystem or has restrictive permissions.

**Fix:**

```sh
# Use a writable location:
uv run --locked basseparate serve --storage-root /tmp/basseparate

# Or fix permissions:
chmod -R u+rwX ~/.local/share/basseparate
```

## Missing frontend build

**Symptom:** `serve` exits with `frontend build not found`.

**Cause:** `frontend/dist` does not exist. The Python wheel force-includes
this directory, and `serve` verifies it at startup.

**Fix:**

```sh
uv run --locked python scripts/dev.py build
# or just the frontend:
pnpm --dir frontend run build
```

## Unsupported Python version

**Symptom:** `uv sync` fails, or `uv run` reports an incompatible interpreter.

**Cause:** The project requires Python 3.11 (`>=3.11,<3.12`).

**Fix:**

```sh
# uv installs the correct interpreter automatically:
uv python install 3.11.15
uv sync --locked
```

Do not point the project at a system Python 3.10 or 3.12.

## Missing pnpm

**Symptom:** `pnpm: command not found` during setup or build.

**Cause:** pnpm is not installed or not on `PATH`.

**Fix:**

```sh
# Install pnpm globally (Node 22 required):
npm install -g pnpm@12.8.1

# Verify:
pnpm --version   # should print 12.8.1
```

If pnpm is installed in a non-standard location (for example
`~/.npm-global/bin` or `~/.local/share/pnpm/bin`), ensure that directory
is on `PATH`:

```sh
export PATH="$HOME/.local/share/pnpm/bin:$HOME/.npm-global/bin:$PATH"
```

On this workspace (2026-10-24) the installed pnpm is 12.15.0 at
`~/.local/share/pnpm/bin/pnpm`, while the repository pins 12.8.1.
pnpm normally switches to the pinned engine automatically. If that
switch fails because the package-manager store is read-only (as in the
agent sandbox), keep using the existing `frontend/node_modules`; do not
delete it just to reinstall.

## Locked dependency mismatch

**Symptom:** `uv sync --locked` fails with `the lockfile does not satisfy
the requirements`.

**Cause:** `pyproject.toml` was edited without regenerating `uv.lock`, or
`pnpm-lock.yaml` is out of sync with `package.json`.

**Fix:**

```sh
# Python:
uv lock          # regenerate uv.lock
uv sync --locked

# Frontend:
pnpm install     # regenerate pnpm-lock.yaml
pnpm install --frozen-lockfile   # verify
```

## Browser fails to open

**Symptom:** Backend is running but no browser tab appears. The console
message says automatic opening failed and prints the bootstrap URL.

**Cause:** No desktop environment, `xdg-open` missing, or the browser
binary is not found.

**Fix:** The backend remains fully usable. Copy the printed URL:

```
http://127.0.0.1:8765/#token=...
```

and paste it into a browser manually. This is not a database or backend
failure.

## Session expires after backend restart

**Symptom:** The browser shows "session expired" after restarting the
backend.

**Cause:** The session token is generated at startup and stored in
`sessionStorage`. A backend restart produces a new token; the old one is
rejected.

**Fix:** Stop the backend, start it again, and use the new bootstrap URL
printed in the terminal. Projects persist in the database; only the
authentication token changes.

## Database schema newer than supported

**Symptom:** `serve` exits with an error about the database schema version.

**Cause:** The database file was created by a newer version of basseparate
that applied migrations this version does not recognise.

**Fix:** Downgrade is not supported. Back up the database file, then either
upgrade basseparate or delete the database to start fresh:

```sh
mv ~/.local/share/basseparate/basseparate.db ~/.local/share/basseparate/basseparate.db.bak
```

## GPU unavailable

**Symptom:** `doctor` reports `gpu (optional): nvidia-smi present but
driver query failed`, or separation is configured for a GPU device that
cannot be used.

**Cause:** No NVIDIA driver is loaded, the GPU is absent, or the sandbox
hides `/dev/nvidia*`.

**Fix:** Import, waveform editing, playback, export, and portable
projects work without a GPU. Separation can run on the explicit `cpu`
device in the isolated analysis environment, but it is several times
slower than real time. Select the GPU only when `torch.cuda.is_available()`
is true in `analysis/.venv`. GPU acceptance runs may need approved
escalated device access outside the sandbox.

## Playwright browser dependencies unavailable on Nobara

**Symptom:** `pnpm --dir frontend exec playwright test` fails with missing
system libraries (e.g. `libnss3.so`, `libatk-bridge.so`).

**Cause:** Playwright's bundled browsers need system libraries that are not
installed by default on all distributions.

**Fix:**

```sh
# Install the required system dependencies:
sudo dnf install nss atk at-spi2-atk cups-libs libdrm libxkbcommon \
    libXcomposite libXdamage libXfixes libXrandr mesa-libgbm alsa-lib pango

# Then install Playwright browsers:
pnpm --dir frontend exec playwright install chromium firefox
```

If a specific browser's dependencies cannot be resolved, that browser's
tests will be skipped. The unit and integration tests do not require
Playwright.

## Git placeholder prevents repository initialization

**Symptom:** `git init` fails, or a `.git` directory contains a placeholder
file instead of a real repository.

**Cause:** A previous setup step created a `.git` file (gitlink) or a
placeholder that conflicts with a fresh `git init`.

**Fix:**

```sh
# Remove the placeholder:
rm -f .git

# Reinitialize:
git init
git add .
git commit -m "initial commit"
```

If the placeholder is a submodule reference in a parent repository, remove
it from the parent's `.gitmodules` and `git rm` the entry before
re-initializing.

## ImportError after moving the project directory

**Symptom:** Python imports fail with `cannot import name
'PROJECT_SCHEMA_VERSION' from 'basseparate' (unknown location)`, every
test module errors during collection, or `.venv/bin/basseparate` exits with
"No such file or directory" naming an old checkout path.

**Cause:** A virtual environment is not relocatable. The editable install
stores an absolute source path in
`.venv/lib/python3.11/site-packages/_editable_impl_basseparate.pth`, and
the console scripts (`basseparate`, `pytest`, `ruff`, `mypy`) plus the
`activate*` files embed the interpreter prefix. After moving or copying the
checkout, those paths are stale even though the packages are still
installed.

**Fix (preferred):** recreate the environment from the lockfile:

```sh
rm -rf .venv
uv sync --locked
```

If recreating is not possible, repoint the old absolute prefix in the text
files under `.venv` and remove stale bytecode:

```sh
grep -rIl '/old/checkout/path' .venv
# after checking the list, rewrite it (text files only):
grep -rIl '/old/checkout/path' .venv | xargs sed -i 's#/old/checkout/path#/new/checkout/path#g'
find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
```

Verify with `.venv/bin/basseparate doctor` and a single test module before
re-running the full suite.

## Separation fails: analysis runtime or model bundle

**Symptom:** A separation job fails, the job error mentions
`ANALYSIS_RUNTIME_UNAVAILABLE`, or the worker reports that the prepared
input, normalization profile, or model bundle does not exist. `doctor`
shows `model-baseline` as unavailable.

**Cause:** The isolated analysis environment `analysis/.venv` is missing or
incomplete, or the bundled `htdemucs_ft` directory is absent or corrupted.
The application environment cannot run inference itself.

**Fix:**

```sh
cd analysis && uv sync --locked && cd ..
.venv/bin/basseparate doctor
analysis/.venv/bin/python analysis/qualify_bundled.py --device cpu
```

Re-provision `models/htdemucs_ft` from the release bundle if needed: four
checkpoint files plus `htdemucs_ft.yaml`, 336,565,233 bytes in total. The
runner verifies every size and SHA-256 against
`src/basseparate/models/registry.py` before loading; there is no remote
fallback. For a non-default analysis location, set
`BASSEPARATE_ANALYSIS_ROOT`.

## Model install refused: offline mode

**Symptom:** `basseparate models install ...` exits with "offline mode is
active" or the install boundary raises `OfflineModeError`.

**Cause:** Offline mode is enabled by default. Model installation is the
only network operation and never overrides offline mode implicitly.

**Fix:** Disable offline mode explicitly for the install action, for
example:

```sh
BASSEPARATE_OFFLINE_MODE=false \
  .venv/bin/basseparate models install beat_this_final0 --yes
```

Then restart the application without the override. No other action
downloads anything.

## Rhythm model not installed

**Symptom:** `doctor` reports `rhythm-models: ... not installed`, or a
rhythm analysis job fails with a missing-model error.

**Cause:** Beat This! checkpoints are not bundled; the user must install
one explicitly.

**Fix:** Install the required preset while online, or import a verified
offline bundle:

```sh
BASSEPARATE_OFFLINE_MODE=false .venv/bin/basseparate models install beat_this_final0 --yes
# or
.venv/bin/basseparate models import-bundle beat_this_final0 /path/to/bundle
.venv/bin/basseparate models verify beat_this_final0
```

Existing import, playback, waveform, separation, export, and portable
work is unaffected when the rhythm model is absent.

## Beat This! runtime missing

**Symptom:** Qualification or rhythm inference fails because
`rhythm/.venv/bin/python` does not exist.

**Fix:**

```sh
cd rhythm && uv sync --locked
rhythm/.venv/bin/python rhythm/qualify.py \
  --model-id beat_this_final0 \
  --checkpoint <storage>/data/models/beat_this_final0/final0.ckpt \
  --device cpu --threads 4
```

The rhythm environment is separate from the application and Demucs
environments; installing one does not create the others.
