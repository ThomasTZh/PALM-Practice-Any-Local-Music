# basseparate

Local music-analysis and bass practice application.

Milestone 0 (current): reproducible foundation — loopback service, browser
shell, persistent empty projects, worker protocol probe. No audio import, no
models, no analysis yet. See `projectPlans/milestone0.md` for the detailed
specification and `basseparate_project_plan.md` for the full plan.

## Requirements

- Python 3.11 (managed by uv; system Python is not used or modified)
- Node 22.22.2 + pnpm (frontend build and tests only)
- FFmpeg/ffprobe (available from system packages)
- Linux (initial target: Nobara)

## Setup (network-capable, deliberate)

```sh
uv run --locked python scripts/dev.py setup
```

## Build

```sh
uv run --locked python scripts/dev.py build
```

## Run

```sh
uv run --locked basseparate serve
```

Stop with Ctrl-C. The service binds `127.0.0.1:8765` and opens one browser tab.

## Tests

```sh
uv run --locked python scripts/dev.py check
uv run --locked python scripts/dev.py test
uv run --locked python scripts/dev.py test-browser
```

## Storage

Application data lives in the platform-standard user directories
(`~/.config/basseparate`, `~/.local/share/basseparate`,
`~/.cache/basseparate`, `~/.local/state/basseparate`), overridable with
`basseparate serve --storage-root /explicit/path`.

## Diagnostics

```sh
uv run --locked basseparate doctor
uv run --locked basseparate version
uv run --locked basseparate worker-probe
```

See `docs/development.md` for the development workflow and
`docs/troubleshooting.md` for common failures.
