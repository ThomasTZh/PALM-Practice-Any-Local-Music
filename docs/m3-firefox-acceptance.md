# M3 Firefox human acceptance guide

Purpose: verify the Milestone 3 rhythm workflow by hand in Firefox. This
guide covers the five supplied recordings and the offline portable
reopen. Record results in `docs/evidence/m3.21-listening-review.md`
(gitignored, create it from the checklist at the end).

Known UI limitation at this checkpoint: the rhythm lanes and ruler are
read-only. Metronome, count-in, loops, speed, snapping commands, and
transport all work, but there are no lane controls for moving a pulse,
setting a downbeat, or editing meter regions yet. Record any correction
you would want instead of attempting it in the UI.

## 0. Prepare once

Run all commands from the repository root:

```sh
cd /home/thomas/Documents/basseparate
```

Create a fresh acceptance storage root and copy the installed Beat This!
models into it (the model is 81 MB; `small0` is copied too):

```sh
mkdir -p storage/m3-ff-acceptance/data
cp -a storage/m3.2/data/models storage/m3-ff-acceptance/data/
.venv/bin/basseparate models verify beat_this_final0 \
  --storage-root storage/m3-ff-acceptance
.venv/bin/basseparate doctor --storage-root storage/m3-ff-acceptance
```

Expected: the model verifies, and `doctor` reports the rhythm runtime and
model as ready (GPU warnings are acceptable; analysis will use CPU).

Start the server (port 18800; use 18801 if it is busy):

```sh
.venv/bin/basseparate serve --no-browser --port 18800 \
  --storage-root storage/m3-ff-acceptance
```

The command prints one bootstrap URL containing `#token=...`. Open that
URL in Firefox. Do not open it in a private window; the token moves to
`sessionStorage` and the fragment disappears from the address bar.

Success check: the project list appears and `Connected` is shown.

## 1. Recording loop (repeat for all five)

Supplied files in `audio2test/`:

- `46.GIBBS - Simplicity.wav`
- `Carousel Theory Full Mix V1 (With Limiter).wav`
- `Summer By The Sea Instrumental Demo.wav`
- `Sweet Demo.wav`
- `Videoslave Instrumental Demo.wav`

For each file:

1. On the project list, click **New project**.
2. Enter the recording name and click **Create project**.
3. Drop the WAV on **Drop an audio or video file here**, or click the
   dropzone and choose it.
4. Wait until the import finishes and the waveform plus playback panel
   appear. If a stream-choice dialog appears, choose the stereo/mix
   stream.
5. In **Musical analysis**, click **Analyze rhythm**. Wait for the status
   line to read `Status: completed`. Typical CPU time is seconds to tens
   of seconds per excerpt; do not click it repeatedly.
6. Confirm the **Automatic** and **Edited** selectors appear, with one
   automatic result and one branch whose label includes `valid` or
   `uncertain` and a pulse count.
7. Look above the waveform: bar lines, bar numbers, beat/primary lines,
   and a meter label should be visible for the analyzed range.
8. Press **Play** briefly and watch the musical readout next to the time
   readout. It should show `Bar N Beat B...` and change as playback
   advances.
9. With playback paused, press `Shift+Right` and `Shift+Left`. The
   playhead should jump to the next/previous bar; no grid should show a
   clear "No musical grid" message.
10. Press `M` with focus outside a text field. The metronome should toggle
    and be audible while playing; pressing `M` again silences it.
11. Open **Metronome settings**, enable **Metronome**, choose
    `Primary beats`, enable **Accent downbeats**, set a comfortable
    volume, then press **Play**. Listen for one click per beat and a
    stronger click on bar starts.
12. Set **Count-in** to `One bar`, **Repeats** to `Once at start`, press
    **Play**, and confirm the status line shows `Count-in ...` for one
    bar before audio starts. Repeat with `Two bars`.
13. Drag across roughly two bars on the waveform to create a selection.
    In **Loops**, click **Create musical loop**. Confirm the loop row says
    `Musical`, **Looping** is checked, and playback repeats the selection.
14. Set **Speed** to `0.75×` (preset button or slider), play the loop for
    at least one minute, and listen for drift between clicks and audio.
    Try `0.5×` and `1.5×` as well.
15. With speed at `0.75×`, enable `One bar` count-in and
    **Repeats: Before every loop**. Confirm the count-in restarts before
    each loop pass and no clicks are dropped or doubled.
16. Seek by clicking the waveform at a different bar, then verify the
    musical readout and metronome clicks re-align at the new position.
17. In **Portable file**, click **Save portable project**, wait for the
    revision/size line, then click **Download** and keep the file.
    For full-length recordings this archive is large; if disk space is a
    concern, use a 60-second excerpt with this command first:

    ```sh
    ffmpeg -ss 60 -t 60 -i "audio2test/Sweet Demo.wav" \
      -c:a pcm_s16le /tmp/m3-excerpt.wav
    ```

18. Record the result for this recording in the checklist.

Stop playback before switching projects. Use **Stop**, not only pause.

## 2. Offline portable reopen (do once)

1. Stop the server with `Ctrl+C`.
2. Create a second, empty storage root and start a new server there:

   ```sh
   mkdir -p storage/m3-ff-offline
   .venv/bin/basseparate serve --no-browser --port 18802 \
     --storage-root storage/m3-ff-offline
   ```

3. Open the new bootstrap URL in Firefox.
4. Under **Open a portable project**, drop the `.basseparate` file
   downloaded in step 17, or click the dropzone and choose it.
5. Wait for the project view. Verify:
   - the ruler and bar/beat readout appear without running analysis;
   - the active **Edited** branch is restored;
   - the musical loop is present and still marked `Musical`;
   - metronome and count-in settings are restored;
   - **Play** works immediately;
   - clicking **Analyze rhythm** fails with
     `RHYTHM_MODEL_NOT_INSTALLED` (this root has no model), and nothing
     else breaks.
6. Stop the server and restart it once more with the same offline root.
   Reopen the project and verify the grid and loop state persisted.

## 3. Expected results

| Check | Pass condition |
|---|---|
| Import | Waveform and playback panel appear |
| Analyze rhythm | `Status: completed`; branch selector appears |
| Ruler | Bar/beat/subdivision lines and labels visible |
| Readout | `Bar N Beat B` follows playback and bar jumps |
| Metronome | Clicks audible, downbeats accented, stays aligned after 1 minute |
| Count-in | Exactly one/two bars of clicks before audio; repeats before loops |
| Loop | Musical loop repeats; speed changes do not drift |
| Portable save | Revision and size shown; download succeeds |
| Offline reopen | Grid, loop, metronome, count-in restored; playback works without model |

Record any mismatch with the exact recording, bar number, speed, and
whether the metronome, audio, or readout disagreed. Screenshots are
useful but the textual record is required.

## 4. Manual review checklist

Create `docs/evidence/m3.21-listening-review.md` with one block per
recording:

```md
### <recording name>

- Import: pass/fail
- Analyze rhythm status: completed / failed <message>
- BPM shown / meter label / grid validity:
- Readout and Shift+Arrow navigation: pass/fail
- Metronome alignment at 1× for 1 minute: pass/fail, notes
- Count-in one bar / two bars / every repeat: pass/fail, notes
- Musical loop at 0.75× for 1 minute: pass/fail, notes
- Portable save size and revision:
- Offline reopen: grid/loop/metronome/count-in restored: pass/fail
- Corrections needed (beat/downbeat/meter/loop): notes
- Visible console/runtime errors:
```

Firefox-specific checks:

- Open the developer console once per session and record any errors.
- If audio is silent, confirm the OS output device and that **Play** was
  clicked (Firefox blocks audio until a user gesture).
- If playback reports buffering problems, record the transport state and
  whether the problem survives a reload.
- Do not test Chromium in this pass. Firefox is the acceptance target for
  now; Chromium adaptation is a later step.
