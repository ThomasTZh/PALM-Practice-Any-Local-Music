# Five-recording practice review

Human acceptance for the local practice studio. Run after restarting the
backend with the local Vamp configuration. Record results in
`docs/evidence/five-recordings-review.md` (gitignored).

## Setup

```sh
export BASSEPARATE_VAMP_PLUGIN_PATH="$PWD/storage/tools/vamp-plugins"
export BASSEPARATE_VAMP_NATIVE_HOST_PATH="$PWD/storage/tools/vamp-host"
.venv/bin/basseparate serve --no-browser --port 18800 \
  --storage-root storage/m3-ff-acceptance
```

Use Firefox and hard-reload. The five supplied files are in `audio2test/`:

1. `46.GIBBS - Simplicity.wav`
2. `Carousel Theory Full Mix V1 (With Limiter).wav`
3. `Summer By The Sea Instrumental Demo.wav`
4. `Sweet Demo.wav`
5. `Videoslave Instrumental Demo.wav`

## Per recording

For each file:

1. Create a project and import the file; wait for **Ready**.
2. Click **Separate stems**; wait for the four-track mixer. Use CPU if no
   qualified GPU is offered.
3. Click **Analyze rhythm** with the correct **Beats per bar** (default 4).
4. Confirm the ruler and bar/beat lanes appear and bar 1 is sensible.
5. Drag a 4–8 bar passage; click **Add section from selection**.
6. Rename it, click **Loop**, and play. Check:
   - the loop boundary is clean;
   - the first click is on the downbeat;
   - four clicks per bar for 4/4;
   - no missing or doubled clicks.
7. Set 0.75× and 1.25×; check pitch remains natural and loop timing holds.
8. Save the portable project.
9. Reopen it after a fresh app start or offline open; confirm sections, loop,
   speed, and stems are retained.

## Evidence table

| Recording | Stems | Grid 4/4 | Section | Loop clean | Speed | Save/reopen | Notes |
|---|---|---|---|---|---|---|---|
| 46.GIBBS | | | | | | | |
| Carousel Theory | | | | | | | |
| Summer By The Sea | | | | | | | |
| Sweet Demo | | | | | | | |
| Videoslave | | | | | | | |

## Pass criteria

- Five recordings complete the flow without manual database work.
- No audible metronome drift or dropped click on a steady 4/4 passage.
- Loop boundaries do not click or truncate the passage.
- Speed changes preserve pitch and do not desynchronise the grid.
- Portable reopen retains sections and the active section loop.

Record failures with the recording, section frame range, bpb, speed, and
whether the grid or the transport is at fault.
