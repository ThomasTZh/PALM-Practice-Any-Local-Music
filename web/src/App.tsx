import { useCallback, useEffect, useMemo, useState } from "react";

import { createStudioApi, type StudioApi } from "./api/client";
import { LibraryPanel } from "./panels/library/LibraryPanel";
import { TimeRuler } from "./panels/ruler/TimeRuler";
import { TransportPanel } from "./panels/transport/TransportPanel";
import { WaveformPane, type Lane } from "./panels/waveform/WaveformPane";
import { hasSelection, type Selection } from "./panels/waveform/selection";
import {
  fitViewport,
  zoomToSelection as zoomViewportToSelection,
  zoomViewport,
  type Viewport,
} from "./panels/waveform/viewport";
import { formatPosition } from "./state/format";
import { createLocalPlayer } from "./state/localPlayer";
import type { StudioPlayer } from "./state/player";
import type { Project } from "./state/types";
import { usePlayerState } from "./state/usePlayerState";

/** The stage is a fixed logical width; CSS scales it down on small screens. */
const VIEW_WIDTH = 960;

export interface AppProps {
  api?: StudioApi;
  player?: StudioPlayer;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface LaneSource {
  id: string;
  name: string;
  peaksAssetId: string;
}

function laneSources(project: Project): LaneSource[] {
  if (project.stems.length > 0) {
    return project.stems.map((stem) => ({
      id: stem.id,
      name: stem.name,
      peaksAssetId: stem.peaksAssetId,
    }));
  }
  return [
    {
      id: project.asset.id,
      name: "Mix",
      peaksAssetId: project.asset.id,
    },
  ];
}

/**
 * Studio shell: library, shared ruler, one waveform lane per stem (or the mix),
 * transport and a status line. The shell owns only view state; playback lives
 * behind the `StudioPlayer` seam and project data behind the API client.
 */
export function App({ api: apiProp, player: playerProp }: AppProps) {
  const [api] = useState<StudioApi>(() => apiProp ?? createStudioApi());
  const [fallbackPlayer] = useState(() => createLocalPlayer());
  const player = playerProp ?? fallbackPlayer;
  const playerState = usePlayerState(player);

  const [project, setProject] = useState<Project | null>(null);
  const [lanes, setLanes] = useState<Lane[]>([]);
  const [viewport, setViewport] = useState<Viewport>(() =>
    fitViewport(0, VIEW_WIDTH),
  );
  const [selection, setSelection] = useState<Selection | null>(null);
  const [follow, setFollow] = useState(true);
  const [message, setMessage] = useState(
    "Choose a recording from the library.",
  );
  const [tone, setTone] = useState<"info" | "error">("info");

  useEffect(
    () => () => {
      if (playerProp === undefined) {
        fallbackPlayer.dispose();
      }
    },
    [fallbackPlayer, playerProp],
  );

  const durationSeconds = project?.durationSeconds ?? 0;
  const fitted = useMemo(
    () => fitViewport(durationSeconds, VIEW_WIDTH),
    [durationSeconds],
  );

  const openProject = useCallback(
    async (projectId: string) => {
      setTone("info");
      setMessage(`Opening ${projectId}…`);
      try {
        const next = await api.openProject(projectId);
        const sources = laneSources(next);
        const peaks = await Promise.all(
          sources.map((source) => api.fetchPeaks(source.peaksAssetId)),
        );
        setProject(next);
        setLanes(
          sources.map((source, index) => ({
            id: source.id,
            name: source.name,
            peaks: peaks[index],
          })),
        );
        player.setDuration(next.durationSeconds);
        player.seek(0);
        player.setLoopRange(null);
        player.setLoopEnabled(false);
        player.setSpeed(1);
        setSelection(null);
        setFollow(true);
        setViewport(fitViewport(next.durationSeconds, VIEW_WIDTH));
        setTone("info");
        setMessage(`Loaded ${next.title}`);
      } catch (error) {
        setTone("error");
        setMessage(errorMessage(error));
      }
    },
    [api, player],
  );

  const handleSeek = useCallback(
    (seconds: number) => {
      player.seek(seconds);
    },
    [player],
  );
  const handleTogglePlay = useCallback(() => {
    player.toggle();
  }, [player]);
  const handleToggleFollow = useCallback(() => {
    setFollow((value) => !value);
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
            <dd data-testid="key-readout">{project?.key ?? "—"}</dd>
          </div>
          <div>
            <dt>BPM</dt>
            <dd data-testid="bpm-readout">
              {project?.grid
                ? `${Math.round(project.grid.bpm)} ${project.grid.meter.numerator}/${project.grid.meter.denominator}`
                : "—"}
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
          </div>
        </section>
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
        </span>
      </footer>
    </div>
  );
}
