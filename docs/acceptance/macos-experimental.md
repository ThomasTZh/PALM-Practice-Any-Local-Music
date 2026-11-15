# macOS Apple Silicon one-shot acceptance kit

Status: **NOT RUN**. This is a one-shot kit for a friend's Apple Silicon Mac.
It does not claim macOS acceptance until the run is complete and the evidence
listed below is supplied. Do not edit the app, install developer tools, or try
to fix code on the Mac. The Mac is a test client; fixes belong in the Linux/CI
tree and will be re-tested there.

Target time: **45 to 60 minutes**. Stop at 60 minutes, keep the evidence and
report the blocker rather than extending the session.

## Artifact and prerequisites

Use the arm64 experimental asset:

`PALM-0.1.0-dev-macos-arm64.zip` (or the matching `.dmg` if supplied)

Record the exact filename, byte size and SHA-256. The app is unsigned and not
notarized. The Mac needs:

- Apple Silicon (arm64), macOS 11 or newer;
- a user account that can write `~/Applications` and `~/Library`;
- a network connection for the setup downloads;
- Safari and Google Chrome installed;
- FFmpeg and FFprobe available. If they are not on PATH, use a trusted
  portable build and set both overrides in the terminal that launches PALM:

```sh
export PALM_FFMPEG="$HOME/Downloads/ffmpeg/bin/ffmpeg"
export PALM_FFPROBE="$HOME/Downloads/ffmpeg/bin/ffprobe"
"$PALM_FFMPEG" -version
"$PALM_FFPROBE" -version
```

No administrator password is required for the app or its data. Do not install
a system service or a system-wide package.

## 0. Host record (5 minutes)

Run in Terminal and save as `evidence/01-host.txt`:

```sh
set -eu
sw_vers
uname -m
system_profiler SPHardwareDataType
sysctl -n machdep.cpu.brand_string 2>/dev/null || true
defaults read /Applications/Safari.app/Contents/Info.plist CFBundleShortVersionString
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version
sw_vers -productVersion
```

Record macOS version/build, chip model, memory, Safari version, Chrome version,
whether FFmpeg/FFprobe were found, and the ZIP SHA-256:

```sh
shasum -a 256 "$HOME/Downloads/PALM-0.1.0-dev-macos-arm64.zip"
```

## 1. Unsigned launch (10 minutes)

Extract to the user's Applications folder. Do not use `sudo`:

```sh
mkdir -p "$HOME/Applications"
cd "$HOME/Downloads"
unzip -q PALM-0.1.0-dev-macos-arm64.zip -d "$HOME/Applications"
xattr -dr com.apple.quarantine "$HOME/Applications/PALM.app"
open "$HOME/Applications/PALM.app"
```

If Finder blocks the app: right-click `PALM.app`, choose **Open**, then confirm
**Open**. If it still refuses, run the `xattr` command above and try again.
The app should open a Terminal window with logs and then the browser at a
loopback URL. Keep Terminal open.

Record whether Gatekeeper required right-click Open, whether the quarantine
command was needed, and whether a UAC/admin prompt appeared (expected: none).
Take a screenshot of the Terminal and browser as `evidence/02-launch.png`.

## 2. Setup, CPU only (10 minutes)

In the setup wizard:

1. Confirm the system checks. FFmpeg/FFprobe must resolve to the path shown
   above, and the disk check must pass.
2. Install the analysis tools if offered. On macOS this is Sonic Annotator and
   the Vamp plugin pack. Do not grant admin or install system-wide; if the
   tool installer asks for elevation, stop and record the exact message.
3. Select **CPU**, never CUDA. Record the estimated download size.
4. Install exactly one model card. Record model id, size and licence shown.
5. Wait for setup complete. Do not skip a failed step.

Save setup screenshots in `evidence/03-setup/` and copy the setup section of
Terminal output. Expected data root:
`$HOME/Library/Application Support/palm`.

## 3. CPU analysis (10 minutes)

Import a short local recording you own, ideally 5 to 30 seconds. Click Analyse.
Record:

- import and duration;
- key and BPM;
- chord ribbon entries;
- bar/beat grid;
- no `PiperUnavailable`, missing-tool or missing-FFmpeg error.

Save `evidence/04-analysis.png` and the relevant
`~/Library/Application Support/palm/logs/server.log` tail.

## 4. Short separation (10 minutes)

With the installed model selected, separate the same short recording. Record:

- selected model id;
- progress stages;
- completion and elapsed wall time;
- expected stem lanes (drums/bass/other/vocals, plus guitar/piano if the model
  provides them);
- at least one stem playing.

Save `evidence/05-separation.png` and the server log tail. If it fails, record
the exact error, model id, recording duration and whether the app stayed
responsive.

## 5. Safari and Chrome playback (10 minutes)

Run the same checks in Safari and Google Chrome. Record for each:

- page loads at the loopback URL and the library is usable;
- Play starts and the position advances;
- speed 0.5x and 1.5x work while pitch remains usable;
- metronome and count-in are audible;
- a selected section loops;
- closing only the browser tab does not stop the Terminal/server.

Take one screenshot per browser in `evidence/06-browser/` and state whether
audio was actually audible. A moving position alone is not proof of audio.

## 6. Status, Ctrl+C and stop (5 minutes)

In a new Terminal window, query the running app. Use the wrapper path, not a
new app launch:

```sh
"$HOME/Applications/PALM.app/Contents/MacOS/palm" --status
```

Expected: exit 0, URL, data root `.../Library/Application Support/palm`, and
server/launcher pids. Save as `evidence/07-status.txt`.

Return to the PALM Terminal and press **Ctrl+C**. Expected: launcher exits, the
URL stops responding, and `run/server.json` is gone. Verify:

```sh
test ! -f "$HOME/Library/Application Support/palm/run/server.json" && echo stopped
```

If the server remains, run:

```sh
"$HOME/Applications/PALM.app/Contents/MacOS/palm" --stop
```

Record the output and exit code, then verify the state file is gone. Stop any
leftover process before continuing.

## 7. Logs, screenshots and uninstall (5 minutes)

Copy these to `evidence/08-logs/` before deleting anything:

```text
~/Library/Application Support/palm/logs/launcher.log
~/Library/Application Support/palm/logs/server.log
~/Library/Application Support/palm/run/server.json (if present)
~/Library/Application Support/palm/setup.json
```

Evidence folder:

```text
evidence/macos-experimental/
  01-host.txt
  02-launch.png
  03-setup/
  04-analysis.png
  05-separation.png
  06-browser/
  07-status.txt
  08-logs/
  checklist.md
  zip-sha256.txt
```

Uninstall after evidence is copied:

```sh
"$HOME/Applications/PALM.app/Contents/MacOS/palm" --stop || true
rm -rf "$HOME/Applications/PALM.app"
# Optional; this permanently deletes practice data, so back up projects first:
# rm -rf "$HOME/Library/Application Support/palm"
```

Remove any `PALM_FFMPEG`, `PALM_FFPROBE` or `PALM_DATA_DIR` exports you added.
No system service, installer or admin action is involved.

## 8. Checklist and timebox

Mark PASS, FAIL or BLOCKED with the evidence filename. The target is 45 to 60
minutes total; stop at 60 and report.

- [ ] 0-5 min: host/version/CPU fields and ZIP SHA-256 recorded.
- [ ] 5-15 min: unsigned right-click Open succeeds without admin.
- [ ] 15-25 min: CPU setup, tools and one model complete; data root is
      `~/Library/Application Support/palm`.
- [ ] 25-35 min: CPU analysis gives key, BPM, chords and bars.
- [ ] 35-45 min: short separation produces the expected stems.
- [ ] 45-55 min: Safari and Chrome playback checks pass in both.
- [ ] 55-60 min: `--status`, Ctrl+C and `--stop` clean up; evidence copied.
- [ ] Uninstall removes the app and no admin prompt appeared.

The mac-only session is capped at 60 minutes. **Do not debug or patch on the
Mac.** Capture the failing step, exact command/error, log tails, screenshot and
host details, then stop. Fixes are made in the Linux/CI tree and re-tested
there; this document remains unaccepted until the friend supplies this
one-shot evidence.

## 9. Failure report

For each failure include:

1. Step number, exact command and exit code.
2. Exact error text or wrong visual result.
3. Tails of `logs/launcher.log` and `logs/server.log`.
4. Screenshot or short recording.
5. macOS version/build, chip, memory, Safari/Chrome versions and ZIP SHA-256.
6. Whether a workaround (quarantine removal, portable FFmpeg, retry) was used.

Do not claim macOS support or acceptance from this kit; the evidence is
reviewed separately. Windows and Linux results are not macOS acceptance.
