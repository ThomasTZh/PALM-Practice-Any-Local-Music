# macOS app verification

- Cross-platform build on Linux: `python scripts/package_macos.py --online`
  produced `PALM-0.1.0-dev-macos-arm64.zip` (78,743,539 B, SHA-256
  `999b1343f0a6890749854a3ba46b37cd93cb582f4b8fa43a5a25478f68f798b9`,
  3,815 entries) with
  `PALM.app/Contents/MacOS/palm`, `Info.plist`, embedded arm64 Python, `bin/uv`,
  web UI, analysis workers/registry, cpu-macos/msst-macos definitions, licences
  and hashed runtime requirements. `package-macos-check` passed.
- Wrapper contract test: fake `Contents/Resources/app/bin/palm` receives
  `PALM_DATA_DIR=$HOME/Library/Application Support/palm` even when
  `XDG_DATA_HOME` is set; no XDG path is exported, and `--status` is passed
  through.
- The extracted `PALM.app` wrapper was exercised with the Linux portable payload
  substituted for the arm64 payload on this host: `--no-browser --no-terminal`
  started the server, `/api/health` returned ok, `--status` printed URL/data
  root/pids and `--stop` removed run/server.json.
- The macOS arm64 binaries cannot execute on this Linux host. Native launch,
  Terminal.app, health, status and stop are exercised by the `macos-package`
  GitHub Actions job on macos-14; no native execution is claimed here.
