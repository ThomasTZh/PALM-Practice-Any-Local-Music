# Milestone 0 — Reproducible foundation: detailed implementation specification

This expands Milestone 0 in Section 13 of the basseparate project plan. The rest of the project plan remains unchanged.

## 1\. Outcome, scope, and current environment

### 1\.1 Required outcome

At the end of Milestone 0, one command must:

1. Start basseparate on your PC.
2. Bind its service to the loopback interface.
3. Initialize its local working storage.
4. Open the browser.
5. Display a functioning application shell.
6. Show backend connection status.
7. Allow creation and reopening of an empty working project.
8. Shut down cleanly when stopped.

The application must start without CUDA, PyTorch, downloaded models, or an internet connection after dependencies and frontend assets have been installed.

An empty working project is a persisted project record. Portable `.basseparate` archive creation belongs to Milestone 2.

### 1\.2 Included work

- Repository and package layout.
- Isolated development environments.
- Dependency locks.
- Local backend and frontend.
- Launcher and development commands.
- Configuration and storage directories.
- Project and asset schemas.
- Database initialization and schema-version handling.
- Generated frontend API types.
- Loopback authentication and request protection.
- Worker protocol and a model-free worker test.
- Automated tests.
- Dependency/license inventory.
- Startup, shutdown, and troubleshooting documentation.

### 1\.3 Work scheduled for later milestones

- Importing or decoding audio.
- Waveform rendering.
- Playback and time stretching.
- Model installation or GPU inference.
- Actual separation or transcription.
- Job scheduling and GPU allocation.
- Musical timeline editing.
- Portable project archives.
- YouTube import.
- Export.
- Complete undo/redo.

Milestone 0 should not display invented analysis, placeholder waveforms, or progress bars that are not connected to real work.

### 1\.4 Observed workspace

The workspace currently contains:

- `basseparate_project_plan.md`.
- Five WAV files.
- `system-inventory.txt`.
- Empty, read-only `.git`, `.agents`, and `.codex` directories.

No application code or usable Git repository was found.

Installed tools observed:

| Tool | Observed state |
|---|---|
| Python | System Python 3.14.7 |
| Node | 22\.22.2 |
| uv | 0\.12.0 |
| FFmpeg/ffprobe | Available |
| Git | Available, but current directory is not a valid repository |
| pnpm | Not on PATH |
| CMake | Available |
| Emscripten | Not on PATH |

Use a separate Python 3.11 environment as established in the main plan. Do not replace system Python.

### 1\.5 Definition of the milestone boundary

Milestone 0 is complete when the foundation works and the tests below pass. It does not require resolving the previously observed NVIDIA-driver access problem.

A GPU diagnostic warning must not prevent a model-free application from starting.

***

## 2\. Work package M0.1 — Protect existing files and establish project structure

### 2\.1 Preserve the workspace

1. Read any applicable repository instructions.
2. Record the names and sizes of existing user files.
3. Calculate SHA-256 hashes of the five WAV files before implementation.
4. Store this baseline in a local, ignored verification report.
5. Leave the existing recordings at their current paths.
6. Leave `system-inventory.txt` unchanged.
7. Keep the main project plan as the top-level design reference.
8. Do not overwrite existing files when scaffolding.
9. At milestone completion, verify the original recordings still match their baseline hashes.

### 2\.2 Handle the Git placeholder

1. Check whether `.git` is a real repository.
2. If it becomes a usable existing repository, inspect its current changes before editing.
3. If it is writable but empty, initialize Git normally.
4. If it remains read-only, leave it untouched.
5. Continue creating application files in the writable workspace.
6. Use filesystem comparison for generated-artifact checks when Git is unavailable.
7. Record Git initialization as an environment limitation, not an application-runtime requirement.
8. Do not delete the placeholder or relocate the user’s workspace.

### 2\.3 Create the intended layout

```
basseparate/
├── basseparate_project_plan.md
├── README.md
├── CONTRIBUTING.md
├── .gitignore
├── .editorconfig
├── .python-version
├── .node-version
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── src/
│   └── basseparate/
│       ├── __init__.py
│       ├── cli.py
│       ├── app.py
│       ├── config.py
│       ├── diagnostics.py
│       ├── api/
│       ├── domain/
│       ├── storage/
│       ├── workers/
│       └── web/
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── src/
│   └── tests/
├── contracts/
│   ├── openapi.json
│   ├── project.schema.json
│   ├── asset.schema.json
│   └── worker.schema.json
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── milestone-0.md
│   ├── architecture.md
│   ├── development.md
│   ├── troubleshooting.md
│   └── decisions/
└── licenses/
    ├── components.json
    └── THIRD_PARTY_NOTICES.md
```

The directories describe ownership boundaries. Create implementation files when needed rather than populating every directory with empty abstractions.

### 2\.4 Configure ignored files

Exclude:

- Python virtual environments.
- `node_modules`.
- Frontend build output.
- Test coverage and browser reports.
- Temporary files.
- Local runtime storage.
- SQLite database, WAL, and SHM files.
- Model weights.
- Downloaded media.
- Generated stems.
- Local logs and diagnostic reports.
- The existing root-level WAV files.

Allow small, deliberately created test fixtures under `tests/fixtures`.

Do not use an ignore rule that prevents legitimate JSON schemas or documentation from being tracked.

### 2\.5 Record architecture decisions

Create concise decision records for:

1. Python backend and TypeScript frontend.
2. Local browser application with loopback service.
3. Single backend process in Milestone 0.
4. Separate future model workers.
5. SQLite working storage.
6. Python-owned contracts with generated TypeScript.
7. Source-sample-based timing.
8. No network activity during ordinary startup.

**Acceptance:** the structure is understandable, user recordings remain unchanged, and no generated or private assets are accidentally treated as source code.

***

## 3\. Work package M0.2 — Establish reproducible development environments

### 3\.1 Python environment

1. Check locally installed uv-managed Python versions.
2. Reuse an available Python 3.11 patch release if suitable.
3. Otherwise install a maintained Python 3.11 patch through uv.
4. Record the exact selected patch in `.python-version`.
5. Set the application’s initial Python requirement to `>=3.11,<3.12`.
6. Create a workspace-local virtual environment.
7. Use a standard `src` package layout.
8. Use Hatchling as the Python build backend.
9. Register a `basseparate` console entry point.
10. Generate `uv.lock`.
11. Verify installation with `uv sync --locked`.
12. Verify that a stale lockfile causes failure rather than an unnoticed update.

uv distinguishes locked installation from automatic lock updates; use the locked workflow for verification and repeatable setup. [uv locking and syncing](<https://docs.astral.sh/uv/concepts/projects/sync/>)

### 3\.2 Initial Python runtime dependencies

Install only what Milestone 0 uses:

- FastAPI.
- Uvicorn.
- Pydantic v2.
- pydantic-settings.
- platformdirs.

Use Python standard-library facilities for:

- CLI argument parsing.
- SQLite.
- Logging.
- JSON.
- Hashing.
- Process management.
- File locking on the initial Linux target.
- UUIDs and timestamps.

Do not install PyTorch, librosa, separation packages, or neural model weights in this milestone.

### 3\.3 Python development dependencies

Add:

- pytest.
- pytest-asyncio.
- pytest-cov.
- HTTPX for API tests.
- Ruff.
- mypy.

Configure:

1. Ruff linting.
2. Ruff formatting.
3. Strict typing for application modules.
4. Async test behavior explicitly.
5. Test markers for integration and browser-related checks.
6. Coverage reporting without an arbitrary percentage gate.

Use targeted tests for important behavior rather than tests that merely repeat field declarations.

### 3\.4 Frontend environment

1. Retain Node 22.22.2 as the initial local baseline.
2. Record it in `.node-version`.
3. Confirm the selected Vite release supports that Node version.
4. Install pnpm locally through the supported installation method.
5. Pin its exact version in the root `packageManager` field.
6. Configure the frontend as a pnpm workspace package.
7. Generate `pnpm-lock.yaml`.
8. Verify `pnpm install --frozen-lockfile`.
9. Avoid global replacement of the user’s Node installation.

Vite and pnpm document their runtime and installation requirements; verify the exact versions selected during setup against those sources. [Vite setup](<https://vite.dev/guide/>), [pnpm installation](<https://pnpm.io/installation>)

### 3\.5 Frontend dependencies

Runtime:

- React.
- React DOM.

Development:

- TypeScript.
- Vite and its React integration.
- ESLint.
- Prettier.
- Vitest.
- React Testing Library.
- jsdom.
- Playwright.
- openapi-typescript.
- openapi-fetch.

Use plain CSS with CSS variables for the shell. Introduce Zustand when shared editor state becomes necessary; it is not required for a connection indicator and project list.

### 3\.6 Pinning policy

1. Resolve current compatible releases during initial setup.
2. Store exact direct versions and full dependency locks.
3. Record the resulting toolchain in a version manifest.
4. Do not use floating Git branches.
5. Do not run package upgrades as part of application startup.
6. Update dependencies through a deliberate maintenance command.
7. Re-run relevant checks after changes.

Exact untested package versions should not be invented in the design document. The implementation’s lockfiles become the authoritative resolved versions.

### 3\.7 WebAssembly boundary

Record the planned Signalsmith/Emscripten integration in architecture documentation.

Actual compiler installation, WASM compilation, and time-stretcher integration begin in Milestone 2, when they can be tested against real playback requirements.

**Acceptance:** dependencies install from locks, system Python remains untouched, and the foundation imports without any ML package.

***

## 4\. Work package M0.3 — Configuration, paths, and diagnostics

### 4\.1 Configuration model

Define a typed `AppConfig` with:

| Setting | Initial default |
|---|---|
| Bind address | `127.0.0.1` |
| Port | `8765` |
| Open browser | Enabled |
| Offline mode | Enabled |
| Log level | `INFO` |
| Development mode | Disabled |
| Startup timeout | 15 seconds |
| Worker handshake timeout | 5 seconds |
| Worker graceful-stop timeout | 5 seconds |
| Database busy timeout | 5 seconds |

Keep localhost binding nonconfigurable to a LAN address in this milestone.

### 4\.2 Configuration precedence

Use:

1. Explicit CLI argument.
2. `BASSEPARATE_` environment variable.
3. User TOML configuration.
4. Built-in default.

Implementation steps:

1. Parse defaults.
2. Read the TOML file if present.
3. Apply environment variables.
4. Apply CLI options.
5. Validate the final configuration.
6. Produce a clear error for invalid values.
7. Log the effective configuration with secrets removed.
8. Keep authentication tokens outside the persisted configuration.

### 4\.3 Storage directories

Use platformdirs following Linux XDG conventions. These conventions distinguish configuration, data, cache, and state. [XDG Base Directory Specification](<https://specifications.freedesktop.org/basedir/latest/>)

Create:

| Category | Contents |
|---|---|
| Configuration | User settings |
| Data | Working database and future project assets |
| Cache | Rebuildable future analysis and waveform artifacts |
| State | Logs and last-run information |
| Runtime | Instance lock and temporary session metadata |

For tests and portable development, support:

`--storage-root /explicit/path`

That override places all categories beneath the selected directory.

### 4\.4 Directory handling

1. Resolve the configured storage root.
2. Create missing app-owned directories.
3. Use owner-only permissions for sensitive runtime files.
4. Verify required directories are writable.
5. Fail before opening the browser if essential storage is unavailable.
6. Keep data directories independent of the current working directory.
7. Never treat a user-selected path as a directory to clear recursively.
8. Remove only known temporary files created by the current operation.

### 4\.5 Diagnostic command

Implement:

`basseparate doctor`

Report:

- Application version.
- Python version and executable.
- Platform and CPU architecture.
- RAM.
- Storage locations and available disk space.
- FFmpeg/ffprobe presence.
- Node/pnpm presence for development.
- NVIDIA command availability.
- GPU information if the driver query succeeds.
- Frontend-build availability.
- Database accessibility.

Rules:

1. Do not import PyTorch.
2. Put timeouts on external commands.
3. Run executables with argument arrays, not shell interpolation.
4. Distinguish required and optional capabilities.
5. Return success when the core foundation can run.
6. Report missing GPU access as an optional warning.
7. Do not install software or change drivers.

**Acceptance:** diagnostics explain readiness without mutating the environment or requiring GPU access.

***

## 5\. Work package M0.4 — Domain schemas and versioning

### 5\.1 Schema ownership

Pydantic models are authoritative.

Generate:

- API OpenAPI.
- Project JSON Schema.
- Asset JSON Schema.
- Worker-protocol JSON Schema.
- TypeScript API types.

Pydantic supports generating JSON Schema from model definitions, allowing the backend and frontend to share a contract. [Pydantic JSON Schema](<https://docs.pydantic.dev/latest/concepts/json_schema/>)

### 5\.2 Shared primitive types

Define:

1. UUID identifiers serialized as strings.
2. UTC timestamps serialized in ISO 8601 form.
3. SHA-256 hashes as lowercase hexadecimal strings.
4. Nonnegative integer revisions.
5. Integer sample positions.
6. Half-open intervals: `[start_sample, end_sample)`.
7. Explicit schema and protocol version numbers.

For frontend-exposed sample positions:

- Reject nonintegers.
- Reject negative values where negative positions are not permitted.
- Bound values to JavaScript’s safe-integer range.
- Never use milliseconds as the authoritative stored timeline.

### 5\.3 Project schema

Define `ProjectRecord`:

| Field | Meaning |
|---|---|
| `schema_version` | Project schema version, initially 1 |
| `id` | Project UUID |
| `name` | User-visible project name |
| `created_at` | UTC creation time |
| `updated_at` | UTC last modification |
| `revision` | Initially 0 |
| `source_asset_id` | Null until import |
| `sample_rate` | Null until a source is assigned |
| `duration_samples` | Null until a source is assigned |
| `status` | `empty` or `ready` |

Validation:

1. Trim leading/trailing name whitespace.
2. Require 1–200 characters after trimming.
3. Preserve normal Unicode names.
4. Reject embedded control characters.
5. Do not convert the name into a filesystem path.
6. Require source timing fields to be present together.
7. Permit a persisted empty project.

Do not populate an empty project with an arbitrary 44.1 kHz sample rate.

### 5\.4 Asset schema

Define `AssetRecord`:

- UUID.
- Content hash.
- Role.
- Relative storage path.
- Media type.
- Byte count.
- Creation timestamp.
- Optional audio metadata:
  - Sample rate.
  - Channel count.
  - Sample count.
  - Sample format.

Initial roles:

- `source_original`.
- `source_pcm`.
- `stem`.
- `analysis_artifact`.
- `waveform_cache`.

Audio metadata is optional because original containers and non-audio artifacts do not share the same fields.

### 5\.5 Asset-path rules

1. Store internal asset locations relative to managed storage.
2. Reject absolute internal paths.
3. Reject `..` traversal.
4. Reject NUL bytes.
5. Resolve paths and verify containment before access.
6. Check symlinks when accessing existing paths.
7. Preserve original source locations only as provenance metadata.
8. Never serve an arbitrary absolute path supplied by the browser.

Actual import and asset-serving endpoints are deferred.

### 5\.6 Confidence schema

Carry forward the main plan’s confidence structure:

- Value or null.
- Score kind.
- Method identifier.
- Calibration flag.
- Alternatives.
- Review state.

Validate:

- Numeric normalized scores are within `[0,1]`.
- `unavailable` uses null.
- Unknown confidence is not represented as zero.
- Human review does not overwrite machine confidence.

Milestone 0 only defines and tests this contract.

### 5\.7 Version domains

Keep these versions separate:

| Version | Controls |
|---|---|
| Application version | Release identity |
| API version | HTTP contract |
| Database version | SQL schema |
| Project schema version | Serialized project structure |
| Worker protocol version | Process messages |

Start the application at `0.1.0-dev`, API at `/api/v1`, and the three schema/protocol versions at `1`.

### 5\.8 Forward-compatibility behavior

1. Detect a database or serialized project version newer than supported.
2. Refuse to write it.
3. Show a specific compatibility error.
4. Preserve the original file.
5. Do not silently drop unknown required fields.

**Acceptance:** valid empty projects and assets serialize predictably; malformed identifiers, paths, timing, and confidence values fail clearly.

***

## 6\. Work package M0.5 — SQLite storage foundation

### 6\.1 Database choice

Use Python’s built-in `sqlite3` with explicit SQL and a small repository layer.

Do not introduce an ORM or a separate database server.

### 6\.2 Initial database

Create one managed working database containing:

- `projects`.
- `assets`.
- `project_assets`.

`project_assets` associates assets with projects and gives each association a role. This permits future content-addressed reuse without requiring duplicated project records.

Portable per-project snapshots will be implemented later.

### 6\.3 Initialization sequence

1. Resolve the database location.
2. Open a connection.
3. Enable foreign keys.
4. Configure the busy timeout.
5. Enable WAL mode on supported local storage.
6. Use `synchronous=FULL` for the initial small metadata workload.
7. Read the database schema version.
8. Reject newer unsupported versions.
9. Apply required migrations.
10. Verify the resulting version.
11. Close the initialization connection.

SQLite provides application-controlled schema-version storage through `PRAGMA user_version`. [SQLite pragmas](<https://www.sqlite.org/pragma.html#pragma_user_version>)

### 6\.4 Migration behavior

1. Define ordered migration functions.
2. Start with migration `0 → 1`.
3. Run each migration transactionally.
4. Set the schema version only after successful SQL changes.
5. Roll back failed migrations.
6. Before modifying an existing nonempty database, create a consistent backup using SQLite’s backup API.
7. Retain the backup after failure.
8. Record migration outcome in the local log.
9. Never copy only the main SQLite file while ignoring active WAL state.

### 6\.5 Repository methods

Implement:

- `create_project(name)`.
- `get_project(project_id)`.
- `list_projects()`.
- `register_asset(asset)`.
- `attach_asset(project_id, asset_id, role)`.

Only the first three require user-facing API routes now. Asset operations are exercised through integration tests.

### 6\.6 Transaction and concurrency rules

1. Use parameterized SQL.
2. Keep write transactions short.
3. Create connections within the operation that uses them.
4. Do not share one connection across unrelated threads.
5. Run synchronous repository work outside the async event loop.
6. Return immutable domain records from the repository.
7. Let uniqueness and foreign-key constraints protect integrity.
8. Translate expected storage failures into application errors.

**Acceptance:** an empty project survives shutdown and restart; partial operations do not leave inconsistent records.

***

## 7\. Work package M0.6 — Backend lifecycle and HTTP API

### 7\.1 Application factory

Implement:

`create_app(config)`

It must:

1. Accept an explicit configuration.
2. Avoid filesystem mutations at module import.
3. Avoid starting background workers at module import.
4. Avoid opening a browser.
5. Avoid network requests.
6. Permit isolated test instances.

### 7\.2 Startup and shutdown lifecycle

Use FastAPI’s lifespan mechanism for resource initialization and cleanup. [FastAPI lifespan](<https://fastapi.tiangolo.com/advanced/events/>)

Startup:

1. Validate configuration.
2. Initialize storage.
3. Initialize/migrate the database.
4. Load application/build metadata.
5. Create the session token.
6. Mark the service ready.

Shutdown:

1. Mark readiness false.
2. Stop accepting new operations.
3. Complete or roll back active short transactions.
4. Stop any app-owned test/probe worker.
5. Close resources.
6. Flush logs.

### 7\.3 Milestone 0 routes

| Route | Behavior |
|---|---|
| `GET /api/v1/health` | Minimal unauthenticated liveness/readiness |
| `GET /api/v1/system` | Authenticated version and basic runtime status |
| `GET /api/v1/projects` | List working projects |
| `POST /api/v1/projects` | Create an empty working project |
| `GET /api/v1/projects/{id}` | Retrieve project |
| `GET /api/v1/modules` | Empty installed-module list |
| `GET /api/v1/models` | Empty installed-model list |

The empty lists must mean “none installed,” not failed discovery.

Do not add nonfunctional import, playback, or analysis endpoints.

### 7\.4 Health response

Example:

```
{
  "status": "ready",
  "api_version": 1
}
```

Rules:

- Return `200` when ready.
- Return `503` when not ready.
- Include no paths, tokens, process environment, or GPU details.

### 7\.5 Project creation

Request:

```
{
  "name": "Untitled project"
}
```

Response:

- HTTP `201`.
- Full `ProjectRecord`.
- Server-generated ID and timestamps.
- Null source/timing fields.
- Revision `0`.

Use an `Idempotency-Key` for creation requests:

1. Store the key and request identity transactionally.
2. Return the same project for a retry of the same request.
3. Reject key reuse with a different body using HTTP `409`.

### 7\.6 Error envelope

Use a consistent response:

```
{
  "error": {
    "code": "PROJECT_NOT_FOUND",
    "message": "The requested project does not exist.",
    "request_id": "uuid",
    "details": {}
  }
}
```

Map:

- Invalid input → `422`.
- Missing project → `404`.
- Invalid authentication → `401`.
- Disallowed origin/host → `403`.
- Idempotency conflict → `409`.
- Temporary storage contention → `503`.
- Unexpected failure → `500`.

Do not return tracebacks to the browser.

### 7\.7 Request tracing

1. Generate a request ID.
2. Return it in a response header.
3. Include it in error responses.
4. Include it in server logs.
5. Keep logging local.
6. Avoid logging request bodies and authorization headers.

**Acceptance:** the API is usable by the generated client and returns predictable errors.

***

## 8\. Work package M0.7 — Loopback access and browser authentication

### 8\.1 Bind behavior

1. Bind to `127.0.0.1`.
2. Use port `8765` by default.
3. Permit an explicit different port.
4. If the port is occupied, report the conflict.
5. Do not select a random replacement silently.
6. Do not bind to `0.0.0.0`.

### 8\.2 Session authentication

Use a random bearer token generated at application startup.

Bootstrap:

1. Generate at least 256 bits of randomness.
2. Open the browser at a URL containing the token in its fragment.
3. Read the fragment in the frontend.
4. Remove it immediately with `history.replaceState`.
5. Store the token in `sessionStorage`.
6. Send it in the `Authorization` header for API calls.
7. Never place it in request query parameters.
8. Never store it in project files.
9. Rotate it on backend restart.

URL fragments are not sent as part of the HTTP request. The frontend must still clear the fragment promptly and avoid logging it.

### 8\.3 Reload and reconnect behavior

1. Reuse sessionStorage after a tab reload.
2. Display a reconnecting state during a temporary connection failure.
3. On `401`, stop automatic protected retries.
4. Show that the local session has expired.
5. Instruct the user to reopen the application through the launcher.
6. Do not repeatedly launch browser windows automatically.

### 8\.4 Request protection

1. Allow only expected Host values.
2. Reject hostile Origin values.
3. In production, allow only the served application origin.
4. Require bearer authentication for all protected routes.
5. Permit token-authenticated CLI requests without an Origin header.
6. Do not use permissive wildcard CORS.
7. Do not rely on loopback binding alone.
8. Rate-limit failed authentication attempts conservatively.
9. Keep the minimal health route unauthenticated.

Because authentication uses an explicit authorization header rather than ambient cookies, cross-site requests cannot authenticate merely by causing a browser request.

### 8\.5 Static application headers

Production frontend responses include:

- Content Security Policy restricted to local application resources.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: no-referrer`.
- `Cross-Origin-Opener-Policy: same-origin`.
- `Cross-Origin-Embedder-Policy: require-corp`.

Development may need limited, documented exceptions for Vite’s local development connection. Those exceptions must not enter production configuration.

### 8\.6 Security tests

Test:

1. Valid token succeeds.
2. Missing token fails.
3. Incorrect token fails.
4. Old token fails after restart.
5. Hostile Origin fails.
6. Unexpected Host fails.
7. Health reveals no sensitive information.
8. Authorization headers never appear in logs.
9. Static routes cannot expose source audio or the working database.

**Acceptance:** a browser tab can use the local app, while an unrelated website cannot operate its protected API.

***

## 9\. Work package M0.8 — Browser shell and generated client

### 9\.1 Build the shell

Create:

- Header with application name.
- Backend connection indicator.
- Working-project list.
- New-project button.
- Empty-project view.
- Small local runtime-status panel.
- Accessible error notifications.

Do not include enabled import or analysis controls before those functions exist.

### 9\.2 User-facing states

Implement distinct states:

1. Connecting.
2. Connected with no projects.
3. Connected with existing projects.
4. Creating project.
5. Empty project open.
6. Backend unavailable.
7. Session expired.
8. API error.

A database or authentication error must not appear as an empty project list.

### 9\.3 New-project workflow

1. Click “New project.”
2. Enter a project name.
3. Validate the name locally for immediate feedback.
4. Submit using the generated client.
5. Disable duplicate submission while pending.
6. Retain the name if the request fails.
7. Navigate to the created project.
8. Display “No audio imported yet.”
9. Add the project to the list.
10. Verify it remains available after reload.

### 9\.4 Client generation

1. Export OpenAPI from the application factory without starting the server.
2. Generate TypeScript API definitions using openapi-typescript.
3. Use openapi-fetch for requests.
4. Add authorization through a common client wrapper.
5. Parse the standard error envelope centrally.
6. Keep components free from hand-built endpoint URLs.
7. Keep generated files clearly marked.
8. Never edit generated types manually.

### 9\.5 Contract-drift check

1. Generate schemas into a temporary directory.
2. Compare them with checked-in generated artifacts.
3. Fail the check if they differ.
4. Print the regeneration command.
5. Make comparisons deterministic by excluding timestamps and sorting stable JSON output.
6. Support this check without requiring Git.

### 9\.6 Frontend behavior standards

1. Use semantic HTML.
2. Give every field a visible label.
3. Support keyboard-only navigation.
4. Keep focus visible.
5. Restore focus after closing dialogs.
6. Use text alongside connection-status colors.
7. Show understandable error messages.
8. Keep fonts and icons local.
9. Make the empty state usable at common desktop widths.

### 9\.7 Serving strategy

Production:

- Build static frontend assets.
- Include them in the application package.
- Serve frontend and API from the backend origin.

Development:

- Run Vite on loopback.
- Proxy `/api` to the backend.
- Restrict the backend to the exact configured development origin.
- Do not expose Vite on the LAN.

**Acceptance:** the real browser shell creates and reopens a persisted empty project using generated API types.

***

## 10\. Work package M0.9 — Worker protocol and model-free probe

### 10\.1 Purpose

Validate the future subprocess boundary without implementing analysis scheduling or loading any model.

### 10\.2 Transport

Use newline-delimited JSON:

- Parent sends requests through worker stdin.
- Worker sends protocol messages through stdout.
- Worker sends logs through stderr.

Do not use pickle, shared Python objects, or large inline binary arrays.

### 10\.3 Message envelope

Define:

```
{
  "protocol_version": 1,
  "message_id": "uuid",
  "request_id": "uuid-or-null",
  "type": "hello",
  "payload": {}
}
```

Use a discriminated union for message types.

Initial messages:

| Direction | Type | Purpose |
|---|---|---|
| Worker → parent | `hello` | Protocol/version identification |
| Parent → worker | `describe` | Ask for capabilities |
| Worker → parent | `capabilities` | Return module description |
| Parent → worker | `ping` | Check responsiveness |
| Worker → parent | `pong` | Confirm responsiveness |
| Parent → worker | `shutdown` | Request clean exit |
| Worker → parent | `stopped` | Confirm shutdown |
| Worker → parent | `error` | Structured failure |

Reserve analysis execution and cancellation messages for the milestone implementing real jobs.

### 10\.4 Probe worker

Implement a built-in probe worker that:

1. Emits `hello`.
2. Reports a model-free diagnostic capability.
3. Responds to `ping`.
4. Validates incoming message versions.
5. Rejects unknown message types.
6. Writes logs only to stderr.
7. Stops on shutdown or stdin EOF.

Do not list this worker as an available music-analysis module in the user interface.

### 10\.5 Parent supervisor

1. Spawn the probe with `sys.executable`.
2. Use an argument array.
3. Set an explicit working directory.
4. Wait up to five seconds for handshake.
5. Read stdout and stderr concurrently.
6. Validate each message.
7. Limit individual message size to 1 MiB.
8. Handle malformed JSON.
9. Detect unexpected process exit.
10. Request graceful shutdown.
11. Terminate only the app-owned child after timeout.
12. Reap the child process.

### 10\.6 Probe tests

Test:

- Successful handshake.
- Ping/pong.
- Version mismatch.
- Invalid JSON.
- Oversized message.
- Missing handshake.
- Worker exception.
- Unexpected exit.
- Stderr output without protocol corruption.
- Graceful shutdown.
- Timeout cleanup.
- No leftover child process.

**Acceptance:** the process boundary works independently of any model or GPU.

***

## 11\. Work package M0.10 — Launcher and lifecycle commands

### 11\.1 User commands

Implement:

```
basseparate serve
basseparate serve --no-browser
basseparate serve --port 8766
basseparate serve --storage-root /explicit/path
basseparate doctor
basseparate version
basseparate worker-probe
```

### 11\.2 Normal launch sequence

1. Parse CLI arguments.
2. Load configuration.
3. Verify static frontend assets exist.
4. Acquire a lock for the selected storage root.
5. Bind the configured loopback socket.
6. Initialize backend resources.
7. Wait for readiness.
8. Open one browser tab with the bootstrap fragment.
9. Print a concise ready message without the token.
10. Continue serving until stopped.

For `--no-browser`, print the bootstrap URL only as an explicit user-facing output, not to persistent logs.

### 11\.3 Instance handling

1. Use an OS-backed advisory lock on Linux.
2. Let the OS release it after a crash.
3. Prevent two application instances from owning the same storage root.
4. If the lock is held, report that basseparate is already running.
5. Permit separate instances with separate storage roots and ports.
6. Do not kill a process merely because it occupies the preferred port.

### 11\.4 Browser-launch failure

1. Keep the backend running.
2. Report that automatic opening failed.
3. Provide the local bootstrap URL explicitly.
4. Do not repeatedly retry opening.
5. Do not treat this as database or backend failure.

### 11\.5 Shutdown sequence

On SIGINT or SIGTERM:

1. Stop accepting new work.
2. Complete/roll back active short operations.
3. Stop owned workers.
4. Close database connections.
5. Flush logs.
6. Remove app-owned ephemeral runtime files.
7. Release the instance lock.
8. Exit successfully.

On a forced crash, the next launch must rely on database transaction recovery rather than an assumption that the previous shutdown finished.

### 11\.6 Development command wrapper

Provide a small Python script exposing:

```
dev.py setup
dev.py dev
dev.py build
dev.py check
dev.py test
dev.py test-browser
dev.py contracts
dev.py contracts --check
dev.py licenses
```

Responsibilities:

- `setup`: install locked dependencies; this is the explicitly network-capable setup operation.
- `dev`: start backend and Vite, stop both together.
- `build`: build frontend and Python distribution.
- `check`: run nonmutating formatting, lint, typing, and contract checks.
- `test`: run Python and frontend unit/integration tests.
- `test-browser`: run Playwright tests.
- `contracts`: regenerate artifacts deliberately.
- `licenses`: regenerate dependency inventory.

Normal `serve` never runs dependency installation.

**Acceptance:** startup and shutdown are repeatable, with no orphan workers or unintended process termination.

***

## 12\. Work package M0.11 — Logging, licenses, and documentation

### 12\.1 Logging

1. Use Python standard logging.
2. Write readable console output.
3. Write structured local file logs.
4. Include timestamp, severity, component, and request ID.
5. Rotate logs at approximately 5 MiB.
6. Retain five rotated files.
7. Redact tokens and authorization headers.
8. Avoid recording user media contents or request bodies.
9. Log detailed internal failures locally.
10. Return only safe summaries to the browser.

### 12\.2 Dependency inventory

Generate `licenses/components.json` from the installed locked environment.

For each component record:

- Name.
- Version.
- Ecosystem.
- Direct or transitive dependency.
- Source/homepage.
- Declared license expression.
- Bundled notice location.
- Runtime or development-only role.
- Verification status.

### 12\.3 License handling

1. Record runtime and development dependencies separately.
2. Preserve upstream notices.
3. Mark missing/ambiguous metadata as unresolved.
4. Inspect unresolved licenses for bundled runtime components.
5. Generate a human-readable notices file.
6. Avoid claiming that a wrapper’s license covers future model weights.
7. Record that Milestone 0 bundles no model weights.
8. Do not choose a public license for the user’s own application without a separate publication decision.
9. Mark the project private/unpublished in package metadata.

### 12\.4 README

Document:

1. What Milestone 0 currently does.
2. What is not implemented yet.
3. Supported initial OS.
4. Python/Node requirements.
5. Setup command.
6. Build command.
7. Start command.
8. Shutdown procedure.
9. Storage locations.
10. Test commands.
11. Link to the main plan.
12. Link to the detailed milestone document.

### 12\.5 Troubleshooting guide

Include:

- Port already in use.
- Read-only storage directory.
- Missing frontend build.
- Unsupported Python version.
- Missing pnpm.
- Locked dependency mismatch.
- Browser fails to open.
- Session expires after backend restart.
- Database schema newer than supported.
- GPU unavailable but foundation still usable.
- Playwright browser dependencies unavailable on Nobara.
- Git placeholder prevents repository initialization.

**Acceptance:** a fresh developer can install, start, test, and diagnose the foundation using the documentation.

***

## 13\. Work package M0.12 — Verification matrix

### 13\.1 Backend unit tests

| Area | Required scenarios |
|---|---|
| Configuration | Defaults, precedence, invalid port, invalid storage path |
| Project model | Empty project, Unicode name, blank/oversized name |
| Timing | Integer positions, invalid ranges, safe-integer limits |
| Assets | Valid relative path, traversal, absolute path, malformed hash |
| Confidence | Valid score, unavailable/null, out-of-range score |
| Errors | Consistent envelope and request ID |
| Versioning | Current version, newer unsupported version |

### 13\.2 Storage integration tests

1. Initialize a fresh database.
2. Initialize the same database again without duplicating schema.
3. Create a project.
4. Close/reopen and retrieve it.
5. Attach a valid test asset.
6. Reject references to missing objects.
7. Roll back a failed transaction.
8. Apply the initial migration.
9. Preserve the original after a failed migration.
10. Reject a newer database version without writing.
11. Handle a temporarily locked database.
12. Keep separate test roots isolated.

### 13\.3 HTTP integration tests

1. Health succeeds without authentication.
2. Protected endpoints require authentication.
3. Project creation returns `201`.
4. Invalid creation returns `422`.
5. Missing project returns `404`.
6. Retry with the same idempotency key returns the same project.
7. Conflicting key reuse returns `409`.
8. Invalid Origin/Host is rejected.
9. Internal exceptions do not leak tracebacks.
10. API responses match generated contracts.

### 13\.4 Frontend tests

1. Connecting state.
2. Empty project list.
3. Existing project list.
4. Successful project creation.
5. Validation feedback.
6. Failed request preserves entered name.
7. Session expiration.
8. Backend disconnection.
9. Keyboard navigation.
10. Error versus empty-state distinction.

### 13\.5 Browser end-to-end tests

Use Playwright against a real local backend and temporary storage.

1. Launch app.
2. Complete session bootstrap.
3. Confirm token disappears from the address bar.
4. Create project.
5. Open project.
6. Reload page.
7. Confirm project persists.
8. Restart backend.
9. Confirm previous token is rejected.
10. Bootstrap a new session.
11. Confirm project still exists.
12. Stop application and confirm port release.

Run Chromium and Firefox. Add WebKit coverage when its system dependencies work in the test environment; keep actual Safari validation in Milestone 8. Playwright documents its browser installation and supported test setup. [Playwright installation](<https://playwright.dev/docs/intro>)

### 13\.6 Offline-start test

After installing dependencies and building assets:

1. Launch with network access restricted to loopback.
2. Open the application.
3. Create and reopen an empty project.
4. Run the worker probe.
5. Observe browser and backend requests.
6. Fail on any external runtime request.
7. Confirm missing models do not trigger downloads.

### 13\.7 Lifecycle and process tests

1. Normal startup.
2. Normal shutdown.
3. Startup timeout.
4. Port conflict.
5. Second instance using the same storage.
6. Independent second instance using another storage root.
7. Worker handshake timeout.
8. Worker cleanup after failure.
9. Abrupt termination followed by restart.
10. Browser-launch failure with backend remaining usable.

### 13\.8 Package smoke test

1. Build frontend assets.
2. Build the Python wheel.
3. Install it in a clean temporary Python 3.11 environment.
4. Start outside the source directory.
5. Confirm static assets are included.
6. Create a project.
7. Restart and reopen.
8. Run without Node or pnpm on runtime PATH.
9. Verify no model package is needed.

***

## 14\. Implementation order and acceptance gates

Execute in this order:

| Gate | Work packages | Required evidence |
|---|---|---|
| A | M0.1–M0.2 | Preserved recordings, working package environments and locks |
| B | M0.3–M0.5 | Valid configuration, contracts, persistent database |
| C | M0.6–M0.7 | Working authenticated loopback API |
| D | M0.8 | Browser creates and reopens a real empty project |
| E | M0.9–M0.10 | Worker protocol, reliable launcher and cleanup |
| F | M0.11–M0.12 | Documentation, licenses, passing checks and package smoke test |

Do not move a gate to “passed” based only on mocked behavior when the table requires an integrated workflow.

### Final verification commands

The completed developer wrapper must support running:

```
uv run --locked python scripts/dev.py check
uv run --locked python scripts/dev.py test
uv run --locked python scripts/dev.py build
uv run --locked python scripts/dev.py test-browser
uv run --locked basseparate worker-probe
uv run --locked basseparate doctor
uv run --locked basseparate serve
```

The `check` command must inspect formatting rather than rewrite files.

### Milestone completion checklist

- [ ] Existing WAV files are unchanged.
- [ ] Main project plan is preserved.
- [ ] Python 3.11 environment is isolated.
- [ ] Exact dependency locks exist.
- [ ] Fresh locked installation succeeds.
- [ ] Application starts without ML dependencies.
- [ ] Frontend assets are served locally.
- [ ] Backend listens only on loopback.
- [ ] Protected routes require a session token.
- [ ] Browser bootstrap clears the URL fragment.
- [ ] Empty projects persist across restarts.
- [ ] Schema versions are explicit.
- [ ] Unsupported newer schemas are not modified.
- [ ] Generated TypeScript matches backend contracts.
- [ ] Model-free worker probe passes.
- [ ] Shutdown leaves no owned child processes.
- [ ] Ordinary startup performs no external requests.
- [ ] Logs exclude secrets.
- [ ] License inventory covers installed components.
- [ ] Clean-package smoke test passes.
- [ ] Chromium and Firefox end-to-end tests pass.
- [ ] Any environment-limited checks are documented accurately.
- [ ] README and troubleshooting instructions match the implemented commands.

### Handoff to Milestone 1

Deliver:

1. Working source and locked environments.
2. Browser shell and local API.
3. Database migrations and repository layer.
4. Project, asset, confidence, and worker schemas.
5. Generated frontend types.
6. Launcher and diagnostic commands.
7. Test fixtures and acceptance results.
8. Dependency/license inventory.
9. A short implementation report identifying any environment limitations.
10. A clean interface for adding audio import, PCM assets, and waveform generation.