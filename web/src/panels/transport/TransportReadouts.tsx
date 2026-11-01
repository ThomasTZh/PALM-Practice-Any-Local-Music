import { formatBarBeat, formatPosition } from "../../state/format";
import type { StudioPlayer } from "../../state/player";
import type { Grid } from "../../state/types";
import { usePlayerState } from "../../state/usePlayerState";

export interface TransportReadoutsProps {
  player: StudioPlayer;
  grid?: Grid | null;
}

/** Position and bar/beat readouts shown at the right of the stage toolbar. */
export function TransportReadouts({
  player,
  grid = null,
}: TransportReadoutsProps) {
  const state = usePlayerState(player);
  const barBeat = formatBarBeat(state.positionSeconds, grid);

  return (
    <div className="transport-readouts" aria-label="Playback position">
      <span
        className="transport-position"
        role="timer"
        aria-label="Position"
        data-testid="transport-position"
      >
        {formatPosition(state.positionSeconds)} /{" "}
        {formatPosition(state.durationSeconds)}
      </span>
      <span className="transport-bar-beat" data-testid="transport-bar-beat">
        {barBeat ?? ""}
      </span>
    </div>
  );
}
