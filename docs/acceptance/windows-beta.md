# Windows x64 no-admin acceptance kit

Status: **NOT RUN**. This is a kit and checklist for the user's Windows laptop.
It does not claim Windows acceptance until the laptop run is completed and the
evidence below is supplied.

The kit exercises the unsigned Windows portable ZIP described in
[packaging/windows/README.md](../../packaging/windows/README.md). Use a normal
user account. Every step must work without UAC, an administrator shell, a
system-wide installer or a machine-wide PATH change.

## Artifact

Use the Windows ZIP supplied with this kit:

`PALM-0.1.0-dev-windows-x86_64.zip`

Record its exact name, byte size and SHA-256 in the evidence file. Do not
continue if `Get-FileHash` does not match the checksum supplied by the
maintainer. The archive is unsigned and may trigger SmartScreen; no signing is
claimed.

## 1. Host record

Run these in PowerShell and save the output as `evidence\01-host.txt`:

```powershell
$ErrorActionPreference = "Stop"
"Windows: " + [System.Environment]::OSVersion.VersionString
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption, Version, BuildNumber, OSArchitecture, LastBootUpTime |
  Format-List
Get-CimInstance Win32_Processor |
  Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed |
  Format-List
Get-CimInstance Win32_ComputerSystem |
  Select-Object Manufacturer, Model, TotalPhysicalMemory |
  Format-List
$PSVersionTable | Format-List
```

Record Windows edition/build, CPU model, physical/logical cores, base clock,
RAM, GPU (if any), browser versions and PowerShell version. Windows 10 or 11
x64 and a desktop Chrome/Firefox are the intended targets. CUDA is not a
supported Windows target in this beta; choose the CPU environment.

## 2. Extract without admin

1. Unblock the downloaded archive if Windows marks it:

   ```powershell
   Unblock-File -LiteralPath "$env:USERPROFILE\Downloads\PALM-0.1.0-dev-windows-x86_64.zip"
   ```

2. Extract under the user profile. Do not use `C:\Program Files` and do not
   run the shell as administrator:

   ```powershell
   $zip = "$env:USERPROFILE\Downloads\PALM-0.1.0-dev-windows-x86_64.zip"
   $dest = "$env:LOCALAPPDATA\Programs\PALM"
   Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
   Expand-Archive -LiteralPath $zip -DestinationPath $dest
   $app = Get-ChildItem $dest -Directory | Select-Object -First 1
   Set-Location $app.FullName
   Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Format-List
   ```

Record the resulting `$app.FullName`, ZIP SHA-256 and whether any UAC prompt
appeared (expected: none). Do not edit `palm.cmd`.

## 3. Portable FFmpeg and FFprobe

The ZIP does not include FFmpeg. Place a trusted Windows FFmpeg build outside
the extracted app tree, for example:

```text
%USERPROFILE%\Downloads\ffmpeg\bin\ffmpeg.exe
%USERPROFILE%\Downloads\ffmpeg\bin\ffprobe.exe
```

For the current PowerShell session, set both overrides before starting PALM:

```powershell
$env:PALM_FFMPEG  = "$env:USERPROFILE\Downloads\ffmpeg\bin\ffmpeg.exe"
$env:PALM_FFPROBE = "$env:USERPROFILE\Downloads\ffmpeg\bin\ffprobe.exe"
& $env:PALM_FFMPEG -version
& $env:PALM_FFPROBE -version
```

`BASSEPARATE_FFMPEG`/`BASSEPARATE_FFPROBE` are accepted aliases, but use the
`PALM_*` names for this run. If you use `setx` to persist them, open a new
PowerShell afterwards and re-check `$env:PALM_FFMPEG`. Record both command
outputs in `evidence\03-ffmpeg.txt`. The setup checks must show ffmpeg ready;
if they do not, stop and report the resolved path.

## 4. Start and setup

From the extracted app folder:

```powershell
Set-Location $app.FullName
.\palm.cmd
```

A console must open, print the local URL and open the browser. Keep that
console open. Closing only the browser must not stop the server.

In the setup wizard:

1. Confirm System checks, especially ffmpeg with the portable path.
2. Install the analysis tools if offered. The Windows tool path is Sonic
   Annotator plus the Vamp plugin pack. If Windows reports that the Vamp
   per-user install needs administrator rights, stop and report the exact
   message; do not elevate.
3. Choose **CPU**, not CUDA. Record the download size shown.
4. Install one model card only. Record the model id, size and licence shown.
5. Wait for setup complete. Do not skip a failing step.

Capture the complete wizard, the setup result and the browser URL in
`evidence\04-setup\`. Save the console text from the start through setup.

## 5. CPU analysis

Import a short local recording you own, 5 to 30 seconds is enough. Use the
analysis action and record:

- import succeeds and duration is shown;
- chord ribbon is populated;
- key and BPM are populated;
- bar/beat grid is visible;
- no `PiperUnavailable`, missing-tool or missing-ffmpeg error appears.

Save a screenshot in `evidence\05-analysis\` and copy the relevant
`server.log` lines. If analysis fails, record the exact banner and log tail;
do not retry silently more than once.

## 6. Short CPU separation

Select the installed model and separate the same short recording. Record:

- selected model id and that it is selectable without reopening;
- progress stages and completion;
- drums, bass, other and vocals (plus guitar/piano if the chosen model
  provides them) appear as stem lanes;
- playback of at least one stem works;
- elapsed wall time and any memory warning.

Save screenshots and the log tail in `evidence\06-separation\`. A failure must
include the exact error, model id, duration and whether the app remained
responsive.

## 7. Browser playback checks

Run the same checks in **Chrome** and **Firefox** (latest stable installed on
the laptop). For each browser record:

- page loads at `http://127.0.0.1:<port>/` and the library is usable;
- Play starts audio and the position advances;
- speed 0.5x and 1.5x change playback while pitch remains usable;
- metronome and count-in are audible;
- loop over a selected section wraps;
- closing the browser tab does not stop the terminal/server.

Save one screenshot per browser in `evidence\07-browser\`, plus a short
screen recording if available. State explicitly whether audio output was
audible; a visual position advance alone is not proof of audibility.

## 8. Status, Ctrl+C and stop

With PALM running, in a second PowerShell:

```powershell
Set-Location $app.FullName
.\palm.cmd --status
```

Expected: exit 0 and lines for URL, data root, and server/launcher pids. Save
the output as `evidence\08-status.txt`.

Return to the PALM console and press **Ctrl+C**. Expected: the console exits,
the browser URL stops responding, and `run\server.json` is absent. Record the
console tail and:

```powershell
Test-Path "$env:LOCALAPPDATA\palm\run\server.json"
```

If Ctrl+C leaves a server, restart and use `.\palm.cmd --stop`; record its
output and exit code. Then verify again that the state file is gone.

## 9. Logs and evidence

Default data root: `%LOCALAPPDATA%\palm` (override with `--data-dir` or
`PALM_DATA_DIR`). Relevant files:

```text
%LOCALAPPDATA%\palm\logs\launcher.log
%LOCALAPPDATA%\palm\logs\server.log
%LOCALAPPDATA%\palm\run\server.json
%LOCALAPPDATA%\palm\setup.json
%LOCALAPPDATA%\palm\projects\
%LOCALAPPDATA%\palm\stems\
%LOCALAPPDATA%\palm\models\
%LOCALAPPDATA%\palm\tools\
%LOCALAPPDATA%\palm\environments\
```

Before sending evidence, copy the logs and state files, record the data-root
path, and remove personal audio paths or names if needed. Do not send audio
you do not own.

Expected evidence folder:

```text
evidence\windows-beta\
  01-host.txt
  03-ffmpeg.txt
  04-setup\
  05-analysis\
  06-separation\
  07-browser\
  08-status.txt
  09-logs\
  checklist.md
  zip-sha256.txt
```

## 10. Uninstall

1. Stop PALM with Ctrl+C, or `.\palm.cmd --stop`.
2. Remove the extracted app folder (`$app.FullName` or
   `%LOCALAPPDATA%\Programs\PALM`).
3. If you also want to delete practice data, remove
   `%LOCALAPPDATA%\palm`. Back up `projects\`, `assets\` and `uploads\` first;
   this deletion is permanent.
4. Remove any `PALM_FFMPEG`, `PALM_FFPROBE`, `PALM_DATA_DIR` environment
   variables you added for the test.

Nothing is installed system-wide; no service, registry uninstall entry or
administrator action is required. Record the commands and the result of
checking that the app and data folders are gone.

## 11. Checklist

Mark each item PASS, FAIL or BLOCKED and attach the evidence filename:

- [ ] ZIP SHA-256 matches the supplied checksum; extraction needs no admin.
- [ ] `palm.cmd` opens a console without UAC; URL opens in browser.
- [ ] Portable `PALM_FFMPEG` and `PALM_FFPROBE` are used; setup reports ready.
- [ ] Setup completes with analysis tools, CPU environment and one model.
- [ ] CPU analysis produces key, BPM, chords and bars.
- [ ] Short separation produces all expected stem lanes.
- [ ] Chrome playback: play, speed, metronome, loop.
- [ ] Firefox playback: play, speed, metronome, loop.
- [ ] Closing browser alone leaves server running.
- [ ] `palm.cmd --status` reports URL/data root/pids.
- [ ] Ctrl+C stops the server cleanly; state file removed.
- [ ] `palm.cmd --stop` is available and removes stale state.
- [ ] Uninstall removes app and optional data without admin.
- [ ] No FFmpeg/tools/models/environments were extracted from the ZIP into the app tree.

## 12. Failure reporting

For every failure record:

1. The exact step number and command.
2. The exact error text and exit code, or "no error, wrong result".
3. The tail of `logs\server.log` and `logs\launcher.log` (at least 80 lines).
4. A screenshot or short recording of the screen.
5. Windows version/build, CPU, browser version and ZIP SHA-256.
6. Whether the step required admin, a network retry or a manual directory
   creation; do not hide a workaround.

Send the evidence folder to the maintainer through the agreed channel. Do not
mark this document accepted or add a PASS result until the laptop owner has
run the steps and supplied the evidence. The Linux/Wine and CI results are
build evidence only, not Windows laptop acceptance.
