# Windows x64 portable ZIP

`scripts/package_windows.py` builds the unsigned Windows x64 beta archive from
the pinned standalone CPython 3.11.15 and uv 0.12.0 archives in
`build-manifest.toml`. Run it on Windows for a native build:

```powershell
pnpm install
pnpm build
python -m pip install uv==0.12.0
python scripts/package_windows.py --online
python scripts/package_windows.py --check
```

The ZIP contains `palm.cmd`, `python\python.exe`, `bin\uv.exe`, the built web
UI, analysis workers/registry and Windows env definitions, scripts, licences
and the hashed runtime requirements. It intentionally contains no FFmpeg,
Sonic Annotator, Vamp plugins, models, inference environments or development
sources. No administrator rights are needed: extract the ZIP under the user's
profile and double-click `palm.cmd`; the console shows logs and Ctrl+C stops it.
`palm.cmd --status` and `palm.cmd --stop` use the normal launcher state under
`%LOCALAPPDATA%\palm`.

Windows CI runs the build, package checks, unit/adapter tests and a no-admin
ZIP smoke that starts `palm.cmd`, requests `/api/health`, and stops it. The
cross-platform build and Wine smoke are recorded in `VERIFICATION.md`. The
archive is unsigned; SmartScreen may ask for confirmation. No signing or
native installer is produced here.
