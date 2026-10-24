# Audible judgement guide (Firefox, M3)

This is the listening-only pass. UI state, import, analysis, and portable
save are already covered by the Firefox Playwright test; do not repeat
those unless something fails.

Use headphones or a single output device. Relative click/audio alignment
is what matters, so Bluetooth output latency does not invalidate the
comparison as long as both go to the same device.

## 0. Restart and open

The storage-path and import fixes are server-side. Stop the old server
(`Ctrl+C`) and start it again:

```sh
cd /home/thomas/Documents/basseparate
.venv/bin/basseparate serve --no-browser --port 18800 \
  --storage-root storage/m3-ff-acceptance
```

Open the printed URL in Firefox and hard-reload (`Ctrl+Shift+R`).

If the project with the uploaded file still shows empty, open it and
click **Prepare audio** once. Wait until the waveform and **Play** button
appear. Then click **Analyze rhythm** and wait for `Status: completed`
and the **Automatic** / **Edited** selectors.

## 1. Set the listening baseline

1. Use **Original** playback mode (there is no separation control in this
   UI).
2. Set **Monitoring volume** to a comfortable level (start at 60–100%).
3. In **Metronome settings**:
   - enable **Metronome**;
   - set volume so clicks are clearly audible over the music but not
     painful (start around 40–60%);
   - **Clicks: Primary beats**;
   - **Accent downbeats** checked.
4. Set **Count-in** to `Off` for the metronome tests. You will enable it
   later.
5. Choose a 30–60 second section with a clear, steady drum/bass pulse.
   Click the waveform to position the playhead there.

## 2. Metronome alignment at 1×

1. Press **Play**.
2. Listen for 10–15 seconds, then keep playing for at least 60 seconds.
3. Compare each click with the perceived beat (usually the bass drum or
   the bass note attack).

Pass:
- the click sounds with the beat, not as a separate flam or double
  attack;
- no progressive offset: the last 10 seconds feel the same as the first
  10;
- downbeats are stronger and land on the first beat of the bar.

Record: `aligned`, `early`, `late`, `drift after N s`, or `unusable`.
If it is late/early by a constant amount, note roughly how much (for
example "about one 16th late") and the BPM/meter shown in the ruler.

## 3. Speed changes

1. Keep playing at 1× and listen for the beat.
2. Click **0.75×** while playing. Listen for 10–15 seconds.
3. Click **1.25×**, then **1.5×**, then **0.5×**.
4. Return to **1×**.

Pass: click tempo follows the audio; no phase jump at the moment of the
change; no cumulative drift after the change.

Record each speed separately if one fails.

## 4. Seek and resume

1. While playing, click a different bar on the waveform.
2. Listen to the first few clicks after the seek.
3. Pause, seek again, then press **Play**.

Pass: the first click after the seek is on a beat; no burst of old
clicks; no silent gap longer than the intended seek.

## 5. Count-in, one and two bars

1. Set **Count-in** to `One bar`.
2. Set **Repeats** to `Once at start`.
3. Seek to a bar start, press **Play**, and count the clicks before the
   music begins.

Expected number of clicks per bar is the number of primary pulses in the
meter grouping shown in the ruler:

| Meter / grouping | Clicks in one bar |
|---|---|
| 4/4 (1+1+1+1) | 4 |
| 3/4 (1+1+1) | 3 |
| 6/8 (3+3) | 2 |
| 9/8 (3+3+3) | 3 |
| 12/8 (3+3+3+3) | 4 |
| 5/4 (2+3) or (3+2) | 2 |
| 7/8 (2+2+3 etc.) | 3 |

4. Repeat with **Two bars**: twice the count.
5. Listen to the first count click: it should be the accented downbeat
   of the count, and the music should enter on the next downbeat after
   the last count click.

Pass: exactly the expected number of clicks; no missing/extra click; no
music before the count ends; no click after the music starts (unless the
metronome is enabled and should continue).

Record the observed count versus expected.

## 6. Count-in at slow and fast speeds

1. Set speed to **0.25×**, count-in `One bar`, and play.
2. Listen to the count duration and clarity.
3. Repeat at **2×**.

Pass: the count slows/speeds with playback; it does not overlap the
music or clip; the downbeat accent is still distinguishable.

## 7. Loop and count-in before every repeat

1. Drag a selection of about two bars on the waveform.
2. Click **Create musical loop**.
3. Check **Looping**.
4. Set **Count-in** to `One bar`, **Repeats** to `Before every loop`.
5. Press **Play** and listen for at least three loop passes.

Pass:
- the loop repeats without a gap or double hit at the join;
- the count-in plays before each repeat;
- clicks stay aligned to the music after each pass;
- the click count is the same on every pass.

6. Switch **Repeats** back to `Once at start` and confirm the count-in
   happens only before the first pass.

Record the loop length, speed, and whether drift grows per pass.

## 8. Stop and pause during count-in

1. Enable `One bar` count-in.
2. Press **Play**, then press **Stop** during the count.
3. Repeat, pressing **Play/Pause** during the count.

Pass: clicks stop immediately; no audio starts late; a new **Play**
starts a fresh count.

## 9. Meter and grouping check

For each recording, read the meter label in the ruler (for example
`4/4`, `6/8 (3+3)`, `7/8 (2+2+3)`) and listen to the accent pattern:

- 4/4: accent every 4 primary beats;
- 6/8 (3+3): two grouped pulses per bar, first accented;
- 7/8: three grouped pulses with the grouping pattern accented.

Pass: the perceived bar starts agree with the accented clicks and the
bar labels in the ruler. If the meter is wrong, record the label and
where it diverges; do not try to correct it in the UI (lane editing is
read-only at this checkpoint).

## 10. Before the first mapped pulse

1. Seek to the very start of a recording whose first detected pulse is
   slightly after 0.
2. Play with the metronome enabled.

Pass: no clicks occur in the unmapped lead-in; clicks begin at the first
mapped beat. A brief "no grid" state is acceptable; a click at an
arbitrary time is not.

## Per-recording record

Copy this block into `docs/evidence/m3.21-listening-review.md` for each of
the five supplied files:

```md
### <recording>

- Section used / duration:
- Meter label / grouping / BPM:
- 1× metronome, 60 s: aligned / early / late / drift (notes)
- 0.5× / 0.75× / 1.25× / 1.5×:
- Seek/resume:
- One-bar count-in: observed clicks / expected:
- Two-bar count-in: observed clicks / expected:
- Count-in at 0.25× / 2×:
- Loop pass alignment and every-repeat count-in:
- Stop/pause during count-in:
- Meter/grouping agreement:
- Unmapped lead-in:
- Defects to fix (with timestamps/bar numbers):
```

If only one thing can be tested, prioritize: **1× alignment**, **60 s
drift**, **one-bar count-in**, and **loop every-repeat**. Those are the
highest-risk behaviours.
