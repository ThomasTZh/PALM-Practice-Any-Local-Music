
# Milestone 1 — Import, waveform, and original playback: detailed implementation specification

This expands Milestone 1 in Section 13 of [basseparate_project_plan.md](../product/basseparate_project_plan.md). It builds on the foundation specified in [milestone0.md](milestone0.md).

The implementation sequence below covers media import, local storage, audio decoding, waveform rendering, original-track playback, basic annotations, persistence, and validation.

## 1. Outcome and milestone boundaries

### 1.1 Required user workflow

At completion, the user can:

1. Launch basseparate.
2. Create or open a working project.
3. Import a local audio or video file.
4. Select an audio stream when the file contains several.
5. See the original audio waveform.
6. Play, pause, stop, and seek.
7. Zoom horizontally from the whole recording to individual samples.
8. Zoom waveform amplitude vertically without changing playback volume.
9. Select a time range.
10. Add, rename, move, and delete markers.
11. Undo and redo the annotation edits introduced in this milestone.
12. Close and reopen the working project.
13. Resume working without importing or decoding the source again.

### 1.2 Included capabilities

- Browser file picker and drag-and-drop.
- Bounded-memory file transfer to localhost.
- File hashing and deduplicated source storage.
- ffprobe inspection.
- Audio-stream selection.
- Canonical float32 PCM decoding.
- Original channel preservation.
- Explicit stereo monitoring downmix for multichannel sources.
- Playback-rate conversion when the browser uses a different sample rate.
- Multiresolution waveform caches.
- Canvas waveform rendering.
- A shared, extensible browser transport.
- PCM buffering and seek cancellation.
- Source-time readout.
- Follow-playhead behavior.
- Basic selection and markers.
- Working-project autosave and recovery.
- Format, timing, memory, and browser tests.

### 1.3 Deferred capabilities

These remain in their planned later milestones:

- Source separation.
- Multiple separated tracks.
- Variable-speed playback and pitch preservation.
- Loops and loop queues.
- Metronome and count-in.
- Beat, chord, key, and bass-note analysis.
- Musical bar/beat ruler.
- Beat snapping.
- YouTube import.
- Portable `.basseparate` archive creation.
- Audio and analysis exports.

The playback architecture must allow these additions, but Milestone 1 must not simulate them.

### 1.4 Existing environment

The inspected workspace contains the main plan, `milestone0.md`, five WAV files, and a system inventory. It does not yet contain the implemented application.

FFmpeg 8.1.2 and ffprobe are installed. Their presence establishes feasibility, not completion of any decoding or playback tests.

---

## 2. Technical decisions fixed for this milestone

| Area | Decision |
|---|---|
| Project time | Integer sample-frame positions at the selected source stream’s sample rate |
| Source storage | Preserve original imported file unchanged |
| Canonical decoded audio | Interleaved little-endian float32 PCM with separate metadata |
| Multichannel sources | Preserve all original channels; create a separate stereo monitoring representation |
| Browser audio | One `AudioContext`, one AudioWorklet transport |
| Browser sample-rate mismatch | Cached FFmpeg-generated playback representation at the actual context rate |
| Normal playback speed | Exactly 1× |
| Waveform rendering | Canvas 2D with shared viewport transforms |
| Waveform cache | Min/max pyramid, 64-frame base buckets, factor-four coarsening |
| Large binary responses | Bounded binary PCM and peak endpoints |
| Job execution | Local subprocess worker; one media-processing job at a time initially |
| Progress delivery | Poll durable job state; defer general WebSocket event infrastructure |
| Persistence | Extend Milestone 0 SQLite storage |
| Annotation edits | Transactional commands with revision checks and undo/redo |
| Source replacement | Not supported inside an already populated project in this milestone |

### 2.1 Terminology

A **sample frame** contains one sample for every channel at one instant.

For stereo audio:

- One frame contains two samples.
- Frame 100 has a left sample and a right sample.
- Timeline positions count frames, not individual interleaved channel values.

Use `frame` explicitly in implementation names where ambiguity would otherwise arise.

### 2.2 Authoritative duration

For canonical PCM:

```text
duration_seconds = frame_count / sample_rate
```

The decoded frame count is authoritative. Container metadata provides an estimate until decoding completes.

---

## 3. Work package M1.1 — Validate prerequisites and extend contracts

### 3.1 Confirm Milestone 0 readiness

Before implementing import:

1. Run the foundation checks.
2. Verify the application launches without a model.
3. Verify authentication works.
4. Create and reopen an empty project.
5. Verify database migration behavior.
6. Verify generated API types match backend contracts.
7. Verify worker-probe startup and cleanup.
8. Record any failed prerequisite before adding media functionality.

Do not build import on a nonpersistent mock project.

### 3.2 Extend project metadata

Add:

- Original-file asset ID.
- Canonical-audio asset ID.
- Selected source stream index.
- Source sample rate.
- Source frame count.
- Source channel count.
- Source channel layout.
- Decode-profile version.
- Waveform-cache status.
- Optional monitoring-downmix asset ID.
- Source metadata summary.

Keep import-job state separate from the project’s source readiness.

A project may have usable audio while waveform generation is still running.

### 3.3 Define import records

An import record contains:

- Import ID.
- Target project ID.
- Original filename.
- Declared byte count.
- Received byte count.
- Completed source SHA-256.
- Transfer state.
- Probe result.
- Selected stream.
- Processing job IDs.
- Error details.
- Creation/update timestamps.

### 3.4 Define audio representation metadata

Each decoded or derived representation records:

- Asset ID.
- Parent asset ID.
- Representation role.
- Sample rate.
- Channel count.
- Channel layout.
- Frame count.
- Encoding: `f32le`.
- Interleaving: `interleaved`.
- Content hash.
- Transform/version identity.
- Project-time mapping.
- Decoder/resampler provenance.

### 3.5 Add dependencies

Add NumPy for efficient PCM and waveform-array processing.

Keep FFmpeg and ffprobe as executable dependencies. Do not add neural inference packages.

Update locks and the component/license inventory.

**Acceptance:** the schemas distinguish original media, canonical PCM, monitoring audio, playback-rate audio, and waveform caches.

---

## 4. Work package M1.2 — Implement bounded local file transfer

### 4.1 Browser file selection

1. Add an “Import audio or video” control to empty projects.
2. Support drag-and-drop onto the empty editor.
3. Use a normal browser file input as the compatibility baseline.
4. Treat file extensions as picker hints only.
5. Validate actual contents on the backend.
6. Accept one file per import.
7. If several files are dropped, ask the user to choose one.
8. Preserve the user-visible filename as metadata.
9. Never interpret it as a server path.

### 4.2 Upload protocol

Use a resumable, sequential chunk protocol.

Initial defaults:

- Chunk size: 8 MiB.
- Maximum imported local media file: 20 GiB.
- This media-import limit does not apply to portable `.basseparate` archives; Milestone 2 defines a separate configurable archive-transfer limit.
- One active transfer per import.
- Configurable file-size limit.
- No entire-file `arrayBuffer()` call.

Sequence:

1. Create an import session.
2. Receive the accepted maximum size and chunk size.
3. Read the first `File.slice()`.
4. Send it as `application/octet-stream`.
5. Receive the acknowledged byte offset.
6. Continue sequentially.
7. Finalize after all bytes are acknowledged.
8. Verify declared and received sizes.
9. Calculate the full source hash.
10. Start probing.

### 4.3 Backend upload handling

1. Authenticate every request.
2. Validate project ownership within local application state.
3. Require the target project to be empty.
4. Reserve an app-generated temporary path.
5. Check available disk space.
6. Enforce body-size limits before and while reading.
7. Stream each body to disk.
8. Validate the expected offset.
9. Return the durable acknowledged offset.
10. Keep the upload manifest separate from media bytes.
11. Reject concurrent writes to the same upload.
12. Never buffer the complete media file in server memory.

### 4.4 Retry behavior

1. Include chunk offset, byte count, and chunk hash.
2. A repeated identical chunk returns the existing acknowledgment.
3. A repeated offset with different bytes returns a conflict.
4. An offset beyond the next expected position is rejected.
5. Retry transient transfer failures up to three times.
6. Preserve the import session after retries are exhausted.
7. Display “Transfer interrupted,” not “Invalid audio.”

### 4.5 Browser reload recovery

The browser cannot assume continued access to the original `File` after a reload.

1. List incomplete imports when reopening the project.
2. Ask the user to reselect the file to resume.
3. Compare file size and the hashes of already acknowledged chunks.
4. Resume only if the content matches.
5. Otherwise offer to start a new import.
6. Do not append a different file to an existing partial upload.

### 4.6 Cancellation

1. Provide Cancel during transfer.
2. Abort the active HTTP request.
3. Mark the import cancelled.
4. Remove only the cancelled import’s uncommitted temporary bytes.
5. Retain any previously published shared assets.
6. Leave the project empty and usable.

**Acceptance:** large files transfer with bounded memory, retries do not duplicate data, and cancellation leaves no corrupt project reference.

---

## 5. Work package M1.3 — Inspect media and select audio streams

Use ffprobe JSON output for format and stream inspection. Its documented stream-selection and output facilities support this workflow. [ffprobe documentation](https://ffmpeg.org/ffprobe.html)

### 5.1 Probe execution

1. Run ffprobe against the completed local upload.
2. Invoke it using an argument array.
3. Disable standard-input interaction.
4. Restrict input handling to local media.
5. Apply a 30-second initial probe timeout.
6. Bound captured stdout and stderr.
7. Parse JSON using a validated schema.
8. Retain only needed metadata.
9. Save FFmpeg/ffprobe version information.

### 5.2 Metadata to collect

At container level:

- Recognized format.
- Estimated duration.
- Total byte count.
- Relevant title/artist tags.

For every audio stream:

- Global stream index.
- Codec.
- Sample rate.
- Channel count.
- Channel layout.
- Language.
- Title.
- Default disposition.
- Estimated duration.
- Start timestamp.
- Relevant padding/delay metadata when exposed.

### 5.3 Stream-selection behavior

1. If no audio stream exists, fail with `NO_AUDIO_STREAM`.
2. If one exists, select it automatically.
3. If several exist, present a selection dialog.
4. Display stream language, title, codec, and channels.
5. Highlight the default-disposition stream as the suggested choice.
6. Require confirmation for multiple audio streams.
7. Store the exact global stream index.
8. Decode only that stream.

An MP3 containing cover art must still be treated as one audio source; the attached image is not another candidate audio stream.

### 5.4 Input support policy

Initial tested set:

- WAV.
- FLAC.
- MP3.
- AAC/M4A.
- Ogg Vorbis.
- Opus.
- AIFF.
- MP4.
- MOV.
- MKV.
- WebM.

Other self-contained files may work if the installed FFmpeg build supports them, but they should not be listed as tested until covered.

### 5.5 Reject unsupported cases explicitly

Reject:

- Files with no usable audio.
- Encrypted/protected audio.
- Playlist files requiring external resources.
- Inputs that attempt network retrieval.
- Unsupported channel layouts without an explicit mapping.
- Midstream sample-rate or channel-layout changes that cannot be represented by the fixed canonical format.

For the initial supported path:

- Sample rates: 8 kHz–192 kHz.
- Channels: 1–8.

These are application limits, not claims about FFmpeg’s maximum capabilities.

**Acceptance:** the user hears and sees the selected audio stream, regardless of video or attachment streams in the container.

---

## 6. Work package M1.4 — Add durable media jobs

### 6.1 Extend the worker protocol

Introduce worker protocol version 2 with:

- `run`.
- `progress`.
- `completed`.
- `failed`.
- `cancel`.
- `cancelled`.

Keep version negotiation explicit.

### 6.2 Supported job types

- Probe.
- Canonical decode.
- Monitoring downmix.
- Playback-rate conversion.
- Waveform generation.

No model jobs are implemented yet.

### 6.3 Durable job states

Use:

```text
queued → running → completed
                 → failed
                 → cancelling → cancelled
```

On application restart:

- `queued` remains queued.
- Previously `running` or `cancelling` becomes `interrupted`.
- Interrupted operations can be restarted from a safe boundary.
- Completed assets remain reusable.

### 6.4 Ownership rules

1. The backend owns SQLite writes.
2. Workers receive validated paths and parameters.
3. Workers write only into assigned staging locations.
4. Workers emit progress and result metadata.
5. The backend verifies and publishes completed outputs.
6. Workers never directly attach an asset to a project.

### 6.5 Scheduling

1. Run one media-processing job at a time initially.
2. Permit playback and API requests while a job runs.
3. Bound numerical/FFmpeg thread use to four threads initially.
4. Run CPU-heavy waveform work outside the API process.
5. Prioritize user-requested playback preparation over optional cache rebuilding.
6. Do not cancel a valid shared preparation job merely because one browser tab closes.

### 6.6 Progress reporting

Report stages separately:

- Transferring.
- Verifying.
- Inspecting.
- Decoding.
- Preparing playback.
- Building waveform.
- Ready.

Use determinate percentages only when a reliable denominator exists.

Unknown-duration files show processed time/bytes and an indeterminate progress indicator.

### 6.7 Cancellation and process cleanup

1. Set cancellation state.
2. Notify the worker.
3. Terminate its owned FFmpeg subprocess gracefully.
4. Wait up to five seconds.
5. Force termination if necessary.
6. Reap both subprocesses.
7. Remove incomplete staging output.
8. Retain the original committed source file for retry.
9. Never publish partial PCM as a completed asset.

**Acceptance:** a failed or cancelled job cannot corrupt a previously completed project asset.

---

## 7. Work package M1.5 — Decode canonical audio

FFmpeg supports explicit stream mapping and PCM conversion. Use these facilities to select only the requested audio and avoid unintended video processing. [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html)

### 7.1 Canonical representation

Store:

- Original selected-stream sample rate.
- Original channel count and layout.
- Interleaved float32 little-endian samples.
- Separate metadata containing frame count and provenance.

Use a raw PCM file rather than relying on ordinary WAV’s size limits.

### 7.2 Decode sequence

1. Confirm the selected stream still matches the probe result.
2. Estimate output storage requirements.
3. Check free space.
4. Create a staging PCM file.
5. Start FFmpeg with explicit audio-stream mapping.
6. Exclude video, subtitles, and data outputs.
7. Convert sample format to float32.
8. Preserve source sample rate.
9. Preserve channel count and channel order.
10. Write PCM incrementally.
11. Capture machine-readable progress.
12. Check the process exit code.
13. Validate output frame alignment.
14. Count actual decoded frames.
15. Check for nonfinite samples.
16. Compute the PCM content hash.
17. Publish the completed audio asset.
18. Attach it to the project transactionally.

### 7.3 Timing origin and encoder delay

Define project time zero as the start of the decoded selected audio stream after decoder-supported priming/padding handling.

1. Retain original container start-time metadata.
2. Do not prepend silence merely because video began earlier.
3. Let the decoder apply supported codec delay/padding metadata.
4. Do not apply the same trim a second time.
5. Store exact decoded length.
6. Use compressed-file metadata only as an estimate.
7. Test known MP3, AAC, and Opus delay cases.

### 7.4 Timestamp discontinuities

For internal discontinuities:

1. Normalize the selected stream’s first decoded timestamp to zero.
2. Preserve later forward timestamp gaps as silence.
3. Trim overlapping frames caused by backward discontinuities.
4. Use no gradual speed correction.
5. Record a timing-repair warning when this policy changes the continuous sample sequence.
6. Test gap and overlap fixtures against explicit expected output.

FFmpeg’s resampler distinguishes padding/trimming from continuous timestamp compensation; configure and verify the selected behavior rather than accepting an undocumented default. [FFmpeg resampler](https://ffmpeg.org/ffmpeg-resampler.html)

### 7.5 Sample-value handling

1. Preserve finite float values above `1.0` or below `-1.0`.
2. Do not normalize or clip canonical audio.
3. Reject nonfinite decoded samples with an explicit diagnostic.
4. Record maximum absolute amplitude for waveform and clipping information.
5. Keep monitoring volume separate from stored sample values.

### 7.6 Empty and damaged inputs

- Zero decoded frames: fail with `EMPTY_AUDIO`.
- Decode process failure: fail and preserve the original for inspection.
- Truncated media producing decoder errors: do not silently declare a clean import.
- Valid silence: accept normally.
- Duration mismatch: use decoded duration and record the discrepancy.

**Acceptance:** canonical audio has a reproducible sample count, preserved channel structure, and a defined time origin.

---

## 8. Work package M1.6 — Asset publication, hashing, and disk budgeting

### 8.1 Content-addressed storage

Store completed assets under app-generated hash-based locations.

Maintain two identities:

1. **Content hash:** the actual asset bytes.
2. **Transformation key:** input hash plus stream, parameters, and implementation versions.

### 8.2 Transformation key contents

Canonical decoding includes:

- Original-file hash.
- Stream index.
- Decoder-profile version.
- Relevant FFmpeg build identity.
- Timestamp policy.
- Output sample format.
- Channel policy.

Derived playback includes:

- Canonical hash.
- Downmix matrix/version.
- Target sample rate.
- Resampler settings/version.

### 8.3 Publication sequence

1. Write staging output on the destination filesystem.
2. Validate metadata and size.
3. Compute/verify the hash.
4. Flush and close the file.
5. Atomically rename into final storage.
6. Insert asset metadata.
7. Attach project references in a database transaction.
8. Mark the job complete only after the references commit.

If the process crashes between file publication and database commit, the result is an unreferenced complete asset, not a broken project.

### 8.4 Deduplication

1. Reuse an identical original-file asset.
2. Reuse a canonical asset only when the transformation key matches.
3. Reuse waveform caches by canonical hash and cache version.
4. Reuse playback representations by source transform and target rate.
5. Never reuse based only on filename or file size.

### 8.5 Disk estimate

Canonical PCM bytes:

```text
frame_count × channel_count × 4
```

For one hour of stereo 48 kHz float32 audio, this is approximately 1.38 GB in decimal units.

Before processing, budget:

- Retained original.
- Canonical PCM.
- Required monitoring/playback representation.
- Waveform caches.
- Temporary publication overhead.
- A free-space reserve of 2 GiB.

Use duration estimates conservatively and monitor free space during output writing.

### 8.6 Cache cleanup boundary

In Milestone 1:

- Preserve source and canonical assets.
- Permit explicit deletion of rebuildable waveform/playback caches.
- Do not add automatic broad asset garbage collection.
- Remove only identified incomplete staging outputs after recovery.
- Preserve ambiguous recovery files until their ownership is resolved.

**Acceptance:** reopening reuses existing assets, and disk-space failures leave a recoverable project.

---

## 9. Work package M1.7 — Monitoring channels and playback-rate representations

### 9.1 Mono and stereo

- Mono canonical audio remains mono.
- Stereo remains stereo.
- Mono is duplicated to both output speakers at playback.
- Do not create a stereo disk copy just to duplicate mono.

### 9.2 Multichannel preservation

1. Preserve all original channels in canonical storage.
2. Display channel labels.
3. Generate a separate stereo monitoring representation.
4. Record the downmix matrix.
5. Make the chosen monitoring mode visible in source information.

### 9.3 Explicit downmix rules

For standard layouts:

- Front left contributes to left.
- Front right contributes to right.
- Center contributes to both at coefficient `0.7071`.
- Left surround/rear contributes to left at `0.7071`.
- Right surround/rear contributes to right at `0.7071`.
- LFE contributes to both at `0.5`.

Normalize each matrix row by at least its sum of absolute coefficients, so full-scale aligned input channels do not exceed full scale solely due to summation.

This is a documented monitoring transform. It does not normalize the canonical source.

For unknown layouts:

1. Preserve the canonical channels.
2. Require the user to select left/right source channels for monitoring.
3. Do not guess speaker identities from channel count alone.

FFmpeg’s `pan` filter can implement explicit channel matrices. [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html#pan)

### 9.4 Browser sample-rate negotiation

1. Create/resume `AudioContext` after a user gesture.
2. Read its actual `sampleRate`.
3. Compare with the monitoring/source representation.
4. Reuse the source when rates match.
5. Otherwise request a cached representation at the context rate.
6. Display “Preparing playback” while conversion runs.
7. Begin playback only when the representation is complete and validated.

Do not assume browsers honor a requested sample rate.

### 9.5 Resampling method

Use FFmpeg’s built-in SWR resampler with a versioned quality profile:

- Float32 output.
- Filter size 64.
- Exact rational handling enabled.
- No dither for float output.
- No asynchronous tempo correction.

Resample the continuous representation once, then serve ranges from it. Do not independently resample one-second chunks, which can introduce boundary artifacts and inconsistent sample counts.

### 9.6 Time mapping

Map playback frames to project frames using:

```text
project_position = playback_frame × project_rate / playback_rate
```

1. Retain fractional position internally.
2. Round only for source-sample editing/readout boundaries.
3. Use actual resampled length for EOF.
4. Clamp final display to canonical duration.
5. Record any endpoint difference caused by rational rounding.
6. Test impulses near start, middle, and end.

**Acceptance:** 44.1 kHz and 48 kHz sources play with correct pitch and duration under either browser output rate.

---

## 10. Work package M1.8 — Build the waveform pyramid

### 10.1 Cache structure

For every canonical channel:

- Base bucket: 64 sample frames.
- Successive levels: 256, 1,024, 4,096, and so forth.
- Bucket contents: signed minimum and maximum.
- Tile size: 4,096 buckets.
- Values: float32 little-endian.
- Metadata: cache version, source hash, sample rate, frame count, channel count, level sizes.

### 10.2 Generation algorithm

1. Read canonical PCM in bounded blocks.
2. Reshape frames by channel.
3. Carry incomplete base buckets between blocks.
4. Compute per-channel signed minima/maxima.
5. Write completed base buckets.
6. Aggregate groups of four into the next level.
7. Carry incomplete groups between blocks.
8. Flush final partial groups at EOF.
9. Record the true frame count of final partial buckets.
10. Continue until the coarsest level fits into one tile.

Do not pad incomplete buckets with zeros, because that changes the extrema of all-positive or all-negative intervals.

### 10.3 Progressive publication

1. Generate peaks after canonical audio is committed.
2. Publish only complete immutable tiles.
3. Mark available tile ranges in cache metadata.
4. Permit visible completed regions to render while other tiles are pending.
5. Show pending regions as unloaded, not silence.
6. Publish the final manifest when all levels finish.
7. Allow playback while waveform generation continues.

### 10.4 Cache validation

Verify:

- Source hash.
- Cache version.
- Expected tile byte lengths.
- Level bucket sizes.
- Channel count.
- Final bucket counts.
- Finite extrema.
- `minimum ≤ maximum`.

Corrupt waveform caches can be rebuilt without reimporting the source.

### 10.5 Memory bound

Target waveform-worker working arrays below 256 MiB.

Use chunked reads and bounded aggregation buffers rather than loading the entire PCM file.

**Acceptance:** waveform extrema remain correct across block boundaries, channel boundaries, partial buckets, and very long files.

---

## 11. Work package M1.9 — Define media HTTP interfaces

All routes remain authenticated and loopback-only.

### 11.1 Import routes

| Route | Purpose |
|---|---|
| `POST /api/v1/imports` | Create upload session |
| `PUT /api/v1/imports/{id}/chunks?offset=…` | Upload next chunk |
| `GET /api/v1/imports/{id}` | Transfer/probe state |
| `POST /api/v1/imports/{id}/complete` | Finalize transfer and queue probe |
| `POST /api/v1/imports/{id}/select-stream` | Choose audio stream and queue decode |
| `POST /api/v1/imports/{id}/cancel` | Cancel import |

### 11.2 Job routes

- `GET /api/v1/jobs/{id}`.
- `POST /api/v1/jobs/{id}/cancel`.

Poll active jobs approximately every 500 ms while the application is visible, backing off to two seconds when hidden.

### 11.3 Asset routes

| Route | Purpose |
|---|---|
| `GET /api/v1/assets/{id}/metadata` | Audio/cache metadata |
| `GET /api/v1/assets/{id}/pcm?start_frame=…&frame_count=…` | Bounded raw PCM |
| `GET /api/v1/assets/{id}/peaks/manifest` | Waveform levels and availability |
| `GET /api/v1/assets/{id}/peaks?level=…&tile=…` | One binary peak tile |
| `POST /api/v1/projects/{id}/playback-preparations` | Resolve/create suitable playback representation |

### 11.4 PCM response contract

Return:

- Interleaved `f32le` bytes.
- Representation ID.
- Sample rate.
- Channel count.
- Start frame.
- Actual returned frame count.
- EOF indicator.
- Representation version/hash.

Rules:

1. Reject negative/noninteger positions.
2. Limit one response to 8 MiB.
3. Return only complete frames.
4. Clip a valid request at EOF.
5. Return zero frames and EOF at exactly the end.
6. Reject starts beyond the end.
7. Never return metadata from one representation with bytes from another.

Use frame-based query parameters consistently; do not mix them with HTTP byte-range semantics.

### 11.5 Binary parsing

1. Validate expected byte length.
2. Read little-endian values explicitly.
3. Reject truncated bodies.
4. Reject stale representation IDs.
5. Deinterleave in a browser worker.
6. Transfer resulting arrays to the audio/rendering path.
7. Do not parse PCM on the React render path.

**Acceptance:** every PCM and waveform request is bounded, validated, and tied to an immutable asset.

---

## 12. Work package M1.10 — Render the waveform editor

### 12.1 Layout

Add:

- Project/source header.
- Import progress and source information.
- Transport controls.
- Overview waveform.
- Main waveform view.
- Time ruler.
- Marker lane.
- Selection readout.
- Horizontal scrollbar.
- Channel display controls.
- Vertical amplitude controls.

### 12.2 Coordinate transform

Maintain one viewport:

- `start_frame`.
- `frames_per_css_pixel`.
- Viewport width.
- Channel lane heights.

Mapping:

```text
x = (frame - start_frame) / frames_per_css_pixel
frame = start_frame + x × frames_per_css_pixel
```

All ruler labels, markers, selections, and playhead positions use this transform.

### 12.3 Canvas layers

Use separate layers for:

1. Waveforms.
2. Grid/ruler annotations.
3. Selection.
4. Markers.
5. Playhead.

A playhead update must not redraw all waveform samples.

### 12.4 Device-pixel handling

1. Measure CSS canvas size.
2. Allocate backing pixels using device-pixel ratio.
3. Apply the corresponding transform.
4. Rebuild backing stores after resize or display-scale changes.
5. Keep mouse coordinates in CSS pixels.

### 12.5 Resolution selection

1. Select a peak level producing approximately one to two buckets per CSS pixel.
2. Fetch visible tiles and one adjacent tile in each direction.
3. Cancel obsolete tile requests after large navigation changes.
4. Cache tiles with a byte-bounded LRU.
5. Switch to actual PCM at fewer than 64 frames per pixel.
6. Aggregate exact visible PCM ranges when several frames still occupy a pixel.
7. Draw sample points/lines when frames become individually visible.

### 12.6 Channel rendering

- Stereo: separate left/right lanes by default.
- Mono: one lane.
- Multichannel: stacked labeled lanes.
- Allow lane collapse without changing audio.
- Use vertical virtualization for lanes outside the visible editor.

### 12.7 Amplitude display

1. Center zero in each lane.
2. Default scale to ±1.
3. Allow values outside ±1 to be revealed through vertical zoom.
4. Mark samples/extrema beyond full scale.
5. Label vertical controls as display amplitude.
6. Never alter playback gain through waveform zoom.

### 12.8 Empty and pending states

Distinguish:

- No source imported.
- Audio decoding.
- Waveform cache pending.
- Missing/corrupt cache.
- Valid silent audio.
- Unsupported input.

**Acceptance:** the waveform remains aligned with markers and the ruler at every zoom level.

---

## 13. Work package M1.11 — Navigation, zoom, and selection

### 13.1 Horizontal zoom

1. Support zoom buttons.
2. Support `+` and `-`.
3. Support Ctrl/Cmd-wheel zoom.
4. Anchor pointer zoom under the pointer.
5. Anchor keyboard zoom at the playhead.
6. Provide Fit Song.
7. Provide Fit Selection.
8. Permit a maximum zoom of eight CSS pixels per source frame.
9. Clamp the viewport to valid project boundaries.
10. Preserve fractional viewport coordinates for smooth movement.

### 13.2 Panning

1. Support horizontal scrollbar dragging.
2. Support Shift-wheel horizontal pan.
3. Support overview-window dragging.
4. Clamp at source boundaries.
5. Suspend playhead following after manual pan.
6. Show a return-to-playhead button.

### 13.3 Vertical zoom

1. Provide per-lane amplitude controls.
2. Offer linked scaling across source channels.
3. Support reset to ±1.
4. Set an initial scale range from 0.25× to 16×.
5. Persist the selected display scale.

### 13.4 Selection semantics

1. Pointer-down begins a possible click/drag.
2. Movement beyond three CSS pixels starts range selection.
3. A click seeks.
4. A drag selects without automatically seeking.
5. Store selection as source-frame boundaries.
6. Normalize reverse drags.
7. Clamp boundaries to the source.
8. Allow boundary-handle adjustments.
9. Escape clears selection.
10. Show start, end, and duration.
11. Provide “Seek to selection start.”

Looping is not introduced here.

### 13.5 Time ruler

1. Display source time only.
2. Select sensible tick intervals for current zoom.
3. Avoid overlapping labels.
4. Display milliseconds when useful.
5. Expose exact frame position in an inspector/readout at high zoom.
6. Do not show placeholder bars or beats before musical analysis exists.

**Acceptance:** precise selection and navigation work identically at overview and sample-level zoom.

---

## 14. Work package M1.12 — Implement the AudioWorklet transport

AudioWorklet processing runs on the audio-rendering path. Its implementation must use the actual output-block length rather than assuming a fixed block size forever. [AudioWorklet processing](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor/process)

### 14.1 Transport ownership

The audio engine owns:

- Current source position.
- Current playback-representation position.
- Playing/paused state.
- Buffer consumption.
- End-of-file behavior.
- Seek generations.

React observes transport state; it does not advance audio time.

### 14.2 Public frontend interface

Provide:

- `loadSource(...)`.
- `play()`.
- `pause()`.
- `stop()`.
- `seek(projectFrame)`.
- `setOutputGain(gain)`.
- `dispose()`.
- State subscription.

Do not expose raw worklet messages to UI components.

### 14.3 Transport states

Use:

- `unloaded`.
- `preparing`.
- `paused`.
- `playing`.
- `seeking`.
- `buffering`.
- `ended`.
- `error`.

Keep `desiredPlaying` separate from actual state so a seek or underrun can temporarily pause output without losing user intent.

### 14.4 Playback sequence

1. Receive Play from a user gesture.
2. Create/resume the AudioContext.
3. Resolve the appropriate playback representation.
4. Initialize the transport.
5. Fill at least two seconds of buffer, or the remaining file if shorter.
6. Start on an acknowledged render boundary.
7. Consume PCM using the worklet.
8. Send position anchors to the main thread.
9. Continue prefetching.
10. Stop exactly at the valid representation endpoint.

### 14.5 Pause and stop

Pause:

- Ramp monitoring output down over approximately five milliseconds.
- Stop consumption.
- Preserve the acknowledged position.

Stop:

- Pause output.
- Reset the source position to zero.
- Invalidate pending seek/play messages.
- Keep reusable cached data.

### 14.6 Seek sequence

1. Convert requested source position to playback position.
2. Increment transport-generation ID.
3. Request worklet stop/flush.
4. Wait for flush acknowledgment.
5. Abort obsolete fetch requests.
6. Clear generation-specific buffers.
7. Fetch around the new position.
8. Refill the buffer.
9. Start only if `desiredPlaying` is true.
10. Discard late responses/messages from older generations.

### 14.7 Audio-thread constraints

The processing callback must:

- Avoid network calls.
- Avoid filesystem calls.
- Avoid promises.
- Avoid logging.
- Avoid unbounded allocations.
- Avoid locks or waits.
- Fill output deterministically.
- Emit silence when data is unavailable.

Control messages can prepare data structures outside the actual processing callback.

### 14.8 Output gain

1. Add one monitoring-volume control.
2. Use short gain ramps.
3. Keep canonical samples unchanged.
4. Default to unity gain.
5. Indicate potential clipping.
6. Do not add automatic normalization.

**Acceptance:** play, pause, stop, and repeated seeking work without drift or stale audio from earlier seeks.

---

## 15. Work package M1.13 — Buffering and browser compatibility

### 15.1 Shared-memory path

When cross-origin isolation and SharedArrayBuffer are available:

1. Use a single-producer/single-consumer ring buffer.
2. Let a browser worker fetch and deinterleave PCM.
3. Let the worklet consume frames.
4. Use atomic indices and generation metadata.
5. Never call blocking waits in the audio thread.
6. Reset indices only after a transport flush acknowledgment.

### 15.2 Transferable-buffer fallback

When shared memory is unavailable:

1. Fetch bounded PCM chunks in a browser worker.
2. Transfer channel arrays to the worklet.
3. Queue a bounded number of chunks.
4. Acknowledge consumed chunks.
5. Stop sending when the queue reaches its high-water mark.
6. Apply identical generation and EOF rules.
7. Test this path explicitly even on browsers supporting shared memory.

### 15.3 Buffer defaults

- Network chunk: approximately one second.
- Initial prebuffer: two seconds.
- Steady lookahead: eight seconds.
- Retained history: two seconds.
- Total retained PCM: at most 12 seconds per active playback representation.

For stereo 48 kHz float32 PCM, 12 seconds is approximately 4.6 MB before bookkeeping.

### 15.4 Underrun behavior

1. Detect insufficient frames.
2. Ramp to silence where possible.
3. Enter buffering.
4. Freeze source advancement while no source frames are consumed.
5. Refill to the start threshold.
6. Resume only if play is still desired.
7. Record the underrun in local diagnostics.
8. Do not skip unplayed source frames to catch up with wall time.

### 15.5 Browser suspension

1. Listen for AudioContext state changes.
2. Freeze extrapolated playhead position while suspended.
3. Preserve desired playback state.
4. Require a user gesture if the browser requires it for resumption.
5. On tab visibility return, redraw from actual transport state.
6. Do not replay missed animation frames.

### 15.6 Audio-device changes

1. Detect context failure or closure.
2. Retain the last acknowledged source position.
3. Recreate context if necessary.
4. Re-read the actual sample rate.
5. Resolve a compatible playback representation.
6. Refill buffers.
7. Resume only under the browser’s permitted gesture rules.

**Acceptance:** buffering never causes time to advance over unheard audio, and both shared-memory and transferable-buffer paths function.

---

## 16. Work package M1.14 — Synchronized readout and follow-playhead

### 16.1 Position anchors

The worklet reports:

- Transport generation.
- AudioContext render-frame position.
- Corresponding source position.
- Playback state.
- Buffered extent.

Send anchors approximately 20 times per second, not every audio block.

### 16.2 Audible-position estimate

1. Use `AudioContext.getOutputTimestamp()` where available.
2. Map the output device’s context timestamp into the matching transport segment.
3. Retain recent segments across seeks and state changes.
4. Fall back to a documented latency estimate if output timestamps are unavailable.
5. Clamp interpolation to known valid transport segments.
6. Freeze extrapolation when paused, buffering, or suspended.

The output timestamp API relates audio-context time to performance time; it is more suitable for audible-position estimation than a UI timer alone. [getOutputTimestamp](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/getOutputTimestamp)

### 16.3 Readout

Display:

```text
01:32.481 / 05:13.270
```

Also show exact source frame in the inspector.

Do not display chord, note, or bar placeholders in Milestone 1.

### 16.4 Follow-playhead

1. Default to page-follow behavior.
2. Keep the viewport still while the playhead is within the visible area.
3. Advance the viewport when the playhead reaches approximately 80% of its width.
4. Position the playhead near 20% after the move.
5. Suspend following after manual navigation.
6. Allow immediate reenable through a visible control.
7. Persist the preference.

### 16.5 UI update strategy

1. Draw the playhead using requestAnimationFrame.
2. Read the latest transport anchor.
3. Interpolate only for display.
4. Update text at approximately 20 Hz.
5. Avoid storing every playhead update in React application state.
6. Never use UI interpolation to control playback.

**Acceptance:** waveform cursor and time readout follow audible playback without accumulating drift.

---

## 17. Work package M1.15 — Markers, persistence, and undo/redo

### 17.1 Marker model

Each marker contains:

- UUID.
- Project ID.
- Source-frame position.
- Label.
- Color.
- Creation/update timestamps.

Allow markers at zero and exactly at project end.

### 17.2 Marker operations

1. Add at playhead.
2. Add at a selected ruler position.
3. Rename.
4. Move by dragging.
5. Enter an exact time/frame.
6. Change color.
7. Delete.
8. Navigate to previous/next marker.
9. Select marker without automatically editing it.
10. Double-click marker to seek.

### 17.3 Commands

Add the planned project-command endpoint and support:

- Add marker.
- Update marker.
- Delete marker.
- Change selection.
- Change viewport/display settings.

Each command includes:

- Command ID.
- Idempotency key.
- Base project revision.
- Before/after state or validated operation payload.

### 17.4 Command behavior

1. Validate revision.
2. Apply the edit transactionally.
3. Record history.
4. Increment revision.
5. Return the resulting state.
6. Reject stale commands with `409`.
7. Group a drag into one command.
8. Group continuous zoom/pan gestures.
9. Clear the active redo branch after a new edit.
10. Do not put continuous playback position updates in undo history.

### 17.5 Working autosave

Persist:

- Source/stream metadata.
- Asset references.
- Markers.
- Selection.
- Viewport.
- Channel display settings.
- Monitoring volume.
- Last source position.
- Follow-playhead preference.

Rules:

1. Commit semantic commands immediately.
2. Debounce view-state persistence by approximately one second.
3. Save last playhead position on pause and every five seconds during playback.
4. Serialize writes per browser tab.
5. Flush on explicit project navigation.
6. Treat page-close requests as best effort.
7. Display unsaved/pending state until acknowledged.

### 17.6 Reopen

1. Load project metadata.
2. Validate canonical asset availability.
3. Restore markers and view.
4. Restore last playhead position.
5. Remain paused.
6. Use existing waveform caches.
7. Rebuild missing waveform caches only.
8. Reuse a matching playback representation.
9. Never automatically reimport the original.

### 17.7 Recovery

- Interrupted upload: offer resume after file reselection.
- Interrupted decode: restart from retained original.
- Interrupted waveform generation: rebuild missing cache output.
- Missing canonical asset: report the missing source representation and offer regeneration from the retained original.
- Missing original but valid canonical asset: allow playback with a provenance warning.

**Acceptance:** annotations and working state survive restart, and introduced manual edits can be undone and redone.

---

## 18. Work package M1.16 — Test corpus and automated verification

### 18.1 Synthetic fixtures

Create deterministic, locally generated fixtures:

1. Mono sine wave.
2. Stereo tones with different left/right frequencies.
3. Impulses at known frames.
4. Silence.
5. DC-offset signal.
6. Full-scale and above-full-scale float samples.
7. Short signal ending inside a peak bucket.
8. Signal crossing processing-block boundaries.
9. 44.1 kHz source.
10. 48 kHz source.
11. 96 kHz source.
12. Standard 5.1 and 7.1 channel impulses.
13. Known timestamp gap.
14. Known timestamp overlap.
15. Long 60-minute test recording.

Generate long fixtures during testing; do not commit large audio files.

### 18.2 Format fixtures

Using available encoders, generate:

- PCM WAV and float WAV.
- FLAC.
- MP3 CBR and VBR.
- AAC/M4A.
- Ogg Vorbis.
- Opus.
- AIFF.
- Video containers with one audio stream.
- Video containers with multiple labeled audio streams.
- Video without audio.
- Audio with cover art.

Record which codec/container combinations the installed build can actually encode/decode.

### 18.3 Import tests

Verify:

- Unicode and space-containing filenames.
- Misleading extensions.
- Duplicate files.
- Chunk retry.
- Wrong chunk offset.
- Wrong chunk hash.
- Interrupted transfer.
- Resume with correct file.
- Resume with incorrect file.
- Cancellation.
- Oversized input.
- Low disk space.
- No audio.
- Probe timeout.
- Decode failure.

### 18.4 PCM correctness tests

1. Compare lossless decoded samples with expected normalized PCM.
2. Verify channel order.
3. Verify exact frame counts.
4. Verify source time zero.
5. Verify no double encoder-delay trimming.
6. Verify downmix coefficients.
7. Verify above-full-scale finite values survive.
8. Verify EOF range behavior.
9. Verify binary byte ordering.
10. Verify no partial frames are served.

For lossy formats, use timing and signal-tolerance comparisons rather than byte equality.

### 18.5 Waveform tests

Check:

- Signed minima/maxima.
- Every channel.
- Tile boundaries.
- Final partial bucket.
- All-positive/all-negative signals.
- Silence.
- Values outside ±1.
- Consistency between peak and sample rendering.
- Cache invalidation after transform-version changes.
- Corrupt-cache recovery.

### 18.6 Transport tests

Verify:

- Play from zero.
- Pause/resume.
- Stop/reset.
- Seek while paused.
- Seek while playing.
- Rapid repeated seeks.
- Seek near EOF.
- Empty/final partial chunk.
- Underrun and recovery.
- Old-generation response rejection.
- Context suspension.
- Context-rate mismatch.
- Both buffering implementations.

### 18.7 Persistence tests

Verify:

- Import survives restart.
- Reopen does not rerun decode.
- Markers persist.
- View state persists.
- Undo/redo persists.
- Stale revision fails safely.
- Interrupted job recovery.
- Original user files remain unchanged.

---

## 19. Browser, performance, and listening acceptance

### 19.1 Browser coverage

Required Milestone 1 validation:

- Chromium on Linux.
- Firefox on Linux.

Also run WebKit automation when available. Actual Safari playback validation remains a later platform gate and must not be claimed from WebKit automation alone.

### 19.2 Playback timing targets

These are targets to measure:

- Digital transport has no cumulative timing drift.
- Source↔playback conversion error remains within one source frame at tested anchors.
- Foreground visual playhead is generally within 30 ms of estimated audible position.
- No increasing offset over a 30-minute playback test.
- No skipped source content during deliberate underrun tests.

Physical output latency depends on the browser, device, and audio system. Report measured conditions.

### 19.3 Responsiveness targets

On your PC:

- Cached play starts within approximately 300 ms after the user gesture.
- Cached seek resumes within approximately 500 ms.
- UI remains interactive during decoding and waveform generation.
- Visible waveform updates avoid repeated long main-thread stalls.
- Transport controls remain responsive during cache work.

First-time playback preparation is measured separately from cached playback.

### 19.4 Memory targets

- Upload handling: bounded chunks, no full-file buffering.
- Decode handling: bounded process buffers.
- Waveform computation: working arrays below 256 MiB.
- Browser waveform cache: initial 64 MiB budget.
- Browser playback PCM: bounded to the configured time window.
- Long-track memory growth must stabilize rather than scale with full recording duration.

### 19.5 Existing recordings

Use all five supplied WAV files for manual acceptance:

1. Import each without modifying the original.
2. Verify displayed duration.
3. Listen near start, middle, and end.
4. Seek repeatedly.
5. Compare waveform transients with audible events.
6. Zoom to sample-level detail.
7. Add markers.
8. Restart and reopen.
9. Confirm no import/decode rerun.
10. Record any audible artifacts.

No reference stems or annotations are required for Milestone 1.

### 19.6 Offline verification

After setup:

1. Disable external network access.
2. Launch basseparate.
3. Import a local file.
4. Decode and generate waveforms.
5. Play and seek.
6. Save working state.
7. Restart and reopen.
8. Confirm no external requests.

Browser-native `decodeAudioData()` requires complete encoded file data and resamples to the context rate, so it is not the large-file import path chosen here. [decodeAudioData](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/decodeAudioData)

---

## 20. Implementation order and completion gates

| Gate | Work packages | Required result |
|---|---|---|
| A | M1.1–M1.3 | Validated upload and correct stream selection |
| B | M1.4–M1.6 | Durable jobs, canonical PCM, atomic asset storage |
| C | M1.7–M1.9 | Monitoring representations, waveform caches, bounded media APIs |
| D | M1.10–M1.11 | Navigable multiresolution waveform editor |
| E | M1.12–M1.14 | Reliable playback and synchronized playhead |
| F | M1.15 | Persistent markers, view state, and edit history |
| G | M1.16–M1.19 | Correctness, browser, long-track, and offline validation |

### Final completion checklist

- [ ] All original user media remains unchanged.
- [ ] File picker and drag-and-drop work.
- [ ] Upload memory is bounded.
- [ ] Interrupted uploads can resume safely.
- [ ] Multiple audio streams can be selected explicitly.
- [ ] Canonical audio preserves source rate and channels.
- [ ] Decoder timing policy is tested.
- [ ] Original and decoded assets are hash-identified.
- [ ] Partial processing results are never published as complete.
- [ ] Standard multichannel downmixing is explicit and tested.
- [ ] Browser sample-rate differences preserve pitch and duration.
- [ ] Peak and sample-level waveform modes agree.
- [ ] Horizontal and vertical zoom behave independently.
- [ ] All views use one source-time transform.
- [ ] Play, pause, stop, and seek work in Chromium and Firefox.
- [ ] Seek generations prevent stale audio.
- [ ] Underruns freeze source advancement.
- [ ] Playhead and readout follow the audio clock.
- [ ] Selection and markers are editable.
- [ ] Introduced manual edits support undo/redo.
- [ ] Working projects reopen without reimport or decoding.
- [ ] Long tracks have bounded memory use.
- [ ] Offline import and playback pass.
- [ ] Failure messages identify recoverable next actions.
- [ ] Tests and documentation reflect actual supported formats.

### Handoff to Milestone 2

Deliver a working original-audio practice foundation with:

1. Immutable source and canonical assets.
2. Explicit source-time mappings.
3. Reusable PCM and waveform interfaces.
4. A transport capable of adding synchronized stems.
5. A renderer capable of adding more tracks.
6. Durable processing jobs.
7. Transactional annotation commands.
8. Verified restart and recovery behavior.
9. Recorded timing, memory, and browser measurements.
10. A clear integration point for Demucs separation, stem mixing, loops, and Signalsmith time stretching.

