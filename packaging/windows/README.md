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

The output contains both `PALM-<version>-windows-x86_64-installer.exe` (Inno
Setup, per-user lowest privileges) and the portable ZIP. Both use the same
staged payload: `PALM.exe`, `python\python.exe`, `bin\uv.exe`, built web UI,
analysis workers/registry and Windows env definitions, scripts, licences,
`install.json` and hashed runtime requirements. No FFmpeg, Sonic Annotator,
Vamp plugins, models, inference environments or development sources are
bundled.

The installer places PALM under `%LOCALAPPDATA%\Programs\PALM`, creates
per-user Start Menu/desktop shortcuts and an uninstall entry, and launches the
app optionally after install. `PALM.exe` is a GUI-subsystem launcher built from
`palm_launcher.c`; it starts `pythonw.exe --window` with no console. The
uninstaller asks app-only (default, preserves `%LOCALAPPDATA%\palm`) or also
delete the data root; silent/scripted uninstall never deletes data. The ZIP is
portable: extract and double-click `PALM.exe`. `palm.cmd` is the diagnostic
console fallback only.

Windows CI builds PALM.exe from source, compiles the installer with ISCC.exe,
runs package checks, native install/upgrade/uninstall tests and a PALM.exe
health smoke. Nothing is code-signed or notarized; SmartScreen may ask for
confirmation.

First launch opens the licence/setup screen. Managed FFmpeg/FFprobe, Sonic
Annotator, the Vamp Plugin Pack, the CPU environment and selected models are
downloaded only after consent and verified under `%LOCALAPPDATA%\palm`.
Windows Vamp setup may show one UAC prompt; the app itself needs no
administrator rights. Check for updates only opens the release page; there is no
automatic updater.
