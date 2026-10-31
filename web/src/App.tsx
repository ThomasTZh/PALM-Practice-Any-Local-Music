import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AnalysisPanel } from "./panels/analysis";
import { ChordRibbon } from "./panels/chords";
import { LibraryPanel } from "./panels/library/LibraryPanel";
import { MixerPanel } from "./panels/mixer";
import { PracticePanel } from "./panels/practice";
import { TimeRuler } from "./panels/ruler/TimeRuler";
import { SectionLane } from "./panels/sections";
import { SpectrogramPane } from "./panels/spectrogram/SpectrogramPane";
import { TransportPanel } from "./panels/transport/TransportPanel";
import { WaveformPane, type Lane } from "./panels/waveform/WaveformPane";
import { hasSelection, type Selection } from "./panels/waveform/selection";
import {
  fitViewport,
  zoomToSelection as zoomViewportToSelection,
  zoomViewport,
  type Viewport,
} from "./panels/waveform/viewport";
import { createRangedPcmLoader, type PcmLoader } from "./spectrogram";
import type { AnalysisJobClient, AnalysisSnapshot } from "./state/analysis";
import { createAnalysisJobClient } from "./state/analysisApi";
import {
  runSeparationJob,
  type SeparationJobClient,
  type SeparationJobState,
} from "./state/separation";
import { createSeparationJobClient } from "./state/separationApi";
import { formatPosition } from "./state/format";
import { createLocalStudioRuntime } from "./state/localStudio";
import { clampLoopRangeToDuration, type StudioPlayer } from "./state/player";
import {
  barTimesFromGrid,
  buildServerState,
  createShellApi,
  type ShellApi,
  type StudioProject,
} from "./state/project";
import {
  uniformBeats,
  type BeatGrid,
  type Section,
  type SnapMode,
} from "./state/sections";
import {
  applyStudioRuntimeSnapshot,
  captureStudioRuntime,
  createShellTransport,
  type ShellTransport,
  type StudioRuntime,
} from "./state/studioRuntime";
import { useMixerState } from "./state/useMixerState";
import { usePlayerState } from "./state/usePlayerState";
import { usePracticeState } from "./state/usePracticeState";

/** Fixed logical timeline width; smaller screens scroll it inside the stage. */
export const VIEW_WIDTH = 940;

export interface AppProps {
  api?: ShellApi;
  transport?: ShellTransport;
  analysisClient?: AnalysisJobClient;
  separationClient?: SeparationJobClient;
  createPcmLoader?: (projectId: string) => PcmLoader;
  autosaveDelayMs?: number;
  separationPollIntervalMs?: number;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: string }).name === "AbortError"
  );
}

function titleCase(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);
}

const FALLBACK_GRID = {
  bpm: 120,
  meter: { numerator: 4, denominator: 4 },
  offsetSeconds: 0,
};

function sectionGrid(project: StudioProject | null): BeatGrid | null {
  if (project === null) {
    return null;
  }
  if (project.analysis !== null && project.analysis.beats.length > 0) {
    return { beats: project.analysis.beats, bpb: project.analysis.bpb };
  }
  return uniformBeats(project.grid ?? FALLBACK_GRID, project.durationSeconds);
}

function applyRestoredState(
  runtime: StudioRuntime,
  project: StudioProject,
): void {
  const { state, loopRange, positionSeconds, mixer } = project.restored;
  runtime.practice.setSpeed(state.speed);
  runtime.practice.setPitchSemitones(state.pitchSemitones);
  runtime.practice.setCountInBars(state.countInBars);
  runtime.practice.setMetronomeVolume(state.metronomeVolume);
  runtime.practice.setMetronomeEnabled(state.metronomeEnabled);
  runtime.practice.setAccentDownbeat(state.accentDownbeat);
  if (loopRange !== null) {
    runtime.player.setLoopRange(loopRange);
    runtime.practice.setLoopEnabled(true);
  }
  const channels = runtime.mixer.getState();
  for (const [channelId, channel] of Object.entries(mixer)) {
    if (!(channelId in channels)) {
      continue;
    }
    runtime.mixer.setGain(channelId, channel.gainDb);
    runtime.mixer.setPan(channelId, channel.pan);
    runtime.mixer.setMuted(channelId, channel.muted);
    runtime.mixer.setSoloed(channelId, channel.soloed);
  }
  runtime.player.seek(positionSeconds);
}

/**
 * Studio shell. It owns view state (project, viewport, selection, sections and
 * snap mode) and mounts the analysis and practice panels. Playback, mixer and
 * practice state come from the runtime factory, so the shell never imports the
 * audio engine directly.
 */
export function App({
  api: apiProp,
  transport: transportProp,
  analysisClient: clientProp,
  separationClient: separationClientProp,
  createPcmLoader: pcmFactoryProp,
  autosaveDelayMs = 900,
  separationPollIntervalMs = 400,
}: AppProps) {
  const [api] = useState<ShellApi>(() => apiProp ?? createShellApi());
  const [transport] = useState<ShellTransport>(
    () =>
      transportProp ??
      createShellTransport((project) => createLocalStudioRuntime(project)),
  );
  const [analysisClient] = useState<AnalysisJobClient>(
    () => clientProp ?? createAnalysisJobClient(),
  );
  const [separationClient] = useState<SeparationJobClient>(
    () => separationClientProp ?? createSeparationJobClient(),
  );
  const [placeholderRuntime] = useState(() => createLocalStudioRuntime());
  const [runtime, setRuntime] = useState<StudioRuntime | null>(null);
  const active = runtime ?? placeholderRuntime;
  const playerState = usePlayerState(active.player);
  const mixerState = useMixerState(active.mixer);
  const practiceState = usePracticeState(active.practice);

  const [project, setProject] = useState<StudioProject | null>(null);
  const [lanes, setLanes] = useState<Lane[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [snapMode, setSnapMode] = useState<SnapMode>("bar");
  const [viewport, setViewport] = useState<Viewport>(() =>
    fitViewport(0, VIEW_WIDTH),
  );
  const [selection, setSelection] = useState<Selection | null>(null);
  const [follow, setFollow] = useState(true);
  const [message, setMessage] = useState(
    "Choose a recording from the library.",
  );
  const [tone, setTone] = useState<"info" | "error">("info");
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [separation, setSeparation] = useState<{
    running: boolean;
    progress: number;
    stage: string;
    error: string | null;
  }>({ running: false, progress: 0, stage: "", error: null });
  const revisionRef = useRef(1);
  const hydratedRef = useRef(false);
  const openTokenRef = useRef(0);
  const sectionsRef = useRef<Section[]>([]);
  const projectRef = useRef<StudioProject | null>(null);
  const runtimeRef = useRef<StudioRuntime | null>(null);
  const separationAbortRef = useRef<AbortController | null>(null);
  const separationJobRef = useRef<SeparationJobState | null>(null);
  sectionsRef.current = sections;
  projectRef.current = project;
  runtimeRef.current = runtime;

  const pcmLoaderFor = useCallback(
    (projectId: string): PcmLoader =>
      pcmFactoryProp
        ? pcmFactoryProp(projectId)
        : createRangedPcmLoader({ projectId }),
    [pcmFactoryProp],
  );

  useEffect(() => {
    if (runtime === null || runtime.subscribeNotice === undefined) {
      setNotice(null);
      return;
    }
    return runtime.subscribeNotice(setNotice);
  }, [runtime]);

  const durationSeconds = project?.durationSeconds ?? 0;
  const fitted = useMemo(
    () => fitViewport(durationSeconds, VIEW_WIDTH),
    [durationSeconds],
  );
  const grid = useMemo(() => sectionGrid(project), [project]);
  const pcmLoader = useMemo(
    () => (project === null ? null : pcmLoaderFor(project.id)),
    [project, pcmLoaderFor],
  );
  const mixerStems = useMemo(() => {
    const fromProject = (project?.stems ?? []).map((stem) => ({
      id: stem.id,
      name: stem.name,
      role: stem.role,
    }));
    if (fromProject.length > 0) {
      return [{ id: "mix", name: "Mix", role: "mix" }, ...fromProject];
    }
    return Object.keys(mixerState)
      .filter((channelId) => channelId !== "mix")
      .map((channelId) => ({
        id: channelId,
        name: titleCase(channelId),
        role: channelId,
      }));
  }, [project, mixerState]);

  const openProject = useCallback(
    async (projectId: string) => {
      setTone("info");
      setMessage(`Opening ${projectId}…`);
      const token = openTokenRef.current + 1;
      openTokenRef.current = token;
      try {
        const next = await api.openProject(projectId);
        const peaks = await api.fetchPeaks(next.asset.id);
        const opened = await transport.open(next, next.analysis);
        if (token !== openTokenRef.current) {
          return;
        }
        revisionRef.current = next.revision;
        hydratedRef.current = false;
        setProject(next);
        setLanes([{ id: next.asset.id, name: "Mix", peaks }]);
        setSections(next.sections);
        setSnapMode("bar");
        setSelection(null);
        setFollow(true);
        setViewport(fitViewport(next.durationSeconds, VIEW_WIDTH));
        setRuntime(opened);
        setSaveState("idle");
        setTone("info");
        setMessage(`Loading ${next.title}…`);
        void (async () => {
          try {
            await opened.ready;
            if (token !== openTokenRef.current) {
              return;
            }
            applyRestoredState(opened, next);
            hydratedRef.current = true;
            setTone("info");
            setMessage(`Loaded ${next.title}`);
          } catch (error) {
            if (token !== openTokenRef.current) {
              return;
            }
            setTone("error");
            setMessage(errorMessage(error));
          }
        })();
      } catch (error) {
        if (isAbort(error) || token !== openTokenRef.current) {
          return;
        }
        hydratedRef.current = false;
        setRuntime(null);
        setProject(null);
        setLanes([]);
        setSections([]);
        setTone("error");
        setMessage(errorMessage(error));
      }
    },
    [api, transport],
  );

  const handleAnalyzed = useCallback(
    (snapshot: AnalysisSnapshot) => {
      const player = active.player;
      player.updateGrid?.({
        bpm: snapshot.bpm ?? 120,
        bpb: snapshot.bpb,
        beatsSeconds: snapshot.beats,
        offsetSeconds: snapshot.beats[0] ?? 0,
      });
      // Analysis never shrinks the recording, but a shorter duration (or a
      // future re-import) must clamp an existing loop rather than delete it.
      const before = player.getState();
      const clampedLoop = clampLoopRangeToDuration(
        before.loopRange,
        before.durationSeconds,
      );
      if (
        clampedLoop !== null &&
        (before.loopRange === null ||
          clampedLoop.startSeconds !== before.loopRange.startSeconds ||
          clampedLoop.endSeconds !== before.loopRange.endSeconds)
      ) {
        player.setLoopRange(clampedLoop);
        player.setLoopEnabled(before.loopEnabled);
      } else if (before.loopRange !== null && clampedLoop === null) {
        player.setLoopRange(null);
      }
      setProject((current) => {
        if (current === null) {
          return current;
        }
        return {
          ...current,
          analysis: snapshot,
          chords: snapshot.chords,
          beats: snapshot.beats,
          bars: snapshot.bars,
          bpb: snapshot.bpb,
          key: snapshot.key,
          grid: {
            bpm: snapshot.bpm ?? current.grid?.bpm ?? 120,
            meter: {
              numerator: snapshot.bpb,
              denominator: current.grid?.meter.denominator ?? 4,
            },
            offsetSeconds:
              snapshot.beats[0] ?? current.grid?.offsetSeconds ?? 0,
          },
        };
      });
      setTone("info");
      setMessage("Analysis complete");
    },
    [active.player],
  );

  const handleSeparate = useCallback(async () => {
    if (project === null || separation.running) {
      return;
    }
    const separationProjectId = project.id;
    const controller = new AbortController();
    separationAbortRef.current?.abort();
    separationAbortRef.current = controller;
    setSeparation({
      running: true,
      progress: 0,
      stage: "Queued",
      error: null,
    });
    setTone("info");
    setMessage("Separating stems…");
    try {
      const job = await runSeparationJob(separationClient, project.id, {
        pollIntervalMs: separationPollIntervalMs,
        signal: controller.signal,
        onUpdate: (state) => {
          if (controller.signal.aborted) {
            return;
          }
          separationJobRef.current = state;
          setSeparation({
            running: true,
            progress: Math.min(1, Math.max(0, state.progress)),
            stage: state.message,
            error: null,
          });
        },
      });
      separationJobRef.current = job;
      if (projectRef.current?.id !== separationProjectId) {
        setSeparation({
          running: false,
          progress: 0,
          stage: "",
          error: null,
        });
        return;
      }
      // Capture at activation time so a session that kept playing through a
      // long separation resumes at its current position and settings.
      const snapshot = captureStudioRuntime(runtimeRef.current ?? active);
      const preservedSections = sectionsRef.current;
      setSeparation((current) => ({
        ...current,
        progress: 1,
        stage: "Activating stems…",
      }));
      const refreshed = await api.openProject(project.id);
      if (controller.signal.aborted) {
        return;
      }
      const opened = await transport.open(refreshed, refreshed.analysis);
      if (controller.signal.aborted) {
        opened.dispose?.();
        return;
      }
      revisionRef.current = refreshed.revision;
      setProject(refreshed);
      setSections(preservedSections);
      setRuntime(opened);
      await opened.ready;
      if (controller.signal.aborted) {
        return;
      }
      applyStudioRuntimeSnapshot(opened, snapshot, {
        resumePlayback: snapshot.wasPlaying,
      });
      if (refreshed.stems.length > 0) {
        opened.mixer.setMuted("mix", true);
      }
      setSeparation({
        running: false,
        progress: 0,
        stage: "",
        error: null,
      });
      setTone("info");
      setMessage("Stems ready");
    } catch (error) {
      if (isAbort(error) || controller.signal.aborted) {
        return;
      }
      const detail = errorMessage(error);
      setSeparation((current) => ({
        ...current,
        running: false,
        error: detail,
      }));
      setTone("error");
      setMessage(detail);
    } finally {
      if (separationAbortRef.current === controller) {
        separationAbortRef.current = null;
      }
    }
  }, [
    project,
    separation.running,
    active,
    api,
    transport,
    separationClient,
    separationPollIntervalMs,
  ]);

  const handleCancelSeparation = useCallback(() => {
    const job = separationJobRef.current;
    separationAbortRef.current?.abort();
    separationAbortRef.current = null;
    if (job !== null) {
      void separationClient.cancel(job.id).catch(() => undefined);
    }
    setSeparation({
      running: false,
      progress: 0,
      stage: "",
      error: null,
    });
    setTone("info");
    setMessage("Separation cancelled");
  }, [separationClient]);

  useEffect(
    () => () => {
      separationAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (
      project === null ||
      runtime === null ||
      !hydratedRef.current ||
      autosaveDelayMs <= 0 ||
      playerState.status === "playing" ||
      playerState.status === "loading"
    ) {
      return;
    }
    const bars =
      project.bars.length > 0
        ? project.bars
        : barTimesFromGrid(
            project.beats,
            [],
            project.analysis?.bpm ?? project.grid?.bpm ?? null,
            project.bpb,
            project.grid?.offsetSeconds ?? 0,
            project.durationSeconds,
          );
    const timer = setTimeout(() => {
      const state = buildServerState({
        sections,
        bars,
        sampleRate: project.asset.sampleRate,
        positionSeconds: playerState.positionSeconds,
        loopRange: playerState.loopRange,
        practice: practiceState,
        mixer: mixerState,
      });
      setSaveState("saving");
      void api
        .saveState(project.id, state, revisionRef.current)
        .then((revision) => {
          revisionRef.current = revision;
          setSaveState("saved");
        })
        .catch((error) => {
          if (isAbort(error)) {
            return;
          }
          setSaveState("error");
        });
    }, autosaveDelayMs);
    return () => clearTimeout(timer);
  }, [
    project,
    runtime,
    sections,
    practiceState,
    mixerState,
    playerState.loopRange,
    playerState.status,
    Math.floor(playerState.positionSeconds),
    api,
    autosaveDelayMs,
  ]);

  const handleSeek = useCallback(
    (seconds: number) => {
      active.player.seek(seconds);
    },
    [active.player],
  );
  const handleTogglePlay = useCallback(() => {
    active.player.toggle();
  }, [active.player]);
  const handleToggleFollow = useCallback(() => {
    setFollow((value) => !value);
  }, []);
  const handleLoopSection = useCallback((section: Section) => {
    setMessage(`Looping ${section.name}`);
  }, []);

  const zoomIn = useCallback(() => {
    setViewport((current) =>
      zoomViewport(current, durationSeconds, VIEW_WIDTH, 1.5, VIEW_WIDTH / 2),
    );
  }, [durationSeconds]);
  const zoomOut = useCallback(() => {
    setViewport((current) =>
      zoomViewport(
        current,
        durationSeconds,
        VIEW_WIDTH,
        1 / 1.5,
        VIEW_WIDTH / 2,
      ),
    );
  }, [durationSeconds]);
  const fit = useCallback(() => {
    setViewport(fitViewport(durationSeconds, VIEW_WIDTH));
  }, [durationSeconds]);
  const zoomSelection = useCallback(() => {
    if (selection === null) {
      return;
    }
    setViewport(
      zoomViewportToSelection(selection, durationSeconds, VIEW_WIDTH),
    );
  }, [durationSeconds, selection]);

  const zoomPercent = Math.round(
    (fitted.secondsPerPixel / viewport.secondsPerPixel) * 100,
  );
  const selectionText =
    selection !== null && hasSelection(selection)
      ? `selection ${formatPosition(selection.startSeconds)}–${formatPosition(
          selection.endSeconds,
        )}`
      : "no selection";
  const keyLabel = project?.analysis?.key ?? project?.key ?? null;
  const bpm = project?.analysis?.bpm ?? project?.grid?.bpm ?? null;
  const bpb = project?.analysis?.bpb ?? project?.bpb ?? 4;
  const player: StudioPlayer = active.player;
  const transportNotice = notice ?? playerState.error;

  return (
    <div className="studio">
      <header className="studio-header">
        <div className="studio-heading">
          <h1>Bass practice studio</h1>
          <p
            className={`status-line status-${tone}`}
            data-testid="status-line"
            role={tone === "error" ? "alert" : "status"}
          >
            {message}
          </p>
        </div>
        <dl className="readouts">
          <div>
            <dt>Track</dt>
            <dd data-testid="project-title">
              {project?.title ?? "No project"}
            </dd>
          </div>
          <div>
            <dt>Key</dt>
            <dd data-testid="key-readout">{keyLabel ?? "—"}</dd>
          </div>
          <div>
            <dt>BPM</dt>
            <dd data-testid="bpm-readout">
              {bpm !== null ? `${Math.round(bpm * 10) / 10} · ${bpb}/4` : "—"}
            </dd>
          </div>
        </dl>
      </header>

      <main className="studio-main">
        <LibraryPanel
          api={api}
          onOpen={(projectId) => {
            void openProject(projectId);
          }}
          activeProjectId={project?.id ?? null}
        />

        <div className="studio-column">
          <section className="stage" aria-label="Waveform stage">
            <div className="stage-toolbar">
              <button type="button" aria-label="Zoom in" onClick={zoomIn}>
                +
              </button>
              <button type="button" aria-label="Zoom out" onClick={zoomOut}>
                −
              </button>
              <button type="button" aria-label="Fit" onClick={fit}>
                Fit
              </button>
              <button
                type="button"
                aria-label="Zoom to selection"
                onClick={zoomSelection}
                disabled={selection === null || !hasSelection(selection)}
              >
                Zoom to selection
              </button>
              <button
                type="button"
                aria-label="Follow playhead"
                aria-pressed={follow}
                onClick={handleToggleFollow}
              >
                Follow
              </button>
              {transportNotice !== null && (
                <span
                  className="stage-notice"
                  data-testid="transport-notice"
                  role="status"
                >
                  {transportNotice}
                </span>
              )}
            </div>

            <div className="timeline" style={{ width: VIEW_WIDTH }}>
              <TimeRuler
                viewport={viewport}
                widthPx={VIEW_WIDTH}
                grid={project?.grid ?? null}
                positionSeconds={playerState.positionSeconds}
                onSeek={handleSeek}
              />
              {lanes.length === 0 ? (
                <p className="stage-empty">
                  Open a recording to see its waveform.
                </p>
              ) : (
                lanes.map((lane) => (
                  <WaveformPane
                    key={lane.id}
                    lane={lane}
                    viewport={viewport}
                    durationSeconds={durationSeconds}
                    selection={selection}
                    positionSeconds={playerState.positionSeconds}
                    playing={playerState.status === "playing"}
                    follow={follow}
                    widthPx={VIEW_WIDTH}
                    onViewportChange={setViewport}
                    onSelectionChange={setSelection}
                    onSeek={handleSeek}
                    onTogglePlay={handleTogglePlay}
                    onToggleFollow={handleToggleFollow}
                  />
                ))
              )}
              {project !== null && pcmLoader !== null && (
                <SpectrogramPane
                  projectId={project.id}
                  viewport={viewport}
                  widthPx={VIEW_WIDTH}
                  sampleRate={project.asset.sampleRate}
                  positionSeconds={playerState.positionSeconds}
                  loadPcm={pcmLoader}
                  defaultCollapsed
                />
              )}
            </div>
          </section>

          {project !== null && (
            <>
              <ChordRibbon
                chords={project.chords}
                viewport={viewport}
                widthPx={VIEW_WIDTH}
                positionSeconds={playerState.positionSeconds}
                onSeek={handleSeek}
              />

              <SectionLane
                sections={sections}
                grid={grid}
                viewport={viewport}
                widthPx={VIEW_WIDTH}
                durationSeconds={durationSeconds}
                positionSeconds={playerState.positionSeconds}
                snapMode={snapMode}
                onSnapModeChange={setSnapMode}
                selection={selection}
                onChange={setSections}
                onLoop={handleLoopSection}
                onSeek={handleSeek}
                player={player}
              />

              <div className="panel-grid">
                <AnalysisPanel
                  projectId={project.id}
                  analysis={project.analysis}
                  client={analysisClient}
                  onAnalyzed={handleAnalyzed}
                />
                <MixerPanel
                  stems={mixerStems}
                  controller={active.mixer}
                  separation={{
                    hasStems: project.stems.length > 0,
                    running: separation.running,
                    progress: separation.progress,
                    stage: separation.stage,
                    error: separation.error,
                    onSeparate: () => {
                      void handleSeparate();
                    },
                    onCancel: handleCancelSeparation,
                  }}
                />
                <PracticePanel
                  controller={active.practice}
                  snapMode={snapMode}
                  onSnapModeChange={setSnapMode}
                />
              </div>
            </>
          )}
        </div>
      </main>

      <TransportPanel
        player={player}
        grid={project?.grid ?? null}
        selection={selection}
      />

      <footer className="status-line-footer">
        <span className="status-detail" data-testid="status-detail">
          <span>{formatPosition(playerState.positionSeconds)}</span>
          <span>{selectionText}</span>
          <span>{`zoom ${zoomPercent}%`}</span>
          <span data-testid="save-status">
            {saveState === "idle"
              ? ""
              : saveState === "saved"
                ? "saved"
                : saveState === "saving"
                  ? "saving…"
                  : "save failed"}
          </span>
        </span>
      </footer>
    </div>
  );
}
