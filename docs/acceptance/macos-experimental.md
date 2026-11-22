# macOS Apple Silicon one-shot acceptance kit

Status: **NOT RUN**. This is a one-shot kit for the owner's Apple Silicon Mac.
It makes no macOS acceptance claim until the run is complete and the evidence
below is supplied. Do not edit the app, install developer tools, or fix code on
the Mac; fixes belong in the Linux/CI tree and are re-tested there.

Target time: **45 to 60 minutes**. Stop at 60 minutes, keep the evidence and
report the blocker rather than extending the session.

This kit tests the unsigned **`PALM.app` control window**. Do not use Terminal,
a shell, a system installer or an administrator install. The app must be
usable entirely from the control window and the browser.

## Artifact and prerequisites

Use the arm64 experimental artifact supplied with this kit:

```text
PALM-0.1.0-dev-macos-arm64.zip
```

or the matching `.dmg`. Record the exact filename, byte size and the SHA-256
published with the artifact. The app is unsigned and not notarized.

The Mac needs:

- Apple Silicon (arm64), macOS 11 or newer;
- a normal user account that can write `~/Applications` and `~/Library`;
- bundled FFmpeg/Sonic/Vamp (no tool download); network only for the CPU runtime/model.
- Safari and Google Chrome installed.

Do not install FFmpeg, Sonic Annotator, Vamp plugins or Python. PALM uses its
bundled tools; setup downloads only the CPU runtime and selected model.

## 0. Host record

Use the Apple menu and System Settings only; no Terminal. Save notes and
screenshots as `evidence/01-host/`.

- Apple menu > About This Mac: chip, memory, macOS version and build.
- System Settings > General > About: model and storage.
- Safari > About Safari and Chrome > About Google Chrome: exact versions.
- Note the display and audio output device used for the listening checks.

Record the artifact name, size and SHA-256 exactly as supplied. No shell
command is required for this kit.

## 1. Unsigned launch and control window

1. In Finder, open the downloaded ZIP (or mount the DMG) and drag `PALM.app`
   to `~/Applications`. Do not use `sudo`.
2. Double-click `PALM.app`. If Gatekeeper blocks the first launch, right-click
   the app, choose **Open**, then confirm **Open**. If macOS still blocks it,
   open System Settings > Privacy & Security and use **Open Anyway**.
3. Do not remove quarantine with a terminal command; record the exact
   Gatekeeper/Privacy message if the graphical Open flow cannot proceed.

Expected:

- no Terminal window appears;
- the PALM control window opens;
- the window shows a status such as `Running at http://127.0.0.1:<port>`;
- it shows the data root (`Data: ~/Library/Application Support/palm`);
- the browser opens at the same loopback URL;
- buttons are visible: **Open browser**, **View logs**, **Quit**,
  **Check for updates**.

Save `evidence/02-control/launch.png`. If a Terminal window appears or the app
cannot open the control window, record that as a FAIL for the no-terminal
requirement and stop.

## 2. Licence review and consent

In the browser setup page, review **Before downloading** before installing
anything. It must list every downloadable component with version, licence,
source link, size and Required/Optional state, including:

- bundled FFmpeg/FFprobe 9.0.2, Sonic Annotator and Vamp plugins with
  licence/source links;
- the CPU inference environment;
- the Demucs model.

Open at least one licence and one Source link for each group and confirm they
open in a new tab. Record the components, sizes and licence names in
`evidence/03-licences/summary.txt`; screenshot the summary and full licence
text.

Accept the group licences required by the page:

- the CPU runtime and selected model;
- CPU environment;
- Demucs model.

Do not accept a licence whose text you have not reviewed. Record the exact
**Install recommended setup** state before and after consent; it must be
disabled until the required consents are given.

## 3. Recommended setup with bundled tools

Press **Install recommended setup** and follow its four visible steps:

1. CPU runtime.
2. Selected model.
3. CPU environment.
4. Demucs model.

Expected:

- PALM uses bundled FFmpeg/FFprobe, Sonic Annotator and Vamp plugins from the
  app payload. Do not install FFmpeg or set `PALM_FFMPEG`/`PALM_FFPROBE`.
- Bundled tools need no download, UAC or separate installer. Do not copy plugin
  files or grant administrator rights.
- CPU is selected; CUDA must not be offered as a working macOS choice.
- Demucs is visibly selected while all model cards remain editable.
- Each of the four progress steps and its completion message is recorded.

If macOS shows an elevation prompt for a tool, stop and record the exact
message; the kit does not grant admin rights. Save screenshots in
`evidence/04-setup/`. If a step fails, capture its Retry/Open setup action and
do not use a shell workaround.

After setup, confirm the setup page reports media tools, analysis tools, CPU
environment and Demucs installed/ready.

## 4. CPU analysis

Import a short local recording you own (5 to 30 seconds) and use Analyse.
Record:

- import succeeds and duration is shown;
- key and BPM are populated;
- chord ribbon is populated;
- bar/beat grid is visible;
- no missing-FFmpeg, missing-tool or `PiperUnavailable` error appears; analysis
  runs from the bundled Sonic/Vamp payload.

Save `evidence/05-analysis/` and the control window's **View logs** tail. A
failure must include the exact banner, log text and whether the app stayed
responsive; do not retry silently more than once.

## 5. Short CPU separation

Select the installed Demucs model and separate the same short recording.
Record:

- the model is selectable without reopening the app;
- progress stages and completion;
- the expected stem lanes (drums/bass/other/vocals, plus guitar/piano if the
  model provides them);
- at least one stem plays;
- elapsed wall time and any memory warning.

Save screenshots and the **View logs** tail in `evidence/06-separation/`. A
failure must include the exact error, model id, duration and whether the
control window remained usable.

## 6. Safari and Chrome playback

Test both **Safari** and **Google Chrome** at the control window's URL. For
each:

- the library loads and a project opens;
- Play starts audio and the position advances;
- 0.5x and 1.5x change speed while pitch remains usable;
- metronome and count-in are audible;
- a selected section loops;
- closing only the browser tab leaves the control window and server running
  (reopen the URL to confirm).

Save one screenshot per browser in `evidence/07-browser/` and state whether
audio was actually audible. A moving position alone is not proof of
audibility.

## 7. Control-window quit, update check and OS removal

Use **`PALM.app`**, not Terminal.

### Quit

Click **Quit** in the control window. Expected: the window closes, the server
stops, and the browser URL no longer responds. The data folder and logs remain.
Relaunch `PALM.app` and confirm the library reopens with the same data root;
quit again before the update check.

Save `evidence/08-control/quit.txt` and screenshots.

### Check for updates

Relaunch `PALM.app`, wait for Running, and click **Check for updates**. Expected:
the matching release/download page opens in the browser with instructions.
PALM does not download or replace itself. Record the URL and exact detail text;
a metadata error is a FAIL. Save `evidence/08-control/update-check.png`.

### Removal (OS-level)

Quit PALM, then move `PALM.app` from `~/Applications` to the Trash. Do not delete
`~/Library/Application Support/palm`; it contains practice data, models and
tools. There is no custom Uninstall button or helper. Record the app removed and
that the data root remains.

## 8. Evidence and logs

The control window's **View logs** button exposes the server log. The data root
shown in the window (normally `~/Library/Application Support/palm`) contains:

```text
logs/launcher.log
logs/server.log
run/server.json
setup.json
```

Copy or screenshot the relevant logs before removal. Do not send audio you
do not own and remove personal names or paths from screenshots.

Expected evidence folder:

```text
evidence/macos-experimental/
  01-host/
  02-control/launch.png
  03-licences/summary.txt
  04-setup/
  05-analysis/
  06-separation/
  07-browser/
  08-control/quit.txt
  08-control/update-check.png
  08-control/removal.png
  checklist.md
  artifact.txt
```

## 9. Checklist and timebox

Mark PASS, FAIL or BLOCKED with the evidence filename:

- [ ] Artifact size/SHA-256 recorded; extraction and launch use no admin and
      no Terminal.
- [ ] `PALM.app` opens the control window with no Terminal; the browser opens.
- [ ] Licence summary lists every component with licence, source, size and
      Required/Optional; group consents gate installation.
- [ ] Install recommended setup completes media tools, analysis tools, CPU and
      Demucs without a separate FFmpeg install or plugin copy.
- [ ] Bundled FFmpeg/FFprobe and Sonic/Vamp are reported ready; no
      `PALM_FFMPEG` override or tool download was needed.
- [ ] Bundled Vamp detection is automatic; no manual plugin copy or admin
      action was required.
- [ ] CPU analysis returns key, BPM, chords and bars with no missing-tool or
      missing-FFmpeg error.
- [ ] Separation returns expected stems and at least one stem plays.
- [ ] Safari playback passes play/speed/metronome/loop.
- [ ] Chrome playback passes play/speed/metronome/loop.
- [ ] Closing the browser alone leaves the control window/server running.
- [ ] Control-window Quit stops the server and preserves data.
- [ ] Check for updates opens the release/download page with instructions.
- [ ] OS-level removal (Trash) removes PALM.app and keeps the data root; no
      custom Uninstall button is expected.
- [ ] No Terminal, shell command, manual FFmpeg install or manual plugin copy
      was required.

The target is 45 to 60 minutes total; stop at 60 and report. If any step fails,
do not debug or patch on the Mac: capture the step, exact GUI text, **View
logs** tail, screenshot, host details and artifact hash, then stop.

## 10. Failure report

For every failure record:

1. Step number and the exact control-window/browser text.
2. The full error, button state and whether the app stayed responsive.
3. Screenshots of the control window, browser and **View logs** tail.
4. macOS version/build, chip, memory, Safari/Chrome versions and artifact
   SHA-256.
5. Whether Gatekeeper, Privacy & Security, a UAC-like prompt, a network retry
   or any workaround appeared.

Send the evidence to the maintainer through the agreed channel. Keep this
document Status **NOT RUN** and do not claim macOS support until the owner has
run it and supplied the evidence. Windows/Linux/CI results are not macOS
acceptance.
