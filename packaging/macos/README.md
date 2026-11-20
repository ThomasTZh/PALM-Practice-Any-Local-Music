# macOS Apple Silicon experimental app

`scripts/package_macos.py` builds the unsigned `PALM.app` from pinned standalone
CPython 3.11.15 arm64 and uv 0.12.0 archives. Build on macOS for a native app,
or on POSIX for cross-installed arm64 wheels:

```sh
pnpm install
pnpm build
python -m pip install uv==0.12.0
python scripts/package_macos.py --online
python scripts/package_macos.py --check
python scripts/package_macos.py --online --dmg   # macOS only: hdiutil
```

The DMG is a conventional drag-to-Applications disk image: it contains
`PALM.app` and an `Applications` symlink. Drag the app onto the link, then
eject the disk image. The ZIP contains the same `PALM.app` with `Contents/MacOS/palm`, `Info.plist`,
`Contents/Resources/app` (embedded Python, `bin/palm`, `bin/uv`, web UI,
analysis workers/registry, `cpu-macos`/`msst-macos` definitions, scripts and
licences), and the hashed runtime requirements. It contains no FFmpeg, Sonic
Annotator, Vamp plugins, models, inference environments or test/audio sources.
No signing, notarization, `.pkg` installer or notarization claim is part of
this build.

## First launch

The app is unsigned. Right-click `PALM.app` and choose **Open**, then confirm
**Open** in the dialog. If macOS blocks it, remove the quarantine attribute
from the app bundle you extracted:

```sh
xattr -dr com.apple.quarantine /Applications/PALM.app
open /Applications/PALM.app
```

To remove PALM, quit it and move `PALM.app` to the Trash; projects, models and
tools remain in `~/Library/Application Support/palm` unless you delete that
data root separately. Do not claim the app is signed or notarized. The wrapper sets
`PALM_DATA_DIR="$HOME/Library/Application Support/palm"` unless it is already
set, so data stays in the native macOS root rather than the XDG
`~/.local/share/palm` path. Finder starts the app without a tty; the launcher opens the PALM control
window and browser, with no Terminal.app window. `--status` and `--stop` pass
through the wrapper for recovery only.

No FFmpeg, Sonic Annotator, Vamp plugin pack, model weights, inference
environments or test audio are bundled. The setup wizard downloads what the
user selects later.
