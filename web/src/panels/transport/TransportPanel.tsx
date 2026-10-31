import { formatBarBeat, formatPosition, formatSpeed } from "../../state/format";
import {
  SPEED_OPTIONS,
  type PlaybackStatus,
  type StudioPlayer,
} from "../../state/player";
import type { Grid } from "../../state/types";
import { usePlayerState } from "../../state/usePlayerState";
import { hasSelection, type Selection } from "../waveform/selection";

export interface TransportPanelProps {
  player: StudioPlayer;
  grid?: Grid | null;
  selection?: Selection | null;
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
  grid = null,
  selection = null,
}: TransportPanelProps) {
  const state = usePlayerState(player);
  const playing = state.status === "playing";
  const canPlay = state.durationSeconds > 0 && state.status !== "loading";
  const barBeat = formatBarBeat(state.positionSeconds, grid);
  const speeds = SPEED_OPTIONS.includes(
    state.speed as (typeof SPEED_OPTIONS)[number],
  )
    ? [...SPEED_OPTIONS]
    : [...SPEED_OPTIONS, state.speed].sort((a, b) => a - b);

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

      <div className="transport-readout">
        <span
          className="transport-position"
          role="timer"
          aria-label="Position"
          data-testid="transport-position"
        >
          {formatPosition(state.positionSeconds)} /{" "}
          {formatPosition(state.durationSeconds)}
        </span>
        {barBeat !== null && (
          <span className="transport-bar-beat" data-testid="transport-bar-beat">
            {barBeat}
          </span>
        )}
        <span className="transport-status" data-testid="transport-status">
          {STATUS_LABELS[state.status]}
        </span>
      </div>

      <label className="speed-control">
        Speed
        <select
          aria-label="Speed"
          value={state.speed}
          onChange={(event) => player.setSpeed(Number(event.target.value))}
        >
          {speeds.map((speed) => (
            <option key={speed} value={speed}>
              {formatSpeed(speed)}
            </option>
          ))}
        </select>
      </label>

      {state.error !== null && (
        <p className="transport-error" role="alert">
          {state.error}
        </p>
      )}
    </section>
  );
}
