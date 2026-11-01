# Analysis and practice UI contracts

These are the seams the shell task (t16) wires to the real transport, mixer,
metronome and analysis job. Panels are prop-driven and hold no audio or network
side effects of their own.

## Panels

| Panel | File | Props |
| --- | --- | --- |
| `ChordRibbon` | `panels/chords/ChordRibbon.tsx` | `chords`, `viewport`, `widthPx`, `positionSeconds`, `onSeek?` |
| `KeyBpmReadout` | `panels/chords/KeyBpmReadout.tsx` | `keyLabel`, `bpm`, `bpb?` |
| `SectionLane` | `panels/sections/SectionLane.tsx` | `sections`, `grid`, `viewport`, `widthPx`, `durationSeconds`, `positionSeconds`, `snapMode?`, `onSnapModeChange?`, `selection?`, `onChange`, `onLoop`, `onSeek?`, `player?` |
| `BarBeatOverlay` | `panels/sections/BarBeatOverlay.tsx` | `beats`, `bpb`, `viewport`, `widthPx` |
| `MixerPanel` | `panels/mixer/MixerPanel.tsx` | `stems` (`{id,name,role?}[]`), `controller` |
| `PracticePanel` | `panels/practice/PracticePanel.tsx` | `controller`, `snapMode`, `onSnapModeChange` |
| `AnalysisPanel` | `panels/analysis/AnalysisPanel.tsx` | `projectId`, `analysis`, `client`, `defaultBpb?`, `pollIntervalMs?`, `onAnalyzed?` |

All panels share the t4 `Viewport` from `panels/waveform/viewport.ts`, so the
chord ribbon, section lane and bar/beat overlay line up with the ruler and
waveform when mounted at the same `widthPx`.

When `SectionLane.player` is supplied, pressing Loop on a section calls
`setLoopRange(sectionLoopRange(section))` and `setLoopEnabled(true)` before the
`onLoop(section)` callback. The section is never removed or locked.

## State seams

- `state/chords.ts`: `normalizeChordLabel`, `normalizeChords`, `chordAt`,
  `chordBlocks`. Chordino labels become compact symbols (`C:maj` → `C`,
  `A:min7` → `Am7`, `N` → `N.C.`).
- `state/sections.ts`: `SnapMode = "bar" | "beat" | "free"`, `snapTime`,
  `snapRange`, `addSection`, `splitSection`, `resizeSection`, `renameSection`,
  `deleteSection`, `sectionAt`, `sectionLoopRange`, `draftSectionRange`,
  `uniformBeats` (tempo-only fallback when analysis has no beats).
- `state/mixer.ts`: `MixerController` (`getState`, `subscribe`, `setGain`,
  `setPan`, `setMuted`, `setSoloed`) plus `MixerState`, gain/pan clamps and the
  solo/mute audibility rules. The t16 adapter should map it to the engine's
  per-stem mix methods.
- `state/practice.ts`: `PracticeController` (`setSpeed`, `setLoopEnabled`,
  `setCountInBars`, `setMetronomeEnabled`, `setMetronomeVolume`,
  `setAccentDownbeat`) and `PracticeState`. The t16 adapter should map it to the
  transport plus the engine's metronome/count-in. Pitch shifting is not a
  user-facing practice feature.
- `state/analysis.ts`: `AnalysisSnapshot`, `AnalysisJobState`,
  `AnalysisJobClient`, `runAnalysisJob` (polling + abort).
- `state/analysisApi.ts`: `createAnalysisJobClient({ baseUrl?, fetchImpl? })`
  for the t17 endpoint. `AnalysisPanel` takes any `AnalysisJobClient`, so tests
  and the shell can inject a fake or the real client.

## Analysis job contract (t17)

`POST /api/jobs` with `{"kind":"analysis","params":{"project_id": "...", "bpb": 4}}`,
then `GET /api/jobs/{id}` until a terminal state. The job `result` is parsed as
`{cached, bpb, bpm, key, chords:[{start_seconds,end_seconds,label}], beats:[number], bars:[number]}`.
`key` is the label (`"C major"`), not the plugin's tonic number; `key_label` is
also accepted. The cached badge shows `Cached` when the result or the project
analysis says `cached`, `Fresh` after a fresh run, and `Not analysed` before
that.

## Test doubles

`state/fakeMixer.ts` and `state/fakePractice.ts` implement the controllers with a
`calls` log and a `sync()` method for engine-reported changes; component tests
use them the same way the t16 adapter will satisfy the interfaces.
