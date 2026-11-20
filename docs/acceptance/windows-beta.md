# Windows x64 no-terminal acceptance kit

Status: **NOT RUN**. This is a checklist for the owner's Windows laptop. It
makes no Windows acceptance claim until the run is completed and the evidence
below is supplied.

This kit tests the native **`PALM.exe` control window** from the unsigned
Windows x64 beta ZIP. Do not use a command prompt, `palm.cmd`, an administrator
shell, a system installer or a machine-wide PATH change. The app must be
usable entirely from the control window and the browser.

## Artifact

Use the Windows artifact supplied with this kit:

```text
PALM-0.1.0-dev-windows-x86_64.zip
```

Record the exact filename, byte size and the SHA-256 published with the
artifact. Do not continue if the size differs. The archive is unsigned and may
trigger SmartScreen; no signing claim is made.

## 1. Host record

Use Windows Settings and Task Manager only. Save screenshots and notes as
`evidence/01-host/`.

- Settings > System > About: Windows edition, version, build, processor and
  installed RAM.
- Task Manager > Performance > CPU: model, cores, logical processors and base
  speed.
- Browser Help/About: exact Chrome and Firefox versions.
- System Information or the laptop label: manufacturer and model.
- Note the GPU, but do not expect CUDA. The Windows beta is CPU only.

Record the artifact name, size and SHA-256 exactly as supplied. No terminal
command is required for this kit.

## 2. Extract without admin

1. In File Explorer, open the downloaded ZIP.
2. Extract it under the user profile, for example:

   ```text
   %LOCALAPPDATA%\Programs\PALM
   ```

   Do not use `C:\Program Files` and do not run any installer as
   administrator.
3. If Windows marks the ZIP as blocked, use the file's Properties > Unblock
   before extracting. Record whether SmartScreen or Unblock appeared.

Record the extracted folder and confirm that the ZIP contains `PALM.exe` at
the folder root. Do not edit or replace `PALM.exe`.

## 3. Start the control window

Double-click **`PALM.exe`** in the extracted folder.

Expected:

- no console window appears;
- the PALM control window appears with a status such as
  `Running at http://127.0.0.1:<port>`;
- the window shows the data root (`Data: ...`);
- the browser opens the same loopback URL;
- buttons are visible: **Open browser**, **View logs**, **Quit**,
  **Check for updates**.

If Windows SmartScreen appears, choose **More info** > **Run anyway**. Record
whether SmartScreen appeared. If no control window appears, capture the exact
message and stop; do not fall back to a terminal.

Save `evidence/02-control/launch.png` and record the URL and data root shown in
the control window. Closing only the browser must not stop the server; verify
that the control window still says Running.

## 4. Licence review and consent

In the browser setup page, review the **Before downloading** summary before
installing anything. It must list every downloadable component with its
version, licence, source link, size and Required/Optional state, including:

- managed FFmpeg/FFprobe;
- the CPU inference environment;
- the Demucs model.

Windows Sonic/Vamp analysis is temporarily blocked while the 64-bit plugin
bundle is rebuilt, so no Vamp/Sonic component or licence is offered on this
platform.

Open at least one licence and one Source link for each group and confirm they
open in a new tab. Record the listed components, sizes and licence names in
`evidence/03-licences/summary.txt`; screenshot the full summary and the full
licence text.

Accept the group licences required by the page:

- media tools (FFmpeg/FFprobe);
- CPU environment;
- Demucs model.

Do not accept a licence whose text you have not reviewed. The
**Install recommended setup** button must become enabled only after the
required consents. Record its exact state before and after consent.

## 5. Recommended setup, managed FFmpeg and Windows analysis blocker

Press **Install recommended setup** and follow the visible steps:

1. Media tools (FFmpeg/FFprobe).
2. CPU environment.
3. Demucs model.

Expected:

- FFmpeg and FFprobe are downloaded by PALM into its data root. Do not install
  FFmpeg separately and do not set `PALM_FFMPEG` or `PALM_FFPROBE`.
- Windows Sonic/Vamp analysis is **temporarily unavailable** in this build
  while the plugin bundle is rebuilt. The UI must report that blocker clearly;
  do not use an administrator prompt, separate installer, manual DLL copy or workaround
  workaround. Record the exact blocker text.
- CPU is selected; CUDA must not be offered as a working Windows choice.
- Demucs is visibly selected in the model cards while all model cards remain
  editable.
- The progress stage and completion message are recorded for each available
  step.

Save screenshots of each step and the final setup state in
`evidence/04-setup/`. If a step fails, save the exact error and its Retry or
Open setup action; do not skip the step and do not use a terminal workaround.

After setup, confirm in the setup page that media tools, CPU environment and
Demucs show installed/ready. Analysis remains BLOCKED on this platform.

## 6. Import, playback and separation (analysis blocked)

Import a short local recording you own (5 to 30 seconds). Use the normal
import, playback and Separate actions. Record:

- import succeeds and the duration is shown;
- playback, speed, pitch, loop and metronome work;
- separation returns stem lanes and at least one stem plays;
- the Analyse control reports the Windows analysis blocker, with no UAC,
  administrator or manual-DLL workaround.

Screenshot the result in `evidence/05-analysis-blocked/`. Do not claim chord,
key, BPM or bar analysis on Windows; it is not part of this beta.

## 7. Short CPU separation

Select the installed Demucs model in the mixer and separate the same short
recording. Record:

- the model is selectable without reopening or reloading the app;
- progress stages and completion;
- drums, bass, other and vocals appear as stem lanes;
- playback of at least one stem works;
- elapsed wall time and any memory warning.

Save screenshots and the **View logs** tail in `evidence/06-separation/`. A
failure must include the exact error, model id, duration and whether the
control window remained usable.

## 8. Browser playback

Test both **Chrome** and **Firefox** at the control window's URL. For each:

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

## 9. Control-window quit, update check and OS removal

Use **`PALM.exe`**, not a terminal.

### Quit

Click **Quit** in the control window. Expected: the window closes, the server
stops, and the browser URL no longer responds. The default data folder and its
logs remain. Relaunch `PALM.exe` and confirm the library still opens with the
same data root; then quit again for the update check.

Save screenshots and note the result in `evidence/08-control/quit.txt`.

### Check for updates

Relaunch `PALM.exe`, wait for Running, and click **Check for updates**. Expected:
the matching release/download page opens in the browser with instructions.
PALM does not download or replace itself. Record the URL and exact detail text;
a metadata error is a FAIL. Save `evidence/08-control/update-check.png`.

### Removal (OS-level)

Quit PALM, then remove the app with Windows Installed apps (installed build) or
File Explorer (portable ZIP). Do not delete `%LOCALAPPDATA%\palm`; it contains
practice data, models and tools. There is no custom Uninstall button/helper.

For the installed build, the interactive uninstaller offers app-only (default,
keeps data) or also deleting the default `%LOCALAPPDATA%\palm`. Test the
app-only path in the normal run. The delete-data branch is a separate manual
step: create a marker under `%LOCALAPPDATA%\palm`, run the uninstaller, choose
No, and confirm only that default root is removed. A custom `PALM_DATA_DIR` or
`--data-dir` is never removed automatically. Record the exact prompt and result.

## 10. Evidence and logs

The control window's **View logs** button exposes the server log. The data root
shown in the window (normally `%LOCALAPPDATA%\palm`) contains:

```text
logs\launcher.log
logs\server.log
run\server.json
setup.json
```

Copy or screenshot the relevant logs before removal. Do not send audio you
do not own and remove personal names or paths from screenshots.

Expected evidence folder:

```text
evidence\windows-beta\
  01-host\
  02-control\launch.png
  03-licences\summary.txt
  04-setup\
  05-analysis-blocked\
  06-separation\
  07-browser\
  08-control\quit.txt
  08-control\update-check.png
  08-control/removal.png
  checklist.md
  artifact.txt
```

## 11. Checklist

Mark PASS, FAIL or BLOCKED with the evidence filename:

- [ ] Artifact size/SHA-256 recorded; extraction under the user profile needed
      no administrator shell.
- [ ] `PALM.exe` opens the control window with no console; the browser opens.
- [ ] Licence summary lists every component with licence, source, size and
      Required/Optional; group consents gate installation.
- [ ] Install recommended setup completes media tools, CPU and Demucs without a
      separate FFmpeg install or DLL copy.
- [ ] Managed FFmpeg/FFprobe are reported ready; no `PALM_FFMPEG` override was
      needed.
- [ ] Windows analysis blocker is clearly reported (temporary plugin-bundle
      rebuild); no admin/manual-DLL workaround was offered, and no Vamp/Sonic
      component is listed as downloadable.
- [ ] Import, playback and separation work; analysis is not claimed.
- [ ] Separation returns the expected stem lanes and at least one stem plays.
- [ ] Chrome playback passes play/speed/metronome/loop.
- [ ] Firefox playback passes play/speed/metronome/loop.
- [ ] Closing the browser alone leaves the control window/server running.
- [ ] Control-window Quit stops the server and preserves data.
- [ ] Check for updates opens the release/download page with instructions.
- [ ] OS-level removal (File Explorer/Installed apps) removes the app and keeps
      the data root; no custom Uninstall button is expected.
- [ ] No terminal, `palm.cmd`, manual FFmpeg install or manual DLL copy was
      required.

## 12. Failure reporting

For every failure record:

1. Step number and the exact control-window/browser text.
2. The full error, button state and whether the app stayed responsive.
3. Screenshots of the control window, browser and **View logs** tail.
4. Windows edition/build, CPU, RAM, browser versions and artifact SHA-256.
5. Whether SmartScreen, a network retry or any workaround appeared.

Send the evidence to the maintainer through the agreed channel. Keep this
document Status **NOT RUN** and do not claim Windows support until the owner
has run it and supplied the evidence. Wine/CI results are build evidence only,
not Windows laptop acceptance.
