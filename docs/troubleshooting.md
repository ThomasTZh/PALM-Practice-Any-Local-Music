# Troubleshooting

Common failures and their resolutions for the basseparate foundation
(Milestone 0).

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

If pnpm is installed in a non-standard location (e.g. `~/.npm-global/bin`),
ensure that directory is on `PATH`:

```sh
export PATH="$HOME/.npm-global/bin:$PATH"
```

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

## GPU unavailable but foundation still usable

**Symptom:** `doctor` reports no GPU detected.

**Cause:** No NVIDIA/AMD GPU is present, or drivers are not installed.

**Fix:** Milestone 0 does not require a GPU. The worker probe, browser
shell, and project management all function without one. GPU is only needed
for later milestones (model inference). No action required.

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
