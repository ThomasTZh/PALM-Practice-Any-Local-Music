# Windows ZIP verification

Built cross-platform on Linux with:

```text
python scripts/package_windows.py --online
python scripts/package_windows.py --check
```

- `PALM-0.1.0-dev-windows-x86_64.zip`
- 79,338,033 bytes
- SHA-256 `e07a217e4bb2e41e4d1d511b4a0b2fd01d39f99d1c198e22461ce10d83203799`
- 4,977 entries; `package-windows-check` required content present.

The archive contains `palm.cmd`, `python\python.exe`, `bin\uv.exe`, the built
web UI, analysis workers/registry, `analysis/envs/cpu-windows` and
`msst-windows`, scripts, licences and hashed runtime requirements. It contains
no FFmpeg, Sonic Annotator, Vamp plugins, model weights, inference environments
or test/audio trees.

Wine 11.21 smoke on the extracted ZIP:

- `wine cmd /c palm.cmd --help` exited 0 and printed the launcher options.
- `palm.cmd --no-browser --no-terminal --port 0 --data-dir Z:\...`
  started the packaged server; `/api/health` returned
  `{"status":"ok","version":"0.1.0-dev",...}`.
- `palm.cmd --status` printed the URL/data root/pids and exited 0.
- `palm.cmd --stop` stopped the launcher/server, removed
  `run/server.json`, and exited 0.

The native GitHub Actions `windows-package` job repeats the build, checks,
unit/adapter tests and a no-admin ZIP smoke on `windows-2022`. No signing,
installer or administrator action is part of this package.
