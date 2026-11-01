import type { ReactNode } from "react";

import { type PlaybackStatus, type StudioPlayer } from "../../state/player";
import { usePlayerState } from "../../state/usePlayerState";
import { hasSelection, type Selection } from "../waveform/selection";

export interface TransportPanelProps {
  player: StudioPlayer;
  selection?: Selection | null;
  projectTitle?: string | null;
  keyLabel?: string | null;
  bpm?: number | null;
  bpb?: number | null;
  /** Practice controls rendered in the bottom bar's left zone. */
  practice?: ReactNode;
}

const STATUS_LABELS: Record<PlaybackStatus, string> = {
  idle: "No audio loaded",
  loading: "Loading audio…",
  ready: "Ready",
  playing: "Playing",
  paused: "Paused",
  ended: "Ended",
  error: "Playback error",
};

/**
 * Transport controls driven entirely by the `StudioPlayer` seam. Every button
 * reflects the current player state and asks the player to change it; the
 * panel holds no playback state of its own.
 */
export function TransportPanel({
  player,
  selection = null,
  projectTitle = null,
  keyLabel = null,
  bpm = null,
  bpb = null,
  practice = null,
}: TransportPanelProps) {
  const state = usePlayerState(player);
  const playing = state.status === "playing";
  const canPlay = state.durationSeconds > 0 && state.status !== "loading";
  const bpmText =
    bpm === null ? "—" : `${Math.round(bpm * 10) / 10} · ${bpb ?? 4}/4`;

  function handleLoop(): void {
    if (state.loopEnabled) {
      player.setLoopEnabled(false);
      return;
    }
    if (state.loopRange === null) {
      const range =
        selection !== null && hasSelection(selection)
          ? selection
          : { startSeconds: 0, endSeconds: state.durationSeconds };
      player.setLoopRange(range);
    }
    player.setLoopEnabled(true);
  }

  return (
    <section className="transport" aria-label="Transport">
      <div
        className="transport-practice-zone"
        data-testid="transport-practice-zone"
      >
        {practice}
      </div>

      <div className="transport-center" data-testid="transport-center">
        <div className="transport-buttons">
          <button
            type="button"
            className="transport-button transport-return"
            aria-label="Return to start"
            onClick={() => player.seek(0)}
          >
            ⏮
          </button>
          <button
            type="button"
            className="transport-button transport-toggle"
            data-testid="transport-toggle"
            aria-label={playing ? "Pause" : "Play"}
            disabled={!canPlay}
            onClick={() => player.toggle()}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            className="transport-button transport-loop"
            aria-label="Loop"
            aria-pressed={state.loopEnabled}
            onClick={handleLoop}
          >
            Loop
          </button>
        </div>
        <span
          className="transport-status visually-hidden"
          data-testid="transport-status"
        >
          {STATUS_LABELS[state.status]}
        </span>
      </div>

      <dl className="transport-meta" aria-label="Track details">
        <div>
          <dt>Track</dt>
          <dd data-testid="project-title">{projectTitle ?? "No project"}</dd>
        </div>
        <div>
          <dt>Key</dt>
          <dd data-testid="key-readout">{keyLabel ?? "—"}</dd>
        </div>
        <div>
          <dt>BPM</dt>
          <dd data-testid="bpm-readout">{bpmText}</dd>
        </div>
      </dl>

      {state.error !== null && (
        <p className="transport-error" role="alert">
          {state.error}
        </p>
      )}
    </section>
  );
}
