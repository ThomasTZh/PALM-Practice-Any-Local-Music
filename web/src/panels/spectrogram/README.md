# Spectrogram

The pane is a drop-in child of the shared timeline container. It takes the same
`viewport`, `widthPx` and `positionSeconds` as the ruler and waveform pane, so
the time axis, zoom and playhead line up without any extra synchronisation.

```tsx
import { createRangedPcmLoader } from "../../spectrogram";
import { SpectrogramPane } from "./SpectrogramPane";

<SpectrogramPane
    projectId={project.id}
    viewport={viewport}
    widthPx={VIEW_WIDTH}
    sampleRate={project.asset.sampleRate}
    positionSeconds={playerState.positionSeconds}
    loadPcm={createRangedPcmLoader({ projectId: project.id })}
    defaultCollapsed={false}
/>;
```

- `loadPcm` is the only data dependency: a `(startFrame, endFrame, signal?) =>
Promise<PcmChunk>` loader. `createRangedPcmLoader` matches the server's
  `/api/projects/{id}/pcm` endpoint, checks the format headers and downmixes to
  mono.
- `engine` is optional and exists for tests; by default the pane creates the
  module Web Worker (`spectrogram.worker.ts`) and transfers the PCM buffer to
  it. The UI thread never runs an FFT.
- The image is cached per `(start seconds, width, FFT size)` for the lifetime of
  the mounted pane (and reset when `projectId` changes).
- Collapsing hides only the body. The header stays, the pane's width does not
  change, and nothing above it in the timeline moves.
- Exports: `SpectrogramPane`, `SpectrogramPaneProps`; DSP and loader helpers are
  in `web/src/spectrogram/index.ts`.
