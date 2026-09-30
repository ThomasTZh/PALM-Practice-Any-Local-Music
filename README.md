# basseparate

Local music-analysis and bass practice application.

## What Milestone 0 does

- Loopback-only HTTP service (127.0.0.1, no external network)
- Browser shell with project management (create, list, open)
- Persistent empty projects (SQLite, WAL mode)
- Bearer-token authentication with session bootstrap via URL fragment
- Worker process protocol (newline-delimited JSON) with model-free probe
- Structured logging (console + rotating file)
- Reproducible environments (uv.lock, pnpm-lock.yaml)
- Contract generation (OpenAPI → TypeScript)
- Diagnostics (`doctor`, `version`, `worker-probe`)

## What is not implemented yet

- Audio import and analysis
- Machine-learning models (no model weights are bundled)
- GPU inference
- Multi-user support
- Mobile or non-Linux platforms

## Supported platform

Linux (initial target: Nobara). Other POSIX systems may work but are not
tested.

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.11.15 | Managed by uv; system Python is not used |
| Node | 22.22.2 | Frontend build and tests only |
| pnpm | 12.8.1 | Frontend package manager |
| FFmpeg | 8.x | System package (`ffmpeg`, `ffprobe`) |
| uv | 0.12+ | Python environment manager |

## Setup

```sh
uv run --locked python scripts/dev.py setup
```

This installs locked Python dependencies (`uv sync --locked`) and frontend
dependencies (`pnpm install --frozen-lockfile`). Network access is required
for this step only.

## Build

```sh
uv run --locked python scripts/dev.py build
```

Builds the frontend (`frontend/dist`) and the Python wheel (`dist/`).

## Run

```sh
uv run --locked basseparate serve
```

Starts the service on `127.0.0.1:8765` and opens a browser tab. Use
`--no-browser` to skip the browser and print the bootstrap URL instead:

```sh
uv run --locked basseparate serve --no-browser
```

Optional flags: `--port N`, `--storage-root /path`.

## Shutdown

Press **Ctrl-C** (SIGINT) or send SIGTERM. The service:

1. Stops accepting new requests
2. Completes active short operations
3. Closes the database
4. Releases the instance lock
5. Exits with code 0

## Storage locations

| Category | Default path | Override |
|----------|-------------|----------|
| Config | `~/.config/basseparate` | `--storage-root` |
| Data (database) | `~/.local/share/basseparate` | `--storage-root` |
| Cache | `~/.cache/basseparate` | `--storage-root` |
| State | `~/.local/state/basseparate` | `--storage-root` |
| Runtime (locks) | `~/.local/state/basseparate/runtime` | `--storage-root` |

With `--storage-root /path`, all categories are placed under `/path/`.

## Tests

```sh
# All checks (format, lint, types, contracts, frontend):
uv run --locked python scripts/dev.py check

# Python + frontend unit tests:
uv run --locked python scripts/dev.py test

# Playwright browser tests (requires system deps):
uv run --locked python scripts/dev.py test-browser
```

## Diagnostics

```sh
uv run --locked basseparate version
uv run --locked basseparate doctor
uv run --locked basseparate worker-probe
```

## Development workflow

```sh
uv run --locked python scripts/dev.py dev
```

Starts the Vite dev server and the backend together. Stop both with Ctrl-C.

## Documentation

- [Main project plan](basseparate_project_plan.md)
- [Milestone 0 specification](projectPlans/milestone0.md)
- [Architecture notes](docs/architecture.md)
- [Troubleshooting guide](docs/troubleshooting.md)
- [Implementation status](docs/implementation-status.md)
- [Dependency notices](licenses/NOTICES.md)

## License

Private and unpublished. No public license is claimed. See
[licenses/NOTICES.md](licenses/NOTICES.md) for third-party component
notices. Milestone 0 bundles no model weights.
